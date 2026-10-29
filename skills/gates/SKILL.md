---
name: gates
description: The method for any non-trivial task in a project that works with Claude Code agents - the walls, the seven gates (intake, recall, shape, act, prove, record, deliver), task sizing, the verification ladder, roles and the learning loop. Load it before planning, splitting or briefing agent work, and before recording a finished task.
---

# Gates

Every task passes the same seven gates inside the same walls, from a one-line fix to a new feature.
The gates do not change; what happens inside a gate depends on the role the agent plays.
Small tasks pass a gate in one thought, and large tasks leave a written artifact at each gate.
No gate is skipped.

The kit's hooks enforce what a machine can check.
This page carries the rest, and each wall says which hook or rule enforces it, or that none does.

## Walls

The walls hold in every role, for the main session and for every subagent.

| # | Wall | Enforced by |
| --- | --- | --- |
| 1 | Secrets stay in their files: no reading a secret file into the conversation and no dumping the environment. | Built-in `secret-read` and `env-dump` deny the commands; the secret output scan redacts known patterns in the output of a command that succeeded, and only warns after a failed one. |
| 2 | Only the owner's explicit ask publishes, deploys or pushes, and subagents never deploy or publish. | Project config lists the commands in `commands.deny`, `commands.askFromSubagent` and `commands.alwaysAsk`; built-in `git-push-force` asks for a force push. |
| 3 | No destructive git on a tree that agents share: no stash, no hard reset, no whole-tree checkout or restore, no forced clean. | Built-in `git-stash`, `git-reset-hard`, `git-checkout-all`, `git-restore-all` and `git-clean-force`. |
| 4 | Stage and commit by path, never everything at once. | Built-in `git-add-all` and `git-commit-all` deny the forms that take everything; committing by path is a practice the kit does not check. |
| 5 | A branch with unmerged commits is never deleted by force. | Built-in `git-branch-force-delete`. |
| 6 | The owner's own browser, tabs and accounts are never used; throwaway profiles are used instead. | Not enforced; the agent prompts state it. |
| 7 | Numbers come from code or a script, never from memory. | Not enforced. |
| 8 | Only what was verified is reported as verified; inferences are labeled, and failures are reported as failures. | Not enforced. |
| 9 | Owner decisions that are hard to reverse are asked, or logged as assumptions, never made silently. | Not enforced; `agent-steddy record decision` writes them down. |
| 10 | A subagent starts only with an agent type the project allows, and a model it is started with must match the one the project sets for that type. | `guard_agent` with `agents.allowed` and `agents.models`. |
| 11 | A fenced subagent writes only inside its write fence. | `guard_write` with `agents.writeFences`; a write through the Bash tool is not fenced. |
| 12 | A subagent's hand-back carries the items the project requires. | `stop_check` with `handback.agents` and `handback.required`; it blocks once. |

A rule matches the usual forms of a command, not every way around it; [the limits](../../docs/config.md#command-matching) are in the config reference.

## Gates

| Gate | Purpose | Output | Do not pass if |
| --- | --- | --- | --- |
| 1 Intake | Understand the real goal, the scope, the size (S, M or L) and the type (bug, feature, review, analysis, content). | One sentence that restates the goal and the scope; M and L tasks name the task with `agent-steddy metrics start "<task>"`. | An ambiguity that changes the result is neither asked nor logged as an assumption. |
| 2 Recall | Load the walls, the role card of each role in play, and the matching lessons. | A short list of the traps to avoid this time. | Work starts before the role cards were read. |
| 3 Shape | Pick the roles and the split, check the side effects on existing behavior, and define Done. | The roles, the split and Done written down; a large task has a spec before any work starts. | Nobody can say what done means, or an owner decision is still open. |
| 4 Act | Do the work to the role's standards. | The smallest correct change, in the right place and in the files assigned. | A wall or a role rule is broken. |
| 5 Prove | Act as the adversary: evidence, not promises; reproduce a bug before fixing it. | Evidence at the level chosen on the ladder below: test output, screenshots you looked at, numbers from code, and subagent reports checked with your own eyes. | Anything is red, a screenshot was not looked at, or a claim has no evidence. |
| 6 Record | Log the decisions, write the retro, and add the metrics line. | `agent-steddy record decision` lines, one `agent-steddy record lesson` entry, and one `agent-steddy metrics log` line. | A mistake reached the owner without a lesson entry. |
| 7 Deliver | Report to the owner, merge the verified branch with `agent-steddy record finish <branch>`, and release what the task started. | The report: what changed, the evidence, what was not done and why, and what the owner must do. | Done from gate 3 is not met. |

Gate 7 never deploys, publishes or pushes unless the owner asked for that exact action.
The commands of gates 6 and 7 are in the [finish skill](../finish/SKILL.md).

## Sizing a task

- S: one file or a small tweak, under about ten minutes; gates 1 to 3 take one thought, gate 5 is one check at the lowest level that fits, and gate 6 is the retro line.
- M: a feature slice across several files; write Done down, collect evidence at the ladder level, then record the retro and the metrics line.
- L: cross-cutting work, new pages, a data model or a brand change; write a spec at gate 3, get the owner's answer on each open decision, and run parallel subagents only as the orchestrator role allows.

## Verification ladder

Pick the lowest level at which this change could still be caught if it were wrong.
When the diff alone decides the result (a value swap, a rename, a copy or docs edit) and tests pin it, no runtime check is needed.
When the owner says they will review visually, take no screenshots.

| Level | Change type | Evidence |
| --- | --- | --- |
| L0 Static | Value swaps, copy, docs, renames, and config that holds no native settings. | `rg` shows the old value is gone, and the project's `verifyCommand` passes. |
| L1 Unit | Logic in services, domain code, hooks or sync. | Targeted tests first, then the project's `verifyCommand`. |
| L2 Headless web | Layout or CSS of a web page. | Headless screenshots of the changed pages at one phone and one desktop width; a tablet width only when a breakpoint changed. |
| L3 Running app | Interaction, navigation or gestures that tests cannot show. | The running dev server or app, reused; screenshots of the changed screens only. |
| L4 Native | Native modules, native configuration, dependencies with native code, SDK upgrades. | One build and a launch smoke test; a config-only check runs in a throwaway copy of the project. |
| L5 End-to-end | Bug fixes (reproduce end to end first), onboarding, navigation or data flow changes, release checks. | Only the end-to-end flows that touch the changed area; the full suite before a release or a risky merge. |

When a runtime check is needed:

- Reuse what is already running, and never rebuild native code for a change that is only JavaScript.
- Jump straight to the screen with a deep link or a test hook instead of walking through onboarding.
- Capture the changed screens, and one neighbor only when a shared component changed, at the smallest supported size unless the problem is size specific.
- Look at every screenshot you take.
- Time box the setup to ten minutes; when it fails for infrastructure reasons, stop and report instead of fighting it.

### Release what the task started

Before the report, stop what the task started and no longer needs: dev servers, simulators, headless browsers, watchers and background polls.
Find what still listens with `lsof -nP -iTCP -sTCP:LISTEN`.
Delete throwaway copies and temp folders, unless the report needs them as evidence.
Keep what the owner asked to keep, and say so in the report.

## Roles

A role is a set of standards for one kind of work.
Each role has a card in the project's roles folder, with the same shape: mission, reads, standards, done, pitfalls, tools and handoff.
The agent reads the card of each role it plays at gate 2.
The [templates](../../templates/README.md) hold the empty shape and a filled orchestrator card.

| Role | Typical work |
| --- | --- |
| Orchestrator | Splits the work, briefs the subagents, checks what comes back, and merges. |
| Implementer | Changes the code or the content of one area. |
| Verifier | Runs runtime checks at ladder levels L2 to L5, and edits tests only. |
| Auditor | Reads and researches, and writes only its own report. |
| Docs writer | Writes documentation and copy that need no code change. |

The orchestrator splits before it acts.
It picks one mode for each unit of work:

- Do it yourself for small work: a few files, a tweak, or a tight look-fix-look loop.
- Use one subagent for large work that runs in sequence, or for units that share files.
- Use parallel subagents only for two or more sizable units, each about fifteen minutes or more, that touch disjoint files and need nothing from each other until the end.

Each subagent gets a brief that states its verification level (`Verify at`) and why.
Pass `isolation: "worktree"` to the Agent tool when a subagent's scope could overlap another's.
Integrate every branch of a round first, then verify once.
Checking each branch and then again after every merge repeats the same checks.

## Learning loop

1. Write a retro at gate 6 for every task: three lines (Worked, Exposed, Rule), and ask whether any step was slow or repeated.
2. A lesson seen a second time moves into the Pitfalls of the matching role card.
3. A role rule broken a second time, or any rule about safety, data or money, moves into the walls.
   When a machine can check it, it also becomes a check: a project config entry such as `commands.deny`, `agents.writeFences` or `handback.required`, or a new built-in rule in the kit.
4. At each merge, prune: merge duplicate rules, drop stale ones, and keep the cards short.
5. A procedure done by hand three times becomes a script, a make target or a skill.
6. Each week, run `agent-steddy metrics report` and `agent-steddy metrics slow`; a command near the top by total time gets faster, or gets a written reason to stay.

## Measuring

`agent-steddy metrics` measures the work; the [config reference](../../docs/config.md#metrics) lists the clocks and the file format.

- `metrics start "<task>"` names the task and starts its clock; a running named task is kept, and `--force` replaces it.
- `metrics log --size S|M|L --type new|feedback --verify-first-pass yes|no` appends one line and closes the clock; `log` also takes `--task`, `--roles`, `--agents`, `--exposed` and `--minutes`.
- `metrics report` prints a weekly table of tasks (count, new and feedback, average minutes by size, average prompt minutes, defects the owner found per task, and the share of first-pass verifications) and a weekly table of commits by prefix with the share of fixes.
- `metrics slow` prints the Bash commands with the most total time, grouped.

Two clocks run: `minutes` covers the work from `start` to `log`, and `prompt_minutes` runs from the prompt that began the work, so it includes the discussion before `start`.
The clock stays local and is never committed; the metrics file is.
The report should move toward fewer feedback rounds and exposed defects per task, more first-pass verifications, shorter minutes per size, and a lower share of fix commits.

## Where things live

| What | Where |
| --- | --- |
| The walls and the gates | This skill; each agent prompt repeats the walls it needs, because a subagent does not see this conversation. |
| Role cards and their pitfalls | The project's roles folder; `docs/agents/roles/` in the templates. |
| Lessons | `records.lessons`, newest first. |
| Decisions and assumptions | `records.decisions`. |
| Metrics lines | `records.metrics`. |
| Project settings | `.claude/agent-steddy.json`, see the [config reference](../../docs/config.md). |
