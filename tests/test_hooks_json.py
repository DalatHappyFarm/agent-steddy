import json
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent

# (event, matcher or None) -> the script that runs, and tool names the matcher must and must not catch
WIRING = [
    ("PreToolUse", "Bash", "guard_bash.py", ["Bash"], ["Write", "Agent"]),
    ("PreToolUse", "Agent|Task", "guard_agent.py", ["Agent", "Task"], ["Bash", "TaskStop", "Write"]),
]


class HooksJson(unittest.TestCase):
    def entries(self):
        hooks = json.loads((ROOT / "hooks" / "hooks.json").read_text())["hooks"]
        for event, groups in hooks.items():
            for group in groups:
                for hook in group["hooks"]:
                    yield event, group.get("matcher"), hook

    def test_each_script_runs_on_its_event_and_matcher(self):
        found = {(event, matcher): hook for event, matcher, hook in self.entries()}
        self.assertEqual(sorted(found, key=str), sorted([(event, matcher) for event, matcher, *_ in WIRING], key=str))
        for event, matcher, script, catches, ignores in WIRING:
            hook = found[(event, matcher)]
            self.assertEqual(hook["type"], "command")
            self.assertEqual(hook["command"], f'python3 -I "${{CLAUDE_PLUGIN_ROOT}}/scripts/{script}"')
            self.assertTrue((ROOT / "scripts" / script).is_file(), script)
            for name in catches:
                self.assertRegex(name, f"^(?:{matcher})$")
            for name in ignores:
                self.assertNotRegex(name, f"^(?:{matcher})$")

    def test_every_hook_has_a_short_timeout(self):
        for event, matcher, hook in self.entries():
            self.assertLessEqual(hook["timeout"], 5, (event, matcher))


if __name__ == "__main__":
    unittest.main()
