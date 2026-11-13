import contextlib
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import guard_write  # noqa: E402
from hook_runner import chdir, git, make_repo, run_hook, write_config  # noqa: E402

FENCE = {"agents": {"writeFences": {"acme-auditor": ["docs/reviews/", "docs/research"]}}}
BUILDER = {"agents": {"writeFences": {"acme-builder": ["cmd/", "internal"]}}}


@contextlib.contextmanager
def project():
    """A temp project dir with the fenced folders, a folder outside them, and two symlinks: one out of a fenced folder, one into it."""
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp).resolve()
        for folder in ["docs/reviews", "docs/research", "docs/reviews-old", "apps/web"]:
            (root / folder).mkdir(parents=True)
        (root / "docs" / "reviews" / "to-apps").symlink_to(root / "apps")
        (root / "shortcut").symlink_to(root / "docs" / "reviews")
        yield root


def verdict(root, path, agent="acme-auditor", config=FENCE, key="file_path", cwd=None):
    """'deny' or 'allow' for a write by `agent`, in process. `path` may be relative to the project dir."""
    data = {"agent_type": agent, "tool_input": {key: str(path)}}
    if cwd is not None:
        data["cwd"] = str(cwd)
    return "deny" if guard_write.judge(data, config, root) else "allow"


class Fence(unittest.TestCase):
    def test_a_fenced_agent_may_write_inside_its_prefixes(self):
        with project() as root:
            for path in [root / "docs/reviews/a.md", root / "docs/reviews/deep/er/a.md", root / "docs/research/b.md", "docs/reviews/a.md",
                         "docs/research/b.md", root / "docs/reviews", root / "docs/research", "docs/reviews/./a.md", "docs/reviews//a.md"]:
                self.assertEqual(verdict(root, path), "allow", path)

    def test_a_fenced_agent_may_not_write_outside_its_prefixes(self):
        with project() as root:
            for path in [root / "apps/web/a.ts", "apps/web/a.ts", "docs/a.md", root / "README.md", root / "docs/reviews-old/a.md", "docs/researchers/a.md",
                         "/tmp/agent-steddy-test.md", root / "docs" / "reviews" / ".." / ".." / "apps" / "x.ts", "docs/reviews/../../apps/x.ts",
                         "docs/reviews/../a.md", root / ".." / "elsewhere" / "docs" / "reviews" / "a.md", "../docs/reviews/a.md"]:
                self.assertEqual(verdict(root, path), "deny", path)

    def test_a_symlink_cannot_carry_a_write_out_of_the_fence_and_can_lead_into_it(self):
        with project() as root:
            self.assertEqual(verdict(root, root / "docs/reviews/to-apps/x.ts"), "deny")
            self.assertEqual(verdict(root, "docs/reviews/to-apps/new/x.ts"), "deny")
            self.assertEqual(verdict(root, root / "shortcut/a.md"), "allow")
            self.assertEqual(verdict(root, root / "shortcut/../apps/a.ts"), "deny")

    def test_the_project_dir_may_itself_be_reached_through_a_symlink(self):
        with project() as root, tempfile.TemporaryDirectory() as other:
            alias = pathlib.Path(other) / "alias"
            alias.symlink_to(root)
            self.assertEqual(verdict(alias, root / "docs/reviews/a.md"), "allow")
            self.assertEqual(verdict(alias, alias / "docs/reviews/a.md"), "allow")
            self.assertEqual(verdict(alias, alias / "apps/a.ts"), "deny")

    def test_a_relative_path_is_taken_from_the_hook_inputs_cwd_then_the_project_dir(self):
        with project() as root:
            self.assertEqual(verdict(root, "a.md", cwd=root / "docs/reviews"), "allow")
            self.assertEqual(verdict(root, "docs/reviews/a.md", cwd=root / "apps"), "deny")
            self.assertEqual(verdict(root, "../../apps/a.ts", cwd=root / "docs/reviews"), "deny")
            self.assertEqual(verdict(root, "docs/reviews/a.md", cwd=root), "allow")
            self.assertEqual(verdict(root, "docs/reviews/a.md", cwd=""), "allow")
            self.assertEqual(verdict(root, root / "docs/reviews/a.md", cwd=root / "apps"), "allow")  # an absolute path ignores the cwd

    def test_a_notebook_is_fenced_by_its_notebook_path(self):
        with project() as root:
            self.assertEqual(verdict(root, root / "docs/research/n.ipynb", key="notebook_path"), "allow")
            self.assertEqual(verdict(root, root / "apps/n.ipynb", key="notebook_path"), "deny")

    def test_the_main_session_and_an_unfenced_agent_are_never_fenced(self):
        with project() as root:
            for agent in [None, "", "acme-web", "Explore", "acme-auditor-2", "Acme-Auditor"]:
                self.assertEqual(verdict(root, root / "apps/web/a.ts", agent), "allow", agent)
            data = {"tool_input": {"file_path": str(root / "apps/web/a.ts")}}  # no agent_type at all: the main session
            self.assertIsNone(guard_write.judge(data, FENCE, root))

    def test_fences_match_by_pattern_and_the_first_matching_pattern_decides(self):
        wide_first = {"agents": {"writeFences": {"acme-*": ["src/"], "acme-auditor": ["docs/"]}}}
        narrow_first = {"agents": {"writeFences": {"acme-auditor": ["docs/"], "acme-*": ["src/"]}}}
        with project() as root:
            self.assertEqual(verdict(root, "src/a.ts", "acme-web", wide_first), "allow")
            self.assertEqual(verdict(root, "docs/a.md", "acme-web", wide_first), "deny")
            self.assertEqual(verdict(root, "docs/a.md", "acme-auditor", wide_first), "deny")
            self.assertEqual(verdict(root, "docs/a.md", "acme-auditor", narrow_first), "allow")
            self.assertEqual(verdict(root, "src/a.ts", "acme-auditor", narrow_first), "deny")
            self.assertEqual(verdict(root, "src/a.ts", "other", narrow_first), "allow")

    def test_an_empty_prefix_list_fences_an_agent_out_of_every_write(self):
        with project() as root:
            config = {"agents": {"writeFences": {"acme-auditor": []}}}
            self.assertEqual(verdict(root, "docs/reviews/a.md", config=config), "deny")
            self.assertIn("nothing", guard_write.judge({"agent_type": "acme-auditor", "tool_input": {"file_path": "a.md"}}, config, root))

    def test_the_reason_names_the_agent_the_prefixes_and_the_path(self):
        with project() as root:
            reason = guard_write.judge({"agent_type": "acme-auditor", "tool_input": {"file_path": "apps/web/a.ts"}}, FENCE, root)
            self.assertIn("`acme-auditor` may write only under docs/reviews/, docs/research", reason)
            self.assertIn("agents.writeFences", reason)
            self.assertTrue(reason.endswith("Refused path: apps/web/a.ts"), reason)


@contextlib.contextmanager
def worktrees(project_folder="acme"):
    """A repo `acme` with a linked worktree inside it (`.claude/worktrees/x`) and one outside it (`acme-worktrees/y`).

    Yields (project dir, inner worktree, outer worktree, the folder that holds the project and the outer worktrees).
    """
    with tempfile.TemporaryDirectory() as tmp:
        base = pathlib.Path(tmp).resolve()
        root = base / "acme"
        (root / "sub").mkdir(parents=True)
        make_repo(root)
        inner, outer = root / ".claude" / "worktrees" / "x", base / "acme-worktrees" / "y"
        git(root, "worktree", "add", "-q", str(inner), "-b", "inner")
        git(root, "worktree", "add", "-q", str(outer), "-b", "outer")
        for tree in (root, inner, outer):
            (tree / "cmd").mkdir()
            (tree / "docs").mkdir()
        yield root, inner, outer, base


class Worktrees(unittest.TestCase):
    """A prefix is relative to the worktree that holds the file, so one entry covers the main checkout and every linked worktree."""

    def judge(self, root, path, agent="acme-builder", config=BUILDER):
        return verdict(root, path, agent, config)

    def test_a_write_inside_the_fence_is_allowed_in_a_worktree_inside_and_one_outside_the_project(self):
        with worktrees() as (root, inner, outer, _):
            for tree in (root, inner, outer):
                for path in ["cmd/a.go", "cmd/deep/er/a.go", "internal/a.go", "cmd", "cmd/./a.go", "cmd//a.go"]:
                    self.assertEqual(self.judge(root, tree / path), "allow", f"{tree} {path}")

    def test_a_write_outside_the_fence_is_denied_in_both_worktrees(self):
        with worktrees() as (root, inner, outer, _):
            (outer / "cmd" / "to-docs").symlink_to(outer / "docs")
            for tree in (root, inner, outer):
                self.assertEqual(self.judge(root, tree / "cmd/a.go"), "allow", tree)  # the fence is not a blanket deny
                for path in ["docs/a.md", "README.md", "cmdx/a.go", "cmd/../docs/a.md", "internal-old/a.go", "cmd/to-docs/a.md" if tree == outer else "docs/b.md"]:
                    self.assertEqual(self.judge(root, tree / path), "deny", f"{tree} {path}")

    def test_the_prefixes_are_not_matched_from_another_worktrees_root(self):
        with worktrees() as (root, inner, outer, _):
            self.assertEqual(self.judge(root, outer / "cmd/a.go"), "allow")
            self.assertEqual(self.judge(root, outer / ".claude/worktrees/x/cmd/a.go"), "deny")
            self.assertEqual(self.judge(root, inner / ".claude/worktrees/x/cmd/a.go"), "deny")  # a folder of that name inside a worktree is just a folder
            self.assertEqual(self.judge(root, outer / "cmd/../../y/docs/a.md"), "deny")

    def test_a_relative_target_is_taken_from_the_cwd_in_a_worktree(self):
        with worktrees() as (root, inner, outer, _):
            self.assertEqual(verdict(root, "a.go", "acme-builder", BUILDER, cwd=outer / "cmd"), "allow")
            self.assertEqual(verdict(root, "a.go", "acme-builder", BUILDER, cwd=outer / "docs"), "deny")
            self.assertEqual(verdict(root, "cmd/a.go", "acme-builder", BUILDER, cwd=inner), "allow")

    def test_a_path_in_another_repo_or_in_no_repo_is_judged_against_the_project_only(self):
        with worktrees() as (root, inner, outer, base):
            other = base / "other"
            other.mkdir()
            make_repo(other)
            (other / "cmd").mkdir()
            git(other, "worktree", "add", "-q", str(base / "other-wt"), "-b", "side")
            (base / "other-wt" / "cmd").mkdir()
            (base / "plain" / "cmd").mkdir(parents=True)
            (base / "broken" / "cmd").mkdir(parents=True)
            (base / "broken" / ".git").write_text("not a gitdir file")
            self.assertEqual(self.judge(root, outer / "cmd/a.go"), "allow")  # the same shape of path, in the project's repo
            for path in [other / "cmd/a.go", base / "other-wt/cmd/a.go", base / "plain/cmd/a.go", base / "broken/cmd/a.go", base / "cmd/a.go"]:
                self.assertEqual(self.judge(root, path), "deny", path)
            self.assertEqual(self.judge(other, other / "cmd/a.go", config={"agents": {"writeFences": {"acme-builder": ["cmd"]}}}), "allow")  # its own project

    def test_a_target_folder_that_does_not_exist_yet_is_judged_by_the_worktree_that_will_hold_it(self):
        with worktrees() as (root, inner, outer, _):
            for tree in (inner, outer):
                self.assertEqual(self.judge(root, tree / "cmd/new/er/still/a.go"), "allow", tree)
                self.assertEqual(self.judge(root, tree / "internal/new/a.go"), "allow", tree)
                self.assertEqual(self.judge(root, tree / "docs/new/er/a.md"), "deny", tree)
                self.assertEqual(self.judge(root, tree / "new/cmd/a.go"), "deny", tree)

    def test_the_old_duplicated_prefixes_still_allow_next_to_the_plain_ones(self):
        config = {"agents": {"writeFences": {"acme-builder": ["internal", ".claude/worktrees/x/cmd/"]}}}
        with worktrees() as (root, inner, outer, _):
            self.assertEqual(self.judge(root, inner / "cmd/a.go", config=config), "allow")  # the project-relative match, as before
            self.assertEqual(self.judge(root, "cmd/a.go", config=config), "deny")
            self.assertEqual(self.judge(root, inner / "docs/a.md", config=config), "deny")
            self.assertEqual(self.judge(root, inner / "internal/a.go", config=config), "allow")  # the plain one covers the worktree too
            self.assertEqual(self.judge(root, outer / "internal/a.go", config=config), "allow")
            self.assertEqual(self.judge(root, outer / "cmd/a.go", config=config), "deny")

    def test_an_agent_with_no_fence_is_untouched_while_a_fenced_one_is_judged_in_the_same_worktree(self):
        with worktrees() as (root, inner, outer, base):
            for path in [outer / "docs/a.md", inner / "docs/a.md", base / "plain/a.md"]:
                self.assertEqual(self.judge(root, path, "acme-web"), "allow", path)
                self.assertEqual(self.judge(root, path, None), "allow", path)
                self.assertEqual(self.judge(root, path), "deny", path)
            self.assertEqual(self.judge(root, outer / "cmd/a.go"), "allow")

    def test_a_project_below_the_repo_root_keeps_its_prefixes_relative_to_the_project_in_every_tree(self):
        config = {"agents": {"writeFences": {"acme-builder": ["docs"]}}}
        with worktrees() as (root, inner, outer, _):
            project = root / "sub"
            for tree in (root, inner, outer):
                (tree / "sub" / "docs").mkdir(parents=True, exist_ok=True)
            for tree in (root, inner, outer):
                self.assertEqual(self.judge(project, tree / "sub/docs/a.md", config=config), "allow", tree)
                self.assertEqual(self.judge(project, tree / "docs/a.md", config=config), "deny", tree)
                self.assertEqual(self.judge(project, tree / "sub/cmd/a.go", config=config), "deny", tree)

    def test_the_project_and_the_worktree_may_be_reached_through_a_symlink(self):
        with worktrees() as (root, inner, outer, base), tempfile.TemporaryDirectory() as other:
            alias = pathlib.Path(other) / "alias"
            alias.symlink_to(base)
            for tree in (alias / "acme", alias / "acme/.claude/worktrees/x", alias / "acme-worktrees/y"):
                self.assertEqual(self.judge(alias / "acme", tree / "cmd/a.go"), "allow", tree)
                self.assertEqual(self.judge(alias / "acme", tree / "docs/a.md"), "deny", tree)
                self.assertEqual(self.judge(root, tree / "cmd/a.go"), "allow", tree)

    def test_the_reason_names_the_worktree_it_judged_against_only_for_another_worktree(self):
        with worktrees() as (root, inner, outer, base):
            reason = guard_write.judge({"agent_type": "acme-builder", "tool_input": {"file_path": str(outer / "docs/a.md")}}, BUILDER, root)
            self.assertIn("`acme-builder` may write only under cmd/, internal", reason)
            self.assertIn(f"Refused path: {outer / 'docs/a.md'}", reason)
            self.assertTrue(reason.endswith(f"(also judged from the worktree {outer})"), reason)
            for path in ["docs/a.md", root / "docs/a.md", base / "plain/docs/a.md"]:
                reason = guard_write.judge({"agent_type": "acme-builder", "tool_input": {"file_path": str(path)}}, BUILDER, root)
                self.assertTrue(reason.endswith(f"Refused path: {path}"), reason)

    def test_the_hook_process_judges_a_write_in_a_worktree_outside_the_project(self):
        with worktrees() as (root, inner, outer, _):
            write_config(root, BUILDER)
            for tree in (inner, outer):
                data = {"tool_name": "Write", "agent_type": "acme-builder", "cwd": str(tree), "tool_input": {"file_path": str(tree / "cmd/new/a.go"), "content": "x"}}
                self.assertIsNone(run_hook("guard_write.py", data, root), tree)
                data["tool_input"]["file_path"] = str(tree / "docs/a.md")
                self.assertEqual(run_hook("guard_write.py", data, root)["hookSpecificOutput"]["permissionDecision"], "deny", tree)


class BrokenConfigAndInput(unittest.TestCase):
    def test_wrongly_typed_fences_fail_open(self):
        with project() as root:
            for fences in [["acme-auditor"], "docs/", {"acme-auditor": "docs/reviews/"}, {"acme-auditor": None}, {"acme-auditor": {"docs": 1}}]:
                config = {"agents": {"writeFences": fences}}
                self.assertEqual(verdict(root, "apps/a.ts", config=config), "allow", fences)
            self.assertEqual(verdict(root, "apps/a.ts", config={"agents": "x"}), "allow")
            self.assertEqual(verdict(root, "apps/a.ts", config={}), "allow")

    def test_broken_prefixes_are_skipped_and_do_not_hide_a_valid_one(self):
        with project() as root:
            config = {"agents": {"writeFences": {"acme-auditor": [1, None, ["x"], "docs/reviews/"]}}}
            self.assertEqual(verdict(root, "docs/reviews/a.md", config=config), "allow")
            self.assertEqual(verdict(root, "apps/a.ts", config=config), "deny")

    def test_a_broken_entry_before_a_valid_fence_does_not_hide_it(self):
        with project() as root:
            config = {"agents": {"writeFences": {"acme-*": "oops", "acme-auditor": ["docs/reviews/"]}}}
            self.assertEqual(verdict(root, "apps/a.ts", config=config), "deny")

    def test_a_write_with_no_path_is_allowed(self):
        with project() as root:
            for tool_input in [{}, {"file_path": ""}, {"file_path": 5}, {"content": "x"}, None]:
                data = {"agent_type": "acme-auditor", "tool_input": tool_input}
                self.assertIsNone(guard_write.judge(data, FENCE, root), tool_input)


class Hook(unittest.TestCase):
    """The script as Claude Code runs it."""

    def decide(self, root, path, config=FENCE, agent="acme-auditor", raw=None):
        if config is not None:
            write_config(root, config)
        data = {"tool_name": "Write", "agent_type": agent, "cwd": str(root), "tool_input": {"file_path": str(path), "content": "x"}}
        return run_hook("guard_write.py", data, root, raw)

    def test_denies_with_a_pre_tool_use_decision(self):
        with project() as root:
            out = self.decide(root, root / "apps/web/a.ts")["hookSpecificOutput"]
            self.assertEqual(out["hookEventName"], "PreToolUse")
            self.assertEqual(out["permissionDecision"], "deny")
            self.assertIn("docs/reviews/", out["permissionDecisionReason"])

    def test_allows_by_printing_nothing(self):
        with project() as root:
            self.assertIsNone(self.decide(root, root / "docs/reviews/a.md"))
            self.assertIsNone(self.decide(root, root / "apps/web/a.ts", agent=None))
            self.assertIsNone(self.decide(root, root / "apps/web/a.ts", agent="acme-web"))

    def test_allows_with_no_config_file_and_with_a_broken_one(self):
        with project() as root:
            self.assertIsNone(self.decide(root, root / "apps/web/a.ts", config=None))
            for config in [["not", "an", "object"], {"agents": {"writeFences": 3}}]:
                self.assertIsNone(self.decide(root, root / "apps/web/a.ts", config=config), config)
            (root / ".claude" / "agent-steddy.json").write_text("{not json")
            self.assertIsNone(self.decide(root, root / "apps/web/a.ts", config=None))

    def test_allows_broken_input(self):
        with project() as root:
            for raw in ["not json", "", "[]", '{"agent_type": "acme-auditor", "tool_input": "x"}']:
                self.assertIsNone(self.decide(root, "x", raw=raw), raw)

    def test_the_fence_prefixes_start_at_the_project_dir_whatever_the_process_cwd_is(self):
        with project() as root, tempfile.TemporaryDirectory() as elsewhere, chdir(elsewhere):
            self.assertIsNone(self.decide(root, "docs/reviews/a.md"))
            self.assertEqual(self.decide(root, "apps/a.ts")["hookSpecificOutput"]["permissionDecision"], "deny")


if __name__ == "__main__":
    unittest.main()
