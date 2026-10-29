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
ASKS = {"commands": {"askFromSubagent": ["make deploy", "git push"], "alwaysAsk": ["npm publish"]}}


def decide(command, config=None, agent_type=None):
    """Run the hook the way Claude Code does, in a temp project dir holding `config` when given; return its JSON output or None."""
    data = {"tool_name": "Bash", "tool_input": {"command": command}}
    if agent_type:
        data["agent_type"] = agent_type
    payload = json.dumps(data)
    with tempfile.TemporaryDirectory() as tmp:
        if config is not None:
            (pathlib.Path(tmp) / ".claude").mkdir()
            (pathlib.Path(tmp) / ".claude" / "agent-steddy.json").write_text(json.dumps(config))
        env = {**os.environ, "CLAUDE_PROJECT_DIR": tmp}
        out = subprocess.run([sys.executable, "-I", str(SCRIPT)], input=payload, capture_output=True, text=True, env=env, check=True).stdout
    return json.loads(out)["hookSpecificOutput"] if out.strip() else None


def run(command, config=None, agent_type=None):
    """The decision for a command, in process: 'deny', 'ask' or 'allow'. `config` is the project config as a dict."""
    verdict = guard_bash.judge(command, agent_type, config or {})
    return verdict[0] if verdict else "allow"


class GuardBash(unittest.TestCase):
    def test_denies_git_stash_in_any_position(self):
        for command in ["git stash", "git stash pop", "git -C ../other stash list", "cd app && git stash",
                        "ls; git stash", "/usr/bin/git stash", "echo x|git stash"]:
            self.assertEqual(run(command), "deny", command)

    def test_allows_everything_else(self):
        for command in ["git status", "git commit -m 'stash later' -- a.md", "echo 'git stash'", "rg stash", "git log --grep stash"]:
            self.assertEqual(run(command), "allow", command)

    def test_split_ends_a_command_at_operators_newlines_backticks_and_substitutions(self):
        cases = {
            "a b; c": [["a", "b"], ["c"]],
            "a && b || c | d & e": [["a"], ["b"], ["c"], ["d"], ["e"]],
            "ls\ngit stash": [["ls"], ["git", "stash"]],
            "echo $(git stash)": [["echo"], ["git", "stash"]],
            "echo `git stash`": [["echo"], ["git", "stash"]],
            "(cd app; git stash)": [["cd", "app"], ["git", "stash"]],
            "git \\\n  stash": [["git", "stash"]],
            "": [],
            "  \n ; ": [],
        }
        for line, expected in cases.items():
            self.assertEqual(guard_bash.split(line), expected, line)

    def test_split_keeps_quoted_text_inside_its_word_and_keeps_empty_words(self):
        cases = {
            "echo 'git stash; ls'": [["echo", "git stash; ls"]],
            'echo "a && b"': [["echo", "a && b"]],
            "sed -i '' s/a/b/ f": [["sed", "-i", "", "s/a/b/", "f"]],
            'FOO="a b" cmd': [["FOO=a b", "cmd"]],
            "echo it\\'s": [["echo", "it's"]],
            "git commit -m 'it''s'": [["git", "commit", "-m", "its"]],
            "echo 'unterminated": [["echo", "unterminated"]],
        }
        for line, expected in cases.items():
            self.assertEqual(guard_bash.split(line), expected, line)

    def test_split_skips_comments_and_heredoc_bodies(self):
        cases = {
            "echo grep # git stash": [["echo", "grep"]],
            "echo http://x/#frag $# ${A}": [["echo", "http://x/#frag", "$#", "${A}"]],
            "cat <<EOF\ngit stash\nEOF\nls": [["cat"], ["ls"]],
            "cat <<'EOF' | grep x\ngit stash\nEOF": [["cat"], ["grep", "x"]],
            "cat <<-X\n\tgit stash\n\tX\nls": [["cat"], ["ls"]],
            "cat <<A <<B\none\nA\ntwo\nB\nls": [["cat"], ["ls"]],
            "cat <<EOF\nnever closed": [["cat"]],
            "cat <<< git": [["cat", "<<<", "git"]],
            "git commit -m \"$(cat <<'EOF'\nfeat: x\n\ngit add -A\nEOF\n)\"": [["git", "commit", "-m", "$(cat <<'EOF'\nfeat: x\n\ngit add -A\nEOF\n)"]],
        }
        for line, expected in cases.items():
            self.assertEqual(guard_bash.split(line), expected, line)

    def test_split_keeps_redirections_in_one_word(self):
        cases = {
            "git stash 2>&1 | tee log": [["git", "stash", "2>&1"], ["tee", "log"]],
            "make test &>/dev/null; git stash": [["make", "test", "&>/dev/null"], ["git", "stash"]],
            "cat < .env": [["cat", "<", ".env"]],
            "cat<.env": [["cat", "<", ".env"]],
            "echo $(<.env)": [["echo"], ["<", ".env"]],
        }
        for line, expected in cases.items():
            self.assertEqual(guard_bash.split(line), expected, line)

    def test_denies_git_stash_after_a_newline_or_a_backtick_and_not_in_a_heredoc(self):
        self.assertEqual(run("ls\ngit stash"), "deny")
        self.assertEqual(run("echo `git stash`"), "deny")
        self.assertEqual(run("echo $(git stash)"), "deny")
        self.assertEqual(run("cat <<EOF\ngit stash\nEOF"), "allow")
        self.assertEqual(run("echo x # git stash"), "allow")

    def test_looks_through_assignments_wrappers_and_keywords(self):
        wrapped = [
            "FOO=1 {}", 'A=1 B="x y" {}', "env {}", "env FOO=1 {}", "env -i FOO=1 {}", "env -u FOO {}", "env -- {}", "/usr/bin/env {}",
            "sudo {}", "sudo -E {}", "sudo -u root {}", "sudo --user=root {}", "sudo -- {}", "command {}", "nohup {}", "time {}", "time -p {}",
            "nice {}", "nice -n 10 {}", "nice -10 {}", "exec {}", "sudo env FOO=1 nohup {}", "FOO=1 sudo -u me nice -n 5 {}",
            "if true; then {}; fi", "while true; do {}; done", "! {}", "{{ {}; }}",
        ]
        for template in wrapped:
            for inner, config in [("git stash", None), ("supabase config push", DENY_PUSH)]:
                command = template.format(inner)
                self.assertEqual(run(command, config), "deny", command)
                self.assertEqual(run(template.format("git status"), config), "allow", template)

    def test_a_wrapper_word_only_counts_at_the_start_of_a_command(self):
        for command in ["echo sudo git stash", "echo env FOO=1 git stash", "git log nohup stash", "ls time git stash", "echo FOO=1 git stash"]:
            self.assertEqual(run(command, DENY_PUSH), "allow", command)
        self.assertEqual(run("echo sudo supabase config push", DENY_PUSH), "allow")

    def test_checks_the_script_of_a_shell_dash_c(self):
        for command in ['bash -c "git stash"', "sh -c 'git stash'", 'zsh -c "git stash"', 'bash -lc "git stash"', 'bash -ec "git stash"',
                        'bash -c "cd app && git stash"', 'bash -c "ls\ngit stash"', "bash -c 'sh -c \"git stash\"'", 'sudo bash -c "git stash"',
                        'env A=1 sh -c "git stash" name', 'bash --norc -c "git stash"', 'bash -o pipefail -c "git stash"',
                        "echo hi; bash -c 'git stash'", "bash -c 'git stash' | tee log"]:
            self.assertEqual(run(command), "deny", command)
        for command in ['bash -c "supabase config push"', "sh -c 'cd x; supabase --debug config push'"]:
            self.assertEqual(run(command, DENY_PUSH), "deny", command)
        for command in ['bash -c "git status"', "bash -c 'echo git stash'", "bash script.sh", "bash git stash", "bash -c", "bash -x script.sh -c 'git stash'",
                        "echo bash -c 'git stash'", "bash -c ''", 'dash -c "git stash"']:
            self.assertEqual(run(command), "allow", command)

    def test_looks_into_nested_scripts_three_levels_deep(self):
        three = "bash -c \"bash -c \\\"bash -c 'git stash'\\\"\""
        four = "bash -c \"bash -c \\\"bash -c 'bash -c \\\\\\\"git stash\\\\\\\"'\\\"\""
        self.assertEqual(run(three), "deny")
        self.assertEqual(run(four), "allow")  # the depth limit: a script nested deeper is not read

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

    def test_pattern_words_match_in_order_among_the_positional_words(self):
        pattern = "cli config push"
        for command in ["cli --workdir app config push", "cli app config push", "cli config app push", "cli config push app",
                        "cli -v config -q push", "cli a b config c d push e"]:
            self.assertTrue(guard_bash.matches(command.split(), pattern), command)
        for command in ["cli push config", "cli config", "cli push", "cli --config --push", "cli config-push", "cli config pull"]:
            self.assertFalse(guard_bash.matches(command.split(), pattern), command)
        self.assertTrue(guard_bash.matches(["cli", "--x=config", "config", "push"], pattern))
        self.assertTrue(guard_bash.matches(["make", "deploy"], "make deploy"))
        self.assertTrue(guard_bash.matches(["make"], "make"))

    def test_an_option_value_does_not_hide_a_listed_command(self):
        for command in ["supabase --workdir app config push", "cd x && supabase --workdir app config push --yes"]:
            self.assertEqual(run(command, DENY_PUSH), "deny", command)

    def test_denies_a_command_listed_in_the_project_config_with_its_reason(self):
        for command in ["supabase config push", "supabase --debug config push --yes", "cd app && supabase config push",
                        "make test; /usr/bin/supabase config push | tee log"]:
            decision = decide(command, DENY_PUSH)
            self.assertEqual(decision["permissionDecision"], "deny", command)
            self.assertEqual(decision["permissionDecisionReason"], "Ask the owner to run config push.")

    def test_always_ask_asks_in_the_main_session_and_in_a_subagent(self):
        for command in ["npm publish", "npm publish --access public", "cd pkg && npm publish", "sudo -u me npm publish", "bash -c 'npm publish'",
                        "/usr/bin/npm --prefix pkg publish"]:
            for agent in [None, "", "acme-web"]:
                self.assertEqual(run(command, ASKS, agent), "ask", f"{command} {agent!r}")
        for command in ["npm run build", "npm test", "echo 'npm publish'", "echo npm publish", "git status"]:
            self.assertEqual(run(command, ASKS, "acme-web"), "allow", command)

    def test_ask_from_subagent_asks_a_subagent_and_allows_the_main_session(self):
        for command in ["make deploy", "make -C app deploy", "git push", "git -C x push origin main", "cd app && make deploy", "env CI=1 make deploy",
                        "sh -c 'git push'"]:
            self.assertEqual(run(command, ASKS, "acme-web"), "ask", command)
            for main_session in [None, ""]:
                self.assertEqual(run(command, ASKS, main_session), "allow", f"{command} {main_session!r}")
        for command in ["make test", "git status", "git pull", "echo make deploy"]:
            self.assertEqual(run(command, ASKS, "acme-web"), "allow", command)

    def test_an_ask_gives_a_reason_that_names_the_pattern_and_the_key(self):
        always = decide("npm publish", ASKS)
        self.assertEqual(always["permissionDecision"], "ask")
        self.assertIn("`npm publish`", always["permissionDecisionReason"])
        self.assertIn("alwaysAsk", always["permissionDecisionReason"])
        sub = decide("make deploy", ASKS, "acme-web")
        self.assertEqual(sub["permissionDecision"], "ask")
        self.assertIn("`make deploy`", sub["permissionDecisionReason"])
        self.assertIn("askFromSubagent", sub["permissionDecisionReason"])
        self.assertIsNone(decide("make deploy", ASKS))

    def test_a_deny_beats_an_ask(self):
        both = {"commands": {**DENY_PUSH["commands"], "alwaysAsk": ["supabase config push", "make deploy"], "askFromSubagent": ["supabase config push"]}}
        for agent in [None, "acme-web"]:
            decision = guard_bash.judge("supabase config push", agent, both)
            self.assertEqual(decision, ("deny", "Ask the owner to run config push."))
            self.assertEqual(run("make deploy && supabase config push", both, agent), "deny")
            self.assertEqual(run("supabase config push; make deploy", both, agent), "deny")
        self.assertEqual(run("make deploy", both), "ask")

    def test_a_built_in_deny_beats_a_config_deny_and_a_config_ask(self):
        config = {"commands": {"deny": [{"match": "git stash", "reason": "config reason"}], "alwaysAsk": ["git stash"], "askFromSubagent": ["git stash"]}}
        for agent in [None, "acme-web"]:
            kind, reason = guard_bash.judge("git stash", agent, config)
            self.assertEqual(kind, "deny")
            self.assertTrue(reason.startswith("[git-stash] "), reason)
        off = {**config, "guards": {"disable": ["git-stash"]}}
        self.assertEqual(guard_bash.judge("git stash", None, off), ("deny", "config reason"))

    def test_broken_ask_entries_are_skipped_and_do_not_hide_a_valid_one(self):
        config = {"commands": {"alwaysAsk": [42, None, ["x"], {"match": "a"}, "", "npm publish"], "askFromSubagent": "make deploy"}}
        self.assertEqual(run("npm publish", config), "ask")
        self.assertEqual(run("make deploy", config, "acme-web"), "allow")
        self.assertEqual(run("git status", config, "acme-web"), "allow")

    def test_ask_lists_work_from_the_config_file_through_the_hook(self):
        for agent, expected in [(None, None), ("acme-web", "ask")]:
            decision = decide("git push", ASKS, agent)
            self.assertEqual(decision and decision["permissionDecision"], expected)
        self.assertEqual(decide("npm publish", ASKS)["hookEventName"], "PreToolUse")

    def test_allows_other_commands_with_a_config(self):
        for command in ["supabase config list", "supabase db push", "echo 'supabase config push'", "git status"]:
            self.assertEqual(run(command, DENY_PUSH), "allow", command)

    def test_allows_the_listed_command_without_a_config_file_or_with_a_broken_one(self):
        self.assertIsNone(decide("supabase config push"))
        self.assertIsNone(decide("supabase config push", ["not", "an", "object"]))

    def test_built_in_rules_hold_without_the_config_and_with_a_broken_one(self):
        for config in [None, DENY_PUSH, ["not", "an", "object"], {"commands": {"deny": [42]}}, {"commands": "x", "guards": [1]},
                       {"guards": {"disable": [["git-stash"], 7, None]}}, {"guards": {"disable": "git-stash"}}]:
            self.assertEqual(decide("git stash", config)["permissionDecision"], "deny", config)
        for config in [{"commands": {"deny": "oops"}}, {"commands": {"deny": [None, {"match": 3}]}}, {"commands": []}]:
            self.assertIsNone(decide("git status", config), config)

    def test_a_broken_deny_entry_does_not_hide_a_valid_one_after_it(self):
        config = {"commands": {"deny": [42, {"match": 3}, {"reason": "no match key"}] + DENY_PUSH["commands"]["deny"]}}
        self.assertEqual(run("supabase config push", config), "deny")

    def test_a_project_can_turn_a_built_in_rule_off_by_id(self):
        off = {"guards": {"disable": ["git-stash"]}}
        self.assertEqual(run("git stash"), "deny")
        self.assertEqual(run("git stash", off), "allow")
        self.assertIsNone(decide("git stash", off))
        self.assertEqual(run("git stash", {"guards": {"disable": ["no-such-rule"]}}), "deny")
        self.assertEqual(run("git stash", {**DENY_PUSH, **off}), "allow")
        self.assertEqual(run("supabase config push", {**DENY_PUSH, **off}), "deny")

    def test_the_reason_of_a_built_in_rule_starts_with_its_id(self):
        decision = decide("git stash")
        self.assertEqual(decision["permissionDecision"], "deny")
        self.assertTrue(decision["permissionDecisionReason"].startswith("[git-stash] "), decision)

    def test_a_rule_without_a_reason_still_denies(self):
        decision = decide("make deploy", {"commands": {"deny": [{"match": "make deploy"}]}})
        self.assertEqual(decision["permissionDecision"], "deny")
        self.assertIn("make deploy", decision["permissionDecisionReason"])


if __name__ == "__main__":
    unittest.main()
