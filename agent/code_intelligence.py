"""LUMU 代码智能引擎 - 高级代码理解与生成

核心能力:
1. 代码生成: 根据自然语言描述生成高质量代码
2. 代码解释: 用自然语言解释代码逻辑
3. 代码审查: 自动发现代码问题和改进建议
4. 代码重构: 智能代码重构建议和执行
5. 代码调试: 分析错误信息，定位问题，提供修复方案
6. 单元测试生成: 自动生成测试用例
7. 文档生成: 自动生成代码文档和注释
8. 依赖分析: 分析代码依赖关系
9. 安全审计: 检测常见安全漏洞
10. 性能优化: 代码性能分析和优化建议
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass, field
from typing import Any

# ---- 日志配置 ----
try:
    from core.logging_config import get_logger
except ImportError:
    def get_logger(name: str) -> Any:  # type: ignore[misc]
        """回退日志器，当 core.logging_config 不可用时使用标准 logging"""
        import logging
        return logging.getLogger(name)

logger = get_logger("code_intelligence")

# ---- 语言检测模式 ----

# 语言特征模式（用于 detect_language）
_LANGUAGE_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "python": [
        re.compile(r"^\s*import\s+\w", re.MULTILINE),
        re.compile(r"^\s*from\s+\w+\s+import", re.MULTILINE),
        re.compile(r"^\s*def\s+\w+\s*\(", re.MULTILINE),
        re.compile(r"^\s*class\s+\w+", re.MULTILINE),
        re.compile(r"\bself\.\w+"),
        re.compile(r"\bprint\s*\("),
        re.compile(r"#.*$", re.MULTILINE),
    ],
    "javascript": [
        re.compile(r"\bconst\s+\w+\s*=", re.MULTILINE),
        re.compile(r"\blet\s+\w+\s*=", re.MULTILINE),
        re.compile(r"\bvar\s+\w+\s*=", re.MULTILINE),
        re.compile(r"\bfunction\s+\w+\s*\(", re.MULTILINE),
        re.compile(r"=>\s*\\{"),
        re.compile(r"console\.log"),
        re.compile(r"require\s*\("),
    ],
    "typescript": [
        re.compile(r":\s*(string|number|boolean|void|any|never)\b"),
        re.compile(r"interface\s+\w+"),
        re.compile(r"type\s+\w+\s*="),
        re.compile(r"<[A-Z]\w*>"),
    ],
    "java": [
        re.compile(r"\bpublic\s+(class|interface|enum)\s+\w+"),
        re.compile(r"\bSystem\.out\.print"),
        re.compile(r"@Override"),
        re.compile(r"\bprivate\s+\w+\s+\w+"),
    ],
    "go": [
        re.compile(r"^\s*package\s+\w+", re.MULTILINE),
        re.compile(r"^\s*func\s+", re.MULTILINE),
        re.compile(r":=\s*"),
        re.compile(r"fmt\.Print"),
    ],
    "rust": [
        re.compile(r"^\s*fn\s+\w+\s*\(", re.MULTILINE),
        re.compile(r"^\s*use\s+\w+", re.MULTILINE),
        re.compile(r"let\s+mut\s+"),
        re.compile(r"->\s*(Self|&|Vec|Result|Option)"),
        re.compile(r"#\[derive"),
    ],
    "c": [
        re.compile(r"#include\s*<"),
        re.compile(r"int\s+main\s*\("),
        re.compile(r"printf\s*\("),
    ],
    "cpp": [
        re.compile(r"#include\s*<"),
        re.compile(r"std::(cout|vector|string|map)"),
        re.compile(r"class\s+\w+\\s*\\{"),
        re.compile(r"->"),
    ],
}

# 文件扩展名到语言名的映射
_EXTENSION_MAP: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".jsx": "javascript",
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
    ".c": "c",
    ".cpp": "cpp",
    ".h": "c",
    ".hpp": "cpp",
    ".rb": "ruby",
    ".php": "php",
    ".swift": "swift",
    ".kt": "kotlin",
    ".scala": "scala",
    ".r": "r",
    ".sql": "sql",
    ".sh": "shell",
    ".bash": "shell",
    ".html": "html",
    ".css": "css",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".toml": "toml",
    ".xml": "xml",
    ".md": "markdown",
}


# ---- 数据类定义 ----


@dataclass
class CodeResult:
    """代码生成结果"""
    code: str
    language: str
    description: str
    explanation: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExplainResult:
    """代码解释结果"""
    original_code: str
    explanation: str
    language: str
    complexity: str = ""
    key_concepts: list[str] = field(default_factory=list)


@dataclass
class ReviewIssue:
    """代码审查问题项"""
    severity: str       # critical, warning, info, suggestion
    category: str       # bug, style, performance, security, maintainability
    line: int | None    # 行号
    message: str
    suggestion: str = ""


@dataclass
class ReviewResult:
    """代码审查结果"""
    original_code: str
    issues: list[ReviewIssue] = field(default_factory=list)
    summary: str = ""
    score: float = 0.0  # 0-10 分
    language: str = ""


@dataclass
class RefactorResult:
    """代码重构结果"""
    original_code: str
    refactored_code: str
    changes_description: str
    language: str = ""
    applied_patterns: list[str] = field(default_factory=list)


@dataclass
class DebugResult:
    """代码调试结果"""
    original_code: str
    error_message: str
    root_cause: str
    fixed_code: str
    explanation: str
    language: str = ""


@dataclass
class TestCase:
    """测试用例"""
    name: str
    description: str = ""
    code: str = ""


@dataclass
class TestResult:
    """测试生成结果"""
    original_code: str
    test_code: str
    test_cases: list[TestCase] = field(default_factory=list)
    test_framework: str = ""
    language: str = ""
    coverage_notes: str = ""


@dataclass
class DocResult:
    """文档生成结果"""
    original_code: str
    generated_docs: str
    doc_type: str = ""
    language: str = ""


@dataclass
class SecurityIssue:
    """安全问题项"""
    severity: str       # critical, high, medium, low
    category: str       # injection, xss, sqli, auth, crypto, etc.
    line: int | None
    description: str
    recommendation: str = ""
    cwe_id: str = ""


@dataclass
class SecurityResult:
    """安全审计结果"""
    original_code: str
    issues: list[SecurityIssue] = field(default_factory=list)
    summary: str = ""
    risk_level: str = ""  # critical, high, medium, low, safe
    language: str = ""


@dataclass
class PerfIssue:
    """性能问题项"""
    severity: str
    category: str       # algorithm, io, memory, concurrency
    line: int | None
    description: str
    suggestion: str = ""
    estimated_impact: str = ""


@dataclass
class PerfResult:
    """性能分析结果"""
    original_code: str
    issues: list[PerfIssue] = field(default_factory=list)
    summary: str = ""
    overall_rating: str = ""  # excellent, good, fair, poor
    language: str = ""


# ---- Prompt 模板 ----

_PROMPT_GENERATE = """你是一个高级{language}开发工程师。请根据以下描述生成高质量的代码。

要求:
- 代码应当完整、可运行、符合{language}最佳实践
- 包含适当的错误处理和边界检查
- 添加必要的注释（中文）
- 使用有意义的变量名和函数名

描述: {description}

{context_section}"""

_PROMPT_EXPLAIN = """你是一个代码教学专家。请用自然语言（中文）解释以下{language}代码的逻辑。

解释要求:
- 详细程度: {detail_level}
- 先概述代码整体功能
- 然后逐段/逐函数解释
- 指出关键概念和设计模式
- 最后给出代码复杂度评估

代码:
```{language}
{code}
```"""

_PROMPT_REVIEW = """你是一个资深代码审查专家。请对以下{language}代码进行全面审查。

审查维度: {focus_section}

请以严格的JSON格式返回审查结果:
{{
  "issues": [
    {{
      "severity": "critical|warning|info|suggestion",
      "category": "bug|style|performance|security|maintainability",
      "line": 行号或null,
      "message": "问题描述",
      "suggestion": "修改建议"
    }}
  ],
  "summary": "整体评价",
  "score": 8.5
}}

只返回JSON，不要有其他内容。

代码:
```{language}
{code}
```"""

_PROMPT_REFACTOR = """你是一个代码重构专家。请对以下{language}代码进行重构，目标: {goal}

请以严格的JSON格式返回:
{{
  "refactored_code": "重构后的完整代码",
  "changes_description": "做了哪些改动以及为什么",
  "applied_patterns": ["设计模式1", "设计模式2"]
}}

只返回JSON，不要有其他内容。

原始代码:
```{language}
{code}
```"""

_PROMPT_DEBUG = """你是一个调试专家。请分析以下{language}代码的错误并给出修复方案。

错误信息:
{error_message}

请以严格的JSON格式返回:
{{
  "root_cause": "错误的根本原因分析",
  "fixed_code": "修复后的完整代码",
  "explanation": "修复思路和原理说明"
}}

只返回JSON，不要有其他内容。

代码:
```{language}
{code}
```"""

_PROMPT_TESTS = """你是一个测试工程专家。请为以下{language}代码生成全面的单元测试。

要求:
- 使用 {framework} 测试框架
- 覆盖正常路径、边界情况和异常情况
- 每个测试用例有清晰的描述
- 包含必要的 mock 和 fixture

请以严格的JSON格式返回:
{{
  "test_code": "完整的测试文件代码",
  "test_cases": [
    {{"name": "测试名称", "description": "测试描述", "code": "测试函数代码"}}
  ],
  "coverage_notes": "覆盖率说明和未覆盖的场景"
}}

只返回JSON，不要有其他内容。

代码:
```{language}
{code}
```"""

_PROMPT_DOCS = """你是一个技术文档专家。请为以下{language}代码生成{doc_type}。

请以严格的JSON格式返回:
{{
  "generated_docs": "生成的文档内容"
}}

只返回JSON，不要有其他内容。

代码:
```{language}
{code}
```"""

_PROMPT_SECURITY = """你是一个应用安全审计专家。请对以下{language}代码进行安全审计。

请以严格的JSON格式返回:
{{
  "issues": [
    {{
      "severity": "critical|high|medium|low",
      "category": "injection|xss|sqli|auth|crypto|config|other",
      "line": 行号或null,
      "description": "安全问题描述",
      "recommendation": "修复建议",
      "cwe_id": "CWE-XXX"
    }}
  ],
  "summary": "安全审计整体评估",
  "risk_level": "critical|high|medium|low|safe"
}}

只返回JSON，不要有其他内容。

代码:
```{language}
{code}
```"""

_PROMPT_PERF = """你是一个性能优化专家。请分析以下{language}代码的性能。

请以严格的JSON格式返回:
{{
  "issues": [
    {{
      "severity": "high|medium|low",
      "category": "algorithm|io|memory|concurrency",
      "line": 行号或null,
      "description": "性能问题描述",
      "suggestion": "优化建议",
      "estimated_impact": "预期改善效果"
    }}
  ],
  "summary": "性能分析整体评估",
  "overall_rating": "excellent|good|fair|poor"
}}

只返回JSON，不要有其他内容。

代码:
```{language}
{code}
```"""


# ---- LLM调用辅助函数 ----


async def _call_llm(
    prompt: str,
    client: Any,
    model: str,
    system_prompt: str = "你是一个专业的代码分析助手，精通多种编程语言。",
    temperature: float = 0.2,
    max_tokens: int = 4096,
) -> str:
    """统一的LLM调用封装

    Args:
        prompt: 用户提示
        client: OpenAI兼容API客户端
        model: 模型名称
        system_prompt: 系统提示
        temperature: 采样温度
        max_tokens: 最大生成token数

    Returns:
        模型返回的文本内容
    """
    try:
        response = await client.chat.completions.create(
            model=model or "default",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content or ""  # type: ignore[union-attr]
    except Exception as exc:
        logger.error("LLM调用失败: %s", exc)
        raise RuntimeError(f"LLM调用失败: {exc}") from exc


def _extract_json(text: str) -> dict[str, Any] | None:
    """从LLM返回的文本中提取JSON对象

    处理可能被markdown代码块包裹的情况。
    """
    if not text.strip():
        return None

    # 尝试直接解析
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        pass

    # 尝试从markdown代码块中提取
    json_match = re.search(r"```(?:json)?\s*\n?(\{[\s\S]*?\})\s*\n?```", text)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except (json.JSONDecodeError, ValueError):
            pass

    # 最后尝试提取花括号包裹的内容
    brace_match = re.search(r"\{[\s\S]*\}", text)
    if brace_match:
        try:
            return json.loads(brace_match.group())
        except (json.JSONDecodeError, ValueError):
            pass

    return None




# ---- 核心类: CodeIntelligence ----


class CodeIntelligence:
    """代码智能引擎 - 高级代码理解与生成

    提供代码生成、解释、审查、重构、调试、测试生成、
    文档生成、安全审计、性能优化等全方位代码智能能力。

    所有分析功能通过调用LLM实现，配合精心设计的prompt模板。

    用法示例::

        ci = get_code_intelligence()
        result = await ci.generate_code(
            "实现一个LRU缓存",
            language="python",
            client=client,
            model="gpt-4",
        )
        print(result.code)
    """

    def __init__(self) -> None:
        pass

    async def generate_code(
        self,
        description: str,
        language: str = "python",
        context: str | None = None,
        client: Any = None,
        model: str = "",
    ) -> CodeResult:
        """代码生成 - 根据自然语言描述生成高质量代码

        Args:
            description: 代码功能描述
            language: 编程语言
            context: 额外上下文（如现有代码片段）
            client: OpenAI兼容API客户端
            model: 模型名称

        Returns:
            代码生成结果
        """
        if not client:
            return CodeResult(
                code="",
                language=language,
                description=description,
                explanation="未提供LLM客户端，无法生成代码",
            )

        context_section = ""
        if context and context.strip():
            context_section = f"\n上下文参考:\n```{language}\n{context}\n```"

        prompt = _PROMPT_GENERATE.format(
            language=language,
            description=description,
            context_section=context_section,
        )

        logger.info("代码生成: language=%s, desc=%s", language, description[:50])

        try:
            response_text = await _call_llm(prompt, client, model)
            # 提取代码块
            code = self._extract_code_block(response_text, language)

            return CodeResult(
                code=code,
                language=language,
                description=description,
                explanation=response_text,
            )
        except Exception as exc:
            logger.error("代码生成失败: %s", exc)
            return CodeResult(
                code="",
                language=language,
                description=description,
                explanation=f"生成失败: {exc}",
            )

    async def explain_code(
        self,
        code: str,
        language: str | None = None,
        detail_level: str = "medium",
        client: Any = None,
        model: str = "",
    ) -> ExplainResult:
        """代码解释 - 用自然语言解释代码逻辑

        Args:
            code: 待解释的代码
            language: 编程语言（可自动检测）
            detail_level: 解释详细程度 ("brief" | "medium" | "detailed")
            client: OpenAI兼容API客户端
            model: 模型名称

        Returns:
            代码解释结果
        """
        if not client:
            return ExplainResult(
                original_code=code,
                explanation="未提供LLM客户端，无法解释代码",
                language=language or "unknown",
            )

        if not language:
            language = self.detect_language(code)

        detail_map = {"brief": "简要", "medium": "适中", "detailed": "详细"}
        level_text = detail_map.get(detail_level, "适中")

        prompt = _PROMPT_EXPLAIN.format(
            language=language,
            detail_level=level_text,
            code=code,
        )

        logger.info("代码解释: language=%s, detail=%s", language, detail_level)

        try:
            response_text = await _call_llm(prompt, client, model)
            return ExplainResult(
                original_code=code,
                explanation=response_text,
                language=language,
            )
        except Exception as exc:
            logger.error("代码解释失败: %s", exc)
            return ExplainResult(
                original_code=code,
                explanation=f"解释失败: {exc}",
                language=language,
            )

    async def review_code(
        self,
        code: str,
        language: str | None = None,
        focus: list[str] | None = None,
        client: Any = None,
        model: str = "",
    ) -> ReviewResult:
        """代码审查 - 自动发现代码问题和改进建议

        Args:
            code: 待审查的代码
            language: 编程语言（可自动检测）
            focus: 关注的审查维度列表 ("bug", "style", "performance", "security", "maintainability")
            client: OpenAI兼容API客户端
            model: 模型名称

        Returns:
            代码审查结果
        """
        if not client:
            return ReviewResult(
                original_code=code,
                issues=[],
                summary="未提供LLM客户端，无法进行代码审查",
                language=language or "unknown",
            )

        if not language:
            language = self.detect_language(code)

        focus_section = "全面审查（bug、风格、性能、安全、可维护性）"
        if focus:
            focus_names = {
                "bug": "缺陷(Bug)",
                "style": "代码风格",
                "performance": "性能",
                "security": "安全性",
                "maintainability": "可维护性",
            }
            focus_section = "、".join(focus_names.get(f, f) for f in focus)

        prompt = _PROMPT_REVIEW.format(
            language=language,
            focus_section=focus_section,
            code=code,
        )

        logger.info("代码审查: language=%s, focus=%s", language, focus)

        try:
            response_text = await _call_llm(prompt, client, model)
            data = _extract_json(response_text)

            if not data:
                return ReviewResult(
                    original_code=code,
                    summary=response_text,
                    language=language,
                )

            issues: list[ReviewIssue] = []
            for issue_data in data.get("issues", []):
                issues.append(ReviewIssue(
                    severity=issue_data.get("severity", "info"),
                    category=issue_data.get("category", "bug"),
                    line=issue_data.get("line"),
                    message=issue_data.get("message", ""),
                    suggestion=issue_data.get("suggestion", ""),
                ))

            return ReviewResult(
                original_code=code,
                issues=issues,
                summary=data.get("summary", ""),
                score=float(data.get("score", 0)),
                language=language,
            )
        except Exception as exc:
            logger.error("代码审查失败: %s", exc)
            return ReviewResult(
                original_code=code,
                issues=[],
                summary=f"审查失败: {exc}",
                language=language,
            )

    async def refactor_code(
        self,
        code: str,
        goal: str,
        language: str | None = None,
        client: Any = None,
        model: str = "",
    ) -> RefactorResult:
        """代码重构 - 智能代码重构建议和执行

        Args:
            code: 待重构的代码
            goal: 重构目标（如"提升可读性"、"应用设计模式"、"减少重复代码"）
            language: 编程语言（可自动检测）
            client: OpenAI兼容API客户端
            model: 模型名称

        Returns:
            重构结果
        """
        if not client:
            return RefactorResult(
                original_code=code,
                refactored_code="",
                changes_description="未提供LLM客户端，无法进行重构",
                language=language or "unknown",
            )

        if not language:
            language = self.detect_language(code)

        prompt = _PROMPT_REFACTOR.format(
            language=language,
            goal=goal,
            code=code,
        )

        logger.info("代码重构: language=%s, goal=%s", language, goal)

        try:
            response_text = await _call_llm(prompt, client, model)
            data = _extract_json(response_text)

            if not data:
                return RefactorResult(
                    original_code=code,
                    refactored_code="",
                    changes_description=response_text,
                    language=language,
                )

            return RefactorResult(
                original_code=code,
                refactored_code=data.get("refactored_code", ""),
                changes_description=data.get("changes_description", ""),
                language=language,
                applied_patterns=data.get("applied_patterns", []),
            )
        except Exception as exc:
            logger.error("代码重构失败: %s", exc)
            return RefactorResult(
                original_code=code,
                refactored_code="",
                changes_description=f"重构失败: {exc}",
                language=language,
            )

    async def debug_code(
        self,
        code: str,
        error_message: str,
        language: str | None = None,
        client: Any = None,
        model: str = "",
    ) -> DebugResult:
        """代码调试 - 分析错误信息，定位问题，提供修复方案

        Args:
            code: 出错的代码
            error_message: 错误信息
            language: 编程语言（可自动检测）
            client: OpenAI兼容API客户端
            model: 模型名称

        Returns:
            调试结果
        """
        if not client:
            return DebugResult(
                original_code=code,
                error_message=error_message,
                root_cause="未提供LLM客户端，无法分析错误",
                fixed_code="",
                explanation="",
                language=language or "unknown",
            )

        if not language:
            language = self.detect_language(code)

        prompt = _PROMPT_DEBUG.format(
            language=language,
            error_message=error_message,
            code=code,
        )

        logger.info("代码调试: language=%s, error=%s", language, error_message[:100])

        try:
            response_text = await _call_llm(prompt, client, model)
            data = _extract_json(response_text)

            if not data:
                return DebugResult(
                    original_code=code,
                    error_message=error_message,
                    root_cause="",
                    fixed_code="",
                    explanation=response_text,
                    language=language,
                )

            return DebugResult(
                original_code=code,
                error_message=error_message,
                root_cause=data.get("root_cause", ""),
                fixed_code=data.get("fixed_code", ""),
                explanation=data.get("explanation", ""),
                language=language,
            )
        except Exception as exc:
            logger.error("代码调试失败: %s", exc)
            return DebugResult(
                original_code=code,
                error_message=error_message,
                root_cause="",
                fixed_code="",
                explanation=f"调试失败: {exc}",
                language=language,
            )

    async def generate_tests(
        self,
        code: str,
        language: str = "python",
        test_framework: str = "pytest",
        client: Any = None,
        model: str = "",
    ) -> TestResult:
        """单元测试生成 - 自动生成测试用例

        Args:
            code: 待测试的代码
            language: 编程语言
            test_framework: 测试框架 ("pytest" | "unittest" | "jest" | "go test" 等)
            client: OpenAI兼容API客户端
            model: 模型名称

        Returns:
            测试生成结果
        """
        if not client:
            return TestResult(
                original_code=code,
                test_code="",
                test_framework=test_framework,
                language=language,
                coverage_notes="未提供LLM客户端，无法生成测试",
            )

        prompt = _PROMPT_TESTS.format(
            language=language,
            framework=test_framework,
            code=code,
        )

        logger.info("测试生成: language=%s, framework=%s", language, test_framework)

        try:
            response_text = await _call_llm(prompt, client, model)
            data = _extract_json(response_text)

            if not data:
                return TestResult(
                    original_code=code,
                    test_code="",
                    test_framework=test_framework,
                    language=language,
                    coverage_notes=response_text,
                )

            test_cases: list[TestCase] = []
            for tc_data in data.get("test_cases", []):
                test_cases.append(TestCase(
                    name=tc_data.get("name", ""),
                    description=tc_data.get("description", ""),
                    code=tc_data.get("code", ""),
                ))

            return TestResult(
                original_code=code,
                test_code=data.get("test_code", ""),
                test_cases=test_cases,
                test_framework=test_framework,
                language=language,
                coverage_notes=data.get("coverage_notes", ""),
            )
        except Exception as exc:
            logger.error("测试生成失败: %s", exc)
            return TestResult(
                original_code=code,
                test_code="",
                test_framework=test_framework,
                language=language,
                coverage_notes=f"生成失败: {exc}",
            )

    async def generate_docs(
        self,
        code: str,
        language: str | None = None,
        doc_type: str = "docstring",
        client: Any = None,
        model: str = "",
    ) -> DocResult:
        """文档生成 - 自动生成代码文档和注释

        Args:
            code: 待文档化的代码
            language: 编程语言（可自动检测）
            doc_type: 文档类型 ("docstring" | "readme" | "api_doc" | "inline_comment")
            client: OpenAI兼容API客户端
            model: 模型名称

        Returns:
            文档生成结果
        """
        if not client:
            return DocResult(
                original_code=code,
                generated_docs="",
                doc_type=doc_type,
                language=language or "unknown",
            )

        if not language:
            language = self.detect_language(code)

        doc_type_names = {
            "docstring": "函数/类的docstring文档",
            "readme": "README文档",
            "api_doc": "API接口文档",
            "inline_comment": "行内注释",
        }
        type_text = doc_type_names.get(doc_type, doc_type)

        prompt = _PROMPT_DOCS.format(
            language=language,
            doc_type=type_text,
            code=code,
        )

        logger.info("文档生成: language=%s, type=%s", language, doc_type)

        try:
            response_text = await _call_llm(prompt, client, model)
            data = _extract_json(response_text)

            if not data:
                return DocResult(
                    original_code=code,
                    generated_docs=response_text,
                    doc_type=doc_type,
                    language=language,
                )

            return DocResult(
                original_code=code,
                generated_docs=data.get("generated_docs", ""),
                doc_type=doc_type,
                language=language,
            )
        except Exception as exc:
            logger.error("文档生成失败: %s", exc)
            return DocResult(
                original_code=code,
                generated_docs="",
                doc_type=doc_type,
                language=language,
            )

    async def analyze_security(
        self,
        code: str,
        language: str | None = None,
        client: Any = None,
        model: str = "",
    ) -> SecurityResult:
        """安全审计 - 检测常见安全漏洞

        Args:
            code: 待审计的代码
            language: 编程语言（可自动检测）
            client: OpenAI兼容API客户端
            model: 模型名称

        Returns:
            安全审计结果
        """
        if not client:
            return SecurityResult(
                original_code=code,
                issues=[],
                summary="未提供LLM客户端，无法进行安全审计",
                risk_level="unknown",
                language=language or "unknown",
            )

        if not language:
            language = self.detect_language(code)

        # 先做静态规则检查
        static_issues = self._static_security_check(code, language)

        prompt = _PROMPT_SECURITY.format(language=language, code=code)

        logger.info("安全审计: language=%s", language)

        try:
            response_text = await _call_llm(prompt, client, model)
            data = _extract_json(response_text)

            issues: list[SecurityIssue] = list(static_issues)

            if data:
                for issue_data in data.get("issues", []):
                    issues.append(SecurityIssue(
                        severity=issue_data.get("severity", "medium"),
                        category=issue_data.get("category", "other"),
                        line=issue_data.get("line"),
                        description=issue_data.get("description", ""),
                        recommendation=issue_data.get("recommendation", ""),
                        cwe_id=issue_data.get("cwe_id", ""),
                    ))

            return SecurityResult(
                original_code=code,
                issues=issues,
                summary=data.get("summary", "") if data else "",
                risk_level=data.get("risk_level", "medium") if data else "medium",
                language=language,
            )
        except Exception as exc:
            logger.error("安全审计失败: %s", exc)
            return SecurityResult(
                original_code=code,
                issues=static_issues,
                summary=f"审计失败: {exc}",
                risk_level="unknown",
                language=language,
            )

    async def optimize_performance(
        self,
        code: str,
        language: str | None = None,
        client: Any = None,
        model: str = "",
    ) -> PerfResult:
        """性能优化 - 代码性能分析和优化建议

        Args:
            code: 待分析的代码
            language: 编程语言（可自动检测）
            client: OpenAI兼容API客户端
            model: 模型名称

        Returns:
            性能分析结果
        """
        if not client:
            return PerfResult(
                original_code=code,
                issues=[],
                summary="未提供LLM客户端，无法进行性能分析",
                overall_rating="unknown",
                language=language or "unknown",
            )

        if not language:
            language = self.detect_language(code)

        prompt = _PROMPT_PERF.format(language=language, code=code)

        logger.info("性能优化: language=%s", language)

        try:
            response_text = await _call_llm(prompt, client, model)
            data = _extract_json(response_text)

            if not data:
                return PerfResult(
                    original_code=code,
                    summary=response_text,
                    language=language,
                )

            issues: list[PerfIssue] = []
            for issue_data in data.get("issues", []):
                issues.append(PerfIssue(
                    severity=issue_data.get("severity", "medium"),
                    category=issue_data.get("category", "algorithm"),
                    line=issue_data.get("line"),
                    description=issue_data.get("description", ""),
                    suggestion=issue_data.get("suggestion", ""),
                    estimated_impact=issue_data.get("estimated_impact", ""),
                ))

            return PerfResult(
                original_code=code,
                issues=issues,
                summary=data.get("summary", ""),
                overall_rating=data.get("overall_rating", ""),
                language=language,
            )
        except Exception as exc:
            logger.error("性能优化分析失败: %s", exc)
            return PerfResult(
                original_code=code,
                issues=[],
                summary=f"分析失败: {exc}",
                language=language,
            )

    def detect_language(self, code: str) -> str:
        """语言检测 - 基于语法特征识别编程语言

        使用正则模式匹配和AST分析来检测代码语言。
        如果无法确定，返回 "unknown"。

        Args:
            code: 代码文本

        Returns:
            检测到的编程语言名称
        """
        if not code or not code.strip():
            return "unknown"

        # 统计每种语言模式的匹配得分
        scores: dict[str, float] = {}

        for lang, patterns in _LANGUAGE_PATTERNS.items():
            match_count = sum(1 for p in patterns if p.search(code))
            scores[lang] = match_count

        # 获取得分最高的语言
        if not scores or max(scores.values()) == 0:
            return "unknown"

        best_lang = max(scores, key=scores.get)  # type: ignore[arg-type]
        best_score = scores[best_lang]

        # 如果最高分太低（匹配不足），尝试AST分析（仅Python）
        if best_score < 2:
            try:
                ast.parse(code)
                if "python" not in scores or scores.get("python", 0) < best_score:
                    # AST能解析但模式匹配不够，可能确实是Python
                    pass
                else:
                    return "python"
            except (SyntaxError, ValueError):
                pass

        return best_lang if best_score >= 1 else "unknown"

    def _extract_code_block(self, text: str, language: str) -> str:
        """从LLM返回的文本中提取代码块"""
        # 尝试匹配 ```language\n...\n``` 格式
        pattern = re.compile(rf"```(?:{re.escape(language)})?\s*\n(.*?)\n?```", re.DOTALL)
        match = pattern.search(text)
        if match:
            return match.group(1).strip()

        # 尝试匹配任意代码块
        generic_pattern = re.compile(r"```\w*\s*\n(.*?)\n?```", re.DOTALL)
        match = generic_pattern.search(text)
        if match:
            return match.group(1).strip()

        # 如果没有代码块标记，返回原文
        return text.strip()

    def _static_security_check(self, code: str, language: str) -> list[SecurityIssue]:
        """静态安全规则检查（无需LLM的快速检查）"""
        issues: list[SecurityIssue] = []
        lines = code.split("\n")

        for i, line in enumerate(lines, 1):
            line_lower = line.lower().strip()

            # 检测硬编码密码/密钥
            secret_patterns = [
                (r'(?:password|passwd|pwd)\s*=?\s*["\']\S+["\']', "硬编码密码", "CWE-798"),
                (r'(?:api_key|apikey|secret_key|secretkey)\s*=?\s*["\']\S+["\']', "硬编码API密钥", "CWE-798"),
                (r'(?:token|auth_token)\s*=?\s*["\']\S+["\']', "硬编码Token", "CWE-798"),
            ]

            for pattern, desc, cwe in secret_patterns:
                if re.search(pattern, line_lower):
                    issues.append(SecurityIssue(
                        severity="high",
                        category="config",
                        line=i,
                        description=f"检测到{desc}: {line.strip()[:80]}",
                        recommendation="使用环境变量或密钥管理服务存储敏感信息",
                        cwe_id=cwe,
                    ))

            # 检测 eval/exec
            if re.search(r'\beval\s*\(', line):
                issues.append(SecurityIssue(
                    severity="high",
                    category="injection",
                    line=i,
                    description="使用eval()可能导致代码注入",
                    recommendation="避免使用eval，使用更安全的替代方案",
                    cwe_id="CWE-95",
                ))

            if re.search(r'\bexec\s*\(', line):
                issues.append(SecurityIssue(
                    severity="high",
                    category="injection",
                    line=i,
                    description="使用exec()可能导致代码注入",
                    recommendation="避免使用exec，使用更安全的替代方案",
                    cwe_id="CWE-95",
                ))

            # SQL拼接检测
            if re.search(rf'\b(select|insert|update|delete|drop)\b.*\+.*\b', line_lower):
                issues.append(SecurityIssue(
                    severity="high",
                    category="sqli",
                    line=i,
                    description="疑似SQL字符串拼接，存在SQL注入风险",
                    recommendation="使用参数化查询(prepared statements)",
                    cwe_id="CWE-89",
                ))

        return issues


# ---- 单例工厂 ----

_code_intelligence_instance: CodeIntelligence | None = None


def get_code_intelligence() -> CodeIntelligence:
    """获取CodeIntelligence单例实例

    Returns:
        CodeIntelligence实例
    """
    global _code_intelligence_instance
    if _code_intelligence_instance is None:
        _code_intelligence_instance = CodeIntelligence()
        logger.info("CodeIntelligence单例已创建")
    return _code_intelligence_instance
