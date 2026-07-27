"""Agent context engine — enhanced context window management with intelligent compression.

Features:
- Token counting with model-aware limits
- Priority-based message retention (keep important messages longer)
- Semantic compression: summarize old messages instead of dropping them
- Tool call/result coupling: never split tool_call from its result
"""
import json
import os
import re
import time


class ContextEngine:
    """Manages context window — tracks token usage, compresses when needed."""

    def __init__(self, context_window: int = 32000):
        self.context_window = context_window
        self.last_prompt_tokens = 0
        self.last_completion_tokens = 0
        self.compression_count = 0
        self._estimated_tokens = 0
        # Enhanced attributes
        self.compress_threshold = 0.75
        self.max_messages = 100
        self._summary_cache: dict = {}  # session_id -> summary

    def estimate_tokens(self, text: str) -> int:
        """Estimate token count (~4 chars per token for English, ~1.5 for CJK)."""
        if not text:
            return 0
        cjk = len(re.findall(r'[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]', text))
        non_cjk = len(text) - cjk
        return int(cjk * 1.5 + non_cjk / 4)

    def should_compress(self, messages: list[dict] | None = None) -> bool:
        """Check if context needs compression based on token usage."""
        threshold = int(self.context_window * self.compress_threshold)
        return self._estimated_tokens > threshold and self._estimated_tokens > 0

    def update_from_response(self, response):
        """Update token counts from API response."""
        try:
            if hasattr(response, "usage") and response.usage:
                self.last_prompt_tokens = getattr(response.usage, "prompt_tokens", 0) or 0
                self.last_completion_tokens = getattr(response.usage, "completion_tokens", 0) or 0
                self._estimated_tokens = self.last_prompt_tokens + self.last_completion_tokens
        except Exception:
            pass

    def compress_messages(self, messages: list[dict], session_id: str = "") -> list[dict]:
        """Intelligently compress message history to fit within context window.

        Strategy:
        1. Always keep system messages
        2. Always keep tool_call + tool_result pairs (causal coupling)
        3. Compress oldest user/assistant pairs into a summary
        4. Keep recent messages intact
        """
        if not messages:
            return messages

        # Separate system messages
        system_msgs = [m for m in messages if m.get("role") == "system"]
        non_system = [m for m in messages if m.get("role") != "system"]

        if not non_system:
            return messages

        # Calculate current token usage
        total_tokens = sum(self.estimate_tokens(m.get("content", "")) for m in non_system)
        # Also count tool_calls content
        for m in non_system:
            if m.get("tool_calls"):
                for tc in m["tool_calls"]:
                    if isinstance(tc, dict):
                        func = tc.get("function", {})
                        total_tokens += self.estimate_tokens(func.get("arguments", ""))

        threshold = int(self.context_window * self.compress_threshold)

        if total_tokens <= threshold and len(non_system) <= self.max_messages:
            return messages

        # Identify tool_call/result pairs and protect them
        protected = set()
        for i, msg in enumerate(non_system):
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                protected.add(i)
                protected.add(i + 1)  # The following tool result
            elif msg.get("role") == "tool":
                protected.add(i)

        # Compress from oldest to newest
        compressed = []
        summary_parts = []
        keep_count = min(30, len(non_system))  # Keep last 30 messages uncompressed

        for i in range(len(non_system)):
            if i < len(non_system) - keep_count and i not in protected:
                # Compress this message into summary
                msg = non_system[i]
                if msg.get("role") in ("user", "assistant"):
                    content = msg.get("content", "")
                    if content and len(content) > 20:
                        role_label = "User" if msg["role"] == "user" else "AI"
                        if len(content) > 200:
                            content = content[:200] + "..."
                        summary_parts.append(f"{role_label}: {content}")
            else:
                compressed.append(msg)

        # Insert summary as a system note if we compressed anything
        if summary_parts:
            summary_text = "Summary of earlier conversation:\n" + "\n".join(summary_parts[-10:])
            summary_msg = {
                "role": "user",
                "content": f"[System note: compressed earlier conversation history for reference]\n{summary_text}",
            }
            compressed.insert(0, summary_msg)
            self.compression_count += 1

        return system_msgs + compressed

    async def compress_messages_async(self, messages: list[dict], client, model: str) -> list[dict]:
        """Compress messages by summarizing older ones with LLM.

        Strategy:
        - Keep system messages and last 6 messages as-is
        - Summarize the rest into a single system message
        - Fall back to local compression if LLM call fails
        """
        if len(messages) < 8:
            return messages

        # Try LLM-based compression first
        try:
            system_msgs = [m for m in messages if m.get("role") == "system"]
            non_system = [m for m in messages if m.get("role") != "system"]

            if len(non_system) <= 6:
                return messages

            old_msgs = non_system[:-6]
            recent_msgs = non_system[-6:]

            # Build text to summarize
            to_summarize = []
            for m in old_msgs:
                role = m.get("role", "unknown")
                content = m.get("content", "")
                if content:
                    truncated = content[:500] + "..." if len(content) > 500 else content
                    to_summarize.append(f"[{role}]: {truncated}")

            summary_text = "\n".join(to_summarize)

            response = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "Summarize the following conversation concisely. Keep key facts, decisions, and results. Use the same language as the conversation."},
                    {"role": "user", "content": summary_text},
                ],
                max_tokens=500,
                temperature=0,
            )

            summary = response.choices[0].message.content.strip()
            summary_msg = {
                "role": "user",
                "content": f"[Earlier conversation summary]: {summary}",
            }
            self.compression_count += 1
            return system_msgs + [summary_msg] + recent_msgs

        except Exception as e:
            # Fall back to local compression
            return self.compress_messages(messages)

    def get_context_stats(self, messages: list[dict]) -> dict:
        """Return context usage statistics."""
        total = sum(self.estimate_tokens(m.get("content", "")) for m in messages)
        tool_calls = sum(1 for m in messages if m.get("tool_calls"))
        return {
            "total_tokens": total,
            "context_window": self.context_window,
            "usage_percent": round(total / self.context_window * 100, 1) if self.context_window > 0 else 0,
            "message_count": len(messages),
            "tool_call_count": tool_calls,
            "needs_compression": self.should_compress(messages),
            "compression_count": self.compression_count,
        }
