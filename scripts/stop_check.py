"""SubagentStop hook: block a subagent's first attempt to stop when its hand-back misses something the project requires.

Reads the hook input as JSON on stdin and prints a block decision, or nothing to let the agent stop.
`handback.agents` lists the agent type patterns that are checked (none by default, so a project opts in) and `handback.required` the patterns the final message must contain.
It blocks once: when the agent is already continuing because of a stop hook (`stop_hook_active`), it is allowed to stop.
Any internal error lets the agent stop (prints nothing, exits 0), so a bug here never traps a session.
"""
import fnmatch
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python3 -I leaves the script directory off the path
import project_config  # noqa: E402


def judge(data, config):
    """The reason to block the stop, None to let the agent stop.

    The agent type must match `handback.agents`, and the hand-back (`last_assistant_message`) is searched for each `handback.required` regular expression.
    The reason lists the hint of every one it does not contain.
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
    if not missing:
        return None
    return f"Your hand-back is missing: {'; '.join(missing)}. Fix this in your final message; this check blocks only once."


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
