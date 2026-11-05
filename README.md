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

## How it works

Two halves: hooks that act on their own, and a method the agent follows.

**On their own, the hooks:**

1. **Session start.** If the branch has a resume note from a paused task, the agent is told to read it first.
2. **Every prompt.** The seven gates, a line when a rule keeps repeating, and up to three recorded lessons that match the prompt go into the agent's context; a task clock starts.
3. **Every Bash command.** It is checked before it runs (denied, or sent to you), timed, and stripped of secrets in its output. When the same command fails twice, the agent is told to test its premise instead of trying a third fix.
4. **Every subagent.** It must be an allowed type on its set model; when your config sets them, it writes only inside its fence and its hand-back must carry a status, a verification level and a retro line.

**The agent, at each of the seven gates:**

| Gate | What the agent does |
| --- | --- |
| 1&nbsp;Intake | Restates the goal, sizes the task (S, M or L), asks what is unclear. |
| 2&nbsp;Recall | Reads the walls and role cards, and runs `agent-steddy lessons find "<goal and plan>"`. |
| 3&nbsp;Shape | Picks the roles, splits the work, writes down what done means. |
| 4&nbsp;Act | Makes the smallest correct change while the hooks guard each step. |
| 5&nbsp;Prove | Shows evidence: test output, screenshots it looked at, numbers from code; a bug is reproduced before it is fixed. |
| 6&nbsp;Record | Logs decisions, a retro with a rule and its When line, and a metrics line. |
| 7&nbsp;Deliver | `agent-steddy record finish <branch>` runs your verify command on the branch and merges it, never pushing; then a short report. |

## Workflow

**One task.**
You send a prompt.
The agent gets the gates and the lessons that fit, works through them, and the hooks stop what would break shared work.
It ends with the change merged on your working branch and a report: what changed, the evidence, what is left, what you must do.
You review and push.

**A task that stops halfway.**
`agent-steddy pause` writes a resume note; the next session is pointed at it and carries on from there.

**Over weeks, the learning loop.**

1. A mistake becomes a rule with a key and a When line, the situation it applies to.
2. The rule comes back when that situation does, through the prompt hook or `agent-steddy lessons find`.
3. Seen twice, it moves into a role card or the project's walls with `agent-steddy lessons promote`.
4. Broken again after that, it needs a check a machine runs: a deny rule shown with `agent-steddy guard "<the bad command>" --expect deny`, or a test, kept as an eval case that `agent-steddy lessons eval` reruns after a plugin or model change.
5. A rule that no longer holds is retired with `agent-steddy lessons retire`.

**What you do.**
Give tasks, answer the questions the agent asks, review the report, push.
Once a week, read `agent-steddy lessons check` and `agent-steddy metrics report`.

**Where things live.**
`.claude/agent-steddy.json` and `docs/agents/` (lessons, decisions, metrics, walls, role cards, eval cases) are committed and shared with your team.
`.git/agent-steddy/` (the task clock, command timings, resume notes) stays on your machine.

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
