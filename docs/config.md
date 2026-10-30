# Project config

The kit holds the mechanism, each project holds its own settings.
This file is the seam between them: `.claude/agent-steddy.json` in the project root.
Every hook reads it through `scripts/project_config.py`.
A complete example is in [`examples/acme/.claude/agent-steddy.json`](../examples/acme/.claude/agent-steddy.json).

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
| `workingBranch` | `"main"` | `scripts/record.py` |
| `verifyCommand` | `null` | `scripts/record.py` |
| `agents.allowed` | `["*"]` | `scripts/guard_agent.py` |
| `agents.models` | `{}` | `scripts/guard_agent.py` |
| `agents.writeFences` | `{}` | `scripts/guard_write.py` |
| `guards.disable` | `[]` | `scripts/guard_bash.py` |
| `handback.agents` | `[]` | `scripts/stop_check.py` |
| `handback.required` | a verification level and a retro line | `scripts/stop_check.py` |
| `commands.deny` | `[]` | `scripts/guard_bash.py` |
| `commands.askFromSubagent` | `[]` | `scripts/guard_bash.py` |
| `commands.alwaysAsk` | `[]` | `scripts/guard_bash.py` |
| `resume.folder` | `null` | `scripts/resume.py`, `scripts/session_start.py`, `scripts/record.py` |
| `reminder.enabled` | `true` | `scripts/gate_reminder.py` |
| `reminder.text` | the seven gates | `scripts/gate_reminder.py` |
| `records.lessons` | `"docs/agents/lessons.md"` | `scripts/record.py`, `scripts/lessons.py`, `scripts/gate_reminder.py` |
| `records.metrics` | `"docs/agents/metrics.jsonl"` | `scripts/metrics.py` |
| `records.decisions` | `"docs/agents/decisions.md"` | `scripts/record.py` |
| `records.roles` | `"docs/agents/roles"` | `scripts/lessons.py` |
| `records.walls` | `"docs/agents/walls.md"` | `scripts/lessons.py` |

- `workingBranch` is the branch agents work on and merge into; `record finish` fast-forwards it.
- `verifyCommand` is the command that proves a change, or `null` when the project has none.
  `record finish` runs it through a shell in the project root.
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
- `resume.folder` is where the [resume notes](#resume-notes) live: `null` keeps them in the local state, a folder relative to the project root (for example `docs/agents/resume`) keeps them in the repo, where the project can commit them by path so that other machines see them.
  An absolute path, or one with `..`, is refused.
- `reminder.enabled` turns the per-prompt reminder off when it is `false`; the task clock still starts.
- `reminder.text` is the text added to the context of every prompt; the default lists the seven gates.
  An empty text adds nothing.
- `records.*` are paths relative to the project root: the lessons file, the metrics file, the decisions file, the folder of the role cards and the walls file.
  The command creates the file and its folder when it first writes to it; the role cards are never created, since `lessons promote` writes into a card that exists (copy `templates/roles/role-card.md` from the plugin).
- `records.roles` is the folder of the role cards, one `<role>.md` for each role; `lessons promote --to <role>` writes into the card of that name, and `lessons check` reads every card of the folder.
- `records.walls` is the project's walls file, the rules that every role reads at gate 2; `lessons promote --to walls` appends to it and creates it when it is missing.

## Decisions

A command gets one of three decisions: allow (the hook prints nothing), ask (the owner confirms in the permission prompt) or deny (the agent sees the reason and the command does not run).
When several rules match, the strictest decision wins and, within it, the first rule in this order:

1. built-in deny rules;
2. `commands.deny`;
3. built-in ask rules, which ask in every session;
4. `commands.alwaysAsk`;
5. `commands.askFromSubagent`, for a subagent only.

So a deny beats an ask, and a built-in rule beats a config rule.
This holds for a whole line: in `make deploy && acme-cli config push` the denied half blocks the line even though the other half only asks.
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

## Secret output scan

`scripts/secret_output_scan.py` runs after every Bash command: in `PostToolUse` when the command succeeded and in `PostToolUseFailure` when it failed.
It looks for secrets in the last 200 KB of `stdout` and `stderr`, and in the `error` text of a failed command.
The patterns are in `scripts/secret-patterns.txt`, one per line: a name, a regular expression, and optionally a second expression for placeholders that are not secrets (`password`, `changeme`).
They cover the keys and tokens of common services (Anthropic, OpenAI, Stripe, Slack, Google, npm, GitLab, GitHub, AWS, Sentry and more; the file names every one), Postgres URLs with a password, and private key headers.
The patterns are not configurable yet.

When a pattern matches, the agent gets a note that names the pattern and never the value, and tells it not to repeat the secret and to report it to the owner.

- After a command that succeeded, the hook also replaces each secret span with `[REDACTED:<pattern name>]` in the output Claude reads (`updatedToolOutput`); every other field of the output comes back as received.
- After a failure Claude Code reads `additionalContext` only, so the hook warns and cannot replace the text.
- The command has already run when the hook fires.
  The replacement changes only what the agent sees, and telemetry captures the original output (Claude Code hooks reference).
  A leaked secret still has to be rotated.
- This is a safety net after the fact; the built-in `secret-read` rule is what keeps secret files out of the conversation in the first place.

The same fail-open rule applies: any internal error prints nothing and the output stays as it was.

## Local state

The kit keeps a little state per project, and none of it is committed: the pending task clock, the tool timing log and the resume notes.
It lives in the `agent-steddy` folder inside the git common dir, for example `.git/agent-steddy/`, so every worktree of a repo shares it.
The files:

- `pending-task.json` is the task clock, written by the prompt hook and read by `agent-steddy metrics`.
- `tool-times.jsonl` is the tool timing log, one line per Bash command.
- `tool-marks/` holds the start time of each Bash command that has not finished.
- `resume/` holds the [resume notes](#resume-notes), one file per branch, unless `resume.folder` puts them in the project.

Outside a git repo the hooks use a folder per project under `CLAUDE_PLUGIN_DATA`, and with neither they keep no state.
The resume notes are the exception: they live in the git common dir only, so a project that is not a git repo has no resume notes in the local state.
Claude Code gives `CLAUDE_PLUGIN_DATA` to hook processes and not to commands that the Bash tool runs.
So in a project that is not a git repo the hooks can write the state and the `agent-steddy` command cannot find it.

## Tool timing

`scripts/tool_timing.py` times every Bash command.
It runs three times per command: `pre` before it (`PreToolUse`), and `post` after a success (`PostToolUse`) or `fail` after a failure (`PostToolUseFailure`).
`pre` stores the start time under the tool call id; `post` and `fail` append one line to `tool-times.jsonl` and delete the mark:

```json
{"ts": "2026-10-29T17:40:02", "agent": "main", "ms": 2500, "status": "ok", "cmd": "make test"}
```

- `agent` is the agent type from the hook input, and `main` in the main session.
- `ms` is the `duration_ms` that Claude Code reports with the result when it does; that leaves out the time the owner took to answer a permission prompt.
  Otherwise it is the time from the mark to the `post` hook.
  A result with neither a duration nor a mark is not logged.
- `cmd` is normalized so that equal work groups together in `agent-steddy metrics slow`.
  A leading `cd <path> &&` is dropped, the project root and the working directory become relative paths, temp paths become `<tmp>`, and heredoc bodies are removed.
  Secrets are replaced by `[REDACTED:<pattern>]` with the patterns of the [secret output scan](#secret-output-scan), and the text is cut to 400 characters after that.
- A command that was denied or interrupted leaves a mark and no line; `metrics slow` deletes marks older than a day.
- The hook prints nothing, never blocks and exits 0 whatever happens.

## Gate reminder

`scripts/gate_reminder.py` runs when a prompt is submitted (`UserPromptSubmit`).
It does three things, and none can block the prompt.

1. It adds `reminder.text` to the context of the prompt, so the gates stay in front of the agent in a long session.
   The default text lists seven gates: intake, recall, shape, act, prove, record and deliver.
   A project writes its own text, for example one that names its own gates document, or sets `reminder.enabled` to `false`.
2. When a rule of the lessons file is due for promotion, it adds one more line to the same context: `Learning loop: <n> rule(s) seen twice and not promoted (<keys>); run agent-steddy lessons check.`
   The line names at most three keys, then `...`, and is left out when nothing is due, when the reminder is off or its text is empty, and when the lessons file cannot be read.
   It is one plain file read, and no git call.
3. It starts the task clock.
   When no task is pending, the time of the prompt becomes the start of an auto task named `auto <time>` in `pending-task.json` (see [Local state](#local-state)).
   `agent-steddy metrics start` names that task and keeps the prompt time as `prompt_start`; `metrics log` closes it and deletes the file.
   A pending task is never replaced, so a second prompt of the same task keeps the first start.
   The one exception is an auto task older than 12 hours, which was a prompt that never reached `metrics log`; the new prompt replaces it.

Claude Code discards the context of a `UserPromptSubmit` hook that reaches its timeout, so the hook does almost nothing: it reads the config, the lessons file and one small file.
The same fail-open rules apply: a value of the wrong type is read as the default and any error leaves the prompt as it was.

## Command line

`bin/agent-steddy` is the command for what a hook cannot do: name a task, write a line to the metrics file, show a report.
Claude Code puts the `bin/` folder of a plugin on the `PATH` of the Bash tool while the plugin is enabled, so an agent runs it as a bare `agent-steddy`.
Claude.ai and Cowork do not install a plugin that has a top-level `bin/` folder, so the plugin installs in Claude Code only.
The command only dispatches to `scripts/cli.py`, which runs isolated (`python3 -I`) like the hooks.

The Bash tool does not give `CLAUDE_PROJECT_DIR` to the commands it runs.
So the command finds the project itself: `CLAUDE_PROJECT_DIR` when it is set, else the nearest folder from the working directory up that has `.claude/agent-steddy.json` or `.git`.
It reads the project config from there, and every path it writes comes from that config.
A command that is refused prints the reason on stderr after `agent-steddy: refused:` and exits 1.
The learning loop's refusals that ask for another key or target (a rule with no key, a bad key, a promotion that is not allowed) exit 2, the code of a usage error, so a caller can tell them from a failed record.
`pause` and `resume` exit 2 as well when there is no branch or repo to work with: a detached HEAD, a repo with no commit, a project that is not a git repo, a `resume.folder` outside the project.

## Metrics

`agent-steddy metrics` measures the work.
It writes to `records.metrics`, a JSON lines file that the project commits, and keeps the clock of the task in progress in the [local state](#local-state).

| Command | What it does |
| --- | --- |
| `metrics start "<task>" [--force]` | Names the task and starts its clock. It refuses when a named task is already running, so a sub-agent that reads the gates does not restart the clock of the task it works for; `--force` replaces it. |
| `metrics log --size S\|M\|L --type new\|feedback --verify-first-pass yes\|no [--task T] [--roles a,b] [--agents N] [--minutes N] [--exposed N]` | Appends one line to the metrics file and deletes the clock. `--task` defaults to the name given to `start`; `--minutes` replaces the clock. |
| `metrics report [--weeks 8]` | Prints a table per week of tasks (count, average minutes by size, average prompt minutes, defects found by the owner per task, share of first-pass verifications) and a table per week of commits by conventional prefix, with the share of fixes as rework. |
| `metrics slow [--days 7] [--top 10]` | Prints the Bash commands of the [tool timing](#tool-timing) log grouped by key, by total time and by count. A command line is keyed by its heaviest known step, else by the chain of its steps. |
| `metrics selftest` | Checks the installed scripts on temporary files and prints `selftest ok`. |

A line of the metrics file has these fields: `date`, `task`, `type` (`new` for a fresh request, `feedback` for an owner round on earlier work), `size`, `roles`, `agents`, `minutes`, `prompt_minutes`, `exposed` (defects the owner found in work that was already delivered), `verify_first_pass`.

There are two clocks, both in local time:

- `minutes` runs from `start` to `log`, which is the work itself.
  When `start` was never called it runs from the auto start that the [prompt hook](#gate-reminder) wrote.
- `prompt_minutes` runs from the prompt that began the work to `log`, so it includes the discussion before `start`.
  It starts at the auto start, which `start` keeps as `prompt_start`, and an auto start that only `log` names is still the prompt time.
  It is `null` when there was no auto start, as for a second task of the same prompt (`log` deletes the clock), and when the auto start is older than 12 hours: that was a prompt that never reached `log`, and it is not the prompt of the task being logged now.
  A stale auto start also gives a `null` for `minutes`, unless `--minutes` is given.
- The report averages `prompt_minutes` over the lines that have it.

`metrics log` does not need the clock: with `--task` and `--minutes` it works in a project that has no local state.
`start` needs it and refuses without one.
A line that is not a JSON object with a `date` is skipped by the report.

## Records

`agent-steddy record` writes down what a task decided and learned, and ends it.

| Command | What it does |
| --- | --- |
| `record decision "<area>" "<text>"` | Appends `- [area] text` to `records.decisions`. The area is a short tag of letters, digits, spaces and `_ . / -`; the area and the text are one line each. A missing file is created with a short header. |
| `record lesson --task T --roles a,b --worked W --exposed E --rule R [--key K]` | Puts an entry at the top of `records.lessons`, above the older ones: a heading `## <date> - <task> - roles: a, b` and the three lines Worked, Exposed and Rule. A rule other than `none` takes a key, see [Learning loop](#learning-loop). A missing file is created from a template: a title, the entry format in a code fence, and how a repeated rule moves up. A heading inside a code fence is not an entry. |
| `record finish <branch> [--full] [--no-verify]` | Verifies a branch and merges it into `workingBranch`, and deletes the branch's [resume note](#resume-notes), see below. |

`record finish` is the merge at the end of a task, and it never pushes.
It refuses when the branch does not exist, is the working branch, or does not fast-forward onto it, and when the working tree has uncommitted or untracked files.
Then:

1. It checks out the branch, runs `verifyCommand` through a shell in the project root, and goes back to the branch it came from, so the proof is of the branch itself.
   `--full` appends ` --full` to the command, for a verify script that scopes itself to what the branch changed and checks everything with that flag.
2. When the command fails it merges nothing, keeps the branch, and prints the last 40 lines of the output.
3. When it passes it checks out `workingBranch`, merges the branch with `git merge --ff-only`, and deletes the branch with `git branch -d`.
4. It then deletes the branch's [resume note](#resume-notes) when there is one, and says so.
   A note kept in the repo (`resume.folder`) does not count as an uncommitted file in the clean-tree check, so it never blocks the merge.
   When that note was committed, the deletion is left uncommitted and the output says to commit it by path.
   A note that cannot be deleted never undoes the merge; the output says it was not cleared.

With no `verifyCommand` nothing proves the branch, so the command refuses unless `--no-verify` is given.
With a `verifyCommand`, `--no-verify` is refused: a gate the project set is not skipped by a flag.
The command runs git itself and not through the Bash tool, so the Bash rules do not see it; it uses only `switch`, `merge --ff-only` and `branch -d`.

## Resume notes

A task that stops before it is done leaves a resume note, so the next session carries on from what is on disk and does not redo it.
`agent-steddy pause` writes the note, `agent-steddy resume` reads it, and a `SessionStart` hook points at it.
The method for when to pause and how to pick up is in the [gates skill](../skills/gates/SKILL.md#pause-and-pick-up).

There is one note per branch, in the file `<branch with "/" replaced by "__">.md`, so the note of `feat/x` is `feat__x.md`.
Two branch names that map to the same file name (`feat/x` and `feat__x`) share it, and a note is shown only for the branch its `Branch:` line names, so the other branch sees no note.
The folder is `resume.folder` of the project, else `resume/` in the [local state](#local-state): never committed and shared by every worktree of the repo.
Notes kept in the project are not committed by the kit either; the project commits them by path when other machines should see them.

| Command | What it does |
| --- | --- |
| `pause --intent I --done D --next N [--open O] [--pitfalls P] [--files a,b]` | Writes the note of the checked out branch and replaces the branch's older one. `--intent`, `--done` and `--next` are required single lines; `--done` says what is done and how it was verified, with the ladder level. `--open` and `--pitfalls` are single lines, `--files` is a comma separated list, and each one left out reads `none`. It commits nothing, and for a note kept in the repo it says to commit the file by path. |
| `resume [--branch B]` | Prints the note of the branch (the checked out one by default), then what changed since it, then a reminder that the note is a claim. |
| `resume [--branch B] --clear` | Deletes the note. A branch with no note is not an error. |

`pause` exits 2, writing nothing, on a detached HEAD, in a repo with no commit and outside a git repo; `resume` exits 2 on a detached HEAD without `--branch` and outside a git repo.
An empty or multi-line value exits 1, like the other commands.
`resume` for a branch with no note prints that and exits 0.

The note has a fixed shape (the date is local time):

```text
# Resume note: feat/x

- Date: 2026-10-30 14:05
- Branch: feat/x
- HEAD: <the full commit hash> <its subject>
- Base: main (merge base <12 characters of the hash>)

## Committed since the base
<git diff --stat from the merge base to HEAD, or none>

## Uncommitted files
- M path
- ?? path

## Intent
## Done and verified
## Open decisions
## Next step
## Key files
## Pitfalls
```

- The base is `workingBranch`.
  When that branch does not exist the note says so and has no diff.
  A long `git diff --stat` keeps its first lines and its summary line.
- The uncommitted files are the `git status --porcelain` lines, untracked files included, and the note folder itself is left out when it is in the repo.
- `resume` prints the note as written, then `Since the note`: the commits after the note's HEAD (`git log --oneline <head>..<branch>`) and the uncommitted files now, then one closing line: the note is a claim, not evidence; check Done against git and run the verify command (`verifyCommand` when set); do not redo what git shows is done.
  When the note's HEAD is not an ancestor of the branch (a rebase or a reset), or is not in the repo at all, it says so and names `git log <workingBranch>..<branch>` instead.
  For another branch than the checked out one (`--branch`) the uncommitted files are not listed, since they belong to the checkout.
- The note is written by `pause` and meant to be read by `resume`; a note edited by hand still prints, and one with no `HEAD:` line has no `Since the note` list.

`scripts/session_start.py` runs on `SessionStart`, for every source (`startup`, `resume`, `clear`, `compact` and `fork`); `compact` is the one that matters most, since the context was just summarized.
When the checked out branch has a note it adds one line to the context: `Resume note for <branch> from <date>: run agent-steddy resume before you start.`
It prints nothing otherwise, and it calls git only when the note folder holds a note.
It fails open: an error, a broken config, an unusable `resume.folder`, a detached HEAD and a project that is not a git repo all print nothing, and it exits 0 whatever happens.

## Learning loop

A rule that repeats is worth more than a rule written once, so the kit counts the repeats and writes the promotion.
The counting needs a name for each rule: the key.

### Rule lines and keys

The Rule line of an entry has an optional key right after `Rule`, and a promoted rule ends with a marker:

```text
## 2026-10-30 - fix the footer - roles: web, docs
- Worked: the brief named the files
- Exposed: a commit took a neighbor's file
- Rule [commit-by-path]: commit by path, never git add all [promoted -> docs/agents/roles/web.md]
```

- A key is a lowercase slug, `[a-z0-9]+(-[a-z0-9]+)*`, at most 40 characters.
- A rule of `none` (any case) needs no key, and a key passed with it is ignored.
- A line with no key, as in a file from before keys, still parses; `lessons check` lists it with a suggested key, and adding the key to the line by hand migrates it.
- The marker ` [promoted -> <path>]` is written by `lessons promote`; the path is relative to the project root.
  A key is promoted when any of its Rule lines carries the marker, and a promoted key is never due again.
- The roles of an entry are read from its heading, so name them as the role cards are named: `web` for `docs/agents/roles/web.md`.
- The newest entry of a key is the one with the latest date, and the one higher in the file when the dates are equal.

### Recording a rule

`record lesson` with a rule other than `none` and no `--key` writes nothing, exits 2 and prints the closest recorded rules, up to five, each as `<key> (seen <n> times): <newest rule text>`, then `re-run with --key <existing> if it is the same rule, or --key <new-slug> if it is new`.
With no keyed rule recorded yet it says so and asks for a new slug.
The ranking is the mean of two numbers from 0 to 1 for the rule texts: the `difflib` ratio of their words, and the share of words they have in common; the best score of the key's entries counts, and ties go by key.
It is a rough aid for choosing, not a decision.

After writing with a key, the command counts the entries that carry it.
At two or more, and when the key is not promoted, it prints `<key> is now seen <n> times`, the command `agent-steddy lessons promote <key> --to <role>` with the role that the headings of those entries name most often, the roles with their counts, and a line that a rule about safety, data or money goes `--to walls` instead.
The threshold is the constant 2 in `scripts/lessons.py`; it is not a config key.

### lessons check

| Command | What it does |
| --- | --- |
| `lessons check` | Prints three sections and exits 0, a report and not a gate. Each section says `none` when it is empty. |
| `lessons check --quiet` | Prints the one line that the prompt reminder adds, and nothing when no rule is due. |

1. Due: every key seen twice or more and not promoted, with its dates, its tasks, its roles and the promote command.
2. Unkeyed: every Rule line with no key and a rule other than `none`, with a suggested key (the first four words that are not common function words, joined by hyphens), and the pairs of those lines whose rule texts look alike (the same score as above, from 0.45), at most ten.
3. Cards to prune: each card of `records.roles` whose `## Pitfalls` section has more than 12 bullets, and the pairs of pitfalls in one card that look alike, at most ten a card.
   Only the first line of a top-level bullet counts, a `(lessons: ...)` note is left out of the comparison, and a placeholder bullet (`None recorded yet ...` or one in angle brackets) is not a pitfall.

### lessons promote

`lessons promote <key> --to <role|walls> [--text "<final wording>"] [--force]` moves a rule up:

1. `--to <role>` appends `- <text> (lessons: <date>, <date>)` as the last bullet of the `## Pitfalls` section of the card `<records.roles>/<role>.md`; the section is added at the end when the card has none, and a placeholder bullet of the section is replaced.
   The card must exist, or the command exits 2 with a hint to copy `templates/roles/role-card.md` from the plugin.
2. `--to walls` appends the same bullet to `records.walls`, and creates it with a short header when it is missing.
3. The text is `--text`, else the rule text of the newest entry of the key; the dates are those of every entry of the key, oldest first.
4. Every Rule line of the key then gets ` [promoted -> <path of the card or the walls file>]`, and the command prints what it wrote and where.

It refuses, exit 2 and nothing written, an unknown key, a key seen less than twice (unless `--force`), a key that is already promoted, a role with no card or a name that is not a file name, and a text that is empty, on more than one line or holds the marker.
`--force` lifts only the count.
It reads the lessons file and the target, writes the target, then writes the lessons file; two agents promoting at the same moment could lose a change.

## Command matching

A command pattern is a few words, such as `"acme-cli config push"`.
It matches a simple command when the program's basename equals the first pattern word.
The command's positional words are the words that do not start with `-`, after the program.
The remaining pattern words must appear in order among the positional words; other words may sit between them.
So `acme-cli --debug config push --yes`, `acme-cli --workdir app config push` and `/usr/local/bin/acme-cli config push` match, and `acme-cli config list` does not.
A line is split into simple commands at `;`, `&&`, `||`, `|`, `&`, newlines, backticks and `$(`, so `cd app && acme-cli config push` matches too.
Quoted text is never a command, so `echo "acme-cli config push"` does not match.
Heredoc bodies and comments are skipped.

Wrappers are looked through, at the start of a simple command and in any order:

- leading `NAME=value` assignments;
- `env`, `sudo`, `command`, `nohup`, `time`, `nice` and `exec`, with their options (`env -i FOO=1`, `sudo -u root`, `nice -n 10`) and, for `env` and `sudo`, assignments;
- the shell keywords `!`, `{`, `if`, `then`, `elif`, `else`, `while`, `until` and `do`.

The script of `bash -c`, `sh -c` and `zsh -c` (also `-lc` and similar option clusters) is checked as its own command line, up to three levels deep.
So `sudo -u root env FOO=1 acme-cli config push` and `bash -lc "cd app && acme-cli config push"` both match the pattern above.
A wrapper word further along does not count: `echo sudo acme-cli config push` does not match.

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
