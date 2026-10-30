"""Resume notes: stop a task safely, and pick it up again in a new session or after the context was summarized.

`agent-steddy pause` writes one note per branch with a fixed shape; `agent-steddy resume` prints it and what changed since; `record finish` deletes it.
The notes live in the local state (`<git common dir>/agent-steddy/resume/`, never committed, shared by the worktrees of a repo), or, with `resume.folder`, in a project-relative folder that the project commits by path if other machines should see them.
The kit never commits a note.
A note is a claim, not evidence: the git history and the verify command decide what is done.
Every function takes the project root and the config, so the tests call them directly; the `SessionStart` hook (session_start.py) calls `pointer`.
"""
import datetime as dt
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python3 -I leaves the script directory off the path
import local_state  # noqa: E402
import project_config  # noqa: E402
from local_state import Refuse, git, one_line  # noqa: E402

MAX_STAT_LINES = 40  # a longer `git diff --stat` keeps its first lines and its summary line
NONE = "none"
CLAIM = "The note is a claim, not evidence: check Done against git ({checks}) and run {verify}; do not redo what git shows is done."


def folder_setting(config):
    """`resume.folder` as a non-empty string, else None (the local state)."""
    section = config.get("resume")
    value = section.get("folder") if isinstance(section, dict) else None
    return value.strip() if isinstance(value, str) and value.strip() else None


def outside_project(setting):
    """Whether a `resume.folder` value points out of the project: an absolute path, or one with `..`."""
    path = Path(setting)
    return path.is_absolute() or ".." in path.parts


def note_folder(project, config):
    """Where the notes live, not created. Refuses a folder that is not inside the project, and, with no `resume.folder`, a project that is not a git repo."""
    setting = folder_setting(config)
    if setting:
        if outside_project(setting):
            raise Refuse(f"resume.folder must be a folder inside the project, not {setting!r}", 2)
        return Path(project) / setting
    common = local_state.git_common_dir(Path(project).resolve())
    if common is None:
        raise Refuse("this is not a git repo, so the resume notes have no place in the local state; set resume.folder to a folder of the project", 2)
    return common / local_state.NAME / "resume"


def note_name(branch):
    """The file name of a branch's note: `/` becomes `__`, so `feat/x` is `feat__x.md`."""
    return branch.replace("/", "__") + ".md"


def current_branch(project):
    """The branch the checkout is on, "" on a detached HEAD and outside a repo."""
    done = git(project, "branch", "--show-current", check=False)
    return done.stdout.strip() if done.returncode == 0 else ""


def need_branch(project, branch=None):
    """`branch`, else the checked out branch; refuses (exit 2) outside a git repo and on a detached HEAD."""
    if local_state.git_common_dir(Path(project).resolve()) is None:
        raise Refuse("this is not a git repo", 2)
    if branch:
        return branch
    found = current_branch(project)
    if not found:
        raise Refuse("HEAD is detached, so there is no branch to keep a note for; switch to a branch, or pass --branch", 2)
    return found


def fields(text):
    """The date, branch and full HEAD hash that a note's header lines name; a missing one is left out."""
    found = {}
    for name, pattern in (("date", r"- Date: (.+)"), ("branch", r"- Branch: (.+)"), ("head", r"- HEAD: ([0-9a-f]{7,64})(?: .*)?")):
        match = re.search(f"^{pattern}$", text, re.M)
        if match:
            found[name] = match.group(1).strip()
    return found


def read_note(folder, branch):
    """The note text of `branch`, None when there is none or when the file names another branch (two branch names can map to one file name)."""
    try:
        text = (folder / note_name(branch)).read_text(encoding="utf-8")
    except OSError:
        return None
    return text if fields(text).get("branch") == branch else None


def exclude_note_folder(project, config):
    """The `git status` arguments that leave the note folder out of the file list, so a note kept in the repo does not make the tree dirty; [] with no `resume.folder`."""
    setting = folder_setting(config)
    if not setting or outside_project(setting):  # an unusable setting is refused where the folder is needed, not here
        return []
    absolute = Path(project).resolve() / setting
    return ["--", ":/", f":(exclude,literal){absolute}"]  # ":/" keeps the whole repo in view when the project is a subfolder


def changed_files(project, config):
    """The uncommitted and untracked files as `<status> <path>` lines, the note folder left out."""
    done = git(project, "status", "--porcelain", "--untracked-files=all", *exclude_note_folder(project, config))
    return [line[:2].strip() + " " + line[3:] for line in done.stdout.splitlines() if line.strip()]


def diff_stat(project, base):
    """(merge base short hash or None, the `git diff --stat` lines from it to HEAD)."""
    if git(project, "rev-parse", "--verify", "--quiet", f"refs/heads/{base}", check=False).returncode:
        return None, []
    merge = git(project, "merge-base", base, "HEAD", check=False)
    if merge.returncode:
        return None, []
    commit = merge.stdout.strip()
    lines = git(project, "diff", "--stat", commit, "HEAD").stdout.splitlines()
    if len(lines) > MAX_STAT_LINES:
        lines = [*lines[:MAX_STAT_LINES - 2], f" ... {len(lines) - MAX_STAT_LINES + 1} more lines", lines[-1]]
    return commit[:12], lines


def bullets(items):
    return [f"- {item}" for item in items] or [f"- {NONE}"]


def render(branch, head, subject, base, merge, stat, changed, intent, done, open_decisions, next_step, files, pitfalls, now):
    """The text of a note, in its fixed shape."""
    base_line = f"{base} (merge base {merge})" if merge else f"{base} (not found, so there is no diff against it)"
    return "\n".join([
        f"# Resume note: {branch}", "",
        f"- Date: {now:%Y-%m-%d %H:%M}",
        f"- Branch: {branch}",
        f"- HEAD: {head} {subject}",
        f"- Base: {base_line}", "",
        "## Committed since the base", "```text", *(stat or [NONE]), "```", "",
        "## Uncommitted files", *bullets(changed), "",
        "## Intent", intent, "",
        "## Done and verified", done, "",
        "## Open decisions", open_decisions, "",
        "## Next step", next_step, "",
        "## Key files", *bullets(files), "",
        "## Pitfalls", pitfalls, "",
    ])


def pause(project, config, intent, done, next_step, open_decisions=None, pitfalls=None, files=None, now=None):
    """Write the note of the checked out branch, replacing its older note. Returns the lines to print.

    Intent, done (what is done and how it was verified, with the ladder level) and next are required single lines.
    It commits nothing, even when the notes live in the repo.
    """
    project = Path(project)
    branch = need_branch(project)
    intent, done, next_step = one_line("intent", intent), one_line("done", done), one_line("next", next_step)
    open_decisions = NONE if open_decisions is None else one_line("open", open_decisions)
    pitfalls = NONE if pitfalls is None else one_line("pitfalls", pitfalls)
    key_files = [name.strip() for name in (files or "").split(",") if name.strip()]
    if git(project, "rev-parse", "--verify", "--quiet", "HEAD", check=False).returncode:
        raise Refuse("this branch has no commit yet, so the note has no HEAD to name", 2)
    folder = note_folder(project, config)
    head = git(project, "rev-parse", "HEAD").stdout.strip()
    subject = git(project, "log", "-1", "--format=%s").stdout.strip()
    base = project_config.working_branch(config)
    merge, stat = diff_stat(project, base)
    text = render(branch, head, subject, base, merge, stat, changed_files(project, config), intent, done, open_decisions, next_step, key_files, pitfalls, now or dt.datetime.now())
    path = folder / note_name(branch)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if folder_setting(config):
        shown = path.relative_to(project).as_posix()
        return [f"saved: {shown}", f"nothing was committed; commit the note by path if other machines should see it: git add {shown}, then git commit -m \"<message>\" -- {shown}"]
    return [f"saved: {path}", "kept in the local state of this repo: never committed, shared by every worktree"]


def since(project, config, branch, head):
    """The lines that say what changed after the note: the commits after its HEAD and the uncommitted files now."""
    project = Path(project)
    if git(project, "cat-file", "-e", f"{head}^{{commit}}", check=False).returncode:
        return [f"the note's HEAD {head[:12]} is not in this repo, so compare with the base: git log {project_config.working_branch(config)}..{branch}"]
    out = []
    tip = f"refs/heads/{branch}"
    if git(project, "rev-parse", "--verify", "--quiet", tip, check=False).returncode:
        out.append(f"branch {branch} does not exist here, so no commits are listed")
    elif git(project, "merge-base", "--is-ancestor", head, tip, check=False).returncode:
        out.append(f"the note's HEAD {head[:12]} is not an ancestor of {branch} (rebased or reset); git log {project_config.working_branch(config)}..{branch} shows what is on it")
    else:
        commits = git(project, "log", "--oneline", f"{head}..{tip}").stdout.splitlines()
        out += [f"commits after {head[:12]} ({len(commits)}):", *(f"  {line}" for line in commits or [NONE])]
    if current_branch(project) == branch:
        files = changed_files(project, config)
        out += [f"uncommitted files now ({len(files)}):", *(f"  {line}" for line in files or [NONE])]
    else:
        out.append(f"uncommitted files: not listed, the checkout is on {current_branch(project) or 'a detached HEAD'}, not on {branch}")
    return out


def show(project, config, branch=None):
    """The note of a branch, then what changed since it, then the reminder that it is a claim. Returns the lines to print."""
    project = Path(project)
    branch = need_branch(project, branch)
    folder = note_folder(project, config)
    text = read_note(folder, branch)
    if text is None:
        return [f"no resume note for {branch} (looked in {folder})"]
    verify = config.get("verifyCommand")
    verify = f"the verify command (`{verify}`)" if isinstance(verify, str) and verify.strip() else "the project's checks"
    head = fields(text).get("head")
    return [*text.rstrip("\n").splitlines(), "", "## Since the note",
            *(since(project, config, branch, head) if head else ["the note has no HEAD line, so compare with the base with git log and git diff"]), "",
            CLAIM.format(checks="`git log`, `git diff`", verify=verify)]


def has_note(project, config, branch):
    """Whether `branch` has a note."""
    return read_note(note_folder(project, config), branch) is not None


def clear(project, config, branch=None):
    """Delete the note of a branch. Returns the lines to print; a missing note is not an error."""
    project = Path(project)
    branch = need_branch(project, branch)
    folder = note_folder(project, config)
    path = folder / note_name(branch)
    if not has_note(project, config, branch):
        return [f"no resume note for {branch}, nothing to clear"]
    tracked = bool(folder_setting(config)) and git(project, "ls-files", "--error-unmatch", "--", str(path), check=False).returncode == 0
    path.unlink()
    shown = path.relative_to(project).as_posix() if folder_setting(config) else str(path)
    return [f"cleared: {shown}", *([f"the note was committed; commit its removal by path: git commit -m \"<message>\" -- {shown}"] if tracked else [])]


def pointer(project, config):
    """The one line for the `SessionStart` hook when the checked out branch has a note, else "". Cheap: no git call unless the note folder holds a note."""
    folder = note_folder(project, config)
    if not folder.is_dir() or not any(folder.glob("*.md")):
        return ""
    branch = current_branch(project)
    text = read_note(folder, branch) if branch else None
    if text is None:
        return ""
    return f"Resume note for {branch} from {fields(text).get('date', 'an unknown date')}: run agent-steddy resume before you start."
