import contextlib
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import lessons  # noqa: E402
import record  # noqa: E402
from hook_runner import git, make_repo  # noqa: E402
from local_state import Refuse  # noqa: E402


@contextlib.contextmanager
def folder():
    with tempfile.TemporaryDirectory() as tmp:
        yield pathlib.Path(tmp).resolve()


class Decision(unittest.TestCase):
    def test_a_missing_file_is_created_with_a_header_and_the_folder_too(self):
        with folder() as root:
            path = root / "docs" / "agents" / "decisions.md"
            self.assertEqual(record.decision(path, "app", "keep the sync queue local - the owner asked"), "- [app] keep the sync queue local - the owner asked")
            text = path.read_text()
            self.assertTrue(text.startswith("# Decisions\n"), text)
            self.assertTrue(text.endswith("\n\n- [app] keep the sync queue local - the owner asked\n"), repr(text))

    def test_the_next_decision_goes_below_the_last_line(self):
        with folder() as root:
            path = root / "decisions.md"
            record.decision(path, "app", "first")
            record.decision(path, "web", "second")
            self.assertEqual(path.read_text().splitlines()[-2:], ["- [app] first", "- [web] second"])
            self.assertEqual(path.read_text().count("# Decisions"), 1)

    def test_an_existing_file_is_kept_whether_or_not_it_ends_with_a_newline(self):
        with folder() as root:
            for original in ["# Mine\n\n- [a] old\n", "# Mine\n\n- [a] old"]:
                path = root / "d.md"
                path.write_text(original)
                record.decision(path, "b", "new")
                self.assertEqual(path.read_text(), "# Mine\n\n- [a] old\n- [b] new\n", original)

    def test_an_empty_area_or_text_a_second_line_or_a_bad_tag_is_refused_and_nothing_is_written(self):
        with folder() as root:
            path = root / "d.md"
            for area, text in [("", "x"), ("app", ""), ("  ", "x"), ("app", "a\nb"), ("a\nb", "x"), ("bad area!", "x"), ("[x]", "x"), ("-x", "x")]:
                with self.assertRaises(Refuse, msg=(area, text)):
                    record.decision(path, area, text)
            self.assertFalse(path.exists())

    def test_the_text_is_kept_as_written(self):
        with folder() as root:
            self.assertEqual(record.decision(root / "d.md", "api/v2", "  use `x` - na\u00efve, not y  "), "- [api/v2] use `x` - na\u00efve, not y")


class Lesson(unittest.TestCase):
    def entry(self, **extra):
        return {"task": "fix the build", "roles": "web, docs", "worked": "tests first", "exposed": "a stale cache", "rule": "clear the cache in CI", "key": "clear-the-cache", "today": "2026-10-29", **extra}

    def test_a_missing_file_is_created_from_the_template_with_the_entry_below_it(self):
        with folder() as root:
            path = root / "docs" / "agents" / "lessons.md"
            self.assertEqual(record.lesson(path, **self.entry()), "## 2026-10-29 - fix the build - roles: web, docs")
            lines = path.read_text().split("\n")
            self.assertEqual(lines[0], "# Lessons")
            self.assertEqual(lines.count("```text"), 1)
            at = lines.index("## 2026-10-29 - fix the build - roles: web, docs")
            self.assertGreater(at, lines.index("```"))  # below the format block, not inside it
            self.assertEqual(lines[at + 1:at + 5], ["- Worked: tests first", "- Exposed: a stale cache", "- Rule [clear-the-cache]: clear the cache in CI", ""])
            self.assertEqual(path.read_text()[-1], "\n")

    def test_the_newest_entry_goes_first(self):
        with folder() as root:
            path = root / "lessons.md"
            record.lesson(path, **self.entry(task="one", today="2026-10-01"))
            record.lesson(path, **self.entry(task="two", today="2026-10-02"))
            record.lesson(path, **self.entry(task="three", today="2026-10-03"))
            headings = [line for line in path.read_text().split("\n") if line.startswith("## ") and "roles:" in line and "<" not in line]
            self.assertEqual([h.split(" - ")[1] for h in headings], ["three", "two", "one"])
            self.assertEqual(path.read_text().count("## <date>"), 1)  # the format example in the template stays alone

    def test_an_entry_goes_above_the_first_heading_outside_a_code_fence(self):
        with folder() as root:
            path = root / "lessons.md"
            path.write_text("# My lessons\n\n```\n## example heading\n```\n\n## 2026-01-01 - old - roles: x\n- Worked: a\n")
            record.lesson(path, **self.entry())
            lines = path.read_text().split("\n")
            self.assertLess(lines.index("## 2026-10-29 - fix the build - roles: web, docs"), lines.index("## 2026-01-01 - old - roles: x"))
            self.assertLess(lines.index("```"), lines.index("## 2026-10-29 - fix the build - roles: web, docs"))
            self.assertEqual(lines[-2:], ["- Worked: a", ""])

    def test_a_file_with_no_entry_gets_the_entry_at_the_end(self):
        with folder() as root:
            for original in ["# My lessons\n", "# My lessons", "# My lessons\n\n\n"]:
                path = root / "lessons.md"
                path.write_text(original)
                record.lesson(path, **self.entry())
                self.assertEqual(path.read_text(), "# My lessons\n\n## 2026-10-29 - fix the build - roles: web, docs\n- Worked: tests first\n- Exposed: a stale cache\n- Rule [clear-the-cache]: clear the cache in CI\n", original)

    def test_the_date_defaults_to_today(self):
        import datetime
        with folder() as root:
            heading = record.lesson(root / "l.md", **self.entry(today=None))
            self.assertTrue(heading.startswith(f"## {datetime.date.today().isoformat()} - "), heading)

    def test_the_template_shows_the_key_and_what_a_repeat_does(self):
        self.assertIn("- Rule [<key>]: <the rule to keep, or none>", record.LESSONS_TEMPLATE)
        self.assertIn("agent-steddy lessons promote <key> --to <role>", record.LESSONS_TEMPLATE)
        self.assertEqual(lessons.parse(record.LESSONS_TEMPLATE), [])  # the format example is not an entry

    def test_a_rule_without_a_key_writes_nothing_and_exits_2_with_the_closest_rules_first(self):
        with folder() as root:
            path = root / "lessons.md"
            for task, rule, key, today in [("a", "commit by path and never stage everything", "commit-by-path", "2026-10-01"),
                                           ("b", "commit by path and never stage everything", "commit-by-path", "2026-10-02"),
                                           ("c", "clear the cache in CI before a build", "clear-the-cache", "2026-10-03"),
                                           ("d", "read the role card first", "role-card-first", "2026-10-04")]:
                record.lesson(path, **self.entry(task=task, rule=rule, key=key, today=today))
            before = path.read_text()
            with self.assertRaises(Refuse) as caught:
                record.lesson(path, **self.entry(rule="always commit by path, never git add all", key=None))
            self.assertEqual(caught.exception.code, 2)
            lines = str(caught.exception).splitlines()
            self.assertIn("nothing was written", lines[0])
            self.assertEqual(lines[1], "closest recorded rules:")
            self.assertTrue(lines[2].startswith("  commit-by-path (seen 2 times): commit by path"), lines[2])  # the most alike first, with its count and newest text
            self.assertEqual([line.split()[0] for line in lines[2:5]], ["commit-by-path", "clear-the-cache", "role-card-first"])
            self.assertEqual(lines[-1], "re-run with --key <existing> if it is the same rule, or --key <new-slug> if it is new")
            self.assertEqual(path.read_text(), before)

    def test_at_most_five_candidates_are_listed_and_ties_go_by_key(self):
        with folder() as root:
            path = root / "lessons.md"
            for key in ["zz", "bb", "aa", "dd", "cc", "ee", "ff"]:
                record.lesson(path, **self.entry(rule="same words every time", key=key))
            with self.assertRaises(Refuse) as caught:
                record.lesson(path, **self.entry(rule="something else", key=None))
            self.assertEqual([line.split()[0] for line in str(caught.exception).splitlines()[2:-1]], ["aa", "bb", "cc", "dd", "ee"])

    def test_with_no_recorded_rule_the_refusal_asks_for_a_new_slug(self):
        with folder() as root:
            with self.assertRaises(Refuse) as caught:
                record.lesson(root / "l.md", **self.entry(key=None))
            self.assertEqual(caught.exception.code, 2)
            self.assertIn("no keyed rule is recorded yet", str(caught.exception))
            self.assertIn("--key <new-slug>", str(caught.exception))
            self.assertFalse((root / "l.md").exists())

    def test_a_key_is_written_after_the_word_rule_and_an_old_line_without_one_still_parses(self):
        with folder() as root:
            path = root / "l.md"
            path.write_text("# L\n\n## 2026-01-01 - old - roles: web\n- Worked: a\n- Exposed: b\n- Rule: write it down\n")
            record.lesson(path, **self.entry())
            self.assertEqual([(e.task, e.key, e.rule) for e in lessons.read(path)], [("fix the build", "clear-the-cache", "clear the cache in CI"), ("old", None, "write it down")])

    def test_a_rule_of_none_needs_no_key_and_a_key_passed_with_it_is_dropped(self):
        with folder() as root:
            for number, (rule, key) in enumerate([("none", None), ("None", None), ("NONE", None), ("none", "some-key")]):
                path = root / f"l{number}.md"
                record.lesson(path, **self.entry(rule=rule, key=key))
                self.assertIn(f"\n- Rule: {rule}\n", path.read_text(), rule)
                self.assertEqual(lessons.read(path)[0].key, None)

    def test_a_bad_key_is_refused_with_exit_2_and_nothing_is_written(self):
        with folder() as root:
            path = root / "l.md"
            for key in ["", "Commit", "commit_by_path", "commit by path", "-commit", "commit-", "commit--path", "a" * 41, "caf\u00e9", "a/b", "[x]"]:
                with self.assertRaises(Refuse, msg=key) as caught:
                    record.lesson(path, **self.entry(key=key))
                self.assertEqual(caught.exception.code, 2, key)
            self.assertFalse(path.exists())
            for key in ["a", "commit-by-path", "x1-2y", "a" * 40]:
                record.lesson(path, **self.entry(key=key))

    def test_a_rule_that_carries_the_promoted_marker_is_refused(self):
        with folder() as root:
            with self.assertRaises(Refuse):
                record.lesson(root / "l.md", **self.entry(rule="do x [promoted -> docs/x.md]"))
            self.assertFalse((root / "l.md").exists())

    def test_missing_or_multi_line_fields_are_refused_and_nothing_is_written(self):
        with folder() as root:
            path = root / "l.md"
            bad = [{"task": ""}, {"roles": ""}, {"roles": " , "}, {"worked": "a\nb"}, {"exposed": ""}, {"rule": "  "}, {"task": "a\r\nb"}]
            for change in bad:
                with self.assertRaises(Refuse, msg=change):
                    record.lesson(path, **self.entry(**change))
            self.assertFalse(path.exists())


def repo_with_branch(root, files=("feature.txt",)):
    """A repo on main with one commit and a branch `feat/x` one commit ahead that adds `files`; the repo is left on main."""
    make_repo(root)
    git(root, "switch", "-q", "-c", "feat/x")
    for name in files:
        (root / name).write_text("x")
        git(root, "add", name)
    git(root, "commit", "-q", "-m", "work")
    git(root, "switch", "-q", "main")


def current(root):
    return git(root, "branch", "--show-current").strip()


def branches(root):
    return git(root, "branch", "--format=%(refname:short)").split()


class Finish(unittest.TestCase):
    def run_finish(self, root, config=None, branch="feat/x", **kwargs):
        said = []
        record.finish(root, branch, config if config is not None else {"verifyCommand": "true"}, say=said.append, **kwargs)
        return said

    def test_a_passing_verify_merges_deletes_the_branch_and_stays_on_the_working_branch(self):
        with folder() as root:
            repo_with_branch(root)
            tip = git(root, "rev-parse", "feat/x")
            said = self.run_finish(root, {"verifyCommand": "test -f feature.txt"})  # the file exists on the branch only: the proof ran on the branch
            self.assertEqual((current(root), branches(root)), ("main", ["main"]))
            self.assertEqual(git(root, "rev-parse", "main"), tip)
            self.assertTrue((root / "feature.txt").exists())
            self.assertEqual(git(root, "status", "--porcelain"), "")
            self.assertIn("test -f feature.txt passed", said)
            self.assertTrue(said[-1].endswith("(nothing was pushed)"), said)

    def test_it_never_pushes(self):
        with folder() as root, folder() as remote:
            git(remote, "init", "-q", "--bare", "-b", "main")
            repo_with_branch(root)
            git(root, "remote", "add", "origin", str(remote))
            git(root, "push", "-q", "origin", "main")
            before = git(remote, "rev-parse", "main")
            self.run_finish(root)
            self.assertEqual(git(remote, "rev-parse", "main"), before)
            self.assertEqual(git(remote, "branch", "--format=%(refname:short)").split(), ["main"])

    def test_a_failing_verify_merges_nothing_keeps_the_branch_and_shows_the_output(self):
        with folder() as root:
            repo_with_branch(root)
            main_tip = git(root, "rev-parse", "main")
            with self.assertRaises(Refuse) as raised:
                self.run_finish(root, {"verifyCommand": "echo broken test output; exit 3"})
            self.assertIn("nothing merged", str(raised.exception))
            self.assertIn("exit 3", str(raised.exception))
            self.assertIn("broken test output", str(raised.exception))
            self.assertEqual((current(root), sorted(branches(root))), ("main", ["feat/x", "main"]))
            self.assertEqual(git(root, "rev-parse", "main"), main_tip)
            self.assertFalse((root / "feature.txt").exists())

    def test_after_a_failure_the_checkout_is_back_where_it_started(self):
        with folder() as root:
            repo_with_branch(root)
            git(root, "switch", "-q", "-c", "elsewhere")
            with self.assertRaises(Refuse):
                self.run_finish(root, {"verifyCommand": "false"})
            self.assertEqual(current(root), "elsewhere")

    def test_without_a_verify_command_it_refuses_unless_no_verify_is_given(self):
        for config in [{}, {"verifyCommand": None}]:
            with folder() as root:
                repo_with_branch(root)
                with self.assertRaises(Refuse) as raised:
                    self.run_finish(root, config)
                self.assertIn("verifyCommand is not set", str(raised.exception))
                self.assertEqual(sorted(branches(root)), ["feat/x", "main"])
                said = self.run_finish(root, config, no_verify=True)
                self.assertEqual((current(root), branches(root)), ("main", ["main"]))
                self.assertFalse(any("passed" in line for line in said), said)

    def test_no_verify_cannot_skip_a_verify_command_the_project_set(self):
        with folder() as root:
            repo_with_branch(root)
            with self.assertRaises(Refuse) as raised:
                self.run_finish(root, {"verifyCommand": "true"}, no_verify=True)
            self.assertIn("without --no-verify", str(raised.exception))
            self.assertEqual(sorted(branches(root)), ["feat/x", "main"])

    def test_full_appends_the_flag_to_the_verify_command(self):
        with folder() as root:
            repo_with_branch(root)
            only_full = {"verifyCommand": "python3 -c \"import sys; sys.exit(0 if '--full' in sys.argv else 1)\""}
            with self.assertRaises(Refuse):
                self.run_finish(root, only_full)
            self.run_finish(root, only_full, full=True)
            self.assertEqual(branches(root), ["main"])

    def test_a_verify_command_that_is_not_a_string_is_refused(self):
        with folder() as root:
            repo_with_branch(root)
            for value in [["make", "verify"], 5, "", "  "]:
                with self.assertRaises(Refuse, msg=value):
                    self.run_finish(root, {"verifyCommand": value})

    def test_the_working_branch_comes_from_the_config(self):
        with folder() as root:
            make_repo(root, branch="trunk")
            git(root, "switch", "-q", "-c", "feat/x")
            (root / "f").write_text("1")
            git(root, "add", "f")
            git(root, "commit", "-q", "-m", "work")
            git(root, "switch", "-q", "trunk")
            with self.assertRaises(Refuse):
                self.run_finish(root)  # the default working branch is main, which does not exist here
            self.run_finish(root, {"workingBranch": "trunk", "verifyCommand": "true"})
            self.assertEqual((current(root), branches(root)), ("trunk", ["trunk"]))

    def test_bad_branches_and_a_dirty_tree_are_refused_before_anything_runs(self):
        with folder() as root, folder() as elsewhere:
            repo_with_branch(root)
            marker = elsewhere / "ran-verify"
            config = {"verifyCommand": f"touch {marker}"}
            for branch in ["main", "nope", "bad branch", "-x", ""]:
                with self.assertRaises(Refuse, msg=branch):
                    self.run_finish(root, config, branch=branch)
            (root / "untracked").write_text("d")
            with self.assertRaises(Refuse) as raised:
                self.run_finish(root, config)
            self.assertIn("not clean", str(raised.exception))
            self.assertFalse(marker.exists())
            self.assertEqual(sorted(branches(root)), ["feat/x", "main"])

    def test_a_branch_that_does_not_fast_forward_is_refused(self):
        with folder() as root:
            repo_with_branch(root)
            (root / "other.txt").write_text("y")
            git(root, "add", "other.txt")
            git(root, "commit", "-q", "-m", "main moved on")
            with self.assertRaises(Refuse) as raised:
                self.run_finish(root)
            self.assertIn("does not fast-forward", str(raised.exception))
            self.assertEqual(sorted(branches(root)), ["feat/x", "main"])


if __name__ == "__main__":
    unittest.main()
