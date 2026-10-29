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


def run_hook(script, data, project_dir, raw=None):
    """The JSON a hook script prints, None when it prints nothing. `raw` replaces the stdin text. Fails when the script exits non-zero."""
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project_dir)}
    stdin = json.dumps(data) if raw is None else raw
    out = subprocess.run([sys.executable, "-I", str(SCRIPTS / script)], input=stdin, capture_output=True, text=True, env=env, check=True).stdout
    return json.loads(out) if out.strip() else None
