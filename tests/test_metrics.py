import contextlib
import datetime as dt
import json
import os
import pathlib
import sys
import statistics
import tempfile
import unittest
from unittest import mock

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

    def test_a_task_that_still_has_its_auto_name_is_refused_without_a_task_and_nothing_changes(self):
        for name, minutes_ago in [("a fresh auto start", 5), ("a stale one", 13 * 60), ("one named exactly `auto `", 0)]:
            with workspace() as (state, log_file):
                put(state, task=f"auto {ago(minutes_ago)}" if minutes_ago else "auto ", start=ago(minutes_ago))
                before = pending(state)
                for given in (None, ""):  # no --task, and an empty one
                    with self.assertRaises(Refuse) as raised:
                        finish(state, log_file, task=given)
                    self.assertEqual(raised.exception.code, 2, name)
                    message = str(raised.exception)
                    self.assertIn(f'the pending task is still named "{before["task"]}"', message)
                    self.assertIn('pass --task "<what was done>"', message)
                    self.assertIn('`agent-steddy metrics start "<task>"`', message)
                    self.assertIn("nothing was written and the clock is kept", message)
                    self.assertFalse(log_file.exists(), name)
                    self.assertEqual(pending(state), before, name)
                row = finish(state, log_file, task="named at log")  # the same clock logs once it is named
                self.assertEqual(row["task"], "named at log", name)
                self.assertFalse((state / local_state.PENDING).exists(), name)

    def test_a_named_task_logs_without_task_and_a_missing_task_keeps_its_own_refusal(self):
        with workspace() as (state, log_file):
            put(state, task="named", start=ago(3))
            self.assertEqual(finish(state, log_file)["task"], "named")
            with self.assertRaises(Refuse) as raised:  # no clock at all: the old refusal, with its exit code 1
                finish(state, log_file)
            self.assertEqual((raised.exception.code, str(raised.exception).startswith("no task")), (1, True))

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
                             ["Tasks (docs/agents/metrics.jsonl)", "  no rows yet", "", "Git rework (conventional commit prefixes)", "  no commits in this range",
                              "", "Verdicts, the last two weeks that have tasks", "  needs two weeks with tasks"])
            make_repo(repo)
            git(repo, "commit", "-q", "--allow-empty", "-m", "feat: a thing")
            git(repo, "commit", "-q", "--allow-empty", "-m", "fix: the thing")
            finish(state, log_file, task="t", minutes=5)
            lines = metrics.report(log_file, "docs/agents/metrics.jsonl", repo, 8)
            self.assertEqual(lines[0], "Tasks (docs/agents/metrics.jsonl)")
            self.assertIn("  5/", "\n".join(lines))  # the average of size S
            self.assertIn("50%", lines[lines.index("Git rework (conventional commit prefixes)") + 2])  # one fix of one feat and one fix
            self.assertEqual(sum(1 for line in lines if line.startswith("2")), 2)
            self.assertEqual(lines[-2:], ["Verdicts, the last two weeks that have tasks", "  needs two weeks with tasks"])  # one week only


A = [10, 20, 30, 40, 50]  # median 30, interquartile range 30 (statistics.quantiles, n=4)
C = [5, 10, 15, 20, 25]  # median 15, range 15
D = [10, 15, 20, 25, 30]  # median 20, range 15
E = [6, 11, 16, 21, 26]  # median 16, range 15
FASTER = ("faster", "slower")
BETTER = ("better", "worse")
NO_DIFFERENCE, INCONCLUSIVE = "no measurable difference", "inconclusive"


def share(passed, total):
    return [1] * passed + [0] * (total - passed)


class Verdict(unittest.TestCase):
    def test_the_numbers_the_cases_rely_on(self):
        for values, median, spread in [(A, 30, 30), (C, 15, 15), (D, 20, 15), (E, 16, 15)]:
            q = statistics.quantiles(values, n=4)
            self.assertEqual((statistics.median(values), q[2] - q[0]), (median, spread), values)

    def test_minutes_are_compared_by_median_against_half_the_larger_interquartile_range(self):
        cases = [
            ("a gap under half the range is no difference", A, [11, 21, 31, 41, 51], NO_DIFFERENCE),
            ("a gap of exactly half the range is a difference", A, C, "faster"),  # 15 is not less than 0.5 x 30
            ("a gap just under half the range is not", A, E, NO_DIFFERENCE),  # 14 < 15
            ("the larger range counts, not the smaller", A, D, NO_DIFFERENCE),  # 10 < 15 here, and 10 > 7.5 with the smaller range
            ("and in the other order", D, A, NO_DIFFERENCE),
            ("a long way up is slower", A, [60, 70, 80, 90, 100], "slower"),
            ("a long way down is faster", [60, 70, 80, 90, 100], A, "faster"),
            ("equal medians are no difference", A, A, NO_DIFFERENCE),
            ("no spread at all and the same value", [10] * 5, [10] * 5, NO_DIFFERENCE),
            ("no spread and a higher value is slower", [10] * 5, [12] * 5, "slower"),
            ("no spread and a lower value is faster", [12] * 5, [10] * 5, "faster"),
        ]
        for name, old, new, expected in cases:
            self.assertEqual(metrics.verdict(old, new, statistics.median, True, FASTER), expected, name)

    def test_fewer_than_five_tasks_in_either_week_is_inconclusive(self):
        cases = [([10] * 4, [10] * 10), ([10] * 10, [1] * 4), ([], A), (A, []), ([10] * 4, [10] * 4), ([10, 20], [30, 40])]
        for old, new in cases:
            self.assertEqual(metrics.verdict(old, new, statistics.median, True, FASTER), INCONCLUSIVE, (old, new))
        self.assertNotEqual(metrics.verdict(A, A, statistics.median, True, FASTER), INCONCLUSIVE)  # five and five is enough

    def test_the_share_is_better_when_higher_and_compared_the_same_way(self):
        cases = [
            ("a small spread and a big move", share(2, 10), share(8, 10), "better"),  # gap 0.6, ranges 0.25: threshold 0.125
            ("and back", share(8, 10), share(2, 10), "worse"),
            ("a middle share has a wide range, so 50% to 80% is no difference", share(5, 10), share(8, 10), NO_DIFFERENCE),  # gap 0.3, range 1: threshold 0.5
            ("equal shares", share(5, 10), share(5, 10), NO_DIFFERENCE),
            ("under five tasks", share(1, 4), share(4, 4), INCONCLUSIVE),
        ]
        for name, old, new, expected in cases:
            self.assertEqual(metrics.verdict(old, new, statistics.mean, False, BETTER), expected, name)

    def test_the_two_constants_are_the_whole_rule(self):
        self.assertEqual((metrics.MIN_TASKS, metrics.IQR_SHARE), (5, 0.5))
        self.assertEqual(metrics.verdict(A, E, statistics.median, True, FASTER), NO_DIFFERENCE)
        with mock.patch.object(metrics, "IQR_SHARE", 0.25):  # the threshold is now 7.5, and the gap is 14
            self.assertEqual(metrics.verdict(A, E, statistics.median, True, FASTER), "faster")
        with mock.patch.object(metrics, "MIN_TASKS", 6):
            self.assertEqual(metrics.verdict(A, A, statistics.median, True, FASTER), INCONCLUSIVE)


class Verdicts(unittest.TestCase):
    def rows(self, day, size, minutes, first_pass=True):
        return [{"date": day, "task": "t", "type": "new", "size": size, "minutes": value, "verify_first_pass": first_pass} for value in minutes]

    def test_it_compares_the_last_two_weeks_that_have_tasks_and_says_n_for_each(self):
        rows = [*self.rows("2026-09-07", "S", [1] * 6),  # an older week, not compared
                *self.rows("2026-10-05", "S", A), *self.rows("2026-10-05", "M", [30, 40, 50]), *self.rows("2026-10-05", "L", [60] * 5),  # W41
                *self.rows("2026-10-26", "S", [60, 70, 80, 90, 100]), *self.rows("2026-10-26", "M", [20] * 6), *self.rows("2026-10-27", "L", [60] * 5, first_pass=False)]  # W44, W42 and W43 are empty
        lines = metrics.verdicts(rows, 8)
        self.assertEqual(lines[0], "Verdicts, 2026-W41 vs 2026-W44 (rule: inconclusive when either week has fewer than 5 tasks of that size; otherwise the medians are compared, "
                                   "and a gap under 0.5 x the larger week's interquartile range is no measurable difference, else faster or slower, better or worse for the share)")
        table = [line.split() for line in lines[1:-1]]
        self.assertEqual(table[0], ["metric", "2026-W41", "2026-W44", "verdict"])
        self.assertEqual(lines[2], "  minutes S         median 30 (n=5)     median 80 (n=5)     slower")
        self.assertEqual(lines[3], "  minutes M         median 40 (n=3)     median 20 (n=6)     inconclusive")
        self.assertEqual(lines[4], "  minutes L         median 60 (n=5)     median 60 (n=5)     no measurable difference")
        self.assertEqual(lines[5], "  first-pass share  100% (n=13)         69% (n=16)          no measurable difference")  # 11 of 16 passed: the gap 0.31 is under half of the range 1
        self.assertEqual(lines[-1], "  (for the share each task counts 1 or 0, and the share stands where the median stands)")

    def test_the_share_counts_every_task_of_the_week_and_the_minutes_only_those_that_have_them(self):
        week = self.rows("2026-10-12", "S", A) + [{"date": "2026-10-12", "size": "S", "minutes": None, "verify_first_pass": False},
                                                    {"date": "2026-10-12", "size": "S", "minutes": "9", "verify_first_pass": False},
                                                    {"date": "2026-10-12", "size": "S", "minutes": True, "verify_first_pass": False},
                                                    {"date": "2026-10-12", "size": "S", "verify_first_pass": False}]
        lines = metrics.verdicts([*week, *self.rows("2026-10-19", "S", A)], 8)
        self.assertIn("median 30 (n=5)     median 30 (n=5)     no measurable difference", lines[2])
        self.assertIn("(n=9)", lines[5])  # all nine tasks of the first week count for the share

    def test_a_size_with_no_tasks_shows_n_0_and_is_inconclusive(self):
        lines = metrics.verdicts([*self.rows("2026-10-12", "S", A), *self.rows("2026-10-19", "S", A)], 8)
        self.assertIn("  minutes L         - (n=0)             - (n=0)             inconclusive", lines)

    def test_fewer_than_two_weeks_say_so_and_the_weeks_option_limits_the_pair(self):
        for rows, weeks in [([], 8), (self.rows("2026-10-12", "S", A), 8), ([*self.rows("2026-10-05", "S", A), *self.rows("2026-10-12", "S", A)], 1)]:
            self.assertEqual(metrics.verdicts(rows, weeks), ["Verdicts, the last two weeks that have tasks", "  needs two weeks with tasks"], (len(rows), weeks))

    def test_the_command_prints_the_verdicts_after_both_tables(self):
        with workspace() as (_, log_file), tempfile.TemporaryDirectory() as plain:
            log_file.parent.mkdir(parents=True)
            log_file.write_text("".join(json.dumps(row) + "\n" for row in [*self.rows("2026-10-12", "S", A), *self.rows("2026-10-19", "S", [60, 70, 80, 90, 100])]))
            lines = metrics.report(log_file, "m.jsonl", plain, 8)
            self.assertEqual([line for line in lines if line.startswith("Verdicts")][0][:36], "Verdicts, 2026-W42 vs 2026-W43 (rule")
            self.assertGreater(lines.index("Git rework (conventional commit prefixes)"), lines.index("Tasks (m.jsonl)"))
            self.assertIn("slower", "\n".join(lines))


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
