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
Lessons that apply: <the lines of `agent-steddy lessons find "<this unit's task>"` that fit, or none>.
Budget: read at most <N> files; hand back at most <M> lines, and list every file you read.

Done means:
- <criterion 1, for example: the verify command passes>
- <criterion 2>
Verify at: <L0 to L5> (<why this level>).
Screens or pages to check: <list, or none>.

Hand back in English, starting with these four lines, filled in (pick one status), then the detail; only your last message reaches the orchestrator, so the whole hand-back goes in it:
Status: PASS | ISSUES | BLOCKED
Verification: L<0-5>, <what you ran and what you saw>
Resources: <released, or kept and why>
Retro: worked <...> / exposed <...> / rule <...>
```

The hand-back block is the last thing in the brief, and each agent file ends with the same four lines; leave it as it is, since the agent fills it in.
The hand-back starts with the filled block and then carries: files changed; commit hash; evidence; decisions; what was not done and why.
The status is `PASS` when every Done item is met and verified, `ISSUES` when the work is delivered but something is red, unverified or left out, and `BLOCKED` when the agent could not finish; the orchestrator reads that word first.
For the agent types listed in `handback.agents`, the kit's `stop_check` hook checks the items in `handback.required`; by default those are a status (`PASS`, `ISSUES` or `BLOCKED`), a verification level and a retro line.
The lines of the block carry the words that the default items, and the `resources` item of the example config, look for, so a hand-back that fills the block in passes the check on the first try; a blocked hand-back costs the agent an extra turn.

Notes for the orchestrator:

- Pick the budget before you start the agent: N from the files the task has to read to be done right, and M from what you will really read in the hand-back; the kit has no measured default, so start from your last similar task and change the numbers when an agent runs over or leaves out what you needed.
- Do not repeat in the brief a wall that a hook already denies.
- Run `agent-steddy lessons find` with the unit's task in plain words and paste the rules that fit: a subagent does not see the prompt hook's lessons, and the lessons file is too long to send whole.
- The orchestrator owns the task clock: subagents do not run `agent-steddy metrics start` or `metrics log`.
- The orchestrator normally runs `agent-steddy record finish` itself, so a subagent does not merge.
- Check the evidence in the hand-back yourself; a report can be wrong while it sounds precise.
