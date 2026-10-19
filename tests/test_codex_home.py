import sqlite3
import tempfile
import unittest
from pathlib import Path

from media_manager.codex_home import import_home
from media_manager.codex_sdk import CodexSetupError, _raise_known_sdk_error


class ImportHomeTests(unittest.TestCase):
    def test_preserves_source_and_skips_corrupt_projection(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory) / "source", Path(directory) / "target"
            (source / "sessions").mkdir(parents=True)
            rollout = source / "sessions" / "test.jsonl"
            rollout.write_text('{}\n')
            (source / "thread_history_1.sqlite").write_bytes(b"corrupt")
            with sqlite3.connect(source / "state_5.sqlite") as db:
                db.execute("CREATE TABLE threads (id TEXT, rollout_path TEXT)")
                db.execute("INSERT INTO threads VALUES (?, ?)", ("test", str(rollout)))
            import_home(source, target)
            self.assertFalse((target / "thread_history_1.sqlite").exists())
            self.assertEqual((source / "thread_history_1.sqlite").read_bytes(), b"corrupt")
            with sqlite3.connect(target / "state_5.sqlite") as db:
                self.assertEqual(db.execute("SELECT rollout_path FROM threads").fetchone()[0],
                                 str(target / "sessions" / "test.jsonl"))
            with self.assertRaises(ValueError):
                import_home(source, target)
            with self.assertRaises(ValueError):
                import_home(source, source / "nested")

    def test_corruption_is_reported_without_resetting_state(self):
        with self.assertRaisesRegex(CodexSetupError, "corrompido"):
            _raise_known_sdk_error(RuntimeError("database disk image is malformed"))
