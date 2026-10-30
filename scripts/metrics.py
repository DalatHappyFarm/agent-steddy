"""Metrics for the work: the task clocks, one JSON line per finished task, the weekly report and the slow-command report.

Run as `agent-steddy metrics ...` (see cli.py).
Every function takes the files it reads and writes, so the tests call them directly and no path is fixed here: the metrics file is `records.metrics` of the project config and the local state is in the git common dir (local_state.py).

Two clocks, both local time:
  minutes         from `start` (or from the auto start the prompt hook wrote, when `start` was never called) to `log`: the work itself.
  prompt_minutes  from the owner's prompt that began the work (the auto start, kept as `prompt_start` when `start` runs after it) to `log`.
                  It includes the discussion before `start`.
                  It is null when no auto start existed (a second task of one prompt, since `log` deletes the clock) or when it is older than 12 hours (a prompt that never reached `log`).
The report averages `prompt_minutes` over the rows that have it.

The report ends with verdicts for the last two weeks that have tasks (see `verdicts`); the two constants below are the whole rule.
"""
import datetime as dt
import json
import os
import re
import statistics
import subprocess
import sys
import tempfile
import time
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python3 -I leaves the script directory off the path
import local_state  # noqa: E402
import tool_timing  # noqa: E402
from local_state import Refuse  # noqa: E402


# The verdict rule, in one place (docs/config.md states it): fewer than MIN_TASKS tasks in either week is inconclusive;
# otherwise a gap between the two weeks' medians under IQR_SHARE of the larger week's interquartile range is no measurable difference.
MIN_TASKS = 5  # at least 2, since an interquartile range needs two values
IQR_SHARE = 0.5


def _when(value):
    """A datetime from an ISO text, None when it is anything else."""
    try:
        return dt.datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _minutes(since, now):
    return round((now - since).total_seconds() / 60) if since else None


def _need_state(state):
    if state is None:
        raise Refuse("there is no local state folder for the task clock: the project is not in a git repo, and CLAUDE_PLUGIN_DATA is only set for hooks")


def start(state, task, force=False, now=None):
    """Name the task and start its clock. The auto start of the prompt hook is kept as `prompt_start`. Returns a line to print."""
    _need_state(state)
    now = now or dt.datetime.now()
    old = local_state.read_pending(state)
    running = str(old.get("task", ""))
    if running and not running.startswith("auto ") and not force:
        # sub-agents read the gates too: the clock of the running task is kept, never restarted from inside it
        raise Refuse(f"'{running}' has been running since {old.get('start')}; its clock is kept so a sub-agent does not restart it (--force replaces it)")
    auto = local_state.auto_start(old, now)  # an auto start from a prompt that never reached `log` is not this task's prompt
    prompt_start = auto.isoformat(timespec="seconds") if auto else old.get("prompt_start")
    state.mkdir(parents=True, exist_ok=True)
    (state / local_state.PENDING).write_text(json.dumps({"task": task, "start": now.isoformat(timespec="seconds"), "prompt_start": prompt_start}), encoding="utf-8")
    return f"started: {task}"


def log(state, log_file, size, task_type, verify_first_pass, task=None, roles="", agents=0, minutes=None, exposed=0, now=None):
    """Append one line for a finished task to `log_file` and close the clock. Returns the line as a dict."""
    now = now or dt.datetime.now()
    pending = local_state.read_pending(state) if state else {}
    task = task or pending.get("task")
    if not task:
        raise Refuse("no task: run `agent-steddy metrics start` first or pass --task")
    # a fresh auto start (renamed by --task or not) is itself the prompt time and the start of the work; a stale one is neither
    auto = local_state.auto_start(pending, now)
    is_auto = str(pending.get("task", "")).startswith("auto ")
    began = auto if is_auto else _when(pending.get("start"))
    prompt_began = auto or _when(pending.get("prompt_start"))
    row = {
        "date": now.date().isoformat(),
        "task": task,
        "type": task_type,
        "size": size,
        "roles": [role.strip() for role in roles.split(",") if role.strip()],
        "agents": agents,
        "minutes": minutes if minutes is not None else _minutes(began, now),
        "prompt_minutes": _minutes(prompt_began, now),
        "exposed": exposed,
        "verify_first_pass": verify_first_pass == "yes",
    }
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with log_file.open("a", encoding="utf-8") as lines:
        lines.write(json.dumps(row, ensure_ascii=False) + "\n")
    if state:
        (state / local_state.PENDING).unlink(missing_ok=True)
    return row


def week_of(day):
    year, week, _ = dt.date.fromisoformat(day).isocalendar()
    return f"{year}-W{week:02d}"


def read_rows(log_file):
    """The task lines of the metrics file; a line that is not a JSON object with a date is skipped."""
    rows = []
    for line in log_file.read_text(encoding="utf-8").splitlines() if log_file.exists() else []:
        try:
            row = json.loads(line)
            week_of(row["date"])
        except (ValueError, KeyError, TypeError, AttributeError):
            continue
        rows.append(row)
    return rows


def task_table(rows, weeks):
    by_week = defaultdict(list)
    for row in rows:
        by_week[week_of(row["date"])].append(row)
    out = ["week      tasks  new  feedback  avg_min(S/M/L)      prompt_min  exposed/task  verify_1st_pass"]
    for week in sorted(by_week)[-weeks:]:
        rs = by_week[week]

        def average(size, rs=rs):
            minutes = [r["minutes"] for r in rs if r.get("size") == size and r.get("minutes") is not None]
            return f"{sum(minutes) / len(minutes):.0f}" if minutes else "-"

        prompt = [r["prompt_minutes"] for r in rs if r.get("prompt_minutes") is not None]
        prompt_average = f"{sum(prompt) / len(prompt):.0f}" if prompt else "-"
        exposed = sum(r.get("exposed", 0) for r in rs) / len(rs)
        first_pass = sum(1 for r in rs if r.get("verify_first_pass")) / len(rs)
        new = sum(1 for r in rs if r.get("type") == "new")
        out.append(f"{week}  {len(rs):5d}  {new:3d}  {len(rs) - new:8d}  {average('S'):>4}/{average('M'):>4}/{average('L'):>4}      {prompt_average:>10}  {exposed:12.2f}  {first_pass:15.0%}")
    return out


def git_rows(root, weeks, today=None):
    """[(date, subject)] of the commits of the last `weeks` weeks; [] when `root` is not a repo or has no commits."""
    since = ((today or dt.date.today()) - dt.timedelta(weeks=weeks)).isoformat()
    done = subprocess.run(["git", "-C", str(root), "log", f"--since={since}", "--pretty=%ad|%s", "--date=short"], capture_output=True, text=True)
    return [line.split("|", 1) for line in done.stdout.splitlines() if "|" in line] if done.returncode == 0 else []


def git_table(pairs, weeks):
    """Commits per week by conventional prefix, and the share of fixes: rework = fix / (feat + fix)."""
    by_week = defaultdict(lambda: defaultdict(int))
    for day, subject in pairs:
        kind = subject.split(":", 1)[0].split("(", 1)[0].strip() if ":" in subject else "other"
        by_week[week_of(day)][kind if kind in ("feat", "fix", "docs", "chore") else "other"] += 1
    out = ["week      feat  fix  docs  chore  other  rework(fix/(feat+fix))"]
    for week in sorted(by_week)[-weeks:]:
        c = by_week[week]
        denominator = c["feat"] + c["fix"]
        rework = f"{c['fix'] / denominator:.0%}" if denominator else "-"
        out.append(f"{week}  {c['feat']:4d}  {c['fix']:3d}  {c['docs']:4d}  {c['chore']:5d}  {c['other']:5d}  {rework:>8}")
    return out


def verdict(old, new, center, lower_is_better, words):
    """The verdict on two weeks of values, `old` the earlier week: inconclusive, no measurable difference, or one of `words` (the word for a move in the good direction, then for the bad one).

    Fewer than MIN_TASKS values in either week is inconclusive.
    Otherwise the two weeks' centers (`center` of the values) are compared, and a gap under IQR_SHARE of the larger week's interquartile range (`statistics.quantiles`, n=4) is no measurable difference; equal centers never are a difference.
    """
    if min(len(old), len(new)) < MIN_TASKS:
        return "inconclusive"
    gap = center(new) - center(old)
    spread = max(q[2] - q[0] for q in (statistics.quantiles(old, n=4), statistics.quantiles(new, n=4)))
    if gap == 0 or abs(gap) < IQR_SHARE * spread:
        return "no measurable difference"
    return words[0] if (gap < 0) == lower_is_better else words[1]


def verdicts(rows, weeks):
    """Lines that compare the last two weeks that have tasks, among the `weeks` the tables show: minutes by size, and the first-pass share."""
    by_week = defaultdict(list)
    for row in rows:
        by_week[week_of(row["date"])].append(row)
    shown = sorted(by_week)[-weeks:]
    if len(shown) < 2:
        return ["Verdicts, the last two weeks that have tasks", "  needs two weeks with tasks"]
    old_week, new_week = shown[-2:]
    old, new = by_week[old_week], by_week[new_week]
    rule = (f"inconclusive when either week has fewer than {MIN_TASKS} tasks of that size; otherwise the medians are compared, and a gap under {IQR_SHARE:g} x the larger week's "
            "interquartile range is no measurable difference, else faster or slower, better or worse for the share")
    out = [f"Verdicts, {old_week} vs {new_week} (rule: {rule})", f"  {'metric':<18}{old_week:<20}{new_week:<20}verdict"]

    def line(name, old_values, new_values, center, shown_as, lower_is_better, words):
        cells = [f"{shown_as(center(values))} (n={len(values)})" if values else "- (n=0)" for values in (old_values, new_values)]
        out.append(f"  {name:<18}{cells[0]:<20}{cells[1]:<20}{verdict(old_values, new_values, center, lower_is_better, words)}")

    for size in ("S", "M", "L"):
        minutes = [[r["minutes"] for r in week if r.get("size") == size and isinstance(r.get("minutes"), (int, float)) and not isinstance(r.get("minutes"), bool)] for week in (old, new)]
        line(f"minutes {size}", *minutes, statistics.median, lambda value: f"median {value:g}", True, ("faster", "slower"))
    passed = [[1 if r.get("verify_first_pass") else 0 for r in week] for week in (old, new)]
    line("first-pass share", *passed, statistics.mean, lambda value: f"{value:.0%}", False, ("better", "worse"))
    out.append("  (for the share each task counts 1 or 0, and the share stands where the median stands)")
    return out


def report(log_file, label, root, weeks):
    """The weekly task table, the weekly git rework table and the verdicts on the last two weeks, as lines."""
    rows = read_rows(log_file)
    pairs = git_rows(root, weeks)
    return [f"Tasks ({label})", *(task_table(rows, weeks) if rows else ["  no rows yet"]),
            "", "Git rework (conventional commit prefixes)", *(git_table(pairs, weeks) if pairs else ["  no commits in this range"]),
            "", *verdicts(rows, weeks)]


# Commands whose second word names the work (`git commit`, `make test`), so it is part of the key.
SUBCOMMANDS = {"git", "make", "pnpm", "npm", "npx", "yarn", "gh", "docker", "cargo", "go", "kubectl", "terraform"}
# The slow tools, heaviest first: a chain of commands is keyed by its heaviest step.
HEAVY = ["pnpm", "npm", "yarn", "make", "cargo", "go", "docker", "node", "npx", "pytest", "python3 <script>", "git"]
# Glue and output filters: never the key of a command.
SKIP = {"cd", "do", "done", "then", "else", "fi", "for", "while", "until", "if", "{", "}", "export", "set", "true", ":", "head", "tail", "wc", "tee"}
CHAIN_MAX = 4
PATH_IN_BODY = re.compile(r"[\w@./-]+\.(?:md|py|ts|tsx|js|mjs|json|sh|sql|css|html|yml|yaml|toml)\b")
HEREDOC = re.compile(r"<<-?\s*(['\"]?)(\w+)\1[^\n]*\n.*?(?:\n\2(?=\n|$)|$)", re.S)


def split_chain(command):
    """Split on && || ; | and newlines outside quotes and $(...) / ( ... ) groups."""
    out, current, quote, depth, i = [], "", "", 0, 0
    while i < len(command):
        ch = command[i]
        if quote:
            quote = "" if ch == quote else quote
        elif ch in "\"'":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        elif depth == 0 and (ch in ";|\n" or command.startswith("&&", i)):
            out.append(current)
            current = ""
            i += 2 if command.startswith(("&&", "||"), i) else 1
            continue
        current += ch
        i += 1
    return out + [current]


def seg_key(segment, body=""):
    """The key of one simple command, the program plus its subcommand; '' for glue (cd, assignments, loop keywords)."""
    segment = re.sub(r"\s+<<.*$", "", segment.strip(), flags=re.S)  # the heredoc marker
    segment = re.sub(r"^(?:(?:do|then|else|\{)\s+|\w+=\S*\s+|/usr/bin/)+", "", segment)
    words = segment.split()
    if not words:
        return ""
    program = words[0].rsplit("/", 1)[-1] if words[0].startswith("/") else words[0]
    rest = words[1:]
    if program in SKIP or "(" in program or program.endswith("=") or re.match(r"\w+\(\)", program):
        return ""
    if program.startswith("python"):
        if rest[:1] == ["-I"]:
            rest = rest[1:]
        if rest[:1] == ["-"]:  # an inline script from stdin: name the file it edits when the body shows one
            found = PATH_IN_BODY.search(body)
            return f"{program} -I - ({found.group(0) if found else 'inline'})"
        return " ".join([program] + rest[:1])
    if program == "node":
        return " ".join([program] + [word for word in rest if not word.startswith("-")][:1])
    if program in SUBCOMMANDS:
        rest = re.sub(r"^(?:-C\s+\S+|--filter\s+\S+|-w|-r)\s*", "", " ".join(rest)).split()
        return " ".join([program] + [word for word in rest if not word.startswith("-")][:1])
    return program


def heavy_rank(key):
    name = key.split()[0]
    if name.startswith("python"):  # a script file ranks, inline stdin does not
        return HEAVY.index("python3 <script>") if "(" not in key else len(HEAVY)
    return HEAVY.index(name) if name in HEAVY else len(HEAVY)


def norm_cmd(command):
    """The group key of a logged command or chain: its heaviest known step, else the chain of step names."""
    text = re.sub(r"(/private)?/(tmp|var/folders)/\S+|\$TMPDIR\S*", "<tmp>", command.strip())
    body = text.split("\n", 1)[1] if "\n" in text else ""
    keys = []
    for segment in split_chain(HEREDOC.sub("", text)):
        key = seg_key(segment, body)
        if key and (not keys or keys[-1] != key):
            keys.append(key)
    cut = " > ?" if len(command.strip()) == tool_timing.CAP else ""  # the log cut the command: its tail may hold the heavy step
    if not keys:
        return "(empty)" if not text else "(shell glue)" + cut
    best = min(keys, key=heavy_rank)  # the first of the heaviest
    if heavy_rank(best) < len(HEAVY):
        return best
    return " > ".join(keys[:CHAIN_MAX]) + (" > ..." if len(keys) > CHAIN_MAX else "") + cut


def slow_rows(lines, since):
    """{key: [count, total ms, fails]} of the log lines that start at or after `since`; a line that cannot be read is skipped."""
    by_key = defaultdict(lambda: [0, 0, 0])
    for line in lines:
        try:
            row = json.loads(line)
            if dt.datetime.fromisoformat(row["ts"]) < since:
                continue
            entry = by_key[norm_cmd(row["cmd"])]
            entry[0] += 1
            entry[1] += row["ms"]
            entry[2] += row.get("status") == "fail"
        except (ValueError, KeyError, TypeError, AttributeError):
            continue
    return by_key


def slow_tables(by_key, top):
    if not by_key:
        return ["no timing rows yet (the tool timing hook fills the log while the plugin is enabled)"]

    def table(title, order):
        out = [title, "  count  total_s  avg_s  fails  key (normalized command)"]
        for key, (count, ms, fails) in sorted(by_key.items(), key=order, reverse=True)[:top]:
            out.append(f"  {count:5d}  {ms / 1000:7.1f}  {ms / count / 1000:5.1f}  {fails:5d}  {key}")
        return out

    return table("Top by total time", lambda item: item[1][1]) + [""] + table("Top by count", lambda item: item[1][0])


def slow(state, days, top, now=None):
    """The Bash commands of the last `days` days grouped by key, as lines. Also deletes start marks older than a day: orphans of denied or interrupted commands."""
    now = now or dt.datetime.now()
    times = state / local_state.TIMES if state else None
    lines = times.read_text(encoding="utf-8").splitlines() if times and times.exists() else []
    out = [f"Bash commands, last {days} days ({times})", *slow_tables(slow_rows(lines, now - dt.timedelta(days=days)), top)]
    marks = state / local_state.MARKS if state else None
    for mark in marks.glob("*") if marks and marks.is_dir() else []:
        if time.time() - mark.stat().st_mtime > 86400:
            mark.unlink(missing_ok=True)
    return out


def selftest():
    """A quick check of the command keys, the tables and the clocks on temporary files. Raises AssertionError when something is off."""
    from pathlib import Path
    for command, key in [("git show 1a2b3c4d5e", "git show"), ("cd /x && make test | tail -3", "make test"), ("FOO=1 pnpm --filter app test", "pnpm test"),
                         ("cp a b; sed s/a/b/ b; make build", "make build"), ("ls", "ls"), ("cp 1 2; mv 3 4; ls; cat 5; rm 6", "cp > mv > ls > cat > ...")]:
        assert norm_cmd(command) == key, (command, norm_cmd(command), key)
    now = dt.datetime(2026, 1, 5, 12, 0, 0)
    by_key = slow_rows([json.dumps({"ts": now.isoformat(), "ms": 4000, "status": "fail", "cmd": "make test"}), "not json"], now - dt.timedelta(days=1))
    assert by_key["make test"] == [1, 4000, 1], dict(by_key)
    ago = lambda minutes: (now - dt.timedelta(minutes=minutes)).isoformat(timespec="seconds")
    with tempfile.TemporaryDirectory() as folder:
        state, log_file = Path(folder) / "state", Path(folder) / "m.jsonl"
        state.mkdir()
        (state / local_state.PENDING).write_text(json.dumps({"task": f"auto {ago(30)}", "start": ago(30)}))
        start(state, "named", now=now)
        row = log(state, log_file, "S", "new", "yes", now=now)
        assert (row["task"], row["minutes"], row["prompt_minutes"]) == ("named", 0, 30), row
        assert not (state / local_state.PENDING).exists()
    assert "no timing rows" in slow_tables({}, 5)[0]
