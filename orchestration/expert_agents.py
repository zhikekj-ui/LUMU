"""LUMU 专家Agent协同系统 - 专业领域Agent编排

核心能力:
1. 专家Agent池: 预定义的专业领域Agent（代码专家/数据分析师/文档专家/搜索专家/系统专家）
2. 任务分解: 将复杂任务分解为子任务，分配给合适的专家Agent
3. 并行执行: 多个Agent并行处理独立子任务
4. 结果合并: 智能合并多个Agent的输出结果
5. 动态调度: 根据任务类型和Agent能力动态分配
6. Agent间通信: Agent之间可以互相请求帮助
7. 质量评估: 对Agent输出质量进行评估和筛选
8. 争议解决: 多个Agent结果冲突时智能仲裁

使用示例:
    orchestrator = ExpertOrchestrator()
    result = await orchestrator.orchestrate(
        user_message="帮我重构这段代码并写一份文档",
        client=client,
        model="gpt-4o"
    )
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable

# 日志库导入，模块缺失时降级为print
try:
    from core.logging_config import get_logger
    _logger = get_logger(__name__)
except ImportError:
    import logging
    import sys
    _logger = logging.getLogger(__name__)
    if not _logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(logging.DEBUG)
        _logger.addHandler(handler)
    _logger.setLevel(logging.DEBUG)


# ============================================================
# 数据类定义
# ============================================================


class TaskPriority(Enum):
    """任务优先级枚举"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class SubTaskStatus(Enum):
    """子任务状态枚举"""
    PENDING = "pending"
    ASSIGNED = "assigned"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class ExpertAgent:
    """专家Agent定义

    Attributes:
        name: Agent唯一标识名称
        display_name: Agent展示名称
        description: Agent能力描述
        capabilities: Agent具备的能力标签列表
        system_prompt: Agent的系统提示词
        max_retries: 最大重试次数
        timeout_seconds: 超时时间（秒）
    """
    name: str
    display_name: str
    description: str
    capabilities: list[str] = field(default_factory=list)
    system_prompt: str = ""
    max_retries: int = 2
    timeout_seconds: float = 120.0

    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式"""
        return {
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "capabilities": self.capabilities,
        }


@dataclass
class SubTask:
    """子任务定义

    Attributes:
        id: 子任务唯一标识
        description: 子任务描述
        assigned_agent: 分配的专家Agent名称
        priority: 任务优先级
        status: 任务状态
        dependencies: 依赖的其他子任务ID列表
        context: 子任务的额外上下文信息
        max_tokens: 最大生成token数
    """
    id: str
    description: str
    assigned_agent: str = ""
    priority: TaskPriority = TaskPriority.MEDIUM
    status: SubTaskStatus = SubTaskStatus.PENDING
    dependencies: list[str] = field(default_factory=list)
    context: str = ""
    max_tokens: int = 4096


@dataclass
class SubTaskResult:
    """子任务执行结果

    Attributes:
        subtask_id: 子任务ID
        agent_name: 执行Agent名称
        content: 生成的内容
        success: 是否执行成功
        quality_score: 质量评分(0-1)
        error_message: 错误信息（失败时）
        execution_time: 执行耗时（秒）
        token_usage: token使用量
    """
    subtask_id: str
    agent_name: str
    content: str = ""
    success: bool = True
    quality_score: float = 0.0
    error_message: str = ""
    execution_time: float = 0.0
    token_usage: dict[str, int] = field(default_factory=dict)


@dataclass
class TaskDecomposition:
    """任务分解结果

    Attributes:
        original_task: 原始任务描述
        subtasks: 分解后的子任务列表
        reasoning: 分解推理过程
        estimated_complexity: 预估复杂度(1-10)
    """
    original_task: str
    subtasks: list[SubTask]
    reasoning: str = ""
    estimated_complexity: int = 5


@dataclass
class MergeResult:
    """结果合并输出

    Attributes:
        merged_content: 合并后的最终内容
        sources: 参与合并的子任务结果ID列表
        conflicts_resolved: 解决的冲突数量
        merge_strategy: 合并策略描述
        quality_score: 合并结果质量评分
    """
    merged_content: str
    sources: list[str] = field(default_factory=list)
    conflicts_resolved: int = 0
    merge_strategy: str = ""
    quality_score: float = 0.0


@dataclass
class OrchestrationResult:
    """编排最终结果

    Attributes:
        final_output: 最终输出内容
        subtask_results: 所有子任务的执行结果
        task_decomposition: 任务分解信息
        merge_result: 合并结果信息
        total_execution_time: 总执行耗时（秒）
        success: 整体是否成功
        error_message: 错误信息
    """
    final_output: str = ""
    subtask_results: list[SubTaskResult] = field(default_factory=list)
    task_decomposition: TaskDecomposition | None = None
    merge_result: MergeResult | None = None
    total_execution_time: float = 0.0
    success: bool = True
    error_message: str = ""


# ============================================================
# 预定义专家Agent池
# ============================================================

_BUILTIN_EXPERT_AGENTS: list[ExpertAgent] = [
    ExpertAgent(
        name="code_expert",
        display_name="代码开发专家",
        description="擅长编写、调试、重构代码，精通多种编程语言和设计模式",
        capabilities=["coding", "debugging", "refactoring", "architecture", "testing"],
        system_prompt=(
            "你是一位资深代码开发专家。你的职责是：\n"
            "1. 编写高质量、可维护的代码\n"
            "2. 调试和修复代码问题\n"
            "3. 重构代码提升质量\n"
            "4. 设计合理的架构方案\n"
            "5. 编写和完善测试用例\n"
            "请始终给出可直接使用的代码，并附上必要的说明。"
        ),
    ),
    ExpertAgent(
        name="data_analyst",
        display_name="数据分析专家",
        description="擅长数据处理、可视化、统计分析，精通Python数据科学生态",
        capabilities=["data_processing", "visualization", "statistics", "analysis", "ml"],
        system_prompt=(
            "你是一位资深数据分析专家。你的职责是：\n"
            "1. 处理和清洗数据\n"
            "2. 进行统计分析\n"
            "3. 创建数据可视化\n"
            "4. 提供数据驱动的洞察\n"
            "5. 搭建机器学习模型\n"
            "请用清晰、数据驱动的方式回答问题。"
        ),
    ),
    ExpertAgent(
        name="doc_writer",
        display_name="文档专家",
        description="擅长技术文档写作、总结、翻译，精通中英文双语",
        capabilities=["writing", "documentation", "summarization", "translation", "editing"],
        system_prompt=(
            "你是一位资深文档专家。你的职责是：\n"
            "1. 撰写清晰的技术文档\n"
            "2. 总结归纳复杂内容\n"
            "3. 进行高质量翻译\n"
            "4. 编辑和润色文本\n"
            "请保持语言简洁明了、结构清晰。"
        ),
    ),
    ExpertAgent(
        name="search_expert",
        display_name="搜索专家",
        description="擅长信息检索、事实核查、知识查询",
        capabilities=["search", "fact_checking", "information_retrieval", "verification"],
        system_prompt=(
            "你是一位资深搜索和信息检索专家。你的职责是：\n"
            "1. 精准检索相关信息\n"
            "2. 核实事实准确性\n"
            "3. 整合多方信息来源\n"
            "4. 提供可信的信息参考\n"
            "请确保所有信息的准确性和时效性。"
        ),
    ),
    ExpertAgent(
        name="system_admin",
        display_name="系统专家",
        description="擅长系统管理、部署、运维，精通Linux和容器技术",
        capabilities=["system_admin", "deployment", "devops", "monitoring", "infrastructure"],
        system_prompt=(
            "你是一位资深系统管理和运维专家。你的职责是：\n"
            "1. 系统配置和优化\n"
            "2. 应用部署和发布\n"
            "3. 监控和告警配置\n"
            "4. 故障排查和修复\n"
            "5. 基础设施管理\n"
            "请给出可直接执行的命令和配置。"
        ),
    ),
    ExpertAgent(
        name="researcher",
        display_name="研究专家",
        description="擅长深度分析、研究报告、逻辑推理",
        capabilities=["research", "analysis", "reasoning", "report", "deep_thinking"],
        system_prompt=(
            "你是一位资深研究分析师。你的职责是：\n"
            "1. 进行深度分析研究\n"
            "2. 撰写专业研究报告\n"
            "3. 进行严密的逻辑推理\n"
            "4. 提供有深度的洞察和建议\n"
            "请确保分析过程严谨、结论有据可依。"
        ),
    ),
    ExpertAgent(
        name="creative",
        display_name="创意专家",
        description="擅长创意写作、头脑风暴、创新设计",
        capabilities=["creative_writing", "brainstorming", "design", "innovation", "storytelling"],
        system_prompt=(
            "你是一位资深创意专家。你的职责是：\n"
            "1. 进行创意头脑风暴\n"
            "2. 撰写创意内容\n"
            "3. 设计创新方案\n"
            "4. 提供独特的视角和灵感\n"
            "请发挥创造力，给出新颖且有价值的想法。"
        ),
    ),
]


# ============================================================
# 核心编排器
# ============================================================


class ExpertOrchestrator:
    """专家Agent协同编排器

    负责任务分解、Agent分配、并行执行和结果合并的完整流程。

    Attributes:
        agents: 专家Agent字典，key为agent名称
        max_parallel: 最大并行执行数
    """

    def __init__(
        self,
        custom_agents: list[ExpertAgent] | None = None,
        max_parallel: int = 5,
    ) -> None:
        """初始化编排器

        Args:
            custom_agents: 自定义专家Agent列表，会追加到内置Agent池中
            max_parallel: 最大并行执行子任务数
        """
        self.agents: dict[str, ExpertAgent] = {}
        self.max_parallel: int = max(max_parallel, 1)

        # 加载内置专家Agent
        for agent in _BUILTIN_EXPERT_AGENTS:
            self.agents[agent.name] = agent

        # 追加自定义Agent
        if custom_agents:
            for agent in custom_agents:
                if agent.name in self.agents:
                    _logger.warning("自定义Agent '%s' 覆盖了内置Agent", agent.name)
                self.agents[agent.name] = agent

        _logger.info(
            "ExpertOrchestrator 初始化完成，共加载 %d 个专家Agent",
            len(self.agents),
        )

    # ----------------------------------------------------------
    # 公共方法
    # ----------------------------------------------------------

    async def decompose_task(
        self,
        user_message: str,
        client: Any | None = None,
        model: str = "",
    ) -> TaskDecomposition:
        """将用户任务分解为子任务

        调用LLM分析用户消息，识别需要哪些专家领域，
        然后将任务拆分为可独立执行的子任务。

        Args:
            user_message: 用户的原始任务描述
            client: OpenAI兼容的异步客户端
            model: 使用的模型名称

        Returns:
            TaskDecomposition: 包含子任务列表的分解结果

        Raises:
            ValueError: 当client或model未提供时
        """
        self._validate_client_model(client, model, "decompose_task")

        # 构建Agent能力描述
        agent_descriptions = self._build_agent_descriptions()

        prompt = (
            f"你是一个任务分解专家。请分析以下用户任务，将其分解为子任务。\n\n"
            f"可用专家Agent:\n{agent_descriptions}\n\n"
            f"用户任务: {user_message}\n\n"
            f'请以JSON格式返回，包含以下字段:\n'
            f'{{"reasoning": "分解推理过程", "estimated_complexity": 1-10的数字, '
            f'"subtasks": [{{"description": "子任务描述", "assigned_agent": "agent名称", '
            f'"priority": "low/medium/high", "dependencies": ["依赖的子任务ID列表"]}}]}}\n\n'
            f"注意:\n"
            f"- 子任务ID从subtask_1开始递增\n"
            f"- assigned_agent必须是上面列出的Agent名称之一\n"
            f"- 独立子任务dependencies为空列表\n"
            f"- 只返回JSON，不要附加其他文本"
        )

        try:
            response = await client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=2048,
            )
            raw = response.choices[0].message.content.strip()
            subtasks_data = self._parse_json_response(raw)

            subtasks: list[SubTask] = []
            for idx, st in enumerate(subtasks_data.get("subtasks", []), start=1):
                subtask = SubTask(
                    id=st.get("id", f"subtask_{idx}"),
                    description=st.get("description", ""),
                    assigned_agent=st.get("assigned_agent", ""),
                    priority=TaskPriority(st.get("priority", "medium").lower()),
                    status=SubTaskStatus.PENDING,
                    dependencies=st.get("dependencies", []),
                )
                subtasks.append(subtask)

            decomposition = TaskDecomposition(
                original_task=user_message,
                subtasks=subtasks,
                reasoning=subtasks_data.get("reasoning", ""),
                estimated_complexity=subtasks_data.get("estimated_complexity", 5),
            )

            _logger.info(
                "任务分解完成: %d 个子任务, 复杂度=%d",
                len(subtasks),
                decomposition.estimated_complexity,
            )
            return decomposition

        except Exception as exc:
            _logger.error("任务分解失败: %s", exc, exc_info=True)
            # 降级：返回单个子任务
            return TaskDecomposition(
                original_task=user_message,
                subtasks=[
                    SubTask(id="subtask_1", description=user_message, status=SubTaskStatus.PENDING)
                ],
                reasoning="LLM分解失败，降级为单一任务",
                estimated_complexity=3,
            )

    async def assign_agents(
        self, subtasks: list[SubTask]
    ) -> dict[str, ExpertAgent]:
        """为子任务分配专家Agent

        如果子任务已指定Agent则直接使用，否则基于能力匹配自动分配。

        Args:
            subtasks: 待分配的子任务列表

        Returns:
            子任务ID到专家Agent的映射字典
        """
        assignments: dict[str, ExpertAgent] = {}

        for subtask in subtasks:
            agent = self._match_agent(subtask)
            if agent:
                subtask.assigned_agent = agent.name
                subtask.status = SubTaskStatus.ASSIGNED
                assignments[subtask.id] = agent
                _logger.info(
                    "子任务 '%s' 分配给 Agent '%s'",
                    subtask.id,
                    agent.display_name,
                )
            else:
                _logger.warning(
                    "子任务 '%s' 未找到合适的Agent: %s",
                    subtask.id,
                    subtask.description[:50],
                )

        return assignments

    async def execute_subtask(
        self,
        agent: ExpertAgent,
        subtask: SubTask,
        client: Any,
        model: str = "",
    ) -> SubTaskResult:
        """执行单个子任务

        调用LLM，以专家Agent的身份处理子任务。

        Args:
            agent: 执行任务的专家Agent
            subtask: 待执行的子任务
            client: OpenAI兼容的异步客户端
            model: 使用的模型名称

        Returns:
            SubTaskResult: 子任务执行结果
        """
        start_time = time.monotonic()
        subtask.status = SubTaskStatus.RUNNING

        messages: list[dict[str, str]] = [
            {"role": "system", "content": agent.system_prompt},
            {"role": "user", "content": subtask.description},
        ]
        if subtask.context:
            messages.insert(1, {"role": "system", "content": f"额外上下文: {subtask.context}"})

        last_error = ""
        for attempt in range(1, agent.max_retries + 1):
            try:
                _logger.debug(
                    "执行子任务 '%s' (尝试 %d/%d), Agent='%s'",
                    subtask.id, attempt, agent.max_retries, agent.display_name,
                )

                response = await asyncio.wait_for(
                    client.chat.completions.create(
                        model=model,
                        messages=messages,
                        temperature=0.7,
                        max_tokens=subtask.max_tokens,
                    ),
                    timeout=agent.timeout_seconds,
                )

                content = response.choices[0].message.content or ""
                elapsed = time.monotonic() - start_time
                quality = self._estimate_quality(content)

                token_usage: dict[str, int] = {}
                if hasattr(response, "usage") and response.usage:
                    token_usage = {
                        "prompt_tokens": response.usage.prompt_tokens or 0,
                        "completion_tokens": response.usage.completion_tokens or 0,
                        "total_tokens": response.usage.total_tokens or 0,
                    }

                subtask.status = SubTaskStatus.COMPLETED
                _logger.info(
                    "子任务 '%s' 执行成功, 耗时=%.2fs, 质量=%.2f",
                    subtask.id, elapsed, quality,
                )
                return SubTaskResult(
                    subtask_id=subtask.id,
                    agent_name=agent.name,
                    content=content,
                    success=True,
                    quality_score=quality,
                    execution_time=elapsed,
                    token_usage=token_usage,
                )

            except asyncio.TimeoutError:
                last_error = f"执行超时 ({agent.timeout_seconds}s)"
                _logger.warning(
                    "子任务 '%s' 执行超时 (尝试 %d/%d)",
                    subtask.id, attempt, agent.max_retries,
                )
            except Exception as exc:
                last_error = str(exc)
                _logger.warning(
                    "子任务 '%s' 执行失败 (尝试 %d/%d): %s",
                    subtask.id, attempt, agent.max_retries, exc,
                )

        # 所有重试均失败
        elapsed = time.monotonic() - start_time
        subtask.status = SubTaskStatus.FAILED
        _logger.error("子任务 '%s' 最终执行失败: %s", subtask.id, last_error)
        return SubTaskResult(
            subtask_id=subtask.id,
            agent_name=agent.name,
            success=False,
            quality_score=0.0,
            error_message=last_error,
            execution_time=elapsed,
        )

    async def merge_results(
        self,
        results: list[SubTaskResult],
        original_task: str,
        client: Any | None = None,
        model: str = "",
    ) -> MergeResult:
        """合并多个子任务的执行结果

        先进行争议解决，再调用LLM综合所有结果生成最终输出。

        Args:
            results: 子任务执行结果列表
            original_task: 原始任务描述
            client: OpenAI兼容的异步客户端
            model: 使用的模型名称

        Returns:
            MergeResult: 合并后的结果
        """
        if not results:
            return MergeResult(merged_content="", quality_score=0.0)

        # 争议解决
        resolved = await self.resolve_conflicts(results)

        # 如果只有一个成功结果或没有LLM客户端，直接拼接
        successful = [r for r in resolved if r.success]
        if len(successful) <= 1 or client is None:
            merged = "\n\n".join(
                f"### {r.agent_name} 的输出\n\n{r.content}" for r in successful
            )
            return MergeResult(
                merged_content=merged,
                sources=[r.subtask_id for r in successful],
                conflicts_resolved=len(results) - len(resolved),
                merge_strategy="直接拼接（无LLM或仅单个结果）",
                quality_score=sum(r.quality_score for r in successful) / max(len(successful), 1),
            )

        # 构建合并提示词
        subtask_outputs = "\n".join(
            f"[子任务 {r.subtask_id} - {r.agent_name}]:\n{r.content}" for r in successful
        )
        prompt = (
            f"你是一个结果合并专家。请将以下多个专家Agent的输出结果，"
            f"合并为一个连贯、完整的最终回答。\n\n"
            f"原始任务: {original_task}\n\n"
            f"各专家输出:\n{subtask_outputs}\n\n"
            f"要求:\n"
            f"1. 整合所有有价值的信息，消除冗余\n"
            f"2. 解决不同专家之间的分歧（如有）\n"
            f"3. 保持逻辑清晰、结构完整\n"
            f"4. 用中文回答\n"
            "5. 不要提及「子任务」或「Agent」等内部概念"
        )

        try:
            response = await client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=4096,
            )
            merged_content = response.choices[0].message.content.strip()
            return MergeResult(
                merged_content=merged_content,
                sources=[r.subtask_id for r in successful],
                conflicts_resolved=len(results) - len(resolved),
                merge_strategy="LLM智能合并",
                quality_score=self._estimate_quality(merged_content),
            )
        except Exception as exc:
            _logger.error("LLM合并失败，降级为拼接: %s", exc)
            merged = "\n\n".join(
                f"### {r.agent_name} 的输出\n\n{r.content}" for r in successful
            )
            return MergeResult(
                merged_content=merged,
                sources=[r.subtask_id for r in successful],
                conflicts_resolved=len(results) - len(resolved),
                merge_strategy="拼接降级（LLM合并失败）",
                quality_score=sum(r.quality_score for r in successful) / max(len(successful), 1),
            )

    async def resolve_conflicts(
        self, results: list[SubTaskResult]
    ) -> list[SubTaskResult]:
        """解决多个Agent结果之间的冲突

        基于质量评分和成功状态筛选最佳结果。
        对于明显冲突的结果（质量差异大），保留高质量结果。

        Args:
            results: 待仲裁的子任务结果列表

        Returns:
            筛选后的结果列表
        """
        if len(results) <= 1:
            return results

        # 移除失败的结果
        successful = [r for r in results if r.success]
        if len(successful) <= 1:
            return successful

        # 计算平均质量
        avg_quality = sum(r.quality_score for r in successful) / len(successful)

        # 筛选出质量在可接受范围内的结果
        threshold = max(avg_quality * 0.7, 0.3)
        filtered = [r for r in successful if r.quality_score >= threshold]

        if filtered:
            conflicts_count = len(successful) - len(filtered)
            if conflicts_count > 0:
                _logger.info(
                    "争议解决: %d/%d 个结果被过滤 (阈值=%.2f)",
                    conflicts_count, len(successful), threshold,
                )
            return filtered

        # 所有结果都低于阈值，保留质量最高的
        best = max(successful, key=lambda r: r.quality_score)
        _logger.info(
            "争议解决: 所有结果均低于阈值，保留最高质量结果 (%s, %.2f)",
            best.subtask_id, best.quality_score,
        )
        return [best]

    async def orchestrate(
        self,
        user_message: str,
        context: list[dict] | None = None,
        client: Any | None = None,
        model: str = "",
    ) -> OrchestrationResult:
        """一键编排入口 - 完整的专家Agent协同流程

        执行完整流程: 任务分解 -> Agent分配 -> 并行执行 -> 结果合并

        Args:
            user_message: 用户的原始任务描述
            context: 对话历史上下文
            client: OpenAI兼容的异步客户端
            model: 使用的模型名称

        Returns:
            OrchestrationResult: 完整的编排结果
        """
        start_time = time.monotonic()
        _logger.info("开始编排任务: %s", user_message[:100])

        try:
            self._validate_client_model(client, model, "orchestrate")

            # 步骤1: 任务分解
            decomposition = await self.decompose_task(user_message, client, model)
            subtasks = decomposition.subtasks

            if not subtasks:
                return OrchestrationResult(
                    success=False,
                    error_message="任务分解未产生任何子任务",
                    total_execution_time=time.monotonic() - start_time,
                )

            # 步骤2: Agent分配
            assignments = await self.assign_agents(subtasks)

            # 为子任务注入上下文
            if context:
                context_str = self._format_context(context)
                for st in subtasks:
                    if not st.context:
                        st.context = context_str

            # 步骤3: 并行执行子任务（考虑依赖关系）
            task_results = await self._execute_with_dependencies(
                subtasks, assignments, client, model
            )

            # 步骤4: 合并结果
            merge = await self.merge_results(
                task_results, user_message, client, model
            )

            elapsed = time.monotonic() - start_time
            _logger.info("编排完成: %d 个子任务, 耗时=%.2fs", len(subtasks), elapsed)

            return OrchestrationResult(
                final_output=merge.merged_content,
                subtask_results=task_results,
                task_decomposition=decomposition,
                merge_result=merge,
                total_execution_time=elapsed,
                success=True,
            )

        except Exception as exc:
            elapsed = time.monotonic() - start_time
            _logger.error("编排失败: %s", exc, exc_info=True)
            return OrchestrationResult(
                success=False,
                error_message=f"编排流程异常: {exc}",
                total_execution_time=elapsed,
            )

    def get_available_agents(self) -> list[dict]:
        """获取所有可用的专家Agent列表

        Returns:
            包含Agent信息的字典列表
        """
        return [agent.to_dict() for agent in self.agents.values()]

    # ----------------------------------------------------------
    # 内部方法
    # ----------------------------------------------------------

    @staticmethod
    def _validate_client_model(client: Any | None, model: str, method_name: str) -> None:
        """验证client和model参数"""
        if client is None:
            raise ValueError(f"{method_name}() 需要传入 client 参数（OpenAI兼容的异步客户端）")
        if not model:
            raise ValueError(f"{method_name}() 需要传入 model 参数")

    def _build_agent_descriptions(self) -> str:
        """构建Agent能力描述文本，用于LLM提示词"""
        lines: list[str] = []
        for agent in self.agents.values():
            caps = ", ".join(agent.capabilities) if agent.capabilities else "通用"
            lines.append(
                f"- {agent.name} ({agent.display_name}): "
                f"{agent.description} [能力: {caps}]"
            )
        return "\n".join(lines)

    def _match_agent(self, subtask: SubTask) -> ExpertAgent | None:
        """基于关键词匹配为子任务选择最佳Agent"""
        # 如果子任务已指定Agent，直接查找
        if subtask.assigned_agent and subtask.assigned_agent in self.agents:
            return self.agents[subtask.assigned_agent]

        # 关键词匹配评分
        desc_lower = subtask.description.lower()
        scores: dict[str, int] = {}

        keyword_map: dict[str, list[str]] = {
            "code_expert": [
                "代码", "编程", "开发", "调试", "bug", "函数",
                "重构", "code", "coding", "debug", "program",
                "script", "api", "class", "module",
            ],
            "data_analyst": [
                "数据", "分析", "统计", "可视化", "图表", "data",
                "analysis", "chart", "graph", "pandas", "sql",
                "database", "数据集", "报表",
            ],
            "doc_writer": [
                "文档", "写作", "翻译", "总结", "文档", "doc",
                "write", "document", "translate", "summary",
                "编辑", "润色", "readme",
            ],
            "search_expert": [
                "搜索", "查找", "检索", "信息", "事实", "核查",
                "search", "find", "lookup", "verify",
            ],
            "system_admin": [
                "部署", "运维", "服务器", "docker", "k8s",
                "deploy", "server", "linux", "运维", "配置",
                "nginx", "监控", "告警",
            ],
            "researcher": [
                "研究", "分析", "报告", "调研", "深度", "research",
                "report", "investigate", "论证",
            ],
            "creative": [
                "创意", "头脑风暴", "设计", "创新", "创意",
                "brainstorm", "creative", "design", "innovation",
                "故事", "文案",
            ],
        }

        for agent_name, keywords in keyword_map.items():
            score = sum(1 for kw in keywords if kw in desc_lower)
            if agent_name in self.agents:
                scores[agent_name] = score

        if not scores:
            default_agent = next(iter(self.agents.values()), None)
            if default_agent:
                _logger.debug(
                    "子任务 '%s' 未匹配到关键词，使用默认Agent '%s'",
                    subtask.id, default_agent.name,
                )
            return default_agent

        best_name = max(scores, key=lambda k: scores[k])
        return self.agents[best_name]

    async def _execute_with_dependencies(
        self,
        subtasks: list[SubTask],
        assignments: dict[str, ExpertAgent],
        client: Any,
        model: str,
    ) -> list[SubTaskResult]:
        """考虑依赖关系并行执行子任务"""
        results: list[SubTaskResult] = []
        completed_ids: set[str] = set()
        pending = list(subtasks)
        max_rounds = len(subtasks) + 1

        for _ in range(max_rounds):
            if not pending:
                break

            # 找出所有依赖已满足的子任务
            ready: list[SubTask] = []
            still_pending: list[SubTask] = []
            for st in pending:
                if all(dep in completed_ids for dep in st.dependencies):
                    ready.append(st)
                else:
                    still_pending.append(st)

            if not ready:
                _logger.warning("检测到循环依赖，强制执行剩余 %d 个子任务", len(pending))
                ready = pending
                pending = []
            else:
                pending = still_pending

            coroutines: list[Awaitable[SubTaskResult]] = []
            for st in ready:
                agent = assignments.get(st.id)
                if agent:
                    coroutines.append(self.execute_subtask(agent, st, client, model))
                else:
                    results.append(SubTaskResult(
                        subtask_id=st.id, agent_name="none",
                        content="", success=False, error_message="未分配到专家Agent",
                    ))
                    completed_ids.add(st.id)

            if coroutines:
                semaphore = asyncio.Semaphore(self.max_parallel)

                async def _run_with_limit(coro: Awaitable[SubTaskResult]) -> SubTaskResult:
                    async with semaphore:
                        return await coro

                batch_results = await asyncio.gather(
                    *[_run_with_limit(c) for c in coroutines],
                    return_exceptions=True,
                )

                for result in batch_results:
                    if isinstance(result, Exception):
                        results.append(SubTaskResult(
                            subtask_id="unknown", agent_name="unknown",
                            success=False, error_message=str(result),
                        ))
                    else:
                        results.append(result)
                        completed_ids.add(result.subtask_id)

        return results

    @staticmethod
    def _format_context(context: list[dict]) -> str:
        """将对话上下文格式化为文本"""
        lines: list[str] = []
        for msg in context[-10:]:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if isinstance(content, str) and content:
                if len(content) > 500:
                    content = content[:500] + "..."
                lines.append(f"[{role}]: {content}")
        return "\n".join(lines)

    @staticmethod
    def _estimate_quality(content: str) -> float:
        """估算输出内容的质量评分(0-1)"""
        if not content:
            return 0.0

        score = 0.5

        if len(content) > 50:
            score += 0.1
        if len(content) > 200:
            score += 0.1
        if len(content) > 1000:
            score += 0.05

        structural_markers = ["#", "-", "*", "1.", "2.", "```", "|", "##"]
        marker_count = sum(1 for m in structural_markers if m in content)
        score += min(marker_count * 0.03, 0.15)

        error_indicators = [
            "error", "错误", "失败", "抱歉", "无法", "sorry", "i cannot",
        ]
        error_count = sum(1 for e in error_indicators if e in content.lower())
        score -= min(error_count * 0.1, 0.3)

        return max(0.0, min(1.0, score))

    @staticmethod
    def _parse_json_response(raw: str) -> dict[str, Any]:
        """解析LLM返回的JSON字符串，容错处理"""
        import json

        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass

        try:
            if "```json" in raw:
                start = raw.index("```json") + 7
                end = raw.index("```", start)
                return json.loads(raw[start:end].strip())
            if "```" in raw:
                start = raw.index("```") + 3
                end = raw.index("```", start)
                return json.loads(raw[start:end].strip())
        except (ValueError, json.JSONDecodeError):
            pass

        try:
            start = raw.index("{")
            end = raw.rindex("}") + 1
            return json.loads(raw[start:end])
        except (ValueError, json.JSONDecodeError):
            pass

        raise ValueError(f"无法解析LLM返回的JSON: {raw[:200]}")
