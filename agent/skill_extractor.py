"""Auto skill extractor — learns reusable procedures from conversations."""
import asyncio
import json
import logging
import re
from typing import Any

_logger = logging.getLogger("agent.skill_extractor")

EXTRACTION_PROMPT = """分析以下对话，判断是否包含可复用的操作步骤或技能。

判断标准：
- 涉及多个步骤的操作流程
- 用户可能需要重复执行类似任务
- 包含特定的命令、API调用或配置方法

如果可以提取技能，以JSON格式回复：
{{"extract": true, "name": "skill-name", "description": "一句话描述", "content": "步骤1\\n步骤2\\n步骤3", "tags": "tag1,tag2"}}

如果不需要提取（简单问答、闲聊等），回复：
{{"extract": false}}

只回复JSON，不要其他内容。

对话内容：
{conversation}"""


async def extract_skill_from_conversation(
    messages: list[dict],
    client: Any,
    model: str,
    skill_manager: Any,
) -> dict | None:
    """Analyze a conversation and extract a reusable skill if applicable."""
    # Build compact conversation summary
    parts = []
    for msg in messages[-20:]:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if role == "user" and content:
            parts.append(f"用户: {content[:300]}")
        elif role == "assistant" and content:
            parts.append(f"助手: {content[:500]}")
        elif role == "tool" and content:
            parts.append(f"工具结果: {content[:200]}")
    
    if not parts:
        return None
    
    conversation_text = "\n".join(parts)
    prompt = EXTRACTION_PROMPT.format(conversation=conversation_text)
    
    try:
        _logger.info(f"[skill_extractor] Analyzing {len(messages)} messages for skill extraction...")
        
        response = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=16000,
        )
        
        result_text = (response.choices[0].message.content or "").strip()
        _logger.info(f"[skill_extractor] Raw response: {result_text[:300]}", )
        
        if not result_text:
            _logger.info("[skill_extractor] Empty response, skipping", )
            return None
        
        # Strip markdown code fences
        result_text = re.sub(r'^```(?:json)?\s*\n?', '', result_text)
        result_text = re.sub(r'\n?```\s*$', '', result_text)
        result_text = result_text.strip()
        
        # Try to find JSON object in the response
        json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', result_text, re.DOTALL)
        if json_match:
            result_text = json_match.group(0)
        
        result = json.loads(result_text)
        
        # Ensure it's a dict
        if not isinstance(result, dict):
            _logger.info(f"[skill_extractor] Response is not a dict: {type(result)}", )
            return None
        
        if not result.get("extract", False):
            _logger.info("[skill_extractor] No skill to extract", )
            return None
        
        name = result.get("name", "")
        description = result.get("description", "")
        content = result.get("content", "")
        tags = result.get("tags", "")
        
        if not name or not description or not content:
            _logger.info(f"[skill_extractor] Incomplete result: name={name}, desc={description}, content={content[:50] if content else ''}", )
            return None
        
        # Save skill
        is_new = skill_manager.save(name, description, content, tags)
        action = "Created" if is_new else "Updated"
        _logger.info(f"[skill_extractor] {action} skill: {name}", )
        
        return {
            "name": name,
            "description": description,
            "content": content,
            "tags": tags,
            "is_new": is_new,
        }
        
    except json.JSONDecodeError as e:
        _logger.info(f"[skill_extractor] JSON parse error: {e}, text: {result_text[:200]}", )
        return None
    except Exception as e:
        _logger.info(f"[skill_extractor] Error: {e}", )
        return None
