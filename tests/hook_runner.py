"""Run a hook script the way Claude Code does: the hook input as JSON on stdin and `CLAUDE_PROJECT_DIR` set to the project."""
import json
import os
import pathlib
import subprocess
import sys

SCRIPTS = pathlib.Path(__file__).resolve().parent.parent / "scripts"


def write_config(project_dir, config):
    """Write `config` (any JSON value) as the project's `.claude/agent-steddy.json`."""
    folder = pathlib.Path(project_dir) / ".claude"
    folder.mkdir(exist_ok=True)
    (folder / "agent-steddy.json").write_text(json.dumps(config))


def run_hook(script, data, project_dir, raw=None, env=None, args=()):
    """The JSON a hook script prints, None when it prints nothing. `raw` replaces the stdin text, `env` adds to the environment, `args` follow the script. Fails when the script exits non-zero."""
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project_dir), **(env or {})}
    stdin = json.dumps(data) if raw is None else raw
    out = subprocess.run([sys.executable, "-I", str(SCRIPTS / script), *args], input=stdin, capture_output=True, text=True, env=env, check=True).stdout
    return json.loads(out) if out.strip() else None


def git(folder, *args):
    """The output of git in `folder`, with a throwaway identity and no signing. Fails when git does."""
    return subprocess.run(["git", "-C", str(folder), "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *args],
                          capture_output=True, text=True, check=True).stdout


def make_repo(folder, branch="main"):
    """A git repo in `folder` on `branch` with one empty commit."""
    git(folder, "init", "-q", "-b", branch)
    git(folder, "commit", "-q", "--allow-empty", "-m", "first")
