"""PreToolUse hook (matcher Bash): deny shell commands that break work other agents share.

Reads the hook input as JSON on stdin and prints a deny decision, or nothing to allow.
The built-in rules always hold; the project config (`commands.deny`) adds its own.
Any internal error allows the command (prints nothing, exits 0), so a bug here never blocks a session.
"""
import json
import os
import shlex
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python3 -I leaves the script directory off the path

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


def matches(words, pattern):
    """True when a simple command runs the program named by the first pattern word, then the other pattern words.

    The program is compared by basename; the command's words that do not start with `-` must begin with the rest of the pattern.
    So `supabase --debug config push --yes` matches "supabase config push" and `supabase config list` does not.
    """
    want = pattern.split()
    if not words or not want or words[0].rsplit("/", 1)[-1] != want[0]:
        return False
    positional = [word for word in words[1:] if not word.startswith("-")]
    return positional[:len(want) - 1] == want[1:]


def reason(line):
    """Why the command is denied, or None when it is allowed."""
    simple = list(commands(line))
    for words in simple:
        if git_subcommand(words) == "stash":
            return "Never git stash while agents share the working tree: it hides their changes. Commit by path instead."
    import project_config  # here, not at the top: the built-in rules above hold even if the config cannot load
    for rule in project_config.load()["commands"]["deny"]:
        if any(matches(words, rule["match"]) for words in simple):
            return rule.get("reason") or f"Denied by this project's agent-steddy config: {rule['match']}."
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
