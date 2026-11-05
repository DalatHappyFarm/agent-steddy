"""Hook for UserPromptSubmit: put the gates in front of the agent on every prompt, and start the task clock.

Prints one JSON object whose `additionalContext` is `reminder.text` of the project config, and nothing when `reminder.enabled` is false.
When a rule of the lessons file is due for promotion (seen twice and not promoted) or broke after its promotion, one more line names the keys and says to run `agent-steddy lessons check`; a problem reading the lessons file leaves that line out.
When `recall.prompt` is on, the rules that match the prompt follow (lessons.recall: at most three, each sharing two terms with it), whether or not the reminder is on.
It also starts the task clock that `agent-steddy metrics` reads: when no task is pending, the time of this prompt becomes the start of an auto task named `auto <time>`.
A pending task is never replaced, except an auto task older than 12 hours, which is a prompt that never reached `metrics log`.
The clock starts whether or not the reminder is on.
A turn that only carries a background task's notification (its prompt starts with `<task-notification>`) also fires this hook; it gets the reminder but starts no clock, since no one asked for anything.
The hook never blocks and exits 0 whatever happens, and a problem with the clock does not hide the reminder.
"""
import datetime as dt
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python3 -I leaves the script directory off the path
import evals  # noqa: E402
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
    """The line that says rules are due for promotion or broke after it, empty when none is or when the lessons file cannot be read."""
    try:
        cased = evals.case_keys(Path(project) / project_config.get(config, "records", "evals"))
        return lessons.nudge(Path(project) / project_config.get(config, "records", "lessons"), cased)
    except Exception:
        return ""


def recall_lines(project, config, prompt):
    """The lessons that match the prompt, [] when recall is off, there is no prompt, or the lessons file cannot be read."""
    if not prompt or not project_config.get(config, "recall", "prompt"):
        return []
    try:
        return lessons.recall(Path(project) / project_config.get(config, "records", "lessons"), prompt)
    except Exception:
        return []


def reminder(config, project=None, prompt=None):
    """The hook output, None when it has nothing to add: the reminder text when it is on (with the learning loop line when a rule is due), then the lessons that match the prompt."""
    text = project_config.get(config, "reminder", "text")
    parts = []
    if project_config.get(config, "reminder", "enabled") and text.strip():
        line = learning_loop_line(project, config) if project is not None else ""
        parts.append(f"{text}\n{line}" if line else text)
    if project is not None:
        parts += recall_lines(project, config, prompt)
    if not parts:
        return None
    return {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": "\n".join(parts)}}


def prompt_of(raw):
    """The prompt of the hook input, None when there is none."""
    try:
        prompt = json.loads(raw).get("prompt")
    except Exception:
        return None
    return prompt if isinstance(prompt, str) else None


def is_notification(raw):
    """True when the hook input is a turn that Claude Code opened for a background task's notification, not a prompt someone typed."""
    prompt = prompt_of(raw)
    return prompt is not None and prompt.lstrip().startswith("<task-notification>")


def main():
    project = local_state.project_dir()
    prompt = None
    try:
        raw = sys.stdin.read()
        if not is_notification(raw):
            prompt = prompt_of(raw)
            start_clock(project, dt.datetime.now())
    except Exception:
        pass
    output = reminder(project_config.load(project), project, prompt)
    if output:
        print(json.dumps(output))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
