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
from hook_runner import make_repo, write_config  # noqa: E402

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


if __name__ == "__main__":
    unittest.main()
