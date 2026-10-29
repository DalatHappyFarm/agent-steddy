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
| `agents.allowed` | `["*"]` | `scripts/guard_agent.py` |
| `agents.models` | `{}` | `scripts/guard_agent.py` |
| `agents.writeFences` | `{}` | `scripts/guard_write.py` |
| `guards.disable` | `[]` | `scripts/guard_bash.py` |
| `handback.agents` | `[]` | `scripts/stop_check.py` |
| `handback.required` | a verification level and a retro line | `scripts/stop_check.py` |
| `commands.deny` | `[]` | `scripts/guard_bash.py` |
| `commands.askFromSubagent` | `[]` | `scripts/guard_bash.py` |
| `commands.alwaysAsk` | `[]` | `scripts/guard_bash.py` |
| `records.lessons` | `"docs/agents/lessons.md"` | planned: step 5 |
| `records.metrics` | `"docs/agents/metrics.jsonl"` | planned: step 5 |
| `records.decisions` | `"docs/agents/decisions.md"` | planned: step 5 |

- `workingBranch` is the branch agents work on and merge into.
- `verifyCommand` is the command that proves a change, or `null` when the project has none.
- `agents.allowed` is a list of agent type patterns; only those agent types may be started.
  The default `["*"]` allows every type, and `[]` allows none.
- `agents.models` maps an agent type pattern to the model that agent must run on, for example `"acme-docs": "haiku"`.
  The model name is matched as a substring of the model the call passes, ignoring case, so `haiku` accepts `claude-haiku-4-5`.
- `agents.writeFences` maps an agent type pattern to the list of path prefixes that agent may write, for example `"acme-auditor": ["docs/reviews/"]`.
  An agent type that matches no pattern is not fenced, and an empty list fences an agent out of every write.
- `guards.disable` is a list of built-in rule ids (see [Built-in rules](#built-in-rules)) that this project turns off.
  An id that no rule has is ignored, so a typo leaves the rule on.
- `handback.agents` is a list of agent type patterns whose final message is checked when they stop.
  The default `[]` checks no agent, so a project opts in.
- `handback.required` is a list of `{"id": "<name>", "pattern": "<regular expression>", "hint": "<text>"}` objects: what the final message of a checked agent must contain.
  The default asks for a verification level (the text `verif` in any case, or `L0` to `L5`) and a retro line (the text `retro` in any case).
  A list in the config replaces the default list.
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
The keys of `agents.models` and `agents.writeFences` and the items of `handback.agents` are agent type patterns too.
Matching is case-sensitive on every platform.

## Agent guard

`scripts/guard_agent.py` runs before the tool that starts a subagent (`Agent`, and `Task`, its older name).
It checks the call against the project config and denies it with a reason the agent reads, or says nothing to allow it:

1. The call's `subagent_type` must match a pattern of `agents.allowed`.
   A call that names no type is checked as `general-purpose`, the type Claude Code starts then.
2. When the call passes a `model` and a pattern of `agents.models` matches the type, the model must contain that pattern's model name.
   The first matching pattern wins, in the order of the file, so put a specific pattern such as `acme-docs` before a wide one such as `acme-*`.
   A call that passes no `model` is allowed, because the agent file carries its own model.

Everything fails open.
A value of the wrong type is read as the default (`allowed` as a string allows every type), a pattern whose model is not a string allows the call, an entry of the wrong type inside a list is skipped, and any error inside the hook allows the call.

## Write fence

`scripts/guard_write.py` runs before the file-writing tools (`Write`, `Edit`, `MultiEdit` and `NotebookEdit`).
It reads `agent_type` from the hook input and looks for the first pattern of `agents.writeFences`, in the order of the file, that matches it.
A match fences the agent: the file it writes (`file_path`, or `notebook_path` for a notebook) must be one of that pattern's prefixes or sit below one.
Anything else is denied, and the reason lists the allowed prefixes and the refused path.

- A prefix is relative to the project root and matches whole path parts, so `docs/reviews` allows `docs/reviews/a.md` and not `docs/reviews-old/a.md`.
  A trailing slash makes no difference, and a prefix can also be one file.
- The target is resolved before the check: `..` is applied and symlinks are followed, so a link inside a fenced folder cannot lead out of it.
  A relative target is taken from the hook input's `cwd`, as the tool does, and from the project root when there is none.
- The main session and an agent type that matches no pattern are never fenced.
  The hook input has `agent_type` inside a subagent, and in a main session started with `--agent`, which a fence then covers too.
- The fence guards the file-writing tools only.
  A write through the Bash tool (`echo > file`, `tee`, `sed -i`, a script) is not fenced by this hook, so give a fenced agent no way to write through Bash, or deny those commands with `commands.deny`.

The same fail-open rules as the agent guard apply: a fence that is not a list is ignored, a prefix that is not a string is skipped, and any error inside the hook allows the write.

## Hand-back check

`scripts/stop_check.py` runs when a subagent is about to stop (the `SubagentStop` event).
It reads `agent_type` and `last_assistant_message`, the final text of the agent, from the hook input.
When the agent type matches a pattern of `handback.agents` and the text lacks a `handback.required` item, it blocks the stop: the agent keeps working and reads one line that lists the `hint` of every missing item.
A `hint` falls back to the `id`, then to the `pattern`.

- A `pattern` is a Python regular expression, searched anywhere in the text and case-sensitive.
  A pattern that ignores case starts with `(?i)`, for example `(?i)retro`; inside a pattern, `(?i:...)` limits the flag to a group.
- The check blocks once.
  When the agent stops again after the block, the hook input has `stop_hook_active` set to true and the hook lets it stop, whatever the text says.
  So a hand-back that stays incomplete after one reminder ends the agent anyway; the check cannot trap a session.
- A hook input with no `last_assistant_message` text is not judged, and the agent may stop.
  An empty text lacks every item, so it is blocked.
- An item that is not an object with a string `pattern`, or whose pattern is not a valid regular expression, is skipped.
  A value of the wrong type is read as the default, and any error inside the hook lets the agent stop.

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
- Built-in rules share these limits.
  They stop the usual forms of a command and guard against honest mistakes; an agent set on getting around them, for example with `eval` or a command built from variables, can.

## Built-in rules

The rules built into `scripts/guard_bash.py`, such as denying `git stash` or asking before a force push, do not depend on the config.
They hold with no config file, with a broken one, and with any `commands.deny`.
Each has a short id, and the id leads the reason the agent sees, for example `[git-stash] Never git stash ...`.
The README lists every id.

Built-in rules use the same splitting and wrapper handling as the patterns above.
They do not match words in order; each reads the options of the program it guards.
For git that means its own options, such as `-C dir`, are skipped and the next word is the subcommand, so `git -C app stash` is a stash and `git log --grep stash` is not.

A project that must allow what a rule blocks lists the id in `guards.disable`:

```json
{ "guards": { "disable": ["sed-in-place"] } }
```

Only that rule is off; the others and the project's own `commands.deny` rules stay on.

The `secret-read` rule can be turned off like any other, but it should not be.
It is what keeps the values of `.env` files out of the conversation, and a value that reaches the conversation is leaked.
If an agent needs a secret, run the script that loads it instead of printing the file.
