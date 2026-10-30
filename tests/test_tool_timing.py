import contextlib
import io
import json
import os
import pathlib
import re
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import local_state  # noqa: E402
import tool_timing  # noqa: E402
from hook_runner import make_repo, run_hook, write_config  # noqa: E402

START = 1_800_000_000.0  # a fixed clock for the in-process tests


@contextlib.contextmanager
def repo():
    """A temp git repo as a resolved path."""
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp).resolve()
        make_repo(root)
        yield root


def call(command="make test", tool="Bash", call_id="toolu_1", **extra):
    return {"tool_name": tool, "tool_use_id": call_id, "tool_input": {"command": command}, **extra}


def rows(root):
    log = local_state.state_dir(root) / local_state.TIMES
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


class Pairing(unittest.TestCase):
    def test_a_start_and_an_end_make_one_line_and_the_mark_goes_away(self):
        with repo() as root:
            self.assertIsNone(tool_timing.handle("pre", call(), root, START))
            marks = local_state.state_dir(root) / local_state.MARKS
            self.assertEqual(len(list(marks.iterdir())), 1)
            row = tool_timing.handle("post", call(agent_type="acme-web"), root, START + 2.5)
            self.assertEqual((row["agent"], row["ms"], row["status"], row["cmd"]), ("acme-web", 2500, "ok", "make test"))
            self.assertEqual(rows(root), [row])
            self.assertEqual(list(marks.iterdir()), [])

    def test_the_line_starts_at_the_start_time(self):
        import time
        with repo() as root:
            tool_timing.handle("pre", call(), root, START)
            row = tool_timing.handle("post", call(), root, START + 90)
            self.assertEqual(row["ts"], time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(START)))

    def test_a_failure_is_logged_with_its_status_and_the_main_session_is_main(self):
        with repo() as root:
            tool_timing.handle("pre", call("false"), root, START)
            row = tool_timing.handle("fail", call("false", error="Exit code 1"), root, START + 1)
            self.assertEqual((row["agent"], row["status"], row["ms"]), ("main", "fail", 1000))

    def test_two_commands_in_flight_do_not_mix_up(self):
        with repo() as root:
            tool_timing.handle("pre", call("slow", call_id="a"), root, START)
            tool_timing.handle("pre", call("quick", call_id="b"), root, START + 1)
            quick = tool_timing.handle("post", call("quick", call_id="b"), root, START + 2)
            slow = tool_timing.handle("post", call("slow", call_id="a"), root, START + 10)
            self.assertEqual((quick["ms"], slow["ms"]), (1000, 10000))

    def test_the_duration_that_claude_code_reports_wins_over_the_time_between_the_hooks(self):
        with repo() as root:
            tool_timing.handle("pre", call(), root, START)  # the owner took a minute to approve, the command took 3 s
            row = tool_timing.handle("post", call(duration_ms=3000), root, START + 63)
            self.assertEqual(row["ms"], 3000)

    def test_an_end_without_a_start_is_logged_only_when_the_duration_is_known(self):
        with repo() as root:
            self.assertIsNone(tool_timing.handle("post", call(), root, START))
            self.assertEqual(rows(root), [])
            row = tool_timing.handle("post", call(duration_ms=2000), root, START)
            self.assertEqual(row["ms"], 2000)
            for bad in ("2", True, -5, None, [1]):
                self.assertIsNone(tool_timing.handle("post", call(duration_ms=bad, call_id=f"x{bad!r}"), root, START), bad)
            self.assertEqual(len(rows(root)), 1)

    def test_other_tools_are_ignored(self):
        with repo() as root:
            tool_timing.handle("pre", call(tool="Read"), root, START)
            self.assertIsNone(tool_timing.handle("post", call(tool="Read", duration_ms=5), root, START))
            self.assertFalse(local_state.state_dir(root).exists())

    def test_a_call_id_cannot_leave_the_marks_folder(self):
        with repo() as root:
            tool_timing.handle("pre", call(call_id="../../escape"), root, START)
            state = local_state.state_dir(root)
            self.assertEqual([p.name for p in (state / local_state.MARKS).iterdir()], ["______escape"])
            self.assertEqual(sorted(p.name for p in state.iterdir()), [local_state.MARKS])

    def test_with_no_state_folder_nothing_happens(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"CLAUDE_PLUGIN_DATA": ""}):
            self.assertIsNone(tool_timing.handle("pre", call(), tmp, START))
            self.assertIsNone(tool_timing.handle("post", call(duration_ms=5), tmp, START))
            self.assertEqual(os.listdir(tmp), [])


class SessionAndAgent(unittest.TestCase):
    def test_the_line_carries_the_session_id_and_the_agent_id_when_the_hook_input_has_them(self):
        cases = [
            ({}, {}),  # an input that has neither, as before
            ({"session_id": "s1"}, {"session_id": "s1"}),  # the main session has no agent_id
            ({"session_id": "s1", "agent_id": "a1", "agent_type": "acme-web"}, {"session_id": "s1", "agent_id": "a1"}),
            ({"session_id": "", "agent_id": None}, {}),  # empty or missing values are left out
            ({"session_id": 7, "agent_id": ["a"]}, {}),  # a value of the wrong type is left out
        ]
        for extra, kept in cases:
            with repo() as root:
                row = tool_timing.handle("post", call(duration_ms=5, **extra), root, START)
                self.assertEqual({key: row[key] for key in ("session_id", "agent_id") if key in row}, kept, extra)
                self.assertEqual(set(row) - {"session_id", "agent_id"}, {"ts", "agent", "ms", "status", "cmd"}, extra)
                self.assertEqual(rows(root), [row])

    def test_a_log_with_old_lines_stays_readable_beside_new_ones(self):
        with repo() as root:
            log = local_state.state_dir(root) / local_state.TIMES
            log.parent.mkdir(parents=True)
            log.write_text('{"ts": "2026-10-29T17:40:02", "agent": "main", "ms": 2500, "status": "ok", "cmd": "make test"}\n')
            tool_timing.handle("post", call(duration_ms=5, session_id="s1"), root, START)
            self.assertEqual([row.get("session_id") for row in rows(root)], [None, "s1"])
            self.assertEqual(len(tool_timing.tail_rows(log)), 2)


class PremiseNudge(unittest.TestCase):
    """A command that fails again and again in one session earns one line that says to test the premise."""

    def play(self, events, root, config=None):
        """Run the events in order and return the hook output of the last one; an event is (kind, command, session, agent_id)."""
        if config is not None:
            write_config(root, config)
        output = None
        for number, (kind, command, session, agent_id) in enumerate(events):
            extra = {"session_id": session, "duration_ms": 10, "tool_use_id": f"toolu_{number}"}
            if agent_id:
                extra["agent_id"] = agent_id
            if kind == "fail":
                output = tool_timing.run("fail", call(command, error="Exit code 1", **extra), root, START + number)
            else:
                output = tool_timing.run("post", call(command, **extra), root, START + number)
        return output

    def nudged(self, output):
        """The failure count the nudge states, None when the hook printed nothing."""
        if output is None:
            return None
        self.assertEqual(list(output), ["hookSpecificOutput"])
        self.assertEqual(output["hookSpecificOutput"]["hookEventName"], "PostToolUseFailure")
        self.assertEqual(list(output["hookSpecificOutput"]), ["hookEventName", "additionalContext"])
        return int(re.match(r"This command failed (\d+) times in a row in this session\. ", output["hookSpecificOutput"]["additionalContext"]).group(1))

    def test_the_count_of_failures_in_a_row_decides_whether_the_nudge_speaks(self):
        fail = lambda command="make test", session="s1", agent=None: ("fail", command, session, agent)
        ok = lambda command="make test", session="s1", agent=None: ("ok", command, session, agent)
        cases = [
            ("one failure", [fail()], None),
            ("two", [fail(), fail()], 2),
            ("three", [fail(), fail(), fail()], 3),
            ("four", [fail()] * 4, 4),
            ("a success resets the count", [fail(), fail(), ok(), fail()], None),
            ("and it counts up again after the reset", [fail(), fail(), ok(), fail(), fail()], 2),
            ("a success first changes nothing", [ok(), fail(), fail()], 2),
            ("another command that failed in between does not matter", [fail(), fail("make lint"), fail()], 2),
            ("nor does one that passed", [fail(), ok("make lint"), fail("make lint"), ok("make lint"), fail()], 2),
            ("two other commands do not add up", [fail("make lint"), fail("make test")], None),
            ("the same command behind a cd is the same command", [fail("cd /elsewhere && make test"), fail("make test")], 2),
            ("another session is not counted", [fail(session="s1"), fail(session="s2")], None),
            ("and the first session still has its own count", [fail(session="s1"), fail(session="s2"), fail(session="s1")], 2),
            ("a subagent is not the main session", [fail(), fail(agent="a1")], None),
            ("one subagent is not another", [fail(agent="a1"), fail(agent="a2")], None),
            ("a subagent counts its own runs", [fail(agent="a1"), fail(), fail(agent="a1")], 2),
            ("a success of another session does not reset", [fail(), ok(session="s2"), fail()], 2),
        ]
        for name, events, expected in cases:
            with repo() as root:
                self.assertEqual(self.nudged(self.play(events, root)), expected, name)

    def test_the_nudge_text_is_the_one_in_the_docs_and_holds_nothing_of_the_command(self):
        with repo() as root:
            secret = "sbp_" + "a1B2" * 10
            output = self.play([("fail", f"deploy --token {secret}", "s1", None)] * 3, root)
            text = output["hookSpecificOutput"]["additionalContext"]
            self.assertEqual(text, "This command failed 3 times in a row in this session. If the fixes between the runs rest on one premise, stop: "
                                   "write that premise as one sentence and test it before the next fix (gates skill, attack the premise).")
            for fragment in ("deploy", "sbp_", "a1B2"):
                self.assertNotIn(fragment, text)

    def test_only_a_failure_speaks(self):
        with repo() as root:
            self.play([("fail", "make test", "s1", None)] * 3, root)
            self.assertIsNone(self.play([("ok", "make test", "s1", None)], root))
            data = call("make test", session_id="s1", duration_ms=5, error="Exit code 1")
            self.assertIsNone(tool_timing.run("post", data, root, START))
            self.assertIsNone(tool_timing.run("pre", data, root, START))
            self.assertIsNone(tool_timing.run("fail", call("make test", tool="Read", session_id="s1", duration_ms=5), root, START))

    def test_an_input_without_a_session_id_never_speaks(self):
        with repo() as root:
            for number in range(4):
                self.assertIsNone(tool_timing.run("fail", call("make test", duration_ms=5, error="Exit code 1", tool_use_id=f"t{number}"), root, START))
            self.assertEqual(len(rows(root)), 4)

    def test_lines_from_before_the_session_id_existed_are_not_counted(self):
        with repo() as root:
            log = local_state.state_dir(root) / local_state.TIMES
            log.parent.mkdir(parents=True)
            old = '{"ts": "2026-10-29T17:40:02", "agent": "main", "ms": 50, "status": "fail", "cmd": "make test"}\n'
            log.write_text(old * 3)
            self.assertIsNone(self.play([("fail", "make test", "s1", None)], root))
            self.assertEqual(self.nudged(self.play([("fail", "make test", "s1", None)], root)), 2)  # the old lines stay in the file and out of the count

    def test_the_config_switch(self):
        cases = [
            ("no config", None, 2),
            ("on", {"nudges": {"premise": True}}, 2),
            ("off", {"nudges": {"premise": False}}, None),
            ("a wrong type is the default, which is on", {"nudges": {"premise": "no"}}, 2),
            ("an empty section is the default", {"nudges": {}}, 2),
            ("a section of the wrong type is the default", {"nudges": "off"}, 2),
            ("an unrelated section changes nothing", {"reminder": {"enabled": False}}, 2),
        ]
        for name, config, expected in cases:
            with repo() as root:
                self.assertEqual(self.nudged(self.play([("fail", "make test", "s1", None)] * 2, root, config)), expected, name)
                self.assertEqual(len(rows(root)), 2, name)  # the line is logged whatever the switch says

    def test_a_config_that_cannot_be_read_leaves_the_default(self):
        with repo() as root:
            folder = root / ".claude"
            folder.mkdir()
            (folder / "agent-steddy.json").write_text("{not json")
            with contextlib.redirect_stderr(io.StringIO()) as stderr:
                self.assertEqual(self.nudged(self.play([("fail", "make test", "s1", None)] * 2, root)), 2)
            self.assertIn("ignoring", stderr.getvalue())

    def test_a_broken_log_is_read_as_far_as_it_goes(self):
        with repo() as root:
            log = local_state.state_dir(root) / local_state.TIMES
            log.parent.mkdir(parents=True)
            row = lambda status: json.dumps({"agent": "main", "ms": 1, "status": status, "cmd": "make test", "session_id": "s1"}) + "\n"
            # a cut line, a line that is not an object, a binary byte, a blank line and a row of the wrong shape sit between the rows
            log.write_bytes(row("fail").encode() + b'{"cmd": "make te\n' + b"[1, 2]\n" + b"\xff\xfe\n\n" + b'"text"\n' + row("fail").encode())
            self.assertEqual(self.nudged(self.play([("fail", "make test", "s1", None)], root)), 3)
        with repo() as root:
            log = local_state.state_dir(root) / local_state.TIMES
            log.parent.mkdir(parents=True)
            log.write_bytes(b"\xff" * 50 + b"garbage with no newline")
            self.assertIsNone(self.play([("fail", "make test", "s1", None)], root))

    def test_only_the_tail_of_the_log_is_read(self):
        with repo() as root, mock.patch.object(tool_timing, "TAIL", 1500):
            self.play([("fail", "make test", "s1", None)], root)
            self.play([("ok", f"echo {n}" + "x" * 200, "s1", None) for n in range(20)], root)  # about 5000 bytes of other commands push the failure out of the tail
            self.assertGreater((local_state.state_dir(root) / local_state.TIMES).stat().st_size, 3 * 1500)
            self.assertIsNone(self.play([("fail", "make test", "s1", None)], root))  # it counts one, since the first failure lies beyond the tail
            self.assertEqual(self.nudged(self.play([("fail", "make test", "s1", None)], root)), 2)

    def test_a_log_that_cannot_be_written_stays_silent(self):
        with repo() as root:
            state = local_state.state_dir(root)
            (state / local_state.TIMES).mkdir(parents=True)  # a folder where the log should be
            event = {"hook_event_name": "PostToolUseFailure", **call("make test", session_id="s1", duration_ms=5, error="Exit code 1")}
            for _ in range(3):
                self.assertIsNone(run_hook("tool_timing.py", event, root, args=["fail"]))

    def test_the_hook_process_prints_the_nudge_as_json_and_honors_the_switch(self):
        with repo() as root:
            event = lambda n: {"hook_event_name": "PostToolUseFailure", **call("make test", call_id=f"toolu_{n}", session_id="s1", duration_ms=5, error="Exit code 1")}
            self.assertIsNone(run_hook("tool_timing.py", event(1), root, args=["fail"]))
            second = run_hook("tool_timing.py", event(2), root, args=["fail"])
            self.assertEqual(self.nudged(second), 2)
            write_config(root, {"nudges": {"premise": False}})
            self.assertIsNone(run_hook("tool_timing.py", event(3), root, args=["fail"]))
            write_config(root, {})
            self.assertEqual(self.nudged(run_hook("tool_timing.py", event(4), root, args=["fail"])), 4)

    def test_the_constant_is_the_docs_threshold(self):
        self.assertEqual(tool_timing.PREMISE_FAILS, 2)


class WithTheSecretScan(unittest.TestCase):
    """Both hooks run on PostToolUseFailure, in parallel; Claude Code hands the agent the additionalContext of every hook (hooks reference, checked 2026-10-30), so each one speaks for itself."""

    def test_each_hook_speaks_for_itself_and_the_order_does_not_matter(self):
        secret = "sbp_" + "a1B2" * 10
        command = f"deploy --token {secret}"
        with repo() as root:
            def event(n):
                return {"hook_event_name": "PostToolUseFailure", **call(command, call_id=f"toolu_{n}", session_id="s1", duration_ms=5, error=f"Exit code 1\nbad token {secret}")}

            run_hook("tool_timing.py", event(1), root, args=["fail"])
            for order in (("secret_output_scan.py", "tool_timing.py"), ("tool_timing.py", "secret_output_scan.py")):
                outputs = {script: run_hook(script, event(2), root, args=["fail"] if script == "tool_timing.py" else []) for script in order}
                contexts = {}
                for script, output in outputs.items():
                    self.assertEqual(output["hookSpecificOutput"]["hookEventName"], "PostToolUseFailure", script)
                    contexts[script] = output["hookSpecificOutput"]["additionalContext"]
                    self.assertNotIn(secret, contexts[script], script)
                    self.assertNotIn("updatedToolOutput", output["hookSpecificOutput"], script)
                self.assertIn("supabase-access-token", contexts["secret_output_scan.py"])
                self.assertIn("failed", contexts["tool_timing.py"])
                self.assertNotEqual(*contexts.values())  # two notes, not one note twice


class Normalize(unittest.TestCase):
    def logged(self, command, **extra):
        with repo() as root:
            tool_timing.handle("pre", call(command, **extra), root, START)
            return tool_timing.handle("post", call(command, cwd=str(root), **extra), root, START + 1)["cmd"], root

    def test_what_the_log_keeps_of_a_command(self):
        cases = [
            ("cd /elsewhere && cd x; npm test", "npm test"),
            ("cd '/a dir'\nls", "ls"),
            ('cd "/a dir" && ls', "ls"),
            ("S=/private/tmp/claude-1/session; cp $S/a b", "S=<tmp>; cp $S/a b"),
            ("cat /var/folders/ab/cd/T/x.txt $TMPDIR/y ${TMPDIR}/z", "cat <tmp> <tmp> <tmp>"),
            ("echo done", "echo done"),
        ]
        for command, kept in cases:
            self.assertEqual(self.logged(command)[0], kept, command)

    def test_the_project_root_becomes_a_relative_path(self):
        with repo() as root:
            # a sibling folder that starts with the root name is not the root (here the temp rule takes it, as the test repo sits in a temp folder)
            for command, kept in [(f"cd {root} && cp {root}/docs/a b; ls {root}", "cp docs/a b; ls ."), (f"ls {root}-other", "ls <tmp>")]:
                tool_timing.handle("pre", call(command), root, START)
                self.assertEqual(tool_timing.handle("post", call(command), root, START + 1)["cmd"], kept)

    def test_a_heredoc_body_goes_and_the_rest_stays(self):
        body = "body line\n" * 300
        command = f"cat > f <<'EOF'\n{body}EOF\nmake test"
        self.assertEqual(self.logged(command)[0], "cat > f <<'EOF'\n\nEOF\nmake test")
        self.assertEqual(self.logged("cat <<EOF\nunterminated\nbody")[0], "cat <<EOF\n\nEOF")  # a heredoc with no end is cut at the end of the text

    def test_a_long_command_is_cut_to_400_characters_and_the_heavy_step_after_a_long_prefix_survives(self):
        long = "x" * 500
        self.assertEqual(len(self.logged(long)[0]), tool_timing.CAP)
        prefix = "S=/private/tmp/claude-1/" + "a" * 200 + "; "
        self.assertEqual(self.logged(prefix + "make verify")[0], "S=<tmp>; make verify")

    def test_a_secret_is_replaced_even_when_the_cap_would_have_cut_it(self):
        token = "sbp_" + "a1B2" * 10
        url = "postgres://u:" + "pw" * 8 + "@example.com:5432/x"
        kept = self.logged(f"curl -H 'Authorization: Bearer {token}' {url}")[0]
        self.assertEqual(kept, "curl -H 'Authorization: Bearer [REDACTED:supabase-access-token]' [REDACTED:postgres-url-password]:5432/x")
        for fragment in ("a1B2a1B2", "pwpwpw"):
            self.assertNotIn(fragment, kept)
        straddling = self.logged("echo " + "y" * 372 + " " + token)[0]  # the token starts before character 400 and ends after it
        self.assertNotIn("sbp_", straddling)
        self.assertEqual(len(straddling), tool_timing.CAP)


class Hook(unittest.TestCase):
    """The script as Claude Code runs it."""

    def test_pre_post_and_fail_through_the_hook_process(self):
        with repo() as root:
            pre = {"hook_event_name": "PreToolUse", **call("make test", call_id="toolu_a")}
            self.assertIsNone(run_hook("tool_timing.py", pre, root, args=["pre"]))
            post = {"hook_event_name": "PostToolUse", **call("make test", call_id="toolu_a", duration_ms=1500, agent_type="acme-web")}
            self.assertIsNone(run_hook("tool_timing.py", post, root, args=["post"]))
            failed = {"hook_event_name": "PostToolUseFailure", **call("make lint", call_id="toolu_b", duration_ms=40, error="Exit code 2")}
            self.assertIsNone(run_hook("tool_timing.py", failed, root, args=["fail"]))
            first, second = rows(root)
            self.assertEqual((first["agent"], first["ms"], first["status"], first["cmd"]), ("acme-web", 1500, "ok", "make test"))
            self.assertEqual((second["agent"], second["ms"], second["status"], second["cmd"]), ("main", 40, "fail", "make lint"))

    def test_the_plugin_data_dir_serves_a_project_outside_a_repo(self):
        with tempfile.TemporaryDirectory() as project, tempfile.TemporaryDirectory() as data:
            post = {"hook_event_name": "PostToolUse", **call("ls", duration_ms=7)}
            run_hook("tool_timing.py", post, project, env={"CLAUDE_PLUGIN_DATA": data}, args=["post"])
            with mock.patch.dict(os.environ, {"CLAUDE_PLUGIN_DATA": data}):
                self.assertEqual([row["ms"] for row in rows(project)], [7])

    def test_everything_fails_open_with_broken_input_or_arguments(self):
        with repo() as root:
            for raw in ["not json", "", "[]", "null", '{"tool_name": "Bash", "tool_input": 5}']:
                for mode in ("pre", "post", "fail"):
                    self.assertIsNone(run_hook("tool_timing.py", None, root, raw=raw, args=[mode]), (raw, mode))
            self.assertIsNone(run_hook("tool_timing.py", call(), root, args=[]))
            self.assertIsNone(run_hook("tool_timing.py", call(), root, args=["nonsense"]))


if __name__ == "__main__":
    unittest.main()
