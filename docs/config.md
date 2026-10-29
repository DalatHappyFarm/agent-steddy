# Project config

The kit holds the mechanism, each project holds its own settings.
This file is the seam between them: `.claude/agent-steddy.json` in the project root.
Every hook reads it through `scripts/project_config.py`.
A complete example is in [`examples/agent-steddy.json`](../examples/agent-steddy.json).

## Loading

The path is `<project_dir>/.claude/agent-steddy.json`.
`project_dir` is the `CLAUDE_PROJECT_DIR` environment variable, then the current directory.
A missing file gives the defaults.
Invalid JSON, or JSON whose top level is not an object, gives the defaults and one line on stderr that names the file.
The file's values override the defaults key by key at the top level and one level down.
Objects merge, lists and scalars replace.
So `{"agents": {"allowed": ["acme-*"]}}` replaces only `agents.allowed` and keeps the other `agents` defaults.
Unknown keys are kept and are not an error.

## Keys

| Key | Default | Read by |
| --- | --- | --- |
| `workingBranch` | `"main"` | planned: step 5 |
| `verifyCommand` | `null` | planned: step 5 |
| `agents.allowed` | `["*"]` | planned: step 4 |
| `agents.models` | `{}` | planned: step 4 |
| `agents.writeFences` | `{}` | planned: step 4 |
| `guards.disable` | `[]` | `scripts/guard_bash.py` |
| `commands.deny` | `[]` | `scripts/guard_bash.py` |
| `commands.askFromSubagent` | `[]` | `scripts/guard_bash.py` |
| `commands.alwaysAsk` | `[]` | `scripts/guard_bash.py` |
| `records.lessons` | `"docs/agents/lessons.md"` | planned: step 5 |
| `records.metrics` | `"docs/agents/metrics.jsonl"` | planned: step 5 |
| `records.decisions` | `"docs/agents/decisions.md"` | planned: step 5 |

- `workingBranch` is the branch agents work on and merge into.
- `verifyCommand` is the command that proves a change, or `null` when the project has none.
- `agents.allowed` is a list of agent type patterns; only those agent types may be started.
- `agents.models` maps an agent type pattern to the model that agent must run on, for example `"acme-docs": "haiku"`.
- `agents.writeFences` maps an agent type pattern to the list of path prefixes that agent may write, for example `"acme-auditor": ["docs/reviews/"]`.
  An agent type that matches no pattern is not fenced.
- `guards.disable` is a list of built-in rule ids (see [Built-in rules](#built-in-rules)) that this project turns off.
  An id that no rule has is ignored, so a typo leaves the rule on.
- `commands.deny` is a list of `{"match": "<words>", "reason": "<text>"}` objects; a matching command is always blocked and the agent sees the reason.
  A rule without a `reason` still blocks and says which rule matched.
- `commands.askFromSubagent` is a list of `"<words>"` patterns; a subagent that runs a matching command makes the owner confirm it.
  The main session runs the same command without asking.
  A subagent is a hook input with a non-empty `agent_type`.
- `commands.alwaysAsk` is a list of `"<words>"` patterns; a matching command makes the owner confirm it, whoever runs it.
- `records.*` are the paths, relative to the project root, of the lessons file, the metrics file and the decisions file.

## Decisions

A command gets one of three decisions: allow (the hook prints nothing), ask (the owner confirms in the permission prompt) or deny (the agent sees the reason and the command does not run).
When several rules match, the strictest decision wins and, within it, the first rule in this order:

1. built-in deny rules;
2. `commands.deny`;
3. built-in ask rules, which ask in every session;
4. `commands.alwaysAsk`;
5. `commands.askFromSubagent`, for a subagent only.

So a deny beats an ask, and a built-in rule beats a config rule.
This holds for a whole line: in `make deploy && supabase config push` the denied half blocks the line even though the other half only asks.
An ask is not a deny: the owner can approve it.

## Patterns

Agent type patterns are `fnmatch` patterns: `*` matches any run of characters, `?` one character, `[ab]` one of a set.
So `"acme-*"` matches `acme-web` and `acme-docs`.
The keys of `agents.models` and `agents.writeFences` are agent type patterns too.

## Command matching

A command pattern is a few words, such as `"supabase config push"`.
It matches a simple command when the program's basename equals the first pattern word.
The command's positional words are the words that do not start with `-`, after the program.
The remaining pattern words must appear in order among the positional words; other words may sit between them.
So `supabase --debug config push --yes`, `supabase --workdir app config push` and `/usr/local/bin/supabase config push` match, and `supabase config list` does not.
A line is split into simple commands at `;`, `&&`, `||`, `|`, `&`, newlines, backticks and `$(`, so `cd app && supabase config push` matches too.
Quoted text is never a command, so `echo "supabase config push"` does not match.
Heredoc bodies and comments are skipped.

Wrappers are looked through, at the start of a simple command and in any order:

- leading `NAME=value` assignments;
- `env`, `sudo`, `command`, `nohup`, `time`, `nice` and `exec`, with their options (`env -i FOO=1`, `sudo -u root`, `nice -n 10`) and, for `env` and `sudo`, assignments;
- the shell keywords `!`, `{`, `if`, `then`, `elif`, `else`, `while`, `until` and `do`.

The script of `bash -c`, `sh -c` and `zsh -c` (also `-lc` and similar option clusters) is checked as its own command line, up to three levels deep.
So `sudo -u root env FOO=1 supabase config push` and `bash -lc "cd app && supabase config push"` both match the pattern above.
A wrapper word further along does not count: `echo sudo supabase config push` does not match.

Limits to know:

- A pattern can match too much: `cli config push` also matches `cli config list push`, because the words only have to appear in order.
  Write the pattern with the fewest words that name the command.
- Commands that run other commands are not looked through: `xargs`, `find -exec`, `eval`, `watch`, shell scripts run by path, and a `$(...)` inside double quotes.
- A script nested in more than three `bash -c` levels is not read.

## Built-in rules

The rules built into `scripts/guard_bash.py`, such as denying `git stash` or asking before a force push, do not depend on the config.
They hold with no config file, with a broken one, and with any `commands.deny`.
Each has a short id, and the id leads the reason the agent sees, for example `[git-stash] Never git stash ...`.
The README lists every id.

A project that must allow what a rule blocks lists the id in `guards.disable`:

```json
{ "guards": { "disable": ["sed-in-place"] } }
```

Only that rule is off; the others and the project's own `commands.deny` rules stay on.
