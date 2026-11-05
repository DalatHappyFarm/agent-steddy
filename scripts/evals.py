"""Lesson evals: stored cases that show a recorded rule still holds, run by `agent-steddy lessons eval`.

A case is one Markdown file in `records.evals` (docs/agents/evals/ by default):

    # <title>

    - Key: <the rule's key in the lessons file>
    - Kind: seen | new
    - Check: <a shell command; exit 0 means the rule held>

    ## Prompt

    <a task an agent might get, for a case judged by a model>

    ## Criteria

    - <what a good answer does>

`seen` is the failure the lessons recorded, and `new` is a task the agent has not met, so a pass shows the rule generalized and was not just remembered.
A case has a Check, or a Prompt and Criteria for a model to judge; with `--judge` the answer is written by `claude -p` given the project's walls file and the lessons `find` returns for the prompt, so a case tests recall and the rule together, and a second `claude -p` judges it against the criteria.
"""
import collections
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python3 -I leaves the script directory off the path
import lessons  # noqa: E402
import project_config  # noqa: E402
from local_state import Refuse  # noqa: E402

FIELD = re.compile(r"- (Key|Kind|Check): *(.*)")
KINDS = ("seen", "new")
TIMEOUT = 600  # seconds for one Check command or one claude call
# no tools, no saved session, and no settings, so the project's hooks (this kit's among them) neither fire nor start a task clock
CLAUDE = ["claude", "-p", "--tools", "", "--no-session-persistence", "--setting-sources", "", "--strict-mcp-config"]
ANSWER = "You answer one task for this project. You have no tools and no files, so do not plan to look anything up: write the deliverable the task asks for (the code, the commands or the text) directly."
JUDGE = """You check one answer against criteria, and nothing else.

Criteria:
{criteria}

Answer:
{answer}

Reply with PASS or FAIL on the first line, then one line that names the criterion that failed, or says why it passed."""

# the file, its key, kind and Check command, its Prompt and Criteria texts ("" when missing), and what is wrong with it (None)
Case = collections.namedtuple("Case", "path key kind check prompt criteria problem")


def parse_case(path, text):
    """The Case of one file: the fields come from the bullets before the first `## ` heading, the texts from the Prompt and Criteria sections."""
    lines = text.split("\n")
    marks = lessons.headings(lines)
    fields = {}
    for line in lines[:marks[0] if marks else len(lines)]:
        found = FIELD.fullmatch(line.rstrip())
        if found:
            fields.setdefault(found.group(1), found.group(2).strip())
    sections = {}
    for number, start in enumerate(marks):
        end = marks[number + 1] if number + 1 < len(marks) else len(lines)
        sections[lines[start][3:].strip().lower()] = "\n".join(lines[start + 1:end]).strip()
    key, kind, check = fields.get("Key", ""), fields.get("Kind", ""), fields.get("Check", "")
    prompt, criteria = sections.get("prompt", ""), sections.get("criteria", "")
    problem = None
    if not (re.fullmatch(lessons.SLUG, key) and len(key) <= lessons.MAX_KEY):
        problem = "no valid `- Key: <key>` line"
    elif kind not in KINDS:
        problem = f"`- Kind:` must be {' or '.join(KINDS)}"
    elif not check and not (prompt and criteria):
        problem = "it needs a `- Check: <command>` line, or a `## Prompt` and a `## Criteria` section"
    return Case(path, key, kind, check, prompt, criteria, problem)


def read_cases(folder):
    """Every case of the folder, by file name; [] when the folder is missing."""
    try:
        paths = sorted(Path(folder).glob("*.md"))
    except OSError:
        return []
    cases = []
    for path in paths:
        try:
            cases.append(parse_case(path, path.read_text(encoding="utf-8")))
        except (OSError, ValueError) as error:
            cases.append(Case(path, "", "", "", "", "", f"unreadable: {error}"))
    return cases


def case_keys(folder):
    """The keys that have a valid case: a rule broken after its promotion is off the broken list once it has one."""
    return {case.key for case in read_cases(folder) if not case.problem}


def tail(text, count=10):
    return ["    " + line for line in text.strip().splitlines()[-count:]]


def run_check(project, case):
    """(passed, the lines that show why it failed)."""
    try:
        done = subprocess.run(case.check, shell=True, cwd=project, capture_output=True, text=True, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        return False, [f"    timed out after {TIMEOUT} s"]
    return done.returncode == 0, [] if done.returncode == 0 else [f"    exit {done.returncode}", *tail(done.stdout + done.stderr)]


def claude(prompt, model=None):
    """The text `claude -p` answers to `prompt`, run in an empty folder; Refuse when the CLI is missing, None when it failed."""
    command = CLAUDE + (["--model", model] if model else [])
    with tempfile.TemporaryDirectory() as empty:
        try:
            done = subprocess.run(command, input=prompt, cwd=empty, capture_output=True, text=True, timeout=TIMEOUT)
        except FileNotFoundError:
            raise Refuse("claude is not on the PATH; --judge needs the Claude Code CLI") from None
        except subprocess.TimeoutExpired:
            return None
    return done.stdout if done.returncode == 0 else None


def answer_prompt(project, config, prompt, bare=False):
    """What the answering model gets: a line that it has no tools, the walls file, the lessons `find` returns for the prompt, and the task; `bare` leaves out the walls and the lessons."""
    project = Path(project)
    parts = [ANSWER]
    if bare:
        return "\n\n".join([*parts, "Task:\n" + prompt])
    walls = project / project_config.get(config, "records", "walls")
    if walls.is_file():
        parts.append(walls.read_text(encoding="utf-8").strip())
    entries = lessons.read(project / project_config.get(config, "records", "lessons"))
    if lessons.find(entries, prompt, 1):
        parts.append("Lessons this project recorded that may apply:\n" + "\n".join(lessons.find_lines(entries, prompt, lessons.RECALL_TOP)))
    parts.append("Task:\n" + prompt)
    return "\n\n".join(parts)


def judge_case(project, config, case, model=None, bare=False):
    """(passed, the lines that show why) for a case with a Prompt and Criteria; the judge runs on claude's default model."""
    answer = claude(answer_prompt(project, config, case.prompt, bare), model)
    if answer is None:
        return False, ["    claude failed or timed out while answering"]
    verdict = claude(JUDGE.format(criteria=case.criteria, answer=answer.strip()))
    lines = (verdict or "").strip().splitlines()
    if not lines:
        return False, ["    claude failed or timed out while judging"]
    return lines[0].strip().upper().startswith("PASS"), ["    " + line for line in lines[1:2]]


def run(project, config, key=None, judge=False, model=None, bare=False):
    """(the report lines, True when every case that ran passed): a line per case, then a summary by kind.

    A case with a Check runs it; one with a Prompt and Criteria is judged when `judge` is set and listed for review otherwise; a broken case file fails.
    `bare` judges the answers of a model that gets neither the walls nor the lessons: a case that passes bare does not show that the lesson works.
    """
    project = Path(project)
    folder = project / project_config.get(config, "records", "evals")
    shown = lessons.relative(project, folder)
    cases = [case for case in read_cases(folder) if key is None or case.key == key]
    if not cases:
        return [f"no eval case{' for ' + key if key else ''} in {shown}; add one per promoted rule, a seen case and a new one (see docs/config.md, Lesson evals)"], True
    out, tally, ok = [], collections.Counter(), True
    for case in cases:
        name = f"{case.key or '?'} ({case.kind or '?'}) {lessons.relative(project, case.path)}"
        if case.problem:
            out.append(f"BAD     {name}: {case.problem}")
            ok = False
            continue
        if case.check:
            passed, why = run_check(project, case)
        elif judge:
            passed, why = judge_case(project, config, case, model, bare)
        else:
            out.append(f"REVIEW  {name}: no Check; run with --judge, or read the prompt and criteria and judge it yourself")
            tally[(case.kind, "review")] += 1
            continue
        out += [f"{'PASS' if passed else 'FAIL'}    {name}", *why]
        tally[(case.kind, "pass" if passed else "fail")] += 1
        ok = ok and passed
    summary = []
    for kind in KINDS:
        ran = tally[(kind, "pass")] + tally[(kind, "fail")]
        if ran or tally[(kind, "review")]:
            summary.append(f"{kind}: {tally[(kind, 'pass')]} of {ran} passed" + (f", {tally[(kind, 'review')]} to review" if tally[(kind, "review")] else ""))
    note = [" (bare: answered without the walls and the lessons)"] if bare and judge else [""]
    return out + ["", "summary: " + ("; ".join(summary) or "no case ran") + note[0]], ok
