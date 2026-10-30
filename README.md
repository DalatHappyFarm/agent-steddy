# agent-steddy

Guardrails, gates and a learning loop for a team of Claude Code agents, packaged as a Claude Code plugin.

<!-- diagram source: docs/diagrams/architecture.json -->
![agent-steddy: Claude Code fires its events at the plugin's hooks, which read the project config and answer with deny, ask or block; the hooks keep a task clock and timings in local state under .git/agent-steddy; agents run the agent-steddy command, which reads the project config, keeps that clock and writes the project's records under docs/agents; agents read the skills, and the templates are copied into the project's agents and role cards.](docs/diagrams/architecture.svg)

> Status: version 0.1.0, early.
> Tested with Claude Code 2.1.314 on macOS; it needs `python3` 3.9 or later and `git` on the PATH.
> It works in Claude Code only: the `bin/` folder keeps it out of Claude.ai and Cowork.

## What it does

- Stop the commands that break shared work (destructive git, reading secrets, deploying from a subagent) with hooks, so the rule holds even when a prompt forgets it.
- Give every task the same seven gates: intake, recall, shape, act, prove, record, deliver.
- Turn repeated mistakes into rules: a short retro per task, and a rule that repeats moves into a role card or a hook.
- Measure the work: minutes per task, first-pass verification, defects the owner found.

## How a task flows

<!-- diagram source: docs/diagrams/flow.json -->
![agent-steddy: one task passes seven gates, Intake, Recall, Shape, Act, Prove, Record and Deliver.
The gate reminder fires on every prompt, adds the gates to it and starts the task clock.
The Bash guard checks every command, in the main session and in a subagent, while timing and the secret scan watch it.
When the work is delegated, the agent guard checks a subagent when it starts, the write fence keeps a fenced agent inside its paths, and the stop check blocks a hand-back that misses a required item, once.
At gates 6 and 7 the finish skill records the decisions, a retro and a metrics line, the record files are committed by path, and record finish verifies the branch and merges it without pushing.](docs/diagrams/flow.svg)

Every task passes the same seven gates, from a one-line fix to a new feature; the [gates skill](skills/gates/SKILL.md) says what each gate asks for.
Hooks fire on events, not on gates:

- The gate reminder (`gate_reminder.py`) runs on every prompt: it adds the gates to the prompt and starts the task clock.
- When the work is delegated, `guard_agent.py` checks a subagent when it starts, `guard_write.py` keeps a fenced agent inside its paths, and `stop_check.py` blocks an incomplete hand-back once.
- The Bash hooks run on every command, in the main session and in a subagent: `guard_bash.py` checks it, `tool_timing.py` times it and `secret_output_scan.py` hides a secret in its output.
- Gates 6 and 7 are commands, not hooks: the [finish skill](skills/finish/SKILL.md) records the decisions, the retro and the metrics line, commits the record files by path, and runs `agent-steddy record finish`, which verifies the branch, fast-forwards the working branch onto it and never pushes.

## Layout

```text
agent-steddy/
├── .claude-plugin/              plugin.json, and marketplace.json so this repo is its own marketplace
├── bin/agent-steddy             the command for metrics and records (on the Bash PATH while the plugin is enabled)
├── hooks/hooks.json             which script runs on which Claude Code event
├── scripts/                     the hook scripts and the command's code (Python, standard library only)
├── skills/                      the method: the gates skill and the finish skill
├── templates/                   agent, role card and brief templates for a project to copy
├── examples/acme/               an example project: config, agents and role cards
├── docs/                        config reference, roadmap and the diagrams
├── .github/workflows/test.yml   the tests and the lint on every push and pull request
└── tests/                       unit tests for the scripts, the hooks run on the example project, and a check that the docs agree with the code
```

## Install

```bash
claude plugin marketplace add DalatHappyFarm/agent-steddy
claude plugin install agent-steddy@agent-steddy
```

Inside a Claude Code session, `/plugin marketplace add DalatHappyFarm/agent-steddy` does the first step.
Then copy [examples/acme/.claude/agent-steddy.json](examples/acme/.claude/agent-steddy.json) into your project's `.claude/` folder and edit it; the next section says how.

## Configure

A project adjusts the kit with one file, `.claude/agent-steddy.json` in its root.
Every key is optional; a missing file gives the defaults.
See [docs/config.md](docs/config.md) for every key and [examples/acme/.claude/agent-steddy.json](examples/acme/.claude/agent-steddy.json) for a full example.

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

Every rule looks through `NAME=value` prefixes, `env`, `sudo`, `command`, `nohup`, `time`, `nice` and `exec`, and reads the script of `bash -c`, `sh -c` and `zsh -c`.
The project config can add its own rules (`commands.deny`, `commands.alwaysAsk`, `commands.askFromSubagent`) and turn a built-in rule off by id (`guards.disable`).
A deny beats an ask, and a built-in rule beats a config rule.
See [docs/config.md](docs/config.md) for the details and the limits of the matching.

## Agent rules

Three more hooks keep delegated agents inside their lane.
Agents shipped in a plugin ignore the `hooks` field of their frontmatter, so these rules live in plugin hooks that read `agent_type` from the hook input.
Each one reads its keys from the project config and does nothing until they are set; the stop check is off until a project opts in.

| Hook | Runs | What it blocks |
| --- | --- | --- |
| `guard_agent.py` | before the tool that starts a subagent (`Agent`, and `Task`, its older name) | An agent type that matches no pattern of `agents.allowed`, and a passed `model` that lacks the model name `agents.models` gives that type. |
| `guard_write.py` | before `Write`, `Edit`, `MultiEdit` and `NotebookEdit` | A write outside the path prefixes of `agents.writeFences`, for an agent type that has a fence. The main session and unfenced agents are not fenced. |
| `stop_check.py` | when a subagent is about to stop | A hand-back that lacks a `handback.required` item (by default a verification level and a retro line), for an agent type in `handback.agents`. It blocks once. |

The write fence guards the file-writing tools only; a write through the Bash tool is not fenced.
See [docs/config.md](docs/config.md) for the keys and the matching rules.

## Measure and record

Three more hooks collect the data, and the `agent-steddy` command turns it into numbers and keeps the record of decisions and lessons.
The data is local state in the git common dir (`.git/agent-steddy/`), shared by every worktree and never committed.

| Hook | Runs | What it does |
| --- | --- | --- |
| `tool_timing.py` | before and after every Bash command | Logs how long the command took, the agent type and whether it failed, with the command normalized (no `cd` prefix, relative paths, no heredoc body, secrets redacted). |
| `secret_output_scan.py` | after every Bash command | Replaces a secret in the output the agent reads with `[REDACTED:<pattern>]` and tells the agent to report it. After a failed command it can only warn. It never prints the value. |
| `gate_reminder.py` | when a prompt is submitted | Adds the seven gates (or `reminder.text`) to the prompt context, and starts the task clock when no task is pending. |

| Command | What it does |
| --- | --- |
| `agent-steddy metrics start "<task>"` | Names the task and starts its clock; a running named task is kept. |
| `agent-steddy metrics log --size M --type new --verify-first-pass yes` | Appends one line (minutes, minutes since the prompt, defects found, first-pass verification) to `records.metrics`. |
| `agent-steddy metrics report` | Weekly tables of tasks and of git rework. |
| `agent-steddy metrics slow` | The Bash commands that take the most time, grouped. |
| `agent-steddy record decision "<area>" "<text>"` | Appends a line to `records.decisions`. |
| `agent-steddy record lesson --task T --roles a,b --worked W --exposed E --rule R` | Puts a dated entry at the top of `records.lessons`. |
| `agent-steddy record finish <branch>` | Runs `verifyCommand` on the branch, fast-forwards `workingBranch` onto it and deletes it; it refuses when the verify fails and never pushes. |

Claude Code puts the plugin's `bin/` folder on the Bash tool's `PATH` while the plugin is enabled; Claude.ai and Cowork do not install a plugin that has one.
See [docs/config.md](docs/config.md) for the clocks, the file formats, `finish` and the keys.

## Method

The method for a task has three parts.

- The [gates skill](skills/gates/SKILL.md) holds the walls, the seven gates, task sizing, the verification ladder, roles and the learning loop; its description tells Claude when to load it.
- The [finish skill](skills/finish/SKILL.md) runs gates 6 and 7 as commands: the decisions, the retro, the metrics line, the commit of the records, the merge and the report.
- The [templates](templates/README.md) hold an orchestrator role card, the shape of a role card, an agent file for each kind of agent and the brief for a subagent; a project copies them and fills in the placeholders.

The gates skill marks which walls a hook enforces and which ones a person has to keep.

## Example project

[examples/acme](examples/acme/README.md) is a small complete project for a made-up company: the config, the four agents filled in from the templates and their role cards.
`tests/test_example_project.py` runs the real hook scripts and the command against it, so the config, the agents and the hooks are proved together.
Copy it as a starting point, and read it next to the [config reference](docs/config.md).

## Develop

```bash
claude plugin validate .
python3 -I -m unittest discover -s tests
claude --plugin-dir /path/to/agent-steddy    # a session with the plugin loaded
```

## License

MIT, see [LICENSE](LICENSE).
