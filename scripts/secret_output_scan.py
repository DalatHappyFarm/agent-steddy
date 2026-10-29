"""Hook for the Bash tool (PostToolUse and PostToolUseFailure): hide and report a secret that a command printed.

Reads the hook input as JSON on stdin and prints nothing, or one JSON object with `additionalContext` that names the pattern, never the value.
It scans the last 200 KB of `stdout` and `stderr` with the patterns of `secret-patterns.txt`, and of `error` after a failed command.
After a command that succeeded it also returns `updatedToolOutput`: the Bash output object with each secret span replaced by [REDACTED:<pattern>] and every other field as received.
After a failure the hook can only warn (Claude Code reads `additionalContext` from that event and no replacement), so the secret stays in the text the agent sees.
Any internal error prints nothing and exits 0, so a bug here never hides or blocks a result.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python3 -I leaves the script directory off the path
import secret_patterns  # noqa: E402

MESSAGE = ("A secret matching {names} appeared in this command's output. "
           "Do not repeat or quote it, and tell the owner so the secret can be rotated.")


def scan(data):
    """The hook output for one hook input, None when the output holds no secret."""
    event = data.get("hook_event_name") or "PostToolUse"
    response = data.get("tool_response")
    names = []
    replacement = None
    if event == "PostToolUse" and isinstance(response, dict):
        replacement = dict(response)  # keeps `interrupted`, `isImage` and any other field as received
        for key in ("stdout", "stderr"):
            if isinstance(response.get(key), str):
                replacement[key], found = secret_patterns.redact(response[key])
                names += [name for name in found if name not in names]
    elif event == "PostToolUse" and isinstance(response, str):
        replacement, names = secret_patterns.redact(response)
    else:  # PostToolUseFailure: detect and warn only
        for text in (data.get("error"), response):
            if isinstance(text, str):
                names += [name for name in secret_patterns.find(text) if name not in names]
    if not names:
        return None
    output = {"hookEventName": event, "additionalContext": MESSAGE.format(names=", ".join(names))}
    if replacement is not None:
        output["updatedToolOutput"] = replacement
    return {"hookSpecificOutput": output}


def main():
    result = scan(json.load(sys.stdin))
    if result:
        print(json.dumps(result))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
