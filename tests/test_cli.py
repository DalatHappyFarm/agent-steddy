import contextlib
import datetime as dt
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import local_state  # noqa: E402
import session_marker  # noqa: E402
from hook_runner import cli_env, git, make_repo, run_hook, write_config  # noqa: E402

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
    """The finished process of `bin/agent-steddy` run in `cwd`, the way the Bash tool runs it but outside a session (see `cli_env`); `env` is added."""
    return subprocess.run([str(BIN), *args], cwd=cwd, env=cli_env(**env), capture_output=True, text=True)


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
            self.assertEqual((done.returncode, done.stdout.splitlines()[0], done.stderr), (0, "selftest ok", ""))

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

    def test_a_task_that_still_has_its_auto_name_is_refused_with_exit_2_and_logs_once_it_is_named(self):
        with project() as root:
            state = root / ".git" / "agent-steddy"
            state.mkdir()
            stamp = dt.datetime.now().isoformat(timespec="seconds")
            clock = state / "pending-task.json"
            clock.write_text(json.dumps({"task": f"auto {stamp}", "start": stamp}))
            for extra in ([], ["--task", ""]):
                done = agent_steddy([*LOG, *extra], root)
                self.assertEqual((done.returncode, done.stdout), (2, ""))
                self.assertTrue(done.stderr.startswith(f'agent-steddy: refused: the pending task is still named "auto {stamp}": pass --task "<what was done>"'), done.stderr)
                self.assertIn('name it earlier with `agent-steddy metrics start "<task>"`', done.stderr)
                self.assertFalse((root / "docs").exists())  # nothing was written
                self.assertEqual(json.loads(clock.read_text()), {"task": f"auto {stamp}", "start": stamp})  # and the clock is kept
            done = agent_steddy([*LOG, "--task", "the pricing page"], root)
            self.assertEqual((done.returncode, done.stderr), (0, ""))
            self.assertTrue(done.stdout.startswith('logged: {"date"'), done.stdout)
            self.assertNotIn("note:", done.stdout)
            self.assertEqual(json.loads((root / "docs/agents/metrics.jsonl").read_text())["task"], "the pricing page")
            self.assertFalse(clock.exists())

    def test_a_clock_left_open_is_refused_with_exit_2_and_logs_with_the_active_minutes(self):
        with project() as root:
            state = root / ".git" / "agent-steddy"
            state.mkdir()
            started = (dt.datetime.now() - dt.timedelta(days=2)).isoformat(timespec="seconds")
            clock = state / "pending-task.json"
            clock.write_text(json.dumps({"task": "the pricing page", "start": started, "prompt_start": started}))
            done = agent_steddy(LOG, root)
            self.assertEqual((done.returncode, done.stdout), (2, ""))
            self.assertRegex(done.stderr, r"^agent-steddy: refused: the clock has run \d+ minutes, more than a working day \(480\)")
            self.assertGreaterEqual(int(re.search(r"has run (\d+) minutes", done.stderr).group(1)), 2 * 24 * 60)
            self.assertIn("Pass --minutes <active minutes>", done.stderr)
            self.assertFalse((root / "docs").exists())  # nothing was written
            self.assertEqual(json.loads(clock.read_text())["start"], started)  # and the clock is kept
            done = agent_steddy([*LOG, "--minutes", "90"], root)
            self.assertEqual((done.returncode, done.stderr), (0, ""))
            self.assertEqual(json.loads((root / "docs/agents/metrics.jsonl").read_text())["minutes"], 90)
            self.assertFalse(clock.exists())

    def test_naming_the_task_earlier_with_start_logs_without_task(self):
        with project() as root:
            state = root / ".git" / "agent-steddy"
            state.mkdir()
            stamp = dt.datetime.now().isoformat(timespec="seconds")
            (state / "pending-task.json").write_text(json.dumps({"task": f"auto {stamp}", "start": stamp}))
            self.assertEqual(agent_steddy(["metrics", "start", "the footer"], root).returncode, 0)
            done = agent_steddy(LOG, root)
            self.assertEqual((done.returncode, done.stderr), (0, ""))
            self.assertEqual(json.loads((root / "docs/agents/metrics.jsonl").read_text())["task"], "the footer")


class Reports(unittest.TestCase):
    def test_report_and_slow_run_on_a_fresh_project(self):
        with project() as root:
            report = agent_steddy(["metrics", "report"], root)
            self.assertEqual(report.returncode, 0, report.stderr)
            self.assertIn("Tasks (docs/agents/metrics.jsonl)", report.stdout)
            self.assertIn("no rows yet", report.stdout)
            self.assertTrue(report.stdout.endswith("Verdicts, the last two weeks that have tasks\n  needs two weeks with tasks\n"), report.stdout)
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


class Guard(unittest.TestCase):
    def test_it_prints_the_verdict_of_the_built_in_and_the_project_rules_and_expect_sets_the_exit_code(self):
        with project({"commands": {"deny": [{"match": "acme-cli config push", "reason": "No config push."}], "askFromSubagent": ["make deploy"]}}) as root:
            done = agent_steddy(["guard", "go test ./... | tail -5 && git commit -m x -- a.go"], root)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertTrue(done.stdout.startswith("deny: [pipe-before-commit] A pipeline's exit status"), done.stdout)
            self.assertEqual(agent_steddy(["guard", "acme-cli config push", "--expect", "deny"], root).stdout, "deny: No config push.\n")
            self.assertEqual(agent_steddy(["guard", "git status"], root).stdout, "allow\n")
            self.assertEqual(agent_steddy(["guard", "make deploy"], root).stdout, "allow\n")
            self.assertTrue(agent_steddy(["guard", "make deploy", "--agent", "acme-web"], root).stdout.startswith("ask: "))
            for line, expect, code in [("git stash", "deny", 0), ("git status", "deny", 1), ("git status", "allow", 0), ("git push --force", "ask", 0), ("git stash", "allow", 1)]:
                self.assertEqual(agent_steddy(["guard", line, "--expect", expect], root).returncode, code, (line, expect))


GUARD_CONFIG = {"commands": {"deny": [{"match": "acme-cli config push", "reason": "No config push."}], "askFromSubagent": ["make deploy"]}}
CASES = """# recorded lines and their verdicts

deny git stash
deny acme-cli config push --yes
\tdeny   git add -A
ask @acme-web make deploy
allow make deploy
allow git status --short
allow @acme-web rg TODO web/
"""


class GuardCases(unittest.TestCase):
    def cases(self, root, text, name="docs/agents/guard-cases.txt"):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def test_it_runs_every_case_of_the_default_file_and_prints_one_summary_line(self):
        with project(GUARD_CONFIG) as root:
            self.cases(root, CASES)
            done = agent_steddy(["guard", "--cases"], root)
            self.assertEqual((done.returncode, done.stdout, done.stderr), (0, "guard cases: 7 passed, 0 failed\n", ""))
            (root / "app").mkdir()
            self.assertEqual(agent_steddy(["guard", "--cases"], root / "app").stdout, "guard cases: 7 passed, 0 failed\n")  # the project is found from a subfolder

    def test_the_default_file_comes_from_the_project_config_and_a_file_argument_replaces_it(self):
        with project({**GUARD_CONFIG, "records": {"guardCases": "notes/cases.txt"}}) as root:
            self.cases(root, "deny git stash\n", "notes/cases.txt")
            self.cases(root, "allow git stash\nallow git status\n", "other.txt")
            self.assertEqual(agent_steddy(["guard", "--cases"], root).stdout, "guard cases: 1 passed, 0 failed\n")
            done = agent_steddy(["guard", "--cases", "other.txt"], root)
            self.assertEqual((done.returncode, done.stdout), (1, "FAIL line 1: want allow, got deny: git stash\nguard cases: 1 passed, 1 failed\n"))

    def test_a_failure_prints_its_line_number_and_both_verdicts_and_exits_1(self):
        with project(GUARD_CONFIG) as root:
            text = CASES.replace("deny acme-cli config push --yes", "deny acme-cli config show").replace("allow @acme-web rg TODO web/", "ask @acme-web rg TODO web/")
            self.cases(root, text)
            done = agent_steddy(["guard", "--cases"], root)
            self.assertEqual(done.returncode, 1)
            self.assertEqual(done.stdout.splitlines(), ["FAIL line 4: want deny, got allow: acme-cli config show",
                                                        "FAIL line 9: want ask, got allow: @acme-web rg TODO web/",
                                                        "guard cases: 5 passed, 2 failed"])

    def test_a_config_edit_that_changes_a_verdict_fails_the_same_cases(self):
        with project(GUARD_CONFIG) as root:
            self.cases(root, CASES)
            self.assertEqual(agent_steddy(["guard", "--cases"], root).returncode, 0)
            write_config(root, {"commands": {"deny": [], "askFromSubagent": []}})
            done = agent_steddy(["guard", "--cases"], root)
            self.assertEqual(done.returncode, 1)
            self.assertEqual(done.stdout.splitlines(), ["FAIL line 4: want deny, got allow: acme-cli config push --yes",
                                                        "FAIL line 6: want ask, got allow: @acme-web make deploy",
                                                        "guard cases: 5 passed, 2 failed"])

    def test_an_agent_case_is_judged_as_a_subagent_and_one_without_is_the_main_session(self):
        with project(GUARD_CONFIG) as root:
            self.cases(root, "allow make deploy\nask @acme-web make deploy\nask @other-agent make deploy\n")
            self.assertEqual(agent_steddy(["guard", "--cases"], root).stdout, "guard cases: 3 passed, 0 failed\n")
            self.cases(root, "ask make deploy\nallow @acme-web make deploy\n")
            self.assertEqual(agent_steddy(["guard", "--cases"], root).stdout.splitlines()[:2],
                             ["FAIL line 1: want ask, got allow: make deploy", "FAIL line 2: want allow, got ask: @acme-web make deploy"])

    def test_a_malformed_line_refuses_with_exit_2_naming_its_number_and_runs_nothing(self):
        for text, number, why in [("deny git stash\n\n# note\nblock git stash\n", 4, "a case starts with deny, ask or allow, not 'block'"),
                                  ("deny git stash\nallow @ git status\n", 2, "'@' needs an agent type"),
                                  ("deny git stash\nallow\n", 2, "no command line after the verdict"),
                                  ("deny\n", 1, "no command line after the verdict"),
                                  ("allow @acme-web\n", 1, "no command line after the verdict"),
                                  ("git stash\n", 1, "a case starts with deny, ask or allow, not 'git'")]:
            with project() as root:
                self.cases(root, text)
                done = agent_steddy(["guard", "--cases"], root)
                self.assertEqual((done.returncode, done.stdout), (2, ""), text)
                self.assertRegex(done.stderr, rf"^agent-steddy: refused: .*guard-cases\.txt line {number}: {why}", text)

    def test_a_missing_file_refuses_with_exit_2_and_a_file_that_is_a_folder_too(self):
        with project() as root:
            done = agent_steddy(["guard", "--cases"], root)
            self.assertEqual((done.returncode, done.stdout), (2, ""))
            self.assertRegex(done.stderr, r"^agent-steddy: refused: cannot read the guard cases file .*docs/agents/guard-cases\.txt: No such file or directory")
            self.assertEqual(agent_steddy(["guard", "--cases", "nope.txt"], root).returncode, 2)
            (root / "docs").mkdir()
            self.assertEqual(agent_steddy(["guard", "--cases", "docs"], root).returncode, 2)

    def test_an_empty_file_has_no_failure_and_the_flag_does_not_mix_with_a_line(self):
        with project() as root:
            self.cases(root, "# nothing recorded yet\n\n")
            self.assertEqual(agent_steddy(["guard", "--cases"], root).stdout, "guard cases: 0 passed, 0 failed\n")
            for args in (["guard", "git stash", "--cases"], ["guard", "--cases", "--agent", "acme-web"], ["guard", "--cases", "--expect", "deny"]):
                done = agent_steddy(args, root)
                self.assertEqual((done.returncode, done.stdout), (2, ""), args)
                self.assertIn("agent-steddy: refused: --cases takes no command line", done.stderr)
            done = agent_steddy(["guard"], root)
            self.assertEqual((done.returncode, done.stdout), (2, ""))
            self.assertIn("agent-steddy: refused: give a command line, or --cases", done.stderr)


class Records(unittest.TestCase):
    def test_decision_and_lesson_go_to_the_files_named_in_the_config(self):
        with project({"records": {"decisions": "notes/decisions.md", "lessons": "notes/lessons.md"}}) as root:
            done = agent_steddy(["record", "decision", "api", "keep v1 for a month - clients lag"], root)
            self.assertEqual((done.returncode, done.stdout.strip(), done.stderr), (0, "added: - [api] keep v1 for a month - clients lag", ""))
            self.assertTrue((root / "notes" / "decisions.md").read_text().endswith("- [api] keep v1 for a month - clients lag\n"))
            done = agent_steddy(["record", "lesson", "--task", "t1", "--roles", "web,docs", "--worked", "w", "--exposed", "e", "--rule", "r", "--key", "the-key", "--when", "w"], root)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertRegex(done.stdout, r"^added: ## \d{4}-\d\d-\d\d - t1 - roles: web, docs\n$")
            self.assertIn("- Rule [the-key]: r\n  - When: w\n", (root / "notes" / "lessons.md").read_text())
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


CARD = "# Role: Web\n\nMission: build pages.\n\n## Pitfalls\n\n- None recorded yet; the second time a mistake happens, add it here as a rule.\n\n## Tools\n\n- rg\n"


def lesson(task, rule, key=None, roles="web", when="about to commit"):
    return ["record", "lesson", "--task", task, "--roles", roles, "--worked", "w", "--exposed", "e", "--rule", rule, *(["--key", key, "--when", when] if key else [])]


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

    def test_check_is_a_report_that_exits_0_and_quiet_prints_one_line_or_nothing(self):
        with project() as root:
            done = agent_steddy(["lessons", "check"], root)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual([line for line in done.stdout.splitlines() if not line.startswith(" ")][:1], ["Due: rules seen 2 or more times and not promoted"])
            self.assertEqual(done.stdout.count("  none\n"), 5)
            self.assertEqual(agent_steddy(["lessons", "check", "--quiet"], root).stdout, "")
            for task in ("t1", "t2"):
                agent_steddy(lesson(task, "commit by path", "commit-by-path"), root)
            done = agent_steddy(["lessons", "check"], root)
            self.assertIn("  commit-by-path: seen 2 times", done.stdout)
            quiet = agent_steddy(["lessons", "check", "--quiet"], root)
            self.assertEqual((quiet.returncode, quiet.stdout), (0, "Learning loop: 1 rule(s) seen twice and not promoted (commit-by-path); run agent-steddy lessons check.\n"))

    def test_promote_writes_the_card_marks_the_lines_and_refuses_with_exit_2(self):
        with project() as root:
            (root / "docs/agents/roles").mkdir(parents=True)
            (root / "docs/agents/roles/web.md").write_text(CARD)
            for task in ("t1", "t2"):
                agent_steddy(lesson(task, "commit by path", "commit-by-path"), root)
            done = agent_steddy(["lessons", "promote", "commit-by-path", "--to", "ops"], root)
            self.assertEqual((done.returncode, done.stdout), (2, ""))
            self.assertIn("agent-steddy: refused: the role card docs/agents/roles/ops.md does not exist; copy templates/roles/role-card.md", done.stderr)
            done = agent_steddy(["lessons", "promote", "commit-by-path", "--to", "web", "--text", "Commit by path, always."], root)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertRegex(done.stdout.splitlines()[0], r"^added to docs/agents/roles/web\.md: - Commit by path, always\. \(lessons: \d{4}-\d\d-\d\d, \d{4}-\d\d-\d\d\)$")
            self.assertIn("as [promoted -> docs/agents/roles/web.md]", done.stdout.splitlines()[1])
            self.assertEqual((root / "docs/agents/roles/web.md").read_text().count("- Commit by path, always."), 1)
            self.assertNotIn("None recorded yet", (root / "docs/agents/roles/web.md").read_text())
            self.assertEqual(agent_steddy(["lessons", "check", "--quiet"], root).stdout, "")
            again = agent_steddy(["lessons", "promote", "commit-by-path", "--to", "walls"], root)
            self.assertEqual(again.returncode, 2)
            self.assertIn("already promoted", again.stderr)
            self.assertFalse((root / "docs/agents/walls.md").exists())

    def test_promote_to_walls_and_a_missing_to_option(self):
        with project() as root:
            agent_steddy(lesson("t1", "never print secrets", "no-secrets"), root)
            self.assertEqual(agent_steddy(["lessons", "promote", "no-secrets", "--to", "walls"], root).returncode, 2)  # seen once
            done = agent_steddy(["lessons", "promote", "no-secrets", "--to", "walls", "--force"], root)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertTrue((root / "docs/agents/walls.md").read_text().startswith("# Walls\n"))
            self.assertEqual(agent_steddy(["lessons", "promote", "no-secrets"], root).returncode, 2)  # argparse: --to is required

    def test_several_rules_in_one_entry_and_a_missing_when_exits_2(self):
        with project() as root:
            base = ["record", "lesson", "--task", "t1", "--roles", "web", "--worked", "w", "--exposed", "e", "--from", "owner"]
            done = agent_steddy([*base, "--rule", "commit by path", "--key", "commit-by-path", "--rule", "look at renders", "--key", "look-at-renders", "--when", "about to commit"], root)
            self.assertEqual((done.returncode, done.stdout), (2, ""))
            self.assertIn("2 rules and 1 When", done.stderr)
            done = agent_steddy([*base, "--rule", "commit by path", "--key", "commit-by-path", "--when", "about to commit",
                                 "--rule", "look at renders", "--key", "look-at-renders", "--when", "a diagram is done"], root)
            self.assertEqual(done.returncode, 0, done.stderr)
            text = (root / "docs/agents/lessons.md").read_text()
            self.assertIn("- Rule [commit-by-path]: commit by path\n  - When: about to commit\n  - From: owner\n- Rule [look-at-renders]: look at renders\n  - When: a diagram is done\n  - From: owner\n", text)

    def test_find_lists_the_rules_that_fit_and_retire_takes_one_out(self):
        with project() as root:
            agent_steddy(lesson("t1", "commit by path, never git add all", "commit-by-path", when="about to stage and commit files"), root)
            agent_steddy(lesson("t2", "look at every rendered diagram", "look-at-renders", when="a diagram or a screenshot is done"), root)
            done = agent_steddy(["lessons", "find", "stage", "the", "files", "and", "commit"], root)
            self.assertEqual((done.returncode, done.stdout.splitlines()), (0, ["commit-by-path (seen 1 time): commit by path, never git add all", "  when: about to stage and commit files"]))
            done = agent_steddy(["lessons", "retire", "commit-by-path", "--by", "look-at-renders"], root)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertIn("no recorded rule matches", agent_steddy(["lessons", "find", "stage files and commit"], root).stdout)
            again = agent_steddy(lesson("t3", "commit by path", "commit-by-path"), root)
            self.assertEqual(again.returncode, 2)
            self.assertIn("commit-by-path is retired by look-at-renders", again.stderr)

    def test_a_promoted_rule_recorded_again_is_noticed_nudged_and_cleared_by_an_eval_case(self):
        with project() as root:
            agent_steddy(lesson("t1", "never pipe a test into tail before committing", "test-exit-status"), root)
            agent_steddy(["lessons", "promote", "test-exit-status", "--to", "walls", "--force"], root)
            new_key = agent_steddy(lesson("t2", "capture the exit status of a test before committing", "capture-exit-status"), root)
            self.assertEqual(new_key.returncode, 2)
            self.assertIn("re-run with --key test-exit-status", new_key.stderr)
            again = agent_steddy(lesson("t2", "capture the exit status of a test before committing", "test-exit-status"), root)
            self.assertEqual(again.returncode, 0, again.stderr)
            self.assertEqual(again.stdout.splitlines()[1], "test-exit-status is seen again after its promotion to docs/agents/walls.md (2 times in all)")
            quiet = agent_steddy(["lessons", "check", "--quiet"], root).stdout
            self.assertEqual(quiet, "Learning loop: 1 rule(s) broken after promotion (test-exit-status); run agent-steddy lessons check.\n")
            (root / "docs/agents/evals").mkdir(parents=True)
            (root / "docs/agents/evals/test-exit-status.md").write_text("# a piped test\n\n- Key: test-exit-status\n- Kind: seen\n- Check: true\n")
            self.assertEqual(agent_steddy(["lessons", "check", "--quiet"], root).stdout, "")
            done = agent_steddy(["lessons", "eval"], root)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual(done.stdout.splitlines()[0], "PASS    test-exit-status (seen) docs/agents/evals/test-exit-status.md")
            (root / "docs/agents/evals/test-exit-status.md").write_text("# a piped test\n\n- Key: test-exit-status\n- Kind: seen\n- Check: echo the pipe hid it; false\n")
            done = agent_steddy(["lessons", "eval"], root)
            self.assertEqual(done.returncode, 1)
            self.assertIn("FAIL    test-exit-status (seen)", done.stdout)
            self.assertIn("    the pipe hid it", done.stdout)
            self.assertIn("summary: seen: 0 of 1 passed", done.stdout)


SID = "c0ffee00-1111-4222-8333-444455556666"
VERSION = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))["version"]


class HooksLive(unittest.TestCase):
    """Inside a Claude Code session (CLAUDE_CODE_SESSION_ID) the command says on stderr when this plugin's hooks do not run there."""

    START = ["metrics", "start", "a task"]

    def run_in(self, root, args, session=SID):
        return agent_steddy(args, root, **({"CLAUDE_CODE_SESSION_ID": session} if session else {}))

    def mark(self, root, plugin_root=None, session=SID):
        """The marker that the pre hook writes."""
        session_marker.mark(local_state.state_dir(root), session, plugin_root, 0.0)

    def test_a_session_whose_hooks_never_ran_gets_the_warning_and_nothing_else_changes(self):
        with project() as root:
            done = self.run_in(root, self.START)
            self.assertEqual(done.stderr, session_marker.NO_MARKER + "\n")
            self.assertTrue(done.stderr.startswith("agent-steddy: this plugin's hooks did not run in this session, so the guards, the gate reminder and the task clock are off."))
            self.assertIn("start a new Claude Code session in this project.", done.stderr)
            plain = self.run_in(root, ["metrics", "start", "a task", "--force"], session=None)
            self.assertEqual((done.returncode, done.stdout), (plain.returncode, plain.stdout))
            self.assertEqual((done.returncode, done.stdout), (0, "started: a task\n"))

    def test_the_warning_comes_before_a_refusal_and_the_exit_code_stays(self):
        with project() as root:
            self.assertEqual(self.run_in(root, self.START).returncode, 0)
            done = self.run_in(root, ["metrics", "start", "second"])
            self.assertEqual((done.returncode, done.stdout), (1, ""))
            lines = done.stderr.splitlines()
            self.assertEqual(lines[0], session_marker.NO_MARKER)
            self.assertTrue(lines[1].startswith("agent-steddy: refused: 'a task' has been running"), lines)

    def test_a_session_whose_hooks_run_another_copy_gets_both_versions_and_both_paths(self):
        with project() as root, tempfile.TemporaryDirectory() as tmp:
            cache = pathlib.Path(tmp).resolve() / "cache"
            (cache / ".claude-plugin").mkdir(parents=True)
            (cache / ".claude-plugin" / "plugin.json").write_text('{"version": "9.9.9"}')
            self.mark(root, cache)
            done = self.run_in(root, self.START)
            self.assertEqual(done.returncode, 0)
            self.assertEqual(done.stderr, f"agent-steddy: this is version {VERSION} at {ROOT}, but this session's hooks run version 9.9.9 at {cache}; call `agent-steddy` by name, not through a cache path.\n")

    def test_a_session_whose_hooks_run_this_copy_gets_nothing(self):
        with project() as root:
            self.assertEqual(self.run_in(root, ["metrics", "report"]).stderr, session_marker.NO_MARKER + "\n")
            self.mark(root)
            done = self.run_in(root, self.START)
            self.assertEqual((done.returncode, done.stdout, done.stderr), (0, "started: a task\n", ""))

    def test_the_marker_is_the_sessions_own(self):
        with project() as root:
            self.mark(root, session="another-session")
            self.assertEqual(self.run_in(root, self.START).stderr, session_marker.NO_MARKER + "\n")

    def test_the_pre_hook_is_what_silences_it(self):
        with project() as root:
            self.assertEqual(self.run_in(root, ["metrics", "report"]).stderr, session_marker.NO_MARKER + "\n")
            hook = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_use_id": "toolu_1", "session_id": SID, "tool_input": {"command": "agent-steddy metrics report"}}
            self.assertIsNone(run_hook("tool_timing.py", hook, root, env={"CLAUDE_PLUGIN_ROOT": str(ROOT)}, args=["pre"]))
            self.assertEqual(self.run_in(root, ["metrics", "report"]).stderr, "")

    def test_no_session_id_means_no_check(self):
        with project() as root:
            self.assertEqual(self.run_in(root, ["metrics", "report"]).stderr, session_marker.NO_MARKER + "\n")
            done = self.run_in(root, self.START, session=None)
            self.assertEqual((done.returncode, done.stderr), (0, ""))

    def test_a_project_that_is_not_a_git_repo_has_no_state_folder_and_no_check(self):
        find = ["lessons", "find", "anything"]
        with project() as root, tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(self.run_in(root, find).stderr, session_marker.NO_MARKER + "\n")  # the same command in a repo
            done = self.run_in(pathlib.Path(tmp).resolve(), find)
            self.assertEqual((done.returncode, done.stderr), (0, ""))

    def test_a_marker_that_cannot_be_read_is_silent(self):
        with project() as root:
            marker = local_state.state_dir(root) / "sessions" / SID
            marker.parent.mkdir(parents=True)
            self.assertEqual(self.run_in(root, ["metrics", "report"]).stderr, session_marker.NO_MARKER + "\n")  # no file yet
            for text in ("garbage", "[]", '{"root": 5}'):
                marker.write_text(text)
                self.assertEqual(self.run_in(root, ["metrics", "report"]).stderr, "", text)

    def test_guard_skips_the_check_because_scripts_and_eval_checks_call_it_and_it_does_not_need_the_hooks(self):
        with project() as root:
            self.assertEqual(self.run_in(root, ["metrics", "report"]).stderr, session_marker.NO_MARKER + "\n")  # the same session, a command that checks
            done = self.run_in(root, ["guard", "git stash", "--expect", "deny"])
            self.assertEqual((done.returncode, done.stderr), (0, ""))
            self.assertTrue(done.stdout.startswith("deny: [git-stash]"))

    def test_selftest_prints_the_result_as_its_second_line_and_does_not_repeat_it_on_stderr(self):
        with project() as root:
            expected = {
                "no marker": (None, session_marker.NOT_LIVE),
                "this copy": (True, f"hooks live in this session: yes, version {VERSION}"),
            }
            for name, (mark, line) in expected.items():
                if mark:
                    self.mark(root)
                done = self.run_in(root, ["metrics", "selftest"])
                self.assertEqual((done.returncode, done.stdout.splitlines(), done.stderr), (0, ["selftest ok", line], ""), name)
            self.assertEqual(self.run_in(root, ["metrics", "selftest"], session=None).stdout.splitlines(), ["selftest ok", session_marker.NOT_CHECKED])

    def test_selftest_names_the_other_copy_when_the_hooks_run_one(self):
        with project() as root, tempfile.TemporaryDirectory() as tmp:
            cache = pathlib.Path(tmp).resolve() / "cache"
            (cache / ".claude-plugin").mkdir(parents=True)
            (cache / ".claude-plugin" / "plugin.json").write_text('{"version": "9.9.9"}')
            self.mark(root, cache)
            line = self.run_in(root, ["metrics", "selftest"]).stdout.splitlines()[1]
            self.assertTrue(line.startswith(f"hooks live in this session: yes, version 9.9.9, but this command is version {VERSION} at {ROOT}"), line)


if __name__ == "__main__":
    unittest.main()
