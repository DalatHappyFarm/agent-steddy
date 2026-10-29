---
name: finish
description: Gates 6 and 7 for a finished task - self-review, decisions, the retro, the metrics line, committing the record files by path, the merge with agent-steddy record finish, releasing what the task started, and the report. Use when a task passed gate 5 and is ready to record and deliver.
---

# Finish

Run these steps from the project root, after gate 5 is green and the work is committed by path.
The walls and the gates are in the [gates skill](../gates/SKILL.md).

Use the commands for every record, and never write the record files by hand: the commands keep the formats that `agent-steddy metrics` and `agent-steddy record` read.
If a command refuses, read the reason and fix the input; do not work around the command.

## 1. Self-review

Run `agent-steddy metrics slow --days 1 --top 5` to list the slowest Bash commands of the last day.
Name any slow or repeated step in the retro, in its Exposed or Rule line.

## 2. Decisions

Record each product decision, assumption and deviation from the plan, one command per decision:

```text
agent-steddy record decision "<area>" "<what was decided, and why>"
```

The area is a short tag of letters, digits, spaces and `_ . / -`, such as `core` or `docs`.
The text is one line.

## 3. Retro

Write the retro for every task, even a small one:

```text
agent-steddy record lesson --task "<task>" --roles <a>,<b> --worked "<one line>" --exposed "<one line, or none>" --rule "<one line, or none>"
```

`--roles` is comma separated, and every value is one line.
The entry goes to the top of the lessons file, above the older ones.

## 4. Metrics line

```text
agent-steddy metrics log --task "<task>" --size S|M|L --type new|feedback --verify-first-pass yes|no --roles <a>,<b> --agents <N> --exposed <N>
```

- `--type feedback` marks an owner round on earlier work, and `new` marks a fresh request.
- `--verify-first-pass yes` only when the first verification run was green.
- `--exposed` counts the defects the owner found in work that was already delivered.
- The minutes come from the task clock, and `--minutes` replaces it; with no clock and no `--minutes` the row has no minutes.
- Pass the real name in `--task`; a row still named `auto ...` gets a note.

## 5. Commit the record files by path

The record files are the paths `records.decisions`, `records.lessons` and `records.metrics` in `.claude/agent-steddy.json`.
The defaults are `docs/agents/decisions.md`, `docs/agents/lessons.md` and `docs/agents/metrics.jsonl`.
Commit them by path, with each path written out in the command:

```text
git add <a record file that is new, if any>
git commit -m "docs(agents): record <task>" -- docs/agents/decisions.md docs/agents/lessons.md docs/agents/metrics.jsonl
git status --short
```

Use the paths the project's config names when they differ from the defaults.
The `git status --short` output must show no line for this task's files.

## 6. Merge

```text
agent-steddy record finish <branch>
```

The command runs in this order:

1. It refuses unless the branch exists, is not `workingBranch`, fast-forwards onto `workingBranch`, and the working tree is clean.
2. It switches to the branch, runs `verifyCommand` on it through a shell in the project root, and switches back.
3. When the command passes, it merges the branch with `git merge --ff-only` and deletes the branch.

It never pushes.

- `--full` appends ` --full` to `verifyCommand`, for a verify script that checks everything when it gets that flag.
- `--no-verify` is refused when `verifyCommand` is set; with no `verifyCommand` the command refuses unless `--no-verify` is given, because nothing else would prove the branch.
- When the verify command fails, nothing is merged, the branch stays, and the last 40 lines of its output are printed.
- The command switches the checkout between branches, so no other agent may work in the same checkout while it runs.
- When the owner said they will review the task first, skip this step and name the branch in the report.

## 7. Release what the task started

Stop the dev servers, simulators, headless browsers, watchers and background polls that this task started.
Check what still listens with `lsof -nP -iTCP -sTCP:LISTEN`.
Delete throwaway copies and temp folders, unless the report needs them as evidence.
Keep only what the owner asked to keep, and say so in the report.

## 8. Report

The report to the owner has these parts, in English or in the owner's language:

1. What changed: the files, and the commit hash.
2. Evidence: the commands run with their results, and the screenshots you looked at.
3. The verification level used, and why that level.
4. What was not done, and why.
5. What the owner must do, such as review a branch or run a deploy the owner asked for.
6. The resources released, and the ones kept and why.

This skill never deploys, publishes or pushes.
A deploy, a publish or a push needs the owner's explicit ask for that exact action.
