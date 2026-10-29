# Roadmap

Built step by step; each step ends with tests and a check by the owner before the next one starts.
A new session picks up at the first unticked step.

- [x] 1. Minimal plugin: manifest, one Bash guard (`git stash`), unit tests, `claude plugin validate`, and one live session that shows the hook firing.
- [x] 2. Project config file read by the hooks: working branch, verify command, agent allowlist and models, deploy commands to ask about or deny, write fences per agent.
- [x] 3. The remaining Bash guard rules (destructive git, recursive grep, `sed -i` without a backup suffix, reading secret files, deploys from a subagent), each with tests.
- [x] 4. Agent guard (allowlist and model), a write fence per agent type, and a stop check for the hand-back format.
- [x] 5. Tool timing, secret output scan, the per-prompt gate reminder, and the metrics and record scripts.
- [x] 6. The gates document, agent and role card templates, the brief template, and a `finish` skill.
- [ ] 7. Architecture and flow diagrams in the README, and an example project the tests run against.
- [ ] 8. Open-source audit (secrets, private names, git history), then publish when the owner says so.

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
