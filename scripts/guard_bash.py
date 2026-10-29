"""PreToolUse hook (matcher Bash): deny shell commands that break work other agents share.

Reads the hook input as JSON on stdin and prints a deny decision, or nothing to allow.
The built-in rules always hold; the project config (`commands.deny`) adds its own.
Any internal error allows the command (prints nothing, exits 0), so a bug here never blocks a session.
"""
import json
import os
import re
import shlex
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python3 -I leaves the script directory off the path

GIT_OPTIONS_WITH_VALUE = {"-C", "-c", "--git-dir", "--work-tree"}

# One shell token per match. A word keeps its quotes (unquoted later); `$(`, `;`, `|`, `&`, parentheses and backticks end a command.
# `&` inside a redirection such as `2>&1` or `&>file` stays in the word; the last branch skips a stray character such as an unterminated quote.
TOKEN = re.compile(r"""
    (?P<blank>[ \t\r]+|\\\n)
  | (?P<newline>\n)
  | (?P<comment>\#[^\n]*)
  | (?P<heredoc><<-?[ \t]*(?P<quote>['"]?)(?P<tag>\w+)(?P=quote))
  | (?P<word>(?:[^\s;|&()`'"\\<$]|&(?=>)|(?<=>)&|\$(?!\()|\\.|'[^']*'|"(?:[^"\\]|\\.)*")+|<+)
  | (?P<separator>\$\(|[;|&()`])
  | .
""", re.VERBOSE | re.DOTALL)


def split(line):
    """Split a shell line into simple commands (lists of words).

    Commands end at ; && || | & parentheses, backticks, `$(` and newlines.
    Quoted text stays inside its word, so it is never a command.
    Comments and heredoc bodies are skipped.
    """
    commands, words, heredocs = [], [], []
    pos = 0
    while pos < len(line):
        token = TOKEN.match(line, pos)
        pos = token.end()
        kind = token.lastgroup
        if kind == "word":
            words.append(shlex.split(token.group())[0])
        elif kind == "heredoc":
            heredocs.append(token.group("tag"))
        elif kind in ("newline", "separator"):
            if words:
                commands.append(words)
            words = []
            while kind == "newline" and heredocs:  # the bodies start on the next line
                tag = heredocs.pop(0)
                while pos < len(line):
                    end = line.find("\n", pos)
                    end = len(line) if end < 0 else end
                    body, pos = line[pos:end], end + 1
                    if body.strip() == tag:
                        break
    if words:
        commands.append(words)
    return commands


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

    The program is compared by basename; the other pattern words must appear in order among the command's words that do not start with `-`, not necessarily next to each other.
    So `supabase --workdir app config push --yes` matches "supabase config push" and `supabase config list` does not.
    """
    want = pattern.split()
    if not words or not want or words[0].rsplit("/", 1)[-1] != want[0]:
        return False
    positional = iter(word for word in words[1:] if not word.startswith("-"))
    return all(part in positional for part in want[1:])  # `in` on an iterator consumes up to the match: a subsequence test


def reason(line):
    """Why the command is denied, or None when it is allowed."""
    simple = split(line)
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
