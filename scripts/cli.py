"""The `agent-steddy` command: metrics and records for a project (bin/agent-steddy runs this file).

  agent-steddy metrics start "<task>" [--force]     name the task and start its clock
  agent-steddy metrics log --size S|M|L --type new|feedback --verify-first-pass yes|no [--task T] [--roles a,b] [--agents N] [--minutes N] [--exposed N]
                                                    append one line to the metrics file and close the clock
  agent-steddy metrics report [--weeks 8]           weekly tables: tasks, and git rework by commit prefix
  agent-steddy metrics slow [--days 7] [--top 10]   Bash commands by total time and count
  agent-steddy metrics selftest                     a quick check of the installed scripts

  agent-steddy record decision "<area>" "<text>"    append `- [area] text` to the decisions file
  agent-steddy record lesson --task T --roles a,b --worked W --exposed E --rule R
                                                    put a dated entry at the top of the lessons file
  agent-steddy record finish <branch> [--full] [--no-verify]
                                                    verify the branch, fast-forward the working branch onto it, delete it; never pushes

The project is `CLAUDE_PROJECT_DIR` when set, else the nearest folder from the cwd up that has `.claude/agent-steddy.json` or `.git`.
Every path comes from the project config (docs/config.md); the exit code is 1 when a command is refused, with the reason on stderr.
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python3 -I leaves the script directory off the path
import local_state  # noqa: E402
import metrics  # noqa: E402
import project_config  # noqa: E402
import record  # noqa: E402
from local_state import Refuse  # noqa: E402


def build_parser():
    parser = argparse.ArgumentParser(prog="agent-steddy", description="Metrics and records for a project that works with Claude Code agents.")
    groups = parser.add_subparsers(dest="group", required=True)
    commands = groups.add_parser("metrics", help="task clocks, the metrics file and the reports").add_subparsers(dest="command", required=True)
    start = commands.add_parser("start", help="name the task and start its clock")
    start.add_argument("task")
    start.add_argument("--force", action="store_true", help="replace a running named task")
    log = commands.add_parser("log", help="append one line for a finished task and close the clock")
    log.add_argument("--task", help="the task name; default is the name given to `start`")
    log.add_argument("--size", choices=["S", "M", "L"], required=True)
    log.add_argument("--type", dest="task_type", choices=["new", "feedback"], required=True, help="new for a fresh request, feedback for an owner round on earlier work")
    log.add_argument("--roles", default="", help="comma separated")
    log.add_argument("--agents", type=int, default=0)
    log.add_argument("--minutes", type=int, help="the work in minutes; default is the clock")
    log.add_argument("--exposed", type=int, default=0, help="defects the owner found in work that was already delivered")
    log.add_argument("--verify-first-pass", choices=["yes", "no"], required=True)
    report = commands.add_parser("report", help="weekly tables of tasks and git rework")
    report.add_argument("--weeks", type=int, default=8)
    slow = commands.add_parser("slow", help="Bash commands grouped by total time and count")
    slow.add_argument("--days", type=int, default=7)
    slow.add_argument("--top", type=int, default=10)
    commands.add_parser("selftest", help="a quick check of the installed scripts")
    records = groups.add_parser("record", help="decisions, lessons and the merge that ends a task").add_subparsers(dest="command", required=True)
    decision = records.add_parser("decision", help="append a decision to the decisions file")
    decision.add_argument("area", help="a short tag such as app or website")
    decision.add_argument("text", help="one line: the decision and why")
    lesson = records.add_parser("lesson", help="put an entry at the top of the lessons file")
    for field in ("task", "roles", "worked", "exposed", "rule"):
        lesson.add_argument(f"--{field}", required=True, help="comma separated" if field == "roles" else "one line")
    finish = records.add_parser("finish", help="verify a branch, fast-forward the working branch onto it and delete it; never pushes")
    finish.add_argument("branch")
    finish.add_argument("--full", action="store_true", help="append --full to verifyCommand")
    finish.add_argument("--no-verify", action="store_true", help="merge without proof; only when the project has no verifyCommand")
    return parser


def run_metrics(args, project, config, state):
    log_file = Path(project) / project_config.get(config, "records", "metrics")
    if args.command == "start":
        return [metrics.start(state, args.task, args.force)]
    if args.command == "log":
        row = metrics.log(state, log_file, args.size, args.task_type, args.verify_first_pass, args.task, args.roles, args.agents, args.minutes, args.exposed)
        note = ["note: the task name is still the auto name; pass --task next time"] if str(row["task"]).startswith("auto ") else []
        return [*note, f"logged: {json.dumps(row, ensure_ascii=False)}"]
    if args.command == "report":
        return metrics.report(log_file, project_config.get(config, "records", "metrics"), project, args.weeks)
    if args.command == "slow":
        return metrics.slow(state, args.days, args.top)
    metrics.selftest()
    return ["selftest ok"]


def run_record(args, project, config):
    if args.command == "decision":
        path = Path(project) / project_config.get(config, "records", "decisions")
        return [f"added: {record.decision(path, args.area, args.text)}"]
    if args.command == "lesson":
        path = Path(project) / project_config.get(config, "records", "lessons")
        return [f"added: {record.lesson(path, args.task, args.roles, args.worked, args.exposed, args.rule)}"]
    record.finish(project, args.branch, config, args.full, args.no_verify)  # prints its own progress, since a verify can take minutes
    return []


def main(argv=None):
    args = build_parser().parse_args(argv)
    project = local_state.project_dir()
    try:
        config = project_config.load(project)
        lines = run_metrics(args, project, config, local_state.state_dir(project)) if args.group == "metrics" else run_record(args, project, config)
        for line in lines:
            print(line)
    except Refuse as error:
        print(f"agent-steddy: refused: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
