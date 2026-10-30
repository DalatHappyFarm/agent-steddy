"""The `agent-steddy` command: metrics and records for a project (bin/agent-steddy runs this file).

  agent-steddy metrics start "<task>" [--force]     name the task and start its clock
  agent-steddy metrics log --size S|M|L --type new|feedback --verify-first-pass yes|no [--task T] [--roles a,b] [--agents N] [--minutes N] [--exposed N]
                                                    append one line to the metrics file and close the clock; --task is required while the task has its auto name
  agent-steddy metrics report [--weeks 8]           weekly tables: tasks, and git rework by commit prefix
  agent-steddy metrics slow [--days 7] [--top 10]   Bash commands by total time and count
  agent-steddy metrics selftest                     a quick check of the installed scripts

  agent-steddy record decision "<area>" "<text>"    append `- [area] text` to the decisions file
  agent-steddy record lesson --task T --roles a,b --worked W --exposed E --rule R [--key K]
                                                    put a dated entry at the top of the lessons file; a rule other than none needs a key
  agent-steddy record finish <branch> [--full] [--no-verify]
                                                    verify the branch, fast-forward the working branch onto it, delete it; never pushes

  agent-steddy pause --intent I --done D --next N [--open O] [--pitfalls P] [--files a,b]
                                                    write the resume note of the current branch (what to know to carry on); commits nothing
  agent-steddy resume [--branch B] [--clear]        print the resume note and what changed since it; --clear deletes it

  agent-steddy lessons check [--quiet]              rules seen twice and not promoted, rules with no key, role cards to prune
  agent-steddy lessons promote <key> --to <role|walls> [--text T] [--force]
                                                    write a repeated rule into a role card's Pitfalls or the walls file, and mark its lines

The project is `CLAUDE_PROJECT_DIR` when set, else the nearest folder from the cwd up that has `.claude/agent-steddy.json` or `.git`.
Every path comes from the project config (docs/config.md); the exit code is 1 when a command is refused and 2 when the learning loop wants another key or target, `metrics log` has only an auto task name, or `pause` and `resume` have no branch or repo to work with, with the reason on stderr.
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python3 -I leaves the script directory off the path
import lessons  # noqa: E402
import local_state  # noqa: E402
import metrics  # noqa: E402
import project_config  # noqa: E402
import record  # noqa: E402
import resume  # noqa: E402
from local_state import Refuse  # noqa: E402


def build_parser():
    parser = argparse.ArgumentParser(prog="agent-steddy", description="Metrics and records for a project that works with Claude Code agents.")
    groups = parser.add_subparsers(dest="group", required=True)
    commands = groups.add_parser("metrics", help="task clocks, the metrics file and the reports").add_subparsers(dest="command", required=True)
    start = commands.add_parser("start", help="name the task and start its clock")
    start.add_argument("task")
    start.add_argument("--force", action="store_true", help="replace a running named task")
    log = commands.add_parser("log", help="append one line for a finished task and close the clock")
    log.add_argument("--task", help="what was done; default is the name given to `start`, and it is required while the task still has its auto name")
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
    helps = {"roles": "comma separated", "rule": "one line; first ask: will it still be true in six months, and would it make a later agent decide differently? if not, none (something that happened once is a fact for --exposed, not yet a rule)"}
    for field in ("task", "roles", "worked", "exposed", "rule"):
        lesson.add_argument(f"--{field}", required=True, help=helps.get(field, "one line"))
    lesson.add_argument("--key", help="a slug that names the rule, such as commit-by-path; the same rule takes the same key; not needed when the rule is none")
    finish = records.add_parser("finish", help="verify a branch, fast-forward the working branch onto it and delete it; never pushes")
    finish.add_argument("branch")
    finish.add_argument("--full", action="store_true", help="append --full to verifyCommand")
    finish.add_argument("--no-verify", action="store_true", help="merge without proof; only when the project has no verifyCommand")
    pause = groups.add_parser("pause", help="write the resume note of the current branch; commits nothing")
    pause.add_argument("--intent", required=True, help="one line: what the task is for")
    pause.add_argument("--done", required=True, help="one line: what is done and how it was verified, with the ladder level")
    pause.add_argument("--next", dest="next_step", required=True, help="one line: the first thing to do when work resumes")
    pause.add_argument("--open", dest="open_decisions", help="one line: decisions still open (default none)")
    pause.add_argument("--pitfalls", help="one line: what to watch for (default none)")
    pause.add_argument("--files", help="comma separated: the files that matter")
    pick_up = groups.add_parser("resume", help="print the resume note of a branch and what changed since it")
    pick_up.add_argument("--branch", help="the branch; default is the checked out one")
    pick_up.add_argument("--clear", action="store_true", help="delete the note instead of printing it")
    loop = groups.add_parser("lessons", help="the learning loop: rules that repeat, and moving them up").add_subparsers(dest="command", required=True)
    check = loop.add_parser("check", help="rules seen twice and not promoted, rules with no key, role cards to prune")
    check.add_argument("--quiet", action="store_true", help="print one summary line, and nothing when no rule is due")
    promote = loop.add_parser("promote", help="write a repeated rule into a role card or the walls file, and mark its lines")
    promote.add_argument("key")
    promote.add_argument("--to", required=True, help="a role (the file name of its card without .md), or walls")
    promote.add_argument("--text", help="the final wording; default is the rule text of the newest entry")
    promote.add_argument("--force", action="store_true", help="promote a rule seen only once")
    return parser


def run_metrics(args, project, config, state):
    log_file = Path(project) / project_config.get(config, "records", "metrics")
    if args.command == "start":
        return [metrics.start(state, args.task, args.force)]
    if args.command == "log":
        row = metrics.log(state, log_file, args.size, args.task_type, args.verify_first_pass, args.task, args.roles, args.agents, args.minutes, args.exposed)
        return [f"logged: {json.dumps(row, ensure_ascii=False)}"]
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
        heading = record.lesson(path, args.task, args.roles, args.worked, args.exposed, args.rule, key=args.key)
        notice = [] if lessons.is_none(args.rule) else lessons.repeat_notice(path, args.key)
        return [f"added: {heading}", *notice]
    record.finish(project, args.branch, config, args.full, args.no_verify)  # prints its own progress, since a verify can take minutes
    return []


def run_lessons(args, project, config):
    if args.command == "check":
        line = lessons.nudge(Path(project) / project_config.get(config, "records", "lessons"))
        return ([line] if line else []) if args.quiet else lessons.check(project, config)
    return lessons.promote(project, config, args.key, args.to, args.text, args.force)


def main(argv=None):
    args = build_parser().parse_args(argv)
    project = local_state.project_dir()
    try:
        config = project_config.load(project)
        if args.group == "metrics":
            lines = run_metrics(args, project, config, local_state.state_dir(project))
        elif args.group == "pause":
            lines = resume.pause(project, config, args.intent, args.done, args.next_step, args.open_decisions, args.pitfalls, args.files)
        elif args.group == "resume":
            lines = (resume.clear if args.clear else resume.show)(project, config, args.branch)
        else:
            lines = (run_record if args.group == "record" else run_lessons)(args, project, config)
        for line in lines:
            print(line)
    except Refuse as error:
        print(f"agent-steddy: refused: {error}", file=sys.stderr)
        return error.code
    return 0


if __name__ == "__main__":
    sys.exit(main())
