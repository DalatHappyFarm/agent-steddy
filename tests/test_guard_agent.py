import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import guard_agent  # noqa: E402
from hook_runner import run_hook, write_config  # noqa: E402

ALLOWLIST = {"agents": {"allowed": ["acme-*", "Explore"]}}
MODELS = {"agents": {"models": {"acme-docs": "haiku", "acme-*": "sonnet"}}}


def verdict(config, subagent_type=None, model=None):
    """'deny' or 'allow' for an agent call, in process. A None argument leaves that field out of the call, like the real tool does."""
    call = {"subagent_type": subagent_type, "model": model}
    return "deny" if guard_agent.judge({k: v for k, v in call.items() if v is not None}, config) else "allow"


class AllowedTypes(unittest.TestCase):
    def test_every_type_is_allowed_by_default(self):
        for config in [{}, {"agents": {}}, {"agents": {"allowed": ["*"]}}]:
            for agent in ["general-purpose", "acme-web", "Explore", "x", None, ""]:
                self.assertEqual(verdict(config, agent), "allow", (config, agent))

    def test_only_types_that_match_a_pattern_are_allowed(self):
        cases = {"acme-web": "allow", "acme-docs": "allow", "acme-": "allow", "Explore": "allow",
                 "general-purpose": "deny", "Plan": "deny", "acme": "deny", "ACME-web": "deny", "explore": "deny", "my-acme-web": "deny", "": "deny"}
        for agent, expected in cases.items():
            self.assertEqual(verdict(ALLOWLIST, agent), expected, agent)

    def test_a_call_with_no_type_is_checked_as_general_purpose(self):
        self.assertEqual(verdict(ALLOWLIST), "deny")
        self.assertEqual(verdict({"agents": {"allowed": ["general-purpose"]}}), "allow")
        self.assertEqual(verdict({"agents": {"allowed": ["general-purpose"]}}, "acme-web"), "deny")

    def test_an_empty_list_allows_no_type(self):
        self.assertEqual(verdict({"agents": {"allowed": []}}, "acme-web"), "deny")

    def test_the_reason_names_the_type_and_the_allowed_patterns(self):
        reason = guard_agent.judge({"subagent_type": "general-purpose"}, ALLOWLIST)
        self.assertIn("`general-purpose`", reason)
        self.assertIn("agents.allowed", reason)
        self.assertIn("acme-*, Explore", reason)
        self.assertIn("Allowed: none.", guard_agent.judge({"subagent_type": "x"}, {"agents": {"allowed": []}}))


class Models(unittest.TestCase):
    def test_a_passed_model_must_contain_the_models_name(self):
        cases = [("acme-docs", "haiku", "allow"), ("acme-docs", "claude-haiku-4-5", "allow"), ("acme-docs", "HAIKU", "allow"),
                 ("acme-docs", "sonnet", "deny"), ("acme-docs", "opus", "deny"), ("acme-docs", "inherit", "deny"),
                 ("acme-web", "sonnet", "allow"), ("acme-web", "claude-sonnet-5-5", "allow"), ("acme-web", "haiku", "deny"), ("acme-web", "opus", "deny")]
        for agent, model, expected in cases:
            self.assertEqual(verdict(MODELS, agent, model), expected, (agent, model))

    def test_no_model_is_fine(self):
        for agent in ["acme-docs", "acme-web", "Explore"]:
            self.assertEqual(verdict(MODELS, agent), "allow", agent)
            self.assertEqual(verdict(MODELS, agent, ""), "allow", agent)

    def test_a_type_that_matches_no_pattern_may_pass_any_model(self):
        for model in ["opus", "haiku", "inherit"]:
            self.assertEqual(verdict(MODELS, "Explore", model), "allow", model)

    def test_the_first_matching_pattern_decides_in_file_order(self):
        self.assertEqual(verdict(MODELS, "acme-docs", "sonnet"), "deny")  # acme-docs comes first and wants haiku
        backwards = {"agents": {"models": {"acme-*": "sonnet", "acme-docs": "haiku"}}}
        self.assertEqual(verdict(backwards, "acme-docs", "sonnet"), "allow")
        self.assertEqual(verdict(backwards, "acme-docs", "haiku"), "deny")

    def test_the_type_check_comes_before_the_model_check(self):
        both = {"agents": {**ALLOWLIST["agents"], **MODELS["agents"]}}
        self.assertEqual(verdict(both, "general-purpose", "sonnet"), "deny")
        self.assertIn("agents.allowed", guard_agent.judge({"subagent_type": "general-purpose", "model": "sonnet"}, both))
        self.assertEqual(verdict(both, "acme-docs", "haiku"), "allow")

    def test_the_reason_names_the_type_the_model_and_what_to_do(self):
        reason = guard_agent.judge({"subagent_type": "acme-docs", "model": "opus"}, MODELS)
        self.assertIn("`acme-docs` must run on haiku", reason)
        self.assertIn("agents.models", reason)
        self.assertIn('Drop the model parameter or pass "haiku"', reason)


class BrokenConfig(unittest.TestCase):
    def test_wrongly_typed_values_fail_open(self):
        cases = [
            ({"agents": {"allowed": "acme-*"}}, "general-purpose", None),
            ({"agents": "acme-*"}, "general-purpose", "opus"),
            ({"agents": {"models": ["acme-docs", "haiku"]}}, "acme-docs", "opus"),
            ({"agents": {"models": {"acme-*": 5}}}, "acme-web", "opus"),
            ({"agents": {"models": {"acme-*": None}}}, "acme-web", "opus"),
            ({"agents": {"models": MODELS["agents"]["models"]}}, "acme-web", 7),
        ]
        for config, agent, model in cases:
            self.assertEqual(verdict(config, agent, model), "allow", config)

    def test_broken_entries_are_skipped_and_do_not_hide_a_valid_one(self):
        config = {"agents": {"allowed": [1, None, ["x"], "acme-*"]}}
        self.assertEqual(verdict(config, "acme-web"), "allow")
        self.assertEqual(verdict(config, "Explore"), "deny")


class Hook(unittest.TestCase):
    """The script as Claude Code runs it."""

    def decide(self, config, call, raw=None):
        with tempfile.TemporaryDirectory() as tmp:
            if config is not None:
                write_config(tmp, config)
            return run_hook("guard_agent.py", {"tool_name": "Agent", "tool_input": call}, tmp, raw)

    def test_denies_with_a_pre_tool_use_decision(self):
        out = self.decide(ALLOWLIST, {"subagent_type": "general-purpose", "prompt": "x"})
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "PreToolUse")
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("agents.allowed", out["hookSpecificOutput"]["permissionDecisionReason"])
        out = self.decide(MODELS, {"subagent_type": "acme-docs", "model": "opus"})
        self.assertIn("agents.models", out["hookSpecificOutput"]["permissionDecisionReason"])

    def test_allows_by_printing_nothing(self):
        self.assertIsNone(self.decide(ALLOWLIST, {"subagent_type": "acme-web"}))
        self.assertIsNone(self.decide(MODELS, {"subagent_type": "acme-docs", "model": "haiku"}))
        self.assertIsNone(self.decide(MODELS, {"subagent_type": "acme-docs"}))

    def test_allows_with_no_config_file_and_with_a_broken_one(self):
        call = {"subagent_type": "general-purpose", "model": "opus"}
        for config in [None, ["not", "an", "object"], {"agents": {"allowed": 3, "models": "x"}}]:
            self.assertIsNone(self.decide(config, call), config)

    def test_allows_broken_input(self):
        for raw in ["not json", "", "[]", '{"tool_input": "x"}', '{"tool_input": ["x"]}']:
            self.assertIsNone(self.decide(ALLOWLIST, {}, raw), raw)


if __name__ == "__main__":
    unittest.main()
