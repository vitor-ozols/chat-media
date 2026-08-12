from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from media_manager.codex_sdk import _history_messages, _skill_name


class CodexHistoryTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
