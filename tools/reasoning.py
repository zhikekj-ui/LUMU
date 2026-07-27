"""Reasoning engine — Chain-of-Thought with self-reflection and error correction.

Provides:
- Structured reasoning with explicit thinking steps
- Self-verification of results
- Error detection and backtracking
- Multi-step plan validation
"""
import json
import re
from typing import Any


REASONING_PROMPT = """请用结构化思维分析以下问题。

要求：
1. **理解**: 明确问题的核心是什么
2. **分析**: 列出已知条件和约束
3. **推理**: 逐步推导，每一步都说明理由
4. **验证**: 检查推理过程是否有漏洞
5. **结论**: 给出最终答案，并说明置信度

问题：{question}

上下文：
{context}

请用JSON格式回复：
{{"understanding": "对问题的理解",
  "analysis": ["已知条件1", "已知条件2"],
  "reasoning_steps": ["步骤1: ...", "步骤2: ..."],
  "verification": "验证推理过程是否正确",
  "conclusion": "最终结论",
  "confidence": 0.85}}"""


VERIFY_PROMPT = """请验证以下推理过程和结论是否正确。

原始问题：{question}
推理过程：
{reasoning}

结论：{conclusion}

请检查：
1. 推理逻辑是否严密？
2. 是否有遗漏的情况？
3. 结论是否合理？
4. 是否需要修正？

用JSON格式回复：
{{"is_correct": true/false,
  "issues": ["问题1", "问题2"],
  "corrections": "修正建议（如有）",
  "improved_conclusion": "修正后的结论（如有变化）"}}"""


PLAN_VERIFY_PROMPT = """请验证以下执行计划是否可行。

目标：{goal}
计划：
{plan}

请检查：
1. 步骤是否完整？有没有遗漏？
2. 步骤顺序是否合理？
3. 每步的输入输出是否匹配？
4. 是否有潜在风险？

用JSON格式回复：
{{"is_feasible": true/false,
  "missing_steps": ["遗漏的步骤"],
  "risks": ["潜在风险"],
  "suggestions": "改进建议",
  "revised_plan": "修正后的计划（如有变化）"}}"""


async def reason_about(
    question: str,
    context: str = "",
    iterations: int = 1,
) -> str:
    """Use structured Chain-of-Thought reasoning to analyze a problem.

    iterations>1 时进入多轮自校正：每轮用验证结果修正结论并再次验证，
    直到验证通过或达到迭代上限（对应 notes 改造方向④：拆子问题+交叉验证+多轮迭代）。
    """
    import os
    from openai import AsyncOpenAI
    from providers.registry import get as get_provider
    import config

    provider = get_provider(config.DEFAULT_PROVIDER)
    api_key = os.getenv(provider.api_key_env, "")
    client = AsyncOpenAI(api_key=api_key, base_url=provider.base_url)

    prompt = REASONING_PROMPT.format(question=question, context=context or "无")

    try:
        response = await client.chat.completions.create(
            model=config.DEFAULT_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=16000,
            temperature=0.3,
        )
        reasoning_text = (response.choices[0].message.content or "").strip()
        result = _extract_json(reasoning_text)
        if not result:
            return reasoning_text

        steps = result.get("reasoning_steps", [])
        reasoning_block = "\n".join(steps)
        current_conclusion = result.get("conclusion", "")
        last_verification = None
        verify_history = []

        for _ in range(max(1, min(int(iterations), 5))):
            verify_prompt = VERIFY_PROMPT.format(
                question=question,
                reasoning=reasoning_block,
                conclusion=current_conclusion,
            )
            verify_response = await client.chat.completions.create(
                model=config.DEFAULT_MODEL,
                messages=[{"role": "user", "content": verify_prompt}],
                max_tokens=16000,
                temperature=0.2,
            )
            verify_text = (verify_response.choices[0].message.content or "").strip()
            verification = _extract_json(verify_text)
            last_verification = verification
            verify_history.append(verification or {})
            if verification and not verification.get("is_correct", True):
                improved = verification.get("improved_conclusion", "")
                if improved:
                    current_conclusion = improved
                else:
                    break
            else:
                break

        output_parts = [
            f"【理解】{result.get('understanding', '')}",
            f"【分析】{', '.join(result.get('analysis', []))}",
        ]
        for i, step in enumerate(steps, 1):
            output_parts.append(f"【推理{i}】{step}")

        if len(verify_history) > 1:
            output_parts.append(f"【验证轮次】{len(verify_history)} 轮自校正")
        for vi, v in enumerate(verify_history, 1):
            if isinstance(v, dict):
                output_parts.append(f"【验证{vi}】{v.get('verification', '')}")

        verification = last_verification
        if verification and not verification.get("is_correct", True):
            issues = verification.get("issues", [])
            if issues:
                output_parts.append(f"【发现问题】{'; '.join(issues)}")
            corrections = verification.get("corrections", "")
            if corrections:
                output_parts.append(f"【修正】{corrections}")
            if current_conclusion and current_conclusion != result.get("conclusion", ""):
                output_parts.append(f"【修正后结论】{current_conclusion}")
            else:
                output_parts.append(f"【结论】{result.get('conclusion', '')}")
        else:
            output_parts.append(f"【结论】{current_conclusion or result.get('conclusion', '')}")

        confidence = result.get("confidence", 0)
        output_parts.append(f"【置信度】{confidence:.0%}")

        return "\n".join(output_parts)

    except Exception as e:
        return f"推理失败: {e}"


async def verify_plan(goal: str, plan: str) -> str:
    """Verify whether an execution plan is feasible."""
    import os
    from openai import AsyncOpenAI
    from providers.registry import get as get_provider
    import config

    provider = get_provider(config.DEFAULT_PROVIDER)
    api_key = os.getenv(provider.api_key_env, "")
    client = AsyncOpenAI(api_key=api_key, base_url=provider.base_url)

    prompt = PLAN_VERIFY_PROMPT.format(goal=goal, plan=plan)

    try:
        response = await client.chat.completions.create(
            model=config.DEFAULT_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=16000,
            temperature=0.2,
        )
        result_text = (response.choices[0].message.content or "").strip()
        result = _extract_json(result_text)

        if not result:
            return result_text

        parts = []
        if result.get("is_feasible", True):
            parts.append("✅ 计划可行")
        else:
            parts.append("❌ 计划存在问题")

        missing = result.get("missing_steps", [])
        if missing:
            parts.append(f"遗漏步骤: {'; '.join(missing)}")

        risks = result.get("risks", [])
        if risks:
            parts.append(f"潜在风险: {'; '.join(risks)}")

        suggestions = result.get("suggestions", "")
        if suggestions:
            parts.append(f"建议: {suggestions}")

        revised = result.get("revised_plan", "")
        if revised:
            parts.append(f"\n修正后计划:\n{revised}")

        return "\n".join(parts)

    except Exception as e:
        return f"验证失败: {e}"


def _extract_json(text: str) -> dict | None:
    """Extract JSON object from text, handling markdown fences."""
    text = re.sub(r'^```(?:json)?\s*\n?', '', text)
    text = re.sub(r'\n?```\s*$', '', text)
    text = text.strip()

    # Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try to find JSON object
    match = re.search(r'\{[\s\S]*\}', text)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return None


def register(registry):
    registry.register(
        name="reason_about",
        description=(
            "用结构化思维深入分析一个问题。包含理解→分析→推理→验证→结论的完整过程。"
            "适合处理复杂决策、数学问题、逻辑推理等需要深度思考的场景。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "需要分析的问题",
                },
                "context": {
                    "type": "string",
                    "description": "相关背景信息（可选）",
                },
                "iterations": {
                    "type": "integer",
                    "description": "自校正轮数（默认 1；>1 时多轮交叉验证迭代，最多 5）",
                },
            },
            "required": ["question"],
        },
        handler=reason_about,
        is_async=True,
        toolset="reasoning",
        emoji="🧩",
    )
    registry.register(
        name="verify_plan",
        description=(
            "验证一个执行计划是否可行。检查步骤完整性、顺序合理性、"
            "输入输出匹配度和潜在风险。在执行复杂任务前使用。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "goal": {
                    "type": "string",
                    "description": "要达成的目标",
                },
                "plan": {
                    "type": "string",
                    "description": "执行计划（步骤列表）",
                },
            },
            "required": ["goal", "plan"],
        },
        handler=verify_plan,
        is_async=True,
        toolset="reasoning",
        emoji="✅",
    )
