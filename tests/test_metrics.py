import contextlib
import datetime as dt
import json
import os
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import local_state  # noqa: E402
import metrics  # noqa: E402
import tool_timing  # noqa: E402
from hook_runner import git, make_repo  # noqa: E402
from local_state import Refuse  # noqa: E402

NOW = dt.datetime(2026, 10, 29, 12, 0, 0)


def ago(minutes):
    return (NOW - dt.timedelta(minutes=minutes)).isoformat(timespec="seconds")


@contextlib.contextmanager
def workspace():
    """A temp state folder and a metrics file path (not created)."""
    with tempfile.TemporaryDirectory() as tmp:
        folder = pathlib.Path(tmp)
        (folder / "state").mkdir()
        yield folder / "state", folder / "docs" / "agents" / "metrics.jsonl"


def put(state, **pending):
    (state / local_state.PENDING).write_text(json.dumps(pending))


def pending(state):
    return json.loads((state / local_state.PENDING).read_text())


def finish(state, log_file, **kwargs):
    """Log a task the way the CLI does, with the fields the tests do not care about filled in; the last line of the file."""
    arguments = {"size": "S", "task_type": "new", "verify_first_pass": "yes", "now": NOW, **kwargs}
    metrics.log(state, log_file, **arguments)
    return json.loads(log_file.read_text().splitlines()[-1])


class Start(unittest.TestCase):
    def test_start_names_the_task_and_keeps_the_prompt_time_of_the_auto_start(self):
        with workspace() as (state, _):
            put(state, task=f"auto {ago(30)}", start=ago(30))
            self.assertEqual(metrics.start(state, "fix the build", now=NOW), "started: fix the build")
            self.assertEqual(pending(state), {"task": "fix the build", "start": ago(0), "prompt_start": ago(30)})

    def test_start_with_no_pending_task_has_no_prompt_time(self):
        with workspace() as (state, _):
            metrics.start(state, "a", now=NOW)
            self.assertEqual(pending(state), {"task": "a", "start": ago(0), "prompt_start": None})

    def test_a_running_named_task_is_not_replaced_unless_forced(self):
        with workspace() as (state, _):
            put(state, task="orchestrator", start=ago(20), prompt_start=ago(25))
            with self.assertRaises(Refuse) as raised:
                metrics.start(state, "sub-agent", now=NOW)
            self.assertIn("'orchestrator' has been running", str(raised.exception))
            self.assertEqual(pending(state), {"task": "orchestrator", "start": ago(20), "prompt_start": ago(25)})
            metrics.start(state, "replacement", force=True, now=NOW)
            self.assertEqual(pending(state), {"task": "replacement", "start": ago(0), "prompt_start": ago(25)})

    def test_an_auto_start_older_than_twelve_hours_is_not_the_prompt_time(self):
        with workspace() as (state, _):
            put(state, task=f"auto {ago(13 * 60)}", start=ago(13 * 60))
            metrics.start(state, "fresh", now=NOW)
            self.assertIsNone(pending(state)["prompt_start"])
            put(state, task=f"auto {ago(11 * 60)}", start=ago(11 * 60))
            metrics.start(state, "fresh", now=NOW)
            self.assertEqual(pending(state)["prompt_start"], ago(11 * 60))

    def test_without_a_state_folder_there_is_no_clock_to_start(self):
        with self.assertRaises(Refuse):
            metrics.start(None, "a")


class Log(unittest.TestCase):
    def test_log_after_start_writes_both_clocks_and_closes_the_clock(self):
        with workspace() as (state, log_file):
            put(state, task="named", start=ago(10), prompt_start=ago(30))
            row = finish(state, log_file, roles="web, docs,", agents=2, exposed=1, verify_first_pass="no")
            self.assertEqual(row, {"date": "2026-10-29", "task": "named", "type": "new", "size": "S", "roles": ["web", "docs"], "agents": 2,
                                   "minutes": 10, "prompt_minutes": 30, "exposed": 1, "verify_first_pass": False})
            self.assertFalse((state / local_state.PENDING).exists())

    def test_an_auto_start_that_was_never_named_is_both_clocks(self):
        with workspace() as (state, log_file):
            put(state, task=f"auto {ago(5)}", start=ago(5))
            row = finish(state, log_file)
            self.assertEqual((row["task"], row["minutes"], row["prompt_minutes"]), (f"auto {ago(5)}", 5, 5))

    def test_an_auto_start_named_only_at_log_is_still_the_prompt_time(self):
        with workspace() as (state, log_file):
            put(state, task=f"auto {ago(7)}", start=ago(7))
            row = finish(state, log_file, task="named at log")
            self.assertEqual((row["task"], row["minutes"], row["prompt_minutes"]), ("named at log", 7, 7))

    def test_an_auto_start_older_than_twelve_hours_is_neither_clock(self):
        with workspace() as (state, log_file):
            put(state, task=f"auto {ago(13 * 60)}", start=ago(13 * 60))
            row = finish(state, log_file, task="late")
            self.assertEqual((row["minutes"], row["prompt_minutes"]), (None, None))
            put(state, task=f"auto {ago(13 * 60)}", start=ago(13 * 60))
            self.assertEqual(finish(state, log_file, task="late", minutes=15)["minutes"], 15)

    def test_a_named_task_with_no_prompt_time_has_none(self):
        with workspace() as (state, log_file):
            put(state, task="t", start=ago(4), prompt_start=None)
            row = finish(state, log_file)
            self.assertEqual((row["minutes"], row["prompt_minutes"]), (4, None))

    def test_minutes_given_on_the_command_line_win(self):
        with workspace() as (state, log_file):
            put(state, task="t", start=ago(4), prompt_start=ago(9))
            row = finish(state, log_file, minutes=50)
            self.assertEqual((row["minutes"], row["prompt_minutes"]), (50, 9))

    def test_lines_are_appended_and_the_folder_of_the_file_is_created(self):
        with workspace() as (state, log_file):
            finish(state, log_file, task="one")
            finish(state, log_file, task="two")
            self.assertEqual([json.loads(line)["task"] for line in log_file.read_text().splitlines()], ["one", "two"])

    def test_a_task_name_is_needed_from_the_clock_or_the_command_line(self):
        with workspace() as (state, log_file):
            with self.assertRaises(Refuse):
                finish(state, log_file)
            self.assertFalse(log_file.exists())
            self.assertEqual(finish(state, log_file, task="no clock")["minutes"], None)  # a project with a clock still logs without one

    def test_log_works_without_a_state_folder_when_the_task_is_named(self):
        with workspace() as (_, log_file):
            row = finish(None, log_file, task="t", minutes=3)
            self.assertEqual((row["task"], row["minutes"], row["prompt_minutes"]), ("t", 3, None))


class Report(unittest.TestCase):
    ROWS = [
        {"date": "2026-10-12", "task": "a", "type": "new", "size": "S", "minutes": 10, "prompt_minutes": 30, "exposed": 0, "verify_first_pass": True},
        {"date": "2026-10-12", "task": "b", "type": "feedback", "size": "S", "minutes": 20, "exposed": 2, "verify_first_pass": False},  # an old row has no prompt_minutes
    ]

    def test_the_task_table_averages_by_week_and_size(self):
        table = metrics.task_table(self.ROWS, 8)
        self.assertEqual(len(table), 2)
        self.assertTrue(table[1].startswith("2026-W42"), table)
        self.assertIn("  15/   -/   -", table[1])
        self.assertIn("        30", table[1])  # only the row that has prompt_minutes counts
        self.assertIn("1.00", table[1])
        self.assertIn("50%", table[1])

    def test_only_the_last_weeks_are_shown(self):
        rows = [{**self.ROWS[0], "date": day} for day in ("2026-09-01", "2026-10-12", "2026-10-26")]
        table = metrics.task_table(rows, 2)
        self.assertEqual([line[:8] for line in table[1:]], ["2026-W42", "2026-W44"])

    def test_the_git_table_counts_conventional_prefixes_and_the_share_of_fixes(self):
        table = metrics.git_table([("2026-10-12", "feat(web): x"), ("2026-10-12", "fix(web): y"), ("2026-10-12", "fix: z"), ("2026-10-12", "Merge branch"), ("2026-10-12", "docs: d")], 8)
        self.assertIn("   1    2     1      0      1", table[1])
        self.assertIn("67%", table[1])
        self.assertTrue(metrics.git_table([("2026-10-12", "docs: d")], 8)[1].endswith("       -"))  # no feat and no fix: no share

    def test_unreadable_lines_of_the_metrics_file_are_skipped(self):
        with workspace() as (_, log_file):
            log_file.parent.mkdir(parents=True)
            good = json.dumps(self.ROWS[0])
            log_file.write_text("\n".join([good, "not json", "[1]", '{"no": "date"}', '{"date": "x"}', '{"date": 5}', "", good]) + "\n")
            self.assertEqual(len(metrics.read_rows(log_file)), 2)
            self.assertEqual(metrics.read_rows(log_file.parent / "missing.jsonl"), [])

    def test_the_report_joins_both_tables_and_tolerates_no_data(self):
        with workspace() as (state, log_file), tempfile.TemporaryDirectory() as plain, tempfile.TemporaryDirectory() as repo:
            self.assertEqual(metrics.report(log_file, "docs/agents/metrics.jsonl", plain, 8),
                             ["Tasks (docs/agents/metrics.jsonl)", "  no rows yet", "", "Git rework (conventional commit prefixes)", "  no commits in this range"])
            make_repo(repo)
            git(repo, "commit", "-q", "--allow-empty", "-m", "feat: a thing")
            git(repo, "commit", "-q", "--allow-empty", "-m", "fix: the thing")
            finish(state, log_file, task="t", minutes=5)
            lines = metrics.report(log_file, "docs/agents/metrics.jsonl", repo, 8)
            self.assertEqual(lines[0], "Tasks (docs/agents/metrics.jsonl)")
            self.assertIn("  5/", "\n".join(lines))  # the average of size S
            self.assertIn("50%", lines[-1])  # one fix of one feat and one fix
            self.assertEqual(sum(1 for line in lines if line.startswith("2")), 2)


class Slow(unittest.TestCase):
    CASES = [
        ("git show 1a2b3c4d5e", "git show"),
        ("cd /x/y && make test", "make test"),
        ("cd '/a dir'; cd x && pnpm verify 2>&1 | tail -5", "pnpm verify"),
        ("git status --short | head -5", "git status"),
        ("/usr/bin/git -C /x commit -m hi", "git commit"),
        ("FOO=1 BAR=x pnpm --filter app test", "pnpm test"),
        ("node tools/shot.mjs --all", "node tools/shot.mjs"),
        ("python3 -I scripts/report.py slow", "python3 scripts/report.py"),
        ("cd /x; python3 -I - <<'EOF'\np='docs/a.md'; s=open(p).read()\nEOF", "python3 -I - (docs/a.md)"),
        ("python3 - <<'EOF'\nprint(1)\nEOF", "python3 -I - (inline)"),
        ("rg -n foo docs | head", "rg"),
        ("cd /x\ncat > a.sh <<'EOF'\nx\nEOF", "cat"),
        ("", "(empty)"),
        # a chain is keyed by its heaviest known step, else by the chain of step names
        ("S=/tmp/a; for i in 1 2; do pnpm verify; sleep 1; done", "pnpm verify"),
        ("sed -i '' s/a/b/ f && make test | tail -3", "make test"),
        ("cp a b; sed -i '' s/a/b/ b; python3 -I scripts/x.py", "python3 scripts/x.py"),
        ("python3 -I - <<'E'\nx=1\nE\nnode a.mjs && git status", "node a.mjs"),
        ("echo a; git status; pytest -k 'a; b'", "pytest"),  # a quoted ; does not split
        ("cp a b; sed -i '' s/a/b/ b; cat b | head", "cp > sed > cat"),
        ("sed s/a/b/ f; sed s/c/d/ f; cp a b", "sed > cp"),  # consecutive repeats collapse
        ("cp 1 2; cp 3 4; mv 5 6; rm 7; ls; cat 8", "cp > mv > rm > ls > ..."),
        ("S=/tmp/a; for i in 1 2; do echo $i; done", "echo"),
        ("t(){ echo x; }; while true; do cat f; done", "cat"),
        ("S=/tmp/a; for i in 1 2", "(shell glue)"),
        # rows of the timing hook: cd and temp prefix gone
        ("cp <tmp>/a b; sed -i '' s/a/b/ b; for i in 1 2; do make test; done", "make test"),
        ("cat > f <<'EOF'\n\nEOF\npnpm verify", "pnpm verify"),
    ]

    def test_a_logged_command_gets_the_key_of_its_heaviest_step(self):
        for command, key in self.CASES:
            self.assertEqual(metrics.norm_cmd(command), key, command)

    def test_a_command_cut_at_the_cap_is_marked_because_its_tail_may_hold_the_heavy_step(self):
        prefix = "S=/tmp/a; for i in 1 2; do "
        full = prefix + "x" * (tool_timing.CAP - len(prefix))
        self.assertEqual(metrics.norm_cmd(full), "x" * (tool_timing.CAP - len(prefix)) + " > ?")
        self.assertEqual(metrics.norm_cmd(full + "x"), "x" * (tool_timing.CAP - len(prefix) + 1))
        self.assertEqual(metrics.norm_cmd("cp <tmp>/a b; sed s/a/b/ b; " + "x" * 300), "cp > sed > " + "x" * 300)

    def test_rows_are_grouped_by_key_within_the_period_and_unreadable_lines_are_skipped(self):
        old = (NOW - dt.timedelta(days=30)).isoformat()
        rows = [{"ts": NOW.isoformat(), "ms": 4000, "status": "ok", "cmd": "pnpm verify /tmp/abc123/x 42"},
                {"ts": NOW.isoformat(), "ms": 6000, "status": "fail", "cmd": "pnpm verify /private/tmp/zzz/y 7"},
                {"ts": NOW.isoformat(), "ms": 100, "status": "ok", "cmd": "git status"},
                {"ts": old, "ms": 99999, "status": "ok", "cmd": "ancient"}]
        by_key = metrics.slow_rows([json.dumps(r) for r in rows] + ["not json", "[1]", '{"ts": "x"}', '{"ts": 5, "cmd": "a", "ms": 1}'], NOW - dt.timedelta(days=7))
        self.assertEqual(dict(by_key), {"pnpm verify": [2, 10000, 1], "git status": [1, 100, 0]})

    def test_the_tables_list_the_heaviest_first(self):
        tables = metrics.slow_tables({"pnpm verify": [2, 10000, 1], "git status": [5, 100, 0]}, 10)
        self.assertEqual(tables[0], "Top by total time")
        self.assertTrue(tables[2].endswith("pnpm verify") and "10.0" in tables[2] and "    5.0" in tables[2], tables[2])
        self.assertTrue(tables[3].endswith("git status"))
        self.assertEqual(tables[5], "Top by count")
        self.assertTrue(tables[7].endswith("git status"))
        self.assertEqual(len(metrics.slow_tables({"a": [1, 1, 0], "b": [1, 2, 0]}, 1)), 7)  # --top 1 keeps one row per table
        self.assertIn("no timing rows", metrics.slow_tables({}, 5)[0])

    def test_slow_reads_the_log_of_the_state_folder_and_deletes_old_marks_only(self):
        with workspace() as (state, _):
            (state / local_state.MARKS).mkdir()
            old_mark, new_mark = state / local_state.MARKS / "old", state / local_state.MARKS / "new"
            old_mark.write_text("1")
            new_mark.write_text("1")
            os.utime(old_mark, (1, 1))
            (state / local_state.TIMES).write_text(json.dumps({"ts": NOW.isoformat(), "ms": 2500, "status": "ok", "cmd": "make test"}) + "\n")
            lines = metrics.slow(state, 7, 10, now=NOW)
            self.assertIn("last 7 days", lines[0])
            self.assertTrue(lines[3].endswith("make test"), lines)
            self.assertEqual([p.name for p in (state / local_state.MARKS).iterdir()], ["new"])

    def test_slow_with_no_log_or_no_state_says_so(self):
        with workspace() as (state, _):
            for folder in (state, None):
                self.assertIn("no timing rows", metrics.slow(folder, 7, 10, now=NOW)[1])


class Selftest(unittest.TestCase):
    def test_the_installed_scripts_pass_their_own_check(self):
        metrics.selftest()


if __name__ == "__main__":
    unittest.main()
