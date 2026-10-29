"""PreToolUse hook (matcher Agent|Task): which agent types may be started, and on which model.

Reads the hook input as JSON on stdin and prints a deny, or nothing to allow.
`agents.allowed` lists the agent type patterns that may be started; `agents.models` maps an agent type pattern to the model name a passed `model` must contain.
Any internal error allows the call (prints nothing, exits 0), so a bug here never blocks a session.
"""
import fnmatch
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python3 -I leaves the script directory off the path
import project_config  # noqa: E402

DEFAULT_TYPE = "general-purpose"  # the agent type Claude Code starts when a call names none


def judge(tool_input, config):
    """The reason to deny an agent call, None to allow it.

    The type must match a pattern of `agents.allowed`.
    Then, when the call passes a `model` and a pattern of `agents.models` matches the type, the model must contain that pattern's model name.
    The first matching pattern, in file order, decides; a call that passes no model is fine, the agent file carries one.
    """
    agent = tool_input.get("subagent_type") or DEFAULT_TYPE
    model = tool_input.get("model")
    allowed = [pattern for pattern in project_config.get(config, "agents", "allowed") if isinstance(pattern, str)]
    if not any(fnmatch.fnmatchcase(agent, pattern) for pattern in allowed):
        return f"Agent type `{agent}` is not allowed in this project (agents.allowed). Allowed: {', '.join(allowed) or 'none'}."
    if isinstance(model, str) and model:
        for pattern, want in project_config.get(config, "agents", "models").items():
            if fnmatch.fnmatchcase(agent, pattern):
                if isinstance(want, str) and want.lower() not in model.lower():
                    return f'`{agent}` must run on {want} (agents.models). Drop the model parameter or pass "{want}".'
                break
    return None


def main():
    data = json.load(sys.stdin)
    reason = judge(data.get("tool_input") or {}, project_config.load())
    if reason:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": reason}}))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
