import contextlib
import json
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import evals  # noqa: E402
import project_config  # noqa: E402
from local_state import Refuse  # noqa: E402

CONFIG = project_config.DEFAULTS

# A stand-in for `claude -p`: it logs its arguments, answers well only when the prompt carries the lesson, and judges by that answer.
FAKE_CLAUDE = """#!/usr/bin/env python3
import json, os, sys
text = sys.stdin.read()
with open(os.environ["FAKE_CLAUDE_LOG"], "a") as log:
    log.write(json.dumps({"args": sys.argv[1:], "cwd": os.getcwd(), "judge": "Reply with PASS or FAIL" in text}) + "\\n")
if os.environ.get("FAKE_CLAUDE_FAIL"):
    sys.exit(1)
if "Reply with PASS or FAIL" in text:
    print("PASS\\nthe status is captured" if "STATUS-CAPTURED" in text else "FAIL\\nit reports the exit code of date")
else:
    print("STATUS-CAPTURED" if "test-exit-status" in text else "echo done")
"""

LESSONS = """# Lessons

## 2026-10-31 - console - roles: web
- Rule [test-exit-status]: read a run's exit status before reporting it [promoted -> docs/agents/walls.md]
  - When: about to report that a test or eval run passed
"""


def case(key="test-exit-status", kind="seen", check=None, prompt="Write a script that runs the eval and reports whether the run passed.", criteria="- It reads the exit status before any other command."):
    lines = ["# a case", "", f"- Key: {key}", f"- Kind: {kind}"] + ([f"- Check: {check}"] if check else [])
    if prompt:
        lines += ["", "## Prompt", "", prompt]
    if criteria:
        lines += ["", "## Criteria", "", criteria]
    return "\n".join(lines) + "\n"


@contextlib.contextmanager
def project(cases=None, lessons=LESSONS):
    """A temp project with a lessons file, a walls file and eval cases (file name -> text), and a fake claude first on the PATH."""
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp).resolve()
        (root / "docs/agents/evals").mkdir(parents=True)
        (root / "docs/agents/lessons.md").write_text(lessons)
        (root / "docs/agents/walls.md").write_text("# Walls\n\n- WALL-TEXT: never push.\n")
        for name, text in (cases or {}).items():
            (root / "docs/agents/evals" / name).write_text(text)
        fake = root / "bin"
        fake.mkdir()
        (fake / "claude").write_text(FAKE_CLAUDE)
        (fake / "claude").chmod(0o755)
        with mock.patch.dict(os.environ, {"PATH": f"{fake}{os.pathsep}{os.environ['PATH']}", "FAKE_CLAUDE_LOG": str(root / "claude.log")}):
            yield root


def calls(root):
    path = root / "claude.log"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


class ParseCase(unittest.TestCase):
    def test_the_fields_and_the_sections_are_read(self):
        got = evals.parse_case(pathlib.Path("c.md"), case(check="make test") + "\n## Notes\n\nleft out\n")
        self.assertEqual((got.key, got.kind, got.check, got.prompt, got.criteria, got.problem),
                         ("test-exit-status", "seen", "make test", "Write a script that runs the eval and reports whether the run passed.", "- It reads the exit status before any other command.", None))

    def test_a_broken_case_names_its_problem(self):
        cases = {
            case(key="Bad Key"): "no valid `- Key: <key>` line",
            case(kind="old"): "`- Kind:` must be seen or new",
            case(prompt=""): "it needs a `- Check: <command>` line, or a `## Prompt` and a `## Criteria` section",
            case(criteria=""): "it needs a `- Check: <command>` line",
            "": "no valid `- Key: <key>` line",
        }
        for text, problem in cases.items():
            self.assertIn(problem, evals.parse_case(pathlib.Path("c.md"), text).problem, text)
        self.assertIsNone(evals.parse_case(pathlib.Path("c.md"), case(prompt="", criteria="", check="true")).problem)

    def test_case_keys_skip_broken_cases_and_a_missing_folder(self):
        with project({"a.md": case(key="good-key", check="true"), "b.md": case(key="Bad Key")}) as root:
            self.assertEqual(evals.case_keys(root / "docs/agents/evals"), {"good-key"})
            self.assertEqual(evals.case_keys(root / "nope"), set())


class Run(unittest.TestCase):
    def test_checks_run_in_the_project_root_and_a_failure_shows_its_output_and_fails_the_run(self):
        with project({"a.md": case(check="test -f docs/agents/lessons.md"), "b.md": case(kind="new", check="echo it broke; exit 3")}) as root:
            lines, ok = evals.run(root, CONFIG)
            self.assertFalse(ok)
            self.assertEqual(lines, [
                "PASS    test-exit-status (seen) docs/agents/evals/a.md",
                "FAIL    test-exit-status (new) docs/agents/evals/b.md",
                "    exit 3",
                "    it broke",
                "",
                "summary: seen: 1 of 1 passed; new: 0 of 1 passed",
            ])

    def test_without_judge_a_prompt_case_is_listed_for_review_and_does_not_fail(self):
        with project({"a.md": case()}) as root:
            lines, ok = evals.run(root, CONFIG)
            self.assertTrue(ok)
            self.assertTrue(lines[0].startswith("REVIEW  test-exit-status (seen) docs/agents/evals/a.md: no Check; run with --judge"), lines)
            self.assertEqual(lines[-1], "summary: seen: 0 of 0 passed, 1 to review")
            self.assertEqual(calls(root), [])

    def test_judge_answers_with_the_walls_and_the_found_lessons_in_an_empty_folder_then_judges(self):
        with project({"a.md": case()}) as root:
            lines, ok = evals.run(root, CONFIG, judge=True, model="haiku")
            self.assertTrue(ok, lines)
            self.assertEqual(lines[:2], ["PASS    test-exit-status (seen) docs/agents/evals/a.md", "    the status is captured"])
            answer, verdict = calls(root)
            self.assertEqual((answer["judge"], verdict["judge"]), (False, True))
            self.assertEqual(answer["args"], ["-p", "--tools", "", "--no-session-persistence", "--setting-sources", "", "--strict-mcp-config", "--model", "haiku"])
            self.assertNotIn("--model", verdict["args"])  # the judge stays on the default model
            self.assertNotEqual(pathlib.Path(answer["cwd"]).resolve(), root)  # no project hooks, no task clock
            prompt = evals.answer_prompt(root, CONFIG, case().split("## Prompt\n\n")[1].split("\n")[0])
            self.assertTrue(prompt.startswith(evals.ANSWER + "\n\n# Walls"), prompt[:200])
            self.assertIn("WALL-TEXT", prompt)
            self.assertIn("Lessons this project recorded that may apply:\ntest-exit-status (seen 1 time, promoted -> docs/agents/walls.md)", prompt)
            self.assertTrue(prompt.endswith("Task:\nWrite a script that runs the eval and reports whether the run passed."))

    def test_bare_answers_without_the_walls_and_the_lessons(self):
        with project({"a.md": case()}) as root:
            self.assertEqual(evals.answer_prompt(root, CONFIG, "report the run", bare=True), evals.ANSWER + "\n\nTask:\nreport the run")
            lines, ok = evals.run(root, CONFIG, judge=True, bare=True)
            self.assertFalse(ok)  # the fake answers well only with the lesson in its prompt
            self.assertEqual(lines[-1], "summary: seen: 0 of 1 passed (bare: answered without the walls and the lessons)")

    def test_judge_fails_a_case_whose_lesson_recall_does_not_reach(self):
        with project({"a.md": case(kind="new")}, lessons="# Lessons\n") as root:
            lines, ok = evals.run(root, CONFIG, judge=True)
            self.assertFalse(ok)
            self.assertEqual(lines[:2], ["FAIL    test-exit-status (new) docs/agents/evals/a.md", "    it reports the exit code of date"])
            self.assertNotIn("Lessons this project recorded", evals.answer_prompt(root, CONFIG, "report the run"))

    def test_a_failing_or_missing_claude(self):
        with project({"a.md": case()}) as root:
            with mock.patch.dict(os.environ, {"FAKE_CLAUDE_FAIL": "1"}):
                lines, ok = evals.run(root, CONFIG, judge=True)
            self.assertEqual((lines[:2], ok), (["FAIL    test-exit-status (seen) docs/agents/evals/a.md", "    claude failed or timed out while answering"], False))
            with mock.patch.dict(os.environ, {"PATH": str(root / "nowhere")}):
                with self.assertRaises(Refuse) as caught:
                    evals.run(root, CONFIG, judge=True)
            self.assertIn("claude is not on the PATH", str(caught.exception))

    def test_a_broken_case_fails_the_run_and_key_picks_the_cases(self):
        with project({"a.md": case(key="Bad Key"), "b.md": case(key="other", check="true")}) as root:
            lines, ok = evals.run(root, CONFIG)
            self.assertFalse(ok)
            self.assertEqual(lines[0], "BAD     Bad Key (seen) docs/agents/evals/a.md: no valid `- Key: <key>` line")
            self.assertEqual(evals.run(root, CONFIG, key="other"), (["PASS    other (seen) docs/agents/evals/b.md", "", "summary: seen: 1 of 1 passed"], True))
            lines, ok = evals.run(root, CONFIG, key="missing")
            self.assertTrue(ok)
            self.assertTrue(lines[0].startswith("no eval case for missing in docs/agents/evals"), lines)


if __name__ == "__main__":
    unittest.main()
