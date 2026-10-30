"""Hook for UserPromptSubmit: put the gates in front of the agent on every prompt, and start the task clock.

Prints one JSON object whose `additionalContext` is `reminder.text` of the project config, and nothing when `reminder.enabled` is false.
When a rule of the lessons file is due for promotion (seen twice and not promoted), one more line names the keys and says to run `agent-steddy lessons check`; a problem reading the lessons file leaves that line out.
It also starts the task clock that `agent-steddy metrics` reads: when no task is pending, the time of this prompt becomes the start of an auto task named `auto <time>`.
A pending task is never replaced, except an auto task older than 12 hours, which is a prompt that never reached `metrics log`.
The clock starts whether or not the reminder is on.
The hook never blocks and exits 0 whatever happens, and a problem with the clock does not hide the reminder.
"""
import datetime as dt
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python3 -I leaves the script directory off the path
import lessons  # noqa: E402
import local_state  # noqa: E402
import project_config  # noqa: E402


def start_clock(project, now):
    """Write the pending task when there is none (or only a stale auto one). Returns True when it wrote."""
    state = local_state.state_dir(project)
    if state is None:
        return False
    pending = local_state.read_pending(state)
    is_auto = str(pending.get("task", "")).startswith("auto ")
    if pending and not (is_auto and local_state.auto_start(pending, now) is None):
        return False  # a task is running, or an auto start still counts as the prompt time
    stamp = now.isoformat(timespec="seconds")
    state.mkdir(parents=True, exist_ok=True)
    (state / local_state.PENDING).write_text(json.dumps({"task": f"auto {stamp}", "start": stamp}), encoding="utf-8")
    return True


def learning_loop_line(project, config):
    """The line that says rules are due for promotion, empty when none is or when the lessons file cannot be read."""
    try:
        return lessons.nudge(Path(project) / project_config.get(config, "records", "lessons"))
    except Exception:
        return ""


def reminder(config, project=None):
    """The hook output with the reminder, None when the reminder is off or its text is empty. With a `project`, a due rule adds the learning loop line."""
    text = project_config.get(config, "reminder", "text")
    if not project_config.get(config, "reminder", "enabled") or not text.strip():
        return None
    line = learning_loop_line(project, config) if project is not None else ""
    text = f"{text}\n{line}" if line else text
    return {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": text}}


def main():
    project = local_state.project_dir()
    try:
        start_clock(project, dt.datetime.now())
    except Exception:
        pass
    output = reminder(project_config.load(project), project)
    if output:
        print(json.dumps(output))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
