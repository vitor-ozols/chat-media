from __future__ import annotations

import tempfile
import json
import os
import unittest
from unittest.mock import patch
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from media_manager.codex_sdk import CodexSDK, _history_messages, _rollout_messages, _skill_name, _progress_event


class CodexHistoryTests(unittest.TestCase):
    def test_reads_paginated_rollout_without_tool_or_commentary_output(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / "sessions").mkdir()
            rollout = home / "sessions" / "test.jsonl"
            items = [
                {"type": "UserMessage", "content": [{"type": "text", "text": "Olá"}]},
                {"type": "AgentMessage", "phase": "commentary", "content": [{"text": "Pensando"}]},
                {"type": "CommandExecution", "stdout": "private tool output"},
                {"type": "AgentMessage", "phase": "final_answer", "content": [{"text": "Resposta"}]},
            ]
            rollout.write_text("\n".join(json.dumps({"type": "event_msg", "payload": {
                "type": "item_completed", "turn_id": "turn1", "item": item,
            }}) for item in items) + '\n{"partial":')
            with patch.dict(os.environ, {"CODEX_HOME": directory}):
                self.assertEqual(_rollout_messages(str(rollout)), [
                    {"role": "user", "content": "Olá"},
                    {"role": "assistant", "content": "Resposta"},
                ])
                self.assertEqual(_rollout_messages(str(home / "outside.jsonl")), [])

    def test_reads_current_sdk_thread_items(self) -> None:
        response = {
            "thread": {
                "turns": [
                    {
                        "items": [
                            {
                                "type": "userMessage",
                                "content": [{"type": "text", "text": "Olá"}],
                            },
                            {
                                "type": "agentMessage",
                                "phase": "commentary",
                                "text": "Pensando…",
                            },
                            {
                                "type": "agentMessage",
                                "phase": "final_answer",
                                "text": "Tudo certo.",
                            },
                        ]
                    }
                ]
            }
        }

        self.assertEqual(
            _history_messages(response),
            [
                {"role": "user", "content": "Olá"},
                {"role": "assistant", "content": "Tudo certo."},
            ],
        )

    def test_unwraps_root_content_and_uses_legacy_agent_fallback(self) -> None:
        response = {
            "thread": {
                "turns": [
                    {
                        "items": [
                            {
                                "type": "userMessage",
                                "content": [{"root": {"type": "text", "text": "Teste"}}],
                            },
                            {"type": "agentMessage", "text": "Resposta antiga"},
                        ]
                    }
                ]
            }
        }

        self.assertEqual(
            _history_messages(response),
            [
                {"role": "user", "content": "Teste"},
                {"role": "assistant", "content": "Resposta antiga"},
            ],
        )


class SkillDiscoveryTests(unittest.TestCase):
    def test_reads_skill_name_from_frontmatter(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            skill_file = Path(directory) / "SKILL.md"
            skill_file.write_text(
                "---\nname: minha-skill\ndescription: Teste\n---\n",
                encoding="utf-8",
            )
            self.assertEqual(_skill_name(skill_file), "minha-skill")


class ProgressEventsTests(unittest.TestCase):
    def test_command_lifecycle_and_message_deltas(self):
        phases = {}
        command = {"item": {"type": "commandExecution", "id": "cmd", "command": "ls media", "status": "inProgress"}}
        event = _progress_event("item/started", command, phases)
        self.assertEqual(event["detail"], "ls media")
        self.assertFalse(event["done"])
        self.assertTrue(_progress_event("item/completed", command, phases)["done"])
        _progress_event("item/started", {"item": {"type": "agentMessage", "id": "a", "phase": "commentary"}}, phases)
        self.assertEqual(_progress_event("item/agentMessage/delta", {"item_id": "a", "delta": "Olá"}, phases),
                         {"type": "message", "id": "a", "phase": "commentary", "delta": "Olá"})

    def test_reasoning_content_is_never_forwarded(self):
        self.assertIsNone(_progress_event("item/reasoning/textDelta", {"delta": "private"}, {}))
        event = _progress_event("item/started", {"item": {"type": "reasoning", "id": "r", "content": "private", "summary": "private"}}, {})
        self.assertNotIn("private", json.dumps(event))

    def test_file_changes_and_plan_are_normalized(self):
        event = _progress_event("item/completed", {"item": {"type": "fileChange", "id": "f", "changes": [{"path": "app.py"}]}}, {})
        self.assertEqual(event["detail"], "app.py")
        plan = _progress_event("turn/plan/updated", {"plan": [{"step": "Testar", "status": "inProgress"}]}, {})
        self.assertEqual(plan["steps"], [{"step": "Testar", "status": "inProgress"}])

    def test_real_sdk_payload_models_and_streamed_result(self):
        try:
            from openai_codex.generated.v2_all import AgentMessageDeltaNotification, ItemStartedNotification
        except ImportError:
            self.skipTest("SDK not installed")
        started = ItemStartedNotification.model_validate({"threadId": "t", "turnId": "turn", "startedAtMs": 0,
            "item": {"type": "agentMessage", "id": "a", "phase": "final_answer", "text": ""}})
        delta = AgentMessageDeltaNotification.model_validate({"threadId": "t", "turnId": "turn", "itemId": "a", "delta": "Resposta"})
        notifications = [SimpleNamespace(method="item/started", payload=started),
            SimpleNamespace(method="item/agentMessage/delta", payload=delta),
            SimpleNamespace(method="item/completed", payload={"item": {"type": "agentMessage", "id": "a", "phase": "final_answer", "text": "Resposta"}}),
            SimpleNamespace(method="turn/completed", payload={"turn": {"status": "completed"}})]
        turn, thread, client = Mock(), Mock(), Mock()
        turn.stream.return_value = iter(notifications)
        thread.id = "t"
        thread.turn.return_value = turn
        client.thread_start.return_value = thread
        context = Mock()
        context.__enter__ = Mock(return_value=client)
        context.__exit__ = Mock(return_value=False)
        sdk, events, handles = CodexSDK(Path(".")), [], []
        with patch.object(sdk, "_client", return_value=context), patch.object(sdk, "list_skills", return_value=[]):
            result = sdk.ask("Olá", None, on_event=events.append, on_turn=handles.append)
        self.assertEqual(result.reply, "Resposta")
        self.assertEqual(handles, [turn])
        self.assertTrue(any(event.get("delta") == "Resposta" and event["id"] == "a" for event in events))
        thread.run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
