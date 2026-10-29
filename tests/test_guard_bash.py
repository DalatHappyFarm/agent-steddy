import json
import pathlib
import subprocess
import sys
import unittest

SCRIPT = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "guard_bash.py"


def run(command):
    """Run the hook the way Claude Code does and return its decision: 'deny' or 'allow'."""
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    out = subprocess.run([sys.executable, "-I", str(SCRIPT)], input=payload, capture_output=True, text=True, check=True).stdout
    return json.loads(out)["hookSpecificOutput"]["permissionDecision"] if out.strip() else "allow"


class GuardBash(unittest.TestCase):
    def test_denies_git_stash_in_any_position(self):
        for command in ["git stash", "git stash pop", "git -C ../other stash list", "cd app && git stash",
                        "ls; git stash", "/usr/bin/git stash", "echo x|git stash"]:
            self.assertEqual(run(command), "deny", command)

    def test_allows_everything_else(self):
        for command in ["git status", "git commit -m 'stash later' -- a.md", "echo 'git stash'", "rg stash", "git log --grep stash"]:
            self.assertEqual(run(command), "allow", command)

    def test_broken_input_allows(self):
        out = subprocess.run([sys.executable, "-I", str(SCRIPT)], input="not json", capture_output=True, text=True)
        self.assertEqual((out.returncode, out.stdout), (0, ""))


if __name__ == "__main__":
    unittest.main()
