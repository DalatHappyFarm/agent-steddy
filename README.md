# agent-steddy

A Claude Code plugin that keeps your AI coding agents safe, on process, and learning from their mistakes.

<!-- diagram source: docs/diagrams/architecture.json -->
![agent-steddy sits between your Claude Code agents and your repo: it checks every prompt and command, blocks risky git and secret reads, and keeps what the agents learn in docs/agents. A lesson's life: a mistake is recorded as a rule, the rule is recalled when its situation comes back, promoted when it repeats, and checked by an eval case.](docs/diagrams/architecture.svg)

> Status: version 0.6.0, early.
> Claude Code only; it needs `python3` 3.9 or later and `git`.

## Why

Agents that share a repo stash or reset each other's work, call a test green from the wrong exit code, and repeat mistakes you already corrected.
A line in a prompt does not stop that; a hook and a record do.

## What it adds

- **Guardrails.** Hooks check every command before it runs, in the main agent and in subagents. `git stash`, `git add -A`, reading `.env`, a test piped into `tail` before a commit, and the deploy commands you list are blocked or sent to you.
- **Gates.** Every task goes through the same seven steps: intake, recall, shape, act, prove, record, deliver. A reminder on every prompt keeps them in front of the agent.
- **Memory.** After each task the agent writes a short retro. Each rule says when it applies and comes back when that situation does; a rule that repeats moves into a role card or the project's walls, and one that breaks after that is flagged until it has an eval case.

## Install

In your project's folder:

```bash
claude plugin marketplace add DalatHappyFarm/agent-steddy --scope project
claude plugin install agent-steddy@agent-steddy --scope project
```

Then start a new Claude Code session there.

## Set it up with your agent

Paste this into that session:

```text
Set up the agent-steddy plugin in this repo. It is installed; its files are in
the folder that `dirname "$(dirname "$(command -v agent-steddy)")"` prints.
Read README.md, templates/README.md and docs/config.md there first.

1. Write .claude/agent-steddy.json with only the keys this repo needs,
   modelled on examples/acme/.claude/agent-steddy.json: workingBranch,
   verifyCommand (the one command that proves a change here, such as tests
   plus lint), and our deploy and publish commands under
   commands.askFromSubagent or commands.deny.
2. Copy templates/roles/orchestrator.md into docs/agents/roles/ and
   templates/brief.md into docs/agents/, and write one role card in
   docs/agents/roles/ for each kind of work this repo has. Ask me before
   adding subagent files to .claude/agents/.
3. Prove it works: run `agent-steddy metrics selftest`,
   `agent-steddy guard "git stash" --expect deny`, and the verifyCommand once.
4. Commit these files by path on a new branch, do not push, and tell me what
   you set and why.
```

After that the hooks work on their own, and the agent records each task with the finish skill.
Once a week, run `agent-steddy lessons check` to see which rules repeat.

## Learn more

- [Reference](docs/reference.md): how a task flows, every hook, built-in rule and command.
- [Config](docs/config.md): every key of `.claude/agent-steddy.json` and every file format.
- [Gates skill](skills/gates/SKILL.md): the method the agent follows.
- [Example project](examples/acme/README.md): a config, agents and role cards, filled in.

## License

MIT, see [LICENSE](LICENSE).
