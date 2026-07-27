"""LUMU 高级推理引擎 - 多策略融合推理系统

实现策略:
1. Chain-of-Thought (CoT): 链式思维推理，逐步分解问题
2. ReAct: 推理-行动循环，Thought -> Action -> Observation
3. Self-Reflection: 自我反思评估输出质量，不自信时自动修正
4. Plan-and-Execute: 复杂任务先规划再执行
5. Tree-of-Thought (ToT): 多路径探索，评分选择最优解
6. Multi-Perspective: 多角度分析同一问题
7. Analogical Reasoning: 类比推理，用已知解决未知
8. Hypothesis Testing: 假设验证，生成假设 -> 验证 -> 结论

所有推理策略均通过调用 LLM 实现，非简单 prompt 拼接。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

# --- 安全导入：确保模块缺失不会导致崩溃 ---
try:
    from core.logging_config import get_logger
    logger = get_logger(__name__)
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

try:
    from openai import AsyncOpenAI
    AsyncOpenAI = AsyncOpenAI  # noqa: PLW0127
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False
    logger.warning("openai 包未安装，推理引擎的 LLM 调用功能将不可用")


# ============================================================================
# 数据模型
# ============================================================================


class StrategyType(str, Enum):
    """推理策略枚举"""
    COT = "chain_of_thought"
    REACT = "react"
    SELF_REFLECTION = "self_reflection"
    PLAN_AND_EXECUTE = "plan_and_execute"
    TOT = "tree_of_thought"
    MULTI_PERSPECTIVE = "multi_perspective"
    ANALOGICAL = "analogical_reasoning"
    HYPOTHESIS_TESTING = "hypothesis_testing"


class DomainType(str, Enum):
    """问题领域"""
    GENERAL = "general"
    CODING = "coding"
    MATH = "math"
    SCIENCE = "science"
    BUSINESS = "business"
    CREATIVE = "creative"
    ANALYSIS = "analysis"
    UNKNOWN = "unknown"


@dataclass
class QueryAnalysis:
    """查询分析结果

    Attributes:
        complexity: 复杂度等级 1-5，1最简单，5最复杂
        query_type: 查询类型描述
        requires_tools: 是否需要外部工具辅助
        domain: 问题所属领域
        urgency: 紧急度 1-5
        keywords: 提取的关键词列表
        suggested_strategies: 系统建议的推理策略组合
    """
    complexity: int = 1
    query_type: str = "general"
    requires_tools: bool = False
    domain: str = DomainType.GENERAL.value
    urgency: int = 1
    keywords: list[str] = field(default_factory=list)
    suggested_strategies: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典"""
        return {
            "complexity": self.complexity,
            "query_type": self.query_type,
            "requires_tools": self.requires_tools,
            "domain": self.domain,
            "urgency": self.urgency,
            "keywords": self.keywords,
            "suggested_strategies": self.suggested_strategies,
        }


@dataclass
class ReasoningResult:
    """单次推理结果

    Attributes:
        strategy: 使用的推理策略名称
        thinking_process: 推理过程的详细记录
        conclusion: 推理得出的结论
        confidence: 结论置信度 0.0-1.0
        tool_suggestions: 建议调用的工具列表
        metadata: 额外的元数据信息
        duration_ms: 推理耗时（毫秒）
    """
    strategy: str = ""
    thinking_process: str = ""
    conclusion: str = ""
    confidence: float = 0.0
    tool_suggestions: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典"""
        return {
            "strategy": self.strategy,
            "thinking_process": self.thinking_process,
            "conclusion": self.conclusion,
            "confidence": self.confidence,
            "tool_suggestions": self.tool_suggestions,
            "metadata": self.metadata,
            "duration_ms": self.duration_ms,
        }


@dataclass
class ReasoningOutput:
    """全自动推理输出

    Attributes:
        analysis: 查询分析结果
        strategies_used: 实际使用的推理策略列表
        merged_conclusion: 合并后的最终结论
        individual_results: 各策略的独立推理结果
        total_duration_ms: 总推理耗时
        quality_score: 整体推理质量评分 0.0-1.0
    """
    analysis: QueryAnalysis = field(default_factory=QueryAnalysis)
    strategies_used: list[str] = field(default_factory=list)
    merged_conclusion: str = ""
    individual_results: list[ReasoningResult] = field(default_factory=list)
    total_duration_ms: float = 0.0
    quality_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典"""
        return {
            "analysis": self.analysis.to_dict(),
            "strategies_used": self.strategies_used,
            "merged_conclusion": self.merged_conclusion,
            "individual_results": [r.to_dict() for r in self.individual_results],
            "total_duration_ms": self.total_duration_ms,
            "quality_score": self.quality_score,
        }


# ============================================================================
# 核心推理引擎
# ============================================================================


class ReasoningEngine:
    """LUMU 高级推理引擎

    实现多策略融合推理系统，根据查询特征自动选择并组合最优推理策略。
    所有推理策略均通过调用 LLM 的 OpenAI 兼容 API 实现。

    Usage:
        engine = get_reasoning_engine()
        output = await engine.auto_reason(
            user_message="请帮我分析这段代码的性能瓶颈",
            context=[],
            client=async_openai_client,
            model="gpt-4o",
        )
    """

    # 复杂度评估关键词权重映射
    _COMPLEXITY_KEYWORDS: dict[str, int] = {
        # 低复杂度 (1-2)
        "是什么": 1, "什么是": 1, "谁": 1, "哪里": 1, "什么时候": 1,
        "翻译": 1, "定义": 1, "意思": 1,
        # 中等复杂度 (2-3)
        "怎么": 2, "如何": 2, "怎么做": 2, "怎样": 2,
        "比较": 3, "区别": 3, "对比": 3, "优缺点": 3,
        # 高复杂度 (3-4)
        "分析": 3, "评估": 3, "优化": 4, "改进": 3,
        "设计": 4, "架构": 4, "重构": 4,
        "为什么": 3, "原因": 3,
        # 最高复杂度 (4-5)
        "研究": 5, "调研": 5, "综述": 5, "论文": 5,
        "推理": 4, "证明": 5, "推导": 4,
        "解决方案": 4, "系统设计": 5, "全面分析": 5,
    }

    # 领域识别关键词
    _DOMAIN_KEYWORDS: dict[str, list[str]] = {
        DomainType.CODING.value: [
            "代码", "编程", "函数", "类", "API", "bug", "错误",
            "编程语言", "Python", "Java", "JavaScript", "框架",
            "code", "function", "class", "API", "bug", "debug",
        ],
        DomainType.MATH.value: [
            "计算", "方程", "公式", "积分", "微分", "证明",
            "calculate", "equation", "formula", "integral", "proof",
        ],
        DomainType.SCIENCE.value: [
            "科学", "实验", "理论", "物理", "化学", "生物",
            "science", "experiment", "theory", "physics", "chemistry",
        ],
        DomainType.BUSINESS.value: [
            "商业", "市场", "策略", "营销", "财务", "投资",
            "business", "market", "strategy", "marketing", "finance",
        ],
        DomainType.CREATIVE.value: [
            "写作", "创意", "故事", "诗歌", "设计", "艺术",
            "writing", "creative", "story", "poem", "design", "art",
        ],
        DomainType.ANALYSIS.value: [
            "分析", "评估", "趋势", "数据", "统计", "报告",
            "analysis", "evaluate", "trend", "data", "statistics", "report",
        ],
    }

    # 策略提示词模板 - 用于指导 LLM 执行特定推理策略
    _STRATEGY_PROMPTS: dict[str, str] = {
        StrategyType.COT: (
            "请使用链式思维（Chain-of-Thought）方法逐步分析以下问题。"
            "请在回答中明确展示你的每一步推理过程，从理解问题开始，"
            "逐步分解、分析每个子问题，最终得出结论。\n\n"
            "请按以下格式回答：\n"
            "## 思考过程\n"
            "[逐步展示你的推理链]\n\n"
            "## 结论\n"
            "[最终答案]"
        ),
        StrategyType.REACT: (
            "请使用 ReAct（Reasoning + Acting）方法处理以下请求。\n\n"
            "格式要求：\n"
            "Thought: [你的推理思考]\n"
            "Action: [如果需要使用工具或执行操作，说明需要什么工具]\n"
            "Observation: [基于已知信息或假设工具返回结果的观察]\n"
            "（可以重复 Thought-Action-Observation 循环）\n"
            "Answer: [最终答案]\n\n"
            "注意：Action 步骤中只需要说明需要什么工具或信息，不需要实际执行。"
        ),
        StrategyType.SELF_REFLECTION: (
            "请回答以下问题，然后对答案进行自我反思和评估。\n\n"
            "格式要求：\n"
            "## 初步回答\n"
            "[你的初步答案]\n\n"
            "## 自我反思\n"
            "- 答案的准确性如何？\n"
            "- 是否有遗漏的重要方面？\n"
            "- 推理过程是否有逻辑漏洞？\n"
            "- 是否需要修正或补充？\n\n"
            "## 最终回答\n"
            "[经过反思后修正的最终答案]"
        ),
        StrategyType.PLAN_AND_EXECUTE: (
            "请使用 Plan-and-Execute 方法处理以下复杂任务。\n\n"
            "格式要求：\n"
            "## 任务计划\n"
            "1. [步骤1的描述]\n"
            "2. [步骤2的描述]\n"
            "3. [步骤3的描述]\n"
            "（根据需要添加更多步骤）\n\n"
            "## 执行过程\n"
            "[按照计划逐步执行，记录每一步的结果]\n\n"
            "## 最终结果\n"
            "[完整的执行结果和总结]"
        ),
        StrategyType.TOT: (
            "请使用 Tree-of-Thought 方法探索以下问题的多种可能解决方案。\n\n"
            "格式要求：\n"
            "## 思维分支\n"
            "### 分支A: [简短描述]\n"
            "推理过程: [该分支的推理]\n"
            "评估: [对该方案的评分和分析，1-10分]\n\n"
            "### 分支B: [简短描述]\n"
            "推理过程: [该分支的推理]\n"
            "评估: [对该方案的评分和分析，1-10分]\n\n"
            "### 分支C: [简短描述]\n"
            "推理过程: [该分支的推理]\n"
            "评估: [对该方案的评分和分析，1-10分]\n\n"
            "## 最优方案\n"
            "[选择评分最高的方案并详细说明原因]\n\n"
            "## 最终答案\n"
            "[基于最优方案的最终答案]"
        ),
        StrategyType.MULTI_PERSPECTIVE: (
            "请从多个角度分析以下问题，确保分析的全面性。\n\n"
            "格式要求：\n"
            "## 视角一: [技术角度]\n"
            "[从技术层面分析]\n\n"
            "## 视角二: [业务/实用角度]\n"
            "[从实用性角度分析]\n\n"
            "## 视角三: [用户/体验角度]\n"
            "[从用户体验角度分析]\n\n"
            "## 视角四: [风险/局限性角度]\n"
            "[分析可能的风险和局限性]\n\n"
            "## 综合分析\n"
            "[综合各角度的分析，给出平衡的结论]"
        ),
        StrategyType.ANALOGICAL: (
            "请使用类比推理方法解决以下问题。\n\n"
            "格式要求：\n"
            "## 类比来源\n"
            "[找到一个已知的相关或相似问题/领域]\n\n"
            "## 类比映射\n"
            "- 当前问题的[元素X] 对应 类比问题的[元素Y]\n"
            "- 当前问题的[元素A] 对应 类比问题的[元素B]\n\n"
            "## 类比推理\n"
            "[通过类比关系，将已知解决方案映射到当前问题]\n\n"
            "## 验证与调整\n"
            "[分析类比的合理性，指出不完美之处并进行调整]\n\n"
            "## 最终方案\n"
            "[基于类比推理得出的解决方案]"
        ),
        StrategyType.HYPOTHESIS_TESTING: (
            "请使用假设验证方法分析以下问题。\n\n"
            "格式要求：\n"
            "## 假设生成\n"
            "假设1: [提出第一个假设]\n"
            "假设2: [提出第二个假设]\n"
            "假设3: [提出第三个假设（可选）]\n\n"
            "## 验证计划\n"
            "[说明如何验证每个假设]\n\n"
            "## 逐一验证\n"
            "### 验证假设1\n"
            "- 证据支持: [...]\n"
            "- 证据反对: [...]\n"
            "- 结论: [接受/拒绝/部分接受]\n\n"
            "### 验证假设2\n"
            "- 证据支持: [...]\n"
            "- 证据反对: [...]\n"
            "- 结论: [接受/拒绝/部分接受]\n\n"
            "## 最终结论\n"
            "[基于验证结果的综合结论]"
        ),
    }

    # ToT 策略的分支评估提示
    _TOT_EVALUATION_PROMPT: str = (
        "请评估以下推理分支的质量，给出1-10的评分和简短理由。\n\n"
        "推理分支:\n{branch_content}\n\n"
        "请按以下JSON格式回复（不要包含其他文本）：\n"
        '{{"score": <1-10的整数>, "reason": "<简短评估理由>"}}'
    )

    # 策略选择映射：复杂度 -> 推荐策略
    _COMPLEXITY_STRATEGY_MAP: dict[str, list[str]] = {
        "1": [StrategyType.COT],
        "2": [StrategyType.COT, StrategyType.SELF_REFLECTION],
        "3": [StrategyType.REACT, StrategyType.SELF_REFLECTION],
        "4": [StrategyType.PLAN_AND_EXECUTE, StrategyType.MULTI_PERSPECTIVE],
        "5": [StrategyType.TOT, StrategyType.HYPOTHESIS_TESTING, StrategyType.MULTI_PERSPECTIVE],
    }

    def __init__(self) -> None:
        """初始化推理引擎"""
        self._initialized: bool = False
        self._init_lock: Optional[asyncio.Lock] = None
        self._call_count: int = 0
        self._cache: dict[str, ReasoningResult] = {}
        self._max_cache_size: int = 100

    async def _ensure_initialized(self) -> None:
        """确保引擎已初始化（延迟初始化）"""
        if self._initialized:
            return
        if self._init_lock is None:
            self._init_lock = asyncio.Lock()
        async with self._init_lock:
            if self._initialized:
                return
            try:
                logger.info("正在初始化推理引擎...")
                self._call_count = 0
                self._cache.clear()
                self._initialized = True
                logger.info("推理引擎初始化完成")
            except Exception as e:
                logger.error(f"推理引擎初始化失败: {e}")
                raise

    # ----------------------------------------------------------------
    # 查询分析
    # ----------------------------------------------------------------

    async def analyze_query(self, message: str) -> QueryAnalysis:
        """分析查询复杂度、类型、需要哪些策略

        通过关键词匹配和启发式规则评估查询特征。

        Args:
            message: 用户输入的消息内容

        Returns:
            QueryAnalysis 包含复杂度、类型、领域、紧急度等分析结果
        """
        await self._ensure_initialized()

        analysis = QueryAnalysis()
        if not message or not message.strip():
            logger.warning("收到空消息，返回默认分析结果")
            return analysis

        message_stripped = message.strip()

        # 1. 复杂度评估
        max_score = 1
        matched_keywords: list[str] = []
        for keyword, score in self._COMPLEXITY_KEYWORDS.items():
            if keyword in message_stripped:
                if score > max_score:
                    max_score = score
                matched_keywords.append(keyword)

        # 长度加权：消息越长通常越复杂
        if len(message_stripped) > 500:
            max_score = min(max_score + 1, 5)
        elif len(message_stripped) > 200:
            max_score = min(max_score, 5)

        # 问题数量加权：包含多个问号通常表示更复杂
        question_count = message_stripped.count("?") + message_stripped.count("？")
        if question_count > 3:
            max_score = min(max_score + 1, 5)

        analysis.complexity = max_score
        analysis.keywords = matched_keywords

        # 2. 领域识别
        best_domain = DomainType.GENERAL.value
        best_domain_score = 0
        for domain, keywords in self._DOMAIN_KEYWORDS.items():
            domain_score = sum(1 for kw in keywords if kw in message_stripped)
            if domain_score > best_domain_score:
                best_domain_score = domain_score
                best_domain = domain
        analysis.domain = best_domain

        # 3. 类型判断
        if analysis.complexity <= 2:
            analysis.query_type = "factual_query"
        elif analysis.complexity <= 3:
            analysis.query_type = "analytical"
        elif analysis.complexity <= 4:
            analysis.query_type = "complex_reasoning"
        else:
            analysis.query_type = "research_level"

        # 4. 工具需求判断
        tool_keywords = [
            "搜索", "查找", "计算", "运行", "执行", "编译",
            "search", "calculate", "run", "execute", "compile",
            "当前时间", "天气", "最新", "实时",
        ]
        analysis.requires_tools = any(kw in message_stripped for kw in tool_keywords)

        # 5. 紧急度评估
        urgency_keywords = [
            ("紧急", 5), ("立即", 5), ("马上", 4), ("尽快", 4),
            ("urgent", 5), ("immediately", 5), ("asap", 4),
            ("帮我", 2), ("麻烦", 2), ("请", 1),
        ]
        for kw, score in urgency_keywords:
            if kw in message_stripped:
                analysis.urgency = max(analysis.urgency, score)

        # 6. 推荐策略
        complexity_key = str(analysis.complexity)
        if complexity_key in self._COMPLEXITY_STRATEGY_MAP:
            analysis.suggested_strategies = list(
                self._COMPLEXITY_STRATEGY_MAP[complexity_key]
            )

        # 针对特定领域的策略覆盖
        if analysis.domain == DomainType.CODING.value:
            if StrategyType.REACT not in analysis.suggested_strategies:
                analysis.suggested_strategies.insert(0, StrategyType.REACT)
        elif analysis.domain == DomainType.MATH.value:
            if StrategyType.COT not in analysis.suggested_strategies:
                analysis.suggested_strategies.insert(0, StrategyType.COT)

        logger.info(
            f"查询分析完成: 复杂度={analysis.complexity}, "
            f"领域={analysis.domain}, 策略={analysis.suggested_strategies}"
        )
        return analysis

    # ----------------------------------------------------------------
    # 策略选择
    # ----------------------------------------------------------------

    def select_strategies(self, analysis: QueryAnalysis) -> list[str]:
        """根据查询分析结果自动选择推理策略组合

        Args:
            analysis: 查询分析结果

        Returns:
            推荐使用的推理策略列表（按优先级排序）
        """
        if not analysis.suggested_strategies:
            return [StrategyType.COT]

        # 根据紧急度调整策略数量：越紧急用越少的策略以保证响应速度
        strategies = list(analysis.suggested_strategies)
        if analysis.urgency >= 4:
            strategies = strategies[:1]
        elif analysis.urgency >= 3:
            strategies = strategies[:2]

        logger.debug(f"选择的推理策略: {strategies}")
        return strategies

    # ----------------------------------------------------------------
    # 执行推理
    # ----------------------------------------------------------------

    async def execute_reasoning(
        self,
        messages: list[dict[str, Any]],
        strategy: str,
        client: Any,
        model: str,
    ) -> ReasoningResult:
        """执行特定推理策略（调用 LLM 进行推理）

        构建针对特定策略的 prompt，通过 LLM API 调用实现推理。
        对于 ToT 策略，会实现分支评估和选择。

        Args:
            messages: 对话消息列表，格式为 [{"role": "...", "content": "..."}]
            strategy: 推理策略名称，对应 StrategyType 枚举值
            client: OpenAI 兼容的异步客户端实例
            model: 使用的模型名称

        Returns:
            ReasoningResult 包含推理过程、结论、置信度等

        Raises:
            ValueError: 策略名称无效
            RuntimeError: LLM 调用失败且无法恢复
        """
        await self._ensure_initialized()

        start_time = time.monotonic()
        result = ReasoningResult(strategy=strategy)

        # 验证策略名称
        valid_strategies = [s.value for s in StrategyType]
        if strategy not in valid_strategies:
            logger.error(f"无效的推理策略: {strategy}，有效值: {valid_strategies}")
            raise ValueError(
                f"无效的推理策略 '{strategy}'，有效值: {valid_strategies}"
            )

        # 获取策略提示词
        strategy_prompt = self._STRATEGY_PROMPTS.get(strategy, "")
        if not strategy_prompt:
            logger.error(f"策略 '{strategy}' 缺少对应的提示词模板")
            raise ValueError(f"策略 '{strategy}' 未配置提示词模板")

        try:
            # ToT 策略需要特殊处理（多分支推理+评估）
            if strategy == StrategyType.TOT:
                result = await self._execute_tot_reasoning(
                    messages=messages, client=client, model=model
                )
            else:
                # 构建包含策略指导的消息
                reasoning_messages = self._build_reasoning_messages(
                    messages=messages, strategy_prompt=strategy_prompt
                )

                # 调用 LLM
                response = await self._call_llm(
                    client=client,
                    model=model,
                    messages=reasoning_messages,
                )

                # 解析响应
                thinking_process, conclusion, confidence = self._parse_response(
                    response=response, strategy=strategy
                )
                result.thinking_process = thinking_process
                result.conclusion = conclusion
                result.confidence = confidence

            # 提取工具建议
            result.tool_suggestions = self._extract_tool_suggestions(
                result.thinking_process + "\n" + result.conclusion
            )

        except asyncio.TimeoutError:
            logger.error(f"推理策略 '{strategy}' 执行超时")
            result.thinking_process = f"[推理超时] 策略: {strategy}"
            result.conclusion = (
                "抱歉，推理过程超时，请尝试简化问题或减少推理策略数量。"
            )
            result.confidence = 0.1
        except Exception as e:
            logger.error(f"推理策略 '{strategy}' 执行失败: {e}", exc_info=True)
            result.thinking_process = f"[推理错误] 策略: {strategy}, 错误: {str(e)}"
            result.conclusion = f"推理过程遇到错误: {str(e)}"
            result.confidence = 0.0

        result.duration_ms = (time.monotonic() - start_time) * 1000
        self._call_count += 1

        logger.info(
            f"推理完成: 策略={strategy}, "
            f"置信度={result.confidence:.2f}, "
            f"耗时={result.duration_ms:.1f}ms"
        )
        return result

    async def _execute_tot_reasoning(
        self,
        messages: list[dict[str, Any]],
        client: Any,
        model: str,
        num_branches: int = 3,
    ) -> ReasoningResult:
        """执行 Tree-of-Thought 推理策略

        ToT 策略的实现流程:
        1. 让 LLM 生成多个思维分支
        2. 对每个分支进行评估打分
        3. 选择最优分支作为最终结论

        Args:
            messages: 对话消息列表
            client: LLM 客户端
            model: 模型名称
            num_branches: 生成的分支数量

        Returns:
            ReasoningResult 包含最优分支的推理结果
        """
        result = ReasoningResult(strategy=StrategyType.TOT)

        # 构建分支生成提示
        branch_prompt = self._STRATEGY_PROMPTS[StrategyType.TOT]
        reasoning_messages = self._build_reasoning_messages(
            messages=messages, strategy_prompt=branch_prompt
        )

        # 生成多分支推理
        response = await self._call_llm(
            client=client, model=model, messages=reasoning_messages,
        )

        # 解析各分支
        branches = self._parse_tot_branches(response)
        result.thinking_process = response

        if not branches:
            # 如果无法解析分支，降级为普通 CoT 处理
            logger.warning("ToT 分支解析失败，降级为普通推理")
            thinking, conclusion, confidence = self._parse_response(
                response=response, strategy=StrategyType.TOT
            )
            result.conclusion = conclusion
            result.confidence = confidence
            return result

        # 评估各分支
        branch_scores: list[tuple[str, int, str]] = []
        evaluation_tasks = []
        for branch_content in branches:
            task = self._evaluate_tot_branch(
                client=client, model=model, branch_content=branch_content
            )
            evaluation_tasks.append(task)

        # 并发评估所有分支
        eval_results = await asyncio.gather(*evaluation_tasks, return_exceptions=True)

        for i, eval_result in enumerate(eval_results):
            branch_content = branches[i]
            if isinstance(eval_result, Exception):
                logger.warning(f"分支 {i+1} 评估失败: {eval_result}")
                branch_scores.append((branch_content, 5, "评估失败，给默认分"))
            else:
                branch_scores.append(
                    (branch_content, eval_result["score"], eval_result["reason"])
                )

        # 选择最优分支
        branch_scores.sort(key=lambda x: x[1], reverse=True)
        best_branch = branch_scores[0]

        result.conclusion = (
            f"[ToT 最优分支 - 评分: {best_branch[1]}/10, "
            f"理由: {best_branch[2]}]\n\n"
            f"{best_branch[0]}"
        )
        result.confidence = min(best_branch[1] / 10.0, 1.0)
        result.metadata["num_branches"] = len(branches)
        result.metadata["branch_scores"] = [
            {"score": s, "reason": r} for _, s, r in branch_scores
        ]

        return result

    async def _evaluate_tot_branch(
        self,
        client: Any,
        model: str,
        branch_content: str,
    ) -> dict[str, Any]:
        """评估 ToT 单个思维分支的质量

        Args:
            client: LLM 客户端
            model: 模型名称
            branch_content: 分支内容

        Returns:
            包含 score 和 reason 的字典
        """
        eval_prompt = self._TOT_EVALUATION_PROMPT.format(
            branch_content=branch_content
        )

        eval_messages = [
            {"role": "system", "content": "你是一个推理评估专家，负责评估思维分支的质量。"},
            {"role": "user", "content": eval_prompt},
        ]

        response = await self._call_llm(
            client=client, model=model, messages=eval_messages,
            temperature=0.1,
        )

        # 尝试解析 JSON 格式的评估结果
        try:
            json_str = response.strip()
            if "```json" in json_str:
                json_str = json_str.split("```json")[1].split("```")[0].strip()
            elif "```" in json_str:
                json_str = json_str.split("```")[1].split("```")[0].strip()

            eval_result = json.loads(json_str)
            return {
                "score": int(eval_result.get("score", 5)),
                "reason": str(eval_result.get("reason", "未提供理由")),
            }
        except (json.JSONDecodeError, ValueError, KeyError):
            logger.warning("分支评估结果 JSON 解析失败，使用默认评分")
            return {"score": 5, "reason": "评估结果格式异常，使用默认分"}

    def _parse_tot_branches(self, response: str) -> list[str]:
        """从 ToT 响应中解析各个思维分支

        Args:
            response: LLM 的完整响应文本

        Returns:
            各分支内容列表
        """
        import re

        branches: list[str] = []

        # 尝试按 "### 分支" 格式解析
        branch_pattern = re.compile(
            r"###\s*分支[ABC\d][:：]\s*(.+?)(?=###|$)", re.DOTALL
        )
        matches = branch_pattern.findall(response)

        if matches:
            branches = [m.strip() for m in matches if m.strip()]
        else:
            # 备选：按 "分支A:" 格式解析
            branch_pattern_alt = re.compile(
                r"分支[ABC][:：]\s*(.+?)(?=分支[A-Z][:：]|##|$)", re.DOTALL
            )
            matches_alt = branch_pattern_alt.findall(response)
            branches = [m.strip() for m in matches_alt if m.strip()]

        return branches[:5]  # 最多保留5个分支

    # ----------------------------------------------------------------
    # LLM 调用基础设施
    # ----------------------------------------------------------------

    @staticmethod
    def _build_reasoning_messages(
        messages: list[dict[str, Any]],
        strategy_prompt: str,
    ) -> list[dict[str, Any]]:
        """构建包含推理策略指导的消息列表

        Args:
            messages: 原始对话消息
            strategy_prompt: 策略提示词

        Returns:
            增强后的消息列表
        """
        system_content = (
            "你是一个高级推理助手，擅长使用多种推理策略解决复杂问题。\n"
            "请严格按照指定的推理策略格式输出你的推理过程。\n"
            "确保推理过程清晰、有逻辑、有深度。"
        )

        reasoning_messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_content}
        ]

        # 将策略提示作为用户消息的前缀插入
        first_user_found = False
        for msg in messages:
            new_msg = dict(msg)
            if msg.get("role") == "user" and not first_user_found:
                # 在第一个用户消息前注入策略指导
                new_msg["content"] = (
                    f"{strategy_prompt}\n\n"
                    f"--- 以下是需要推理的问题 ---\n\n"
                    f"{msg.get('content', '')}"
                )
                first_user_found = True
            reasoning_messages.append(new_msg)

        return reasoning_messages

    @staticmethod
    async def _call_llm(
        client: Any,
        model: str,
        messages: list[dict[str, Any]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        timeout: float = 120.0,
    ) -> str:
        """调用 LLM API

        Args:
            client: OpenAI 兼容的异步客户端
            model: 模型名称
            messages: 消息列表
            temperature: 采样温度
            max_tokens: 最大生成 token 数
            timeout: 超时时间（秒）

        Returns:
            LLM 的文本响应

        Raises:
            RuntimeError: LLM 调用失败
            asyncio.TimeoutError: 调用超时
        """
        if not HAS_OPENAI:
            raise RuntimeError("openai 包未安装，无法调用 LLM")

        try:
            response = await asyncio.wait_for(
                client.chat.completions.create(
                    model=model,
                    messages=messages,  # type: ignore[arg-type]
                    temperature=temperature,
                    max_tokens=max_tokens,
                ),
                timeout=timeout,
            )

            content = ""
            if response.choices and len(response.choices) > 0:
                content = response.choices[0].message.content or ""
            return content.strip()

        except asyncio.TimeoutError:
            raise
        except AttributeError as e:
            raise RuntimeError(f"LLM 客户端配置错误: {e}") from e
        except Exception as e:
            raise RuntimeError(f"LLM 调用失败: {e}") from e

    @staticmethod
    def _parse_response(
        response: str, strategy: str
    ) -> tuple[str, str, float]:
        """解析 LLM 响应，提取推理过程、结论和置信度

        Args:
            response: LLM 的原始响应文本
            strategy: 使用的策略名称

        Returns:
            (thinking_process, conclusion, confidence) 元组
        """
        if not response:
            return ("无响应内容", "", 0.0)

        thinking_process = response
        conclusion = ""
        confidence = 0.7  # 默认置信度

        # 尝试提取结论部分
        conclusion_markers = [
            "## 结论", "## 最终回答", "## 最终结论", "## 最终答案",
            "## 最优方案", "# 结论", "# 最终回答",
            "Answer:", "最终答案:", "结论:",
        ]
        for marker in conclusion_markers:
            if marker in response:
                parts = response.split(marker, 1)
                if len(parts) > 1:
                    thinking_process = parts[0].strip()
                    conclusion = parts[1].strip()
                    break

        # 如果没有明确结论，使用最后一段作为结论
        if not conclusion:
            paragraphs = [p.strip() for p in response.split("\n\n") if p.strip()]
            if len(paragraphs) > 1:
                thinking_process = "\n\n".join(paragraphs[:-1])
                conclusion = paragraphs[-1]
            else:
                conclusion = response

        # 尝试从 Self-Reflection 响应中提取置信度
        if strategy == StrategyType.SELF_REFLECTION:
            confidence = ReasoningEngine._extract_confidence_from_reflection(
                response
            )

        return thinking_process, conclusion, confidence

    @staticmethod
    def _extract_confidence_from_reflection(response: str) -> float:
        """从自我反思响应中提取置信度

        查找类似 "置信度: 85%" 或 "confidence: 0.85" 的模式

        Args:
            response: 响应文本

        Returns:
            0.0-1.0 之间的置信度值
        """
        import re

        patterns = [
            r"(?:置信度|confidence|信心)[：:]\s*(\d+(?:\.\d+)?)\s*[%％]?",
            r"(\d+(?:\.\d+)?)\s*[%％]\s*(?:置信|信心|confident)",
        ]
        for pattern in patterns:
            match = re.search(pattern, response, re.IGNORECASE)
            if match:
                try:
                    value = float(match.group(1))
                    return min(max(value / 100.0 if value > 1.0 else value, 0.0), 1.0)
                except ValueError:
                    continue

        return 0.7  # 默认值

    @staticmethod
    def _extract_tool_suggestions(text: str) -> list[str]:
        """从推理文本中提取工具调用建议

        Args:
            text: 推理过程文本

        Returns:
            工具建议列表
        """
        import re

        suggestions: list[str] = []
        tool_patterns = [
            r"需要(?:使用|调用)?[：:]?\s*(.+?)(?:工具|API|服务|来)",
            r"(?:建议|推荐)使用[：:]?\s*(.+?)(?:工具|API|服务)",
            r"Action:\s*(.+)",
        ]
        for pattern in tool_patterns:
            matches = re.findall(pattern, text)
            suggestions.extend(m.strip() for m in matches if m.strip())

        return list(dict.fromkeys(suggestions))[:5]  # 去重并限制数量

    # ----------------------------------------------------------------
    # 结果合并
    # ----------------------------------------------------------------

    def merge_results(self, results: list[ReasoningResult]) -> str:
        """合并多个推理结果

        按置信度加权合并各策略的结论，并展示各自的推理过程摘要。

        Args:
            results: 多个推理结果列表

        Returns:
            合并后的综合结论文本
        """
        if not results:
            return "无推理结果可供合并。"

        if len(results) == 1:
            return results[0].conclusion

        # 按置信度排序
        sorted_results = sorted(results, key=lambda r: r.confidence, reverse=True)

        # 构建合并输出
        output_parts: list[str] = []

        # 综合结论（基于置信度加权）
        total_confidence = sum(r.confidence for r in results)
        if total_confidence > 0:
            weighted_parts: list[str] = []
            for r in sorted_results:
                weight = r.confidence / total_confidence
                weighted_parts.append(f"[权重: {weight:.1%}] {r.conclusion}")
            output_parts.append(
                "## 综合结论（置信度加权）\n" + "\n\n".join(weighted_parts)
            )
        else:
            output_parts.append("## 综合结论\n" + results[0].conclusion)

        # 各策略摘要
        output_parts.append("\n## 各策略推理摘要")
        for r in sorted_results:
            summary = self._summarize_thinking(r.thinking_process, max_lines=5)
            output_parts.append(
                f"\n### {r.strategy} (置信度: {r.confidence:.0%})\n{summary}"
            )

        # 工具建议汇总
        all_tools: list[str] = []
        for r in results:
            all_tools.extend(r.tool_suggestions)
        if all_tools:
            unique_tools = list(dict.fromkeys(all_tools))
            output_parts.append(
                "\n## 建议工具\n" + "\n".join(f"- {t}" for t in unique_tools)
            )

        return "\n".join(output_parts)

    @staticmethod
    def _summarize_thinking(text: str, max_lines: int = 5) -> str:
        """将推理过程摘要为有限行数

        Args:
            text: 原始推理过程文本
            max_lines: 最大行数

        Returns:
            摘要文本
        """
        if not text:
            return "(无推理过程记录)"
        lines = [l for l in text.split("\n") if l.strip()]
        if len(lines) <= max_lines:
            return "\n".join(lines)
        return "\n".join(lines[:max_lines]) + f"\n... (共 {len(lines)} 行)"

    # ----------------------------------------------------------------
    # 全自动推理入口
    # ----------------------------------------------------------------

    async def auto_reason(
        self,
        user_message: str,
        context: list[dict[str, Any]],
        client: Any,
        model: str,
    ) -> ReasoningOutput:
        """全自动推理入口

        执行完整推理流程:
        1. 分析查询特征
        2. 选择推理策略
        3. 并行执行各策略
        4. 合并结果
        5. 返回综合输出

        Args:
            user_message: 用户消息
            context: 对话上下文（历史消息列表）
            client: OpenAI 兼容的异步客户端
            model: 模型名称

        Returns:
            ReasoningOutput 包含分析、各策略结果和合并结论
        """
        await self._ensure_initialized()

        start_time = time.monotonic()
        output = ReasoningOutput()

        if not user_message or not user_message.strip():
            logger.warning("收到空用户消息，跳过推理")
            output.merged_conclusion = "请提供需要推理的问题或任务。"
            return output

        try:
            # Step 1: 分析查询
            output.analysis = await self.analyze_query(user_message)

            # Step 2: 选择策略
            strategies = self.select_strategies(output.analysis)
            output.strategies_used = strategies

            if not strategies:
                logger.warning("未选择到合适的推理策略，使用默认 CoT")
                strategies = [StrategyType.COT]
                output.strategies_used = strategies

            # Step 3: 构建消息上下文
            messages = list(context) if context else []
            messages.append({"role": "user", "content": user_message})

            # Step 4: 并行执行各策略
            tasks = []
            for strategy in strategies:
                task = self.execute_reasoning(
                    messages=messages,
                    strategy=strategy,
                    client=client,
                    model=model,
                )
                tasks.append(task)

            results = await asyncio.gather(*tasks, return_exceptions=True)

            # 收集有效结果
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.error(
                        f"策略 {strategies[i]} 执行异常: {result}",
                        exc_info=result,
                    )
                    output.individual_results.append(
                        ReasoningResult(
                            strategy=strategies[i],
                            thinking_process=f"[异常] {str(result)}",
                            conclusion="该策略执行失败",
                            confidence=0.0,
                        )
                    )
                elif isinstance(result, ReasoningResult):
                    output.individual_results.append(result)
                else:
                    logger.warning(
                        f"策略 {strategies[i]} 返回了意外类型: {type(result)}"
                    )

            # Step 5: 合并结果
            valid_results = [
                r for r in output.individual_results if r.confidence > 0
            ]
            if valid_results:
                output.merged_conclusion = self.merge_results(valid_results)
                output.quality_score = (
                    sum(r.confidence for r in valid_results) / len(valid_results)
                )
            elif output.individual_results:
                output.merged_conclusion = (
                    "所有推理策略均执行失败，请尝试简化问题。"
                )
                output.quality_score = 0.0
            else:
                output.merged_conclusion = "无可用推理结果。"

        except Exception as e:
            logger.error(f"全自动推理流程失败: {e}", exc_info=True)
            output.merged_conclusion = f"推理流程异常: {str(e)}"
            output.quality_score = 0.0

        output.total_duration_ms = (time.monotonic() - start_time) * 1000

        logger.info(
            f"全自动推理完成: 策略数={len(output.strategies_used)}, "
            f"质量评分={output.quality_score:.2f}, "
            f"总耗时={output.total_duration_ms:.1f}ms"
        )
        return output


# ============================================================================
# 单例工厂
# ============================================================================

_reasoning_engine_instance: Optional[ReasoningEngine] = None
_reasoning_engine_lock: Optional[asyncio.Lock] = None


async def get_reasoning_engine() -> ReasoningEngine:
    """获取推理引擎的单例实例（延迟初始化）

    确保整个应用生命周期中只存在一个 ReasoningEngine 实例。
    首次调用时执行初始化，后续调用直接返回已有实例。

    Returns:
        ReasoningEngine 单例实例
    """
    global _reasoning_engine_instance, _reasoning_engine_lock

    if _reasoning_engine_instance is not None:
        return _reasoning_engine_instance

    if _reasoning_engine_lock is None:
        _reasoning_engine_lock = asyncio.Lock()

    async with _reasoning_engine_lock:
        if _reasoning_engine_instance is None:
            _reasoning_engine_instance = ReasoningEngine()
            await _reasoning_engine_instance._ensure_initialized()
            logger.info("推理引擎单例已创建")

    return _reasoning_engine_instance


# ============================================================================
# 辅助函数
# ============================================================================


def generate_cache_key(message: str, strategy: str) -> str:
    """生成推理缓存键

    Args:
        message: 用户消息
        strategy: 推理策略

    Returns:
        缓存键哈希值
    """
    raw = f"{strategy}:{message}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()
