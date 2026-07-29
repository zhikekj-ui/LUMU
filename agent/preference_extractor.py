"""Auto user preference extractor — learns user preferences from conversations.

Runs as a background task after multi-turn conversations. Uses LLM to analyze
user messages and extract implicit/explicit preferences, then stores them
in the memory system under category='preference'.
"""
from core.logging_config import get_logger
_logger = get_logger("agent.preference_extractor")
import json
import logging
import re
import sys
from typing import Any

logger = logging.getLogger("preference_extractor")

EXTRACTION_PROMPT = """分析以下对话，提取用户的个人偏好和习惯。

提取标准：
- 用户明确表达的偏好（如"我喜欢简洁的回答"、"不要用emoji"）
- 从多次纠正中体现的偏好（如用户反复要求更短的回复）
- 技术偏好（如编程语言、框架、编码风格）
- 沟通偏好（如语言、详细程度、格式）
- 工作流偏好（如"直接做不要问我"）

不要提取：
- 一次性的任务指令（如"帮我写这个函数"）
- 临时的事实信息
- 已经在之前提取过的偏好

对每个偏好，评估置信度：
- high: 用户明确说出"我喜欢/我不喜欢/我总是..."
- medium: 从对话上下文推断，有较强证据
- low: 弱推断，可能不准确

以JSON格式回复，可以提取0到多个偏好：
{{"preferences": [
  {{"key": "preference-name", "content": "具体偏好描述", "confidence": "high/medium/low", "source": "触发此偏好的对话片段"}},
  ...
]}}

如果没有值得提取的新偏好，回复：
{{"preferences": []}}

只回复JSON，不要其他内容。

对话内容：
{conversation}"""


def _strip_markdown_fences(text: str) -> str:
    """Remove markdown code fences from LLM response."""
    text = re.sub(r'```(?:json)?\s*\n?', '', text)
    text = text.strip()
    return text


def _find_json_object(text: str) -> str | None:
    """Find the first JSON object in text."""
    depth = 0
    start = -1
    for i, ch in enumerate(text):
        if ch == '{':
            if depth == 0:
                start = i
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0 and start >= 0:
                return text[start:i+1]
    return None


async def extract_preferences_from_conversation(
    messages: list[dict],
    client: Any,
    model: str,
    memory_manager: Any,
    space: str = "work",
) -> list[dict] | None:
    """Analyze conversation and extract user preferences.

    Args:
        messages: List of message dicts from the conversation
        client: AsyncOpenAI client
        model: Model name to use for analysis
        memory_manager: MemoryManager instance to store preferences

    Returns:
        List of extracted preference dicts, or None if extraction failed
    """
    # Build conversation text — focus on user messages
    user_msgs = []
    for m in messages:
        if m.get("role") == "user" and m.get("content"):
            user_msgs.append(m["content"])
        elif m.get("role") == "assistant" and m.get("content"):
            # Include assistant messages for context but mark them
            user_msgs.append(f"[助手]: {m['content'][:200]}")

    if len(user_msgs) < 2:
        # Too short to extract meaningful preferences
        return None

    conversation_text = "\n".join(user_msgs[-30:])  # Last 30 messages
    if len(conversation_text) > 8000:
        conversation_text = conversation_text[-8000:]

    prompt = EXTRACTION_PROMPT.format(conversation=conversation_text)

    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=16000,  # StepFun requirement
            temperature=0.1,
        )
        content = resp.choices[0].message.content or ""
        _logger.info(f"[preference_extractor] LLM response length: {len(content)}", file=sys.stderr, flush=True)

        # Parse JSON response
        cleaned = _strip_markdown_fences(content)
        json_str = _find_json_object(cleaned)
        if not json_str:
            _logger.info(f"[preference_extractor] No JSON found in response: {cleaned[:200]}", file=sys.stderr, flush=True)
            return None

        data = json.loads(json_str)
        preferences = data.get("preferences", [])

        if not preferences:
            _logger.info("[preference_extractor] No preferences extracted (LLM decided none)", file=sys.stderr, flush=True)
            return None

        # Store each preference in memory
        extracted = []
        for pref in preferences:
            key = pref.get("key", "")
            content = pref.get("content", "")
            confidence = pref.get("confidence", "medium")
            source = pref.get("source", "")

            if not key or not content:
                continue

            # Prefix with "pref:" to namespace preferences
            mem_key = f"pref:{key}"

            # Add confidence and source as metadata
            full_content = content
            if confidence == "low":
                full_content = f"[低置信度] {content}"

            memory_manager.save(mem_key, full_content, category="preference", space=space)
            extracted.append({
                "key": key,
                "content": content,
                "confidence": confidence,
                "source": source[:100] if source else "",
            })
            _logger.info(f"[preference_extractor] Saved preference: {key} ({confidence})", file=sys.stderr, flush=True)

        return extracted if extracted else None

    except json.JSONDecodeError as e:
        _logger.info(f"[preference_extractor] JSON parse error: {e}", file=sys.stderr, flush=True)
        return None
    except Exception as e:
        _logger.info(f"[preference_extractor] Extraction error: {e}", file=sys.stderr, flush=True)
        import traceback
        traceback.print_exc(file=sys.stderr)
        sys.stderr.flush()
        return None
