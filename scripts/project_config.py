"""Project config for every hook: `<project>/.claude/agent-steddy.json` merged over the defaults.

The kit holds the mechanism, each project holds its own settings; this file is the seam between them.
A missing, unreadable or invalid file gives the defaults, so a hook never fails because of its config.
"""
import copy
import json
import os
import sys
from pathlib import Path

DEFAULT_REMINDER = (
    "Seven gates for this request: 1 Intake (the goal, the scope and the size; ask when it is unclear) -> "
    "2 Recall (the rules, the role notes and the lessons so far) -> "
    "3 Shape (the role, the split, what done means) -> 4 Act -> "
    "5 Prove (evidence you looked at; re-check what sub-agents report) -> "
    "6 Record (decisions with `agent-steddy record decision`, a retro with `agent-steddy record lesson`, a metrics line with `agent-steddy metrics log`) -> "
    "7 Deliver (an honest report; commit or merge only when asked)."
)

DEFAULTS = {
    "workingBranch": "main",
    "verifyCommand": None,
    "agents": {"allowed": ["*"], "models": {}, "writeFences": {}},
    "guards": {"disable": []},
    "handback": {
        "agents": [],
        "required": [
            {"id": "status", "pattern": r"\b(?:PASS|ISSUES|BLOCKED)\b", "hint": "a status: PASS, ISSUES or BLOCKED"},
            {"id": "verification", "pattern": r"(?i:verif)|\bL[0-5]\b", "hint": "the verification level used"},
            {"id": "retro", "pattern": r"(?i:retro)", "hint": "a one line retro (worked / exposed / rule)"},
        ],
    },
    "commands": {"deny": [], "askFromSubagent": [], "alwaysAsk": []},
    "resume": {"folder": None},  # None keeps the resume notes in the local state; a project-relative folder keeps them in the repo
    "reminder": {"enabled": True, "text": DEFAULT_REMINDER},
    "nudges": {"premise": True},  # the premise nudge of tool_timing.py
    "records": {
        "lessons": "docs/agents/lessons.md",
        "metrics": "docs/agents/metrics.jsonl",
        "decisions": "docs/agents/decisions.md",
        "roles": "docs/agents/roles",
        "walls": "docs/agents/walls.md",
    },
}


def get(config, section, key):
    """config[section][key] when it has the type of the default, else a copy of the default, so a hook never trips over a wrongly typed value."""
    default = DEFAULTS[section][key]
    value = config.get(section)
    value = value.get(key) if isinstance(value, dict) else None
    return value if isinstance(value, type(default)) else copy.deepcopy(default)


def working_branch(config):
    """The branch agents work on and merge into: `workingBranch`, else the default."""
    branch = config.get("workingBranch")
    return branch if isinstance(branch, str) and branch else DEFAULTS["workingBranch"]


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
