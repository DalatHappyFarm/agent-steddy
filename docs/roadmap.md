# Roadmap

Built step by step; each step ends with tests and a check by the owner before the next one starts.
A new session picks up at the first unticked step.

- [x] 1. Minimal plugin: manifest, one Bash guard (`git stash`), unit tests, `claude plugin validate`, and one live session that shows the hook firing.
- [x] 2. Project config file read by the hooks: working branch, verify command, agent allowlist and models, deploy commands to ask about or deny, write fences per agent.
- [x] 3. The remaining Bash guard rules (destructive git, recursive grep, `sed -i` without a backup suffix, reading secret files, deploys from a subagent), each with tests.
- [x] 4. Agent guard (allowlist and model), a write fence per agent type, and a stop check for the hand-back format.
- [x] 5. Tool timing, secret output scan, the per-prompt gate reminder, and the metrics and record scripts.
- [x] 6. The gates document, agent and role card templates, the brief template, and a `finish` skill.
- [x] 7. Architecture and flow diagrams in the README, and an example project the tests run against.
- [x] 8. Open-source audit (secrets, private names, git history), then publish when the owner says so.
- [x] 9. Learning loop automation (rule keys, repeat notice, lessons check and promote, the reminder line) and the single-agent-loop defaults in the method.
- [x] 10. Ideas from pstack: resume notes, rules for checks and lessons, the brief budget, auditor re-run commands, the hand-back status and metric verdicts.
- [ ] 11. Method rules from pstack's principles, the premise nudge, pstack as a companion for engineering principles, and named metrics rows.

## Facts found on the way

- Agents shipped in a plugin ignore the `hooks`, `permissionMode` and `mcpServers` frontmatter fields (Claude Code docs, plugin components, checked 2026-10-29).
  A per-agent fence therefore lives in a plugin hook that reads `agent_type` from the hook input.
- Hook processes receive `CLAUDE_PLUGIN_ROOT`, `CLAUDE_PLUGIN_DATA` and `CLAUDE_PROJECT_DIR`; commands Claude runs through the Bash tool do not.
- Checked in a live Claude Code session on 2026-10-29 (a throwaway project, Haiku): the agent guard denied a type outside `agents.allowed`; a subagent's `Write` outside its fence was denied, so `agent_type` reaches file-writing tools; the stop check blocked a hand-back that missed its items exactly once, and the agent then finished.
- The Claude Code docs (plugins reference and hooks reference, checked 2026-10-29) say that the `bin/` folder of a plugin is on the Bash tool's `PATH` while the plugin is enabled, and that claude.ai and Cowork do not install a plugin that has a top-level `bin/` folder.
  The kit therefore installs in Claude Code only.
- Because the Bash tool gets none of those variables, the `agent-steddy` command finds the project from its working directory, and hook state outside a git repo (kept under `CLAUDE_PLUGIN_DATA`) is out of its reach.
- The `PostToolUse` input has an optional `duration_ms` that leaves out the wait for a permission prompt and for `PreToolUse` hooks, so the timing hook prefers it to the time between its own two hooks.
  `PostToolUseFailure` has `error`, `is_interrupt` and an optional `duration_ms`, no `tool_response`, and takes `additionalContext` only as output.
- `updatedToolOutput` is a `PostToolUse` output.
  It must match the tool's output shape or the original output is used, and it changes only what Claude sees; telemetry captures the original output.
- A `UserPromptSubmit` hook that reaches its timeout has its `additionalContext` discarded.
- Not yet checked in a live session: that Claude Code applies the redacted Bash output of the secret scan, and that the prompt hook's context reaches the agent.
  Step 5 is verified by unit tests and `claude plugin validate` only.
- Checked in a live Claude Code session on 2026-10-29 (Haiku, a throwaway git repo): the gate reminder reached the agent as prompt context; `agent-steddy` from the plugin's `bin/` ran from the Bash tool; a fake AWS key printed by `echo` reached the agent only as `[REDACTED:aws-access-key-id]`, and the timing log stored the redacted command; the prompt hook started the task clock.
- Decided 2026-10-29: task clocks need a git repo; outside one, `metrics log --task --minutes` still works, and no state folder is added to the project.
- Checked in a live Claude Code session on 2026-10-29 (Haiku): the plugin skills load as `agent-steddy:gates` and `agent-steddy:finish`, and the gates description is enough for the agent to say what the skill covers.
- Decided 2026-10-29: the two diagrams in `docs/diagrams/` are drawn from the JSON specs beside them.
  Change the JSON and redraw, never the SVG by hand; `tests/test_diagrams.py` keeps each spec, its SVG and the README alt text equal.
- Decided 2026-10-29: `examples/acme` is the config, four agents and their role cards, with no product code and no Makefile.
  Its demo deny rule uses a made-up command (`acme-cli config push`), and `tests/test_example_project.py` runs the real hooks and the command against it.
- Checked 2026-10-30 for step 8: the repo is its own marketplace.
  `.claude-plugin/marketplace.json` lists the one plugin with `"source": "./"`, which the Claude Code docs (plugin marketplaces) allow, and the entry name equals the `name` in `plugin.json`.
  With Claude Code 2.1.314, `claude plugin validate .` and `claude plugin validate .claude-plugin/marketplace.json` both pass; the first only warns that the plugin has no icon, which is optional.
  A live `marketplace add` and `install` from GitHub is not checked yet; it needs the repository to exist.
- Checked 2026-10-30 in a live Claude Code session (Haiku, a throwaway copy of `examples/acme`, no `--plugin-dir`): the plugin was installed from a fresh clone of the repo with `claude plugin marketplace add <clone> --scope project` and `claude plugin install agent-steddy@agent-steddy --scope project`.
  The config rule denied `acme-cli config push`, the built-in rule denied `git stash`, and `agent-steddy` ran from the Bash `PATH` and wrote the decision to the project's `docs/agents/decisions.md`.
  `marketplace add` refuses a `file://` URL, and a remote served over plain HTTP fails because Claude Code clones it shallow.
  `claude plugin uninstall` leaves the copy under `~/.claude/plugins/cache/`.
- Checked 2026-10-30 after the first push: `claude plugin marketplace add DalatHappyFarm/agent-steddy --scope project` and `claude plugin install agent-steddy@agent-steddy --scope project` installed the plugin from GitHub into a throwaway copy of `examples/acme`.
  A live Claude Code session (Haiku) loaded it from `~/.claude/plugins/cache/agent-steddy/agent-steddy/0.1.0` and gave the same four results as the local install check.
- Checked 2026-10-30: the first CI run passed every job, the tests on Ubuntu and macOS with Python 3.9 and 3.13, and ruff.
  It is the first run of the tests on Linux.
- Checked 2026-10-30: gitleaks 8.30.1 finds nothing in the history (`gitleaks git .`) or in the files (`gitleaks dir .`).
  Python folds `"a" + "b"` into one string when it compiles, so a `__pycache__` folder holds the synthetic test keys whole; `.gitleaks.toml` skips those git-ignored folders and `.gitleaksignore` holds the one old finding in the history.
- Checked 2026-10-30: the unit tests pass on Python 3.9.6 and 3.14 on macOS.
  They use no macOS-only tool: every test repo is made with `git init -b` and an explicit `-c user.name` identity, so they do not read the machine's git config.
  Linux has not been run locally; `.github/workflows/test.yml` runs the tests on Ubuntu and macOS with Python 3.9 and 3.13, and ruff 0.8.4 once.
- Decided 2026-10-30 for step 9: the learning loop is commands plus judgment.
  A rule other than `none` needs a key (a lowercase slug, at most 40 characters), the count that makes a rule due is the constant 2 in `scripts/lessons.py` and not a config key, and the refusals that ask for another key or target exit 2.
  The commands pick nothing that is a judgment: which target (a role card, the walls file, a check as well) and the final wording stay with the person or the agent.
  The method also says the main session is the loop and a role becomes a subagent only when it earns it, with the docs writer as the first fold candidate; the token cost of folding a cheaper-model agent is a trade-off to measure, not a measured number.
- Checked 2026-10-30 for step 9: the unit tests (307) pass on Python 3.9 and 3.14, and the example project runs the whole loop end to end on a temporary copy: two lessons with one key, the notice, the reminder line, `lessons promote` into an Acme role card, and `lessons check` with nothing due.
- Checked 2026-10-30 in four live Claude Code sessions (Haiku, `--plugin-dir`, a throwaway copy of `examples/acme`): `record lesson` with no key wrote nothing and exited 2; with `--key` it wrote the entry, and the second entry with the same key printed the notice and the promote command.
  A new session quoted the reminder line `Learning loop: 1 rule(s) seen twice and not promoted (stage-by-path); run agent-steddy lessons check.` from its prompt context.
  `lessons promote stage-by-path --to web` replaced the placeholder in the Pitfalls of `web.md` and marked both Rule lines, `lessons check` then showed nothing due, and the next session found no reminder line.
  Not checked: that an agent promotes a due rule on its own; in these sessions the prompt told it to.
- Checked 2026-10-30 against the Claude Code hooks reference (https://code.claude.com/docs/en/hooks) for step 10: `SessionStart` has the sources `startup`, `resume`, `clear`, `compact` and `fork` (the docs give no version for `compact` or `fork`), and a hook with no matcher runs for all of them.
  It accepts `hookSpecificOutput.additionalContext` with `hookEventName` set to `SessionStart`, which "adds context for Claude" at the start of the conversation, before the first prompt; plain stdout is added as context too, and the event has no blocking or decision control.
  The docs say it runs on every session, so a hook must be fast; the default timeout of a command hook is 600 seconds, and the kit sets 5.
- Checked 2026-10-30 in live Claude Code sessions (Haiku, `--plugin-dir`, a throwaway copy of `examples/acme` on a branch `feat/pricing`): `pause` saved the note under `.git/agent-steddy/resume/feat__pricing.md`, and a new session quoted `Resume note for feat/pricing from 2026-10-30 14:40: run agent-steddy resume before you start.` from its context.
  After one more commit, `resume` printed the note and listed that commit under "Since the note"; after `resume --clear` the next session found no line.
  A `/compact` in a resumed session (42,436 tokens down to 8,536) fired `SessionStart:compact`, and the hook returned the same line right after the compaction; `SessionStart:resume` returned it when the session was resumed.
  On a copy of a real project's metrics file, the verdicts called a large drop in the median minutes of L tasks inconclusive, because neither week had 5 such tasks, and a first-pass share that moved by one point no measurable difference.
- Decided 2026-10-30 for step 10: a resume note is a claim, so `resume` ends with the reminder to check Done against git and the verify command, and the note stores the full HEAD hash, which is what `git log <head>..HEAD` needs.
  The date has the time, since two pauses of one day differ.
  The notes live in the git common dir (shared by the worktrees) or in `resume.folder`; the kit commits neither, and `record finish` leaves the deletion of a committed note to the person, since it never commits.
  A note kept in the repo does not make the tree dirty for `record finish`, or no in-repo note could ever be merged.
  `feat/x` and `feat__x` map to one file name; the `Branch:` line of the note decides which branch it belongs to, so the other branch sees no note.
  `pause` refuses a value that matches a pattern of the secret output scan, naming the pattern and never the value, since a note kept in the repo can be committed and shared.
- Decided 2026-10-30 for step 10: the hand-back status is a default `handback.required` item, `\b(?:PASS|ISSUES|BLOCKED)\b`, the first of the list.
  The words are whole and in capitals, like the level pattern next to it (`\bL[0-5]\b`), so `PASSWORD` and `passed` do not count.
  This changes the default for a project that opted in with `handback.agents` and left `handback.required` out: its agents are now blocked once until their hand-back has a status word; a project that sets its own `handback.required` list is not affected.
- Decided 2026-10-30 for step 10: the metric verdicts compare the last two weeks that have tasks among the weeks the report shows, minutes by size and the first-pass share, with the two constants `MIN_TASKS` (5) and `IQR_SHARE` (0.5) in `scripts/metrics.py`.
  Equal medians are never a difference, which the written rule leaves open when the interquartile range is 0.
  For the share, which is one number per week, the share itself stands where the median stands: the median of a column of 0 and 1 is only 0, 0.5 or 1, and it would call a move from 50% to 60% of 10 tasks better because the median flipped.
  The tests pin both readings of the rule on sample numbers computed with `statistics`; none of it was checked against a real project's metrics file.
- Fixed 2026-10-30 in 0.3.1: a turn that only delivers a background task's notification fires `UserPromptSubmit` too, with a prompt that starts with `<task-notification>` and no other field that tells it apart (captured in a live session with a hook that logged its input), so the gate reminder started a task clock with no prompt behind it once `metrics log` had closed the last one.
  The reminder now starts no clock on such a turn; the new test failed on the old hook and passes on the fix, and in a live session (Haiku, `--plugin-dir`) a notification that arrived after `metrics log` left no pending task.
- Checked 2026-10-30 against the Claude Code hooks reference (https://code.claude.com/docs/en/hooks) for step 11: "when an event fires, its matching hooks run in parallel", and "when several hooks return `additionalContext` for the same event, Claude receives all of the values"; the 10,000 character cap is measured on each string on its own.
  `PostToolUseFailure` takes `hookSpecificOutput.additionalContext` ("string added to Claude's context alongside the error"), and its input has the common fields `session_id` and, in a subagent, `agent_id` and `agent_type`.
  So the secret scan and the timing hook, which both run on `PostToolUseFailure`, each print their own note and need no coordination; the docs say nothing about the order of the values.
- Decided 2026-10-30 for step 11: the premise nudge counts the failures of one normalized command by one session and one agent, newest first, until a success; the threshold is the constant `PREMISE_FAILS` (2) in `scripts/tool_timing.py`, and the hook reads only the last 256 KB of the timing log.
  It counts failures, not premises, so it can be wrong about a command that fails for a new reason each time; the text says "if the fixes rest on one premise" for that reason.
  Verified by unit tests and the hook process only; not checked in a live Claude Code session yet.
