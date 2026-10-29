"""PreToolUse hook (matcher Write|Edit|MultiEdit|NotebookEdit): keep a fenced agent type inside its own paths.

Reads the hook input as JSON on stdin and prints a deny, or nothing to allow.
`agents.writeFences` maps an agent type pattern to the path prefixes that agent may write; an agent type with no matching pattern, and the main session, are not fenced.
Only these file-writing tools are fenced: a write through the Bash tool (`echo > file`, `sed -i`, `tee`) is not.
Any internal error allows the write (prints nothing, exits 0), so a bug here never blocks a session.
"""
import fnmatch
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python3 -I leaves the script directory off the path
import project_config  # noqa: E402


def judge(data, config, project_dir):
    """The reason to deny a write, None to allow it.

    The fence is the first pattern of `agents.writeFences`, in file order, that matches the hook input's `agent_type`.
    The target (`file_path`, or `notebook_path`) must be one of the fence's prefixes or sit below one, after symlinks and `..` are resolved.
    A prefix is relative to the project dir and matches whole path parts, so `docs/reviews` does not allow `docs/reviews-old/a.md`.
    A relative target is taken from the hook input's `cwd`, as the tool does, else from the project dir.
    """
    agent = data.get("agent_type")
    tool_input = data.get("tool_input") or {}
    target = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not (isinstance(agent, str) and agent and isinstance(target, str) and target):
        return None
    for pattern, prefixes in project_config.get(config, "agents", "writeFences").items():
        if isinstance(prefixes, list) and fnmatch.fnmatchcase(agent, pattern):
            break
    else:
        return None
    root = os.path.realpath(project_dir)
    cwd = data.get("cwd") if isinstance(data.get("cwd"), str) else ""
    path = os.path.realpath(os.path.join(root, cwd, target))  # join drops what comes before an absolute part
    prefixes = [prefix for prefix in prefixes if isinstance(prefix, str)]
    for prefix in prefixes:
        base = os.path.realpath(os.path.join(root, prefix))
        if path == base or path.startswith(base.rstrip(os.sep) + os.sep):
            return None
    allowed = ", ".join(prefixes) or "nothing"
    return f"`{agent}` may write only under {allowed} (agents.writeFences in the project config). Refused path: {target}"


def main():
    data = json.load(sys.stdin)
    reason = judge(data, project_config.load(), os.environ.get("CLAUDE_PROJECT_DIR") or ".")
    if reason:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": reason}}))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
