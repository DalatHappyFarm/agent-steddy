"""SubagentStop hook: block a subagent's first attempt to stop when its hand-back misses something the project requires, or when it leaves a dev port listening.

Reads the hook input as JSON on stdin and prints a block decision, or nothing to let the agent stop.
`handback.agents` lists the agent type patterns that are checked (none by default, so a project opts in) and `handback.required` the patterns the final message must contain.
`resources.ports` lists the TCP ports that must not be listening when a checked agent stops; one block names both what the hand-back misses and the ports that are busy.
It blocks once: when the agent is already continuing because of a stop hook (`stop_hook_active`), it is allowed to stop.
Any internal error lets the agent stop (prints nothing, exits 0), so a bug here never traps a session.
"""
import fnmatch
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python3 -I leaves the script directory off the path
import project_config  # noqa: E402

PROBE_SECONDS = 1  # the hook's own limit is 5 seconds


def port_spec(ports):
    """The ports and `a-b` ranges of `resources.ports` that are valid, as the list `lsof -iTCP:` takes; any other entry is skipped."""
    spec = []
    for entry in ports:
        text = str(entry) if isinstance(entry, int) and not isinstance(entry, bool) else entry.strip() if isinstance(entry, str) else ""
        found = re.fullmatch(r"(\d{1,5})(?:-(\d{1,5}))?", text)
        if found:
            low, high = int(found.group(1)), int(found.group(2) or found.group(1))
            if 0 < low <= high < 65536:
                spec.append(f"{low}-{high}" if high > low else str(low))
    return spec


def busy_ports(config):
    """The ports of `resources.ports` that something listens on, sorted; [] when none is set, `lsof` is missing or too slow, or anything else fails."""
    spec = port_spec(project_config.get(config, "resources", "ports"))
    if not spec:
        return []
    try:
        out = subprocess.run(["lsof", "-nP", f"-iTCP:{','.join(spec)}", "-sTCP:LISTEN"], capture_output=True, text=True, timeout=PROBE_SECONDS, stdin=subprocess.DEVNULL).stdout
    except Exception:  # the resources part is skipped, and the hand-back part still runs
        return []
    return sorted({int(port) for port in re.findall(r":(\d+) \(LISTEN\)", out)})


def judge(data, config):
    """The reason to block the stop, None to let the agent stop.

    The agent type must match `handback.agents`, and the hand-back (`last_assistant_message`) is searched for each `handback.required` regular expression.
    The reason lists the hint of every one it does not contain, and the ports of `resources.ports` that something listens on (`resources.hint` says what to stop).
    An item that is not an object with a string `pattern`, or whose pattern is not a valid regular expression, is skipped.
    """
    agent = data.get("agent_type")
    message = data.get("last_assistant_message")
    if data.get("stop_hook_active") is True or not (isinstance(agent, str) and agent and isinstance(message, str)):
        return None
    if not any(fnmatch.fnmatchcase(agent, pattern) for pattern in project_config.get(config, "handback", "agents") if isinstance(pattern, str)):
        return None
    missing = []
    for item in project_config.get(config, "handback", "required"):
        try:
            if not re.search(item["pattern"], message):
                missing.append(str(item.get("hint") or item.get("id") or item["pattern"]))
        except (TypeError, KeyError, re.error):
            continue
    busy = busy_ports(config)
    if not missing and not busy:
        return None
    parts = [f"Your hand-back is missing: {'; '.join(missing)}."] if missing else []
    if busy:
        hint = project_config.get(config, "resources", "hint").strip()
        what = f" ({hint})" if hint else ""
        parts.append(f"Resources still running: something listens on port(s) {', '.join(map(str, busy))}{what}. Release them, or say in your hand-back why they are kept.")
    parts.append("Fix this in your final message; this check blocks only once.")
    if busy:
        parts.append("Only your last message reaches the orchestrator, so end it with your full hand-back again, not just the resource note.")
    return " ".join(parts)


def main():
    reason = judge(json.load(sys.stdin), project_config.load())
    if reason:
        print(json.dumps({"decision": "block", "reason": reason}))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
