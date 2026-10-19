from __future__ import annotations

import json
import threading
import time
import uuid
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ChatRun:
    id: str
    options: dict[str, Any]
    events: deque = field(default_factory=lambda: deque(maxlen=8000))
    condition: threading.Condition = field(default_factory=threading.Condition)
    state: str = "running"
    sequence: int = 0
    finished_at: float = 0
    turn: Any = None
    cancel_requested: bool = False
    thread_id: str | None = None
    messages: dict = field(default_factory=dict)
    activities: dict = field(default_factory=dict)
    plan: dict | None = None
    outcome: dict | None = None

    def emit(self, event: dict) -> None:
        with self.condition:
            if event["type"] == "thread":
                self.thread_id = event["thread_id"]
            elif event["type"] == "message":
                message = self.messages.setdefault(event["id"], {"type": "message", "id": event["id"], "text": ""})
                message["phase"] = event.get("phase", "")
                message["text"] = event.get("text", message["text"] + event.get("delta", ""))
            elif event["type"] == "activity":
                self.activities[event["id"]] = event
            elif event["type"] == "plan":
                self.plan = event
            self.sequence += 1
            self.events.append((self.sequence, event))
            self.condition.notify_all()

    def attach(self, turn: Any) -> None:
        with self.condition:
            self.turn = turn
            cancel = self.cancel_requested
        if cancel:
            turn.interrupt()

    def cancel(self) -> None:
        with self.condition:
            if self.state != "running" or self.cancel_requested:
                return
            self.cancel_requested = True
            turn = self.turn
        try:
            if turn:
                turn.interrupt()
        except Exception:
            with self.condition:
                self.cancel_requested = False
            raise

    def stream(self, after: int = 0):
        """Replay on reconnect. Snapshot recovers even after the event ring wraps."""
        while True:
            with self.condition:
                if self.events and after < self.events[0][0] - 1:
                    snapshot = {"type": "snapshot", "thread_id": self.thread_id,
                                "messages": list(self.messages.values()),
                                "activities": list(self.activities.values()), "plan": self.plan}
                    batch = [(self.sequence, snapshot)]
                    if self.outcome:
                        batch.append((self.sequence, self.outcome))
                else:
                    batch = [(seq, event) for seq, event in self.events if seq > after]
                finished = self.state != "running"
                if not batch and not finished:
                    if self.condition.wait(timeout=15):
                        continue  # Recheck ring overflow after a producer wakes us.
            for seq, event in batch:
                yield f"id: {seq}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                after = seq
            if finished:
                return
            if not batch:
                yield ": keepalive\n\n"


class ChatRuns:
    def __init__(self, sdk):
        self.sdk = sdk
        self.runs: dict[str, ChatRun] = {}
        self.lock = threading.Lock()
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="chat-agent")

    def get(self, run_id: str) -> ChatRun | None:
        with self.lock:
            run = self.runs.get(run_id)
            if run and run.finished_at and time.monotonic() - run.finished_at >= 3600:
                self.runs.pop(run_id, None)
                return None
            return run

    def start(self, options: dict) -> ChatRun:
        with self.lock:
            now = time.monotonic()
            self.runs = {key: run for key, run in self.runs.items()
                         if not run.finished_at or now - run.finished_at < 3600}
            active = [run for run in self.runs.values() if run.state == "running"]
            thread_id = options.get("thread_id")
            if len(active) >= 2 or any(thread_id and run.thread_id == thread_id for run in active):
                raise RuntimeError("O agente já está ocupado. Aguarde a execução atual.")
            completed = [run for run in self.runs.values() if run.finished_at]
            for old in sorted(completed, key=lambda run: run.finished_at)[:-20]:
                self.runs.pop(old.id, None)
            run = ChatRun(uuid.uuid4().hex, options, thread_id=thread_id)
            self.runs[run.id] = run
            self.executor.submit(self._work, run)
            return run

    def _work(self, run: ChatRun) -> None:
        run.emit({"type": "status", "label": "Conectando ao agente"})
        try:
            result = self.sdk.ask(**run.options, on_event=run.emit, on_turn=run.attach)
            outcome = {"type": "done", "reply": result.reply, "thread_id": result.thread_id}
            state = "completed"
        except InterruptedError:
            outcome, state = {"type": "cancelled", "thread_id": run.thread_id}, "cancelled"
        except Exception as exc:
            outcome, state = {"type": "failure", "error": str(exc), "thread_id": run.thread_id}, "failed"
        with run.condition:
            run.outcome = outcome
            run.emit(outcome)
            run.state = state
            run.finished_at = time.monotonic()
            run.condition.notify_all()
