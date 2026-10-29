import contextlib
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
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
        return {"task": "fix the build", "roles": "web, docs", "worked": "tests first", "exposed": "a stale cache", "rule": "clear the cache in CI", "today": "2026-10-29", **extra}

    def test_a_missing_file_is_created_from_the_template_with_the_entry_below_it(self):
        with folder() as root:
            path = root / "docs" / "agents" / "lessons.md"
            self.assertEqual(record.lesson(path, **self.entry()), "## 2026-10-29 - fix the build - roles: web, docs")
            lines = path.read_text().split("\n")
            self.assertEqual(lines[0], "# Lessons")
            self.assertEqual(lines.count("```text"), 1)
            at = lines.index("## 2026-10-29 - fix the build - roles: web, docs")
            self.assertGreater(at, lines.index("```"))  # below the format block, not inside it
            self.assertEqual(lines[at + 1:at + 5], ["- Worked: tests first", "- Exposed: a stale cache", "- Rule: clear the cache in CI", ""])
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
                self.assertEqual(path.read_text(), "# My lessons\n\n## 2026-10-29 - fix the build - roles: web, docs\n- Worked: tests first\n- Exposed: a stale cache\n- Rule: clear the cache in CI\n", original)

    def test_the_date_defaults_to_today(self):
        import datetime
        with folder() as root:
            heading = record.lesson(root / "l.md", **self.entry(today=None))
            self.assertTrue(heading.startswith(f"## {datetime.date.today().isoformat()} - "), heading)

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
