# Brief

Use this brief for every subagent.
Pick the agent type first.
The agent file already carries the walls, the branch and commit rules, the verification rule, resource release and the hand-back format, so the brief adds only what is specific to this task.
Fill the angle brackets and delete nothing that applies.

```text
Branch: <branch> (stay on it).
Task: <one paragraph: the goal>.
Why: <the owner's intent, in one line>.
Scope: only <paths>.
<Another agent | I> is working on <paths> at the same time, so do not touch them.
Owner decisions already made: <list>.
Open questions: decide them by the project's principles, and log each one.
Read narrowly: <the sections or files that matter>.
Budget: read at most <N> files; hand back at most <M> lines, and list every file you read.

Done means:
- <criterion 1, for example: the verify command passes>
- <criterion 2>
Verify at: <L0 to L5> (<why this level>).
Screens or pages to check: <list, or none>.
```

The hand-back, in English, carries: files changed; commit hash; evidence; the verification level used; resources released or kept, and why; decisions; what was not done and why; one retro line (worked / exposed / rule).
For the agent types listed in `handback.agents`, the kit's `stop_check` hook checks the items in `handback.required`; by default those are a verification level and a retro line.

Notes for the orchestrator:

- Pick the budget before you start the agent: N from the files the task has to read to be done right, and M from what you will really read in the hand-back; the kit has no measured default, so start from your last similar task and change the numbers when an agent runs over or leaves out what you needed.
- Do not repeat in the brief a wall that a hook already denies.
- The orchestrator owns the task clock: subagents do not run `agent-steddy metrics start` or `metrics log`.
- The orchestrator normally runs `agent-steddy record finish` itself, so a subagent does not merge.
- Check the evidence in the hand-back yourself; a report can be wrong while it sounds precise.
