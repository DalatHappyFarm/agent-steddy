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
| `commands.deny` | `[]` | `scripts/guard_bash.py` |
| `commands.askFromSubagent` | `[]` | planned: step 3 |
| `commands.alwaysAsk` | `[]` | planned: step 3 |
| `records.lessons` | `"docs/agents/lessons.md"` | planned: step 5 |
| `records.metrics` | `"docs/agents/metrics.jsonl"` | planned: step 5 |
| `records.decisions` | `"docs/agents/decisions.md"` | planned: step 5 |

- `workingBranch` is the branch agents work on and merge into.
- `verifyCommand` is the command that proves a change, or `null` when the project has none.
- `agents.allowed` is a list of agent type patterns; only those agent types may be started.
- `agents.models` maps an agent type pattern to the model that agent must run on, for example `"acme-docs": "haiku"`.
- `agents.writeFences` maps an agent type pattern to the list of path prefixes that agent may write, for example `"acme-auditor": ["docs/reviews/"]`.
  An agent type that matches no pattern is not fenced.
- `commands.deny` is a list of `{"match": "<words>", "reason": "<text>"}` objects; a matching command is always blocked and the agent sees the reason.
  A rule without a `reason` still blocks and says which rule matched.
- `commands.askFromSubagent` is a list of `"<words>"` patterns; a subagent that runs a matching command makes the owner confirm it.
- `commands.alwaysAsk` is a list of `"<words>"` patterns; a matching command makes the owner confirm it, whoever runs it.
- `records.*` are the paths, relative to the project root, of the lessons file, the metrics file and the decisions file.

## Patterns

Agent type patterns are `fnmatch` patterns: `*` matches any run of characters, `?` one character, `[ab]` one of a set.
So `"acme-*"` matches `acme-web` and `acme-docs`.
The keys of `agents.models` and `agents.writeFences` are agent type patterns too.

## Command matching

A command pattern is a few words, such as `"supabase config push"`.
It matches a simple command when the program's basename equals the first pattern word.
The command's positional words are the words that do not start with `-`, after the program.
Those positional words must start with the remaining pattern words.
So `supabase --debug config push --yes` and `/usr/local/bin/supabase config push` match, and `supabase config list` does not.
A line is split into simple commands at `;`, `&&`, `||`, `|` and `&`, so `cd app && supabase config push` matches too.
Quoted text is never a command, so `echo "supabase config push"` does not match.

Two limits to know:

- The value of an option counts as a positional word, so `supabase --workdir app config push` does not match.
  Write the rule for the form your agents use, or add a second rule.
- Wrappers such as `env`, `sudo` or `VAR=1 command` are not looked through.

## Built-in rules

The rules built into `scripts/guard_bash.py`, such as denying `git stash`, do not depend on the config.
They hold with no config file, with a broken one, and with any `commands.deny`.
