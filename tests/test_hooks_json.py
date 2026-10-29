import json
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent

# (event, matcher or None, script, argument or "") -> tool names the matcher must and must not catch (a hook with no matcher runs for every call)
WIRING = [
    ("PreToolUse", "Bash", "guard_bash.py", "", ["Bash"], ["Write", "Agent"]),
    ("PreToolUse", "Agent|Task", "guard_agent.py", "", ["Agent", "Task"], ["Bash", "TaskStop", "Write"]),
    ("PreToolUse", "Write|Edit|MultiEdit|NotebookEdit", "guard_write.py", "", ["Write", "Edit", "MultiEdit", "NotebookEdit"], ["Read", "Bash", "WriteFile"]),
    ("PostToolUse", "Bash", "secret_output_scan.py", "", ["Bash"], ["Write", "Read"]),
    ("PostToolUseFailure", "Bash", "secret_output_scan.py", "", ["Bash"], ["Write", "Read"]),
    ("SubagentStop", None, "stop_check.py", "", [], []),
]


class HooksJson(unittest.TestCase):
    def entries(self):
        hooks = json.loads((ROOT / "hooks" / "hooks.json").read_text())["hooks"]
        for event, groups in hooks.items():
            for group in groups:
                for hook in group["hooks"]:
                    yield event, group.get("matcher"), hook

    def test_each_script_runs_on_its_event_and_matcher(self):
        found = {(event, matcher, hook["command"]): hook for event, matcher, hook in self.entries()}
        command = lambda script, arg: f'python3 -I "${{CLAUDE_PLUGIN_ROOT}}/scripts/{script}"' + (f" {arg}" if arg else "")
        self.assertEqual(sorted(found, key=str), sorted([(event, matcher, command(script, arg)) for event, matcher, script, arg, *_ in WIRING], key=str))
        for event, matcher, script, arg, catches, ignores in WIRING:
            hook = found[(event, matcher, command(script, arg))]
            self.assertEqual(hook["type"], "command")
            self.assertTrue((ROOT / "scripts" / script).is_file(), script)
            self.assertTrue(matcher or not (catches or ignores), "a hook with no matcher has no names to check")
            for name in catches:
                self.assertRegex(name, f"^(?:{matcher})$")
            for name in ignores:
                self.assertNotRegex(name, f"^(?:{matcher})$")

    def test_every_hook_has_a_short_timeout(self):
        for event, matcher, hook in self.entries():
            self.assertLessEqual(hook["timeout"], 5, (event, matcher))


if __name__ == "__main__":
    unittest.main()
