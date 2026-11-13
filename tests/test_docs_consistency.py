"""The docs that teach the method (the skills, the templates, the README and the reference) must agree with the code they name.

Fourteen checks: every skill has a name that matches its folder and a description, and every agent template has a name, a description and a model;
every `agent-steddy <group> <sub>` names a subcommand of scripts/cli.py, and every command that has no subcommand is in the reference and the config reference;
every key of the config defaults has a row in the config reference;
the README status line names the manifest's version;
the metric verdict rule in the config reference states the two constants of scripts/metrics.py;
the method rules that must stand in more than one place (the two questions before a Rule line, a check that counts as enforced only after it failed, the brief budget, the auditor's re-run commands) do;
the hand-back block (the same four lines last in every agent template, example agent and the brief, each line carrying the words of its stop-check item, and the block passing `stop_check` as it is and filled in);
the rules inside the gates are grouped by gate and each names its pstack principle, and the three that an implementer meets most stand in the implementer template and its example too;
the premise nudge's text, threshold and switch in the config reference and the reference are the code's, and the text points at a rule the gates skill has;
the pstack companion (the reference section with its install command, gate 2 loading principle skills, a `Principles:` line in every role card with names that pstack has);
the hooks live check (the config reference quotes the warnings, the selftest lines and the age of the markers of the code, the README prompt keeps its scope line, its new-session proof and its 80 columns, and the state files and the hooks table name the markers);
named metrics rows (the refusal the config reference quotes is the code's, the finish skill and the reference say it, no doc logs a row without `--task`, and the old after-the-fact note is gone);
open clocks (the config reference states the working-day constant of scripts/metrics.py, quotes its refusal and the list of rows over it, and names the median columns; the skills and the reference say it);
every backticked built-in rule id is listed in the reference's table;
every relative link resolves, and its #anchor exists when the target is a Markdown file.
"""

import argparse
import datetime as dt
import json
import pathlib
import re
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import cli  # noqa: E402
import local_state  # noqa: E402
import metrics  # noqa: E402
import project_config  # noqa: E402
import session_marker  # noqa: E402
import stop_check  # noqa: E402
import tool_timing  # noqa: E402

README = ROOT / "README.md"
REFERENCE = ROOT / "docs" / "reference.md"
METHOD_DOCS = sorted([README, REFERENCE, *ROOT.glob("skills/**/*.md"), *ROOT.glob("templates/**/*.md")])


def frontmatter(path):
    """The `key: value` lines between the opening and closing `---` of a file; {} when it has none."""
    match = re.match(r"---\n(.*?)\n---\n", path.read_text(encoding="utf-8"), re.S)
    return dict(re.findall(r"^([A-Za-z-]+): *(.+?) *$", match.group(1), re.M)) if match else {}


def subcommands():
    """The (group, subcommand) pairs that scripts/cli.py defines, read from its argparse parser."""
    pairs = set()
    for action in cli.build_parser()._actions:
        if isinstance(action, argparse._SubParsersAction):
            for group, group_parser in action.choices.items():
                for inner in group_parser._actions:
                    if isinstance(inner, argparse._SubParsersAction):
                        pairs.update((group, command) for command in inner.choices)
    return pairs


def top_level_commands():
    """The commands of scripts/cli.py that take no subcommand, such as `pause` and `resume`."""
    names = set()
    for action in cli.build_parser()._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, parser in action.choices.items():
                if not any(isinstance(inner, argparse._SubParsersAction) for inner in parser._actions):
                    names.add(name)
    return names


def rule_table():
    """The rule ids and their decisions that the reference's built-in rule table lists."""
    return re.findall(r"^\| `([a-z-]+)` \| (deny|ask) \|", REFERENCE.read_text(encoding="utf-8"), re.M)


def slug(heading):
    """The anchor GitHub makes for a heading: lower case, punctuation dropped, spaces turned into hyphens."""
    return re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")


class Frontmatter(unittest.TestCase):
    def test_every_skill_has_a_name_that_matches_its_folder_and_a_description(self):
        skills = sorted(ROOT.glob("skills/*/SKILL.md"))
        self.assertTrue(skills)
        for path in skills:
            fields = frontmatter(path)
            self.assertEqual(fields.get("name"), path.parent.name, path)
            self.assertTrue(fields.get("description"), path)

    def test_every_agent_template_has_a_name_a_description_and_a_model(self):
        agents = sorted(ROOT.glob("templates/agents/*.md"))
        self.assertTrue(agents)
        for path in agents:
            self.assertTrue({"name", "description", "model"} <= set(frontmatter(path)), path)


class Commands(unittest.TestCase):
    MENTION = re.compile(r"agent-steddy (metrics|record|lessons) ([a-z]+)")

    def test_every_agent_steddy_command_mentioned_names_a_real_subcommand(self):
        known = subcommands()
        self.assertIn(("metrics", "log"), known)  # the parser was read
        self.assertIn(("lessons", "promote"), known)
        mentions = [(path, match.group(1), match.group(2)) for path in METHOD_DOCS for match in self.MENTION.finditer(path.read_text(encoding="utf-8"))]
        self.assertTrue(mentions)
        for path, group, command in mentions:
            self.assertIn((group, command), known, f"{path.relative_to(ROOT)}: agent-steddy {group} {command}")


    def test_every_command_without_a_subcommand_is_in_the_reference_the_config_reference_and_the_gates_skill(self):
        names = top_level_commands()
        self.assertEqual(names, {"guard", "pause", "resume"})
        for path in [REFERENCE, ROOT / "docs" / "config.md", ROOT / "skills" / "gates" / "SKILL.md"]:
            text = path.read_text(encoding="utf-8")
            for name in names:
                self.assertTrue(f"agent-steddy {name}" in text, f"{path.relative_to(ROOT)}: agent-steddy {name}")


class ConfigKeys(unittest.TestCase):
    def test_every_default_key_has_a_row_in_the_config_reference(self):
        rows = set(re.findall(r"^\| `([A-Za-z.]+)` \|", (ROOT / "docs" / "config.md").read_text(encoding="utf-8"), re.M))
        keys = [f"{section}.{key}" if isinstance(value, dict) else section for section, value in project_config.DEFAULTS.items() for key in (value if isinstance(value, dict) else [None])]
        self.assertIn("resume.folder", keys)
        for key in keys:
            self.assertIn(key, rows, f"docs/config.md has no row for {key}")


class Version(unittest.TestCase):
    def test_the_readme_status_line_names_the_version_of_the_plugin_manifest(self):
        version = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))["version"]
        self.assertIn(f"> Status: version {version},", README.read_text(encoding="utf-8"))


class VerdictRule(unittest.TestCase):
    def test_the_config_reference_states_the_constants_of_the_code(self):
        text = squash((ROOT / "docs" / "config.md").read_text(encoding="utf-8"))
        self.assertIn(f"A week with fewer than {metrics.MIN_TASKS} tasks of that size makes the verdict inconclusive.", text)
        self.assertIn(f"differ by less than {metrics.IQR_SHARE:g} x the larger of the two weeks' interquartile ranges", text)
        self.assertIn("`MIN_TASKS` and `IQR_SHARE`", text)
        for name in ("MIN_TASKS", "IQR_SHARE"):  # the rule is written in one place: the constants are defined once and used by name
            self.assertEqual(len(re.findall(rf"^{name} = ", (ROOT / "scripts" / "metrics.py").read_text(encoding="utf-8"), re.M)), 1, name)


def squash(text):
    return " ".join(text.split())


def lesson_help():
    """The help text that `agent-steddy record lesson -h` prints."""
    for action in cli.build_parser()._actions:
        if isinstance(action, argparse._SubParsersAction):
            for inner in action.choices["record"]._actions:
                if isinstance(inner, argparse._SubParsersAction):
                    return squash(inner.choices["lesson"].format_help())


class MethodRules(unittest.TestCase):
    def read(self, relative):
        return squash((ROOT / relative).read_text(encoding="utf-8"))

    def test_the_two_questions_before_a_rule_line_are_asked_in_the_skills_and_the_command_help(self):
        questions = "will it still be true in six months, and would it make a later agent decide differently?"
        for text, where in [(self.read("skills/gates/SKILL.md"), "gates skill"), (self.read("skills/finish/SKILL.md"), "finish skill"), (lesson_help(), "record lesson -h")]:
            self.assertIn(questions, text, where)
        self.assertIn("a fact for the Exposed line, not yet a rule", self.read("skills/gates/SKILL.md"))
        self.assertIn("a fact for the Exposed line, not yet a rule", self.read("skills/finish/SKILL.md"))

    def test_a_check_counts_as_enforced_only_after_it_failed_on_the_recorded_error(self):
        for relative in ["skills/gates/SKILL.md", "skills/finish/SKILL.md"]:
            text = self.read(relative)
            self.assertIn("counts as enforced only after", text, relative)
            self.assertIn("the error the lessons recorded", text, relative)
        self.assertIn("A green test proves only what the test measures.", self.read("skills/gates/SKILL.md"))

    def test_the_brief_has_a_budget_line_and_no_number_for_it(self):
        text = (ROOT / "templates" / "brief.md").read_text(encoding="utf-8")
        self.assertIn("Budget: read at most <N> files; hand back at most <M> lines, and list every file you read.\n", text)
        sentence = next(line for line in text.splitlines() if line.startswith("- Pick the budget"))
        self.assertIn("no measured default", sentence)
        self.assertNotRegex(sentence, r"\d")

    def test_the_auditor_template_and_its_example_ask_for_the_command_the_output_and_a_dropped_section(self):
        for relative in ["templates/agents/auditor.md", "examples/acme/.claude/agents/acme-auditor.md"]:
            text = self.read(relative)
            self.assertIn("the command that shows the finding and the output it printed", text, relative)
            self.assertIn("The report ends with a Dropped section: how many candidate findings you dropped, and why.", text, relative)


    def test_the_example_config_asks_for_the_default_status_item_first(self):
        example = json.loads((ROOT / "examples" / "acme" / ".claude" / "agent-steddy.json").read_text(encoding="utf-8"))
        default = project_config.DEFAULTS["handback"]["required"]
        self.assertEqual(default[0], {"id": "status", "pattern": r"\b(?:PASS|ISSUES|BLOCKED)\b", "hint": "a status: PASS, ISSUES or BLOCKED"})
        self.assertEqual(example["handback"]["required"][:len(default)], default)


class HandBackBlock(unittest.TestCase):
    """The fill-in block that ends each agent file and the brief, so that a hand-back passes the stop check on the first try."""
    LINES = ["Status: PASS | ISSUES | BLOCKED",
             "Verification: L<0-5>, <what you ran and what you saw>",
             "Resources: <released, or kept and why>",
             "Retro: worked <...> / exposed <...> / rule <...>"]
    ITEMS = ["status", "verification", "resources", "retro"]  # the item of handback.required that each line stands for
    FILLED = "Status: ISSUES\nVerification: L2, ran make verify and saw 3 failures\nResources: kept the dev server on port 4310, the owner asked\nRetro: worked the brief / exposed a stale test / rule none"
    AGENTS = [*sorted(ROOT.glob("templates/agents/*.md")), *sorted(ROOT.glob("examples/acme/.claude/agents/*.md"))]
    BRIEF = ROOT / "templates" / "brief.md"

    def fences(self, path):
        return re.findall(r"```text\n(.*?)\n```", path.read_text(encoding="utf-8"), re.S)

    def configs(self):
        """The default items, for any agent, and the example config's items, for an acme agent: (config, agent type, {item id: hint})."""
        example = json.loads((ROOT / "examples" / "acme" / ".claude" / "agent-steddy.json").read_text(encoding="utf-8"))
        example.pop("resources", None)  # the ports are probed for real, and this check is about the words of the block
        return [({"handback": {"agents": ["*"]}}, "any-agent", {item["id"]: item["hint"] for item in project_config.DEFAULTS["handback"]["required"]}),
                (example, "acme-web", {item["id"]: item["hint"] for item in example["handback"]["required"]})]

    def test_every_agent_template_example_agent_and_the_brief_end_with_the_same_four_lines(self):
        self.assertEqual(len(self.AGENTS), 8)
        for path in self.AGENTS:
            text = path.read_text(encoding="utf-8")
            self.assertEqual(self.fences(path)[-1].splitlines(), self.LINES, path.name)
            self.assertTrue(text.rstrip().endswith("```"), f"{path.name}: the block is the last thing in the file")
            lead_in = squash(text.rsplit("```text", 1)[0].rsplit("Hand back in English.", 1)[1])
            self.assertIn("Start your final message with the four lines below, filled in; pick one status", lead_in, path.name)
            self.assertIn("Only your last message reaches the orchestrator, so the whole hand-back goes in that message", lead_in, path.name)
            self.assertNotIn("- Hand back in English", text, path.name)  # the walls no longer carry the old bullet
        self.assertEqual(self.fences(self.BRIEF)[-1].splitlines()[-4:], self.LINES)
        self.assertIn("Hand back in English, starting with these four lines, filled in (pick one status)", self.fences(self.BRIEF)[-1])
        self.assertIn("only your last message reaches the orchestrator", self.fences(self.BRIEF)[-1])

    def blocks(self):
        """(file name, the block of that file as text) for every file that ends with one."""
        found = []
        for path in [*self.AGENTS, self.BRIEF]:
            fences = self.fences(path)
            self.assertTrue(fences, f"{path.name} has no block")
            found.append((path.name, "\n".join(fences[-1].splitlines()[-4:])))
        self.assertEqual(len(found), 9)
        return found

    def filled(self, block, status):
        """The block as an agent fills it in: one status, a level, and text for every placeholder."""
        return block.replace("PASS | ISSUES | BLOCKED", status).replace("L<0-5>", "L2").replace("<...>", "none").replace("<released, or kept and why>", "released the dev server") \
                    .replace("<what you ran and what you saw>", "ran make verify and saw it pass")

    def test_each_block_passes_the_stop_check_as_it_is_and_filled_in_for_the_default_items_and_the_example_config(self):
        for config, agent, items in self.configs():
            self.assertEqual(list(items)[:3], ["status", "verification", "retro"])
            self.assertIsNotNone(stop_check.judge({"agent_type": agent, "last_assistant_message": "Done."}, config))  # the check is on
            for name, block in self.blocks():
                self.assertNotIn("<", self.filled(block, "PASS"), name)  # every placeholder is one that the test fills
                for message in [block, self.FILLED, *[self.filled(block, status) for status in ("PASS", "ISSUES", "BLOCKED")], self.filled(block, "PASS") + "\n\nFiles changed: a.ts. Commit abc123."]:
                    self.assertIsNone(stop_check.judge({"agent_type": agent, "last_assistant_message": message}, config), (agent, name, message))

    def test_each_line_of_each_block_carries_the_words_of_its_own_item(self):
        for config, agent, items in self.configs():
            for name, block in self.blocks():
                lines = block.splitlines()
                for line, item in zip(lines, self.ITEMS):
                    if item not in items:
                        continue  # the default items have no resources line
                    reason = stop_check.judge({"agent_type": agent, "last_assistant_message": "\n".join(other for other in lines if other != line)}, config)
                    self.assertIn(items[item], reason or "", f"{agent}, {name}: without the {item} line")
                    for other in set(items) - {item}:
                        self.assertNotIn(items[other], reason, f"{agent}, {name}: without the {item} line")


class RulesInsideTheGates(unittest.TestCase):
    PRINCIPLES = ["subtract-before-you-add", "laziness-protocol", "build-the-lever", "sequence-verifiable-units", "fix-root-causes", "attack-the-premise", "never-block-on-the-human"]
    GROUPS = ["Act", "Act and Prove", "Prove", "Deliver"]
    # the three rules an implementer meets most: a phrase of each, as the gates skill and the agent files both say it
    IMPLEMENTER = ["ask why until the answer is a wrong decision in the code", "failing test first and the fix on top", "write the premise as one sentence"]
    AGENTS = ["templates/agents/implementer.md", "examples/acme/.claude/agents/acme-web.md"]

    def section(self):
        text = (ROOT / "skills" / "gates" / "SKILL.md").read_text(encoding="utf-8")
        match = re.search(r"^## Rules inside the gates\n(.*?)(?=^## )", text, re.M | re.S)
        self.assertTrue(match, "the gates skill has no section 'Rules inside the gates'")
        return match.group(1)

    def test_the_rules_are_grouped_by_gate_and_each_names_its_principle(self):
        section = self.section()
        self.assertEqual(re.findall(r"^### (.+)$", section, re.M), self.GROUPS)
        bullets = re.findall(r"^- (.*?)(?=^- |^### |\Z)", section, re.M | re.S)
        self.assertEqual(len(bullets), len(self.PRINCIPLES))
        self.assertEqual([re.search(r"\(pstack: ([a-z-]+)\)\s*\Z", bullet).group(1) for bullet in bullets], self.PRINCIPLES)
        for bullet in bullets:
            self.assertTrue(bullet.startswith("**"), bullet[:40])  # a bold lead, then the sentences, one to a line

    def test_the_three_rules_an_implementer_meets_most_stand_in_the_agent_files_and_point_to_the_section(self):
        section = squash(self.section()).lower()
        for phrase in self.IMPLEMENTER:
            self.assertIn(phrase, section, phrase)
        for relative in self.AGENTS:
            text = squash((ROOT / relative).read_text(encoding="utf-8"))
            for phrase in self.IMPLEMENTER:
                line = next((line for line in text.split(" - ") if phrase in line.lower()), None)
                self.assertTrue(line and "gates skill, Rules inside the gates" in line, f"{relative}: {phrase}")

    def test_the_reference_credit_line_names_the_principles_that_became_rules(self):
        credit = squash(REFERENCE.read_text(encoding="utf-8"))
        self.assertIn("seven principles that became the rules inside the gates", credit)


class PremiseNudge(unittest.TestCase):
    def test_the_config_reference_states_the_text_the_threshold_and_the_switch_of_the_code(self):
        config = squash((ROOT / "docs" / "config.md").read_text(encoding="utf-8"))
        self.assertIn(squash(tool_timing.NUDGE.format(n="<n>")), config)
        self.assertIn(f"`PREMISE_FAILS` = {tool_timing.PREMISE_FAILS} failures in a row", config)
        self.assertIn(f"the last `TAIL` bytes of the log ({tool_timing.TAIL // 1024} KB)", config)
        self.assertIn("`nudges.premise`", config)
        self.assertEqual(project_config.DEFAULTS["nudges"], {"premise": True})
        source = (ROOT / "scripts" / "tool_timing.py").read_text(encoding="utf-8")
        for name in ("PREMISE_FAILS", "TAIL", "NUDGE"):  # each number and the text are defined once and used by name
            self.assertEqual(len(re.findall(rf"^{name} = ", source, re.M)), 1, name)

    def test_the_reference_hooks_table_and_the_gates_skill_name_the_nudge_and_its_switch(self):
        readme = squash(REFERENCE.read_text(encoding="utf-8"))
        row = next(line for line in readme.split(" | ") if line.startswith("Logs how long the command took"))
        self.assertIn("premise nudge", row)
        self.assertIn("`nudges.premise` turns it off", row)
        skill = squash((ROOT / "skills" / "gates" / "SKILL.md").read_text(encoding="utf-8"))
        self.assertIn("**Attack the premise.**", skill)  # the rule the nudge text names
        self.assertIn("The premise nudge points at this rule", skill)
        self.assertTrue(tool_timing.NUDGE.endswith("(gates skill, attack the premise)."))

    def test_the_example_config_names_the_switch(self):
        example = json.loads((ROOT / "examples" / "acme" / ".claude" / "agent-steddy.json").read_text(encoding="utf-8"))
        self.assertEqual(example["nudges"], {"premise": True})


class PstackCompanion(unittest.TestCase):
    # the skills of github.com/backnotprop/pstack named principle-*, without the prefix (listed 2026-10-30)
    PRINCIPLES = {
        "attack-the-premise", "boundary-discipline", "build-the-lever", "encode-lessons-in-structure", "exhaust-the-design-space", "experience-first",
        "explain-the-number", "fix-root-causes", "foundational-thinking", "guard-the-context-window", "laziness-protocol", "make-operations-idempotent",
        "migrate-callers-then-delete-legacy-apis", "minimize-reader-load", "model-the-domain", "never-block-on-the-human", "outcome-oriented-execution",
        "prove-it-works", "redesign-from-first-principles", "separate-before-serializing-shared-state", "sequence-verifiable-units", "subtract-before-you-add",
        "test-behavior-not-implementation", "type-system-discipline",
    }
    CARDS = {  # the principles each example role card names
        "web": ["model-the-domain", "boundary-discipline", "test-behavior-not-implementation"],
        "verifier": ["prove-it-works", "explain-the-number"],
        "auditor": ["fix-root-causes", "attack-the-premise"],
        "docs-writer": ["minimize-reader-load"],
    }

    def principles(self, path):
        """The names on the `Principles:` line of a card, which must stand under Standards and before Done."""
        text = path.read_text(encoding="utf-8")
        standards = re.search(r"^## Standards\n(.*?)^## Done\n", text, re.M | re.S)
        self.assertTrue(standards, path)
        lines = re.findall(r"^Principles: (.*)$", standards.group(1), re.M)
        self.assertEqual(len(lines), 1, f"{path.relative_to(ROOT)}: one Principles line under Standards")
        return lines[0]

    def test_the_reference_has_the_section_the_install_command_and_the_credit_line_points_to_it(self):
        readme = REFERENCE.read_text(encoding="utf-8")
        section = re.search(r"^## Works with pstack\n(.*?)^## ", readme, re.M | re.S)
        self.assertTrue(section)
        text = squash(section.group(1))
        self.assertIn("npx skills add backnotprop/pstack", section.group(1))
        self.assertIn("The kit covers process and guardrails", text)
        self.assertIn("The kit does not depend on pstack", text)
        self.assertIn("(see [Works with pstack](#works-with-pstack))", squash(readme))  # the credit line, which the Links check follows to the heading

    def test_gate_2_loads_the_principle_skills_that_fit_the_roles_in_play(self):
        gates = squash((ROOT / "skills" / "gates" / "SKILL.md").read_text(encoding="utf-8"))
        row = next(line for line in gates.split(" | ") if line.startswith("Load the walls"))
        self.assertIn("principle skills installed (for example pstack's `principle-*`), load the ones that fit the roles in play", row)
        self.assertIn("`Principles:` line", row)

    def test_every_role_card_has_a_principles_line_under_standards(self):
        template = self.principles(ROOT / "templates" / "roles" / "role-card.md")
        self.assertIn("the engineering principles this role applies", template)
        for card in sorted((ROOT / "examples" / "acme" / "docs" / "agents" / "roles").glob("*.md")):
            names = [name.strip() for name in self.principles(card).rstrip(".").split(",")]
            self.assertEqual(names, self.CARDS[card.stem], card.name)
            self.assertLessEqual(set(names), self.PRINCIPLES, card.name)
        self.assertEqual(sorted(path.stem for path in (ROOT / "examples" / "acme" / "docs" / "agents" / "roles").glob("*.md")), sorted(self.CARDS))
        orchestrator = [name.strip() for name in self.principles(ROOT / "templates" / "roles" / "orchestrator.md").rstrip(".").split(",")]
        self.assertTrue(orchestrator and set(orchestrator) <= self.PRINCIPLES, orchestrator)

    def test_the_principle_names_the_method_cites_are_pstack_names(self):
        gates = (ROOT / "skills" / "gates" / "SKILL.md").read_text(encoding="utf-8")
        cited = re.findall(r"\(pstack: ([a-z-]+)\)", gates)
        self.assertEqual(len(cited), 7)
        self.assertLessEqual(set(cited), self.PRINCIPLES)


class NamedRows(unittest.TestCase):
    def refusal(self):
        """The message `metrics log` refuses with while the pending task has an auto name, for the task name `auto <time>`."""
        with tempfile.TemporaryDirectory() as folder:
            state = pathlib.Path(folder)
            (state / local_state.PENDING).write_text(json.dumps({"task": "auto <time>", "start": "2026-10-29T11:00:00"}))
            with self.assertRaises(local_state.Refuse) as raised:
                metrics.log(state, state / "m.jsonl", "S", "new", "yes")
            self.assertEqual(raised.exception.code, 2)
            return str(raised.exception)

    def test_the_config_reference_quotes_the_refusal_of_the_code(self):
        config = squash((ROOT / "docs" / "config.md").read_text(encoding="utf-8"))
        self.assertIn(f"agent-steddy: refused: {squash(self.refusal())}", config)
        self.assertIn("exits 2", config)

    def test_the_skills_and_the_reference_say_that_the_task_name_is_required_while_it_is_an_auto_name(self):
        for relative, phrases in [
            ("skills/finish/SKILL.md", ["the command refuses without `--task`", "exits 2, writes nothing and keeps the clock"]),
            ("skills/gates/SKILL.md", ["`--task` names the row for what was done", "refuses with exit 2, writes nothing and keeps the clock"]),
            ("docs/reference.md", ["`--task` is required", "refuses (exit 2), writes nothing and keeps the clock"]),
        ]:
            text = squash((ROOT / relative).read_text(encoding="utf-8"))
            for phrase in phrases:
                self.assertIn(phrase, text, relative)

    def test_no_doc_logs_a_row_without_a_task_and_the_old_note_is_gone(self):
        docs = [*METHOD_DOCS, ROOT / "docs" / "config.md"]
        commands = [(path, match.group(0)) for path in docs for match in re.finditer(r"agent-steddy metrics log[^\n`|]*", path.read_text(encoding="utf-8"))]
        self.assertTrue(commands)
        for path, command in commands:
            self.assertTrue(command.strip() == "agent-steddy metrics log" or "--task" in command, f"{path.relative_to(ROOT)}: {command}")  # a bare mention names the command; any other line shows a full call
        sources = [*docs, *sorted((ROOT / "scripts").glob("*.py")), ROOT / "examples" / "acme" / "README.md"]
        for path in sources:
            self.assertNotIn("the task name is still the auto name", path.read_text(encoding="utf-8"), path.name)
            self.assertNotIn("a row still named", path.read_text(encoding="utf-8"), path.name)


class OpenClock(unittest.TestCase):
    def refusal(self):
        """The message `metrics log` refuses with for a named task whose clock ran 600 minutes, with that number written `<n>`."""
        now = dt.datetime(2026, 10, 29, 12, 0, 0)
        with tempfile.TemporaryDirectory() as folder:
            state = pathlib.Path(folder)
            (state / local_state.PENDING).write_text(json.dumps({"task": "t", "start": (now - dt.timedelta(minutes=600)).isoformat()}))
            with self.assertRaises(local_state.Refuse) as raised:
                metrics.log(state, state / "m.jsonl", "S", "new", "yes", now=now)
            self.assertEqual(raised.exception.code, 2)
            return str(raised.exception).replace("600", "<n>")

    def test_the_config_reference_states_the_line_quotes_the_refusal_and_the_list_and_names_the_median_columns(self):
        text = (ROOT / "docs" / "config.md").read_text(encoding="utf-8")
        config = squash(text)
        self.assertIn(f"`OPEN_CLOCK_MINUTES` = {metrics.OPEN_CLOCK_MINUTES} minutes", config)
        self.assertEqual(len(re.findall(r"^OPEN_CLOCK_MINUTES = ", (ROOT / "scripts" / "metrics.py").read_text(encoding="utf-8"), re.M)), 1)  # defined once, used by name
        self.assertIn(f"agent-steddy: refused: {squash(self.refusal())}", config)
        self.assertIn("exits 2", config)
        listed = metrics.open_clock_lines([{"date": "2026-10-13", "task": "fix the build", "minutes": 6928}], 8)
        self.assertEqual(len(listed), 3)
        self.assertIn("\n".join(listed[1:]), text)  # the heading and the line the section shows
        for header in ("med_min(S/M/L)", "med_prompt_min"):
            self.assertIn(header, metrics.task_table([], 8)[0])
            self.assertIn(f"`{header}`", config)
        self.assertNotIn("avg_min", config)

    def test_the_skills_and_the_reference_say_that_a_clock_over_the_line_needs_minutes(self):
        line = metrics.OPEN_CLOCK_MINUTES
        for relative, phrases in [
            ("skills/finish/SKILL.md", [f"When the clock has run more than {line} minutes", "refuses without `--minutes`: it exits 2, writes nothing and keeps the clock", "`--minutes <active minutes>`, your honest estimate"]),
            ("skills/gates/SKILL.md", [f"a clock that ran more than {line} minutes was left open over a break, so the command refuses it the same way", "`--minutes <active minutes>`",
                                       f"with the rows over {line} minutes listed below it as a clock left open", "median minutes by size"]),
            ("docs/reference.md", [f"a clock that ran more than {line} minutes, a working day: `--minutes <active minutes>` is then required", f"with the rows over {line} minutes listed below as a clock left open"]),
            ("docs/config.md", ["a `metrics log` without `--minutes` of a clock that ran more than a working day) exit 2"]),
        ]:
            text = squash((ROOT / relative).read_text(encoding="utf-8"))
            for phrase in phrases:
                self.assertIn(phrase, text, relative)


class HooksLiveCheck(unittest.TestCase):
    PLACEHOLDERS = {"mine": "<version>", "here": "<path>", "theirs": "<version>", "there": "<path>"}

    def prompt(self):
        """The setup prompt of the README: the text block under `Set it up with your agent`."""
        section = README.read_text(encoding="utf-8").split("## Set it up with your agent\n", 1)[1]
        return section.split("```text\n", 1)[1].split("```", 1)[0]

    def test_the_config_reference_quotes_the_warnings_the_selftest_lines_and_the_marker_age_of_the_code(self):
        config = squash((ROOT / "docs" / "config.md").read_text(encoding="utf-8"))
        texts = [session_marker.NO_MARKER, session_marker.OTHER_ROOT.format(**self.PLACEHOLDERS), session_marker.NOT_LIVE, session_marker.NOT_CHECKED,
                 session_marker.LIVE.format(theirs="<version>"), session_marker.OTHER_COPY.format(**self.PLACEHOLDERS)]
        for text in texts:
            self.assertIn(squash(text), config)
        self.assertIn(f"`MARKER_DAYS` = {session_marker.MARKER_DAYS} days", config)
        source = (ROOT / "scripts" / "session_marker.py").read_text(encoding="utf-8")
        for name in ("MARKER_DAYS", "NO_MARKER", "OTHER_ROOT", "NOT_CHECKED", "LIVE", "NOT_LIVE", "OTHER_COPY"):  # each number and text is defined once and used by name
            self.assertEqual(len(re.findall(rf"^{name} = ", source, re.M)), 1, name)

    def test_the_readme_prompt_limits_the_scope_proves_the_setup_in_a_new_session_and_fits_80_columns(self):
        prompt = self.prompt()
        self.assertLess(max(len(line) for line in prompt.splitlines()), 80)
        text = squash(prompt)
        self.assertIn("Change only .claude/, docs/agents/, CLAUDE.md and .gitignore, and ask me before you touch anything else.", text)
        proof = text.split("5. ", 1)[1]
        self.assertIn("start a new Claude Code session", proof)
        self.assertIn("`agent-steddy metrics selftest` must say the hooks are live", proof)
        self.assertIn("`git stash` must come back denied by the hook", proof)
        self.assertLess(text.index("4. Commit"), text.index("5. "))  # the proof comes after the commit, in the new session
        self.assertIn("Hooks load only when a session starts", squash(README.read_text(encoding="utf-8").split("## Install", 1)[1].split("## Set it up", 1)[0]))

    def test_the_state_files_the_hooks_table_and_the_template_readme_name_the_markers(self):
        config = (ROOT / "docs" / "config.md").read_text(encoding="utf-8")
        self.assertIn("- `sessions/` holds one marker per Claude Code session whose hooks run", config)
        self.assertIn("session markers", README.read_text(encoding="utf-8"))
        row = next(line for line in squash(REFERENCE.read_text(encoding="utf-8")).split(" | ") if line.startswith("Logs how long the command took"))
        self.assertIn("writes the marker of the session", row)
        self.assertIn("hooks load only when a session starts", squash((ROOT / "templates" / "README.md").read_text(encoding="utf-8")))


class RuleIds(unittest.TestCase):
    def test_every_rule_id_mentioned_is_in_the_reference_table(self):
        listed = {rule_id for rule_id, _ in rule_table()}
        self.assertTrue(listed)
        # a mention is a backticked id that starts like a built-in rule, as in `git-stash` or `[git-stash] Never ...`
        families = sorted({rule_id.split("-")[0] for rule_id in listed})
        mention = re.compile(r"`\[?((?:%s)-[a-z-]+)" % "|".join(families))
        mentions = [(path, rule_id) for path in METHOD_DOCS for rule_id in mention.findall(path.read_text(encoding="utf-8"))]
        self.assertTrue(mentions)
        for path, rule_id in mentions:
            self.assertIn(rule_id, listed, f"{path.relative_to(ROOT)}: {rule_id}")


class Links(unittest.TestCase):
    LINK = re.compile(r"\]\(([^)\s]+)\)")
    HEADING = re.compile(r"^#{1,6} +(.+?) *$", re.M)

    def test_every_relative_link_resolves_and_its_anchor_exists(self):
        links = 0
        for path in METHOD_DOCS:
            for target in self.LINK.findall(path.read_text(encoding="utf-8")):
                if re.match(r"[a-z]+:", target):
                    continue  # https, mailto and the like are not checked here
                links += 1
                file_part, _, anchor = target.partition("#")
                dest = (path.parent / file_part).resolve() if file_part else path
                self.assertTrue(dest.exists(), f"{path.relative_to(ROOT)}: {target}")
                if anchor and dest.suffix == ".md":
                    headings = {slug(title) for title in self.HEADING.findall(dest.read_text(encoding="utf-8"))}
                    self.assertIn(anchor, headings, f"{path.relative_to(ROOT)}: {target}")
        self.assertTrue(links)


if __name__ == "__main__":
    unittest.main()
