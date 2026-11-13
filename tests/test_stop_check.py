import contextlib
import os
import pathlib
import shutil
import socket
import stat
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import project_config  # noqa: E402
import stop_check  # noqa: E402
from hook_runner import run_hook, write_config  # noqa: E402

OPT_IN = {"handback": {"agents": ["acme-*"]}}
FULL = "Status: PASS. Done. Files changed: a.ts. Verification level used: L1, tests green. Retro: worked tests / exposed none / rule none."
STATUS_HINT, LEVEL_HINT, RETRO_HINT = "a status: PASS, ISSUES or BLOCKED", "the verification level used", "a one line retro"


def stop(message, config=OPT_IN, agent="acme-web", active=False):
    """The block reason for a hand-back, None when the agent may stop. A None argument leaves that field out of the hook input."""
    data = {"agent_type": agent, "last_assistant_message": message, "stop_hook_active": active}
    return stop_check.judge({k: v for k, v in data.items() if v is not None}, config)


class DefaultItems(unittest.TestCase):
    def test_the_default_items_are_a_status_a_verification_level_and_a_retro_in_that_order(self):
        self.assertEqual([item["id"] for item in project_config.DEFAULTS["handback"]["required"]], ["status", "verification", "retro"])
        self.assertEqual([item["hint"] for item in project_config.DEFAULTS["handback"]["required"]], [STATUS_HINT, LEVEL_HINT, RETRO_HINT + " (worked / exposed / rule)"])

    def test_a_hand_back_with_a_status_a_verification_level_and_a_retro_may_stop(self):
        for message in [FULL, "PASS verified at L2. retro: x.", "ISSUES. Verified. Retro line: x", "L3 and RETRO and BLOCKED", "Status: BLOCKED. Checked at L0. Retro: none."]:
            self.assertIsNone(stop(message), message)

    def test_a_hand_back_that_misses_one_is_blocked_with_its_hint(self):
        cases = [("PASS. Verification L1.", {"retro"}), ("PASS. Retro: x.", {"verification"}), ("PASS. Verified. nothing else", {"retro"}),
                 ("Verification L1. Retro: x.", {"status"}), ("Done. Verified. Retro: x.", {"status"}),
                 ("PASS. verification: l2. retro: x.", set()),  # "verif" is enough, so the lowercase l2 does not matter
                 ("PASS, L6, retro.", {"verification"}), ("PASS, FL1, retro.", {"verification"}), ("Done, L1, retro.", {"status"}), ("Done, L6, retro.", {"status", "verification"})]
        for message, missing in cases:
            reason = stop(message)
            if not missing:
                self.assertIsNone(reason, message)
                continue
            self.assertEqual(STATUS_HINT in reason, "status" in missing, message)
            self.assertEqual(LEVEL_HINT in reason, "verification" in missing, message)
            self.assertEqual(RETRO_HINT in reason, "retro" in missing, message)

    def test_a_hand_back_that_misses_all_lists_all_hints_in_order(self):
        for message in ["Done.", "", "   "]:
            reason = stop(message)
            self.assertEqual(reason, f"Your hand-back is missing: {STATUS_HINT}; {LEVEL_HINT}; {RETRO_HINT} (worked / exposed / rule). "
                                     "Fix this in your final message; this check blocks only once.", message)

    def test_the_level_must_be_a_whole_word_and_case_sensitive(self):
        self.assertIn("verification", stop("PASS retro. level L1x"))
        self.assertIn("verification", stop("PASS retro. level l1"))
        self.assertIsNone(stop("PASS retro. (L1)"))

    def test_the_status_is_one_of_three_whole_words_in_capitals(self):
        for status in ["Status: PASS", "Status: ISSUES", "Status: BLOCKED", "PASS", "(BLOCKED)", "Status: PASS | ISSUES | BLOCKED", "status: PASS.", "ISSUES;", "x-PASS-y"]:
            self.assertIsNone(stop(f"{status}. verified, retro"), status)
        for status in ["Status: pass", "Status: Blocked", "passed", "PASSWORD", "BYPASS", "ISSUE", "UNBLOCKED", "NOISSUES", "PASS_", "Status:", ""]:
            self.assertIn(STATUS_HINT, stop(f"{status}. verified, retro") or "", status)

    def test_a_project_that_only_opted_in_gets_the_status_item_and_one_with_its_own_list_does_not(self):
        self.assertIn(STATUS_HINT, stop("Verified at L1. Retro: x."))  # the default list changed in 0.3.0
        own = {"handback": {"agents": ["acme-*"], "required": [{"id": "retro", "pattern": "(?i:retro)", "hint": RETRO_HINT}]}}
        self.assertIsNone(stop("Verified at L1. Retro: x.", own))


@contextlib.contextmanager
def listening():
    """A real TCP socket that listens on an ephemeral port of 127.0.0.1; yields the port."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen()
        yield sock.getsockname()[1]


def closed_port():
    """A port that nothing listens on: an ephemeral one, released right away."""
    with listening() as port:
        return port


def with_ports(ports, hint=None):
    return {"handback": {"agents": ["acme-*"]}, "resources": {"ports": ports, **({"hint": hint} if hint else {})}}


class ResourceSettings(unittest.TestCase):
    def test_the_defaults_name_no_port_and_no_hint(self):
        self.assertEqual(project_config.DEFAULTS["resources"], {"ports": [], "hint": ""})
        self.assertEqual(project_config.get({"resources": {"ports": "5173", "hint": 7}}, "resources", "ports"), [])
        self.assertEqual(project_config.get({"resources": {"ports": "5173", "hint": 7}}, "resources", "hint"), "")

    def test_ports_are_ints_and_a_b_ranges_and_anything_else_is_skipped(self):
        self.assertEqual(stop_check.port_spec([5173, "5174-5179", " 9224 ", "54329-54329"]), ["5173", "5174-5179", "9224", "54329"])
        self.assertEqual(stop_check.port_spec([True, False, None, 0, -1, 65536, "x", "", "9-3", "1-2-3", "0-5", "1-65536", "9" * 5000, "1-" + "9" * 5000, ["5173"], 51.5]), [])
        self.assertEqual(stop_check.port_spec([]), [])


@unittest.skipUnless(shutil.which("lsof"), "the probe needs lsof")
class BusyPorts(unittest.TestCase):
    """A real socket and a real lsof: the check is whatever lsof says about this machine."""

    def test_a_listening_port_blocks_a_complete_hand_back_and_the_reason_names_the_port_and_the_hint(self):
        with listening() as port:
            reason = stop(FULL, with_ports([port], "stop the dev server and headless Chrome"))
            self.assertIn(f"port(s) {port} (stop the dev server and headless Chrome). Release them, or say in your hand-back why they are kept.", reason)
            self.assertIn("end it with your full hand-back again, not just the resource note", reason)
            self.assertNotIn("Your hand-back is missing", reason)
            self.assertIn(f"port(s) {port}. Release them", stop(FULL, with_ports([port])))  # no hint, no parentheses
        self.assertIsNone(stop(FULL, with_ports([port], "stop the dev server")))  # released

    def test_one_block_lists_the_missing_items_and_the_busy_ports(self):
        with listening() as port:
            reason = stop("Done.", with_ports([port]))
        self.assertIn(STATUS_HINT, reason)
        self.assertIn(LEVEL_HINT, reason)
        self.assertIn(f"port(s) {port}", reason)
        self.assertEqual(reason.count("this check blocks only once"), 1)

    def test_only_the_ports_that_listen_are_named_and_in_order(self):
        with listening() as first, listening() as second:
            low, high = sorted([first, second])
            gone = closed_port()
            reason = stop(FULL, with_ports([high, gone, low]))
            self.assertIn(f"port(s) {low}, {high}. Release", reason)
            self.assertNotIn(str(gone), reason)

    def test_a_range_and_a_port_written_as_a_string_are_probed_too(self):
        with listening() as port:
            self.assertIn(str(port), stop(FULL, with_ports([f"{port}-{port + 1}"])))
            self.assertIn(str(port), stop(FULL, with_ports([str(port)])))
            self.assertIn(str(port), stop(FULL, with_ports([f"{port - 1}-{port}"])))
            self.assertIsNone(stop(FULL, with_ports([True, "x", 70000, "9-3"])))  # invalid entries probe nothing
            self.assertIn(f"port(s) {port}", stop(FULL, with_ports([None, "x", port, 70000])))  # and do not hide a good one

    def test_it_blocks_once_and_only_for_the_agents_that_are_checked(self):
        with listening() as port:
            config = with_ports([port])
            self.assertIsNotNone(stop(FULL, config))
            self.assertIsNone(stop(FULL, config, active=True))
            self.assertIsNone(stop("", config, active=True))
            self.assertIsNone(stop(FULL, config, agent="Explore"))
            self.assertIsNone(stop(FULL, {**config, "handback": {"agents": []}}))
            self.assertIsNotNone(stop(FULL, config, agent="acme-docs"))

    def test_through_the_hook_as_claude_code_runs_it(self):
        with listening() as port, tempfile.TemporaryDirectory() as tmp:
            write_config(tmp, with_ports([port], "stop the dev server"))
            first = {"hook_event_name": "SubagentStop", "agent_type": "acme-web", "stop_hook_active": False, "last_assistant_message": FULL}
            out = run_hook("stop_check.py", first, tmp)
            self.assertEqual(set(out), {"decision", "reason"})
            self.assertEqual(out["decision"], "block")
            self.assertIn(f"port(s) {port} (stop the dev server)", out["reason"])
            self.assertIsNone(run_hook("stop_check.py", {**first, "stop_hook_active": True}, tmp))

    def test_without_lsof_the_resource_part_is_skipped_and_the_hand_back_part_still_blocks(self):
        with listening() as port, tempfile.TemporaryDirectory() as nowhere:
            config = with_ports([port])
            self.assertIsNotNone(stop(FULL, config))  # lsof is found here
            with mock.patch.dict(os.environ, {"PATH": nowhere}):
                self.assertIsNone(stop(FULL, config))
                reason = stop("Done.", config)
                self.assertIn(STATUS_HINT, reason)
                self.assertNotIn("Resources still running", reason)
            write_config(nowhere, config)
            first = {"agent_type": "acme-web", "stop_hook_active": False, "last_assistant_message": FULL}
            self.assertEqual(run_hook("stop_check.py", first, nowhere)["decision"], "block")
            self.assertIsNone(run_hook("stop_check.py", first, nowhere, env={"PATH": nowhere}))


class FakeLsof(unittest.TestCase):
    """The ways lsof can answer or fail, with a stand-in first on the PATH."""

    @contextlib.contextmanager
    def lsof(self, script):
        with tempfile.TemporaryDirectory() as folder:
            path = pathlib.Path(folder) / "lsof"
            path.write_text("#!/bin/sh\n" + script + "\n")
            path.chmod(path.stat().st_mode | stat.S_IXUSR)
            with mock.patch.dict(os.environ, {"PATH": folder + os.pathsep + os.environ["PATH"]}):
                yield path

    def test_it_asks_lsof_for_the_configured_ports_and_reads_ipv4_and_ipv6_listeners_only(self):
        output = ("COMMAND PID USER FD TYPE DEVICE SIZE/OFF NODE NAME\n"
                  "node 11 me 23u IPv4 0x1 0t0 TCP *:5173 (LISTEN)\n"
                  "node 11 me 24u IPv6 0x2 0t0 TCP [::1]:5174 (LISTEN)\n"
                  "Chrome 12 me 25u IPv4 0x3 0t0 TCP 127.0.0.1:9224 (LISTEN)\n"
                  "node 11 me 26u IPv4 0x4 0t0 TCP 127.0.0.1:5173->127.0.0.1:50000 (ESTABLISHED)")
        with self.lsof(f"echo \"$@\" > \"$0.args\"\ncat <<'EOF'\n{output}\nEOF") as path:
            ports = [5173, "5174-5179", "9224-9230"]
            self.assertEqual(stop_check.busy_ports(with_ports(ports)), [5173, 5174, 9224])
            self.assertIn("port(s) 5173, 5174, 9224 (stop the servers)", stop(FULL, with_ports(ports, "stop the servers")))
            self.assertEqual(pathlib.Path(f"{path}.args").read_text().split(), ["-nP", "-iTCP:5173,5174-5179,9224-9230", "-sTCP:LISTEN"])
            self.assertEqual(stop_check.busy_ports(with_ports([])), [])  # no port, no probe

    def test_a_probe_that_hangs_or_fails_is_skipped_within_the_time_limit(self):
        with self.lsof("echo 'node 1 me 3u IPv4 0x1 0t0 TCP *:5555 (LISTEN)'"):
            self.assertIn("port(s) 5555", stop(FULL, with_ports([5555])))  # the stand-in works when it behaves
        for broken in ["exec sleep 5", "echo 'lsof: no memory' >&2; exit 2", "exit 127", "echo garbage; exit 0", "kill -9 $$"]:
            with self.lsof(broken), mock.patch.object(stop_check, "PROBE_SECONDS", 0.3):
                started = time.monotonic()
                self.assertIsNone(stop(FULL, with_ports([5555])), broken)
                self.assertIn(STATUS_HINT, stop("Done.", with_ports([5555])), broken)
                self.assertLess(time.monotonic() - started, 3, broken)


class WhoIsChecked(unittest.TestCase):
    def test_no_agent_is_checked_until_the_project_opts_in(self):
        for config in [{}, {"handback": {}}, {"handback": {"agents": []}}]:
            self.assertIsNone(stop("", config), config)

    def test_only_agents_that_match_a_pattern_are_checked(self):
        config = {"handback": {"agents": ["acme-*", "Explore"]}}
        for agent in ["acme-web", "acme-docs", "Explore"]:
            self.assertIsNotNone(stop("x", config, agent), agent)
        for agent in ["general-purpose", "Plan", "explore", "my-acme-web", "", None]:
            self.assertIsNone(stop("x", config, agent), agent)

    def test_a_missing_or_non_text_hand_back_cannot_be_judged_and_may_stop(self):
        for message in [None, 5, ["x"], {"a": 1}]:
            data = {"agent_type": "acme-web", "last_assistant_message": message}
            self.assertIsNone(stop_check.judge(data, OPT_IN), message)
        self.assertIsNone(stop_check.judge({"agent_type": "acme-web"}, OPT_IN))


class BlocksOnce(unittest.TestCase):
    def test_an_agent_that_is_already_continuing_because_of_a_stop_hook_may_stop(self):
        self.assertIsNotNone(stop("nothing useful", active=False))
        self.assertIsNone(stop("nothing useful", active=True))
        self.assertIsNone(stop("", active=True))
        self.assertIsNotNone(stop("nothing useful", active=None))  # no field at all: a first stop

    def test_a_first_stop_is_blocked_and_the_second_one_is_not_through_the_hook(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_config(tmp, OPT_IN)
            first = {"hook_event_name": "SubagentStop", "agent_type": "acme-web", "stop_hook_active": False, "last_assistant_message": "Done."}
            second = {**first, "stop_hook_active": True}
            self.assertEqual(run_hook("stop_check.py", first, tmp)["decision"], "block")
            self.assertIsNone(run_hook("stop_check.py", second, tmp))
            self.assertIsNone(run_hook("stop_check.py", {**second, "last_assistant_message": FULL}, tmp))


class RequiredItems(unittest.TestCase):
    def test_the_project_replaces_the_required_items(self):
        config = {"handback": {"agents": ["acme-*"], "required": [{"id": "files", "pattern": "Files changed", "hint": "the list of files changed"}]}}
        self.assertIsNone(stop("Files changed: a.ts", config))
        self.assertIn("the list of files changed", stop("Done. Verified. Retro: x", config))
        self.assertEqual(stop("x", {"handback": {"agents": ["acme-*"], "required": []}}), None)

    def test_the_hint_falls_back_to_the_id_then_the_pattern(self):
        for item, shown in [({"id": "files", "pattern": "F"}, "files"), ({"pattern": "F+"}, "F+"), ({"id": "", "pattern": "F", "hint": ""}, "F"),
                            ({"id": "files", "pattern": "F", "hint": 7}, "7")]:
            reason = stop("x", {"handback": {"agents": ["*"], "required": [item]}})
            self.assertTrue(reason.startswith(f"Your hand-back is missing: {shown}. "), (item, reason))

    def test_a_pattern_is_a_regular_expression_searched_anywhere_in_the_text(self):
        def needs(pattern):
            return {"handback": {"agents": ["*"], "required": [{"pattern": pattern}]}}
        self.assertIsNone(stop("Done. Result: 3 passed (ok)", needs(r"Result: \d+ passed")))
        self.assertIsNotNone(stop("Done. Result: many passed", needs(r"Result: \d+ passed")))
        self.assertIsNotNone(stop("fine, OK", needs("ok")))  # case-sensitive unless the pattern starts with (?i)
        self.assertIsNone(stop("fine, OK", needs("(?i)ok")))
        multiline = {"handback": {"agents": ["*"], "required": [{"pattern": r"(?m)^Retro:"}]}}
        self.assertIsNone(stop("Done.\nRetro: x", multiline))
        self.assertIsNotNone(stop("Done. Retro: x", multiline))

    def test_broken_items_are_skipped_and_do_not_hide_a_valid_one(self):
        required = [5, None, "retro", ["x"], {"id": "x"}, {"pattern": 3}, {"pattern": None}, {"pattern": "("}, {"pattern": "[a-"},
                    {"id": "retro", "pattern": "Retro", "hint": "a retro"}]
        config = {"handback": {"agents": ["*"], "required": required}}
        self.assertEqual(stop("Done.", config), "Your hand-back is missing: a retro. Fix this in your final message; this check blocks only once.")
        self.assertIsNone(stop("Retro: x", config))

    def test_wrongly_typed_settings_are_read_as_the_defaults(self):
        self.assertIsNone(stop("", {"handback": {"agents": "acme-*"}}))  # not a list: nobody is opted in
        self.assertIsNone(stop("", {"handback": "acme-*"}))
        self.assertIsNotNone(stop("", {"handback": {"agents": [3, None, "acme-*"]}}))  # a bad entry is skipped
        self.assertIsNotNone(stop("x", {"handback": {"agents": ["acme-*"], "required": "retro"}}))  # the default items apply


class ExampleConfig(unittest.TestCase):
    def test_the_example_opts_the_demo_agents_in_with_valid_items(self):
        with tempfile.TemporaryDirectory() as tmp:
            (pathlib.Path(tmp) / ".claude").mkdir()
            (pathlib.Path(tmp) / ".claude" / "agent-steddy.json").write_text((ROOT / "examples" / "acme" / ".claude" / "agent-steddy.json").read_text())
            config = project_config.load(tmp)
        self.assertEqual(config["handback"]["agents"], ["acme-*"])
        self.assertEqual([item["id"] for item in config["handback"]["required"]][:3], ["status", "verification", "retro"])
        self.assertIsNone(stop(FULL + " Resources released: nothing started.", config))
        ports, hint = config["resources"]["ports"], config["resources"]["hint"]
        self.assertTrue(ports and hint)
        self.assertEqual(len(stop_check.port_spec(ports)), len(ports))  # every entry of the example is a valid port or range
        reason = stop("Done.", config)
        for hint in [item["hint"] for item in config["handback"]["required"]]:
            self.assertIn(hint, reason)
        self.assertIsNone(stop("Done.", config, agent="Explore"))


class Hook(unittest.TestCase):
    """The script as Claude Code runs it."""

    def decide(self, config, message, agent="acme-web", raw=None):
        data = {"hook_event_name": "SubagentStop", "agent_type": agent, "stop_hook_active": False, "last_assistant_message": message}
        with tempfile.TemporaryDirectory() as tmp:
            if config is not None:
                write_config(tmp, config)
            return run_hook("stop_check.py", data, tmp, raw)

    def test_blocks_with_a_top_level_decision(self):
        out = self.decide(OPT_IN, "Done.")
        self.assertEqual(set(out), {"decision", "reason"})
        self.assertEqual(out["decision"], "block")
        self.assertIn("verification level", out["reason"])
        self.assertIn("PASS, ISSUES or BLOCKED", out["reason"])
        self.assertIn("blocks only once", out["reason"])

    def test_lets_a_complete_hand_back_and_an_agent_that_is_not_opted_in_stop(self):
        self.assertIsNone(self.decide(OPT_IN, FULL))
        self.assertIsNone(self.decide(OPT_IN, "Done.", agent="Explore"))
        self.assertIsNone(self.decide(None, "Done."))

    def test_everything_fails_open_with_a_broken_config_or_broken_input(self):
        for config in [["not", "an", "object"], {"handback": 3}, {"handback": {"agents": 1, "required": 2}}]:
            self.assertIsNone(self.decide(config, "Done."), config)
        for raw in ["not json", "", "[]", "null"]:
            self.assertIsNone(self.decide(OPT_IN, "Done.", raw=raw), raw)


if __name__ == "__main__":
    unittest.main()
