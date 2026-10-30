import contextlib
import datetime as dt
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from hook_runner import git, make_repo, write_config  # noqa: E402

BIN = ROOT / "bin" / "agent-steddy"
LOG = ["metrics", "log", "--size", "M", "--type", "new", "--verify-first-pass", "yes"]


@contextlib.contextmanager
def project(config=None):
    """A temp git repo, as a resolved path, with an optional project config."""
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp).resolve()
        make_repo(root)
        if config is not None:
            write_config(root, config)
        yield root


def agent_steddy(args, cwd, **env):
    """The finished process of `bin/agent-steddy` run in `cwd`, the way the Bash tool runs it: no CLAUDE_PROJECT_DIR and no CLAUDE_PLUGIN_DATA."""
    base = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_PROJECT_DIR", "CLAUDE_PLUGIN_DATA")}
    return subprocess.run([str(BIN), *args], cwd=cwd, env={**base, **env}, capture_output=True, text=True)


class Dispatch(unittest.TestCase):
    def test_the_command_is_executable_and_prints_its_usage(self):
        self.assertTrue(os.access(BIN, os.X_OK))
        with project() as root:
            done = agent_steddy(["--help"], root)
            self.assertEqual(done.returncode, 0)
            self.assertIn("metrics", done.stdout)
            self.assertEqual(agent_steddy([], root).returncode, 2)
            self.assertEqual(agent_steddy(["nonsense"], root).returncode, 2)

    def test_it_runs_isolated_like_the_hooks(self):
        with project() as root, tempfile.TemporaryDirectory() as planted:
            pathlib.Path(planted, "json.py").write_text("raise SystemExit('a planted module was imported')")
            done = agent_steddy(["metrics", "selftest"], root, PYTHONPATH=planted)
            self.assertEqual((done.returncode, done.stdout.strip(), done.stderr), (0, "selftest ok", ""))

    def test_the_project_is_found_from_a_subfolder_of_the_repo(self):
        with project({"records": {"metrics": "notes/metrics.jsonl"}}) as root:
            (root / "app" / "src").mkdir(parents=True)
            self.assertEqual(agent_steddy(["metrics", "start", "build it"], root / "app" / "src").stdout.strip(), "started: build it")
            done = agent_steddy([*LOG, "--roles", "web,docs"], root / "app" / "src")
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual(done.stderr, "")
            self.assertTrue(done.stdout.startswith("logged: "))
            lines = (root / "notes" / "metrics.jsonl").read_text().splitlines()
            self.assertEqual(len(lines), 1)
            row = json.loads(lines[0])
            self.assertEqual((row["task"], row["size"], row["roles"], row["minutes"]), ("build it", "M", ["web", "docs"], 0))
            self.assertFalse((root / "app").joinpath("notes").exists())

    def test_claude_project_dir_wins_over_the_cwd(self):
        with project() as one, project({"records": {"metrics": "m.jsonl"}}) as two:
            done = agent_steddy([*LOG, "--task", "t"], one, CLAUDE_PROJECT_DIR=str(two))
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertTrue((two / "m.jsonl").exists())
            self.assertFalse((one / "docs").exists())


class Refusals(unittest.TestCase):
    def test_a_refused_command_exits_1_with_the_reason_on_stderr(self):
        with project() as root:
            self.assertEqual(agent_steddy(["metrics", "start", "first"], root).returncode, 0)
            done = agent_steddy(["metrics", "start", "second"], root)
            self.assertEqual((done.returncode, done.stdout), (1, ""))
            self.assertTrue(done.stderr.startswith("agent-steddy: refused: 'first' has been running"), done.stderr)
            self.assertEqual(agent_steddy(["metrics", "start", "second", "--force"], root).returncode, 0)

    def test_log_with_no_task_is_refused(self):
        with project() as root:
            done = agent_steddy(LOG, root)
            self.assertEqual(done.returncode, 1)
            self.assertIn("no task", done.stderr)
            self.assertFalse((root / "docs").exists())

    def test_a_task_that_is_still_the_auto_name_is_logged_with_a_note(self):
        with project() as root:
            state = root / ".git" / "agent-steddy"
            state.mkdir()
            stamp = dt.datetime.now().isoformat(timespec="seconds")
            (state / "pending-task.json").write_text(json.dumps({"task": f"auto {stamp}", "start": stamp}))
            done = agent_steddy(LOG, root)
            self.assertEqual(done.returncode, 0)
            self.assertIn("note: the task name is still the auto name", done.stdout)
            self.assertIn(f'"task": "auto {stamp}"', done.stdout)


class Reports(unittest.TestCase):
    def test_report_and_slow_run_on_a_fresh_project(self):
        with project() as root:
            report = agent_steddy(["metrics", "report"], root)
            self.assertEqual(report.returncode, 0, report.stderr)
            self.assertIn("Tasks (docs/agents/metrics.jsonl)", report.stdout)
            self.assertIn("no rows yet", report.stdout)
            slow = agent_steddy(["metrics", "slow", "--days", "3", "--top", "5"], root)
            self.assertEqual(slow.returncode, 0, slow.stderr)
            self.assertIn("last 3 days", slow.stdout)
            self.assertIn("no timing rows", slow.stdout)
            self.assertFalse((root / ".git" / "agent-steddy").exists())  # reading creates nothing

    def test_the_report_reads_the_file_named_in_the_config(self):
        with project({"records": {"metrics": "out/m.jsonl"}}) as root:
            self.assertEqual(agent_steddy([*LOG, "--task", "t", "--minutes", "12"], root).returncode, 0)
            report = agent_steddy(["metrics", "report"], root).stdout
            self.assertIn("Tasks (out/m.jsonl)", report)
            self.assertIn("  12/", report)


class Records(unittest.TestCase):
    def test_decision_and_lesson_go_to_the_files_named_in_the_config(self):
        with project({"records": {"decisions": "notes/decisions.md", "lessons": "notes/lessons.md"}}) as root:
            done = agent_steddy(["record", "decision", "api", "keep v1 for a month - clients lag"], root)
            self.assertEqual((done.returncode, done.stdout.strip(), done.stderr), (0, "added: - [api] keep v1 for a month - clients lag", ""))
            self.assertTrue((root / "notes" / "decisions.md").read_text().endswith("- [api] keep v1 for a month - clients lag\n"))
            done = agent_steddy(["record", "lesson", "--task", "t1", "--roles", "web,docs", "--worked", "w", "--exposed", "e", "--rule", "r", "--key", "the-key"], root)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertRegex(done.stdout, r"^added: ## \d{4}-\d\d-\d\d - t1 - roles: web, docs\n$")
            self.assertIn("- Rule [the-key]: r\n", (root / "notes" / "lessons.md").read_text())
            self.assertFalse((root / "docs").exists())

    def test_a_refused_record_exits_1_and_a_missing_option_exits_2(self):
        with project() as root:
            done = agent_steddy(["record", "decision", "bad area!", "x"], root)
            self.assertEqual((done.returncode, done.stdout), (1, ""))
            self.assertIn("agent-steddy: refused: area must be", done.stderr)
            self.assertEqual(agent_steddy(["record", "lesson", "--task", "t"], root).returncode, 2)
            self.assertFalse((root / "docs").exists())

    def feature_branch(self, root):
        if (root / ".claude").exists():  # the project config is committed, as in a real project, so the tree is clean
            git(root, "add", ".claude")
            git(root, "commit", "-q", "-m", "config")
        git(root, "switch", "-q", "-c", "feat/x")
        (root / "f.txt").write_text("1")
        git(root, "add", "f.txt")
        git(root, "commit", "-q", "-m", "work")
        git(root, "switch", "-q", "main")

    def test_finish_merges_a_verified_branch_and_prints_its_progress(self):
        with project({"verifyCommand": "test -f f.txt"}) as root:
            self.feature_branch(root)
            done = agent_steddy(["record", "finish", "feat/x"], root)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertIn("[finish] test -f f.txt passed", done.stdout)
            self.assertTrue(done.stdout.strip().endswith("(nothing was pushed)"))
            self.assertEqual(git(root, "branch", "--format=%(refname:short)").split(), ["main"])

    def test_finish_refuses_a_failing_verify_and_a_missing_verify_command(self):
        with project({"verifyCommand": "false"}) as root:
            self.feature_branch(root)
            done = agent_steddy(["record", "finish", "feat/x"], root)
            self.assertEqual((done.returncode, done.stdout.count("passed")), (1, 0))
            self.assertIn("nothing merged", done.stderr)
            self.assertEqual(sorted(git(root, "branch", "--format=%(refname:short)").split()), ["feat/x", "main"])
        with project() as root:
            self.feature_branch(root)
            done = agent_steddy(["record", "finish", "feat/x"], root)
            self.assertEqual(done.returncode, 1)
            self.assertIn("--no-verify", done.stderr)
            self.assertEqual(agent_steddy(["record", "finish", "feat/x", "--no-verify"], root).returncode, 0)
            self.assertEqual(git(root, "branch", "--format=%(refname:short)").split(), ["main"])



def lesson(task, rule, key=None, roles="web"):
    return ["record", "lesson", "--task", task, "--roles", roles, "--worked", "w", "--exposed", "e", "--rule", rule, *(["--key", key] if key else [])]


class LearningLoop(unittest.TestCase):
    def test_a_rule_with_no_key_exits_2_writes_nothing_and_lists_the_closest_rules_on_stderr(self):
        with project() as root:
            done = agent_steddy(lesson("t1", "commit by path"), root)
            self.assertEqual((done.returncode, done.stdout), (2, ""))
            self.assertTrue(done.stderr.startswith("agent-steddy: refused: a rule needs a key"), done.stderr)
            self.assertIn("no keyed rule is recorded yet", done.stderr)
            self.assertFalse((root / "docs").exists())
            self.assertEqual(agent_steddy(lesson("t1", "commit by path", "commit-by-path"), root).returncode, 0)
            done = agent_steddy(lesson("t2", "always commit by path"), root)
            self.assertEqual(done.returncode, 2)
            self.assertIn("  commit-by-path (seen 1 time): commit by path", done.stderr)
            self.assertIn("re-run with --key <existing> if it is the same rule, or --key <new-slug> if it is new", done.stderr)
            self.assertEqual((root / "docs/agents/lessons.md").read_text().count("## 20"), 1)

    def test_the_second_time_a_key_is_recorded_the_notice_names_the_promote_command(self):
        with project() as root:
            first = agent_steddy(lesson("t1", "commit by path", "commit-by-path", roles="web,docs"), root)
            self.assertEqual(first.stdout.count("\n"), 1)  # the heading, no notice
            second = agent_steddy(lesson("t2", "commit by path always", "commit-by-path", roles="web"), root)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(second.stdout.splitlines()[1:], [
                "commit-by-path is now seen 2 times",
                "agent-steddy lessons promote commit-by-path --to web",
                "roles in these entries, most common first: web (2), docs (1)",
                "a rule about safety, data or money goes --to walls instead",
            ])
            none = agent_steddy(lesson("t3", "none", roles="web"), root)
            self.assertEqual((none.returncode, none.stdout.count("\n")), (0, 1))  # a rule of none: no key, no notice

    def test_a_bad_key_exits_2_and_another_refusal_still_exits_1(self):
        with project() as root:
            done = agent_steddy(lesson("t1", "r", "Bad Key"), root)
            self.assertEqual((done.returncode, done.stdout), (2, ""))
            self.assertIn("bad key 'Bad Key'", done.stderr)
            done = agent_steddy(["record", "lesson", "--task", "t", "--roles", "web", "--worked", "w", "--exposed", "", "--rule", "none"], root)
            self.assertEqual(done.returncode, 1)


if __name__ == "__main__":
    unittest.main()
