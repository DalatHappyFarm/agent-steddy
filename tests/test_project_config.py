import contextlib
import io
import json
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import project_config  # noqa: E402
from hook_runner import chdir  # noqa: E402


@contextlib.contextmanager
def project(text=None):
    """A temp project dir, with `.claude/agent-steddy.json` holding `text` when given."""
    with tempfile.TemporaryDirectory() as tmp:
        if text is not None:
            (pathlib.Path(tmp) / ".claude").mkdir()
            (pathlib.Path(tmp) / ".claude" / "agent-steddy.json").write_text(text)
        yield tmp


class LoadConfig(unittest.TestCase):
    def test_missing_file_gives_defaults_and_a_fresh_copy(self):
        with project() as tmp:
            config = project_config.load(tmp)
            self.assertEqual(config, project_config.DEFAULTS)
            config["agents"]["allowed"].append("x")
            self.assertEqual(project_config.load(tmp)["agents"]["allowed"], ["*"])

    def test_invalid_json_or_non_object_gives_defaults_and_one_stderr_line(self):
        for text in ["{not json", "[1, 2]", ""]:
            with project(text) as tmp, contextlib.redirect_stderr(io.StringIO()) as err:
                self.assertEqual(project_config.load(tmp), project_config.DEFAULTS, text)
            self.assertEqual(len(err.getvalue().splitlines()), 1, text)
            self.assertIn("agent-steddy.json", err.getvalue())

    def test_objects_merge_one_level_down_and_lists_replace(self):
        text = json.dumps({
            "verifyCommand": "make verify",
            "agents": {"allowed": ["acme-*"]},
            "commands": {"deny": [{"match": "x y", "reason": "no"}]},
            "extra": {"kept": True},
        })
        with project(text) as tmp:
            config = project_config.load(tmp)
        self.assertEqual(config["workingBranch"], "main")
        self.assertEqual(config["verifyCommand"], "make verify")
        self.assertEqual(config["agents"], {"allowed": ["acme-*"], "models": {}, "writeFences": {}})
        self.assertEqual(config["commands"]["deny"], [{"match": "x y", "reason": "no"}])
        self.assertEqual(config["commands"]["alwaysAsk"], [])
        self.assertEqual(config["guards"], {"disable": []})
        self.assertEqual(config["records"], project_config.DEFAULTS["records"])
        self.assertEqual(config["reminder"], {"enabled": True, "text": project_config.DEFAULT_REMINDER})
        self.assertEqual(config["extra"], {"kept": True})

    def test_project_dir_comes_from_the_argument_then_the_env_then_the_cwd(self):
        with project('{"workingBranch": "env"}') as env_dir, project('{"workingBranch": "arg"}') as arg_dir:
            with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": env_dir}):
                self.assertEqual(project_config.load()["workingBranch"], "env")
                self.assertEqual(project_config.load(arg_dir)["workingBranch"], "arg")
            with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": ""}), chdir(env_dir):
                self.assertEqual(project_config.load()["workingBranch"], "env")

    def test_get_reads_a_value_of_the_right_type_and_falls_back_to_a_copy_of_the_default(self):
        config = {"agents": {"allowed": ["acme-*"], "models": ["not", "a", "dict"], "writeFences": None}, "guards": "x"}
        self.assertEqual(project_config.get(config, "agents", "allowed"), ["acme-*"])
        self.assertEqual(project_config.get(config, "agents", "models"), {})
        self.assertEqual(project_config.get(config, "agents", "writeFences"), {})
        self.assertEqual(project_config.get(config, "guards", "disable"), [])
        self.assertEqual(project_config.get({"reminder": {"enabled": "no", "text": 5}}, "reminder", "enabled"), True)
        self.assertEqual(project_config.get({"reminder": {"enabled": False}}, "reminder", "enabled"), False)
        self.assertEqual(project_config.get({"reminder": {"enabled": "no", "text": 5}}, "reminder", "text"), project_config.DEFAULT_REMINDER)
        self.assertEqual(project_config.get({}, "agents", "allowed"), ["*"])
        project_config.get({}, "agents", "allowed").append("x")
        self.assertEqual(project_config.DEFAULTS["agents"]["allowed"], ["*"])

    def test_example_config_is_complete_and_uses_only_known_keys(self):
        text = (ROOT / "examples" / "acme" / ".claude" / "agent-steddy.json").read_text()
        example = json.loads(text)
        for key, value in example.items():
            self.assertIn(key, project_config.DEFAULTS, key)
            if isinstance(value, dict):
                self.assertLessEqual(set(value), set(project_config.DEFAULTS[key]), key)
        with project(text) as tmp:
            self.assertEqual(project_config.load(tmp), {**project_config.DEFAULTS, **example})


if __name__ == "__main__":
    unittest.main()
