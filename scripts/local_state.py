"""Where the kit keeps its local state, and which project a process belongs to.

The state is the pending task clock and the tool timing log; it is never committed.
It lives in the git common dir (`<repo>/.git/agent-steddy/`), which every worktree of a repo shares.
Outside a git repo it falls back to `CLAUDE_PLUGIN_DATA`, which Claude Code gives to hook processes and not to the commands the Bash tool runs.
"""
import hashlib
import os
from pathlib import Path

NAME = "agent-steddy"
PENDING = "pending-task.json"  # the task clock: {"task", "start", "prompt_start"}
TIMES = "tool-times.jsonl"  # one line per Bash command
MARKS = "tool-marks"  # start times of Bash commands that have not finished


def project_dir():
    """The project root: `CLAUDE_PROJECT_DIR` (set for hooks), else the nearest folder from the cwd up that has `.claude/agent-steddy.json` or `.git`, else the cwd."""
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        return Path(env)
    cwd = Path.cwd()
    for folder in [cwd, *cwd.parents]:
        if (folder / ".claude" / "agent-steddy.json").is_file() or (folder / ".git").exists():
            return folder
    return cwd


def git_common_dir(start):
    """The git common dir of the repo that holds `start`, a linked worktree included; None outside a repo."""
    for folder in [start, *start.parents]:
        dot = folder / ".git"
        if dot.is_dir():
            return dot
        if dot.is_file():
            text = dot.read_text(encoding="utf-8")
            if text.startswith("gitdir:"):
                gitdir = folder / text[len("gitdir:"):].strip()  # a relative path starts at the folder, an absolute one replaces it
                commondir = gitdir / "commondir"  # a linked worktree names its common dir here, relative to itself
                return (gitdir / commondir.read_text(encoding="utf-8").strip() if commondir.is_file() else gitdir).resolve()
    return None


def state_dir(project):
    """The folder for local state, not created; None outside a git repo when there is no `CLAUDE_PLUGIN_DATA` either."""
    project = Path(project).resolve()
    common = git_common_dir(project)
    if common:
        return common / NAME
    data = os.environ.get("CLAUDE_PLUGIN_DATA")
    # one plugin data folder serves every project, so each project outside a repo gets its own subfolder
    return Path(data) / hashlib.sha256(str(project).encode()).hexdigest()[:12] if data else None
