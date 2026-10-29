import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import secret_output_scan  # noqa: E402
import secret_patterns  # noqa: E402
from hook_runner import run_hook  # noqa: E402

# One synthetic secret per pattern, built at run time so that this file holds nothing a secret scanner would flag.
SECRETS = {
    "supabase-access-token": "sbp_" + "a1B2" * 10,
    "supabase-secret-key": "sb_secret_" + "Ab3_" * 6,
    "supabase-service-role-jwt": "eyJ" + "hbGciOiJIUzI1NiJ9" + "." + "eyJyb2xlIjoic2VydmljZV9yb2xlIn0" + "." + "s" * 20,
    "postgres-url-password": "postgres://app:" + "pw" * 8 + "@example.com",
    "npg-password": "npg_" + "Zy9x" * 5,
    "private-key": "-----BEGIN " + "RSA PRIVATE KEY-----",
    "aws-access-key-id": "AKIA" + "ABCD1234" * 2,
    "github-token": "ghp_" + "Ab1" * 12,
    "lemonsqueezy-api-key": "eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiJ9" + "." + "eyJ" + "a" * 60 + "." + "b" * 110,
    "revenuecat-secret-key": "sk_" + "Ab1" * 9,
    "sentry-auth-token": "sntrys_" + "Ab1" * 15,
    "posthog-personal-api-key": "phx_" + "Ab1" * 11,
}
# Text that must pass untouched: placeholders, short look-alikes, ordinary output.
HARMLESS = [
    "postgres://user:password@localhost:5432/app",
    "postgresql://user:changeme@example.com/app",
    "postgres://user:$DB_PASSWORD@example.com/app",
    "sbp_short", "npg_abc", "AKIA1234", "sk_live", "ghp_tooshort", "-----BEGIN CERTIFICATE-----",
    "On branch main\nnothing to commit, working tree clean\n", "", "Exit code 1\nError: Cannot find module 'express'",
]


def bash_output(stdout="", stderr="", **extra):
    return {"hook_event_name": "PostToolUse", "tool_name": "Bash", "tool_response": {"stdout": stdout, "stderr": stderr, "interrupted": False, "isImage": False, **extra}}


class Patterns(unittest.TestCase):
    def test_every_pattern_has_a_sample_and_the_sample_is_replaced_by_its_name(self):
        self.assertEqual(sorted(SECRETS), sorted(name for name, *_ in secret_patterns.load()))
        for name, secret in SECRETS.items():
            text, names = secret_patterns.redact(f"before {secret} after")
            self.assertEqual(text, f"before [REDACTED:{name}] after", name)
            self.assertEqual(names, [name], name)

    def test_placeholders_and_ordinary_output_are_left_alone(self):
        for text in HARMLESS:
            self.assertEqual(secret_patterns.redact(text), (text, []), text)

    def test_only_the_last_cap_characters_are_scanned(self):
        secret = SECRETS["supabase-access-token"]
        text = secret + " " + "x" * 50
        self.assertEqual(secret_patterns.find(text, cap=20), [])
        self.assertEqual(secret_patterns.redact(text, cap=20)[0], text)
        self.assertEqual(secret_patterns.find(text, cap=None), ["supabase-access-token"])
        self.assertEqual(secret_patterns.find("x" * 300 + secret, cap=100), ["supabase-access-token"])

    def test_the_patterns_load_without_a_warning(self):
        import subprocess
        out = subprocess.run([sys.executable, "-I", "-W", "error", "-c", "import sys; sys.path.insert(0, sys.argv[1]); import secret_patterns; secret_patterns.load()", str(ROOT / "scripts")],
                             capture_output=True, text=True)
        self.assertEqual((out.returncode, out.stderr), (0, ""))


class Scan(unittest.TestCase):
    def test_a_secret_on_stdout_or_stderr_is_replaced_and_named_after_a_successful_command(self):
        secret = SECRETS["npg-password"]
        for field in ("stdout", "stderr"):
            data = bash_output(**{field: f"url {secret} end"})
            output = secret_output_scan.scan(data)["hookSpecificOutput"]
            self.assertEqual(output["hookEventName"], "PostToolUse")
            self.assertIn("npg-password", output["additionalContext"])
            self.assertEqual(output["updatedToolOutput"][field], "url [REDACTED:npg-password] end")
            self.assertEqual({k: v for k, v in output["updatedToolOutput"].items() if k != field}, {k: v for k, v in data["tool_response"].items() if k != field})

    def test_other_fields_of_the_output_come_back_as_received(self):
        data = bash_output(stdout=SECRETS["github-token"], interrupted=True, bashEditDiff={"a": 1})
        replaced = secret_output_scan.scan(data)["hookSpecificOutput"]["updatedToolOutput"]
        self.assertEqual(replaced, {"stdout": "[REDACTED:github-token]", "stderr": "", "interrupted": True, "isImage": False, "bashEditDiff": {"a": 1}})

    def test_every_name_is_listed_once(self):
        secrets = [SECRETS["npg-password"], SECRETS["supabase-access-token"], SECRETS["npg-password"]]
        context = secret_output_scan.scan(bash_output(stdout=" ".join(secrets), stderr=secrets[0]))["hookSpecificOutput"]["additionalContext"]
        self.assertEqual(context.count("npg-password"), 1)
        self.assertEqual(context.count("supabase-access-token"), 1)

    def test_a_plain_string_response_is_scanned_too(self):
        data = {"hook_event_name": "PostToolUse", "tool_response": f"x {SECRETS['npg-password']}"}
        self.assertEqual(secret_output_scan.scan(data)["hookSpecificOutput"]["updatedToolOutput"], "x [REDACTED:npg-password]")

    def test_nothing_is_returned_when_the_output_holds_no_secret(self):
        for text in HARMLESS:
            self.assertIsNone(secret_output_scan.scan(bash_output(stdout=text, stderr=text)), text)
        for data in [{}, {"hook_event_name": "PostToolUse"}, {"tool_response": None}, {"tool_response": ["x"]}, bash_output(stdout=None, stderr=3)]:
            self.assertIsNone(secret_output_scan.scan(data), data)

    def test_after_a_failure_the_hook_warns_and_does_not_replace(self):
        secret = SECRETS["postgres-url-password"]
        data = {"hook_event_name": "PostToolUseFailure", "tool_name": "Bash", "error": f"Exit code 1\ncould not connect to {secret}"}
        output = secret_output_scan.scan(data)["hookSpecificOutput"]
        self.assertEqual(output["hookEventName"], "PostToolUseFailure")
        self.assertIn("postgres-url-password", output["additionalContext"])
        self.assertNotIn("updatedToolOutput", output)
        self.assertIsNone(secret_output_scan.scan({"hook_event_name": "PostToolUseFailure", "error": "Exit code 1\nboom"}))


class Hook(unittest.TestCase):
    """The script as Claude Code runs it: the output never holds a secret value."""

    def run_scan(self, data, raw=None):
        with tempfile.TemporaryDirectory() as tmp:
            return run_hook("secret_output_scan.py", data, tmp, raw)

    def test_no_secret_value_reaches_the_hook_output(self):
        for name, secret in SECRETS.items():
            for data in [bash_output(stdout=f"a {secret} b"), bash_output(stderr=f"a {secret} b"),
                         {"hook_event_name": "PostToolUseFailure", "tool_name": "Bash", "error": f"Exit code 1\na {secret} b"}]:
                out = self.run_scan(data)
                text = json.dumps(out)
                self.assertIn(name, out["hookSpecificOutput"]["additionalContext"], name)
                self.assertNotIn(secret, text, name)
                for fragment in (secret[8:20], secret[-8:]):
                    self.assertNotIn(fragment, text, name)

    def test_a_successful_command_gets_the_redacted_output_back(self):
        out = self.run_scan(bash_output(stdout=f"token {SECRETS['sentry-auth-token']}"))
        self.assertEqual(out["hookSpecificOutput"]["updatedToolOutput"]["stdout"], "token [REDACTED:sentry-auth-token]")

    def test_clean_output_prints_nothing(self):
        self.assertIsNone(self.run_scan(bash_output(stdout="ok")))

    def test_everything_fails_open_with_broken_input(self):
        for raw in ["not json", "", "[]", "null", '{"tool_response": 5}']:
            self.assertIsNone(self.run_scan(None, raw), raw)


if __name__ == "__main__":
    unittest.main()
