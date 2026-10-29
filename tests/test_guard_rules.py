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
    "git-checkout-all": {
        "hit": ["git checkout .", "git checkout -- .", "git checkout HEAD -- .", "git checkout -f .", "git -C app checkout .", "cd app && git checkout -- .",
                "env A=1 git checkout .", "bash -c 'git checkout .'"],
        "miss": ["git checkout feat/x", "git checkout -b feat/y", "git checkout -- apps/web/a.ts", "git checkout ./a.ts", "git checkout HEAD~1 -- a.ts",
                 "git checkout main", "echo 'git checkout .'", "git status ."],
    },
    "git-restore-all": {
        "hit": ["git restore .", "git restore --staged .", "git restore -- .", "git restore --source HEAD~1 .", "git -C app restore .", "ls && git restore .",
                "nohup git restore . &"],
        "miss": ["git restore apps/web/a.ts", "git restore --staged a.md", "git restore ./a.md", "git restore --source HEAD~1 a.ts", "echo 'git restore .'",
                 "git status ."],
    },
    "git-clean-force": {
        "hit": ["git clean -f", "git clean -fd", "git clean -fdx", "git clean -d -f", "git clean -ffdx", "git clean --force", "git clean -d --force",
                "git -C app clean -fd", "cd app && git clean -f", "sudo git clean -f", "bash -c 'git clean -fd'"],
        "miss": ["git clean -n", "git clean -nd", "git clean --dry-run", "git clean", "git clean -i", "git clean -d", "echo 'git clean -f'", "git status -f"],
    },
    "git-add-all": {
        "hit": ["git add -A", "git add --all", "git add .", "git add -- .", "git add -Av", "git add -vA", "git -C apps add -A", "cd apps && git add -A && echo done",
                "git add . && git commit -m x", "echo hi\ngit add -A", "FOO=1 git add .", "bash -c 'git add -A'"],
        "miss": ["git add apps/web/a.ts docs/b.md", "git add -- docs/x.md", "git add ./a.md", "git add -n a.md", "git add -p a.ts", "git add -u a.md",
                 "git commit -m 'git add -A is banned' -- a.md", "echo 'git add .'", "cat <<EOF\ngit add -A\nEOF",
                 "git commit -m \"$(cat <<'EOF'\nfeat: x\n\ngit add -A and git add . mentioned\nEOF\n)\" -- a.md"],
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
