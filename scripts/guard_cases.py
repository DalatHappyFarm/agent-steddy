"""`agent-steddy guard --cases`: recorded command lines, each with the verdict the Bash guard must give it.

A project keeps the lines that its deny and ask rules were written for, and a verify command runs them, so a config edit or a plugin update that changes a verdict fails the verify.
One case per line: `<deny|ask|allow> [@<agent-type>] <command line>`; a blank line and a line that starts with `#` are skipped.
"""
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python3 -I leaves the script directory off the path
import guard_bash  # noqa: E402
import project_config  # noqa: E402
from local_state import Refuse  # noqa: E402

VERDICTS = ("deny", "ask", "allow")
CASE = re.compile(r"(\S+)\s*(@\S*)?\s*(.*)")  # the verdict, an optional @agent, the command line


def parse(text, name):
    """[(line number, verdict, agent type or None, command line, the case as written after the verdict)] for the cases of `text`; a Refuse (exit 2) names the first malformed line."""
    cases = []
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        want, agent, command = CASE.fullmatch(line).groups()
        if want not in VERDICTS:
            raise Refuse(f"{name} line {number}: a case starts with deny, ask or allow, not {want!r}: {line}", 2)
        if agent == "@":
            raise Refuse(f"{name} line {number}: '@' needs an agent type right after it: {line}", 2)
        if not command:
            raise Refuse(f"{name} line {number}: no command line after the verdict: {line}", 2)
        cases.append((number, want, agent[1:] if agent else None, command, line[len(want):].strip()))
    return cases


def run(project, config, file=None):
    """(lines to print, whether every case held) for the cases file `file`, else the project's `records.guardCases`; a Refuse (exit 2) when it is missing or has a malformed line."""
    path = Path(file) if file else Path(project) / project_config.get(config, "records", "guardCases")
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, ValueError) as error:
        raise Refuse(f"cannot read the guard cases file {path}: {getattr(error, 'strerror', None) or error}; pass a file, or set records.guardCases in the project config", 2) from error
    cases = parse(text, path)  # all of it first: a malformed line refuses before anything runs
    lines = []
    for number, want, agent, command, written in cases:
        kind = (guard_bash.judge(command, agent, config) or ("allow",))[0]
        if kind != want:
            lines.append(f"FAIL line {number}: want {want}, got {kind}: {written}")
    failed = len(lines)
    return [*lines, f"guard cases: {len(cases) - failed} passed, {failed} failed"], not failed
