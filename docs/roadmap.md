# Roadmap

Built step by step; each step ends with tests and a check by the owner before the next one starts.
A new session picks up at the first unticked step.

- [x] 1. Minimal plugin: manifest, one Bash guard (`git stash`), unit tests, `claude plugin validate`, and one live session that shows the hook firing.
- [x] 2. Project config file read by the hooks: working branch, verify command, agent allowlist and models, deploy commands to ask about or deny, write fences per agent.
- [x] 3. The remaining Bash guard rules (destructive git, recursive grep, `sed -i` without a backup suffix, reading secret files, deploys from a subagent), each with tests.
- [x] 4. Agent guard (allowlist and model), a write fence per agent type, and a stop check for the hand-back format.
- [ ] 5. Tool timing, secret output scan, the per-prompt gate reminder, and the metrics and record scripts.
- [ ] 6. The gates document, agent and role card templates, the brief template, and a `finish` skill.
- [ ] 7. Architecture and flow diagrams in the README, and an example project the tests run against.
- [ ] 8. Open-source audit (secrets, private names, git history), then publish when the owner says so.

## Facts found on the way

- Agents shipped in a plugin ignore the `hooks`, `permissionMode` and `mcpServers` frontmatter fields (Claude Code docs, plugin components, checked 2026-10-29).
  A per-agent fence therefore lives in a plugin hook that reads `agent_type` from the hook input.
- Hook processes receive `CLAUDE_PLUGIN_ROOT`, `CLAUDE_PLUGIN_DATA` and `CLAUDE_PROJECT_DIR`; commands Claude runs through the Bash tool do not.
- Checked in a live Claude Code session on 2026-10-29 (a throwaway project, Haiku): the agent guard denied a type outside `agents.allowed`; a subagent's `Write` outside its fence was denied, so `agent_type` reaches file-writing tools; the stop check blocked a hand-back that missed its items exactly once, and the agent then finished.
