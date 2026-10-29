"""Project config for every hook: `<project>/.claude/agent-steddy.json` merged over the defaults.

The kit holds the mechanism, each project holds its own settings; this file is the seam between them.
A missing, unreadable or invalid file gives the defaults, so a hook never fails because of its config.
"""
import copy
import json
import os
import sys
from pathlib import Path

DEFAULTS = {
    "workingBranch": "main",
    "verifyCommand": None,
    "agents": {"allowed": ["*"], "models": {}, "writeFences": {}},
    "commands": {"deny": [], "askFromSubagent": [], "alwaysAsk": []},
    "records": {
        "lessons": "docs/agents/lessons.md",
        "metrics": "docs/agents/metrics.jsonl",
        "decisions": "docs/agents/decisions.md",
    },
}


def load(project_dir=None):
    """The defaults with the project file's values on top: objects merge one level down, lists and scalars replace."""
    path = Path(project_dir or os.environ.get("CLAUDE_PROJECT_DIR") or ".") / ".claude" / "agent-steddy.json"
    config = copy.deepcopy(DEFAULTS)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("top level is not an object")
    except FileNotFoundError:
        return config
    except (OSError, ValueError) as error:
        print(f"agent-steddy: ignoring {path}: {error}", file=sys.stderr)
        return config
    for key, value in data.items():
        if isinstance(value, dict) and isinstance(config.get(key), dict):
            config[key].update(value)
        else:
            config[key] = value
    return config
