import json
import threading
import unittest
from unittest.mock import patch

from media_manager.chat_runs import ChatRun, ChatRuns
from support import FakeSDK


def events(run, after=0):
    return [json.loads(line[6:]) for chunk in run.stream(after) for line in chunk.splitlines() if line.startswith("data: ")]


class ChatRunsTests(unittest.TestCase):
    def setUp(self):
        self.sdk = FakeSDK()
        self.runs = ChatRuns(self.sdk)
        self.addCleanup(lambda: self.runs.executor.shutdown(wait=True))
        self.addCleanup(self.sdk.release.set)

    def test_streams_progress_and_replays_finished_turn(self):
        run = self.runs.start({"prompt": "oi"})
        first = events(run)
        self.assertEqual(first[-1]["type"], "done")
        self.assertTrue(any(item["type"] == "activity" for item in first))
        self.assertTrue(any(item.get("delta") for item in first))
        self.assertEqual(events(run), first)
        self.assertEqual(events(run, run.sequence), [])

    def test_interrupts_real_turn_and_emits_cancelled(self):
        self.sdk.block = True
        run = self.runs.start({"prompt": "oi"})
        self.assertTrue(self.sdk.started.wait(2))
        run.cancel()
        self.assertEqual(events(run)[-1]["type"], "cancelled")
        self.assertTrue(self.sdk.interrupted.is_set())
        run.cancel()  # Idempotent after completion.

    def test_cancel_before_handle_attaches_interrupts_on_attach(self):
        run = ChatRun("test", {})
        interrupted = threading.Event()
        run.cancel()
        run.attach(type("Turn", (), {"interrupt": lambda _: interrupted.set()})())
        self.assertTrue(interrupted.is_set())

    def test_busy_thread_and_concurrency_limit_reject_duplicate_work(self):
        self.sdk.block = True
        self.runs.start({"prompt": "first", "thread_id": "same"})
        with self.assertRaises(RuntimeError):
            self.runs.start({"prompt": "second", "thread_id": "same"})
        self.runs.start({"prompt": "different", "thread_id": "different"})
        with self.assertRaises(RuntimeError):
            self.runs.start({"prompt": "third"})

    def test_failure_remains_a_failure_instead_of_an_assistant_reply(self):
        run = self.runs.start({"prompt": "falhar"})
        self.assertEqual(events(run)[-1], {"type": "failure", "error": "Falha de teste", "thread_id": "thread-live"})

    def test_completed_run_expires_without_losing_active_work(self):
        run = self.runs.start({"prompt": "oi"})
        events(run)
        with patch("media_manager.chat_runs.time.monotonic", return_value=run.finished_at + 3601):
            self.assertIsNone(self.runs.get(run.id))

    def test_reconnect_after_ring_wrap_receives_snapshot_and_outcome(self):
        run = ChatRun("test", {})
        for index in range(8005):
            run.emit({"type": "message", "id": "a", "delta": str(index % 10)})
        run.outcome = {"type": "done", "reply": "ok"}
        run.emit(run.outcome)
        run.state = "completed"
        replay = events(run)
        self.assertEqual(replay[0]["type"], "snapshot")
        self.assertEqual(len(replay[0]["messages"][0]["text"]), 8005)
        self.assertEqual(replay[-1]["type"], "done")

    def test_slow_subscriber_recovers_when_ring_wraps_while_waiting(self):
        run = ChatRun("test", {})
        def burst(timeout):
            for _ in range(8005):
                run.emit({"type": "message", "id": "a", "delta": "x"})
            run.state = "completed"
            return True
        with patch.object(run.condition, "wait", side_effect=burst):
            replay = events(run)
        self.assertEqual(replay[0]["type"], "snapshot")
        self.assertEqual(len(replay[0]["messages"][0]["text"]), 8005)
