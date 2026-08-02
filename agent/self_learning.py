"""LUMU 自主学习与进化系统

核心能力:
1. 经验学习: 从成功/失败的交互中提取经验教训
2. 策略优化: 根据历史表现优化推理策略选择
3. 错误模式识别: 识别重复犯错模式并自动修复
4. 用户偏好学习: 学习并适应用户的偏好和习惯
5. 知识自建: 自动构建和更新知识库
6. 性能自优化: 监控自身性能并自我调优
7. 元认知: 对自身认知过程进行反思和改进
8. 技能获取: 从实践中提取可复用的技能模板

使用示例:
    engine = get_self_learning_engine()
    engine.record_outcome(interaction_record)
    lessons = engine.extract_lesson(interaction_record)
    report = engine.get_learning_report()
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any
import os
import sqlite3

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


class OutcomeType(Enum):
    """交互结果类型"""
    SUCCESS = "success"
    PARTIAL_SUCCESS = "partial_success"
    FAILURE = "failure"
    REJECTED = "rejected"


class TaskCategory(Enum):
    """任务分类"""
    CODING = "coding"
    ANALYSIS = "analysis"
    WRITING = "writing"
    RESEARCH = "research"
    GENERAL = "general"
    DEBUGGING = "debugging"
    DESIGN = "design"


@dataclass
class InteractionRecord:
    """交互记录

    Attributes:
        id: 记录唯一标识
        timestamp: 交互时间戳
        user_message: 用户输入
        agent_response: Agent响应
        task_type: 任务类型
        strategy_used: 使用的策略名称
        outcome: 交互结果
        duration_seconds: 响应耗时
        user_feedback: 用户反馈（可选）
        tools_used: 使用的工具列表
        token_usage: token使用量
        context_tags: 上下文标签
    """
    id: str = ""
    timestamp: str = ""
    user_message: str = ""
    agent_response: str = ""
    task_type: str = TaskCategory.GENERAL.value
    strategy_used: str = ""
    outcome: str = OutcomeType.SUCCESS.value
    duration_seconds: float = 0.0
    user_feedback: str = ""
    tools_used: list[str] = field(default_factory=list)
    token_usage: dict[str, int] = field(default_factory=dict)
    context_tags: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        """自动生成ID和时间戳"""
        if not self.id:
            raw = f"{self.user_message}{time.time()}"
            self.id = hashlib.md5(raw.encode()).hexdigest()[:12]
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()


@dataclass
class Lesson:
    """经验教训

    Attributes:
        id: 教训唯一标识
        created_at: 创建时间
        source_interaction_id: 来源交互记录ID
        task_type: 关联的任务类型
        lesson_type: 教训类型 (positive_experience / negative_experience / insight)
        description: 教训描述
        actionable_rule: 可执行的规则
        confidence: 置信度(0-1)
        application_count: 应用次数
        success_count: 成功次数
    """
    id: str = ""
    created_at: str = ""
    source_interaction_id: str = ""
    task_type: str = ""
    lesson_type: str = "insight"
    description: str = ""
    actionable_rule: str = ""
    confidence: float = 0.5
    application_count: int = 0
    success_count: int = 0

    def __post_init__(self) -> None:
        if not self.id:
            self.id = hashlib.md5(
                f"{self.description}{time.time()}".encode()
            ).hexdigest()[:12]
        if not self.created_at:
            self.created_at = datetime.now().isoformat()


@dataclass
class StrategyEvaluation:
    """策略评估结果

    Attributes:
        strategy_name: 策略名称
        task_type: 关联任务类型
        total_uses: 总使用次数
        success_count: 成功次数
        failure_count: 失败次数
        avg_duration: 平均耗时
        avg_score: 平均评分
        trend: 趋势 (improving / stable / declining)
        recommendation: 建议 (continue / optimize / replace / avoid)
    """
    strategy_name: str = ""
    task_type: str = ""
    total_uses: int = 0
    success_count: int = 0
    failure_count: int = 0
    avg_duration: float = 0.0
    avg_score: float = 0.0
    trend: str = "stable"
    recommendation: str = "continue"


@dataclass
class StrategyAdjustment:
    """策略调整建议

    Attributes:
        strategy_name: 策略名称
        adjustment_type: 调整类型 (boost / reduce / replace / add)
        reason: 调整原因
        new_weight: 建议的新权重
        details: 详细说明
    """
    strategy_name: str = ""
    adjustment_type: str = "boost"
    reason: str = ""
    new_weight: float = 0.5
    details: str = ""


@dataclass
class ErrorPattern:
    """错误模式

    Attributes:
        id: 模式唯一标识
        detected_at: 检测时间
        pattern_type: 模式类型
        description: 模式描述
        frequency: 出现频率
        affected_tasks: 受影响的任务类型列表
        suggested_fix: 建议修复方案
        last_occurrence: 最近一次出现时间
    """
    id: str = ""
    detected_at: str = ""
    pattern_type: str = ""
    description: str = ""
    frequency: int = 0
    affected_tasks: list[str] = field(default_factory=list)
    suggested_fix: str = ""
    last_occurrence: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            self.id = hashlib.md5(
                f"{self.pattern_type}{time.time()}".encode()
            ).hexdigest()[:12]
        if not self.detected_at:
            self.detected_at = datetime.now().isoformat()
        if not self.last_occurrence:
            self.last_occurrence = self.detected_at


@dataclass
class Preference:
    """用户偏好

    Attributes:
        id: 偏好唯一标识
        learned_at: 学习时间
        category: 偏好类别
        preference_key: 偏好键名
        preference_value: 偏好值
        confidence: 置信度(0-1)
        source_count: 来源交互数量
    """
    id: str = ""
    learned_at: str = ""
    category: str = ""
    preference_key: str = ""
    preference_value: str = ""
    confidence: float = 0.5
    source_count: int = 0

    def __post_init__(self) -> None:
        if not self.id:
            self.id = hashlib.md5(
                f"{self.category}{self.preference_key}{time.time()}".encode()
            ).hexdigest()[:12]
        if not self.learned_at:
            self.learned_at = datetime.now().isoformat()


@dataclass
class ReflectionResult:
    """元认知反思结果

    Attributes:
        reflected_at: 反思时间
        overall_performance: 整体性能评分(0-1)
        strengths: 识别到的优势列表
        weaknesses: 识别到的劣势列表
        improvement_areas: 改进领域列表
        key_insights: 关键洞察列表
        next_actions: 下一步行动建议
    """
    reflected_at: str = ""
    overall_performance: float = 0.5
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    improvement_areas: list[str] = field(default_factory=list)
    key_insights: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.reflected_at:
            self.reflected_at = datetime.now().isoformat()


# ============================================================
# 数据持久化工具
# ============================================================


class _DataStore:
    """轻量级JSON文件数据存储

    用于在 data/learning/ 目录下持久化学习数据。
    """

    def __init__(self, base_dir: str = "data/learning") -> None:
        self._base_dir = Path(base_dir)
        self._cache: dict[str, list[dict[str, Any]]] = {}
        self._ensure_dir()

    def _ensure_dir(self) -> None:
        """确保数据目录存在"""
        try:
            self._base_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            _logger.warning(
                "无法创建数据目录 '%s': %s，学习数据将仅保存在内存中",
                self._base_dir, exc,
            )

    def _file_path(self, collection: str) -> Path:
        """获取集合对应的文件路径"""
        return self._base_dir / f"{collection}.json"

    async def load(self, collection: str) -> list[dict[str, Any]]:
        """从文件加载数据集合

        Args:
            collection: 集合名称

        Returns:
            数据记录列表
        """
        if collection in self._cache:
            return self._cache[collection]

        path = self._file_path(collection)
        if not path.exists():
            self._cache[collection] = []
            return []

        try:
            content = path.read_text(encoding="utf-8")
            data = json.loads(content)
            if isinstance(data, list):
                self._cache[collection] = data
                return data
            _logger.warning(
                "集合 '%s' 数据格式异常，期望list，实际为 %s",
                collection, type(data).__name__,
            )
            return []
        except (json.JSONDecodeError, OSError) as exc:
            _logger.warning("加载集合 '%s' 失败: %s", collection, exc)
            return []

    async def save(self, collection: str, data: list[dict[str, Any]]) -> None:
        """保存数据集合到文件

        Args:
            collection: 集合名称
            data: 数据记录列表
        """
        self._cache[collection] = data
        path = self._file_path(collection)
        try:
            path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            _logger.error("保存集合 '%s' 失败: %s", collection, exc)

    async def append(self, collection: str, record: dict[str, Any]) -> None:
        """追加单条记录到集合"""
        data = await self.load(collection)
        data.append(record)
        await self.save(collection, data)


# ============================================================
# 核心学习引擎
# ============================================================


class SelfLearningEngine:
    """自主学习与进化引擎

    通过记录交互结果、提取经验教训、优化策略配置，实现Agent的持续进化。
    学习数据持久化到 data/learning/ 目录下的JSON文件。

    Attributes:
        data_dir: 数据存储根目录
    """

    _COL_INTERACTIONS = "interactions"
    _COL_LESSONS = "lessons"
    _COL_STRATEGIES = "strategy_scores"
    _COL_PREFERENCES = "preferences"

    def __init__(self, data_dir: str = "data/learning") -> None:
        """初始化学习引擎

        Args:
            data_dir: 学习数据存储目录
        """
        self._store = _DataStore(base_dir=data_dir)
        self._initialized: bool = False
        _logger.info("SelfLearningEngine 初始化，数据目录: %s", data_dir)

    async def _ensure_initialized(self) -> None:
        """延迟初始化，确保数据集合已加载"""
        if not self._initialized:
            await self._store.load(self._COL_INTERACTIONS)
            await self._store.load(self._COL_LESSONS)
            await self._store.load(self._COL_STRATEGIES)
            await self._store.load(self._COL_PREFERENCES)
            self._initialized = True

    # ----------------------------------------------------------
    # 公共方法 - 交互记录与经验提取
    # ----------------------------------------------------------

    async def record_outcome(self, interaction: InteractionRecord) -> None:
        """记录交互结果

        将交互记录持久化存储，用于后续的经验提取和策略优化。

        Args:
            interaction: 交互记录对象
        """
        await self._ensure_initialized()

        record = asdict(interaction)
        await self._store.append(self._COL_INTERACTIONS, record)

        _logger.info(
            "记录交互结果: id=%s, task=%s, outcome=%s, strategy=%s",
            interaction.id, interaction.task_type,
            interaction.outcome, interaction.strategy_used,
        )

        # 如果有用户反馈，同时更新经验教训的应用统计
        if interaction.user_feedback:
            await self._update_lesson_stats(interaction)
            try:
                await self.learn_preference(interaction)
            except Exception as _pe:
                _logger.warning("learn_preference auto-call failed: %s", _pe)

    # ----------------------------------------------------------
    # P1-1: 将自学成果落库, 使知识球体随对话生长
    # ----------------------------------------------------------
    def _persist_init(self) -> None:
        """确保 lessons.db 有 source_id 列与唯一索引 (幂等)。"""
        home = Path(os.getenv("AGENT_HOME", str(Path(__file__).resolve().parent.parent)))
        lp = home / "data" / "lessons.db"
        mp = home / "data" / "memory.db"
        with sqlite3.connect(lp) as c:
            cur = c.execute("PRAGMA table_info(lessons)").fetchall()
            if not any(r[1] == "source_id" for r in cur):
                c.execute("ALTER TABLE lessons ADD COLUMN source_id TEXT")
            c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_lessons_source ON lessons(source_id)")
        with sqlite3.connect(mp) as c:
            c.execute("CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(key, content)")

    def _persist_lesson(self, lesson) -> None:
        try:
            self._persist_init()
            home = Path(os.getenv("AGENT_HOME", str(Path(__file__).resolve().parent.parent)))
            lp = home / "data" / "lessons.db"
            with sqlite3.connect(lp) as c:
                c.execute(
                    """INSERT INTO lessons (timestamp, interaction_id, title, lesson_type, description, context, action, score, keywords, source_id)
                       VALUES (?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(source_id) DO UPDATE SET
                         timestamp=excluded.timestamp, title=excluded.title, lesson_type=excluded.lesson_type,
                         description=excluded.description, context=excluded.context, action=excluded.action,
                         score=excluded.score, keywords=excluded.keywords""",
                    (
                        lesson.created_at or datetime.now().isoformat(),
                        lesson.source_interaction_id,
                        (lesson.description or lesson.actionable_rule or "(经验)")[:200],
                        lesson.lesson_type,
                        lesson.description,
                        lesson.task_type,
                        lesson.actionable_rule,
                        float(lesson.confidence or 0.5),
                        lesson.task_type,
                        lesson.id,
                    ),
                )
            _logger.info("self-learning lesson 落库: %s", lesson.id)
        except Exception as e:
            _logger.warning("persist_lesson failed: %s", e)

    def _persist_preference(self, pref) -> None:
        try:
            home = Path(os.getenv("AGENT_HOME", str(Path(__file__).resolve().parent.parent)))
            mp = home / "data" / "memory.db"
            key = f"sl_pref:{pref.id}"
            content = f"[{pref.category}] {pref.preference_key}={pref.preference_value} (置信度 {pref.confidence:.2f})"
            with sqlite3.connect(mp) as c:
                c.execute(
                    """INSERT INTO memories (key, content, category)
                       VALUES (?,?,?)
                       ON CONFLICT(key) DO UPDATE SET content=excluded.content, updated_at=datetime('now')""",
                    (key, content, "preference"),
                )
                c.execute("DELETE FROM memories_fts WHERE key=?", (key,))
                c.execute("INSERT INTO memories_fts (key, content) VALUES (?, ?)", (key, content))
            _logger.info("self-learning preference 落库: %s", pref.id)
        except Exception as e:
            _logger.warning("persist_preference failed: %s", e)

    async def extract_lesson(
        self, interaction: InteractionRecord
    ) -> Lesson | None:
        """从交互记录中提取经验教训

        基于交互结果和上下文，自动判断是否有可学习的经验。
        成功交互提取正面经验，失败交互提取反面教训。

        Args:
            interaction: 交互记录对象

        Returns:
            提取到的经验教训，无价值时返回None
        """
        await self._ensure_initialized()

        if interaction.outcome == OutcomeType.SUCCESS.value:
            lesson = self._extract_positive_lesson(interaction)
        elif interaction.outcome == OutcomeType.FAILURE.value:
            lesson = self._extract_negative_lesson(interaction)
        elif interaction.outcome == OutcomeType.PARTIAL_SUCCESS.value:
            lesson = self._extract_partial_lesson(interaction)
        else:
            return None

        if lesson is None:
            return None

        # 检查是否已有类似的教训（避免重复）
        existing = await self._store.load(self._COL_LESSONS)
        for existing_lesson in existing:
            if (
                existing_lesson.get("task_type") == lesson.task_type
                and existing_lesson.get("actionable_rule") == lesson.actionable_rule
            ):
                existing_lesson["confidence"] = min(
                    existing_lesson.get("confidence", 0.5) + 0.1, 1.0
                )
                existing_lesson["application_count"] = (
                    existing_lesson.get("application_count", 0) + 1
                )
                await self._store.save(self._COL_LESSONS, existing)
                self._persist_lesson(lesson)
                _logger.debug("更新已有经验教训: %s", lesson.id)
                return lesson

        await self._store.append(self._COL_LESSONS, asdict(lesson))
        self._persist_lesson(lesson)
        _logger.info(
            "提取新经验教训: type=%s, task=%s, confidence=%.2f",
            lesson.lesson_type, lesson.task_type, lesson.confidence,
        )
        return lesson

    async def evaluate_strategy(
        self, strategy: str, task_type: str, outcome: str
    ) -> StrategyEvaluation:
        """评估策略在特定任务类型上的效果

        基于历史数据统计策略的成功率、平均耗时等指标。

        Args:
            strategy: 策略名称
            task_type: 任务类型
            outcome: 当前交互结果（用于实时更新）

        Returns:
            StrategyEvaluation: 策略评估结果
        """
        await self._ensure_initialized()

        interactions = await self._store.load(self._COL_INTERACTIONS)
        relevant = [
            i for i in interactions
            if i.get("strategy_used") == strategy and i.get("task_type") == task_type
        ]

        total = len(relevant)
        if total == 0:
            return StrategyEvaluation(
                strategy_name=strategy, task_type=task_type,
                recommendation="insufficient_data",
            )

        success = sum(
            1 for i in relevant
            if i.get("outcome") in (
                OutcomeType.SUCCESS.value, OutcomeType.PARTIAL_SUCCESS.value,
            )
        )
        failure = total - success
        avg_duration = sum(i.get("duration_seconds", 0) for i in relevant) / total
        avg_score = success / total

        trend = self._calculate_trend(relevant)
        recommendation = self._generate_recommendation(avg_score, total, trend)

        return StrategyEvaluation(
            strategy_name=strategy,
            task_type=task_type,
            total_uses=total,
            success_count=success,
            failure_count=failure,
            avg_duration=round(avg_duration, 2),
            avg_score=round(avg_score, 3),
            trend=trend,
            recommendation=recommendation,
        )

    async def optimize_strategies(self) -> list[StrategyAdjustment]:
        """优化策略配置

        分析所有策略的历史表现，生成调整建议。
        基于加权评分：成功率(权重0.5) + 速度(权重0.2) + 一致性(权重0.3)。

        Returns:
            策略调整建议列表
        """
        await self._ensure_initialized()

        interactions = await self._store.load(self._COL_INTERACTIONS)
        if not interactions:
            return []

        # 按策略分组
        strategy_groups: dict[str, list[dict]] = {}
        for i in interactions:
            s = i.get("strategy_used", "default")
            strategy_groups.setdefault(s, []).append(i)

        adjustments: list[StrategyAdjustment] = []

        for strategy_name, records in strategy_groups.items():
            if len(records) < 3:
                continue

            # 计算加权评分
            success_rate = sum(
                1 for r in records
                if r.get("outcome") in (
                    OutcomeType.SUCCESS.value, OutcomeType.PARTIAL_SUCCESS.value,
                )
            ) / len(records)

            avg_duration = sum(
                r.get("duration_seconds", 0) for r in records
            ) / len(records)
            speed_score = max(0.0, min(1.0, 1.0 - avg_duration / 60.0))

            consistency = 1.0 - abs(success_rate - 0.5) * 2
            consistency = max(0.0, min(1.0, consistency))

            weighted_score = success_rate * 0.5 + speed_score * 0.2 + consistency * 0.3

            if weighted_score >= 0.7:
                adjustment = StrategyAdjustment(
                    strategy_name=strategy_name,
                    adjustment_type="boost",
                    reason=f"策略表现优秀 (加权评分={weighted_score:.2f}, 成功率={success_rate:.2f})",
                    new_weight=min(weighted_score, 1.0),
                    details="建议增加该策略的使用权重",
                )
            elif weighted_score >= 0.4:
                adjustment = StrategyAdjustment(
                    strategy_name=strategy_name,
                    adjustment_type="continue",
                    reason=f"策略表现一般 (加权评分={weighted_score:.2f})",
                    new_weight=weighted_score,
                    details="维持当前使用策略",
                )
            else:
                adjustment = StrategyAdjustment(
                    strategy_name=strategy_name,
                    adjustment_type="reduce",
                    reason=f"策略表现不佳 (加权评分={weighted_score:.2f}, 成功率={success_rate:.2f})",
                    new_weight=max(weighted_score, 0.1),
                    details="建议减少该策略的使用频率",
                )

            adjustments.append(adjustment)

        _logger.info("策略优化完成，生成 %d 条调整建议", len(adjustments))
        return adjustments

    async def detect_error_patterns(self) -> list[ErrorPattern]:
        """检测错误模式

        分析失败交互的共性，识别重复出现的错误模式。

        Returns:
            检测到的错误模式列表
        """
        await self._ensure_initialized()

        interactions = await self._store.load(self._COL_INTERACTIONS)
        failures = [
            i for i in interactions
            if i.get("outcome") == OutcomeType.FAILURE.value
        ]

        if not failures:
            return []

        # 按任务类型分组
        by_task: dict[str, list[dict]] = {}
        for f in failures:
            task = f.get("task_type", TaskCategory.GENERAL.value)
            by_task.setdefault(task, []).append(f)

        # 按策略分组
        by_strategy: dict[str, list[dict]] = {}
        for f in failures:
            strategy = f.get("strategy_used", "default")
            by_strategy.setdefault(strategy, []).append(f)

        patterns: list[ErrorPattern] = []

        for task_type, records in by_task.items():
            if len(records) >= 2:
                patterns.append(ErrorPattern(
                    pattern_type="task_failure_cluster",
                    description=f"任务类型 '{task_type}' 频繁失败 ({len(records)} 次)",
                    frequency=len(records),
                    affected_tasks=[task_type],
                    suggested_fix=f"建议优化 '{task_type}' 类任务的处理策略或增加额外验证步骤",
                    last_occurrence=records[-1].get("timestamp", ""),
                ))

        for strategy_name, records in by_strategy.items():
            if len(records) >= 3:
                patterns.append(ErrorPattern(
                    pattern_type="strategy_failure_cluster",
                    description=f"策略 '{strategy_name}' 在多种任务中频繁失败 ({len(records)} 次)",
                    frequency=len(records),
                    affected_tasks=list({r.get("task_type", "") for r in records}),
                    suggested_fix=f"建议审查并修改策略 '{strategy_name}' 的配置或替换为其他策略",
                    last_occurrence=records[-1].get("timestamp", ""),
                ))

        _logger.info("错误模式检测完成，发现 %d 个模式", len(patterns))
        return patterns

    async def learn_preference(
        self, interaction: InteractionRecord
    ) -> Preference | None:
        """从交互记录中学习用户偏好

        基于用户反馈和交互模式推断用户偏好。

        Args:
            interaction: 交互记录对象

        Returns:
            学习到的用户偏好，无法推断时返回None
        """
        await self._ensure_initialized()

        feedback = interaction.user_feedback.strip().lower()
        if not feedback:
            return None

        preference: Preference | None = None

        # 长度偏好
        if any(kw in feedback for kw in ["太长", "太啰嗦", "简洁", "简短", "少一点", "too long"]):
            preference = Preference(
                category="response_style", preference_key="verbosity",
                preference_value="concise", confidence=0.7, source_count=1,
            )
        elif any(kw in feedback for kw in ["详细", "多一点", "展开", "具体", "more detail"]):
            preference = Preference(
                category="response_style", preference_key="verbosity",
                preference_value="detailed", confidence=0.7, source_count=1,
            )
        # 语言偏好
        elif any(kw in feedback for kw in ["英文", "english", "用英文"]):
            preference = Preference(
                category="language", preference_key="response_language",
                preference_value="english", confidence=0.8, source_count=1,
            )
        elif any(kw in feedback for kw in ["中文", "chinese", "用中文"]):
            preference = Preference(
                category="language", preference_key="response_language",
                preference_value="chinese", confidence=0.8, source_count=1,
            )

        if preference is None:
            return None

        # 检查是否已有相同偏好，更新置信度
        existing = await self._store.load(self._COL_PREFERENCES)
        for pref in existing:
            if (
                pref.get("preference_key") == preference.preference_key
                and pref.get("preference_value") == preference.preference_value
            ):
                new_confidence = min(pref.get("confidence", 0.5) + 0.15, 1.0)
                new_count = pref.get("source_count", 0) + 1
                pref["confidence"] = new_confidence
                pref["source_count"] = new_count
                pref["learned_at"] = datetime.now().isoformat()
                await self._store.save(self._COL_PREFERENCES, existing)
                _logger.info(
                    "更新用户偏好: key=%s, value=%s, confidence=%.2f",
                    preference.preference_key, preference.preference_value, new_confidence,
                )
                return Preference(**pref)

        await self._store.append(self._COL_PREFERENCES, asdict(preference))
        self._persist_preference(preference)
        _logger.info(
            "学习到新用户偏好: key=%s, value=%s",
            preference.preference_key, preference.preference_value,
        )
        return preference

    async def meta_cognitive_reflection(self) -> ReflectionResult:
        """元认知反思

        综合分析所有学习数据，对自身认知过程进行反思，
        识别优势和劣势，提出改进方向。

        Returns:
            ReflectionResult: 反思结果
        """
        await self._ensure_initialized()

        interactions = await self._store.load(self._COL_INTERACTIONS)
        lessons = await self._store.load(self._COL_LESSONS)
        preferences = await self._store.load(self._COL_PREFERENCES)

        # 整体性能评估
        total = len(interactions)
        successes = sum(
            1 for i in interactions
            if i.get("outcome") in (
                OutcomeType.SUCCESS.value, OutcomeType.PARTIAL_SUCCESS.value,
            )
        )
        overall = successes / max(total, 1)

        # 按任务类型分析
        task_performance: dict[str, list[dict]] = {}
        for i in interactions:
            task = i.get("task_type", TaskCategory.GENERAL.value)
            task_performance.setdefault(task, []).append(i)

        strengths: list[str] = []
        weaknesses: list[str] = []
        improvement_areas: list[str] = []

        for task_type, records in task_performance.items():
            task_success = sum(
                1 for r in records
                if r.get("outcome") in (
                    OutcomeType.SUCCESS.value, OutcomeType.PARTIAL_SUCCESS.value,
                )
            ) / max(len(records), 1)
            if task_success >= 0.8:
                strengths.append(
                    f"任务类型 '{task_type}' 表现优秀 (成功率 {task_success:.0%})"
                )
            elif task_success < 0.5:
                weaknesses.append(
                    f"任务类型 '{task_type}' 表现不佳 (成功率 {task_success:.0%})"
                )
                improvement_areas.append(f"提升 '{task_type}' 类任务的处理能力")

        # 基于经验教训的洞察
        key_insights: list[str] = []
        positive_lessons = [l for l in lessons if l.get("lesson_type") == "positive_experience"]
        negative_lessons = [l for l in lessons if l.get("lesson_type") == "negative_experience"]

        if positive_lessons:
            top_positive = max(positive_lessons, key=lambda x: x.get("confidence", 0))
            key_insights.append(
                f"最有效的经验: {top_positive.get('description', '')[:80]}"
            )
        if negative_lessons:
            top_negative = max(negative_lessons, key=lambda x: x.get("frequency", 0))
            key_insights.append(
                f"最需改进的教训: {top_negative.get('description', '')[:80]}"
            )
        if not key_insights:
            key_insights.append("交互数据尚不足以产生深刻洞察，继续积累经验")

        # 下一步行动建议
        next_actions: list[str] = []
        if total < 20:
            next_actions.append("积累更多交互数据（当前仅 %d 条）" % total)
        if weaknesses:
            next_actions.append(
                "重点改进表现不佳的任务类型: " + ", ".join(w[:20] for w in weaknesses)
            )
        if not preferences:
            next_actions.append("主动学习和适应用户偏好")
        next_actions.append("持续优化策略配置")

        result = ReflectionResult(
            overall_performance=round(overall, 3),
            strengths=strengths[:5],
            weaknesses=weaknesses[:5],
            improvement_areas=improvement_areas[:5],
            key_insights=key_insights[:5],
            next_actions=next_actions[:5],
        )

        _logger.info(
            "元认知反思完成: 整体性能=%.2f, 优势=%d, 劣势=%d",
            overall, len(strengths), len(weaknesses),
        )
        return result

    async def get_learning_report(self) -> dict[str, Any]:
        """生成学习报告

        Returns:
            包含完整学习状态数据的字典
        """
        await self._ensure_initialized()

        interactions = await self._store.load(self._COL_INTERACTIONS)
        lessons = await self._store.load(self._COL_LESSONS)
        preferences = await self._store.load(self._COL_PREFERENCES)

        total = len(interactions)
        successes = sum(
            1 for i in interactions
            if i.get("outcome") in (
                OutcomeType.SUCCESS.value, OutcomeType.PARTIAL_SUCCESS.value,
            )
        )

        return {
            "summary": {
                "total_interactions": total,
                "success_rate": round(successes / max(total, 1), 3),
                "total_lessons": len(lessons),
                "total_preferences": len(preferences),
            },
            "recent_interactions": interactions[-10:],
            "lessons": lessons[-10:],
            "preferences": preferences,
        }

    async def get_stats(self) -> dict[str, Any]:
        """获取统计信息

        Returns:
            包含关键统计指标的字典
        """
        await self._ensure_initialized()

        interactions = await self._store.load(self._COL_INTERACTIONS)
        lessons = await self._store.load(self._COL_LESSONS)
        preferences = await self._store.load(self._COL_PREFERENCES)

        total = len(interactions)
        successes = sum(
            1 for i in interactions
            if i.get("outcome") in (
                OutcomeType.SUCCESS.value, OutcomeType.PARTIAL_SUCCESS.value,
            )
        )
        avg_duration = (
            sum(i.get("duration_seconds", 0) for i in interactions) / max(total, 1)
        )

        strategy_counts: dict[str, int] = {}
        for i in interactions:
            s = i.get("strategy_used", "default")
            strategy_counts[s] = strategy_counts.get(s, 0) + 1

        task_counts: dict[str, int] = {}
        for i in interactions:
            t = i.get("task_type", TaskCategory.GENERAL.value)
            task_counts[t] = task_counts.get(t, 0) + 1

        return {
            "total_interactions": total,
            "success_rate": round(successes / max(total, 1), 3),
            "avg_duration_seconds": round(avg_duration, 2),
            "total_lessons": len(lessons),
            "total_preferences": len(preferences),
            "strategy_distribution": strategy_counts,
            "task_type_distribution": task_counts,
        }

    # ----------------------------------------------------------
    # 内部方法
    # ----------------------------------------------------------

    def _extract_positive_lesson(self, interaction: InteractionRecord) -> Lesson | None:
        """从成功交互中提取正面经验"""
        if not interaction.strategy_used:
            return None
        return Lesson(
            source_interaction_id=interaction.id,
            task_type=interaction.task_type,
            lesson_type="positive_experience",
            description=f"策略 '{interaction.strategy_used}' 在 '{interaction.task_type}' 任务中表现良好",
            actionable_rule=f"当任务类型为 '{interaction.task_type}' 时，优先使用 '{interaction.strategy_used}' 策略",
            confidence=0.6,
        )

    def _extract_negative_lesson(self, interaction: InteractionRecord) -> Lesson | None:
        """从失败交互中提取反面教训"""
        if not interaction.strategy_used:
            return None
        return Lesson(
            source_interaction_id=interaction.id,
            task_type=interaction.task_type,
            lesson_type="negative_experience",
            description=f"策略 '{interaction.strategy_used}' 在 '{interaction.task_type}' 任务中失败",
            actionable_rule=f"当任务类型为 '{interaction.task_type}' 时，避免使用 '{interaction.strategy_used}' 策略，考虑替代方案",
            confidence=0.6,
        )

    def _extract_partial_lesson(self, interaction: InteractionRecord) -> Lesson | None:
        """从部分成功的交互中提取改进经验"""
        if not interaction.strategy_used:
            return None
        return Lesson(
            source_interaction_id=interaction.id,
            task_type=interaction.task_type,
            lesson_type="insight",
            description=f"策略 '{interaction.strategy_used}' 在 '{interaction.task_type}' 任务中部分成功，可能需要辅助措施",
            actionable_rule=f"使用 '{interaction.strategy_used}' 处理 '{interaction.task_type}' 任务时，增加结果验证和补充步骤",
            confidence=0.4,
        )

    async def _update_lesson_stats(self, interaction: InteractionRecord) -> None:
        """根据用户反馈更新经验教训的应用统计"""
        if interaction.outcome not in (
            OutcomeType.SUCCESS.value, OutcomeType.PARTIAL_SUCCESS.value,
        ):
            return
        lessons = await self._store.load(self._COL_LESSONS)
        updated = False
        for lesson in lessons:
            if lesson.get("task_type") == interaction.task_type:
                lesson["application_count"] = lesson.get("application_count", 0) + 1
                if interaction.outcome == OutcomeType.SUCCESS.value:
                    lesson["success_count"] = lesson.get("success_count", 0) + 1
                updated = True
        if updated:
            await self._store.save(self._COL_LESSONS, lessons)

    @staticmethod
    def _calculate_trend(records: list[dict[str, Any]]) -> str:
        """计算策略效果趋势"""
        if len(records) < 4:
            return "stable"
        mid = len(records) // 2
        first_half = records[:mid]
        second_half = records[mid:]

        first_rate = sum(
            1 for r in first_half
            if r.get("outcome") in (
                OutcomeType.SUCCESS.value, OutcomeType.PARTIAL_SUCCESS.value,
            )
        ) / max(len(first_half), 1)
        second_rate = sum(
            1 for r in second_half
            if r.get("outcome") in (
                OutcomeType.SUCCESS.value, OutcomeType.PARTIAL_SUCCESS.value,
            )
        ) / max(len(second_half), 1)

        diff = second_rate - first_rate
        if diff > 0.1:
            return "improving"
        elif diff < -0.1:
            return "declining"
        return "stable"

    @staticmethod
    def _generate_recommendation(avg_score: float, total: int, trend: str) -> str:
        """根据策略评估指标生成建议"""
        if total < 3:
            return "insufficient_data"
        if avg_score >= 0.8 and trend == "improving":
            return "continue"
        elif avg_score >= 0.8 and trend == "declining":
            return "optimize"
        elif avg_score < 0.4:
            return "replace"
        elif avg_score < 0.6:
            return "optimize"
        return "continue"


# ============================================================
# 单例工厂
# ============================================================

_engine_instance: SelfLearningEngine | None = None


def get_self_learning_engine(data_dir: str = "data/learning") -> SelfLearningEngine:
    """获取自主学习引擎的单例实例

    Args:
        data_dir: 学习数据存储目录（仅首次调用生效）

    Returns:
        SelfLearningEngine: 学习引擎单例
    """
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = SelfLearningEngine(data_dir=data_dir)
        _logger.info("创建 SelfLearningEngine 单例实例")
    return _engine_instance
