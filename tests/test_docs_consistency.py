"""The docs that teach the method (the skills, the templates and the README) must agree with the code they name.

Four checks: every skill has a name that matches its folder and a description, and every agent template has a name, a description and a model;
every `agent-steddy <group> <sub>` names a subcommand of scripts/cli.py;
every backticked built-in rule id is listed in the README table;
every relative link resolves, and its #anchor exists when the target is a Markdown file.
"""

import argparse
import pathlib
import re
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import cli  # noqa: E402

README = ROOT / "README.md"
METHOD_DOCS = sorted([README, *ROOT.glob("skills/**/*.md"), *ROOT.glob("templates/**/*.md")])


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


def rule_table():
    """The rule ids and their decisions that the README's built-in rule table lists."""
    return re.findall(r"^\| `([a-z-]+)` \| (deny|ask) \|", README.read_text(encoding="utf-8"), re.M)


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


class RuleIds(unittest.TestCase):
    def test_every_rule_id_mentioned_is_in_the_readme_table(self):
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
