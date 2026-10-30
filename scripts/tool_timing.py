"""Hook for the Bash tool: log how long each command takes, for `agent-steddy metrics slow`.

  python3 -I tool_timing.py pre|post|fail     (the hook input as JSON on stdin)

`pre` (PreToolUse) stores the start time in a mark named after the tool call id.
`post` (PostToolUse) and `fail` (PostToolUseFailure) append one line to the tool timing log in the local state folder and delete the mark:
  {"ts": start time, "agent": agent type or "main", "ms": duration, "status": "ok" or "fail", "cmd": the command, normalized, 400 characters at most, "session_id": ..., "agent_id": ...}
`session_id` is the hook input's, and `agent_id` is its too and is left out in the main session; a line written before they existed has neither and stays readable.
The duration is the `duration_ms` that Claude Code reports when it does, which leaves out the wait for a permission prompt and for PreToolUse hooks; else it is the time from the mark to `post`.
A command that was denied or interrupted leaves a mark and no line; `metrics slow` deletes marks older than a day.
The command is normalized so that equal work groups together: a leading `cd <path> &&` is dropped, the project root and the cwd become relative paths, temp paths become <tmp>, heredoc bodies are removed, and secrets become [REDACTED:<pattern>].
After a failure (`fail`) the hook also looks at the tail of the log: when this session and this agent have now failed the same normalized command PREMISE_FAILS times in a row, it prints the premise nudge,
one `additionalContext` that tells the agent to stop, write down the premise its fixes share and test it (the gates skill, "attack the premise"). A success of that command resets the count; `nudges.premise` turns the nudge off.
Otherwise the hook prints nothing; it never blocks and exits 0 whatever happens.
"""
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python3 -I leaves the script directory off the path
import local_state  # noqa: E402
import project_config  # noqa: E402
import secret_patterns  # noqa: E402

CAP = 400
PREMISE_FAILS = 2  # failures of one command in a row that earn the premise nudge; docs/config.md states it
TAIL = 256 * 1024  # the nudge reads only this many bytes from the end of the log
NUDGE = ("This command failed {n} times in a row in this session. If the fixes between the runs rest on one premise, stop: "
         "write that premise as one sentence and test it before the next fix (gates skill, attack the premise).")
CD = re.compile(r"""\A\s*cd\s+(?:"[^"]*"|'[^']*'|\S+)\s*(?:&&|;|\n)\s*""")
HEREDOC = re.compile(r"(<<-?\s*(['\"]?)([A-Za-z_]\w*)\2[^\n]*)\n.*?(?:\n\s*\3[ \t]*(?=\n|\Z)|\Z)", re.S)
TMP = re.compile(r"(?:/private)?/(?:tmp|var/folders)/[^\s'\";|&)]*|\$\{?TMPDIR\}?[^\s'\";|&)]*")


def normalize(command, roots):
    """The command as the log stores it, before the secret scan and the length cap."""
    while True:
        match = CD.match(command)
        if not match:
            break
        command = command[match.end():]
    command = HEREDOC.sub(r"\1\n\n\3", command)  # body gone; an empty body and the terminator stay, so the end of the heredoc is still visible
    for root in sorted(set(roots), key=len, reverse=True):  # longest first: a worktree can sit inside the main repo
        if len(root) > 1:
            command = re.sub(re.escape(root.rstrip("/")) + r"(?:/|(?![\w.-]))", lambda m: "" if m.group(0).endswith("/") else ".", command)
    return TMP.sub("<tmp>", command)


def handle(mode, data, project, now):
    """Store the mark for `pre`, append the log line for `post` and `fail`. Returns the line, None when nothing was logged."""
    if data.get("tool_name") != "Bash":
        return None
    state = local_state.state_dir(project)
    if state is None:
        return None
    marks = state / local_state.MARKS
    mark = marks / re.sub(r"\W", "_", str(data.get("tool_use_id") or "none"))
    if mode == "pre":
        marks.mkdir(parents=True, exist_ok=True)
        mark.write_text(repr(now), encoding="utf-8")
        return None
    try:
        start = float(mark.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        start = None
    mark.unlink(missing_ok=True)
    ms = data.get("duration_ms")
    if not isinstance(ms, (int, float)) or isinstance(ms, bool) or ms < 0:
        ms = None
    if start is None and ms is None:
        return None  # no matching start: the hook was added in the middle of the command
    ms = round(ms) if ms is not None else round((now - start) * 1000)
    command = str((data.get("tool_input") or {}).get("command", ""))
    roots = [str(project), data.get("cwd") if isinstance(data.get("cwd"), str) else "", os.getcwd()]
    row = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(start if start is not None else now - ms / 1000)),
        "agent": data.get("agent_type") or "main",
        "ms": ms,
        "status": "fail" if mode == "fail" else "ok",
        "cmd": secret_patterns.redact(normalize(command, roots), cap=None)[0][:CAP],
    }
    for key in ("session_id", "agent_id"):
        if isinstance(data.get(key), str) and data[key]:
            row[key] = data[key]
    state.mkdir(parents=True, exist_ok=True)
    with (state / local_state.TIMES).open("a", encoding="utf-8") as log:
        log.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def tail_rows(log):
    """The rows in the last TAIL bytes of the log, oldest first; a line that is not a JSON object, such as the cut one at the start, is skipped."""
    with log.open("rb") as lines:
        size = lines.seek(0, os.SEEK_END)
        lines.seek(max(0, size - TAIL))
        text = lines.read().decode("utf-8", errors="replace")
    rows = []
    for line in text.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def failing_streak(rows, row):
    """How many of the latest runs of `row`'s command by its session and agent failed in a row, newest first; `row` is in `rows`.

    Runs of other commands, other sessions and other agents (and old lines that have no session) are not part of the count.
    """
    who = (row.get("session_id"), row.get("agent_id"), row["cmd"])
    count = 0
    for old in reversed(rows):
        if (old.get("session_id"), old.get("agent_id"), old.get("cmd")) == who:
            if old.get("status") != "fail":
                break
            count += 1
    return count


def premise_nudge(project, row):
    """The hook output that carries the premise nudge for the failure just logged as `row`, None when it should not speak."""
    state = local_state.state_dir(project)
    if state is None or not row.get("session_id"):  # no session to count within
        return None
    count = failing_streak(tail_rows(state / local_state.TIMES), row)
    if count < PREMISE_FAILS or not project_config.get(project_config.load(project), "nudges", "premise"):
        return None
    return {"hookSpecificOutput": {"hookEventName": "PostToolUseFailure", "additionalContext": NUDGE.format(n=count)}}


def run(mode, data, project, now):
    """What the hook prints for one hook input: the premise nudge after a failure that repeats, else None. The line is logged either way."""
    row = handle(mode, data, project, now)
    return premise_nudge(project, row) if mode == "fail" and row else None


def main():
    output = run(sys.argv[1], json.load(sys.stdin), local_state.project_dir(), time.time())
    if output:
        print(json.dumps(output))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
