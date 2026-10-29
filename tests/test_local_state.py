import contextlib
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import local_state  # noqa: E402
from hook_runner import git, make_repo  # noqa: E402


@contextlib.contextmanager
def folder():
    """A temp folder as a resolved path, so comparisons survive the /var to /private/var link on macOS."""
    with tempfile.TemporaryDirectory() as tmp:
        yield pathlib.Path(tmp).resolve()


class StateDir(unittest.TestCase):
    def test_a_repo_keeps_its_state_in_the_git_dir(self):
        with folder() as root:
            make_repo(root)
            self.assertEqual(local_state.state_dir(root), root / ".git" / "agent-steddy")
            (root / "app" / "src").mkdir(parents=True)
            self.assertEqual(local_state.state_dir(root / "app" / "src"), root / ".git" / "agent-steddy")

    def test_every_worktree_of_a_repo_shares_the_state_of_the_main_checkout(self):
        with folder() as root:
            main, other = root / "main", root / "other"
            main.mkdir()
            make_repo(main)
            git(main, "worktree", "add", "-q", str(other), "-b", "side")
            inside = main / "wt"
            git(main, "worktree", "add", "-q", str(inside), "-b", "inner")
            for worktree in (other, inside):
                self.assertTrue((worktree / ".git").is_file())
                self.assertEqual(local_state.state_dir(worktree), main / ".git" / "agent-steddy", worktree)

    def test_a_gitdir_file_without_a_commondir_is_the_git_dir_itself(self):
        with folder() as root:
            (root / "real").mkdir()
            (root / "sub").mkdir()
            (root / "sub" / ".git").write_text("gitdir: ../real\n")  # a submodule, or a repo made with --separate-git-dir
            self.assertEqual(local_state.state_dir(root / "sub"), root / "real" / "agent-steddy")

    def test_a_project_outside_a_repo_uses_a_subfolder_of_the_plugin_data_dir(self):
        with folder() as one, folder() as two, folder() as data:
            with mock.patch.dict(os.environ, {"CLAUDE_PLUGIN_DATA": str(data)}):
                first, second = local_state.state_dir(one), local_state.state_dir(two)
            self.assertEqual(first.parent, data)
            self.assertEqual(second.parent, data)
            self.assertNotEqual(first, second)  # one plugin data folder serves every project
            with mock.patch.dict(os.environ, {"CLAUDE_PLUGIN_DATA": str(data)}):
                self.assertEqual(local_state.state_dir(one), first)

    def test_a_project_outside_a_repo_with_no_plugin_data_dir_has_no_state(self):
        with folder() as root:
            for value in ("", None):
                env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PLUGIN_DATA"}
                if value is not None:
                    env["CLAUDE_PLUGIN_DATA"] = value
                with mock.patch.dict(os.environ, env, clear=True):
                    self.assertIsNone(local_state.state_dir(root), value)

    def test_a_repo_wins_over_the_plugin_data_dir(self):
        with folder() as root, folder() as data:
            make_repo(root)
            with mock.patch.dict(os.environ, {"CLAUDE_PLUGIN_DATA": str(data)}):
                self.assertEqual(local_state.state_dir(root), root / ".git" / "agent-steddy")


class ProjectDir(unittest.TestCase):
    def test_the_env_var_comes_first(self):
        with folder() as root, mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": str(root)}):
            self.assertEqual(local_state.project_dir(), root)

    def test_without_it_the_nearest_folder_with_a_config_or_a_git_dir_wins(self):
        with folder() as root:
            deep = root / "a" / "b"
            deep.mkdir(parents=True)
            make_repo(root)
            with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": ""}):
                with contextlib.ExitStack() as stack:
                    stack.enter_context(mock.patch("pathlib.Path.cwd", return_value=deep))
                    self.assertEqual(local_state.project_dir(), root)
                    (root / "a" / ".claude").mkdir()
                    (root / "a" / ".claude" / "agent-steddy.json").write_text("{}")
                    self.assertEqual(local_state.project_dir(), root / "a")

    def test_with_nothing_to_find_it_is_the_cwd(self):
        with folder() as root, mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": ""}), mock.patch("pathlib.Path.cwd", return_value=root):
            self.assertEqual(local_state.project_dir(), root)


if __name__ == "__main__":
    unittest.main()
