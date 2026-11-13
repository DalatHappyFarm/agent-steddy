import contextlib
import json
import os
import pathlib
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import local_state  # noqa: E402
import session_marker  # noqa: E402
from hook_runner import make_repo  # noqa: E402

NOW = time.time()  # the files these tests write have the real time, so the clock the code is given is the real one
DAY = 86400
SID = "0b1c2d3e-4f50-6172-8394-a5b6c7d8e9f0"
VERSION = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))["version"]


@contextlib.contextmanager
def folder():
    """A temp folder as a resolved path, so comparisons survive the /var to /private/var link on macOS."""
    with tempfile.TemporaryDirectory() as tmp:
        yield pathlib.Path(tmp).resolve()


def plugin(root, version="9.9.9"):
    """A made-up plugin root with a manifest of that version, and its path."""
    (root / ".claude-plugin").mkdir(parents=True)
    (root / ".claude-plugin" / "plugin.json").write_text(json.dumps({"version": version}))
    return root


def age(path, days):
    """Make a file `days` old at NOW."""
    os.utime(path, (NOW - days * DAY, NOW - days * DAY))


class Mark(unittest.TestCase):
    def test_the_marker_is_named_after_the_session_and_holds_the_plugin_root_and_its_version(self):
        with folder() as tmp:
            session_marker.mark(tmp / "state", SID, plugin(tmp / "plugin"), NOW)
            self.assertEqual(json.loads((tmp / "state" / "sessions" / SID).read_text()), {"root": str(tmp / "plugin"), "version": "9.9.9"})

    def test_the_root_defaults_to_the_code_that_runs(self):
        with folder() as tmp:
            session_marker.mark(tmp, SID, None, NOW)
            self.assertEqual(json.loads((tmp / "sessions" / SID).read_text()), {"root": str(ROOT), "version": VERSION})

    def test_a_root_is_stored_with_its_links_resolved(self):
        with folder() as tmp:
            plugin(tmp / "real")
            (tmp / "link").symlink_to(tmp / "real")
            session_marker.mark(tmp, SID, tmp / "link", NOW)
            self.assertEqual(json.loads((tmp / "sessions" / SID).read_text())["root"], str(tmp / "real"))

    def test_a_root_with_no_readable_manifest_has_the_version_unknown(self):
        with folder() as tmp:
            for index, text in enumerate([None, "not json", "[]", '{"name": "x"}', '{"version": 3}']):
                root = tmp / f"p{index}"
                (root / ".claude-plugin").mkdir(parents=True)
                if text is not None:
                    (root / ".claude-plugin" / "plugin.json").write_text(text)
                session_marker.mark(tmp, f"s{index}", root, NOW)
                self.assertEqual(json.loads((tmp / "sessions" / f"s{index}").read_text())["version"], "unknown", text)

    def test_an_unchanged_marker_is_not_written_again(self):
        with folder() as tmp:
            session_marker.mark(tmp, SID, plugin(tmp / "plugin"), NOW)
            marker = tmp / "sessions" / SID
            age(marker, 3)
            session_marker.mark(tmp, SID, tmp / "plugin", NOW)
            self.assertEqual(marker.stat().st_mtime, NOW - 3 * DAY)

    def test_a_marker_that_differs_is_written_again(self):
        with folder() as tmp:
            marker = tmp / "sessions" / SID
            session_marker.mark(tmp, SID, plugin(tmp / "old", "1.0.0"), NOW)
            session_marker.mark(tmp, SID, plugin(tmp / "new", "2.0.0"), NOW)  # the session now has another plugin root
            self.assertEqual(json.loads(marker.read_text()), {"root": str(tmp / "new"), "version": "2.0.0"})
            for damaged in ("garbage", ""):
                marker.write_text(damaged)
                session_marker.mark(tmp, SID, tmp / "new", NOW)
                self.assertEqual(json.loads(marker.read_text()), {"root": str(tmp / "new"), "version": "2.0.0"}, damaged)

    def test_each_session_has_its_own_marker(self):
        with folder() as tmp:
            session_marker.mark(tmp, "one", plugin(tmp / "a", "1.0.0"), NOW)
            session_marker.mark(tmp, "two", plugin(tmp / "b", "2.0.0"), NOW)
            self.assertEqual({p.name: json.loads(p.read_text())["version"] for p in (tmp / "sessions").iterdir()}, {"one": "1.0.0", "two": "2.0.0"})

    def test_a_marker_older_than_30_days_is_pruned_when_another_is_written(self):
        with folder() as tmp:
            sessions = tmp / "sessions"
            sessions.mkdir()
            for name, days in [("stale", 31), ("edge", 29), ("fresh", 0)]:
                (sessions / name).write_text("{}")
                age(sessions / name, days)
            session_marker.mark(tmp, SID, None, NOW)
            self.assertEqual(session_marker.MARKER_DAYS, 30)
            self.assertEqual(sorted(p.name for p in sessions.iterdir()), sorted(["edge", "fresh", SID]))

    def test_nothing_is_pruned_while_the_marker_is_unchanged(self):
        with folder() as tmp:
            session_marker.mark(tmp, SID, None, NOW)
            (tmp / "sessions" / "stale").write_text("{}")
            age(tmp / "sessions" / "stale", 40)
            session_marker.mark(tmp, SID, None, NOW)  # nothing to write, so nothing to prune: the check stays cheap
            self.assertTrue((tmp / "sessions" / "stale").exists())

    def test_the_marker_just_written_is_never_pruned_even_when_the_clock_runs_ahead_of_the_file_system(self):
        with folder() as tmp:
            (tmp / "sessions").mkdir()
            (tmp / "sessions" / "stale").write_text("{}")
            session_marker.mark(tmp, SID, None, NOW + 40 * DAY)
            self.assertEqual([p.name for p in (tmp / "sessions").iterdir()], [SID])

    def test_a_session_id_cannot_name_a_file_outside_the_folder(self):
        with folder() as tmp:
            session_marker.mark(tmp / "state", "../../escape/x", None, NOW)
            self.assertEqual([p.relative_to(tmp).parts[:2] for p in tmp.rglob("*") if p.is_file()], [("state", "sessions")])

    def test_no_session_id_or_no_state_writes_nothing_and_raises_nothing(self):
        with folder() as tmp:
            for state, session_id in [(tmp / "a", None), (tmp / "b", ""), (tmp / "c", 7), (None, SID)]:
                session_marker.mark(state, session_id, None, NOW)
            self.assertEqual(list(tmp.iterdir()), [])

    def test_a_state_folder_that_cannot_be_written_raises_nothing(self):
        with folder() as tmp:
            (tmp / "state").write_text("a file where the folder should be")
            session_marker.mark(tmp / "state", SID, None, NOW)
            self.assertEqual((tmp / "state").read_text(), "a file where the folder should be")


class Status(unittest.TestCase):
    def check(self, root, session=SID):
        """(status, warning, selftest line) for a project, in a process that has this session id, or none."""
        env = {key: value for key, value in os.environ.items() if key not in ("CLAUDE_CODE_SESSION_ID", "CLAUDE_PLUGIN_DATA")}
        if session:
            env["CLAUDE_CODE_SESSION_ID"] = session
        with mock.patch.dict(os.environ, env, clear=True):
            return session_marker.status(root), session_marker.warning(root), session_marker.selftest_line(root)

    def test_a_session_without_a_marker_is_not_live(self):
        with folder() as root:
            make_repo(root)
            found, warning, line = self.check(root)
            self.assertEqual((found, warning), ((False, None), session_marker.NO_MARKER))
            self.assertIn("did not run in this session", warning)
            self.assertIn("start a new Claude Code session in this project", warning)
            self.assertEqual(line, session_marker.NOT_LIVE)

    def test_the_marker_of_this_code_is_live_and_says_nothing(self):
        with folder() as root:
            make_repo(root)
            session_marker.mark(local_state.state_dir(root), SID, None, NOW)
            found, warning, line = self.check(root)
            self.assertEqual((found, warning), ((True, {"root": str(ROOT), "version": VERSION}), None))
            self.assertEqual(line, f"hooks live in this session: yes, version {VERSION}")

    def test_the_marker_of_another_copy_names_both_versions_and_both_paths(self):
        with folder() as root:
            make_repo(root)
            session_marker.mark(local_state.state_dir(root), SID, plugin(root / "elsewhere"), NOW)
            _, warning, line = self.check(root)
            self.assertEqual(warning, f"agent-steddy: this is version {VERSION} at {ROOT}, but this session's hooks run version 9.9.9 at {root / 'elsewhere'}; call `agent-steddy` by name, not through a cache path.")
            self.assertEqual(line, f"hooks live in this session: yes, version 9.9.9, but this command is version {VERSION} at {ROOT}, not the copy at {root / 'elsewhere'} that the hooks run; call `agent-steddy` by name, not through a cache path")

    def test_it_cannot_be_told_without_a_session_id_without_a_state_folder_or_with_a_marker_it_cannot_read(self):
        with folder() as root:
            make_repo(root)
            self.assertEqual(self.check(root, session=None), (None, None, session_marker.NOT_CHECKED))
            with folder() as no_repo:
                self.assertEqual(self.check(no_repo), (None, None, session_marker.NOT_CHECKED))
            marker = local_state.state_dir(root) / "sessions" / SID
            marker.parent.mkdir(parents=True)
            for text in ("garbage", "[]", "{}", '{"root": 3}', ""):
                marker.write_text(text)
                self.assertEqual(self.check(root), (None, None, session_marker.NOT_CHECKED), text)


if __name__ == "__main__":
    unittest.main()
