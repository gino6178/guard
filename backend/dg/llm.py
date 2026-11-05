"""Minimal OpenAI-compatible chat client for the self-hosted vLLM endpoint, with JSON-mode helpers."""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

import httpx

from .config import settings

log = logging.getLogger(__name__)


class LLMUnavailable(RuntimeError):
    pass


class LLM:
    def __init__(self, base_url: str | None = None, api_key: str | None = None, model: str | None = None):
        self.base_url = (base_url or settings.llm_base_url).rstrip("/")
        self.api_key = api_key if api_key is not None else settings.llm_api_key
        self.model = model or settings.llm_model
        self.sem = asyncio.Semaphore(settings.llm_concurrency)
        self.calls = 0
        self.tokens = 0

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    async def health(self) -> bool:
        if not settings.llm_enabled:
            return False
        try:
            async with httpx.AsyncClient(timeout=5) as c:
                r = await c.get(f"{self.base_url}/models", headers=self._headers())
                return r.status_code == 200
        except httpx.HTTPError:
            return False

    async def chat(self, system: str, user: str, max_tokens: int = 4096, temperature: float = 0.0) -> str:
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "max_tokens": max_tokens,
            "temperature": temperature,
            # Qwen3: answer directly; reasoning traces are not needed for extraction and cost latency
            "chat_template_kwargs": {"enable_thinking": False},
        }
        async with self.sem:
            for attempt in range(3):
                try:
                    async with httpx.AsyncClient(timeout=settings.llm_timeout) as c:
                        r = await c.post(f"{self.base_url}/chat/completions", json=body, headers=self._headers())
                    r.raise_for_status()
                    data = r.json()
                    self.calls += 1
                    self.tokens += data.get("usage", {}).get("total_tokens", 0)
                    return data["choices"][0]["message"]["content"] or ""
                except (httpx.HTTPError, KeyError) as e:
                    log.warning("LLM call failed (attempt %d): %s", attempt + 1, e)
                    await asyncio.sleep(2 * (attempt + 1))
        raise LLMUnavailable("LLM endpoint not reachable")

    async def chat_json(self, system: str, user: str, max_tokens: int = 4096) -> Any:
        text = await self.chat(system, user, max_tokens=max_tokens)
        return parse_json(text)


def parse_json(text: str) -> Any:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.S)
    if m:
        text = m.group(1)
    start = min((i for i in (text.find("{"), text.find("[")) if i >= 0), default=-1)
    if start < 0:
        return None
    text = text[start:]
    for end in range(len(text), 0, -1):
        if text[end - 1] in "}]":
            try:
                return json.loads(text[:end])
            except json.JSONDecodeError:
                continue
    return None
