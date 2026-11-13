"""Table-driven tests of the built-in Bash rules.

Every rule id has commands it must block ("hit") and lookalikes it must allow ("miss").
"""
import pathlib
import re
import shlex
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import guard_bash  # noqa: E402

RULE_CASES = {
    "git-stash": {
        "hit": ["git stash", "git stash pop", "git -C apps/web stash", "git -c a.b=c --git-dir x stash", "cd app && git stash",
                "ls; git stash", "/usr/bin/git stash", "echo x|git stash", "echo $(git stash)", 'bash -c "git stash"',
                "git stash push", "git stash push -m x", "git stash save x", "git stash apply", "git stash drop", "git stash clear", "git stash create",
                "git stash store abc", "git stash branch feat/x", "git stash -u", "git stash --keep-index", "git stash -- a.ts", "git stash pop stash@{1}",
                "git stash list; git stash drop", "git stash list && git stash", "git stash list | git stash", "git stash -q list", "git stash -- list"],
        "miss": ["git status", "git commit -m 'stash later' -- a.md", "echo 'git stash'", "rg stash", "git log --grep stash", "git stash-free-tool",
                 "git show HEAD:stash", "git diff stash", "git stash list", "git stash list | head -1", "git stash list --oneline", "git stash show",
                 "git stash show -p", "git stash show stash@{1}", "git -C apps/web stash list", "cd app && git stash show --stat", "bash -c 'git stash list'"],
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
                "git add . && git commit -m x", "echo hi\ngit add -A", "FOO=1 git add .", "bash -c 'git add -A'",
                "git add -u", "git add --update", "git add -uv", "git add -u -- . ':!package.json'", "git add -A .", "git add -A -- .", "git add --all .", "git add a.ts .",
                "git add :/", "git add :", "git add -A :/", "git add ./", "git add -A ':!package.json'", "git add -- ':!package.json'", "git add -u ':^b'",
                "git add -A ':(exclude)b'", "git add -A -n", "git add -A --verbose", "git -C app add -u", "cd app && git add -u && git status"],
        "miss": ["git add apps/web/a.ts docs/b.md", "git add -- docs/x.md", "git add ./a.md", "git add -n a.md", "git add -p a.ts", "git add -u a.md",
                 "git add -A web/src/app/Page.test.tsx", "git add -A docs CLAUDE.md README.md", "git add -A some/dir", "git add --all docs", "git add -Av docs",
                 "git add -A -- docs", "git add -u web/src", "git add --update docs a.md", "git add -A docs ':!docs/draft.md'", "git add -A ./a.md", "git add -A .github",
                 "git add -A -- -odd-name", "git add a.ts b.ts", "git add", "git add -A docs && git commit -m x -- docs", "cd app && git add -A src",
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
    "secret-read": {
        "hit": ["cat .env", "cat .env.local", "cat config/.env.staging", "cat apps/web/.env.production", "cat foo.env.local", "cat ./.env", 'cat "config/.env.local"',
                "cat -n .env", "cat -- .env", "less .env", "more .env.local", "head -n 3 .env", "tail -5 config/.env.local", "sed -n 1p .env",
                "sed -n '1,5p' config/.env.local", "sed -e p .env", "awk -F= '{print $2}' .env.local", "rg -n KEY .env", "rg -e KEY .env.local", "grep KEY .env",
                "grep -n KEY config/.env.local", "bat .env", "strings .env", "xxd .env", "od -c .env", "cut -d= -f2 .env", "sort .env", "nl .env", "base64 .env",
                "base64 -i config/.env.local", "cp .env /dev/stdout", "cp config/.env.local /dev/stderr", "cat .env*", "cat .env.*", "tac .env", "dd if=.env",
                "jq . .env.local", "cat < .env", "cat<.env", "echo $(<.env)", "cat .env | head", "ls && cat .env", "cd config && cat .env.local", 'bash -c "cat .env"',
                "FOO=1 cat .env", "sudo cat .env", "diff .env .env.example", "cat .env.example .env", "ls\ncat .env",
                "source .env; echo $KEY", 'source config/.env.local && printf "%s" "$DATABASE_URL"', '. .env.local; echo "$X"', "set -a; source .env; set +a; echo $TOKEN",
                'bash -c "source .env; echo $K"', "source .env\necho $KEY",
                "source .env && echo $DATABASE_URL", "source .env; echo ${DATABASE_URL}", 'source .env; echo "exit $? $KEY"', "source .env; echo $?$KEY",
                "source .env; echo $status_x", "source .env; echo $statusx", "source .env; echo $PIPESTATUSX", "source .env; echo ${status:-$KEY}",
                "source .env; echo ${pipestatus[$i]}", 'source .env; echo "$(printenv KEY)"', "source .env; echo ${!NAME}", "source .env; echo ${#KEY}", "source .env; echo $",
                "source .env; echo $1$KEY", "source .env; echo $KEY2", 'source .env; printf "%s %s" "$?" "$KEY"',
                'rg -n "DATABASE_URL" .env* | rg -v PASSWORD', "rg TOKEN .env", "rg -n TOKEN .env.local | head", "cut -d= -f2 .env", "cut -d= -f1,2 .env", "cut -d= -f1- .env",
                "cut -d, -f1 .env", "cut -f1 .env", "cut -d= .env", "cut -d= -f1 --complement .env", "cut -d= -f1 -f2 .env", "cut -d= -f2 -f1 .env", "cut -d== -f1 .env",
                "cut -c1-5 .env", "cut -d= -f 2 .env", "cat .env | cut -d= -f1", "rg -L KEY .env", "rg -Ln KEY .env", "rg -c --json KEY .env", "rg -l --json KEY .env",
                "rg --json -q KEY .env", "grep -l --format=%O KEY .env", "grep -c --json KEY .env", "rg -gc KEY .env", "rg -tc KEY .env", "rg -e -c .env",
                "rg -e -q .env", "rg --regexp -c .env", "rg KEY .env -- -c", "rg -A3 KEY .env", "rg -v -n KEY .env", "grep -n KEY .env; rg -c KEY .env",
                "rg -c KEY .env; cat .env", "cat .env; rg -q KEY .env", "grep -A2c KEY .env", "rg -Ec KEY .env", "rg -rc KEY .env", "rg -r c KEY .env",
                "rg -m1 KEY .env", "rg --max-count=1 KEY .env"],
        "miss": ["cat .env.example", "cat config/.env.example", "head .env.example", "ls -la .env.local", "ls .env", "test -f config/.env.local", "[ -f .env ] && echo yes",
                 "make test", "stat .env", "rg -n 'env.local' docs", "rg -n .env.local docs", 'rg --glob "!.env*" KEY', "sed -n '1,5p' .envrc-notes.md",
                 "grep -n ENV_FILE Makefile", "cat docs/env-notes.md", "cat environment.md", "echo $HOME", "echo .env", "cp .env.example .env", "cp .env.local backup/",
                 "git status --short .env.example", "git add .env.example", "cat envfile.txt", "source scripts/lib.sh; echo $X", "source .env; make test",
                 "set -a; source config/.env.local; set +a; bash scripts/run.sh", "echo $KEY; source .env", "cat <<EOF\ncat .env\nEOF", "diff a.md b.md",
                 'set -a && . ./.env.local && set +a && go test ./... 2>&1 | tail -8; echo "exit=${pipestatus[1]}"',
                 '(set -a; . ./.env.local; set +a; go test ./... > out.txt 2>&1); echo "go exit $?"',
                 'cut -d= -f1 .env.development.local | rg "DATABASE_URL|DIRECT_URL"', 'rg -c "^QSTASH_TOKEN=" .env .env.local',
                 'for k in A B; do if rg -q "^$k=" .env.local; then echo "$k set"; fi; done',
                 "source .env; echo $?", "source .env; echo $!", "source .env; echo $#", "source .env; echo $$", "source .env; echo $-", "source .env; echo $0 $1 $9",
                 "source .env; echo $@ $*", 'source .env; echo "$@"', "source .env; echo ${?} ${#} ${1} ${10} ${@}", "source .env; echo $status ${status}",
                 "source .env; echo ${pipestatus[1]} ${pipestatus} $pipestatus[2] ${PIPESTATUS[0]} $PIPESTATUS ${PIPESTATUS[@]} ${pipestatus[-1]}",
                 'source .env; echo "exit=$? status=$status"', 'source config/.env.local; printf "%s\\n" "$?"', "source .env; echo done", "source .env; echo",
                 "cut -d= -f1 .env", "cut -d = -f1 .env", "cut -d '=' -f 1 .env", "cut -d= -f 1 .env", "cut -f1 -d= .env", "cut -f 1 -d '=' .env", "cut -d= -f1 -s .env",
                 "cut -d= -f1 .env.local .env", "cut -d= -f1 < .env", "cut -d= -f1 config/.env.production | sort",
                 "rg -c KEY .env", "rg --count KEY .env", "rg -q KEY .env", "rg --quiet KEY .env", "rg -l KEY .env", "rg --files-with-matches KEY .env",
                 "rg --files-without-match KEY .env", "rg -qn KEY .env", "rg -nc KEY .env", "rg -cn KEY .env.local", "rg -ci KEY .env", "rg -c -o KEY .env",
                 "rg -c -v KEY .env", "rg -l -v KEY .env", "rg --count-matches KEY .env", "rg -c -e KEY .env", "rg -c -A2 KEY .env", "rg -cA2 KEY .env", "rg -c -g '*.x' KEY .env",
                 "rg -c KEY .env*", "rg -c KEY .env.local config/.env", "rg -c -- KEY .env", "rg -iqe KEY .env", "rg -qg x KEY .env",
                 "grep -c KEY .env", "grep -q KEY .env", "grep -l KEY .env", "grep -L KEY .env", "grep --count KEY .env", "grep --quiet KEY .env", "grep --silent KEY .env",
                 "grep --files-with-matches KEY .env", "grep --files-without-match KEY .env", "grep -cE 'A|B' .env", "grep -Ec 'A|B' .env", "grep -ci KEY .env",
                 "grep -qE KEY .env", "egrep -c 'A|B' .env", "fgrep -q KEY .env", "grep -c -e KEY .env", "grep -cA2 KEY .env", "grep -c -m1 KEY .env",
                 "/usr/bin/rg -c KEY .env", "sudo rg -c KEY .env", "cd app && rg -q KEY .env.local", "bash -c 'rg -c KEY .env'", "FOO=1 rg -c KEY .env"],
    },
    "env-dump": {
        "hit": ["printenv", "printenv HOME", "/usr/bin/printenv", "env", "env | sort", "env -0", "env -i", "env -u FOO", "FOO=1 env", "sudo env", "nice env",
                "bash -c env", "echo x; printenv", "ls\nenv", "cd app && env",
                "env | rg KEY", "env | grep KEY", "env | rg -n KEY", "env | rg -i '^ANTHROPIC'", "env | rg -c KEY --json", "env | rg -L KEY", "env | rg -gc KEY", "env | rg -e -c",
                "printenv | rg KEY", "printenv NAME", "printenv | sort", "env | sort | rg -c KEY", "env | cat | rg -q KEY", "env | head", "env | tee out | rg -c KEY",
                "env; rg -c KEY out.txt", "env && rg -c KEY", "env; rg -q KEY", "env | rg -c KEY; env", "env | rg -c KEY && printenv",
                "env | sed -n p", "env | cut -d= -f2", "env | awk '{print}'", "env | wc -l", "env | xargs echo", "env | (cat)", "echo $(env | rg KEY)", "echo `printenv`",
                "env | rg -c KEY | env", "bash -c 'env | rg KEY'", "bash -c 'env'; env | rg -c KEY | cat; printenv", "rg -c KEY | env", "env -0 | rg KEY", "env | rg -- -c KEY",
                "echo $(env)", "bash -c 'echo $(env)'", "env | env"],
        "miss": ["echo env", 'printf "%s\\n" env', "env FOO=1 make test", "env -i FOO=1 bash x.sh", "env -u FOO make test", "sudo env FOO=1 make", "printenvironment",
                 "echo $HOME", "git status", "ls env", "cat env.md", "rg printenv docs",
                 'env | rg -c "^ANTHROPIC_API_KEY="', 'env | rg -c "^UPSTASH"', "env | rg --count '^X'", "env | rg -q '^X'", "env | rg --quiet '^X'", "env | rg -qi x",
                 "env | rg -ci x", "env | grep -c '^X'", "env | grep -q '^X'", "env | grep --count X", "env | egrep -c 'A|B'", "env | fgrep -q X", "env | rg -c -e '^X'",
                 "env | rg -c KEY | head", "env | rg -c KEY | cat", "printenv | rg -c '^X'", "printenv | grep -q '^X'", "printenv NAME | rg -q .", "env | rg -l X", "env | rg --count-matches X",
                 "env | rg -c -v X", "env | rg -c -o X", "env | /usr/bin/rg -c X", "env | sudo rg -c X", "env | rg -c X && echo ok", "env | rg -c X || echo none", "env | rg -c X; echo done",
                 "env | rg -c X 2>&1", "env -0 | rg -c X", "FOO=1 env | rg -c X", "sudo env | rg -c X", "env |\n  rg -c X", "cd app && env | rg -q X && echo set", "bash -c 'env | rg -c X'",
                 "sh -c \"printenv | grep -c '^X'\"", "if env | rg -q '^X'; then echo set; fi", 'test -n "$NAME"', 'test -n "${NAME:-}" && echo set'],
    },
    "pipe-before-commit": {
        "hit": ["go test ./... | tail -5 && git commit -m 'fix: x' -- a.go", "pnpm vitest run 2>&1 | tail -20 && git add web/a.ts && git commit -m x -- web/a.ts",
                "make verify | tee verify.log && git commit -m x -- a", "go test ./... | grep -v ok | tail && git commit -m x -- a",
                "git add a && go test | tail &&\n  git commit -m x -- a", "go test | tail && git -C app commit -m x -- a", "set -o errexit; go test | tail && git commit -m x -- a",
                "bash -c 'go test | tail' && true; go test | tail && git commit -m x -- a"],
        "miss": ["go test ./... > test.log 2>&1 && tail -5 test.log && git commit -m x -- a.go", "set -o pipefail; go test ./... | tail -5 && git commit -m x -- a.go",
                 "set -euo pipefail; go test | tail && git commit -m x -- a", "echo 'fix: x' | git commit -F - -- a.go", "go test ./... | tail -5; git status",
                 "go test ./... | tail -5 && git status", "git commit -m 'a | b && git commit' -- a.go", "go test | tail -5 || git commit -m x -- a",
                 "bash -o pipefail -c 'go test | tail && git commit -m x -- a'", "go test | tail -5\ngit commit -m x -- a", "git log | head -3; git commit -m x -- a"],
    },
}


# `{}` takes the command as it is, `{q}` takes it as one quoted word.
WRAPPERS = [
    "FOO=1 {}", 'A=1 B="x y" {}', "env {}", "env FOO=1 {}", "env -i FOO=1 {}", "env -u FOO {}", "env -- {}", "/usr/bin/env {}",
    "sudo {}", "sudo -E {}", "sudo -u root {}", "sudo --user=root {}", "sudo -- {}", "command {}", "nohup {}", "time {}", "time -p {}",
    "nice {}", "nice -n 10 {}", "nice -10 {}", "exec {}", "sudo env FOO=1 nohup {}", "FOO=1 sudo -u me nice -n 5 {}",
    "if true; then {}; fi", "while true; do {}; done", "! {}", "{{ {}; }}",
    "bash -c {q}", "sh -c {q}", "zsh -c {q}", "bash -lc {q}", "sudo bash -c {q}", "env A=1 sh -c {q}",
]
DENY_PUSH = {"commands": {"deny": [{"match": "acme-cli config push", "reason": "No config push."}]}}
ASKS = {"commands": {"alwaysAsk": ["npm publish"], "askFromSubagent": ["make deploy"]}}


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

    def test_the_reference_lists_every_rule_id_with_its_decision(self):
        readme = (ROOT / "docs" / "reference.md").read_text()
        listed = re.findall(r"^\| `([a-z-]+)` \| (deny|ask) \|", readme, re.MULTILINE)
        self.assertEqual(sorted(listed), sorted((rule_id, kind_of(rule_id)) for rule_id in rule_ids()))

    def test_a_denial_names_the_form_that_is_allowed(self):
        for command, phrases in [("cat .env", ["rg -c", "rg -q", "cut -d= -f1"]), ("env", ['test -n "$NAME"', "env | rg -c"])]:
            reason = verdict(command)[1]
            for phrase in phrases:
                self.assertIn(phrase, reason, command)
            self.assertLess(len(reason), 300, reason)

    def test_disabling_a_rule_allows_its_commands_and_keeps_the_other_rules(self):
        for rule_id, cases in RULE_CASES.items():
            off = {"guards": {"disable": [rule_id]}}
            for command in cases["hit"]:
                self.assertEqual(verdict(command, off)[0], "allow", f"{rule_id}: {command}")
            for other_id, other in RULE_CASES.items():
                if other_id != rule_id:
                    self.assertEqual(verdict(other["hit"][0], off)[0], kind_of(other_id), f"{rule_id} off, {other_id}")


class Wrappers(unittest.TestCase):
    """Every rule, built-in or from the config, sees through every wrapper, and a harmless command stays allowed."""

    def test_each_built_in_rule_sees_through_each_wrapper(self):
        for template in WRAPPERS:
            for rule_id, cases in RULE_CASES.items():
                hit, miss = cases["hit"][0], cases["miss"][0]
                self.assertEqual(verdict(template.format(hit, q=shlex.quote(hit)))[0], kind_of(rule_id), f"{rule_id}: {template}")
                self.assertEqual(verdict(template.format(miss, q=shlex.quote(miss)))[0], "allow", f"{rule_id}: {template}")

    def test_each_config_rule_sees_through_each_wrapper(self):
        for template in WRAPPERS:
            for command, config, agent, expected in [("acme-cli config push", DENY_PUSH, None, "deny"), ("npm publish", ASKS, None, "ask"),
                                                     ("make deploy", ASKS, "acme-web", "ask"), ("make deploy", ASKS, None, "allow")]:
                self.assertEqual(verdict(template.format(command, q=shlex.quote(command)), config, agent)[0], expected, f"{command}: {template}")
            harmless = "acme-cli config list"
            self.assertEqual(verdict(template.format(harmless, q=shlex.quote(harmless)), DENY_PUSH)[0], "allow", template)


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
