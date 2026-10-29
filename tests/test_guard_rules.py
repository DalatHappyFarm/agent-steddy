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
    "git-commit-all": {
        "hit": ["git commit -a -m x", "git commit -am x", "git commit --all -m x", "git commit -m x -a", "git commit -m x --all", "git commit -sam x",
                "git commit -vam x", "git commit --amend -a", "git commit -a", "git -C app commit -am x", "cd app && git commit -am x", "sudo git commit -a -m x",
                "bash -c 'git commit -am x'"],
        "miss": ["git commit -m 'fix: no git stash here'", "git commit -- apps/web/a.ts -m x", "git commit -m msg -- a b", "git commit --amend -m x",
                 "git commit -m -a", "git commit -ma", "git commit -m x -- -a", "git commit -F -", "git commit -m x a.md", "git commit --author='A <a@b.c>' -m x",
                 "git commit --amend --no-edit", "git commit -C HEAD", "git commit -c HEAD -m x", "git commit --message=-a", "echo 'git commit -a'", "git status -a"],
    },
    "git-branch-force-delete": {
        "hit": ["git branch -D x", "git branch -df x", "git branch -Df x", "git branch -fd x", "git branch --delete --force x", "git branch -d -f x",
                "git branch --force -d x", "git branch -D", "git -C a branch -D x", "echo hi && git branch -D x", "bash -c 'git branch -D x'"],
        "miss": ["git branch -d x", "git branch --delete x", "git branch", "git branch -a", "git branch -m a b", "git branch -f x HEAD", "git branch --force x HEAD",
                 "git switch -c x", "git branch feat/D", "echo 'git branch -D x'"],
    },
    "git-push-force": {
        "hit": ["git push --force", "git push -f", "git push -f origin feat/a", "git push --force-with-lease", "git push --force-with-lease=main",
                "git push --force-if-includes", "git push origin +feat/a", "git push origin +HEAD:main", "git push -fu origin x", "git -C x push -f",
                "cd pkg && git push --force", "sudo git push -f", "bash -c 'git push -f'"],
        "miss": ["git push", "git push origin main", "git push --dry-run", "git push -u origin feat/a", "git push --follow-tags", "git push origin feat/fix",
                 "git pull --force", "git fetch -f", "git push origin a+b", "echo 'git push -f'", "git status -f"],
    },
    "grep-recursive": {
        "hit": ["grep -r foo src", "grep -R foo src", "grep --recursive foo src", "grep -rn foo src", "grep -Rn foo src", "grep -rl foo .", "grep -nri foo src",
                "grep foo -r src", "cat f | grep -rn foo", "ls && grep -r foo f", "echo $(grep -rn x y)", "FOO=1 grep -rn x y", "egrep -r x y", "fgrep -r x y",
                "/usr/bin/grep -r x", "sudo grep -r x y", "bash -c 'grep -rn x .'", "ls\ngrep -r x ."],
        "miss": ["ls | grep x", "grep -n foo file.txt", "xcrun simctl list devices booted | grep -c Booted", "git grep -n x", "git grep foo", "git grep -n foo -- src",
                 "rg -n grep src", "rg grep", "echo grep", "echo 'grep -r x'", "grep -n -- -r file", "grep -E 'a|b' f", "grep --include='*.ts' x f", "grep -c x f",
                 "rg -r foo src"],
    },
    "sed-in-place": {
        "hit": ["sed -i 's/a/b/' f", "sed -i -e s/a/b/ f", "sed --in-place s/a/b/ f", "sed --in-place=.bak s/a/b/ f", "sed -n 1p f | sed -i 's/a/b/' g",
                "sed -Ei 's/a/b/' f", "sed -ni 's/a/b/p' f", "sed -E -i 's/a/b/' f", "sudo sed -i s/a/b/ f", "bash -c \"sed -i 's/a/b/' f\"", "FOO=1 sed -i x f",
                "cd app && sed -i s/a/b/ f", "/usr/bin/sed -i s/a/b/ f"],
        "miss": ["sed -i '' 's/a/b/' f", "sed -i \"\" s/a/b/ f", "sed -i.bak 's/a/b/' f", "sed -Ei '' s/a/b/ f", "sed -E -i.bak s/a/b/ f", "sed -n '1,5p' f",
                 "sed 's/a/b/' f", "sed -e 's/i/x/' f", "echo 'sed -i x f'", "sed -n -e 1p f", "sed -s p f", "sed -n 1p -- -i", "python3 -I edit.py"],
    },
}


def rule_ids():
    return [rule_id for rule_id, _, _ in guard_bash.DENY_RULES + guard_bash.ASK_RULES]


def kind_of(rule_id):
    """What a rule decides: 'ask' for an ask rule, 'deny' for the others."""
    return "ask" if rule_id in [ask_id for ask_id, _, _ in guard_bash.ASK_RULES] else "deny"


def verdict(command, config=None, agent_type=None):
    """The decision for a command, in process: (kind, reason), ("allow", "") when nothing blocks it."""
    return guard_bash.judge(command, agent_type, config or {}) or ("allow", "")


class BuiltInRules(unittest.TestCase):
    def test_every_rule_has_cases_and_every_case_has_a_rule(self):
        self.assertEqual(sorted(rule_ids()), sorted(RULE_CASES))
        self.assertEqual(len(rule_ids()), len(set(rule_ids())))

    def test_each_rule_decides_on_its_commands_and_names_itself_in_the_reason(self):
        for rule_id, cases in RULE_CASES.items():
            for command in cases["hit"]:
                kind, reason = verdict(command)
                self.assertEqual(kind, kind_of(rule_id), command)
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
                    self.assertEqual(verdict(other["hit"][0], off)[0], kind_of(other_id), f"{rule_id} off, {other_id}")


class AskRules(unittest.TestCase):
    def test_an_ask_rule_asks_in_the_main_session_and_in_a_subagent(self):
        for agent in [None, "", "acme-web"]:
            self.assertEqual(verdict("git push --force", agent_type=agent)[0], "ask", agent)
            self.assertEqual(verdict("git push", agent_type=agent)[0], "allow", agent)

    def test_a_deny_beats_a_built_in_ask(self):
        self.assertEqual(verdict("git push -f && git stash")[0], "deny")
        self.assertEqual(verdict("git stash; git push -f")[0], "deny")
        self.assertTrue(verdict("git push -f && git stash")[1].startswith("[git-stash] "))
        config = {"commands": {"deny": [{"match": "git push", "reason": "No pushes."}]}}
        self.assertEqual(verdict("git push -f", config), ("deny", "No pushes."))

    def test_a_built_in_ask_comes_before_a_config_ask(self):
        config = {"commands": {"alwaysAsk": ["git push"]}}
        kind, reason = verdict("git push -f", config)
        self.assertEqual(kind, "ask")
        self.assertTrue(reason.startswith("[git-push-force] "), reason)
        self.assertEqual(verdict("git push", config)[0], "ask")
        self.assertIn("alwaysAsk", verdict("git push", config)[1])


if __name__ == "__main__":
    unittest.main()
