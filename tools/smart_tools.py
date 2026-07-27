"""LUMU 智能工具系统 - 高级工具调度和组合

核心能力:
1. 工具推荐: 根据任务自动推荐最佳工具组合
2. 工具组合: 将多个工具串联成工作流自动执行
3. 工具替代: 某个工具失败时自动选择替代方案
4. 参数补全: 自动补全工具调用所需的参数
5. 执行预览: 执行前预览工具调用计划
6. 结果验证: 验证工具执行结果是否符合预期
7. 并行调度: 并行执行互不依赖的工具调用
8. 工具学习: 学习常用工具使用模式
9. 安全检查: 工具调用前的安全风险评估
10. 缓存优化: 相同参数的工具调用结果缓存

使用示例:
    scheduler = get_smart_tool_scheduler()
    recommendations = await scheduler.recommend_tools(
        task_description="分析这个CSV文件并生成图表",
        available_tools=[{"name": "read_csv", "description": "读取CSV文件", ...}]
    )
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable

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


class RiskLevel(Enum):
    """安全风险等级"""
    SAFE = "safe"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class StepStatus(Enum):
    """工作流步骤状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class ToolRecommendation:
    """工具推荐结果

    Attributes:
        tool_name: 工具名称
        relevance_score: 相关度评分(0-1)
        reason: 推荐理由
        suggested_args: 建议的参数
        execution_order: 建议的执行顺序
    """
    tool_name: str
    relevance_score: float
    reason: str = ""
    suggested_args: dict[str, Any] = field(default_factory=dict)
    execution_order: int = 0


@dataclass
class WorkflowStep:
    """工作流执行步骤

    Attributes:
        step_id: 步骤唯一标识
        tool_name: 工具名称
        args: 工具参数
        depends_on: 依赖的前置步骤ID列表
        status: 步骤状态
        result: 执行结果
        error_message: 错误信息
        retry_count: 已重试次数
        max_retries: 最大重试次数
    """
    step_id: str
    tool_name: str
    args: dict[str, Any] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)
    status: StepStatus = StepStatus.PENDING
    result: str = ""
    error_message: str = ""
    retry_count: int = 0
    max_retries: int = 2


@dataclass
class WorkflowPlan:
    """工作流执行计划

    Attributes:
        plan_id: 计划唯一标识
        name: 计划名称
        description: 计划描述
        steps: 执行步骤列表
        total_steps: 总步骤数
        estimated_duration: 预估耗时（秒）
        created_at: 创建时间
    """
    plan_id: str = ""
    name: str = ""
    description: str = ""
    steps: list[WorkflowStep] = field(default_factory=list)
    total_steps: int = 0
    estimated_duration: float = 0.0
    created_at: str = ""

    def __post_init__(self) -> None:
        self.total_steps = len(self.steps)
        if not self.created_at:
            import datetime
            self.created_at = datetime.datetime.now().isoformat()


@dataclass
class WorkflowResult:
    """工作流执行结果

    Attributes:
        plan_id: 计划ID
        success: 整体是否成功
        completed_steps: 成功完成的步骤数
        total_steps: 总步骤数
        step_results: 各步骤的执行结果
        final_output: 最终输出
        error_message: 错误信息
        execution_time: 总执行耗时（秒）
    """
    plan_id: str = ""
    success: bool = True
    completed_steps: int = 0
    total_steps: int = 0
    step_results: list[dict[str, Any]] = field(default_factory=list)
    final_output: str = ""
    error_message: str = ""
    execution_time: float = 0.0


@dataclass
class ExecutionPreview:
    """执行预览

    Attributes:
        steps_preview: 步骤预览列表
        estimated_duration: 预估耗时
        risk_assessment: 风险评估
        required_permissions: 所需权限列表
        potential_issues: 潜在问题列表
    """
    steps_preview: list[dict[str, Any]] = field(default_factory=list)
    estimated_duration: float = 0.0
    risk_assessment: str = "low"
    required_permissions: list[str] = field(default_factory=list)
    potential_issues: list[str] = field(default_factory=list)


@dataclass
class ValidationResult:
    """结果验证结果

    Attributes:
        tool_name: 工具名称
        is_valid: 结果是否有效
        score: 验证评分(0-1)
        issues: 发现的问题列表
        suggestions: 改进建议
    """
    tool_name: str
    is_valid: bool = True
    score: float = 1.0
    issues: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)


@dataclass
class SecurityCheckResult:
    """安全检查结果

    Attributes:
        tool_name: 工具名称
        risk_level: 风险等级
        risk_factors: 风险因素列表
        blocked: 是否被阻止
        block_reason: 阻止原因
        mitigations: 缓解措施建议
    """
    tool_name: str
    risk_level: RiskLevel = RiskLevel.SAFE
    risk_factors: list[str] = field(default_factory=list)
    blocked: bool = False
    block_reason: str = ""
    mitigations: list[str] = field(default_factory=list)


# ============================================================
# 核心调度器
# ============================================================


class SmartToolScheduler:
    """智能工具调度器

    提供工具推荐、工作流编排、并行执行、安全检查等高级调度能力。
    实际工具执行通过传入的 executor 回调函数完成。

    Attributes:
        cache_enabled: 是否启用结果缓存
        max_cache_size: 最大缓存条目数
        default_timeout: 默认超时时间（秒）
        max_parallel: 最大并行执行数
    """

    _DANGEROUS_PATTERNS: list[str] = [
        r"rm\s+-rf", r"del\s+/[fs]", r"drop\s+table", r"truncate",
        r"shutdown", r"reboot", r"format", r"mkfs", r"dd\s+if=",
        r">\s*/dev/", r"chmod\s+777", r"eval\s*\(", r"exec\s*\(",
        r"__import__", r"os\.system", r"subprocess.*shell=True",
    ]

    _ALTERNATIVE_MAP: dict[str, list[str]] = {
        "read_csv": ["read_file", "parse_data", "load_table"],
        "write_csv": ["write_file", "save_data", "export_table"],
        "web_search": ["search_engine", "lookup", "query_knowledge"],
        "execute_code": ["run_script", "eval_expression", "sandbox_exec"],
        "send_email": ["notify", "webhook", "message_send"],
        "database_query": ["cached_query", "read_cache", "api_query"],
        "file_delete": ["file_archive", "file_move"],
        "shell_exec": ["safe_exec", "sandbox_exec"],
    }

    def __init__(
        self,
        cache_enabled: bool = True,
        max_cache_size: int = 1000,
        default_timeout: float = 60.0,
        max_parallel: int = 5,
    ) -> None:
        """初始化智能工具调度器

        Args:
            cache_enabled: 是否启用结果缓存
            max_cache_size: 最大缓存条目数
            default_timeout: 默认超时时间
            max_parallel: 最大并行执行数
        """
        self.cache_enabled: bool = cache_enabled
        self.max_cache_size: int = max_cache_size
        self.default_timeout: float = default_timeout
        self.max_parallel: int = max(max_parallel, 1)

        # 结果缓存: key -> (result, timestamp)
        self._cache: dict[str, tuple[str, float]] = {}

        # 工具使用统计: tool_name -> use_count
        self._usage_stats: dict[str, int] = {}

        # 工具注册表: tool_name -> tool_info
        self._tool_registry: dict[str, dict[str, Any]] = {}

        _logger.info(
            "SmartToolScheduler 初始化完成 (cache=%s, max_parallel=%d)",
            cache_enabled, max_parallel,
        )

    # ----------------------------------------------------------
    # 公共方法 - 工具推荐
    # ----------------------------------------------------------

    async def recommend_tools(
        self,
        task_description: str,
        available_tools: list[dict[str, Any]],
    ) -> list[ToolRecommendation]:
        """根据任务描述推荐最佳工具组合

        基于关键词匹配和工具描述的相似度进行评分推荐。

        Args:
            task_description: 任务描述文本
            available_tools: 可用工具列表

        Returns:
            按相关度排序的推荐工具列表
        """
        recommendations: list[ToolRecommendation] = []
        task_lower = task_description.lower()
        task_intents = self._extract_intents(task_description)

        for tool in available_tools:
            tool_name = tool.get("name", "")
            tool_desc = tool.get("description", "")
            tool_desc_lower = tool_desc.lower()

            score = self._calculate_relevance(task_lower, tool_desc_lower, task_intents)

            if score > 0.1:
                usage = self._usage_stats.get(tool_name, 0)
                freq_bonus = min(usage * 0.01, 0.05)
                adjusted_score = min(score + freq_bonus, 1.0)

                reason = self._generate_recommendation_reason(tool_name, tool_desc, score)

                recommendations.append(ToolRecommendation(
                    tool_name=tool_name,
                    relevance_score=round(adjusted_score, 3),
                    reason=reason,
                    suggested_args=tool.get("parameters", {}),
                    execution_order=0,
                ))

        recommendations.sort(key=lambda r: r.relevance_score, reverse=True)
        for idx, rec in enumerate(recommendations):
            rec.execution_order = idx + 1

        # 注册工具到注册表
        for tool in available_tools:
            name = tool.get("name", "")
            if name:
                self._tool_registry[name] = tool

        _logger.info(
            "工具推荐完成: 任务='%s', 推荐 %d/%d 个工具",
            task_description[:50], len(recommendations), len(available_tools),
        )
        return recommendations

    # ----------------------------------------------------------
    # 公共方法 - 工作流编排与执行
    # ----------------------------------------------------------

    async def compose_workflow(
        self, steps: list[dict[str, Any]]
    ) -> WorkflowPlan:
        """将多个工具调用步骤组合为工作流

        Args:
            steps: 步骤定义列表

        Returns:
            WorkflowPlan: 工作流执行计划
        """
        workflow_steps: list[WorkflowStep] = []

        for idx, step_def in enumerate(steps):
            tool_name = step_def.get("tool_name", "")
            args = step_def.get("args", {})
            depends_on = step_def.get("depends_on", [])

            valid_deps: list[str] = []
            for dep in depends_on:
                if isinstance(dep, int) and dep < idx:
                    valid_deps.append(f"step_{dep}")
                elif isinstance(dep, str):
                    valid_deps.append(dep)

            workflow_steps.append(WorkflowStep(
                step_id=f"step_{idx}",
                tool_name=tool_name,
                args=args if isinstance(args, dict) else {},
                depends_on=valid_deps,
            ))

        plan = WorkflowPlan(
            plan_id=f"plan_{int(time.time())}_{abs(hash(str(steps))) % 10000:04d}",
            name=f"工作流_{len(steps)}步",
            description=f"包含 {len(steps)} 个工具调用步骤的工作流",
            steps=workflow_steps,
        )

        _logger.info("工作流组合完成: plan_id=%s, %d 个步骤", plan.plan_id, len(workflow_steps))
        return plan

    async def execute_workflow(
        self,
        plan: WorkflowPlan,
        tool_executor: Callable[[str, dict[str, Any]], Awaitable[str]],
    ) -> WorkflowResult:
        """执行工作流

        按照步骤依赖关系，并行执行独立的步骤。

        Args:
            plan: 工作流执行计划
            tool_executor: 工具执行器回调

        Returns:
            WorkflowResult: 工作流执行结果
        """
        start_time = time.monotonic()
        completed_steps: dict[str, str] = {}
        step_results: list[dict[str, Any]] = []

        max_rounds = len(plan.steps) + 1
        _logger.info("开始执行工作流: plan_id=%s, %d 个步骤", plan.plan_id, len(plan.steps))

        for _ in range(max_rounds):
            ready: list[WorkflowStep] = []
            for s in plan.steps:
                if s.status not in (StepStatus.PENDING, StepStatus.FAILED):
                    continue
                if all(dep in completed_steps for dep in s.depends_on):
                    ready.append(s)

            if not ready:
                break

            semaphore = asyncio.Semaphore(self.max_parallel)

            async def _exec_step(ws: WorkflowStep) -> tuple[str, str, bool, str, float]:
                async with semaphore:
                    ws.status = StepStatus.RUNNING
                    step_start = time.monotonic()
                    try:
                        # 安全检查
                        sec = self.security_check(ws.tool_name, ws.args)
                        if sec.blocked:
                            return (ws.step_id, "", False, f"安全检查阻止: {sec.block_reason}", time.monotonic() - step_start)

                        # 缓存检查
                        cached = self.cache_get(ws.tool_name, ws.args)
                        if cached is not None:
                            ws.status = StepStatus.COMPLETED
                            ws.result = cached
                            return (ws.step_id, cached, True, "", time.monotonic() - step_start)

                        resolved_args = self._resolve_step_args(ws.args, completed_steps)
                        result = await asyncio.wait_for(
                            tool_executor(ws.tool_name, resolved_args),
                            timeout=self.default_timeout,
                        )
                        ws.status = StepStatus.COMPLETED
                        ws.result = result
                        self._usage_stats[ws.tool_name] = self._usage_stats.get(ws.tool_name, 0) + 1
                        self.cache_set(ws.tool_name, ws.args, result)
                        return (ws.step_id, result, True, "", time.monotonic() - step_start)
                    except asyncio.TimeoutError:
                        ws.status = StepStatus.FAILED
                        ws.error_message = f"执行超时 ({self.default_timeout}s)"
                        return (ws.step_id, "", False, ws.error_message, time.monotonic() - step_start)
                    except Exception as exc:
                        ws.status = StepStatus.FAILED
                        ws.error_message = str(exc)
                        return (ws.step_id, "", False, str(exc), time.monotonic() - step_start)

            batch_results = await asyncio.gather(
                *[_exec_step(ws) for ws in ready],
                return_exceptions=True,
            )

            for result in batch_results:
                if isinstance(result, Exception):
                    _logger.error("步骤执行异常: %s", result)
                    continue
                step_id, content, success, error, duration = result
                completed_steps[step_id] = content
                step_results.append({
                    "step_id": step_id,
                    "success": success,
                    "content": content,
                    "error": error,
                    "duration": round(duration, 3),
                })

        # 汇总结果
        all_success = all(s.status == StepStatus.COMPLETED for s in plan.steps)
        success_count = sum(1 for s in plan.steps if s.status == StepStatus.COMPLETED)

        final_output = ""
        if plan.steps:
            for s in reversed(plan.steps):
                if s.status == StepStatus.COMPLETED:
                    final_output = s.result
                    break

        elapsed = time.monotonic() - start_time
        _logger.info(
            "工作流执行完成: plan_id=%s, 成功=%d/%d, 耗时=%.2fs",
            plan.plan_id, success_count, len(plan.steps), elapsed,
        )

        return WorkflowResult(
            plan_id=plan.plan_id,
            success=all_success,
            completed_steps=success_count,
            total_steps=len(plan.steps),
            step_results=step_results,
            final_output=final_output,
            execution_time=round(elapsed, 3),
        )

    # ----------------------------------------------------------
    # 公共方法 - 替代方案与参数补全
    # ----------------------------------------------------------

    async def find_alternative(
        self, tool_name: str, reason: str
    ) -> str | None:
        """查找工具的替代方案

        当某个工具不可用或执行失败时，查找功能相似的替代工具。

        Args:
            tool_name: 原工具名称
            reason: 需要替代的原因

        Returns:
            替代工具名称，未找到则返回None
        """
        _logger.info("查找替代工具: tool='%s', reason='%s'", tool_name, reason)

        # 从预定义的替代映射中查找
        alternatives = self._ALTERNATIVE_MAP.get(tool_name, [])
        for alt_name in alternatives:
            if alt_name in self._tool_registry:
                _logger.info("找到替代工具: '%s' -> '%s'", tool_name, alt_name)
                return alt_name

        # 基于名称相似度在注册表中查找
        best_match: str | None = None
        best_score = 0.0
        tool_keywords = self._extract_keywords(tool_name)

        for reg_name in self._tool_registry:
            if reg_name == tool_name:
                continue
            reg_keywords = self._extract_keywords(reg_name)
            score = self._keyword_similarity(tool_keywords, reg_keywords)
            if score > best_score and score > 0.3:
                best_score = score
                best_match = reg_name

        if best_match:
            _logger.info(
                "通过相似度匹配到替代工具: '%s' -> '%s' (score=%.2f)",
                tool_name, best_match, best_score,
            )
        else:
            _logger.warning("未找到工具 '%s' 的替代方案", tool_name)

        return best_match

    async def auto_complete_params(
        self,
        tool_name: str,
        partial_args: dict[str, Any],
        context: str,
    ) -> dict[str, Any]:
        """自动补全工具调用参数

        基于工具注册信息和上下文，自动填充缺失的参数。

        Args:
            tool_name: 工具名称
            partial_args: 已有的部分参数
            context: 当前对话上下文

        Returns:
            补全后的完整参数字典
        """
        completed = dict(partial_args)
        tool_info = self._tool_registry.get(tool_name, {})
        parameters = tool_info.get("parameters", {})

        if isinstance(parameters, dict):
            properties = parameters.get("properties", {})
            required = parameters.get("required", [])

            for param_name, param_def in properties.items():
                if param_name in completed:
                    continue

                inferred = self._infer_param_from_context(param_name, param_def, context)
                if inferred is not None:
                    completed[param_name] = inferred
                    _logger.debug("参数 '%s' 从上下文推断: %s", param_name, inferred)
                    continue

                default = param_def.get("default")
                if default is not None:
                    completed[param_name] = default
                    _logger.debug("参数 '%s' 使用默认值: %s", param_name, default)
                elif param_name in required:
                    _logger.warning("必要参数 '%s' 缺失且无法推断", param_name)

        return completed

    # ----------------------------------------------------------
    # 公共方法 - 预览、验证与安全
    # ----------------------------------------------------------

    async def preview_execution(
        self, steps: list[dict[str, Any]]
    ) -> ExecutionPreview:
        """预览工具调用执行计划

        在实际执行前，展示完整的执行计划、预估耗时和潜在风险。

        Args:
            steps: 步骤定义列表

        Returns:
            ExecutionPreview: 执行预览结果
        """
        steps_preview: list[dict[str, Any]] = []
        risk_factors: list[str] = []
        permissions: set[str] = set()
        issues: list[str] = []

        for idx, step in enumerate(steps):
            tool_name = step.get("tool_name", "")
            args = step.get("args", {})

            sec = self.security_check(tool_name, args)
            if sec.risk_level != RiskLevel.SAFE:
                risk_factors.extend(sec.risk_factors)

            tool_info = self._tool_registry.get(tool_name, {})
            perms = tool_info.get("required_permissions", [])
            permissions.update(perms)

            steps_preview.append({
                "step": idx + 1,
                "tool": tool_name,
                "args_preview": {k: f"<{type(v).__name__}>" for k, v in args.items()},
                "depends_on": step.get("depends_on", []),
                "security": sec.risk_level.value,
                "blocked": sec.blocked,
            })

        estimated = len(steps) * 2.0

        overall_risk = "low"
        if risk_factors:
            overall_risk = "medium"
            if any(f in str(risk_factors) for f in ["delete", "remove", "exec"]):
                overall_risk = "high"

        tool_names = [s.get("tool_name", "") for s in steps]
        duplicates = [name for name in set(tool_names) if tool_names.count(name) > 1]
        if duplicates:
            issues.append(f"重复调用的工具: {', '.join(duplicates)}")

        if any(s.get("depends_on") for s in steps) and len(steps) > 5:
            issues.append("复杂依赖链可能导致较长等待时间")

        return ExecutionPreview(
            steps_preview=steps_preview,
            estimated_duration=estimated,
            risk_assessment=overall_risk,
            required_permissions=list(permissions),
            potential_issues=issues,
        )

    async def validate_result(
        self,
        tool_name: str,
        result: str,
        expected: str = "",
    ) -> ValidationResult:
        """验证工具执行结果

        检查结果是否为空、是否包含错误标记、是否符合预期。

        Args:
            tool_name: 工具名称
            result: 执行结果
            expected: 预期结果描述（可选）

        Returns:
            ValidationResult: 验证结果
        """
        issues_list: list[str] = []
        suggestions: list[str] = []
        score = 1.0

        # 空结果检查
        if not result or not result.strip():
            issues_list.append("工具返回空结果")
            suggestions.append(f"检查工具 '{tool_name}' 的输入参数是否正确")
            return ValidationResult(
                tool_name=tool_name, is_valid=False, score=0.0,
                issues=issues_list, suggestions=suggestions,
            )

        # 错误标记检查
        error_patterns = [
            "error", "exception", "traceback", "错误", "异常", "失败",
            "timeout", "unauthorized", "forbidden", "not found", "404", "500",
        ]
        result_lower = result.lower()
        found_errors = [p for p in error_patterns if p in result_lower]
        if found_errors:
            issues_list.append(f"结果包含错误标记: {', '.join(found_errors[:3])}")
            score -= 0.5
            suggestions.append("结果可能包含错误信息，建议检查并重试")

        # 长度检查
        if len(result) < 5:
            issues_list.append("结果异常短，可能不完整")
            score -= 0.2

        # 预期匹配
        if expected:
            expected_keywords = self._extract_keywords(expected)
            result_keywords = self._extract_keywords(result)
            overlap = len(expected_keywords & result_keywords)
            if overlap == 0 and expected_keywords:
                issues_list.append("结果与预期内容不匹配")
                score -= 0.3
                suggestions.append("结果不符合预期，尝试使用替代工具或调整参数")

        score = max(0.0, min(1.0, score))
        return ValidationResult(
            tool_name=tool_name,
            is_valid=score >= 0.5,
            score=round(score, 3),
            issues=issues_list,
            suggestions=suggestions,
        )

    async def parallel_execute(
        self,
        tool_calls: list[dict[str, Any]],
        executor: Callable[[str, dict[str, Any]], Awaitable[str]],
    ) -> list[dict[str, Any]]:
        """并行执行多个独立的工具调用

        Args:
            tool_calls: 工具调用列表
            executor: 工具执行器回调

        Returns:
            各工具调用的执行结果列表
        """
        if not tool_calls:
            return []

        semaphore = asyncio.Semaphore(self.max_parallel)

        async def _exec_one(call: dict[str, Any]) -> dict[str, Any]:
            tool_name = call.get("tool_name", "")
            args = call.get("args", {})
            call_id = call.get("id", tool_name)

            async with semaphore:
                start = time.monotonic()
                try:
                    cached = self.cache_get(tool_name, args)
                    if cached is not None:
                        return {
                            "id": call_id, "tool_name": tool_name,
                            "success": True, "result": cached,
                            "from_cache": True, "duration": 0.0,
                        }

                    result = await asyncio.wait_for(
                        executor(tool_name, args), timeout=self.default_timeout,
                    )

                    self._usage_stats[tool_name] = self._usage_stats.get(tool_name, 0) + 1
                    self.cache_set(tool_name, args, result)

                    return {
                        "id": call_id, "tool_name": tool_name,
                        "success": True, "result": result,
                        "from_cache": False,
                        "duration": round(time.monotonic() - start, 3),
                    }
                except asyncio.TimeoutError:
                    return {
                        "id": call_id, "tool_name": tool_name,
                        "success": False, "result": "",
                        "error": f"执行超时 ({self.default_timeout}s)",
                        "duration": round(time.monotonic() - start, 3),
                    }
                except Exception as exc:
                    return {
                        "id": call_id, "tool_name": tool_name,
                        "success": False, "result": "", "error": str(exc),
                        "duration": round(time.monotonic() - start, 3),
                    }

        results = await asyncio.gather(
            *[_exec_one(call) for call in tool_calls],
            return_exceptions=True,
        )

        output: list[dict[str, Any]] = []
        for r in results:
            if isinstance(r, Exception):
                output.append({
                    "id": "unknown", "tool_name": "unknown",
                    "success": False, "result": "", "error": str(r), "duration": 0.0,
                })
            else:
                output.append(r)

        success_count = sum(1 for o in output if o.get("success"))
        _logger.info("并行执行完成: %d/%d 成功", success_count, len(tool_calls))
        return output

    # ----------------------------------------------------------
    # 公共方法 - 安全检查与缓存
    # ----------------------------------------------------------

    def security_check(
        self, tool_name: str, args: dict[str, Any]
    ) -> SecurityCheckResult:
        """执行工具调用的安全检查

        检查工具名称和参数中是否包含危险模式。

        Args:
            tool_name: 工具名称
            args: 工具参数

        Returns:
            SecurityCheckResult: 安全检查结果
        """
        risk_factors: list[str] = []
        risk_level = RiskLevel.SAFE
        blocked = False
        block_reason = ""
        mitigations: list[str] = []

        dangerous_tools = {
            "shell_exec": RiskLevel.HIGH,
            "eval_code": RiskLevel.HIGH,
            "file_delete": RiskLevel.MEDIUM,
            "database_write": RiskLevel.MEDIUM,
            "send_email": RiskLevel.LOW,
            "system_command": RiskLevel.CRITICAL,
        }

        if tool_name in dangerous_tools:
            tool_risk = dangerous_tools[tool_name]
            risk_factors.append(f"工具 '{tool_name}' 属于高风险工具")
            if tool_risk.value > risk_level.value:
                risk_level = tool_risk

        # 检查参数中的危险模式
        args_str = json.dumps(args, ensure_ascii=False)
        for pattern in self._DANGEROUS_PATTERNS:
            if re.search(pattern, args_str, re.IGNORECASE):
                risk_factors.append(f"参数中检测到危险模式: {pattern}")
                risk_level = RiskLevel.CRITICAL
                blocked = True
                block_reason = f"参数包含危险模式 '{pattern}'，该操作已被安全策略阻止"
                mitigations.append("如确需执行此操作，请使用更安全的替代方案")
                break

        if risk_level == RiskLevel.CRITICAL and not blocked:
            blocked = True
            block_reason = "风险等级为CRITICAL，操作已阻止"
            mitigations.append("请联系管理员审查此操作后再试")

        if risk_factors:
            _logger.warning(
                "安全检查: tool='%s', risk=%s, blocked=%s, factors=%s",
                tool_name, risk_level.value, blocked, risk_factors,
            )

        return SecurityCheckResult(
            tool_name=tool_name,
            risk_level=risk_level,
            risk_factors=risk_factors,
            blocked=blocked,
            block_reason=block_reason,
            mitigations=mitigations,
        )

    def cache_get(
        self, tool_name: str, args: dict[str, Any]
    ) -> str | None:
        """查询工具调用缓存"""
        if not self.cache_enabled:
            return None

        cache_key = self._make_cache_key(tool_name, args)
        entry = self._cache.get(cache_key)
        if entry is not None:
            result, ts = entry
            if time.monotonic() - ts < 600:
                _logger.debug("缓存命中: tool='%s'", tool_name)
                return result
            else:
                del self._cache[cache_key]
        return None

    def cache_set(
        self, tool_name: str, args: dict[str, Any], result: str,
    ) -> None:
        """存储工具调用结果到缓存"""
        if not self.cache_enabled:
            return

        if len(self._cache) >= self.max_cache_size:
            self._evict_cache()

        cache_key = self._make_cache_key(tool_name, args)
        self._cache[cache_key] = (result, time.monotonic())

    # ----------------------------------------------------------
    # 内部方法
    # ----------------------------------------------------------

    @staticmethod
    def _extract_intents(text: str) -> list[str]:
        """从任务描述中提取关键意图词"""
        common_stopwords = {
            "的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都", "一", "一个", "上", "也",
            "the", "a", "an", "is", "are", "was", "were",
            "be", "to", "of", "and", "in", "that", "it",
            "for", "on", "with", "as", "at", "by",
            "please", "help", "can", "you", "me", "my",
            "请", "帮我", "需要", "想要",
        }
        tokens = re.split(r"[\s,，。.!?！？;；:：、]+", text)
        keywords: list[str] = []
        for token in tokens:
            token = token.strip().lower()
            if token and token not in common_stopwords and len(token) > 1:
                keywords.append(token)
        return keywords

    @staticmethod
    def _calculate_relevance(
        task_text: str, tool_desc: str, task_intents: list[str],
    ) -> float:
        """计算任务和工具的相关度评分(0-1)"""
        score = 0.0
        for intent in task_intents:
            if intent in tool_desc:
                score += 0.2

        tool_words = set(re.findall(r"\w+", tool_desc.lower()))
        task_words = set(re.findall(r"\w+", task_text))
        if tool_words and task_words:
            overlap = len(tool_words & task_words)
            jaccard = overlap / len(tool_words | task_words)
            score += jaccard * 0.5

        return min(score, 1.0)

    @staticmethod
    def _generate_recommendation_reason(
        tool_name: str, tool_desc: str, score: float,
    ) -> str:
        """生成推荐理由"""
        if score >= 0.6:
            return f"'{tool_name}' 与任务高度相关: {tool_desc[:50]}"
        elif score >= 0.3:
            return f"'{tool_name}' 可能对任务有帮助: {tool_desc[:50]}"
        return f"'{tool_name}' 有一定关联性"

    @staticmethod
    def _extract_keywords(text: str) -> set[str]:
        """从文本中提取关键词集合"""
        return set(re.findall(r"\w+", text.lower()))

    @staticmethod
    def _keyword_similarity(keywords_a: set[str], keywords_b: set[str]) -> float:
        """计算两个关键词集合的Jaccard相似度"""
        if not keywords_a and not keywords_b:
            return 0.0
        union = keywords_a | keywords_b
        if not union:
            return 0.0
        intersection = keywords_a & keywords_b
        return len(intersection) / len(union)

    @staticmethod
    def _resolve_step_args(
        args: dict[str, Any], completed_steps: dict[str, str],
    ) -> dict[str, Any]:
        """解析工作流步骤中的参数占位符"""
        resolved: dict[str, Any] = {}
        for key, value in args.items():
            if isinstance(value, str):
                for step_id, result in completed_steps.items():
                    placeholder = f"{{{{{step_id}}}}}"
                    if placeholder in value:
                        value = value.replace(placeholder, result)
                resolved[key] = value
            else:
                resolved[key] = value
        return resolved

    @staticmethod
    def _infer_param_from_context(
        param_name: str, param_def: dict[str, Any], context: str,
    ) -> Any:
        """从上下文中推断参数值"""
        desc = param_def.get("description", "").lower()
        param_type = param_def.get("type", "string")

        if param_type == "string" and "path" in (param_name + desc):
            path_patterns = re.findall(r"[\w\-./]+\.\w+", context)
            if path_patterns:
                return path_patterns[0]

        if param_type in ("integer", "number"):
            numbers = re.findall(r"\d+", context)
            if numbers:
                val = int(numbers[0])
                return val if param_type == "integer" else float(numbers[0])

        return None

    def _make_cache_key(self, tool_name: str, args: dict[str, Any]) -> str:
        """生成缓存键"""
        raw = f"{tool_name}:{json.dumps(args, sort_keys=True, default=str)}"
        return hashlib.md5(raw.encode()).hexdigest()

    def _evict_cache(self) -> None:
        """缓存淘汰：移除最旧的缓存条目"""
        if not self._cache:
            return
        evict_count = max(1, len(self._cache) // 5)
        sorted_entries = sorted(self._cache.items(), key=lambda x: x[1][1])
        for key, _ in sorted_entries[:evict_count]:
            del self._cache[key]
        _logger.debug("缓存淘汰: 移除 %d 条旧缓存", evict_count)


# ============================================================
# 单例工厂
# ============================================================

_scheduler_instance: SmartToolScheduler | None = None


def get_smart_tool_scheduler(
    cache_enabled: bool = True,
    max_cache_size: int = 1000,
    default_timeout: float = 60.0,
    max_parallel: int = 5,
) -> SmartToolScheduler:
    """获取智能工具调度器的单例实例

    Args:
        cache_enabled: 是否启用缓存（仅首次调用生效）
        max_cache_size: 最大缓存大小（仅首次调用生效）
        default_timeout: 默认超时时间（仅首次调用生效）
        max_parallel: 最大并行数（仅首次调用生效）

    Returns:
        SmartToolScheduler: 调度器单例
    """
    global _scheduler_instance
    if _scheduler_instance is None:
        _scheduler_instance = SmartToolScheduler(
            cache_enabled=cache_enabled,
            max_cache_size=max_cache_size,
            default_timeout=default_timeout,
            max_parallel=max_parallel,
        )
        _logger.info("创建 SmartToolScheduler 单例实例")
    return _scheduler_instance
