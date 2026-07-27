"""Anthropic Messages API adapter that mimics the AsyncOpenAI client surface.

Why: many Chinese providers (GLM/DeepSeek/Kimi/MiniMax/Hunyuan/SiliconFlow)
expose BOTH an OpenAI-compatible endpoint and an Anthropic-compatible
endpoint (often with different quota/plans). agent/core.py talks OpenAI
protocol everywhere; this module lets it transparently speak Anthropic
whenever the resolved base_url points at an Anthropic-compatible endpoint.

Usage (one-line change in agent/core.py)::

    from providers.anthropic_compat import SmartAsyncClient as AsyncOpenAI

``SmartAsyncClient(api_key=..., base_url=...)`` returns a real AsyncOpenAI
for normal endpoints, or an :class:`AnthropicCompatClient` when the
base_url looks like an Anthropic endpoint (contains "/anthropic" or the
Volcano Ark coding path "/api/coding").
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
from openai import AsyncOpenAI as _RealAsyncOpenAI

ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MAX_TOKENS = 8192


def is_anthropic_url(base_url: str) -> bool:
    u = (base_url or "").rstrip("/")
    return "/anthropic" in u or u.endswith("/api/coding")


class SmartAsyncClient:
    """Factory: returns the right client for the endpoint protocol."""

    def __new__(cls, api_key: str = "", base_url: str = "", **kwargs):
        if is_anthropic_url(base_url):
            return AnthropicCompatClient(api_key=api_key, base_url=base_url)
        return _RealAsyncOpenAI(api_key=api_key, base_url=base_url, **kwargs)


# ---------------------------------------------------------------------------
# Message / tool conversion helpers (OpenAI dict format -> Anthropic)
# ---------------------------------------------------------------------------

def _convert_tools(tools: list[dict] | None) -> list[dict]:
    out = []
    for t in tools or []:
        fn = t.get("function", t) or {}
        out.append({
            "name": fn.get("name", ""),
            "description": fn.get("description", "") or "",
            "input_schema": fn.get("parameters") or {"type": "object", "properties": {}},
        })
    return out


def _convert_messages(messages: list[dict]) -> tuple[str, list[dict]]:
    """Split OpenAI messages into (system_text, anthropic_messages)."""
    system_parts: list[str] = []
    out: list[dict] = []
    for m in messages:
        role = m.get("role")
        content = m.get("content") or ""
        if role == "system":
            if isinstance(content, str) and content.strip():
                system_parts.append(content)
            continue
        if role == "tool":
            block = {
                "type": "tool_result",
                "tool_use_id": m.get("tool_call_id", ""),
                "content": str(content)[:60000],
            }
            # Anthropic requires tool_result inside a *user* message.
            if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list) \
                    and out[-1]["content"] and out[-1]["content"][0].get("type") == "tool_result":
                out[-1]["content"].append(block)
            else:
                out.append({"role": "user", "content": [block]})
            continue
        if role == "assistant":
            blocks: list[dict] = []
            if isinstance(content, str) and content.strip():
                blocks.append({"type": "text", "text": content})
            for tc in m.get("tool_calls") or []:
                fn = tc.get("function", {})
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except Exception:
                    args = {"_raw": fn.get("arguments", "")}
                blocks.append({
                    "type": "tool_use",
                    "id": tc.get("id", ""),
                    "name": fn.get("name", ""),
                    "input": args if isinstance(args, dict) else {"_raw": args},
                })
            if blocks:
                out.append({"role": "assistant", "content": blocks})
            continue
        # user (string or multimodal list)
        if isinstance(content, list):
            blocks = []
            for part in content:
                if part.get("type") == "text":
                    blocks.append({"type": "text", "text": part.get("text", "")})
                elif part.get("type") == "image_url":
                    url = (part.get("image_url") or {}).get("url", "")
                    if url.startswith("data:"):
                        try:
                            head, b64 = url.split(",", 1)
                            media = head.split(";")[0].split(":", 1)[1]
                            blocks.append({"type": "image", "source": {
                                "type": "base64", "media_type": media, "data": b64}})
                        except Exception:
                            pass
                    else:
                        blocks.append({"type": "image", "source": {"type": "url", "url": url}})
            out.append({"role": "user", "content": blocks or [{"type": "text", "text": ""}]})
        else:
            out.append({"role": "user", "content": str(content)})
    # Anthropic requires alternating-ish, non-empty first user msg
    if not out or out[0]["role"] != "user":
        out.insert(0, {"role": "user", "content": "(继续)"})
    return "\n\n".join(system_parts), out


_FINISH_MAP = {"end_turn": "stop", "tool_use": "tool_calls", "max_tokens": "length",
               "stop_sequence": "stop"}


def _mk_tool_call(block: dict) -> SimpleNamespace:
    return SimpleNamespace(
        id=block.get("id", ""),
        type="function",
        function=SimpleNamespace(
            name=block.get("name", ""),
            arguments=json.dumps(block.get("input") or {}, ensure_ascii=False),
        ),
    )


class _Completions:
    def __init__(self, client: "AnthropicCompatClient"):
        self._c = client

    async def create(self, model: str, messages: list[dict], stream: bool = False,
                     tools: list[dict] | None = None, temperature: float | None = None,
                     top_p: float | None = None, max_tokens: int | None = None,
                     **_ignored):
        system, amsgs = _convert_messages(messages)
        payload: dict = {
            "model": model,
            "messages": amsgs,
            "max_tokens": max_tokens or DEFAULT_MAX_TOKENS,
        }
        if system:
            payload["system"] = system
        if tools:
            payload["tools"] = _convert_tools(tools)
        if temperature is not None:
            payload["temperature"] = temperature
        if top_p is not None:
            payload["top_p"] = top_p
        if stream:
            payload["stream"] = True
            return self._c._stream(payload)
        return await self._c._request(payload)


class AnthropicCompatClient:
    """Minimal async client speaking Anthropic Messages API, exposing the
    subset of the AsyncOpenAI surface that agent/core.py uses:
    ``client.chat.completions.create(...)`` (stream & non-stream)."""

    def __init__(self, api_key: str = "", base_url: str = ""):
        self.api_key = api_key or ""
        self.base_url = (base_url or "").rstrip("/")
        self.chat = SimpleNamespace(completions=_Completions(self))

    # -- plumbing --
    @property
    def _endpoint(self) -> str:
        return self.base_url + "/v1/messages"

    @property
    def _headers(self) -> dict:
        return {
            "x-api-key": self.api_key,
            "authorization": f"Bearer {self.api_key}",
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }

    async def _request(self, payload: dict):
        async with httpx.AsyncClient(timeout=600) as hc:
            r = await hc.post(self._endpoint, headers=self._headers, json=payload)
            if r.status_code >= 400:
                raise RuntimeError(f"Anthropic endpoint {r.status_code}: {r.text[:500]}")
            data = r.json()
        text_parts, tool_calls = [], []
        for block in data.get("content") or []:
            if block.get("type") == "text":
                text_parts.append(block.get("text", ""))
            elif block.get("type") == "tool_use":
                tool_calls.append(_mk_tool_call(block))
        usage = data.get("usage") or {}
        message = SimpleNamespace(
            role="assistant",
            content="".join(text_parts),
            tool_calls=tool_calls or None,
        )
        return SimpleNamespace(
            id=data.get("id", ""),
            model=data.get("model", payload.get("model")),
            choices=[SimpleNamespace(
                index=0, message=message,
                finish_reason=_FINISH_MAP.get(data.get("stop_reason"), "stop"),
            )],
            usage=SimpleNamespace(
                prompt_tokens=usage.get("input_tokens", 0),
                completion_tokens=usage.get("output_tokens", 0),
                total_tokens=usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
            ),
        )

    async def _stream(self, payload: dict):
        """Yield OpenAI-style chunks from an Anthropic SSE stream."""
        def chunk(delta=None, finish=None):
            return SimpleNamespace(choices=[SimpleNamespace(
                index=0,
                delta=delta or SimpleNamespace(content=None, tool_calls=None),
                finish_reason=finish,
            )], usage=None)

        async with httpx.AsyncClient(timeout=600) as hc:
            async with hc.stream("POST", self._endpoint, headers=self._headers,
                                 json=payload) as r:
                if r.status_code >= 400:
                    body = await r.aread()
                    raise RuntimeError(
                        f"Anthropic endpoint {r.status_code}: {body.decode()[:500]}")
                tool_idx = -1          # OpenAI-style tool_call index
                block_is_tool = False
                finish = "stop"
                async for line in r.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    if not raw or raw == "[DONE]":
                        continue
                    try:
                        ev = json.loads(raw)
                    except Exception:
                        continue
                    et = ev.get("type")
                    if et == "content_block_start":
                        cb = ev.get("content_block") or {}
                        block_is_tool = cb.get("type") == "tool_use"
                        if block_is_tool:
                            tool_idx += 1
                            yield chunk(SimpleNamespace(content=None, tool_calls=[
                                SimpleNamespace(index=tool_idx, id=cb.get("id", ""),
                                                type="function",
                                                function=SimpleNamespace(
                                                    name=cb.get("name", ""),
                                                    arguments=""))]))
                    elif et == "content_block_delta":
                        d = ev.get("delta") or {}
                        if d.get("type") == "text_delta" and d.get("text"):
                            yield chunk(SimpleNamespace(content=d["text"], tool_calls=None))
                        elif d.get("type") == "input_json_delta" and block_is_tool:
                            yield chunk(SimpleNamespace(content=None, tool_calls=[
                                SimpleNamespace(index=tool_idx, id=None, type="function",
                                                function=SimpleNamespace(
                                                    name=None,
                                                    arguments=d.get("partial_json", "")))]))
                    elif et == "content_block_stop":
                        block_is_tool = False
                    elif et == "message_delta":
                        sr = (ev.get("delta") or {}).get("stop_reason")
                        if sr:
                            finish = _FINISH_MAP.get(sr, "stop")
                    elif et == "message_stop":
                        yield chunk(finish=finish)
                    elif et == "error":
                        err = (ev.get("error") or {}).get("message", "unknown")
                        raise RuntimeError(f"Anthropic stream error: {err}")
