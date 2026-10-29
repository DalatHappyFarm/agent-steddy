import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import project_config  # noqa: E402
import stop_check  # noqa: E402
from hook_runner import run_hook, write_config  # noqa: E402

OPT_IN = {"handback": {"agents": ["acme-*"]}}
FULL = "Done. Files changed: a.ts. Verification level used: L1, tests green. Retro: worked tests / exposed none / rule none."


def stop(message, config=OPT_IN, agent="acme-web", active=False):
    """The block reason for a hand-back, None when the agent may stop. A None argument leaves that field out of the hook input."""
    data = {"agent_type": agent, "last_assistant_message": message, "stop_hook_active": active}
    return stop_check.judge({k: v for k, v in data.items() if v is not None}, config)


class DefaultItems(unittest.TestCase):
    def test_a_hand_back_with_a_verification_level_and_a_retro_may_stop(self):
        for message in [FULL, "verified at L2. retro: x.", "Verified. Retro line: x", "L3 and RETRO", "Checked at L0. Retro: none."]:
            self.assertIsNone(stop(message), message)

    def test_a_hand_back_that_misses_one_is_blocked_with_its_hint(self):
        cases = [("Done. Verification L1.", {"retro"}), ("Done. Retro: x.", {"verification"}), ("Done. Verified. nothing else", {"retro"}),
                 ("verification: l2. retro: x.", set()),  # "verif" is enough, so the lowercase l2 does not matter
                 ("Done, L6, retro.", {"verification"}), ("Done, FL1, retro.", {"verification"})]
        for message, missing in cases:
            reason = stop(message)
            if not missing:
                self.assertIsNone(reason, message)
                continue
            self.assertEqual("the verification level used" in reason, "verification" in missing, message)
            self.assertEqual("a one line retro" in reason, "retro" in missing, message)

    def test_a_hand_back_that_misses_both_lists_both_hints_in_order(self):
        for message in ["Done.", "", "   "]:
            reason = stop(message)
            self.assertEqual(reason, "Your hand-back is missing: the verification level used; a one line retro (worked / exposed / rule). "
                                     "Fix this in your final message; this check blocks only once.", message)

    def test_the_level_must_be_a_whole_word_and_case_sensitive(self):
        self.assertIn("verification", stop("retro. level L1x"))
        self.assertIn("verification", stop("retro. level l1"))
        self.assertIsNone(stop("retro. (L1)"))


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
            (pathlib.Path(tmp) / ".claude" / "agent-steddy.json").write_text((ROOT / "examples" / "agent-steddy.json").read_text())
            config = project_config.load(tmp)
        self.assertEqual(config["handback"]["agents"], ["acme-*"])
        self.assertIsNone(stop(FULL + " Resources released: nothing started.", config))
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
