import contextlib
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import lessons  # noqa: E402


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




if __name__ == "__main__":
    unittest.main()
