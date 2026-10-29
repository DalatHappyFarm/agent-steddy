import contextlib
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import guard_write  # noqa: E402
from hook_runner import chdir, run_hook, write_config  # noqa: E402

FENCE = {"agents": {"writeFences": {"acme-auditor": ["docs/reviews/", "docs/research"]}}}


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
