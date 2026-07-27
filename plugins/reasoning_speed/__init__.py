"""Reasoning Speed Optimizer Plugin

Monkey-patches AsyncCompletions.create to inject
reasoning_effort='low' via extra_body for DeepSeek API calls,
reducing thinking time by 3-5 seconds per response.
"""
import logging
from plugins.base import BasePlugin

logger = logging.getLogger("plugins.reasoning_speed")


class ReasoningSpeedPlugin(BasePlugin):
    name = "reasoning_speed"
    version = "1.0.0"
    description = "降 DeepSeek 的 reasoning_effort 为 low，加快语音响应速度"
    author = "LUMU"

    def on_load(self):
        self._patch_completions()

    def _patch_completions(self):
        """Wrap AsyncCompletions.create to inject reasoning_effort='low' for DeepSeek."""
        try:
            from openai.resources.chat.completions import AsyncCompletions

            _orig_create = AsyncCompletions.create

            async def patched_create(self, *args, **kwargs):
                model = kwargs.get("model", "")
                if "deepseek" in model.lower():
                    # reasoning_effort is a top-level param in DeepSeek API,
                    # but OpenAI SDK requires non-standard params via extra_body
                    extra = kwargs.get("extra_body") or {}
                    if "reasoning_effort" not in extra:
                        extra["reasoning_effort"] = "low"
                    kwargs["extra_body"] = extra
                return await _orig_create(self, *args, **kwargs)

            AsyncCompletions.create = patched_create
            logger.info("[reasoning_speed] Patched AsyncCompletions.create → reasoning_effort=low ✓")
        except Exception as e:
            logger.warning(f"[reasoning_speed] Patch failed: {e}")

    def on_unload(self):
        pass
