# agent-steddy

Guardrails, gates and a learning loop for a team of Claude Code agents, packaged as a Claude Code plugin.

> Status: early build, not published yet. Built step by step; each step is one small commit.

## What it will do

- Stop the commands that break shared work (destructive git, reading secrets, deploying from a subagent) with hooks, so the rule holds even when a prompt forgets it.
- Give every task the same seven gates: intake, recall, shape, act, prove, record, deliver.
- Turn repeated mistakes into rules: a short retro per task, and a rule that repeats moves into a role card or a hook.
- Measure the work: minutes per task, first-pass verification, defects the owner found.

## Layout

```text
agent-steddy/
├── .claude-plugin/plugin.json   plugin manifest
├── hooks/hooks.json             which script runs on which Claude Code event
├── scripts/                     the hook scripts (Python, standard library only)
└── tests/                       unit tests for the scripts
```

## Try it locally

```bash
claude plugin validate .
python3 -I -m unittest discover -s tests
claude --plugin-dir /path/to/agent-steddy    # a session with the plugin loaded
```

## License

MIT, see [LICENSE](LICENSE).
