# Reference

Everything the plugin does, in one page: how a task flows, the hooks, the built-in rules and the commands.
Start with the [README](../README.md) for what agent-steddy is and how to set it up; [config.md](config.md) has every key and file format.

## How a task flows

<!-- diagram source: docs/diagrams/flow.json -->
![agent-steddy: one task passes seven gates, Intake, Recall, Shape, Act, Prove, Record and Deliver.
The gate reminder fires on every prompt, adds the gates to it and starts the task clock.
The Bash guard checks every command, in the main session and in a subagent, while timing and the secret scan watch it.
When the work is delegated, the agent guard checks a subagent when it starts, the write fence keeps a fenced agent inside its paths, and the stop check blocks a hand-back that misses a required item, once.
At gates 6 and 7 the finish skill records the decisions, a retro and a metrics line, the record files are committed by path, and record finish verifies the branch and merges it without pushing.](diagrams/flow.svg)

Every task passes the same seven gates, from a one-line fix to a new feature; the [gates skill](../skills/gates/SKILL.md) says what each gate asks for.
Hooks fire on events, not on gates:

- The session start hook (`session_start.py`) runs when a session starts, resumes or is compacted: when the branch has a resume note it points at it.
- The gate reminder (`gate_reminder.py`) runs on every prompt: it adds the gates to the prompt and starts the task clock.
- When the work is delegated, `guard_agent.py` checks a subagent when it starts, `guard_write.py` keeps a fenced agent inside its paths, and `stop_check.py` blocks an incomplete hand-back once.
- The Bash hooks run on every command, in the main session and in a subagent: `guard_bash.py` checks it, `tool_timing.py` times it (and tells the agent to test its premise when a command has failed twice in a row) and `secret_output_scan.py` hides a secret in its output.
- Gates 6 and 7 are commands, not hooks: the [finish skill](../skills/finish/SKILL.md) records the decisions, the retro and the metrics line, commits the record files by path, and runs `agent-steddy record finish`, which verifies the branch, fast-forwards the working branch onto it and never pushes.

## Layout

```text
agent-steddy/
├── .claude-plugin/              plugin.json, and marketplace.json so this repo is its own marketplace
├── bin/agent-steddy             the command for metrics, records, lessons and resume notes (on the Bash PATH while the plugin is enabled)
├── hooks/hooks.json             which script runs on which Claude Code event
├── scripts/                     the hook scripts and the command's code (Python, standard library only)
├── skills/                      the method: the gates skill and the finish skill
├── templates/                   agent, role card and brief templates for a project to copy
├── examples/acme/               an example project: config, agents and role cards
├── docs/                        config reference, roadmap and the diagrams
├── .github/workflows/test.yml   the tests and the lint on every push and pull request
└── tests/                       unit tests for the scripts, the hooks run on the example project, and a check that the docs agree with the code
```

## Built-in Bash rules

A hook on the Bash tool checks every command before it runs.
Each built-in rule has an id, and the id leads the reason the agent sees, for example `[git-stash] Never git stash ...`.
A deny stops the command; an ask makes the owner confirm it, in the main session and in a subagent.

| Rule id | Decision | What it stops |
| --- | --- | --- |
| `git-stash` | deny | `git stash`, which hides the changes other agents are working on. |
| `git-reset-hard` | deny | `git reset --hard`, which discards uncommitted work. |
| `git-checkout-all` | deny | `git checkout .` and `git checkout -- .`, which overwrite every uncommitted change. |
| `git-restore-all` | deny | `git restore .` and `git restore --staged .`, which discard or unstage everything. |
| `git-clean-force` | deny | `git clean -f`, `-fd`, `-fdx` and `--force`, which delete untracked files. |
| `git-add-all` | deny | `git add -A`, `--all` and `.`, which stage files other agents are editing. |
| `git-commit-all` | deny | `git commit -a`, `-am` and `--all`, which commit other agents' changes. |
| `git-branch-force-delete` | deny | `git branch -D`, and `-d` together with `-f`, which can lose commits. |
| `git-push-force` | ask | `git push` with `--force`, `-f`, `--force-with-lease` or a `+refspec`. |
| `grep-recursive` | deny | `grep -r`, `-R` and `--recursive` (also `egrep` and `fgrep`); use `rg` instead. |
| `sed-in-place` | deny | `sed -i` without a suffix argument, and `--in-place`; they behave differently on macOS and Linux. |
| `secret-read` | deny | Reading `.env`, `.env.*` (not `.env.example`), `*.env.local` or a glob such as `.env*` with `cat`, `grep`, `sed`, `head` and similar, and `source .env` followed by an echo of a variable. |
| `env-dump` | deny | `printenv` and a bare `env`, which print every environment variable. |
| `pipe-before-commit` | deny | A pipeline chained with `&&` to a later `git commit`, such as `go test \| tail -5 && git commit`, with no `set -o pipefail` before it: the `&&` reads the status of `tail`, not of the tests. |

Every rule looks through `NAME=value` prefixes, `env`, `sudo`, `command`, `nohup`, `time`, `nice` and `exec`, the package runners `npx`, `bunx` and `exec` and `dlx` of npm, pnpm and yarn, and reads the script of `bash -c`, `sh -c` and `zsh -c`.
The project config can add its own rules (`commands.deny`, `commands.alwaysAsk`, `commands.askFromSubagent`) and turn a built-in rule off by id (`guards.disable`).
A deny beats an ask, and a built-in rule beats a config rule.
See [docs/config.md](config.md) for the details and the limits of the matching.

## Agent rules

Three more hooks keep delegated agents inside their lane.
Agents shipped in a plugin ignore the `hooks` field of their frontmatter, so these rules live in plugin hooks that read `agent_type` from the hook input.
Each one reads its keys from the project config and does nothing until they are set; the stop check is off until a project opts in.

| Hook | Runs | What it blocks |
| --- | --- | --- |
| `guard_agent.py` | before the tool that starts a subagent (`Agent`, and `Task`, its older name) | An agent type that matches no pattern of `agents.allowed`, and a passed `model` that lacks the model name `agents.models` gives that type. |
| `guard_write.py` | before `Write`, `Edit`, `MultiEdit` and `NotebookEdit` | A write outside the path prefixes of `agents.writeFences`, for an agent type that has a fence. The main session and unfenced agents are not fenced. |
| `stop_check.py` | when a subagent is about to stop | A hand-back that lacks a `handback.required` item (by default a status, a verification level and a retro line), for an agent type in `handback.agents`. It blocks once. |

The write fence guards the file-writing tools only; a write through the Bash tool is not fenced.
See [docs/config.md](config.md) for the keys and the matching rules.

## Measure and record

Four more hooks run around the work: three collect the data, one points at a resume note.
The `agent-steddy` command turns the data into numbers and keeps the record of decisions and lessons, and the resume notes for a task that stops early.
The data and the notes are local state in the git common dir (`.git/agent-steddy/`), shared by every worktree and never committed.

| Hook | Runs | What it does |
| --- | --- | --- |
| `tool_timing.py` | before and after every Bash command | Logs how long the command took, the session, the agent and whether it failed, with the command normalized (no `cd` prefix, relative paths, no heredoc body, secrets redacted). After a failure that is the second or later in a row for the same command in the session, it adds the premise nudge: stop, write the premise of the fixes as one sentence and test it (`nudges.premise` turns it off). |
| `secret_output_scan.py` | after every Bash command | Replaces a secret in the output the agent reads with `[REDACTED:<pattern>]` and tells the agent to report it. After a failed command it can only warn. It never prints the value. |
| `session_start.py` | when a session starts, resumes, is cleared, is compacted or is forked (`SessionStart`) | When the checked out branch has a resume note, adds the line `Resume note for <branch> from <date>: run agent-steddy resume before you start.` to the context, and nothing otherwise. |
| `gate_reminder.py` | when a prompt is submitted | Adds the seven gates (or `reminder.text`) to the prompt context, with one more line while a rule is seen twice and not promoted or broke after its promotion, then up to three recorded rules that match the prompt (`recall.prompt`), and starts the task clock when no task is pending (not on a background task's notification). |

| Command | What it does |
| --- | --- |
| `agent-steddy metrics start "<task>"` | Names the task and starts its clock; a running named task is kept. |
| `agent-steddy metrics log --task T --size M --type new --verify-first-pass yes` | Appends one line (minutes, minutes since the prompt, defects found, first-pass verification) to `records.metrics`. While the task still has its auto name, `--task` is required: the command refuses (exit 2), writes nothing and keeps the clock. |
| `agent-steddy metrics report` | Weekly tables of tasks and of git rework, then a verdict on the last two weeks that have tasks: minutes by size and the first-pass share are faster or slower, better or worse, no measurable difference, or inconclusive, with the number of tasks of each week. |
| `agent-steddy metrics slow` | The Bash commands that take the most time, grouped. |
| `agent-steddy record decision "<area>" "<text>"` | Appends a line to `records.decisions`. |
| `agent-steddy record lesson --task T --roles a,b --worked W --exposed E --rule R --key K --when W [--from owner] [--new]` | Puts a dated entry at the top of `records.lessons`; `--rule`, `--key` and `--when` repeat, one of each per rule. A rule other than `none` needs a key, a slug such as `commit-by-path`, and a When, the situation it applies to; without a key nothing is written and the closest recorded rules are listed. A key recorded a second time prints a notice with the promote command, a promoted key recorded again prints that it broke after its promotion, and a new key that looks like a recorded rule, or whose closest rule is promoted, is refused unless `--new`; the three closest rules are listed. |
| `agent-steddy record finish <branch>` | Runs `verifyCommand` on the branch, fast-forwards `workingBranch` onto it, deletes it and its resume note; it refuses when the verify fails and never pushes. |
| `agent-steddy pause --intent I --done D --next N [--open O] [--pitfalls P] [--files a,b]` | Writes the resume note of the current branch: the date, the HEAD commit, the diff against the base, the uncommitted files, then the intent, what is done and verified, the open decisions, the next step, the key files and the pitfalls. It commits nothing. |
| `agent-steddy resume [--branch B] [--clear]` | Prints the branch's resume note, the commits and uncommitted files since it, and a reminder that the note is a claim, not evidence; `--clear` deletes the note. |
| `agent-steddy guard "<command line>" [--agent T] [--expect deny\|ask\|allow]` | Prints the Bash guard's verdict on a line, from the built-in rules and the project's; with `--expect` it exits 1 unless the verdict is that one, so an eval case can show that a deny rule stops the recorded failure. |
| `agent-steddy lessons check [--quiet]` | Lists the rules seen twice and not promoted, the promoted rules recorded again with no eval case, the rules with no When, the Rule lines with no key (with a suggested key) and the role cards to prune; `--quiet` prints the one reminder line, or nothing. |
| `agent-steddy lessons find "<query>" [--top N]` | Prints the rules that fit a task, best first: BM25 over each key's words, rule texts and When lines, retired rules left out. |
| `agent-steddy lessons promote <key> --to <role\|walls> [--text T] [--force]` | Writes a repeated rule as the last bullet of the role card's Pitfalls, or into `records.walls`, and marks its Rule lines ` [promoted -> <path>]`. |
| `agent-steddy lessons retire <key> [--by K]` | Marks a rule that no longer holds ` [retired]`, or ` [retired -> K]`; find, check and record then leave it out. |
| `agent-steddy lessons eval [--key K] [--judge] [--model M] [--bare]` | Runs the eval cases in `records.evals`: each Check command, and with `--judge` the cases that `claude -p` answers and judges against their criteria (`--bare` answers without the walls and the lessons, to see whether a case needs them); a summary by kind (seen, new), exit 1 when one fails. |

Claude Code puts the plugin's `bin/` folder on the Bash tool's `PATH` while the plugin is enabled; Claude.ai and Cowork do not install a plugin that has one.
See [docs/config.md](config.md) for the clocks, the file formats, `finish`, the resume notes, the learning loop and the keys.

## Method

The method for a task has three parts.

- The [gates skill](../skills/gates/SKILL.md) holds the walls, the seven gates, the rules inside the gates, task sizing, the verification ladder, roles and the learning loop; its description tells Claude when to load it.
- The [finish skill](../skills/finish/SKILL.md) runs gates 6 and 7 as commands: the decisions, the retro, the metrics line, the commit of the records, the merge and the report.
- The [templates](../templates/README.md) hold an orchestrator role card, the shape of a role card, an agent file for each kind of agent and the brief for a subagent; a project copies them and fills in the placeholders.

The gates skill marks which walls a hook enforces and which ones a person has to keep.

### Ideas from

Several ideas in the method come from [pstack](https://github.com/cursor/plugins/tree/main/pstack), a skill pack for coding agents by Lauren Tan (MIT license): pausing a task with a resume note and picking it up from the note and git, a green test that proves only what it measures, a check that counts as enforced only after it failed on the recorded error, two questions before a rule is written, a budget in the brief, auditor findings that carry the command that shows them, a status at the top of a hand-back, a verdict that comes with a metric, and seven principles that became the rules inside the gates (delete before you build, one place for each decision, build the lever, verifiable units, fix where the system first went wrong, attack the premise, do not wait for what can be undone).
The kit's code and wording are its own, and pstack's own skills are a separate install (see [Works with pstack](#works-with-pstack)).
The feedback memory of version 0.5.0 (a When line per rule, `lessons find` with BM25, and lesson evals with seen and new cases) follows a post by Việt Trần on keeping the knowledge a skill gathers as structured, searchable and testable items.

## Works with pstack

The kit covers process and guardrails: the gates, the walls, the hooks, the records and the learning loop.
It says little about engineering judgment, such as modeling the domain, boundaries, types, idempotent operations, migrating callers and testing behavior.
[pstack](https://github.com/cursor/plugins/tree/main/pstack) covers that with one principle skill for each principle (`principle-model-the-domain`, `principle-boundary-discipline`, `principle-type-system-discipline`, `principle-make-operations-idempotent`, `principle-test-behavior-not-implementation` and more), so the two fit together.
Install it next to the kit with:

```bash
npx skills add backnotprop/pstack
```

When a project has principle skills installed, the gates skill has the agent load the ones that fit the roles in play at gate 2, and each role card names its own on a `Principles:` line.
The kit does not depend on pstack and works without it.

## Example project

[examples/acme](../examples/acme/README.md) is a small complete project for a made-up company: the config, the four agents filled in from the templates and their role cards.
`tests/test_example_project.py` runs the real hook scripts and the command against it, so the config, the agents and the hooks are proved together.
Copy it as a starting point, and read it next to the [config reference](config.md).

## Develop

```bash
claude plugin validate .
python3 -I -m unittest discover -s tests
claude --plugin-dir /path/to/agent-steddy    # a session with the plugin loaded
```
