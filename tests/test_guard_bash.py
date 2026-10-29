import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "guard_bash.py"
sys.path.insert(0, str(ROOT / "scripts"))
import guard_bash  # noqa: E402

DENY_PUSH = {"commands": {"deny": [{"match": "supabase config push", "reason": "Ask the owner to run config push."}]}}


def decide(command, config=None):
    """Run the hook the way Claude Code does, in a temp project dir holding `config` when given; return its JSON output or None."""
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    with tempfile.TemporaryDirectory() as tmp:
        if config is not None:
            (pathlib.Path(tmp) / ".claude").mkdir()
            (pathlib.Path(tmp) / ".claude" / "agent-steddy.json").write_text(json.dumps(config))
        env = {**os.environ, "CLAUDE_PROJECT_DIR": tmp}
        out = subprocess.run([sys.executable, "-I", str(SCRIPT)], input=payload, capture_output=True, text=True, env=env, check=True).stdout
    return json.loads(out)["hookSpecificOutput"] if out.strip() else None


def run(command, config=None):
    """The hook's decision: 'deny' or 'allow'."""
    decision = decide(command, config)
    return decision["permissionDecision"] if decision else "allow"


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

    def test_matches_program_basename_then_positional_words(self):
        pattern = "supabase config push"
        for command in ["supabase config push", "supabase --debug config push --yes", "/usr/local/bin/supabase config push",
                        "supabase config push extra"]:
            self.assertTrue(guard_bash.matches(command.split(), pattern), command)
        for command in ["supabase config list", "supabase push", "supabase", "supabase config", "echo supabase config push",
                        "supabase-cli config push", "config push"]:
            self.assertFalse(guard_bash.matches(command.split(), pattern), command)
        self.assertFalse(guard_bash.matches(["ls"], ""))
        self.assertFalse(guard_bash.matches([], "ls"))

    def test_denies_a_command_listed_in_the_project_config_with_its_reason(self):
        for command in ["supabase config push", "supabase --debug config push --yes", "cd app && supabase config push",
                        "make test; /usr/bin/supabase config push | tee log"]:
            decision = decide(command, DENY_PUSH)
            self.assertEqual(decision["permissionDecision"], "deny", command)
            self.assertEqual(decision["permissionDecisionReason"], "Ask the owner to run config push.")

    def test_allows_other_commands_with_a_config(self):
        for command in ["supabase config list", "supabase db push", "echo 'supabase config push'", "git status"]:
            self.assertEqual(run(command, DENY_PUSH), "allow", command)

    def test_allows_the_listed_command_without_a_config_file_or_with_a_broken_one(self):
        self.assertEqual(run("supabase config push"), "allow")
        self.assertEqual(run("supabase config push", ["not", "an", "object"]), "allow")

    def test_built_in_rules_hold_without_the_config_and_with_a_broken_rule(self):
        self.assertEqual(run("git stash", DENY_PUSH), "deny")
        self.assertEqual(run("git stash", {"commands": {"deny": [42]}}), "deny")

    def test_a_rule_without_a_reason_still_denies(self):
        decision = decide("make deploy", {"commands": {"deny": [{"match": "make deploy"}]}})
        self.assertEqual(decision["permissionDecision"], "deny")
        self.assertIn("make deploy", decision["permissionDecisionReason"])


if __name__ == "__main__":
    unittest.main()
