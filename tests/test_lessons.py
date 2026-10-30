import contextlib
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import lessons  # noqa: E402
import project_config  # noqa: E402
from local_state import Refuse  # noqa: E402

CONFIG = project_config.DEFAULTS


@contextlib.contextmanager
def project():
    with tempfile.TemporaryDirectory() as tmp:
        yield pathlib.Path(tmp).resolve()


def lessons_text(*entries):
    """A lessons file: the template's format block, then one entry per (date, task, roles, rule line), newest first."""
    out = ["# Lessons", "", "```text", "## <date> - <task> - roles: <a, b>", "- Rule [<key>]: <rule>", "```", ""]
    for date, task, roles, rule in entries:
        out += [f"## {date} - {task} - roles: {roles}", "- Worked: w", "- Exposed: e", rule, ""]
    return "\n".join(out)


def put(root, relative, text):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def snapshot(root):
    return {str(path.relative_to(root)): path.read_text() for path in sorted(root.rglob("*")) if path.is_file()}


def sections(lines):
    """title -> the lines below it, from the report's blank-line separated sections."""
    found, current = {}, None
    for line in lines:
        if not line:
            current = None
        elif current is None:
            current = found.setdefault(line.split(":")[0], [])
        else:
            current.append(line)
    return found


CARD = """# Role: Web

Mission: build pages.

## Standards

- Stay in web/.

## Pitfalls

- An old lesson (lessons: 2026-01-01, 2026-01-02)
  with a second line
- Check the output twice

## Tools

- rg
"""

TWICE = (
    ("2026-10-30", "task b", "web, docs", "- Rule [commit-by-path]: commit each file by path"),
    ("2026-10-28", "task a", "web", "- Rule [commit-by-path]: commit by path, never git add all"),
)


class Parse(unittest.TestCase):
    def test_entries_and_their_fields(self):
        text = lessons_text(
            ("2026-10-30", "a task - with a dash", "web, docs", "- Rule [commit-by-path]: commit by path"),
            ("2026-10-29", "old", "web", "- Rule: an old rule without a key"),
            ("2026-10-28", "done", "web", "- Rule [clear-cache]: clear it [promoted -> docs/agents/roles/web.md]"),
            ("2026-10-27", "nothing", "web", "- Rule: none"),
        )
        got = [(e.date, e.task, e.roles, e.key, e.rule, e.promoted) for e in lessons.parse(text)]
        self.assertEqual(got, [
            ("2026-10-30", "a task - with a dash", ["web", "docs"], "commit-by-path", "commit by path", None),
            ("2026-10-29", "old", ["web"], None, "an old rule without a key", None),
            ("2026-10-28", "done", ["web"], "clear-cache", "clear it", "docs/agents/roles/web.md"),
            ("2026-10-27", "nothing", ["web"], None, "none", None),
        ])

    def test_what_is_not_an_entry_is_skipped(self):
        cases = {
            "a heading inside a fence": "# L\n\n```\n## 2026-01-01 - x - roles: a\n- Rule [k]: r\n```\n",
            "an entry with no rule line": "## 2026-01-01 - x - roles: a\n- Worked: w\n- Exposed: e\n",
            "a rule line below a heading that is not an entry": "## Notes\n- Rule [k]: r\n",
            "a rule line that is not an exact Rule line": "## 2026-01-01 - x - roles: a\n- Rule [Bad_Key]: r\n- Rules: r\n",
            "an empty file": "",
        }
        for name, text in cases.items():
            self.assertEqual(lessons.parse(text), [], name)

    def test_a_heading_without_roles_and_a_rule_after_other_lines_still_parse(self):
        entries = lessons.parse("## 2026-01-01 - plain task\n- Worked: w\n- Exposed: e\n- Rule [k]: r\n\n## Notes\n- Rule [other]: not an entry\n")
        self.assertEqual([(e.task, e.roles, e.key) for e in entries], [("plain task", [], "k")])

    def test_the_line_index_points_at_the_rule_line(self):
        text = lessons_text(*TWICE)
        lines = text.split("\n")
        for entry in lessons.parse(text):
            self.assertTrue(lines[entry.line].startswith("- Rule [commit-by-path]"), entry)

    def test_a_missing_or_unreadable_file_reads_as_no_entries(self):
        with project() as root:
            self.assertEqual(lessons.read(root / "nope.md"), [])
            (root / "bad.md").write_bytes(b"\xff\xfe## x")
            self.assertEqual(lessons.read(root / "bad.md"), [])
            self.assertEqual(lessons.read(root), [])  # a folder


class Due(unittest.TestCase):
    def entries(self, *rows):
        return lessons.parse(lessons_text(*rows))

    def test_a_key_seen_twice_is_due_and_the_most_seen_come_first_then_by_key(self):
        rows = [("2026-10-%02d" % day, f"t{day}", "web", f"- Rule [{key}]: r") for day, key in enumerate(["b", "a", "c", "c", "b", "c", "once"], start=1)]
        self.assertEqual([(key, len(group)) for key, group in lessons.due(self.entries(*rows))], [("c", 3), ("b", 2)])

    def test_a_promoted_key_and_unkeyed_lines_are_not_due(self):
        marked = " [promoted -> docs/agents/roles/web.md]"
        entries = self.entries(("2026-10-03", "c", "web", "- Rule [k]: r"), ("2026-10-02", "b", "web", "- Rule [k]: r" + marked), ("2026-10-01", "a", "web", "- Rule [k]: r"),
                               ("2026-10-03", "d", "web", "- Rule: same"), ("2026-10-02", "e", "web", "- Rule: same"), ("2026-10-02", "f", "web", "- Rule: none"), ("2026-10-01", "g", "web", "- Rule: none"))
        self.assertEqual(lessons.due(entries), [])

    def test_a_group_is_newest_first_by_date_then_by_place_in_the_file(self):
        rows = [("2026-10-02", "first in file", "web", "- Rule [k]: one"), ("2026-10-02", "second in file", "web", "- Rule [k]: two"), ("2026-10-03", "newest", "web", "- Rule [k]: three"), ("2026-10-01", "oldest", "web", "- Rule [k]: four")]
        group = lessons.groups(self.entries(*rows))["k"]
        self.assertEqual([entry.task for entry in group], ["newest", "first in file", "second in file", "oldest"])

    def test_the_nudge_line_names_at_most_three_keys(self):
        cases = {
            1: "Learning loop: 1 rule(s) seen twice and not promoted (k1); run agent-steddy lessons check.",
            3: "Learning loop: 3 rule(s) seen twice and not promoted (k1, k2, k3); run agent-steddy lessons check.",
            4: "Learning loop: 4 rule(s) seen twice and not promoted (k1, k2, k3, ...); run agent-steddy lessons check.",
        }
        for count, line in cases.items():
            with project() as root:
                rows = [(f"2026-10-0{n}", f"t{k}{n}", "web", f"- Rule [k{k}]: r") for k in range(1, count + 1) for n in (1, 2)]
                path = put(root, "l.md", lessons_text(*rows))
                self.assertEqual(lessons.nudge(path), line, count)

    def test_the_nudge_is_empty_when_nothing_is_due_or_the_file_is_missing(self):
        with project() as root:
            self.assertEqual(lessons.nudge(root / "none.md"), "")
            self.assertEqual(lessons.nudge(put(root, "l.md", lessons_text(TWICE[0]))), "")

    def test_the_repeat_notice_counts_the_key_and_suggests_the_roles_most_common_first(self):
        with project() as root:
            rows = [("2026-10-03", "c", "docs", "- Rule [k]: r"), ("2026-10-02", "b", "web, docs", "- Rule [k]: r"), ("2026-10-01", "a", "docs, web, ops", "- Rule [k]: r"), ("2026-10-01", "z", "web", "- Rule [other]: r")]
            path = put(root, "l.md", lessons_text(*rows))
            self.assertEqual(lessons.repeat_notice(path, "k"), [
                "k is now seen 3 times",
                "agent-steddy lessons promote k --to docs",
                "roles in these entries, most common first: docs (3), web (2), ops (1)",
                "a rule about safety, data or money goes --to walls instead",
            ])
            self.assertEqual(lessons.repeat_notice(path, "other"), [])  # seen once
            self.assertEqual(lessons.repeat_notice(path, "unknown"), [])

    def test_the_repeat_notice_stays_quiet_for_a_promoted_key_and_a_key_with_no_roles(self):
        with project() as root:
            path = put(root, "l.md", lessons_text(("2026-10-02", "b", "web", "- Rule [k]: r"), ("2026-10-01", "a", "web", "- Rule [k]: r [promoted -> docs/agents/roles/web.md]")))
            self.assertEqual(lessons.repeat_notice(path, "k"), [])
            path = put(root, "l2.md", "## 2026-10-02 - b\n- Rule [k]: r\n\n## 2026-10-01 - a\n- Rule [k]: r\n")
            self.assertEqual(lessons.repeat_notice(path, "k")[:2], ["k is now seen 2 times", "agent-steddy lessons promote k --to <role>"])


class Slugs(unittest.TestCase):
    def test_a_suggested_key_is_a_short_valid_slug(self):
        cases = {
            "Commit by path, never git add all": "commit-by-path-never",
            "The cache must be cleared": "cache-must-cleared",
            "x" * 60: "x" * 40,
            "internationalization localization documentation synchronization": "internationalization-localization",
            "!!!": "rule",
            "": "rule",
        }
        for text, key in cases.items():
            self.assertEqual(lessons.suggest_key(text), key, text)
            lessons.valid_key(lessons.suggest_key(text))

    def test_similarity_is_symmetric_from_zero_to_one(self):
        self.assertEqual(lessons.similarity("a b c", "a b c"), 1.0)
        self.assertEqual(lessons.similarity("", "a"), 0.0)
        self.assertEqual(lessons.similarity("a", "..."), 0.0)
        pairs = [("Run the tests before commit", "Run the tests before you commit"), ("commit by path", "clear the cache")]
        for a, b in pairs:
            self.assertEqual(lessons.similarity(a, b), lessons.similarity(b, a))
        near, far = (lessons.similarity(*pair) for pair in pairs)
        self.assertGreater(near, lessons.ALIKE)
        self.assertLess(far, lessons.ALIKE)


class Check(unittest.TestCase):
    def run_check(self, root):
        return lessons.check(root, CONFIG)

    def test_a_project_with_no_records_says_none_three_times(self):
        with project() as root:
            found = sections(self.run_check(root))
            self.assertEqual(list(found), ["Due", "Unkeyed", "Cards to prune"])
            self.assertEqual(list(found.values()), [["  none"]] * 3)

    def test_due_lists_the_dates_the_tasks_the_roles_and_the_command(self):
        with project() as root:
            put(root, "docs/agents/lessons.md", lessons_text(*TWICE, ("2026-10-27", "other", "web", "- Rule [once]: r")))
            due = sections(self.run_check(root))["Due"]
            self.assertEqual(due, [
                "  commit-by-path: seen 2 times (2026-10-28, 2026-10-30)",
                "    tasks: task b; task a",
                "    agent-steddy lessons promote commit-by-path --to web",
                "    roles in these entries, most common first: web (2), docs (1)",
                "    a rule about safety, data or money goes --to walls instead",
            ])

    def test_unkeyed_lines_get_a_suggested_key_and_the_ones_that_look_alike_are_paired(self):
        rows = [
            ("2026-10-05", "five", "web", "- Rule: Run the tests before you commit"),
            ("2026-10-04", "four", "web", "- Rule: none"),
            ("2026-10-03", "three", "web", "- Rule: Run the tests before commit"),
            ("2026-10-02", "two", "web", "- Rule [kept]: has a key"),
            ("2026-10-01", "one", "web", "- Rule: Clear the CI cache"),
        ]
        with project() as root:
            put(root, "docs/agents/lessons.md", lessons_text(*rows))
            unkeyed = sections(self.run_check(root))["Unkeyed"]
            self.assertEqual(unkeyed[0], "  2026-10-05 - five: Run the tests before you commit")
            self.assertEqual(unkeyed[1], "    suggested key: run-tests-before-commit")
            self.assertEqual(sum(line.startswith("    suggested key:") for line in unkeyed), 3)  # none and keyed lines are left out
            alike = [line for line in unkeyed if "looks alike" in line]
            self.assertEqual(len(alike), 1, unkeyed)
            self.assertIn("2026-10-05 - five and 2026-10-03 - three; give both the same key", alike[0])

    def test_a_hand_promoted_unkeyed_line_is_not_listed(self):
        with project() as root:
            put(root, "docs/agents/lessons.md", lessons_text(("2026-10-01", "one", "web", "- Rule: old rule [promoted -> docs/agents/roles/web.md]")))
            self.assertEqual(sections(self.run_check(root))["Unkeyed"], ["  none"])

    def test_a_card_with_more_than_twelve_pitfalls_is_listed_and_one_with_twelve_is_not(self):
        words = "apple river stone cloud forest garden window button hammer ladder pencil rocket silver tunnel violet wagon yellow zebra anchor basket candle dragon engine falcon glacier harbor island jungle kettle lantern marble needle orchard pepper quartz saddle temple umbrella valley whistle".split()

        def card(count):
            bullets = "".join(f"- {words[3 * n]} {words[3 * n + 1]} {words[3 * n + 2]}\n" for n in range(count))
            return CARD.split("## Pitfalls")[0] + "## Pitfalls\n\n" + bullets + "\n## Tools\n\n- rg\n"
        with project() as root:
            put(root, "docs/agents/roles/big.md", card(13))
            put(root, "docs/agents/roles/ok.md", card(12))
            prune = sections(self.run_check(root))["Cards to prune"]
            self.assertEqual(prune, ["  big: 13 pitfalls, more than 12; merge duplicates and drop stale ones"])

    def test_pitfalls_that_look_alike_in_one_card_are_paired_and_placeholders_and_nested_lines_are_not_counted(self):
        text = CARD.replace("- Check the output twice\n", "- Check the output twice\n- Never run git stash on a tree that agents share (lessons: 2026-10-01, 2026-10-02)\n- Do not run git stash on a tree that agents share\n- None recorded yet; the second time a mistake happens, add it here as a rule.\n- <a lesson seen twice: what happened, and the rule it gives>.\n  - a nested bullet that is no pitfall\n")
        self.assertEqual(len(lessons.pitfall_texts(text)), 4)
        with project() as root:
            put(root, "docs/agents/roles/web.md", text)
            put(root, "docs/agents/roles/docs.md", CARD)
            prune = sections(self.run_check(root))["Cards to prune"]
            self.assertEqual(len(prune), 1, prune)
            self.assertTrue(prune[0].startswith('  web: "Never run git stash on a tree that agents share" looks like "Do not run git stash on a tree that agents share" ('), prune[0])

    def test_a_card_with_no_pitfalls_section_and_a_missing_roles_folder_are_fine(self):
        with project() as root:
            put(root, "docs/agents/roles/bare.md", "# Role: Bare\n\nMission: x.\n")
            self.assertEqual(sections(self.run_check(root))["Cards to prune"], ["  none"])
        with project() as root:
            put(root, "docs/agents/roles", "a file where the folder should be")
            self.assertEqual(sections(self.run_check(root))["Cards to prune"], ["  none"])

    def test_the_paths_come_from_the_config(self):
        config = {**CONFIG, "records": {**CONFIG["records"], "lessons": "notes/l.md", "roles": "notes/cards"}}
        with project() as root:
            put(root, "notes/l.md", lessons_text(*TWICE))
            put(root, "notes/cards/web.md", CARD)
            self.assertEqual(len(sections(lessons.check(root, config))["Due"]), 5)

    def test_more_than_ten_pairs_are_cut_with_a_count(self):
        rows = [("2026-10-%02d" % n, f"t{n}", "web", "- Rule: run the tests before you commit") for n in range(1, 8)]  # 21 pairs
        with project() as root:
            put(root, "docs/agents/lessons.md", lessons_text(*rows))
            unkeyed = sections(self.run_check(root))["Unkeyed"]
            self.assertEqual(sum("looks alike" in line for line in unkeyed), 10)
            self.assertEqual(unkeyed[-1], "  ... and 11 more pairs")


class Promote(unittest.TestCase):
    def setup(self, root, card=CARD, rows=TWICE):
        put(root, "docs/agents/lessons.md", lessons_text(*rows))
        if card is not None:
            put(root, "docs/agents/roles/web.md", card)

    def test_a_rule_goes_to_the_end_of_the_pitfalls_and_every_rule_line_with_the_key_is_marked(self):
        with project() as root:
            self.setup(root)
            put(root, "docs/agents/lessons.md", lessons_text(*TWICE, ("2026-10-27", "other", "web", "- Rule [other-key]: not this one")))
            said = lessons.promote(root, CONFIG, "commit-by-path", "web")
            self.assertEqual(said, [
                "added to docs/agents/roles/web.md: - commit each file by path (lessons: 2026-10-28, 2026-10-30)",
                "marked 2 Rule lines of commit-by-path in docs/agents/lessons.md as [promoted -> docs/agents/roles/web.md]",
            ])
            self.assertEqual((root / "docs/agents/roles/web.md").read_text(), CARD.replace("- Check the output twice\n", "- Check the output twice\n- commit each file by path (lessons: 2026-10-28, 2026-10-30)\n"))
            marked = (root / "docs/agents/lessons.md").read_text()
            self.assertIn("- Rule [commit-by-path]: commit each file by path [promoted -> docs/agents/roles/web.md]\n", marked)
            self.assertIn("- Rule [commit-by-path]: commit by path, never git add all [promoted -> docs/agents/roles/web.md]\n", marked)
            self.assertIn("- Rule [other-key]: not this one\n", marked)
            self.assertEqual(marked.count("[promoted ->"), 2)
            self.assertEqual(lessons.due(lessons.parse(marked)), [])

    def test_the_newest_rule_text_is_the_default_and_text_replaces_it(self):
        with project() as root:
            self.setup(root)
            lessons.promote(root, CONFIG, "commit-by-path", "web", text="  Commit by path only.  ")
            self.assertIn("- Commit by path only. (lessons: 2026-10-28, 2026-10-30)\n", (root / "docs/agents/roles/web.md").read_text())

    def test_a_placeholder_bullet_is_replaced_and_the_rest_of_the_card_is_kept(self):
        for placeholder in ["- None recorded yet; the second time a mistake happens, add it here as a rule.", "- <a lesson seen twice: what happened, and the rule it gives>."]:
            with project() as root:
                card = CARD.split("## Pitfalls")[0] + f"## Pitfalls\n\n{placeholder}\n\n## Tools\n\n- rg\n"
                self.setup(root, card)
                lessons.promote(root, CONFIG, "commit-by-path", "web")
                self.assertEqual((root / "docs/agents/roles/web.md").read_text(), card.replace(placeholder, "- commit each file by path (lessons: 2026-10-28, 2026-10-30)"))

    def test_the_pitfalls_section_is_found_at_the_end_of_a_card_with_or_without_a_final_newline(self):
        for tail in ["", "\n"]:
            with project() as root:
                self.setup(root, "# Role: Web\n\n## Pitfalls\n\n- one" + tail)
                lessons.promote(root, CONFIG, "commit-by-path", "web")
                self.assertEqual((root / "docs/agents/roles/web.md").read_text(), "# Role: Web\n\n## Pitfalls\n\n- one\n- commit each file by path (lessons: 2026-10-28, 2026-10-30)\n", repr(tail))

    def test_an_empty_pitfalls_section_gets_its_first_bullet_below_a_blank_line(self):
        for card in ["# R\n\n## Pitfalls\n", "# R\n\n## Pitfalls\n\n## Tools\n\n- rg\n"]:
            with project() as root:
                self.setup(root, card)
                lessons.promote(root, CONFIG, "commit-by-path", "web")
                text = (root / "docs/agents/roles/web.md").read_text()
                self.assertIn("## Pitfalls\n\n- commit each file by path (lessons: 2026-10-28, 2026-10-30)\n", text)
                self.assertTrue(text.endswith("- rg\n") or text.endswith("2026-10-30)\n"))
                self.assertEqual(text.count("## Pitfalls"), 1)

    def test_a_card_with_no_pitfalls_section_gets_one_at_the_end(self):
        for card in ["# Role: Web\n\n## Tools\n\n- rg\n", "# Role: Web\n\n## Tools\n\n- rg", "# Role: Web\n\n## Tools\n\n- rg\n\n\n"]:
            with project() as root:
                self.setup(root, card)
                lessons.promote(root, CONFIG, "commit-by-path", "web")
                self.assertEqual((root / "docs/agents/roles/web.md").read_text(), "# Role: Web\n\n## Tools\n\n- rg\n\n## Pitfalls\n\n- commit each file by path (lessons: 2026-10-28, 2026-10-30)\n", repr(card))

    def test_a_pitfalls_heading_inside_a_code_fence_is_not_the_section(self):
        with project() as root:
            self.setup(root, "# R\n\n```\n## Pitfalls\n```\n")
            lessons.promote(root, CONFIG, "commit-by-path", "web")
            self.assertTrue((root / "docs/agents/roles/web.md").read_text().endswith("```\n\n## Pitfalls\n\n- commit each file by path (lessons: 2026-10-28, 2026-10-30)\n"))

    def test_walls_creates_the_file_with_a_header_and_the_next_rule_goes_below(self):
        with project() as root:
            self.setup(root, card=None, rows=[*TWICE, ("2026-10-27", "x", "web", "- Rule [k2]: r2"), ("2026-10-26", "y", "web", "- Rule [k2]: r2")])
            said = lessons.promote(root, CONFIG, "commit-by-path", "walls")
            self.assertEqual(said[0], "added to docs/agents/walls.md: - commit each file by path (lessons: 2026-10-28, 2026-10-30)")
            walls = (root / "docs/agents/walls.md").read_text()
            self.assertTrue(walls.startswith("# Walls\n\n"), walls)
            self.assertIn("Every role reads this file at gate 2", walls)
            self.assertTrue(walls.endswith("\n\n- commit each file by path (lessons: 2026-10-28, 2026-10-30)\n"), repr(walls))
            self.assertIn("[promoted -> docs/agents/walls.md]", (root / "docs/agents/lessons.md").read_text())
            lessons.promote(root, CONFIG, "k2", "walls")
            self.assertEqual((root / "docs/agents/walls.md").read_text().count("# Walls"), 1)
            self.assertEqual((root / "docs/agents/walls.md").read_text().splitlines()[-2:], ["- commit each file by path (lessons: 2026-10-28, 2026-10-30)", "- r2 (lessons: 2026-10-26, 2026-10-27)"])

    def test_an_existing_walls_file_is_kept_whether_or_not_it_ends_with_a_newline(self):
        for original in ["# My walls\n\n- one\n", "# My walls\n\n- one"]:
            with project() as root:
                self.setup(root, card=None)
                put(root, "docs/agents/walls.md", original)
                lessons.promote(root, CONFIG, "commit-by-path", "walls")
                self.assertEqual((root / "docs/agents/walls.md").read_text(), "# My walls\n\n- one\n- commit each file by path (lessons: 2026-10-28, 2026-10-30)\n", original)

    def test_the_config_names_the_cards_the_walls_and_the_lessons(self):
        config = {**CONFIG, "records": {**CONFIG["records"], "lessons": "notes/l.md", "roles": "notes/cards", "walls": "notes/w.md"}}
        with project() as root:
            put(root, "notes/l.md", lessons_text(*TWICE))
            put(root, "notes/cards/web.md", CARD)
            lessons.promote(root, config, "commit-by-path", "web")
            self.assertIn("[promoted -> notes/cards/web.md]", (root / "notes/l.md").read_text())
            self.assertIn("- commit each file by path", (root / "notes/cards/web.md").read_text())
        with project() as root:
            put(root, "notes/l.md", lessons_text(*TWICE))
            lessons.promote(root, config, "commit-by-path", "walls")
            self.assertTrue((root / "notes/w.md").is_file())
            self.assertIn("[promoted -> notes/w.md]", (root / "notes/l.md").read_text())

    def test_a_key_seen_once_needs_force(self):
        with project() as root:
            self.setup(root, rows=[TWICE[0]])
            before = snapshot(root)
            with self.assertRaises(Refuse) as caught:
                lessons.promote(root, CONFIG, "commit-by-path", "web")
            self.assertEqual(caught.exception.code, 2)
            self.assertIn("seen 1 time, fewer than 2", str(caught.exception))
            self.assertIn("--force", str(caught.exception))
            self.assertEqual(snapshot(root), before)
            said = lessons.promote(root, CONFIG, "commit-by-path", "web", force=True)
            self.assertIn("(lessons: 2026-10-30)", said[0])
            self.assertIn("marked 1 Rule line of commit-by-path", said[1])

    def test_every_refusal_exits_2_and_changes_nothing(self):
        marked = " [promoted -> docs/agents/roles/docs.md]"
        cases = [
            ("an unknown key", TWICE, "nope", "web", None, "no rule has the key 'nope'"),
            ("a key with no entry that carries it", [("2026-10-01", "a", "web", "- Rule: unkeyed")], "unkeyed", "web", None, "no rule has the key"),
            ("a promoted key", [("2026-10-02", "b", "web", "- Rule [k]: r"), ("2026-10-01", "a", "web", "- Rule [k]: r" + marked)], "k", "web", None, "already promoted: docs/agents/roles/docs.md"),
            ("a role with no card", TWICE, "commit-by-path", "ops", None, "docs/agents/roles/ops.md does not exist; copy templates/roles/role-card.md from the plugin"),
            ("a role that is not a name", TWICE, "commit-by-path", "../web", None, "bad target"),
            ("a role that is empty", TWICE, "commit-by-path", "", None, "bad target"),
            ("an empty text", TWICE, "commit-by-path", "web", "  ", "single line that is not empty"),
            ("a two line text", TWICE, "commit-by-path", "web", "a\nb", "single line that is not empty"),
            ("a text with the marker", TWICE, "commit-by-path", "web", "x [promoted -> y]", "must not contain"),
        ]
        for name, rows, key, to, text, reason in cases:
            with project() as root:
                self.setup(root, rows=rows)
                before = snapshot(root)
                with self.assertRaises(Refuse, msg=name) as caught:
                    lessons.promote(root, CONFIG, key, to, text=text)
                self.assertEqual(caught.exception.code, 2, name)
                self.assertIn(reason, str(caught.exception), name)
                self.assertEqual(snapshot(root), before, name)

    def test_force_does_not_lift_the_other_refusals(self):
        with project() as root:
            self.setup(root)
            for key, to in [("nope", "web"), ("commit-by-path", "ops")]:
                with self.assertRaises(Refuse):
                    lessons.promote(root, CONFIG, key, to, force=True)

    def test_walls_needs_no_card_and_a_missing_lessons_file_is_an_unknown_key(self):
        with project() as root:
            with self.assertRaises(Refuse) as caught:
                lessons.promote(root, CONFIG, "k", "walls")
            self.assertIn("no rule has the key", str(caught.exception))
            self.assertFalse((root / "docs").exists())

    def test_after_a_promotion_nothing_is_due_and_a_second_promotion_is_refused(self):
        with project() as root:
            self.setup(root)
            lessons.promote(root, CONFIG, "commit-by-path", "web")
            path = root / "docs/agents/lessons.md"
            self.assertEqual(lessons.nudge(path), "")
            self.assertEqual(lessons.repeat_notice(path, "commit-by-path"), [])
            self.assertEqual(sections(lessons.check(root, CONFIG))["Due"], ["  none"])
            with self.assertRaises(Refuse):
                lessons.promote(root, CONFIG, "commit-by-path", "walls")


if __name__ == "__main__":
    unittest.main()
