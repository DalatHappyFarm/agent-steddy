"""PreToolUse hook (matcher Bash): deny shell commands that break work other agents share.

Reads the hook input as JSON on stdin and prints a decision, or nothing to allow.
The built-in rules hold with no config and with a broken one; the project config adds its own (`commands.deny`) and can turn built-in rules off (`guards.disable`).
Any internal error allows the command (prints nothing, exits 0), so a bug here never blocks a session.
"""
import json
import os
import re
import shlex
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python3 -I leaves the script directory off the path

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


ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
KEYWORDS = {"!", "{", "if", "then", "elif", "else", "while", "until", "do"}
# Wrappers that run the command after them, each with the options that take a separate value.
WRAPPERS = {
    "env": {"-u", "-C", "--unset", "--chdir"},
    "sudo": {"-u", "-g", "-h", "-p", "-C", "-D", "-R", "-T", "-U", "-r", "-t", "--user", "--group"},
    "command": set(),
    "nohup": set(),
    "time": set(),
    "nice": {"-n"},
    "exec": {"-a"},
}
SHELLS = {"bash", "sh", "zsh"}
MAX_SCRIPT_DEPTH = 3


def basename(word):
    return word.rsplit("/", 1)[-1]


def unwrap(words):
    """The command a simple command really runs: leading NAME=value words, shell keywords and wrappers (env, sudo, ...) with their options are skipped.

    A bare `env` has no command after it and stays as ["env"], because it prints the environment.
    """
    i, last = 0, None
    while i < len(words):
        word = words[i]
        name = basename(word)
        if ASSIGNMENT.match(word) or word in KEYWORDS:
            i += 1
        elif name in WRAPPERS:
            i, last = i + 1, name
            while i < len(words):
                if words[i] == "--":
                    i += 1
                    break
                if words[i] in WRAPPERS[name]:
                    i += 2
                elif words[i].startswith("-") or ASSIGNMENT.match(words[i]):
                    i += 1
                else:
                    break
        else:
            break
    return words[i:] or (["env"] if last == "env" else [])


def shell_script(words):
    """The script of `bash -c script` (also sh and zsh, and clusters such as `-lc`), None when the command is not that."""
    if not words or basename(words[0]) not in SHELLS:
        return None
    i = 1
    while i < len(words) and words[i].startswith("-"):
        if re.fullmatch(r"-[A-Za-z]*c[A-Za-z]*", words[i]):
            return words[i + 1] if i + 1 < len(words) else None
        i += 2 if words[i] in ("-o", "-O") else 1
    return None


def parse(line, depth=0):
    """Every simple command a shell line runs, with wrappers looked through; the script of `bash -c` is parsed as its own line."""
    for words in split(line):
        words = unwrap(words)
        script = shell_script(words)
        if script is not None and depth < MAX_SCRIPT_DEPTH:
            yield from parse(script, depth + 1)
        elif words:
            yield words


def matches(words, pattern):
    """True when a simple command runs the program named by the first pattern word, then the other pattern words.

    The program is compared by basename; the other pattern words must appear in order among the command's words that do not start with `-`, not necessarily next to each other.
    So `supabase --workdir app config push --yes` matches "supabase config push" and `supabase config list` does not.
    """
    want = pattern.split()
    if not words or not want or basename(words[0]) != want[0]:
        return False
    positional = iter(word for word in words[1:] if not word.startswith("-"))
    return all(part in positional for part in want[1:])  # `in` on an iterator consumes up to the match: a subsequence test


GIT_OPTIONS_WITH_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env", "--super-prefix"}


def git(words):
    """(subcommand, its arguments) of a git command, skipping git's own options such as `-C dir`; None when the command is not git."""
    if basename(words[0]) != "git":
        return None
    i = 1
    while i < len(words) and words[i].startswith("-"):
        i += 2 if words[i] in GIT_OPTIONS_WITH_VALUE else 1
    return (words[i], words[i + 1:]) if i < len(words) else None


def git_rule(subcommand, test=lambda args: True):
    """A rule test that is true when some command is `git <subcommand> <args>` with test(args)."""
    def check(commands):
        found = (git(words) for words in commands)
        return any(f and f[0] == subcommand and test(f[1]) for f in found)
    return check


# Built-in rules: (id, test over the parsed commands, reason). The id leads the reason and is what `guards.disable` lists.
DENY_RULES = [
    ("git-stash", git_rule("stash"), "Never git stash while agents share the working tree: it hides their changes. Commit by path instead."),
    ("git-reset-hard", git_rule("reset", lambda args: "--hard" in args),
     "git reset --hard discards uncommitted work that other agents may share. Undo with a new commit, or restore one file by path."),
]


def listed(config, section, key):
    """The list at config[section][key], or [] when the section or the key is missing or has another type."""
    section = config.get(section)
    value = section.get(key) if isinstance(section, dict) else None
    return value if isinstance(value, list) else []


def judge(line, agent_type, config):
    """("deny" | "ask", reason) for a shell line the rules stop, None to allow it.

    A deny beats an ask, and built-in rules come before the project config.
    Order: built-in deny, `commands.deny`, `commands.alwaysAsk`, then `commands.askFromSubagent` when `agent_type` is non-empty (a subagent).
    `guards.disable` turns built-in rules off by id.
    """
    commands = list(parse(line))
    off = {rule_id for rule_id in listed(config, "guards", "disable") if isinstance(rule_id, str)}

    def hit(pattern):
        return any(matches(words, pattern) for words in commands)

    def patterns(key):
        return [pattern for pattern in listed(config, "commands", key) if isinstance(pattern, str) and hit(pattern)]

    def built_in(rules):
        return [f"[{rule_id}] {why}" for rule_id, test, why in rules if rule_id not in off and test(commands)]

    deny = built_in(DENY_RULES)
    for rule in listed(config, "commands", "deny"):
        if isinstance(rule, dict) and isinstance(rule.get("match"), str) and hit(rule["match"]):
            why = rule.get("reason")
            deny.append(why if isinstance(why, str) and why else f"Denied by this project's agent-steddy config: {rule['match']}.")
    if deny:
        return "deny", deny[0]
    ask = [f"`{pattern}` needs the owner's confirmation (commands.alwaysAsk in the project config)." for pattern in patterns("alwaysAsk")]
    if agent_type:
        ask += [f"A subagent needs the owner's confirmation to run `{pattern}` (commands.askFromSubagent in the project config)."
                for pattern in patterns("askFromSubagent")]
    return ("ask", ask[0]) if ask else None


def main():
    data = json.load(sys.stdin)
    try:
        import project_config  # here, not at the top: the built-in rules hold even if the config cannot load
        config = project_config.load()
    except Exception:
        config = {}
    verdict = judge((data.get("tool_input") or {}).get("command") or "", data.get("agent_type"), config)
    if verdict:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": verdict[0], "permissionDecisionReason": verdict[1]}}))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
