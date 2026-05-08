from __future__ import annotations

from typing import Any


DEFAULT_MODEL = "gemini-2.5-flash"
DOCUMENTED_CHAT_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-2.5-flash-lite-preview-09-2025",
    "gemini-3-flash-preview",
    "gemini-3-pro-preview",
    "gemini-2.0-flash",
]


def _import_genai() -> Any:
    from google import genai

    return genai


def build_client(api_key: str | None = None) -> Any | None:
    try:
        genai = _import_genai()
    except Exception:
        return None
    return genai.Client(api_key=api_key or None)


def list_model_choices(api_key: str | None = None) -> list[str]:
    client = build_client(api_key)
    if client is None:
        return DOCUMENTED_CHAT_MODELS

    try:
        models = []
        for item in client.models.list():
            name = getattr(item, "name", "")
            actions = list(getattr(item, "supported_actions", []) or [])
            if not name.startswith("models/"):
                continue
            short_name = name.split("/", 1)[1]
            if "generateContent" not in actions:
                continue
            if any(part in short_name for part in ("image", "tts", "embedding", "aqa")):
                continue
            models.append(short_name)
        return sorted(set(models)) or DOCUMENTED_CHAT_MODELS
    except Exception:
        return DOCUMENTED_CHAT_MODELS


def generate_reply(
    messages: list[dict[str, str]],
    model: str,
    api_key: str | None = None,
    system_instruction: str | None = None,
) -> str:
    client = build_client(api_key)
    if client is None:
        return (
            "Nao consegui usar o Gemini porque a biblioteca `google-genai` nao esta instalada. "
            "Mesmo assim, a acao pedida foi processada localmente quando possivel."
        )

    prompt = []
    if system_instruction:
        prompt.append({"role": "user", "parts": [{"text": system_instruction}]})
    for item in messages:
        role = "model" if item["role"] == "assistant" else "user"
        prompt.append({"role": role, "parts": [{"text": item["content"]}]})

    try:
        response = client.models.generate_content(model=model, contents=prompt)
        text = getattr(response, "text", None)
        return text or "O Gemini nao retornou texto."
    except Exception as exc:
        return f"Falha ao consultar o Gemini: {exc}"
