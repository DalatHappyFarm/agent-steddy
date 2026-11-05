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
import lessons  # noqa: E402
import project_config  # noqa: E402
import resume  # noqa: E402
from lessons import plural  # noqa: E402
from local_state import Refuse, git, one_line  # noqa: E402

DECISIONS_HEADER = """# Decisions

One line per decision: `- [area] text`.
Add them with `agent-steddy record decision "<area>" "<text>"`.

"""

LESSONS_TEMPLATE = """# Lessons

One entry per task, newest first: what worked, what the task exposed, and the rules to keep.
Add them with `agent-steddy record lesson`.

```text
## <date> - <task> - roles: <a, b>
- Worked: <what held up>
- Exposed: <what the task showed was missing, or none>
- Rule [<key>]: <the rule to keep, or none>
  - When: <the situation it applies to, in the words an agent would use when it comes up>
  - From: <owner or review, when they found it; left out when the agent did>
```

An entry has one Rule line per rule, each with its key and its When line.
The key is a lowercase slug such as `commit-by-path`; the same rule recorded again takes the same key, so the repeat is counted.
The When line is what `agent-steddy lessons find` and the prompt hook match, so write the situation, not a label: "about to report that a test run passed from a command whose output went through a pipe", not "exit codes".
A rule with no key is only allowed when its text is `none`.
Write `none` unless the rule will still be true in six months and would make a later agent decide differently; something that happened once is a fact for the Exposed line.
A rule seen a second time moves up: `agent-steddy lessons promote <key> --to <role>` writes it into a role card, or `--to walls` into the walls file when it is about safety, data or money, and marks its lines ` [promoted -> <path>]`.
A rule broken after that becomes a check, and the check counts as enforced once it has failed on the error recorded here; an eval case keeps that check (`agent-steddy lessons eval`).
A rule that no longer holds is retired with `agent-steddy lessons retire <key> [--by <key>]`, which marks its lines ` [retired]`.
"""


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
    found = lessons.headings(lines)
    return found[0] if found else None


def as_list(value):
    return [] if value is None else [value] if isinstance(value, str) else list(value)


def lesson(path, task, roles, worked, exposed, rule, today=None, key=None, when=None, source="self", new=False):
    """Put a dated entry at the top of the lessons file, newest first, creating the file from a template when it is missing. Returns its heading.

    `rule`, `key` and `when` are a string or lists of the same length, one item per rule, so one task can keep several rules.
    A rule other than `none` needs a `key` (without one nothing is written and the refusal lists the closest recorded rules) and a `when`, the situation it applies to.
    A rule of `none` stands alone and takes no key or When; a key or When passed with it is ignored.
    `source` is self, owner or review: who found what the rules are about; anything but self is written as a From line under each rule.
    A retired key takes no new line, and a new key whose closest recorded rule is promoted is refused unless `new` (lessons.key_refusal).
    """
    task, worked, exposed = (one_line(name, value) for name, value in (("task", task), ("worked", worked), ("exposed", exposed)))
    rules = [one_line("rule", value) for value in as_list(rule)]
    role_list = [role.strip() for role in (roles or "").split(",") if role.strip()]
    if not rules:
        raise Refuse("rule is empty")
    if not role_list:
        raise Refuse("roles is empty")
    if source not in lessons.SOURCES:
        raise Refuse(f"--from must be one of {', '.join(lessons.SOURCES)}")
    if any(lessons.has_marker(text) for text in rules):
        raise Refuse("rule must not contain '[promoted' or '[retired'; `agent-steddy lessons promote` and `retire` write those markers")
    entries = lessons.read(path)
    if any(lessons.is_none(text) for text in rules):
        if len(rules) > 1:
            raise Refuse("a rule of none stands alone; drop it, or drop the other rules", 2)
        items = [("Rule", rules[0], None)]
    else:
        keys, whens = as_list(key), [one_line("when", value) for value in as_list(when)]
        if not keys:
            raise Refuse("\n".join(lessons.missing_key(entries, text) for text in rules), 2)
        if len(keys) != len(rules):
            raise Refuse(f"{plural(len(rules), 'rule')} and {plural(len(keys), 'key')}: give each --rule its --key, in the same order; nothing was written", 2)
        for name in keys:
            lessons.valid_key(name)
        if len(set(keys)) != len(keys):
            raise Refuse("a key appears twice in one entry; one rule per key", 2)
        if len(whens) != len(rules):
            raise Refuse(f"{plural(len(rules), 'rule')} and {plural(len(whens), 'When')}: give each --rule a --when, the situation it applies to in the words an agent would use when it comes up "
                         "(such as: about to report that a test run passed from a command whose output went through a pipe); nothing was written", 2)
        for text, name in zip(rules, keys):
            refusal = lessons.key_refusal(entries, text, name, new)
            if refusal:
                raise Refuse(refusal, 2)
        items = [(f"Rule [{name}]", text, situation) for text, name, situation in zip(rules, keys, whens)]
    heading = f"## {today or dt.date.today().isoformat()} - {task} - roles: {', '.join(role_list)}"
    entry = [heading, f"- Worked: {worked}", f"- Exposed: {exposed}"]
    for label, text, situation in items:
        entry.append(f"- {label}: {text}")
        if situation is not None:
            entry.append(f"  - When: {situation}")
            if source != "self":
                entry.append(f"  - From: {source}")
    entry.append("")
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


def finish(root, branch, config, full=False, no_verify=False, say=None):
    """Verify `branch`, fast-forward `workingBranch` onto it and delete it. Never pushes.

    The branch must fast-forward onto the working branch and the working tree must be clean.
    The project's `verifyCommand` runs on the branch itself (`--full` appends ` --full`, for a verify script that scopes itself to what the branch changed), and a failure merges nothing.
    With no `verifyCommand` nothing proves the branch, so it refuses unless `no_verify` is given; with one, `no_verify` is refused so the gate cannot be skipped by accident.
    """
    say = say or (lambda message: print(f"[finish] {message}", flush=True))
    base = project_config.working_branch(config)
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
    if git(root, "status", "--porcelain", *resume.exclude_note_folder(root, config)).stdout.strip():  # a resume note kept in the repo does not count
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
    try:
        if resume.has_note(root, config, branch):
            for line in resume.clear(root, config, branch):
                say(line)
    except Refuse as error:  # the merge is done; a note that cannot be cleared must not look like a failed merge
        say(f"the resume note was not cleared: {error}")
    say(f"done, on {base} (nothing was pushed)")
