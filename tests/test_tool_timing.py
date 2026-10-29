import contextlib
import json
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import local_state  # noqa: E402
import tool_timing  # noqa: E402
from hook_runner import make_repo, run_hook  # noqa: E402

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
