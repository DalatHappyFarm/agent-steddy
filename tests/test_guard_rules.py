"""Table-driven tests of the built-in Bash rules.

Every rule id has commands it must block ("hit") and lookalikes it must allow ("miss").
"""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import guard_bash  # noqa: E402

RULE_CASES = {
    "git-stash": {
        "hit": ["git stash", "git stash pop", "git stash list", "git -C apps/web stash", "git -c a.b=c --git-dir x stash", "cd app && git stash",
                "ls; git stash", "/usr/bin/git stash", "echo x|git stash", "echo $(git stash)", 'bash -c "git stash"'],
        "miss": ["git status", "git commit -m 'stash later' -- a.md", "echo 'git stash'", "rg stash", "git log --grep stash", "git stash-free-tool",
                 "git show HEAD:stash", "git diff stash"],
    },
    "git-reset-hard": {
        "hit": ["git reset --hard", "git reset --hard HEAD~1", "git reset HEAD~1 --hard", "git -C app reset --hard origin/main", "cd app && git reset --hard",
                "sudo git reset --hard", "bash -c 'git reset --hard'"],
        "miss": ["git reset HEAD apps/web/a.ts", "git reset --soft HEAD~1", "git reset --mixed", "git reset", "git status --hard", "echo 'git reset --hard'",
                 "git log --oneline", "git revert HEAD"],
    },
}


def rule_ids():
    return [rule_id for rule_id, _, _ in guard_bash.DENY_RULES]


def verdict(command, config=None, agent_type=None):
    """The decision for a command, in process: (kind, reason), ("allow", "") when nothing blocks it."""
    return guard_bash.judge(command, agent_type, config or {}) or ("allow", "")


class BuiltInRules(unittest.TestCase):
    def test_every_rule_has_cases_and_every_case_has_a_rule(self):
        self.assertEqual(sorted(rule_ids()), sorted(RULE_CASES))
        self.assertEqual(len(rule_ids()), len(set(rule_ids())))

    def test_each_rule_denies_its_commands_and_names_itself_in_the_reason(self):
        for rule_id, cases in RULE_CASES.items():
            for command in cases["hit"]:
                kind, reason = verdict(command)
                self.assertEqual(kind, "deny", command)
                self.assertTrue(reason.startswith(f"[{rule_id}] "), f"{command}: {reason}")

    def test_each_rule_allows_its_lookalikes(self):
        for rule_id, cases in RULE_CASES.items():
            for command in cases["miss"]:
                self.assertEqual(verdict(command)[0], "allow", f"{rule_id}: {command}")

    def test_disabling_a_rule_allows_its_commands_and_keeps_the_other_rules(self):
        for rule_id, cases in RULE_CASES.items():
            off = {"guards": {"disable": [rule_id]}}
            for command in cases["hit"]:
                self.assertEqual(verdict(command, off)[0], "allow", f"{rule_id}: {command}")
            for other_id, other in RULE_CASES.items():
                if other_id != rule_id:
                    self.assertEqual(verdict(other["hit"][0], off)[0], "deny", f"{rule_id} off, {other_id}")


if __name__ == "__main__":
    unittest.main()
