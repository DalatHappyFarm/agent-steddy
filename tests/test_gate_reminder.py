import contextlib
import datetime as dt
import json
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import gate_reminder  # noqa: E402
import local_state  # noqa: E402
import project_config  # noqa: E402
from hook_runner import git, make_repo, run_hook, write_config  # noqa: E402

NOW = dt.datetime(2026, 10, 29, 17, 40, 2)
STAMP = "2026-10-29T17:40:02"


@contextlib.contextmanager
def repo():
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp).resolve()
        make_repo(root)
        yield root


def pending_file(root):
    return local_state.state_dir(root) / local_state.PENDING


def pending(root):
    return json.loads(pending_file(root).read_text())


def put_pending(root, task, start):
    pending_file(root).parent.mkdir(parents=True, exist_ok=True)
    pending_file(root).write_text(json.dumps({"task": task, "start": start}))


def ago(hours):
    return (NOW - dt.timedelta(hours=hours)).isoformat(timespec="seconds")


class Reminder(unittest.TestCase):
    def test_the_default_is_the_seven_gates_in_the_prompt_context(self):
        output = gate_reminder.reminder(project_config.load("/nonexistent"))
        self.assertEqual(output, {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": project_config.DEFAULT_REMINDER}})
        text = project_config.DEFAULT_REMINDER
        for gate in ["1 Intake", "2 Recall", "3 Shape", "4 Act", "5 Prove", "6 Record", "7 Deliver"]:
            self.assertIn(gate, text)

    def test_the_project_text_replaces_the_default(self):
        self.assertEqual(gate_reminder.reminder({"reminder": {"text": "Read AGENTS.md first."}})["hookSpecificOutput"]["additionalContext"], "Read AGENTS.md first.")

    def test_the_reminder_can_be_turned_off_or_emptied(self):
        for config in [{"reminder": {"enabled": False}}, {"reminder": {"text": ""}}, {"reminder": {"text": "  \n"}}]:
            self.assertIsNone(gate_reminder.reminder(config), config)

    def test_wrongly_typed_settings_are_read_as_the_defaults(self):
        default = project_config.DEFAULT_REMINDER
        for config in [{"reminder": "off"}, {"reminder": {"enabled": "no"}}, {"reminder": {"enabled": 0}}, {"reminder": {"text": 5}}, {"reminder": {"text": None}}]:
            self.assertEqual(gate_reminder.reminder(config)["hookSpecificOutput"]["additionalContext"], default, config)


LINE = "Learning loop: {n} rule(s) seen twice and not promoted ({keys}); run agent-steddy lessons check."


def lessons_file(root, *keys, path="docs/agents/lessons.md"):
    """A lessons file with two entries for each key."""
    text = "# Lessons\n\n"
    for day, key in [(day, key) for key in keys for day in (1, 2)]:
        text += f"## 2026-10-0{day} - task {key} {day} - roles: web\n- Worked: w\n- Exposed: e\n- Rule [{key}]: r\n\n"
    target = pathlib.Path(root) / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)


class LearningLoopLine(unittest.TestCase):
    def test_a_due_rule_adds_one_line_after_the_reminder_text(self):
        cases = [(["a"], "a"), (["a", "b", "c"], "a, b, c"), (["a", "b", "c", "d"], "a, b, c, ...")]
        for keys, shown in cases:
            with repo() as root:
                lessons_file(root, *keys)
                text = gate_reminder.reminder(project_config.load(root), root)["hookSpecificOutput"]["additionalContext"]
                self.assertEqual(text, project_config.DEFAULT_REMINDER + "\n" + LINE.format(n=len(keys), keys=shown), keys)

    def test_nothing_is_added_when_no_rule_is_due_or_there_is_no_lessons_file(self):
        with repo() as root:
            self.assertEqual(gate_reminder.reminder(project_config.load(root), root)["hookSpecificOutput"]["additionalContext"], project_config.DEFAULT_REMINDER)
            (root / "docs/agents").mkdir(parents=True)
            (root / "docs/agents/lessons.md").write_text("# Lessons\n\n## 2026-10-01 - t - roles: web\n- Rule [a]: r\n\n## 2026-10-02 - u - roles: web\n- Rule: none\n")
            self.assertEqual(gate_reminder.reminder(project_config.load(root), root)["hookSpecificOutput"]["additionalContext"], project_config.DEFAULT_REMINDER)
            lessons_file(root, "a")
            (root / "docs/agents/lessons.md").write_text((root / "docs/agents/lessons.md").read_text().replace("Rule [a]: r\n\n## 2026-10-02", "Rule [a]: r [promoted -> docs/agents/roles/web.md]\n\n## 2026-10-02"))
            self.assertNotIn("Learning loop", gate_reminder.reminder(project_config.load(root), root)["hookSpecificOutput"]["additionalContext"])

    def test_the_line_needs_the_reminder_to_be_on(self):
        with repo() as root:
            lessons_file(root, "a")
            for config in [{"reminder": {"enabled": False}}, {"reminder": {"text": ""}}]:
                self.assertIsNone(gate_reminder.reminder({**project_config.DEFAULTS, **config}, root), config)

    def test_the_project_text_and_the_lessons_path_come_from_the_config(self):
        with repo() as root:
            lessons_file(root, "a", path="notes/l.md")
            config = {"reminder": {"text": "Read AGENTS.md first."}, "records": {"lessons": "notes/l.md"}}
            write_config(root, config)
            out = run_hook("gate_reminder.py", {"hook_event_name": "UserPromptSubmit"}, root)
            self.assertEqual(out["hookSpecificOutput"]["additionalContext"], "Read AGENTS.md first.\n" + LINE.format(n=1, keys="a"))

    def test_the_hook_prints_the_line_and_still_prints_the_reminder_when_the_lessons_file_is_malformed(self):
        with repo() as root:
            lessons_file(root, "a", "b")
            out = run_hook("gate_reminder.py", {"hook_event_name": "UserPromptSubmit"}, root)
            self.assertEqual(out["hookSpecificOutput"]["additionalContext"], project_config.DEFAULT_REMINDER + "\n" + LINE.format(n=2, keys="a, b"))
            path = root / "docs/agents/lessons.md"
            for content in [b"\xff\xfe\x00 not utf-8", b"## \n- Rule [: \n```", b"", b"\x00" * 50]:
                path.write_bytes(content)
                out = run_hook("gate_reminder.py", {"hook_event_name": "UserPromptSubmit"}, root)
                self.assertEqual(out["hookSpecificOutput"]["additionalContext"], project_config.DEFAULT_REMINDER, content)
            path.unlink()
            path.mkdir()  # a folder where the file should be
            self.assertEqual(run_hook("gate_reminder.py", {"hook_event_name": "UserPromptSubmit"}, root)["hookSpecificOutput"]["additionalContext"], project_config.DEFAULT_REMINDER)

    def test_a_failure_while_reading_the_lessons_is_ignored(self):
        with repo() as root:
            with mock.patch.object(gate_reminder.lessons, "nudge", side_effect=RuntimeError("boom")):
                self.assertEqual(gate_reminder.reminder(project_config.load(root), root)["hookSpecificOutput"]["additionalContext"], project_config.DEFAULT_REMINDER)

    def test_the_line_does_not_start_or_change_the_task_clock(self):
        with repo() as root:
            lessons_file(root, "a")
            run_hook("gate_reminder.py", {"hook_event_name": "UserPromptSubmit"}, root)
            self.assertTrue(pending(root)["task"].startswith("auto 20"))


class Clock(unittest.TestCase):
    def test_a_prompt_with_no_pending_task_starts_an_auto_task_at_the_prompt_time(self):
        with repo() as root:
            self.assertTrue(gate_reminder.start_clock(root, NOW))
            self.assertEqual(pending(root), {"task": f"auto {STAMP}", "start": STAMP})

    def test_a_pending_task_is_never_replaced(self):
        with repo() as root:
            put_pending(root, "real task", ago(30))  # a named task, however old
            self.assertFalse(gate_reminder.start_clock(root, NOW))
            self.assertEqual(pending(root), {"task": "real task", "start": ago(30)})

    def test_a_recent_auto_start_is_kept_so_the_first_prompt_stays_the_prompt_time(self):
        with repo() as root:
            put_pending(root, f"auto {ago(11)}", ago(11))
            self.assertFalse(gate_reminder.start_clock(root, NOW))
            self.assertEqual(pending(root)["start"], ago(11))

    def test_an_auto_start_older_than_twelve_hours_is_replaced(self):
        with repo() as root:
            put_pending(root, f"auto {ago(13)}", ago(13))
            self.assertTrue(gate_reminder.start_clock(root, NOW))
            self.assertEqual(pending(root), {"task": f"auto {STAMP}", "start": STAMP})

    def test_an_unreadable_clock_is_replaced(self):
        for text in ["{not json", "[1]", ""]:
            with repo() as root:
                pending_file(root).parent.mkdir(parents=True)
                pending_file(root).write_text(text)
                self.assertTrue(gate_reminder.start_clock(root, NOW), text)
                self.assertEqual(pending(root)["start"], STAMP)

    def test_every_worktree_writes_to_the_clock_of_the_main_checkout(self):
        with repo() as root, tempfile.TemporaryDirectory() as other:
            worktree = pathlib.Path(other).resolve() / "wt"
            git(root, "worktree", "add", "-q", str(worktree), "-b", "side")
            gate_reminder.start_clock(worktree, NOW)
            self.assertEqual(pending(root)["start"], STAMP)
            self.assertFalse(gate_reminder.start_clock(root, NOW))  # the main checkout sees the same clock

    def test_with_no_state_folder_there_is_no_clock(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"CLAUDE_PLUGIN_DATA": ""}):
            self.assertFalse(gate_reminder.start_clock(tmp, NOW))
            self.assertEqual(os.listdir(tmp), [])


class Hook(unittest.TestCase):
    """The script as Claude Code runs it."""

    PROMPT = {"hook_event_name": "UserPromptSubmit", "prompt": "fix the build"}

    def test_it_prints_the_reminder_and_starts_the_clock(self):
        with repo() as root:
            out = run_hook("gate_reminder.py", self.PROMPT, root)
            self.assertEqual(out["hookSpecificOutput"], {"hookEventName": "UserPromptSubmit", "additionalContext": project_config.DEFAULT_REMINDER})
            self.assertTrue(pending(root)["task"].startswith("auto 20"))
            first = pending(root)
            run_hook("gate_reminder.py", self.PROMPT, root)  # the second prompt of the same task keeps the first start
            self.assertEqual(pending(root), first)

    def test_the_project_config_decides_the_text_and_whether_there_is_one(self):
        with repo() as root:
            write_config(root, {"reminder": {"text": "Gates: see docs/gates.md"}})
            self.assertEqual(run_hook("gate_reminder.py", self.PROMPT, root)["hookSpecificOutput"]["additionalContext"], "Gates: see docs/gates.md")
            write_config(root, {"reminder": {"enabled": False}})
            self.assertIsNone(run_hook("gate_reminder.py", self.PROMPT, root))

    def test_the_clock_starts_even_when_the_reminder_is_off(self):
        with repo() as root:
            write_config(root, {"reminder": {"enabled": False}})
            self.assertIsNone(run_hook("gate_reminder.py", self.PROMPT, root))
            self.assertTrue(pending(root)["task"].startswith("auto 20"))

    def test_a_project_outside_a_repo_gets_the_reminder_and_no_clock(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = run_hook("gate_reminder.py", self.PROMPT, tmp, env={"CLAUDE_PLUGIN_DATA": ""})
            self.assertIn("additionalContext", out["hookSpecificOutput"])
            self.assertEqual(os.listdir(tmp), [])

    def test_it_fails_open_with_a_broken_config_or_no_input(self):
        with repo() as root:
            for config in [["not", "an", "object"], {"reminder": 3}]:
                write_config(root, config)
                self.assertEqual(run_hook("gate_reminder.py", self.PROMPT, root)["hookSpecificOutput"]["additionalContext"], project_config.DEFAULT_REMINDER, config)
            for raw in ["", "not json"]:
                self.assertIn("hookSpecificOutput", run_hook("gate_reminder.py", None, root, raw=raw))  # the input is not needed


if __name__ == "__main__":
    unittest.main()
