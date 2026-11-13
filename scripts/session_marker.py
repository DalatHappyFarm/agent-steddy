"""The marker that tells the `agent-steddy` command whether this plugin's hooks run in the Claude Code session it was called from.

Hooks load only when a session starts, so a plugin that was installed, enabled or updated inside a running session has no hooks there,
and the agent in it still finds the command and works as if the guards, the gate reminder and the task clock were on.

The Bash `PreToolUse` hook (`tool_timing.py pre`) calls `mark` before every command, the command's own included.
`mark` writes `<state folder>/sessions/<session id>` when it is missing or differs: `{"root": the plugin root, "version": its version}`, and prunes the markers older than MARKER_DAYS days when it writes.
The Bash tool gives every command `CLAUDE_CODE_SESSION_ID`, which is the `session_id` of the hook input, so the command can look its own session up.

The command calls `warning` before it dispatches, and `metrics selftest` prints `selftest_line`.
Neither raises, and nothing here changes an exit code or what a command prints on stdout; no session id (a person in a terminal) or no state folder (not a git repo) means no check.
"""
import json
import os
import re
from pathlib import Path

import local_state

MARKER_DAYS = 30  # a marker is pruned when it is older than this and another marker is written
NO_MARKER = ("agent-steddy: this plugin's hooks did not run in this session, so the guards, the gate reminder and the task clock are off. "
             "The plugin was installed, enabled or updated after the session started: start a new Claude Code session in this project.")
OTHER_ROOT = ("agent-steddy: this is version {mine} at {here}, but this session's hooks run version {theirs} at {there}; "
              "call `agent-steddy` by name, not through a cache path.")
NOT_CHECKED = "hooks live in this session: not checked (needs a Claude Code session, and a git repo for the project)"
LIVE = "hooks live in this session: yes, version {theirs}"
NOT_LIVE = "hooks live in this session: no, the plugin was installed, enabled or updated after the session started; start a new Claude Code session in this project"
OTHER_COPY = ("hooks live in this session: yes, version {theirs}, but this command is version {mine} at {here}, not the copy at {there} that the hooks run; "
              "call `agent-steddy` by name, not through a cache path")
UNKNOWN = "unknown"


def own_root():
    """The plugin root of this code, symlinks resolved."""
    return Path(__file__).resolve().parent.parent


def plugin_version(root):
    """The `version` of `<root>/.claude-plugin/plugin.json`, `unknown` when it cannot be read."""
    try:
        version = json.loads((Path(root) / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))["version"]
    except (OSError, ValueError, KeyError, TypeError):
        return UNKNOWN
    return version if isinstance(version, str) and version else UNKNOWN


def marker_file(state, session_id):
    """The marker file of a session, None without a state folder or a session id; the name is the id, with anything but letters, digits, `_` and `-` turned into `_`."""
    name = re.sub(r"[^A-Za-z0-9_-]", "_", session_id) if isinstance(session_id, str) else ""
    return Path(state) / local_state.SESSIONS / name if state and name else None


def mark(state, session_id, root, now):
    """Write the marker of a session whose hooks run, when it is missing or differs; never raises. `root` is the plugin root, default this code's own."""
    path = marker_file(state, session_id)
    if path is None:
        return
    root = os.path.realpath(root or own_root())
    text = json.dumps({"root": root, "version": plugin_version(root)})
    try:
        try:
            if path.read_text(encoding="utf-8") == text:
                return
        except (OSError, ValueError):
            pass
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        for old in path.parent.iterdir():
            if old != path and now - old.stat().st_mtime > MARKER_DAYS * 86400:
                old.unlink(missing_ok=True)
    except (OSError, ValueError):
        pass


def status(project):
    """What the marker says: None when it cannot be told, (False, None) when the session has no marker, else (True, the marker as a dict)."""
    try:
        path = marker_file(local_state.state_dir(project), os.environ.get("CLAUDE_CODE_SESSION_ID"))
        if path is None:
            return None
        try:
            marker = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return False, None
        return (True, marker) if isinstance(marker, dict) and isinstance(marker.get("root"), str) else None
    except Exception:  # the check is a courtesy: whatever goes wrong in it, the command runs as if it were not there
        return None


def other_root(marker):
    """The marker's side of a mismatch as format arguments for OTHER_ROOT and OTHER_COPY, None when the hooks run this very code."""
    mine = own_root()
    if os.path.realpath(marker["root"]) == str(mine):
        return None
    return {"mine": plugin_version(mine), "here": mine, "theirs": marker.get("version") or UNKNOWN, "there": marker["root"]}


def warning(project):
    """The line the command prints on stderr before it runs, None when the session's hooks run this very plugin or it cannot be told."""
    found = status(project)
    if found is None:
        return None
    if not found[0]:
        return NO_MARKER
    other = other_root(found[1])
    return OTHER_ROOT.format(**other) if other else None


def selftest_line(project):
    """The one line `metrics selftest` prints about the hooks: yes with their version, no, or not checked; a yes names this command's own version and path when it is not the hooks' copy."""
    found = status(project)
    if found is None:
        return NOT_CHECKED
    if not found[0]:
        return NOT_LIVE
    other = other_root(found[1])
    return OTHER_COPY.format(**other) if other else LIVE.format(theirs=found[1].get("version") or UNKNOWN)
