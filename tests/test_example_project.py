"""The example project (examples/acme) is run through the real hook scripts and the command, the way Claude Code runs them.

Hooks: `CLAUDE_PROJECT_DIR` is the example itself, and each script gets a representative input on stdin.
Command: `bin/agent-steddy` runs in a temp copy of the example (a git repo), so the example stays untouched.
A last class checks that the agents, the role cards and the config of the example agree with each other and with the templates.
"""
import contextlib
import fnmatch
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "examples" / "acme"
CONFIG = json.loads((EXAMPLE / ".claude" / "agent-steddy.json").read_text(encoding="utf-8"))
BIN = ROOT / "bin" / "agent-steddy"
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from hook_runner import git, make_repo, run_hook  # noqa: E402


def bash(command, agent=None):
    """The Bash guard's verdict for a command: (decision, reason); ('allow', None) when it prints nothing."""
    data = {"tool_name": "Bash", "tool_input": {"command": command}, **({"agent_type": agent} if agent else {})}
    out = run_hook("guard_bash.py", data, EXAMPLE)
    return (out["hookSpecificOutput"]["permissionDecision"], out["hookSpecificOutput"]["permissionDecisionReason"]) if out else ("allow", None)


def spawn(subagent_type=None, model=None):
    """The agent guard's reason to deny starting a subagent, None when it is allowed."""
    tool_input = {"prompt": "do the task", **({"subagent_type": subagent_type} if subagent_type else {}), **({"model": model} if model else {})}
    out = run_hook("guard_agent.py", {"tool_name": "Agent", "tool_input": tool_input}, EXAMPLE)
    return out["hookSpecificOutput"]["permissionDecisionReason"] if out else None


def write(agent, path):
    """The write fence's reason to deny a write, None when it is allowed. `agent` None is the main session."""
    data = {"tool_name": "Write", "tool_input": {"file_path": path}, **({"agent_type": agent} if agent else {})}
    out = run_hook("guard_write.py", data, EXAMPLE)
    return out["hookSpecificOutput"]["permissionDecisionReason"] if out else None


def stop(agent, message, active=False):
    """The stop check's reason to block a hand-back, None when the agent may stop."""
    data = {"hook_event_name": "SubagentStop", "agent_type": agent, "last_assistant_message": message, "stop_hook_active": active}
    out = run_hook("stop_check.py", data, EXAMPLE)
    return out["reason"] if out else None


class BashGuard(unittest.TestCase):
    def test_allows_ordinary_commands_and_a_push_from_the_main_session(self):
        for command in ["git status", "rg TODO web/", "git push origin main", "make deploy-web"]:
            self.assertEqual(bash(command), ("allow", None), command)

    def test_denies_a_built_in_rule_and_the_project_rule(self):
        decision, reason = bash("git stash")
        self.assertEqual(decision, "deny")
        self.assertTrue(reason.startswith("[git-stash]"), reason)
        self.assertEqual(bash("cat .env")[0], "deny")
        self.assertEqual(bash("acme-cli config push --yes"), ("deny", CONFIG["commands"]["deny"][0]["reason"]))

    def test_asks_for_a_force_push_and_for_the_project_publish_commands(self):
        decision, reason = bash("git push --force origin main")
        self.assertEqual(decision, "ask")
        self.assertTrue(reason.startswith("[git-push-force]"), reason)
        for command in CONFIG["commands"]["alwaysAsk"]:
            self.assertEqual(bash(command)[0], "ask", command)

    def test_a_subagent_asks_before_a_deploy_that_the_main_session_runs_freely(self):
        for command in CONFIG["commands"]["askFromSubagent"]:
            self.assertEqual(bash(command)[0], "allow", command)
            self.assertEqual(bash(command, agent="acme-web")[0], "ask", command)

    def test_a_deny_beats_an_ask_in_one_line(self):
        self.assertEqual(bash("make deploy && acme-cli config push", agent="acme-web")[0], "deny")


class AgentGuard(unittest.TestCase):
    def test_allows_the_acme_agents_without_a_model_or_on_the_model_the_config_sets(self):
        self.assertIsNone(spawn("acme-web"))
        self.assertIsNone(spawn("acme-web", "sonnet"))
        self.assertIsNone(spawn("acme-docs", "claude-haiku-4-5"))
        self.assertIsNone(spawn("acme-verifier", "claude-sonnet-4-5"))

    def test_denies_a_type_the_project_does_not_allow(self):
        for agent in ["general-purpose", "Explore", None]:
            reason = spawn(agent)
            self.assertIn("agents.allowed", reason or "", agent)
            self.assertIn("acme-*", reason, agent)

    def test_denies_a_model_that_is_not_the_one_set_for_the_type(self):
        self.assertIn("must run on haiku", spawn("acme-docs", "opus"))
        self.assertIn("must run on sonnet", spawn("acme-web", "haiku"))
        self.assertIn("must run on sonnet", spawn("acme-verifier", "opus"))


class WriteFence(unittest.TestCase):
    def test_the_auditor_writes_inside_its_fence(self):
        self.assertIsNone(write("acme-auditor", str(EXAMPLE / "docs" / "reviews" / "security.md")))
        self.assertIsNone(write("acme-auditor", "docs/reviews/performance.md"))

    def test_the_auditor_is_denied_outside_its_fence(self):
        for path in [str(EXAMPLE / "web" / "index.html"), "docs/reviews-old/a.md", "docs/reviews/../../web/a.html", "/etc/hosts"]:
            reason = write("acme-auditor", path)
            self.assertIn("docs/reviews/", reason or "", path)
            self.assertIn(path, reason, path)

    def test_the_main_session_and_the_unfenced_agents_write_anywhere(self):
        for agent in [None, "acme-web", "acme-docs"]:
            self.assertIsNone(write(agent, str(EXAMPLE / "web" / "index.html")), agent)


COMPLETE = "Files: web/index.html. Commit abc123. Verification: L1, unit tests green. Resources: released the dev server. Retro: worked / exposed / rule."


class StopCheck(unittest.TestCase):
    def test_blocks_a_hand_back_that_misses_every_item_and_names_each_hint(self):
        reason = stop("acme-web", "Done.")
        for item in CONFIG["handback"]["required"]:
            self.assertIn(item["hint"], reason)

    def test_blocks_only_the_items_that_are_missing(self):
        reason = stop("acme-docs", "Verified at L0. Retro: worked / exposed / rule.")
        self.assertIn(CONFIG["handback"]["required"][2]["hint"], reason)
        self.assertNotIn(CONFIG["handback"]["required"][0]["hint"], reason)
        self.assertNotIn(CONFIG["handback"]["required"][1]["hint"], reason)

    def test_lets_a_complete_hand_back_stop(self):
        self.assertIsNone(stop("acme-web", COMPLETE))

    def test_blocks_once_and_ignores_agents_the_config_does_not_list(self):
        self.assertIsNone(stop("acme-web", "Done.", active=True))
        self.assertIsNone(stop("general-purpose", "Done."))


@contextlib.contextmanager
def copy_of_example():
    """A temp git repo holding a copy of the example, as a resolved path."""
    with tempfile.TemporaryDirectory() as tmp:
        project = pathlib.Path(tmp).resolve() / "acme"
        shutil.copytree(EXAMPLE, project)
        make_repo(project)
        yield project


def agent_steddy(*args, cwd):
    """The finished process of `bin/agent-steddy`, run as the Bash tool runs it: no CLAUDE_PROJECT_DIR."""
    env = {key: value for key, value in os.environ.items() if key not in ("CLAUDE_PROJECT_DIR", "CLAUDE_PLUGIN_DATA")}
    return subprocess.run([str(BIN), *args], cwd=cwd, env=env, capture_output=True, text=True, check=True)


class WholeTask(unittest.TestCase):
    def test_a_task_from_the_prompt_to_the_records_on_a_copy_of_the_example(self):
        records = CONFIG["records"]
        with copy_of_example() as project:
            reminder = run_hook("gate_reminder.py", {"hook_event_name": "UserPromptSubmit", "prompt": "add a page"}, project)
            self.assertEqual(reminder["hookSpecificOutput"]["additionalContext"], CONFIG["reminder"]["text"])
            clock = project / ".git" / "agent-steddy" / "pending-task.json"
            self.assertTrue(clock.is_file())

            agent_steddy("metrics", "start", "add the pricing page", cwd=project)
            agent_steddy("record", "decision", "web", "keep the pricing page static - no client script needed", cwd=project)
            agent_steddy("record", "lesson", "--task", "add the pricing page", "--roles", "acme-web,acme-docs",
                         "--worked", "the brief named the files", "--exposed", "none", "--rule", "none", cwd=project)
            logged = agent_steddy("metrics", "log", "--size", "S", "--type", "new", "--verify-first-pass", "yes",
                                  "--roles", "acme-web", "--agents", "1", "--minutes", "7", cwd=project)
            self.assertTrue(logged.stdout.startswith("logged: "), logged.stdout)

            decisions = (project / records["decisions"]).read_text(encoding="utf-8")
            self.assertTrue(decisions.startswith("# Decisions\n"), decisions)
            self.assertIn("- [web] keep the pricing page static - no client script needed\n", decisions)
            lessons = (project / records["lessons"]).read_text(encoding="utf-8")
            self.assertRegex(lessons, r"## \d{4}-\d{2}-\d{2} - add the pricing page - roles: acme-web, acme-docs\n- Worked: the brief named the files\n- Exposed: none\n- Rule: none")
            rows = [json.loads(line) for line in (project / records["metrics"]).read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(rows), 1)
            self.assertEqual({key: rows[0][key] for key in ("task", "type", "size", "roles", "agents", "minutes", "exposed", "verify_first_pass")},
                             {"task": "add the pricing page", "type": "new", "size": "S", "roles": ["acme-web"], "agents": 1, "minutes": 7, "exposed": 0, "verify_first_pass": True})
            self.assertFalse(clock.exists(), "metrics log closes the task clock")

    def test_a_rule_recorded_twice_is_noticed_nudged_and_promoted_into_a_role_card(self):
        records = CONFIG["records"]
        key = "commit-by-path"
        with copy_of_example() as project:
            self.assertTrue((project / records["roles"]).is_dir())
            first = agent_steddy("record", "lesson", "--task", "add the pricing page", "--roles", "web", "--worked", "w", "--exposed", "a commit took a neighbor's file",
                                 "--rule", "commit by path, never git add all", "--key", key, cwd=project)
            self.assertEqual(len(first.stdout.splitlines()), 1)  # only the heading: seen once
            second = agent_steddy("record", "lesson", "--task", "fix the footer", "--roles", "web,docs-writer", "--worked", "w", "--exposed", "the same slip again",
                                  "--rule", "commit by path, never git add all", "--key", key, cwd=project)
            self.assertEqual(second.stdout.splitlines()[1:], [
                f"{key} is now seen 2 times",
                f"agent-steddy lessons promote {key} --to web",
                "roles in these entries, most common first: web (2), docs-writer (1)",
                "a rule about safety, data or money goes --to walls instead",
            ])
            nudge = f"Learning loop: 1 rule(s) seen twice and not promoted ({key}); run agent-steddy lessons check."
            prompt = {"hook_event_name": "UserPromptSubmit", "prompt": "add a page"}
            self.assertEqual(run_hook("gate_reminder.py", prompt, project)["hookSpecificOutput"]["additionalContext"], CONFIG["reminder"]["text"] + "\n" + nudge)
            self.assertEqual(agent_steddy("lessons", "check", "--quiet", cwd=project).stdout.strip(), nudge)
            report = agent_steddy("lessons", "check", cwd=project).stdout
            self.assertIn(f"  {key}: seen 2 times", report)
            self.assertIn(f"    agent-steddy lessons promote {key} --to web", report)

            done = agent_steddy("lessons", "promote", key, "--to", "web", cwd=project)
            self.assertEqual(done.stdout.splitlines()[0].split(" (lessons:")[0], "added to docs/agents/roles/web.md: - commit by path, never git add all")
            card = (project / "docs/agents/roles/web.md").read_text(encoding="utf-8")
            self.assertEqual(card.count("- commit by path, never git add all (lessons: "), 1)
            self.assertNotIn("None recorded yet", card)
            self.assertEqual(card.split("## Pitfalls")[1].split("## Tools")[0].strip().count("\n"), 0)  # the one bullet; the next section is untouched
            self.assertEqual(card.count("## Tools"), 1)
            lessons = (project / records["lessons"]).read_text(encoding="utf-8")
            self.assertEqual(lessons.count(f"- Rule [{key}]: commit by path, never git add all [promoted -> docs/agents/roles/web.md]\n"), 2)

            report = agent_steddy("lessons", "check", cwd=project).stdout
            self.assertEqual(report.splitlines()[:2], ["Due: rules seen 2 or more times and not promoted", "  none"])
            self.assertEqual(agent_steddy("lessons", "check", "--quiet", cwd=project).stdout, "")
            self.assertEqual(run_hook("gate_reminder.py", prompt, project)["hookSpecificOutput"]["additionalContext"], CONFIG["reminder"]["text"])
            self.assertFalse((project / records["walls"]).exists())

    def test_a_pause_is_picked_up_with_the_commit_made_after_it_and_then_cleared(self):
        for folder in [None, "docs/agents/resume"]:  # the example's own setting, then the notes kept in the repo
            with self.subTest(folder=folder), copy_of_example() as project:
                if folder:
                    config = json.loads((project / ".claude" / "agent-steddy.json").read_text(encoding="utf-8"))
                    config["resume"]["folder"] = folder
                    (project / ".claude" / "agent-steddy.json").write_text(json.dumps(config), encoding="utf-8")
                git(project, "add", "-A")
                git(project, "commit", "-q", "-m", "docs: the example")
                git(project, "switch", "-q", "-c", "feat/pricing")
                (project / "pricing.html").write_text("<h1>Pricing</h1>")
                git(project, "add", "pricing.html")
                git(project, "commit", "-q", "-m", "feat: pricing page")
                (project / "footer.html").write_text("<footer></footer>")
                tip = git(project, "rev-parse", "HEAD")

                paused = agent_steddy("pause", "--intent", "add the pricing page", "--done", "the page is committed, L1 tests green", "--next", "link it from the footer",
                                      "--files", "pricing.html,footer.html", cwd=project)
                where = project / folder if folder else project / ".git" / "agent-steddy" / "resume"
                self.assertTrue((where / "feat__pricing.md").is_file(), paused.stdout)
                self.assertEqual(git(project, "rev-parse", "HEAD"), tip, "pause committed nothing")
                start = {"hook_event_name": "SessionStart", "source": "compact"}
                pointer = run_hook("session_start.py", start, project)["hookSpecificOutput"]
                self.assertEqual(pointer["hookEventName"], "SessionStart")
                self.assertRegex(pointer["additionalContext"], r"^Resume note for feat/pricing from \d{4}-\d{2}-\d{2} \d{2}:\d{2}: run agent-steddy resume before you start\.$")

                git(project, "add", "footer.html")
                git(project, "commit", "-q", "-m", "feat: footer link", "--", "footer.html")
                picked = agent_steddy("resume", cwd=project).stdout
                self.assertIn("## Intent\nadd the pricing page\n", picked)
                self.assertRegex(picked, r"commits after [0-9a-f]{12} \(1\):\n  [0-9a-f]+ feat: footer link\n")
                self.assertIn("uncommitted files now (0):\n  none\n", picked)
                self.assertIn("run the verify command (`make verify`)", picked)

                self.assertTrue(agent_steddy("resume", "--clear", cwd=project).stdout.startswith("cleared: "))
                self.assertFalse((where / "feat__pricing.md").exists())
                self.assertIsNone(run_hook("session_start.py", start, project))
                self.assertTrue(agent_steddy("resume", cwd=project).stdout.startswith("no resume note for feat/pricing"))

    def test_the_example_itself_is_left_clean(self):
        self.assertFalse((EXAMPLE / "docs" / "agents" / "decisions.md").exists())
        self.assertFalse((EXAMPLE / "docs" / "agents" / "lessons.md").exists())
        self.assertFalse((EXAMPLE / "docs" / "agents" / "metrics.jsonl").exists())
        self.assertFalse((EXAMPLE / "docs" / "agents" / "walls.md").exists())
        self.assertFalse((EXAMPLE / "docs" / "agents" / "resume").exists())


def frontmatter(text):
    match = re.match(r"---\n(.*?)\n---\n", text, re.S)
    return dict(re.findall(r"^([A-Za-z]+): *(.+?) *$", match.group(1), re.M))


def rules(text):
    """The bullets under 'Rules for every ... agent:', the walls each agent repeats."""
    block = re.search(r"^Rules for every .+ agent:\n((?:- .*\n)+)", text, re.M)
    return block.group(1) if block else None


class ExampleAgrees(unittest.TestCase):
    TEMPLATES = {"acme-web": "implementer", "acme-auditor": "auditor", "acme-verifier": "verifier", "acme-docs": "docs-writer"}

    def test_the_four_agents_are_the_templates_filled_in(self):
        agents = {path.stem: path.read_text(encoding="utf-8") for path in (EXAMPLE / ".claude" / "agents").glob("*.md")}
        self.assertEqual(sorted(agents), sorted(self.TEMPLATES))
        for name, text in agents.items():
            template = (ROOT / "templates" / "agents" / f"{self.TEMPLATES[name]}.md").read_text(encoding="utf-8")
            self.assertNotRegex(text.replace(rules(text) or "", ""), r"<project>|<area>|<paths>|<test paths>", name)  # the walls keep their own <paths>
            self.assertEqual(frontmatter(text)["name"], name)
            self.assertEqual(frontmatter(text)["model"], frontmatter(template)["model"], name)
            self.assertTrue(rules(text), name)
            self.assertEqual(rules(text), rules(template), f"{name}: the walls drifted from the template")

    def test_every_agent_matches_the_config(self):
        for name in self.TEMPLATES:
            model = frontmatter((EXAMPLE / ".claude" / "agents" / f"{name}.md").read_text(encoding="utf-8"))["model"]
            wants = [want for pattern, want in CONFIG["agents"]["models"].items() if fnmatch.fnmatchcase(name, pattern)]
            self.assertEqual(wants[:1], [model], name)
            self.assertTrue(any(fnmatch.fnmatchcase(name, pattern) for pattern in CONFIG["agents"]["allowed"]), name)
            self.assertTrue(any(fnmatch.fnmatchcase(name, pattern) for pattern in CONFIG["handback"]["agents"]), name)
        for name, prefixes in CONFIG["agents"]["writeFences"].items():
            text = (EXAMPLE / ".claude" / "agents" / f"{name}.md").read_text(encoding="utf-8")
            for prefix in prefixes:
                self.assertIn(prefix, text, name)

    def test_every_role_card_an_agent_names_exists(self):
        named = set()
        for path in (EXAMPLE / ".claude" / "agents").glob("*.md"):
            named.update(re.findall(r"docs/agents/roles/[\w-]+\.md", path.read_text(encoding="utf-8")))
        self.assertEqual(len(named), 4)
        for card in named:
            self.assertTrue((EXAMPLE / card).is_file(), card)


if __name__ == "__main__":
    unittest.main()
