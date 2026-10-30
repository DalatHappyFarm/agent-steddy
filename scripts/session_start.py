"""Hook for SessionStart: tell the agent that the checked out branch has a resume note.

Runs for every source (startup, resume, clear, compact and fork); the compact source matters most, because the context was just summarized.
Prints one JSON object whose `additionalContext` is `Resume note for <branch> from <date>: run agent-steddy resume before you start.`, and nothing when the branch has no note.
It reads the note folder first and calls git only when the folder holds a note, so a project that never pauses pays almost nothing.
The hook never blocks and exits 0 whatever happens; an error, a broken config or a project that is not a git repo prints nothing.
"""
import contextlib
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python3 -I leaves the script directory off the path
import local_state  # noqa: E402
import project_config  # noqa: E402
import resume  # noqa: E402


def main():
    project = local_state.project_dir()
    with contextlib.redirect_stderr(io.StringIO()):  # a broken config is reported by the other hooks, not here
        line = resume.pointer(project, project_config.load(project))
    if line:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": line}}))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
