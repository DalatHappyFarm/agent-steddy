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
