# Templates

These files are for a project that adopts the kit.
The plugin loads nothing from `templates/`, so copy the files into the project and replace every placeholder in angle brackets.
The copied files hold no links, because a copy in a project would not resolve them.

## What is here

| File | Copy it to | What it is |
| --- | --- | --- |
| `agents/implementer.md` | `.claude/agents/` | A subagent for one area of the project, with its scope and the rules every agent follows. |
| `agents/auditor.md` | `.claude/agents/` | A read-only reviewer that writes its report under one folder. |
| `agents/verifier.md` | `.claude/agents/` | A runtime checker at ladder levels L2 to L5 that edits tests and end-to-end flows only. |
| `agents/docs-writer.md` | `.claude/agents/` | A documentation agent that runs on a small model; the first agent to consider folding into the main session, see [Fold or keep](#fold-or-keep). |
| `roles/role-card.md` | `docs/agents/roles/` | The empty shape of a role card, with a `Principles:` line for the engineering principles the role applies. |
| `roles/orchestrator.md` | `docs/agents/roles/` | A filled orchestrator card: how the main session splits, briefs and checks the work. |
| `brief.md` | `docs/agents/` | The brief that every subagent prompt starts from. |

## Adopt them

The [example project](../examples/acme/README.md) shows the agents, the role cards and the config filled in for a made-up company.

1. Install the plugin, or load it for one session with `claude --plugin-dir <path>`.
2. Copy the agent files into `.claude/agents/`, and replace `<project>`, `<area>`, `<paths>` and the test paths in each one.
   Rename an agent for each area the project has, and delete the template note at the top of `docs-writer.md`.
3. Copy the two role files into `docs/agents/roles/`, and write one card for each role the agents play.
4. Copy `brief.md` into `docs/agents/`.
5. Write `.claude/agent-steddy.json`; [docs/config.md](../docs/config.md) lists every key, and the [example config](../examples/acme/.claude/agent-steddy.json) is a full file.
   For these agents the keys are:
   - `agents.allowed`, a pattern for the agent names, such as `"<project>-*"`;
   - `agents.models`, the model each agent type must run on, such as `"<project>-docs": "haiku"`;
   - `agents.writeFences`, the paths each fenced agent may write, such as `"<project>-auditor": ["docs/reviews/"]`;
   - `handback.agents`, the same patterns as `agents.allowed`, so that every hand-back is checked;
   - `commands.askFromSubagent`, the deploy and publish commands that a subagent must ask the owner about.
6. Run `agent-steddy metrics selftest` in the project; it prints `selftest ok` when the installed scripts work.

## Fold or keep

The main session is the loop, and an agent file is worth having only when its role earns a subagent: it reads far more than it hands back, its work must be independent of the author, or it runs in parallel with other units (see Roles in the [gates skill](../skills/gates/SKILL.md#roles)).
The docs writer is the first one to consider folding, because most documentation work writes down what the main session already knows, so a subagent adds a hand-off and nothing else.
The trade-off is cost: the docs writer runs on a small model, and folding it moves its reads onto the main session's model, which can cost more tokens than it saves.
Measure the tokens and the minutes of a few real docs tasks with and without the subagent before folding it; a role that reads a lot and hands back a little keeps its agent.

## Keep the copies in step

Each agent file repeats the walls, because a subagent does not see the main conversation.
When a wall changes, change it in the gates skill and in every agent file.

## Limits

- The write fence covers `Write`, `Edit`, `MultiEdit` and `NotebookEdit`; a write through the Bash tool is not fenced.
  The auditor's prompt forbids writing through Bash, and `commands.deny` can block the commands that would do it.
- The templates do not use the frontmatter `hooks` field: a plugin's agents ignore it, so the fence lives in `agents.writeFences` and the kit's own hook enforces it.
- `disallowedTools` removes `Edit`, `MultiEdit` and `NotebookEdit` from the auditor; `Write` stays, so that it can write its report, and the fence limits where.
- The agent files set the model; a `model` that a call passes is checked against `agents.models`, so the two must agree.
