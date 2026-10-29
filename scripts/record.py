"""Records: write a decision or a lesson in the right place, and merge a verified branch.

Run as `agent-steddy record ...` (see cli.py).
Every function takes the paths it works on, so the tests call them directly; the paths come from the project config (`records.*`, `workingBranch`, `verifyCommand`).
"""
import datetime as dt
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python3 -I leaves the script directory off the path
import project_config  # noqa: E402
from local_state import Refuse  # noqa: E402

DECISIONS_HEADER = """# Decisions

One line per decision: `- [area] text`.
Add them with `agent-steddy record decision "<area>" "<text>"`.

"""

LESSONS_TEMPLATE = """# Lessons

One entry per task, newest first: what worked, what the task exposed, and the rule to keep.
Add them with `agent-steddy record lesson`.

```text
## <date> - <task> - roles: <a, b>
- Worked: <what held up>
- Exposed: <what the task showed was missing, or none>
- Rule: <the rule to keep, or none>
```

A rule that is broken twice moves up: into a role card, and from there into a hook, so it is enforced and not remembered.
"""


def one_line(name, value):
    value = (value or "").strip()
    if not value:
        raise Refuse(f"{name} is empty")
    if "\n" in value or "\r" in value:
        raise Refuse(f"{name} must be a single line")
    return value


def decision(path, area, text):
    """Append `- [<area>] <text>` to the decisions file, creating it with a short header when it is missing. Returns the line."""
    area, text = one_line("area", area), one_line("text", text)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _./-]*", area):
        raise Refuse("area must be a short tag such as app, website or store")
    line = f"- [{area}] {text}"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(DECISIONS_HEADER, encoding="utf-8")
    newline = "" if path.read_bytes().endswith(b"\n") else "\n"
    with path.open("a", encoding="utf-8") as lines:
        lines.write(f"{newline}{line}\n")
    return line


def first_entry(lines):
    """The index of the first `## ` heading that is not inside a code fence, None when there is none."""
    fenced = False
    for index, line in enumerate(lines):
        if line.startswith("```"):
            fenced = not fenced
        elif not fenced and line.startswith("## "):
            return index
    return None


def lesson(path, task, roles, worked, exposed, rule, today=None):
    """Put a dated entry at the top of the lessons file, newest first, creating the file from a template when it is missing. Returns its heading."""
    task, worked, exposed, rule = (one_line(name, value) for name, value in (("task", task), ("worked", worked), ("exposed", exposed), ("rule", rule)))
    role_list = [role.strip() for role in (roles or "").split(",") if role.strip()]
    if not role_list:
        raise Refuse("roles is empty")
    heading = f"## {today or dt.date.today().isoformat()} - {task} - roles: {', '.join(role_list)}"
    entry = [heading, f"- Worked: {worked}", f"- Exposed: {exposed}", f"- Rule: {rule}", ""]
    # ponytail: read, insert, write - two agents recording at the same moment could lose an entry; one agent per task records, add a lock if that changes
    lines = (path.read_text(encoding="utf-8") if path.exists() else LESSONS_TEMPLATE).split("\n")
    index = first_entry(lines)
    if index is None:
        while lines and lines[-1] == "":
            lines.pop()
        lines += [""] + entry
    else:
        lines[index:index] = entry
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return heading


def git(root, *args, check=True):
    done = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    if check and done.returncode:
        raise Refuse(f"git {' '.join(args)} failed: {done.stderr.strip() or done.stdout.strip()}")
    return done


def finish(root, branch, config, full=False, no_verify=False, say=None):
    """Verify `branch`, fast-forward `workingBranch` onto it and delete it. Never pushes.

    The branch must fast-forward onto the working branch and the working tree must be clean.
    The project's `verifyCommand` runs on the branch itself (`--full` appends ` --full`, for a verify script that scopes itself to what the branch changed), and a failure merges nothing.
    With no `verifyCommand` nothing proves the branch, so it refuses unless `no_verify` is given; with one, `no_verify` is refused so the gate cannot be skipped by accident.
    """
    say = say or (lambda message: print(f"[finish] {message}", flush=True))
    base = config.get("workingBranch")
    base = base if isinstance(base, str) and base else project_config.DEFAULTS["workingBranch"]
    command = config.get("verifyCommand")
    if command is not None and not (isinstance(command, str) and command.strip()):
        raise Refuse("verifyCommand in the project config must be a command string or null")
    if command is None and not no_verify:
        raise Refuse("verifyCommand is not set in the project config, so nothing proves the branch; set it, or pass --no-verify to merge without proof")
    if command is not None and no_verify:
        raise Refuse("verifyCommand is set in the project config; run finish without --no-verify")
    if branch == base or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", branch):
        raise Refuse(f"bad branch name: {branch!r} (it must differ from {base})")
    for name in (branch, base):
        if git(root, "rev-parse", "--verify", "--quiet", f"refs/heads/{name}", check=False).returncode:
            raise Refuse(f"branch {name} does not exist")
    if git(root, "status", "--porcelain").stdout.strip():
        raise Refuse("the working tree is not clean; commit your files by path first")
    if git(root, "merge-base", "--is-ancestor", base, branch, check=False).returncode:
        raise Refuse(f"{branch} does not fast-forward onto {base}; rebase it onto {base} or merge {base} into it first")
    say(f"{branch} fast-forwards onto {base}")
    if command is not None:
        command += " --full" if full else ""
        start = git(root, "branch", "--show-current").stdout.strip() or base
        git(root, "switch", branch)  # the proof is of the branch itself
        say(f"{command} on {branch}")
        try:
            done = subprocess.run(command, shell=True, cwd=root, capture_output=True, text=True)
        finally:
            git(root, "switch", start)
        if done.returncode:
            tail = "\n".join((done.stdout + done.stderr).strip().splitlines()[-40:])
            raise Refuse(f"{command} failed on {branch} (exit {done.returncode}), nothing merged:\n{tail}")
        say(f"{command} passed")
    git(root, "switch", base)
    merged = git(root, "merge", "--ff-only", branch).stdout.strip().splitlines()
    say("merged: " + (merged[0] if merged else "ok"))
    git(root, "branch", "-d", branch)
    say(f"deleted {branch}")
    say(f"done, on {base} (nothing was pushed)")
