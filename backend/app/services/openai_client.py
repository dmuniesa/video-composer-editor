"""OpenAI-compatible chat-completions client (works with z.ai GLM, OpenAI,
OpenRouter, Ollama, LM Studio... anything speaking /chat/completions).

Frames are sent inline as base64 data URLs, the standard vision-message
format. A custom httpx transport can be injected for tests."""
from __future__ import annotations

import base64
from pathlib import Path

import httpx

from .. import settings


class OpenAIError(RuntimeError):
    pass


def configured() -> bool:
    ai = settings.get().ai
    return bool(ai.openai_base_url and ai.openai_model)


def _image_part(path: Path) -> dict:
    b64 = base64.b64encode(path.read_bytes()).decode()
    return {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}


def chat(prompt: str, images: list[Path] | None = None, transport: httpx.BaseTransport | None = None) -> str:
    """One-shot chat completion. Returns the assistant text."""
    ai = settings.get().ai
    if not configured():
        raise OpenAIError(
            "OpenAI-compatible endpoint not configured (base URL and model are required)"
        )
    content: list[dict] | str
    if images:
        content = [{"type": "text", "text": prompt}] + [_image_part(p) for p in images]
    else:
        content = prompt

    url = ai.openai_base_url.rstrip("/") + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    if ai.openai_api_key:
        headers["Authorization"] = f"Bearer {ai.openai_api_key}"

    try:
        with httpx.Client(transport=transport, timeout=ai.timeout_s) as client:
            res = client.post(
                url,
                headers=headers,
                json={
                    "model": ai.openai_model,
                    "messages": [{"role": "user", "content": content}],
                    "temperature": 0.4,
                },
            )
    except httpx.HTTPError as exc:
        raise OpenAIError(f"request to {url} failed: {exc}") from exc

    if res.status_code != 200:
        raise OpenAIError(f"{url} returned {res.status_code}: {res.text[:300]}")
    try:
        data = res.json()
        message = data["choices"][0]["message"]
        text = message.get("content") or ""
        # Some providers return reasoning models' content as a list of parts.
        if isinstance(text, list):
            text = "".join(p.get("text", "") for p in text if isinstance(p, dict))
        return text
    except (KeyError, IndexError, ValueError) as exc:
        raise OpenAIError(f"unexpected response shape: {res.text[:300]}") from exc
