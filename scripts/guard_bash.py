"""PreToolUse hook (matcher Bash): deny shell commands that break work other agents share.

Reads the hook input as JSON on stdin and prints a deny decision, or nothing to allow.
Any internal error allows the command (prints nothing, exits 0), so a bug here never blocks a session.
"""
import json
import shlex
import sys

SEPARATORS = {";", "&&", "||", "|", "&", "(", ")"}
GIT_OPTIONS_WITH_VALUE = {"-C", "-c", "--git-dir", "--work-tree"}


def commands(line):
    """Split a shell line into simple commands (lists of words), honoring quotes and ; && || |."""
    lexer = shlex.shlex(line, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    current = []
    for word in lexer:
        if word in SEPARATORS:
            if current:
                yield current
            current = []
        else:
            current.append(word)
    if current:
        yield current


def git_subcommand(words):
    """`stash` for `git -C dir stash list`, None when the command is not git."""
    if not words or words[0].rsplit("/", 1)[-1] != "git":
        return None
    i = 1
    while i < len(words) and words[i].startswith("-"):
        i += 2 if words[i] in GIT_OPTIONS_WITH_VALUE else 1
    return words[i] if i < len(words) else None


def reason(line):
    """Why the command is denied, or None when it is allowed."""
    for words in commands(line):
        if git_subcommand(words) == "stash":
            return "Never git stash while agents share the working tree: it hides their changes. Commit by path instead."
    return None


def main():
    data = json.load(sys.stdin)
    why = reason((data.get("tool_input") or {}).get("command") or "")
    if why:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": why}}))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
