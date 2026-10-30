"""Resume notes: `agent-steddy pause` and `resume`, `record finish` clearing the note, and the SessionStart hook that points at it."""
import contextlib
import datetime as dt
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import record  # noqa: E402
import resume  # noqa: E402
from hook_runner import SCRIPTS, git, make_repo, run_hook, write_config  # noqa: E402
from local_state import Refuse  # noqa: E402

BIN = ROOT / "bin" / "agent-steddy"
NOW = dt.datetime(2026, 10, 30, 14, 5)
IN_REPO = {"resume": {"folder": "docs/agents/resume"}}
SETTINGS = [("local state", {}), ("in the repo", IN_REPO)]
PAUSE = {"intent": "add the pricing page", "done": "the page renders, L1 unit tests green", "next_step": "write the footer test"}


@contextlib.contextmanager
def folder():
    """A temp folder as a resolved path, so comparisons survive the /var to /private/var link on macOS."""
    with tempfile.TemporaryDirectory() as tmp:
        yield pathlib.Path(tmp).resolve()


@contextlib.contextmanager
def repo(branch="feat/x", extra_commit=True):
    """A repo on main with one commit; with `branch` a second branch of that name is checked out, one commit ahead (it adds `work.txt`)."""
    with folder() as root:
        make_repo(root)
        if branch:
            git(root, "switch", "-q", "-c", branch)
            if extra_commit:
                commit(root, "work.txt", "feat: work")
        yield root


def commit(root, name, subject):
    (root / name).write_text(subject)
    git(root, "add", name)
    git(root, "commit", "-q", "-m", subject)


def paused(root, config=None, now=NOW, **extra):
    return resume.pause(root, config or {}, **{**PAUSE, **extra}, now=now)


def note_path(root, config, branch="feat/x"):
    return resume.note_folder(root, config) / resume.note_name(branch)


def agent_steddy(args, cwd):
    """The finished process of `bin/agent-steddy`, run the way the Bash tool runs it: no CLAUDE_PROJECT_DIR and no CLAUDE_PLUGIN_DATA."""
    env = {key: value for key, value in os.environ.items() if key not in ("CLAUDE_PROJECT_DIR", "CLAUDE_PLUGIN_DATA")}
    return subprocess.run([str(BIN), *args], cwd=cwd, env=env, capture_output=True, text=True)


class BranchNames(unittest.TestCase):
    def test_a_slash_becomes_two_underscores(self):
        for branch, name in [("feat/x", "feat__x.md"), ("a/b/c", "a__b__c.md"), ("main", "main.md"), ("fix-1.2_x", "fix-1.2_x.md"), ("feat/pstack-ideas", "feat__pstack-ideas.md")]:
            self.assertEqual(resume.note_name(branch), name, branch)


class NoteFolder(unittest.TestCase):
    def test_no_setting_is_the_resume_folder_of_the_git_common_dir_that_worktrees_share(self):
        with repo(branch=None) as root:
            self.assertEqual(resume.note_folder(root, {}), root / ".git" / "agent-steddy" / "resume")
            git(root, "worktree", "add", "-q", str(root / "wt"), "-b", "side")
            self.assertEqual(resume.note_folder(root / "wt", {}), root / ".git" / "agent-steddy" / "resume")

    def test_a_setting_is_a_folder_of_the_project(self):
        with repo(branch=None) as root:
            for config in [IN_REPO, {"resume": {"folder": " docs/agents/resume "}}]:
                self.assertEqual(resume.note_folder(root, config), root / "docs" / "agents" / "resume")

    def test_a_value_that_is_not_a_usable_string_means_the_local_state(self):
        with repo(branch=None) as root:
            for config in [{"resume": {"folder": None}}, {"resume": {"folder": ""}}, {"resume": {"folder": 5}}, {"resume": "x"}, {"resume": {}}]:
                self.assertEqual(resume.note_folder(root, config), root / ".git" / "agent-steddy" / "resume", config)

    def test_a_folder_outside_the_project_is_refused_with_exit_2(self):
        with repo(branch=None) as root:
            for setting in ["/tmp/notes", "../notes", "docs/../../notes"]:
                with self.assertRaises(Refuse, msg=setting) as raised:
                    resume.note_folder(root, {"resume": {"folder": setting}})
                self.assertEqual(raised.exception.code, 2)

    def test_outside_a_git_repo_the_local_state_has_no_place_but_a_project_folder_does(self):
        with folder() as root:
            with self.assertRaises(Refuse) as raised:
                resume.note_folder(root, {})
            self.assertEqual(raised.exception.code, 2)
            self.assertEqual(resume.note_folder(root, IN_REPO), root / "docs" / "agents" / "resume")


class Pause(unittest.TestCase):
    def test_the_note_has_the_fixed_shape_for_both_settings(self):
        for label, config in SETTINGS:
            with self.subTest(label), repo() as root:
                (root / "edited.txt").write_text("e")  # untracked
                git(root, "add", "edited.txt")  # staged and new
                head = git(root, "rev-parse", "HEAD").strip()
                merge = git(root, "rev-parse", "--short=12", "main").strip()
                paused(root, config, open_decisions="the footer copy", pitfalls="the cache", files="a.txt, b.txt,,")
                text = note_path(root, config).read_text()
                self.assertEqual(text, "\n".join([
                    "# Resume note: feat/x", "",
                    "- Date: 2026-10-30 14:05", "- Branch: feat/x", f"- HEAD: {head} feat: work", f"- Base: main (merge base {merge})", "",
                    "## Committed since the base", "```text", " work.txt | 1 +", " 1 file changed, 1 insertion(+)", "```", "",
                    "## Uncommitted files", "- A edited.txt", "",
                    "## Intent", "add the pricing page", "",
                    "## Done and verified", "the page renders, L1 unit tests green", "",
                    "## Open decisions", "the footer copy", "",
                    "## Next step", "write the footer test", "",
                    "## Key files", "- a.txt", "- b.txt", "",
                    "## Pitfalls", "the cache", "",
                ]))

    def test_the_optional_parts_default_to_none(self):
        with repo() as root:
            paused(root)
            text = note_path(root, {}).read_text()
            for section in ["## Open decisions\nnone\n", "## Key files\n- none\n", "## Pitfalls\nnone\n", "## Uncommitted files\n- none\n"]:
                self.assertIn(section, text)

    def test_the_local_note_lives_in_the_git_dir_and_the_other_in_the_project_folder(self):
        with repo() as root:
            self.assertEqual(paused(root)[0], f"saved: {root / '.git' / 'agent-steddy' / 'resume' / 'feat__x.md'}")
            self.assertTrue((root / ".git" / "agent-steddy" / "resume" / "feat__x.md").is_file())
            self.assertFalse((root / "docs").exists())
        with repo() as root:
            lines = paused(root, IN_REPO)
            self.assertEqual(lines[0], "saved: docs/agents/resume/feat__x.md")
            self.assertTrue((root / "docs" / "agents" / "resume" / "feat__x.md").is_file())
            self.assertIn("nothing was committed", lines[1])
            self.assertIn("-- docs/agents/resume/feat__x.md", lines[1])

    def test_it_commits_nothing_and_a_note_in_the_repo_stays_untracked(self):
        with repo() as root:
            before = git(root, "rev-parse", "HEAD"), git(root, "log", "--oneline")
            paused(root, IN_REPO)
            self.assertEqual((git(root, "rev-parse", "HEAD"), git(root, "log", "--oneline")), before)
            self.assertEqual(git(root, "status", "--porcelain", "--untracked-files=all").strip(), "?? docs/agents/resume/feat__x.md")

    def test_the_note_folder_is_left_out_of_the_uncommitted_files(self):
        with repo() as root:
            paused(root, IN_REPO)
            paused(root, IN_REPO)  # the first note is untracked now
            self.assertIn("## Uncommitted files\n- none\n", note_path(root, IN_REPO).read_text())
            (root / "other.txt").write_text("o")
            paused(root, IN_REPO)
            self.assertIn("## Uncommitted files\n- ?? other.txt\n", note_path(root, IN_REPO).read_text())

    def test_a_new_pause_replaces_the_note_of_the_branch_and_leaves_the_others(self):
        with repo() as root:
            paused(root, intent="first")
            git(root, "switch", "-q", "-c", "feat/y")
            paused(root, intent="other branch")
            git(root, "switch", "-q", "feat/x")
            paused(root, intent="second")
            folder_ = resume.note_folder(root, {})
            self.assertEqual(sorted(path.name for path in folder_.iterdir()), ["feat__x.md", "feat__y.md"])
            self.assertIn("## Intent\nsecond\n", (folder_ / "feat__x.md").read_text())
            self.assertNotIn("first", (folder_ / "feat__x.md").read_text())
            self.assertIn("## Intent\nother branch\n", (folder_ / "feat__y.md").read_text())

    def test_a_missing_base_branch_is_said_and_the_note_still_saves(self):
        with repo() as root:
            paused(root, {"workingBranch": "trunk"})
            text = note_path(root, {}).read_text()
            self.assertIn("- Base: trunk (not found, so there is no diff against it)\n", text)
            self.assertIn("```text\nnone\n```", text)

    def test_on_the_working_branch_nothing_is_committed_since_the_base(self):
        with repo(branch=None) as root:
            paused(root)
            self.assertIn("```text\nnone\n```", note_path(root, {}, "main").read_text())

    def test_a_long_diff_stat_keeps_the_first_lines_and_the_summary(self):
        with repo(extra_commit=False) as root:
            for number in range(60):
                (root / f"f{number:02d}.txt").write_text("x")
            git(root, "add", ".")
            git(root, "commit", "-q", "-m", "many")
            paused(root)
            stat = note_path(root, {}).read_text().split("```text\n")[1].split("\n```")[0].splitlines()
            self.assertEqual(len(stat), resume.MAX_STAT_LINES)
            self.assertEqual(stat[-1], " 60 files changed, 60 insertions(+)")
            self.assertRegex(stat[-2], r"^ \.\.\. \d+ more lines$")

    def test_a_detached_head_a_repo_with_no_commit_and_no_repo_are_refused_with_exit_2(self):
        with repo() as root:
            git(root, "switch", "-q", "--detach")
            with self.assertRaises(Refuse) as raised:
                paused(root)
            self.assertEqual(raised.exception.code, 2)
            self.assertIn("detached", str(raised.exception))
            self.assertFalse((root / ".git" / "agent-steddy").exists())
        with folder() as root:
            git(root, "init", "-q", "-b", "main")
            with self.assertRaises(Refuse) as raised:
                paused(root)
            self.assertEqual((raised.exception.code, "no commit" in str(raised.exception)), (2, True))
        with folder() as root:
            for config in [{}, IN_REPO]:
                with self.assertRaises(Refuse) as raised:
                    paused(root, config)
                self.assertEqual((raised.exception.code, "not a git repo" in str(raised.exception)), (2, True))
            self.assertEqual(list(root.iterdir()), [])

    def test_empty_or_multi_line_values_are_refused_and_nothing_is_written(self):
        with repo() as root:
            bad = [{"intent": ""}, {"done": "  "}, {"next_step": ""}, {"intent": "a\nb"}, {"done": "a\r\nb"}, {"open_decisions": ""}, {"open_decisions": "a\nb"}, {"pitfalls": "a\nb"}, {"pitfalls": " "}]
            for change in bad:
                with self.assertRaises(Refuse, msg=change):
                    paused(root, **change)
            self.assertFalse((root / ".git" / "agent-steddy").exists())

    def test_a_folder_outside_the_project_is_refused_and_writes_nothing(self):
        with repo() as root, folder() as elsewhere:
            with self.assertRaises(Refuse):
                paused(root, {"resume": {"folder": str(elsewhere / "notes")}})
            self.assertEqual(list(elsewhere.iterdir()), [])


class Show(unittest.TestCase):
    def test_it_prints_the_note_then_what_changed_since_it_for_both_settings(self):
        for label, config in SETTINGS:
            with self.subTest(label), repo() as root:
                paused(root, config, files="work.txt")
                head = git(root, "rev-parse", "HEAD").strip()
                commit(root, "later.txt", "feat: after the pause")
                (root / "dirty.txt").write_text("d")
                lines = resume.show(root, {**config, "verifyCommand": "make verify"})
                note = note_path(root, config).read_text().rstrip("\n").splitlines()
                self.assertEqual(lines[:len(note)], note)
                self.assertEqual(lines[len(note):], [
                    "", "## Since the note",
                    f"commits after {head[:12]} (1):", f"  {git(root, 'rev-parse', '--short', 'HEAD').strip()} feat: after the pause",
                    "uncommitted files now (1):", "  ?? dirty.txt", "",
                    "The note is a claim, not evidence: check Done against git (`git log`, `git diff`) and run the verify command (`make verify`); do not redo what git shows is done.",
                ])

    def test_with_nothing_changed_it_says_none_and_without_a_verify_command_names_the_checks(self):
        with repo() as root:
            paused(root)
            lines = resume.show(root, {})
            self.assertEqual(lines[lines.index("## Since the note"):][1:], [
                f"commits after {git(root, 'rev-parse', 'HEAD').strip()[:12]} (0):", "  none", "uncommitted files now (0):", "  none", "",
                "The note is a claim, not evidence: check Done against git (`git log`, `git diff`) and run the project's checks; do not redo what git shows is done."])

    def test_a_branch_with_no_note_says_so(self):
        with repo() as root:
            lines = resume.show(root, {})
            self.assertEqual(lines, [f"no resume note for feat/x (looked in {root / '.git' / 'agent-steddy' / 'resume'})"])
            self.assertEqual(resume.show(root, {}, "other"), [f"no resume note for other (looked in {root / '.git' / 'agent-steddy' / 'resume'})"])

    def test_a_branch_argument_reads_that_branchs_note_and_says_the_checkout_is_elsewhere(self):
        with repo() as root:
            paused(root)
            commit(root, "later.txt", "feat: later")
            git(root, "switch", "-q", "main")
            lines = resume.show(root, {}, "feat/x")
            self.assertIn("commits after", "\n".join(lines))
            self.assertIn("  " + git(root, "log", "-1", "--format=%h feat: later", "feat/x").strip(), lines)
            self.assertIn("uncommitted files: not listed, the checkout is on main, not on feat/x", lines)
            self.assertEqual(resume.show(root, {})[0][:20], "no resume note for m")  # the checkout is main, which has no note

    def test_a_name_that_maps_to_the_same_file_does_not_show_another_branchs_note(self):
        with repo() as root:
            paused(root)
            self.assertIn("feat__x.md", [path.name for path in resume.note_folder(root, {}).iterdir()])
            git(root, "branch", "feat__x")  # the same file name as feat/x
            self.assertTrue(resume.show(root, {}, "feat__x")[0].startswith("no resume note for feat__x"))

    def test_a_head_that_is_not_on_the_branch_any_more_is_said(self):
        with repo() as root:
            paused(root)
            git(root, "commit", "-q", "--amend", "--allow-empty", "-m", "feat: work, amended")
            self.assertTrue(any("is not an ancestor of feat/x (rebased or reset); git log main..feat/x" in line for line in resume.show(root, {})))
            path = note_path(root, {})
            path.write_text(path.read_text().replace(resume.fields(path.read_text())["head"], "0" * 40))
            self.assertTrue(any("is not in this repo, so compare with the base: git log main..feat/x" in line for line in resume.show(root, {})))

    def test_a_note_edited_by_hand_with_no_head_line_still_prints(self):
        with repo() as root:
            paused(root)
            path = note_path(root, {})
            path.write_text("\n".join(line for line in path.read_text().splitlines() if not line.startswith("- HEAD:")) + "\n")
            lines = resume.show(root, {})
            self.assertIn("the note has no HEAD line, so compare with the base with git log and git diff", lines)
            self.assertEqual(lines[-1][:20], "The note is a claim,")

    def test_a_detached_head_is_refused_unless_a_branch_is_named(self):
        with repo() as root:
            paused(root)
            git(root, "switch", "-q", "--detach")
            with self.assertRaises(Refuse) as raised:
                resume.show(root, {})
            self.assertEqual(raised.exception.code, 2)
            self.assertIn("## Intent", resume.show(root, {}, "feat/x"))


class Clear(unittest.TestCase):
    def test_it_deletes_the_note_of_the_branch_only_and_a_second_clear_is_not_an_error(self):
        for label, config in SETTINGS:
            with self.subTest(label), repo() as root:
                paused(root, config)
                git(root, "switch", "-q", "-c", "feat/y")
                paused(root, config)
                git(root, "switch", "-q", "feat/x")
                shown = str(note_path(root, config)) if not config else "docs/agents/resume/feat__x.md"
                self.assertEqual(resume.clear(root, config), [f"cleared: {shown}"])
                self.assertEqual([path.name for path in resume.note_folder(root, config).iterdir()], ["feat__y.md"])
                self.assertEqual(resume.clear(root, config), ["no resume note for feat/x, nothing to clear"])
                self.assertEqual(resume.clear(root, config, "feat/y")[0][:8], "cleared:")
                self.assertEqual(list(resume.note_folder(root, config).iterdir()), [])

    def test_a_committed_note_is_deleted_with_a_reminder_to_commit_the_removal(self):
        with repo() as root:
            paused(root, IN_REPO)
            git(root, "add", "docs/agents/resume/feat__x.md")
            git(root, "commit", "-q", "-m", "docs: the note", "--", "docs/agents/resume/feat__x.md")
            lines = resume.clear(root, IN_REPO)
            self.assertEqual(lines[0], "cleared: docs/agents/resume/feat__x.md")
            self.assertIn("commit its removal by path", lines[1])
            self.assertEqual(git(root, "status", "--porcelain").strip(), "D docs/agents/resume/feat__x.md")

    def test_a_note_for_a_name_that_maps_to_the_same_file_is_not_deleted(self):
        with repo() as root:
            paused(root)
            self.assertEqual(resume.clear(root, {}, "feat__x"), ["no resume note for feat__x, nothing to clear"])
            self.assertTrue(note_path(root, {}).is_file())


class FinishClearsTheNote(unittest.TestCase):
    def finish(self, root, config):
        said = []
        record.finish(root, "feat/x", {"verifyCommand": "true", **config}, say=said.append)
        return said

    def test_a_merge_deletes_the_note_of_the_branch_and_says_so(self):
        for label, config in SETTINGS:
            with self.subTest(label), repo() as root:
                paused(root, config)
                git(root, "switch", "-q", "main")
                git(root, "switch", "-q", "-c", "feat/y")
                paused(root, config)
                git(root, "switch", "-q", "main")
                said = self.finish(root, config)
                self.assertTrue(any(line.startswith("cleared: ") and "feat__x.md" in line for line in said), said)
                self.assertEqual([path.name for path in resume.note_folder(root, config).iterdir()], ["feat__y.md"])
                self.assertEqual(said[-1], "done, on main (nothing was pushed)")

    def test_a_note_kept_in_the_repo_does_not_make_the_tree_dirty_for_finish(self):
        with repo() as root:
            paused(root, IN_REPO)
            git(root, "switch", "-q", "main")
            self.assertEqual(git(root, "status", "--porcelain", "--untracked-files=all").strip(), "?? docs/agents/resume/feat__x.md")
            self.finish(root, IN_REPO)
            self.assertEqual(git(root, "status", "--porcelain", "--untracked-files=all"), "")
            (root / "stray.txt").write_text("s")
            repo_branch = "feat/z"
            git(root, "switch", "-q", "-c", repo_branch)
            git(root, "switch", "-q", "main")
            with self.assertRaises(Refuse) as raised:
                record.finish(root, repo_branch, {"verifyCommand": "true", **IN_REPO}, say=lambda message: None)
            self.assertIn("not clean", str(raised.exception))  # a stray file still counts

    def test_without_the_setting_an_untracked_file_in_the_same_folder_still_counts(self):
        with repo() as root:
            git(root, "switch", "-q", "main")
            (root / "docs" / "agents" / "resume").mkdir(parents=True)
            (root / "docs" / "agents" / "resume" / "feat__x.md").write_text("x")
            with self.assertRaises(Refuse) as raised:
                self.finish(root, {})
            self.assertIn("not clean", str(raised.exception))

    def test_a_committed_note_is_deleted_and_the_removal_is_left_to_commit(self):
        with repo() as root:
            paused(root, IN_REPO)
            git(root, "add", "docs/agents/resume/feat__x.md")
            git(root, "commit", "-q", "-m", "docs: the note", "--", "docs/agents/resume/feat__x.md")
            git(root, "switch", "-q", "main")
            said = self.finish(root, IN_REPO)
            self.assertTrue(any("commit its removal by path" in line for line in said), said)
            self.assertEqual(git(root, "status", "--porcelain").strip(), "D docs/agents/resume/feat__x.md")

    def test_a_branch_with_no_note_gets_no_mention_of_one(self):
        with repo() as root:
            git(root, "switch", "-q", "main")
            self.assertFalse(any("resume" in line for line in self.finish(root, {})))

    def test_a_failed_verify_keeps_the_note(self):
        with repo() as root:
            paused(root)
            git(root, "switch", "-q", "main")
            with self.assertRaises(Refuse):
                self.finish(root, {"verifyCommand": "false"})
            self.assertTrue(note_path(root, {}).is_file())

    def test_a_folder_setting_that_cannot_be_used_does_not_undo_the_merge(self):
        with repo() as root:
            git(root, "switch", "-q", "main")
            said = self.finish(root, {"resume": {"folder": "../notes"}})
            self.assertTrue(any(line.startswith("the resume note was not cleared:") for line in said), said)
            self.assertEqual(git(root, "branch", "--format=%(refname:short)").split(), ["main"])


class SessionStartHook(unittest.TestCase):
    LINE = "Resume note for feat/x from 2026-10-30 14:05: run agent-steddy resume before you start."

    def hook(self, root, source="startup"):
        return run_hook("session_start.py", {"hook_event_name": "SessionStart", "source": source, "cwd": str(root)}, root)

    def test_a_branch_with_a_note_gets_one_line_whatever_the_source_and_the_setting(self):
        for label, config in SETTINGS:
            for source in ["startup", "resume", "clear", "compact", "fork"]:
                with self.subTest(label, source=source), repo() as root:
                    write_config(root, config)
                    paused(root, config)
                    self.assertEqual(self.hook(root, source), {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": self.LINE}})

    def test_nothing_is_printed_without_a_note_for_this_branch(self):
        with repo() as root:
            self.assertIsNone(self.hook(root))  # no note folder at all
            paused(root)
            git(root, "switch", "-q", "main")
            self.assertIsNone(self.hook(root))  # a note, but for another branch
            git(root, "switch", "-q", "feat/x")
            self.assertEqual(self.hook(root)["hookSpecificOutput"]["additionalContext"], self.LINE)
            resume.clear(root, {})
            self.assertIsNone(self.hook(root))

    def test_a_linked_worktree_sees_the_note_of_its_branch(self):
        with repo() as root:
            git(root, "worktree", "add", "-q", str(root / "wt"), "-b", "side")
            paused(root / "wt", intent="in the worktree")
            self.assertEqual(self.hook(root / "wt")["hookSpecificOutput"]["additionalContext"], self.LINE.replace("feat/x", "side"))
            self.assertIsNone(self.hook(root))

    def test_a_broken_setup_prints_nothing_and_exits_0(self):
        with repo() as root:
            paused(root)
            for raw in ["", "not json", "[]"]:  # whatever arrives on stdin, the project comes from the environment
                self.assertEqual(self.hook_raw(root, raw), self.LINE)
            (root / ".claude").mkdir()
            (root / ".claude" / "agent-steddy.json").write_text("{ broken")  # the defaults apply, and the config's own warning stays out of the hook
            done = self.run_script(root)
            self.assertEqual((done.returncode, done.stderr), (0, ""))
            self.assertIn(self.LINE, done.stdout)
            write_config(root, {"resume": {"folder": "../elsewhere"}})
            done = self.run_script(root)
            self.assertEqual((done.returncode, done.stdout, done.stderr), (0, "", ""))
            git(root, "switch", "-q", "--detach")
            write_config(root, {})
            self.assertEqual(self.run_script(root).stdout, "")

    def test_outside_a_git_repo_it_prints_nothing(self):
        with folder() as root:
            for config in [{}, IN_REPO]:
                write_config(root, config)
                done = self.run_script(root)
                self.assertEqual((done.returncode, done.stdout, done.stderr), (0, "", ""), config)

    def test_a_project_folder_that_is_not_a_folder_prints_nothing(self):
        with repo() as root:
            (root / "docs" / "agents").mkdir(parents=True)
            (root / "docs" / "agents" / "resume").write_text("a file, not a folder")
            write_config(root, IN_REPO)
            self.assertEqual(self.run_script(root).stdout, "")

    def test_a_project_with_no_note_never_calls_git(self):
        with repo() as root:
            with mock.patch.object(resume, "git", side_effect=AssertionError("git was called")):
                self.assertEqual(resume.pointer(root, {}), "")
                (root / ".git" / "agent-steddy" / "resume").mkdir(parents=True)
                self.assertEqual(resume.pointer(root, {}), "")  # an empty note folder

    def run_script(self, root, raw="{}"):
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(root)}
        return subprocess.run([sys.executable, "-I", str(SCRIPTS / "session_start.py")], input=raw, capture_output=True, text=True, env=env)

    def hook_raw(self, root, raw):
        done = self.run_script(root, raw)
        self.assertEqual((done.returncode, done.stderr), (0, ""))
        return json.loads(done.stdout)["hookSpecificOutput"]["additionalContext"]


class Cli(unittest.TestCase):
    ARGS = ["pause", "--intent", "add the page", "--done", "page renders, L1", "--next", "write the test"]

    def test_pause_resume_and_clear_run_the_way_the_bash_tool_runs_them(self):
        with repo() as root:
            done = agent_steddy([*self.ARGS, "--open", "the copy", "--pitfalls", "the cache", "--files", "work.txt,a.txt"], root)
            self.assertEqual((done.returncode, done.stderr), (0, ""))
            self.assertTrue(done.stdout.startswith("saved: "), done.stdout)
            text = (root / ".git" / "agent-steddy" / "resume" / "feat__x.md").read_text()
            for part in ["## Intent\nadd the page\n", "## Open decisions\nthe copy\n", "## Key files\n- work.txt\n- a.txt\n", "## Pitfalls\nthe cache\n"]:
                self.assertIn(part, text)
            commit(root, "later.txt", "feat: later")
            shown = agent_steddy(["resume"], root)
            self.assertEqual((shown.returncode, shown.stderr), (0, ""))
            self.assertIn("## Intent\nadd the page", shown.stdout)
            self.assertIn("commits after ", shown.stdout)
            self.assertIn("feat: later", shown.stdout)
            self.assertIn("claim, not evidence", shown.stdout)
            self.assertEqual(agent_steddy(["resume", "--branch", "feat/x"], root).stdout, shown.stdout)
            cleared = agent_steddy(["resume", "--clear"], root)
            self.assertEqual((cleared.returncode, cleared.stdout.startswith("cleared: ")), (0, True))
            again = agent_steddy(["resume"], root)
            self.assertEqual((again.returncode, again.stdout.startswith("no resume note for feat/x")), (0, True))

    def test_the_config_picks_the_folder(self):
        with repo() as root:
            write_config(root, IN_REPO)
            self.assertEqual(agent_steddy(self.ARGS, root).stdout.splitlines()[0], "saved: docs/agents/resume/feat__x.md")
            self.assertTrue((root / "docs" / "agents" / "resume" / "feat__x.md").is_file())

    def test_the_refusals_exit_2_for_a_missing_branch_or_repo_and_1_for_a_bad_value(self):
        with repo() as root:
            for args, code in [(["pause"], 2), (["pause", "--intent", "i", "--done", "d"], 2), ([*self.ARGS[:-1], ""], 1), ([*self.ARGS[:-1], "a\nb"], 1)]:
                done = agent_steddy(args, root)
                self.assertEqual(done.returncode, code, args)
                self.assertEqual(done.stdout, "", args)
            git(root, "switch", "-q", "--detach")
            for args in [self.ARGS, ["resume"], ["resume", "--clear"]]:
                done = agent_steddy(args, root)
                self.assertEqual(done.returncode, 2, args)
                self.assertTrue(done.stderr.startswith("agent-steddy: refused: HEAD is detached"), done.stderr)
        with folder() as root:
            for args in [self.ARGS, ["resume"]]:
                done = agent_steddy(args, root)
                self.assertEqual(done.returncode, 2, args)
                self.assertIn("not a git repo", done.stderr)


if __name__ == "__main__":
    unittest.main()
