"""LUMU 智能记忆系统 - 多层记忆架构

记忆层次:
1. 工作记忆 (Working Memory): 当前对话上下文的即时信息
2. 情景记忆 (Episodic Memory): 具体事件和交互的记录
3. 语义记忆 (Semantic Memory): 抽象知识和概念
4. 程序记忆 (Procedural Memory): 学到的技能和操作模式
5. 长期记忆 (Long-term Memory): 持久化的重要信息

核心能力:
- 记忆巩固: 短期 -> 长期记忆自动转化
- 遗忘曲线: 基于艾宾浩斯曲线的记忆衰减
- 语义检索: 关键词+语义相似度的混合检索
- 记忆关联: 自动建立记忆之间的关联图谱
- 情感标记: 给记忆附加情感权重影响检索
- 重要性评分: 自动评估记忆重要性决定是否长期保存
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import re
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

# --- 安全导入：确保模块缺失不会导致崩溃 ---
try:
    from core.logging_config import get_logger
    logger = get_logger(__name__)
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

try:
    import jieba
    HAS_JIEBA = True
except ImportError:
    HAS_JIEBA = False
    logger.warning("jieba 未安装，中文分词将使用简单的字符级分割")


# --- 真向量嵌入（替换原 TF-IDF 相似度，让记忆按"语义"而非"字面"召回）---
# 与知识库共用同一向量空间（knowledge.embedding -> fastembed bge-small-zh-v1.5）。
try:
    from memory.embeddings import embed as _mem_embed, cosine as _mem_cosine
    _HAS_REAL_EMBED = True
except Exception:  # 兜底：理论上不会触发（knowledge.embedding 自带哈希兜底）
    _HAS_REAL_EMBED = False
    import hashlib as _hl, math as _hm
    def _mem_embed(text: str) -> list[float]:
        vec = [0.0] * 128
        for n in (2, 3):
            for i in range(len(text) - n + 1):
                h = int(_hl.md5(text[i:i + n].encode()).hexdigest(), 16)
                vec[h % 128] += ((h >> 8) % 1000 - 500) / 500.0
        nm = _hm.sqrt(sum(v * v for v in vec))
        return [v / nm for v in vec] if nm > 0 else vec
    def _mem_cosine(a, b) -> float:
        n = min(len(a), len(b))
        return sum(a[i] * b[i] for i in range(n))


# 轻量嵌入缓存（同文本结果确定，避免每次召回重复计算）
_EMBED_CACHE: dict[str, list[float]] = {}
_EMBED_CACHE_MAX = 5000


def _embed_cached(text: str) -> list[float]:
    """Embed text with a small in-memory cache (deterministic per text)."""
    _key = text[:4000]
    _v = _EMBED_CACHE.get(_key)
    if _v is None:
        _v = _mem_embed(_key)
        if len(_EMBED_CACHE) < _EMBED_CACHE_MAX:
            _EMBED_CACHE[_key] = _v
    return _v


# ============================================================================
# 数据模型
# ============================================================================


class MemoryType(str, Enum):
    """记忆类型枚举"""
    WORKING = "working"        # 工作记忆：当前对话的即时信息
    EPISODIC = "episodic"      # 情景记忆：具体事件和交互记录
    SEMANTIC = "semantic"      # 语义记忆：抽象知识和概念
    PROCEDURAL = "procedural"  # 程序记忆：学到的技能和操作模式
    LONG_TERM = "long_term"    # 长期记忆：持久化的重要信息


class EmotionLabel(str, Enum):
    """情感标签枚举"""
    POSITIVE = "positive"      # 积极
    NEGATIVE = "negative"      # 消极
    NEUTRAL = "neutral"        # 中性
    IMPORTANT = "important"    # 重要标记
    EMOTIONAL = "emotional"    # 强情感


@dataclass
class MemoryEntry:
    """记忆条目数据结构

    Attributes:
        id: 唯一标识符
        content: 记忆内容文本
        memory_type: 记忆类型
        importance: 重要性评分 0.0-1.0
        emotion: 情感标签
        associations: 关联的其他记忆 ID 列表
        created_at: 创建时间 (ISO 8601)
        accessed_at: 最后访问时间 (ISO 8601)
        access_count: 访问次数
        metadata: 额外元数据（session_id, source, tags 等）
        session_id: 所属会话 ID
        keywords: 从内容中提取的关键词
        decay_factor: 衰减因子（基于艾宾浩斯遗忘曲线）
    """
    id: str = ""
    content: str = ""
    memory_type: str = MemoryType.WORKING.value
    importance: float = 0.5
    emotion: str = EmotionLabel.NEUTRAL.value
    associations: list[str] = field(default_factory=list)
    created_at: str = ""
    accessed_at: str = ""
    access_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    session_id: str = ""
    keywords: list[str] = field(default_factory=list)
    decay_factor: float = 1.0

    def __post_init__(self) -> None:
        """初始化后处理：自动生成 ID 和时间戳"""
        if not self.id:
            self.id = str(uuid.uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()
        if not self.accessed_at:
            self.accessed_at = self.created_at

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MemoryEntry:
        """从字典反序列化"""
        return cls(**data)

    def touch(self) -> None:
        """更新访问时间和计数"""
        self.accessed_at = datetime.now(timezone.utc).isoformat()
        self.access_count += 1


@dataclass
class RecallResult:
    """记忆召回结果

    Attributes:
        entries: 召回的记忆条目列表
        query: 原始查询文本
        total_scanned: 总扫描条目数
        elapsed_ms: 检索耗时（毫秒）
    """
    entries: list[MemoryEntry] = field(default_factory=list)
    query: str = ""
    total_scanned: int = 0
    elapsed_ms: float = 0.0


# ============================================================================
# TF-IDF 向量化器（不依赖外部向量库）
# ============================================================================


class SimpleTfidfVectorizer:
    """简易 TF-IDF 向量化器

    使用纯 Python 实现 TF-IDF 计算和余弦相似度，
    不依赖 numpy、scikit-learn 等外部库。
    支持中英文分词（优先使用 jieba，退化为字符/单词切分）。
    """

    # 英文停用词
    EN_STOP_WORDS: set[str] = {
        "a", "an", "the", "is", "are", "was", "were", "be", "been",
        "being", "have", "has", "had", "do", "does", "did", "will",
        "would", "shall", "should", "may", "might", "must", "can",
        "could", "of", "in", "on", "at", "to", "for", "with", "by",
        "from", "as", "into", "through", "during", "before", "after",
        "above", "below", "between", "out", "off", "over", "under",
        "and", "but", "or", "nor", "not", "so", "yet", "both",
        "either", "neither", "each", "every", "all", "any", "few",
        "more", "most", "other", "some", "such", "no", "only",
        "own", "same", "than", "too", "very", "just", "because",
        "if", "when", "where", "how", "what", "which", "who", "whom",
    }

    # 中文停用词
    ZH_STOP_WORDS: set[str] = {
        "的", "了", "在", "是", "我", "有", "和", "就", "不", "人",
        "都", "一", "一个", "上", "也", "很", "到", "说", "要", "去",
        "你", "会", "着", "没有", "看", "好", "自己", "这", "他", "她",
        "吗", "这个", "那个", "什么", "怎么", "为什么", "可以", "能",
        "把", "被", "让", "给", "对", "从", "跟", "与", "比",
    }

    def __init__(self) -> None:
        """初始化向量化器"""
        self._document_frequencies: dict[str, int] = {}
        self._total_documents: int = 0
        self._tokenized_cache: dict[str, list[str]] = {}

    def tokenize(self, text: str) -> list[str]:
        """对文本进行分词

        优先使用 jieba 进行中文分词，
        退化为基于正则的简单分词。

        Args:
            text: 输入文本

        Returns:
            分词结果列表（已去停用词）
        """
        # 检查缓存
        cache_key = text[:200]  # 缓存键截断，避免内存问题
        if cache_key in self._tokenized_cache:
            return self._tokenized_cache[cache_key]

        tokens: list[str] = []

        if HAS_JIEBA:
            # 使用 jieba 分词
            raw_tokens = list(jieba.cut(text))
            tokens = [
                t.strip().lower()
                for t in raw_tokens
                if t.strip()
                and len(t.strip()) > 1
                and t.strip() not in self.ZH_STOP_WORDS
                and t.strip() not in self.EN_STOP_WORDS
            ]
        else:
            # 简单分词：英文按空格，中文按字符
            # 提取英文单词
            en_words = re.findall(r"[a-zA-Z]{2,}", text)
            # 提取中文字符序列（每2-4个字为一组）
            zh_chars = re.findall(r"[\u4e00-\u9fff]+", text)
            zh_groups: list[str] = []
            for seq in zh_chars:
                # 2-gram 和 3-gram
                for n in (2, 3):
                    for i in range(len(seq) - n + 1):
                        zh_groups.append(seq[i : i + n])
                # 也保留单字
                zh_groups.extend(list(seq))

            tokens = [
                w.lower()
                for w in en_words + zh_groups
                if w
                and len(w) > 1
                and w not in self.EN_STOP_WORDS
                and w not in self.ZH_STOP_WORDS
            ]

        self._tokenized_cache[cache_key] = tokens
        return tokens

    def fit(self, documents: list[str]) -> None:
        """根据文档集合计算 IDF 值

        Args:
            documents: 文档文本列表
        """
        self._document_frequencies.clear()
        self._total_documents = len(documents)

        for doc in documents:
            tokens = set(self.tokenize(doc))
            for token in tokens:
                self._document_frequencies[token] = (
                    self._document_frequencies.get(token, 0) + 1
                )

    def transform(self, text: str) -> dict[str, float]:
        """将文本转换为 TF-IDF 向量（字典形式）

        Args:
            text: 输入文本

        Returns:
            {token: tfidf_score} 字典
        """
        tokens = self.tokenize(text)
        if not tokens:
            return {}

        # 计算 TF
        token_counts = Counter(tokens)
        total_tokens = len(tokens)
        tf_scores: dict[str, float] = {}
        for token, count in token_counts.items():
            tf_scores[token] = count / total_tokens if total_tokens > 0 else 0

        # 计算 TF-IDF
        tfidf_scores: dict[str, float] = {}
        for token, tf in tf_scores.items():
            df = self._document_frequencies.get(token, 0)
            idf = math.log(
                (self._total_documents + 1) / (df + 1) + 1
            ) if self._total_documents > 0 else 1.0
            tfidf_scores[token] = tf * idf

        return tfidf_scores

    @staticmethod
    def cosine_similarity(vec_a: dict[str, float], vec_b: dict[str, float]) -> float:
        """计算两个 TF-IDF 向量的余弦相似度

        Args:
            vec_a: 向量 A（字典形式）
            vec_b: 向量 B（字典形式）

        Returns:
            0.0-1.0 的相似度值
        """
        if not vec_a or not vec_b:
            return 0.0

        # 获取共同维度
        common_keys = set(vec_a.keys()) & set(vec_b.keys())
        if not common_keys:
            return 0.0

        # 点积
        dot_product = sum(vec_a[k] * vec_b[k] for k in common_keys)

        # 模长
        norm_a = math.sqrt(sum(v ** 2 for v in vec_a.values()))
        norm_b = math.sqrt(sum(v ** 2 for v in vec_b.values()))

        if norm_a == 0 or norm_b == 0:
            return 0.0

        return dot_product / (norm_a * norm_b)

    def clear_cache(self) -> None:
        """清理分词缓存"""
        self._tokenized_cache.clear()


# ============================================================================
# 艾宾浩斯遗忘曲线
# ============================================================================


class EbbinghausDecay:
    """艾宾浩斯遗忘曲线实现

    基于经典遗忘曲线公式:
    R = e^(-t/S)

    其中:
    - R: 记忆保持率
    - t: 距离上次复习的时间
    - S: 记忆稳定性（随复习次数增长）
    """

    @staticmethod
    def calculate_retention(
        hours_since_access: float,
        review_count: int = 0,
        base_stability: float = 1.0,
    ) -> float:
        """计算记忆保持率

        Args:
            hours_since_access: 距离上次访问的小时数
            review_count: 复习/访问次数
            base_stability: 基础稳定性系数

        Returns:
            0.0-1.0 的记忆保持率
        """
        if hours_since_access <= 0:
            return 1.0

        # 稳定性随复习次数增长（指数增长但有上限）
        stability = base_stability * (1 + review_count) ** 1.5

        # 应用遗忘曲线
        retention = math.exp(-hours_since_access / (stability * 24))

        return max(0.0, min(1.0, retention))

    @staticmethod
    def should_consolidate(
        retention: float,
        importance: float = 0.5,
        threshold: float = 0.3,
    ) -> bool:
        """判断记忆是否需要巩固

        Args:
            retention: 当前记忆保持率
            importance: 记忆重要性
            threshold: 巩固阈值

        Returns:
            True 表示建议巩固
        """
        # 重要的记忆即使保持率较高也应优先巩固
        adjusted_threshold = threshold - (importance - 0.5) * 0.2
        adjusted_threshold = max(0.1, min(0.8, adjusted_threshold))
        return retention < adjusted_threshold


# ============================================================================
# 智能记忆系统核心
# ============================================================================


class IntelligentMemory:
    """LUMU 智能记忆系统

    实现多层记忆架构，提供记忆的存储、检索、巩固和遗忘管理。
    使用 JSON 文件进行持久化存储，不依赖外部数据库。

    Usage:
        memory = get_intelligent_memory()
        await memory.initialize()
        await memory.store_working(MemoryEntry(content="用户询问了Python列表操作"))
        results = await memory.recall("Python 列表")
    """

    # 记忆存储文件名
    _MEMORY_FILES: dict[str, str] = {
        MemoryType.WORKING.value: "working_memory.json",
        MemoryType.EPISODIC.value: "episodic_memory.json",
        MemoryType.SEMANTIC.value: "semantic_memory.json",
        MemoryType.PROCEDURAL.value: "procedural_memory.json",
        MemoryType.LONG_TERM.value: "long_term_memory.json",
    }

    # 各类型记忆的最大条目数
    _MAX_ENTRIES: dict[str, int] = {
        MemoryType.WORKING.value: 500,
        MemoryType.EPISODIC.value: 2000,
        MemoryType.SEMANTIC.value: 1000,
        MemoryType.PROCEDURAL.value: 500,
        MemoryType.LONG_TERM.value: 5000,
    }

    # 重要性评分关键词权重
    _IMPORTANCE_KEYWORDS: dict[str, float] = {
        # 高重要性
        "重要": 0.9, "关键": 0.9, "核心": 0.85, "务必": 0.85,
        "记住": 0.8, "必须": 0.85, "一定": 0.75,
        "important": 0.9, "critical": 0.9, "key": 0.85,
        "must": 0.85, "remember": 0.8, "essential": 0.85,
        # 中等重要性
        "注意": 0.65, "需要": 0.6, "建议": 0.55,
        "note": 0.65, "need": 0.6, "suggest": 0.55,
        # 低重要性
        "随便": 0.2, "无所谓": 0.2,
        "casual": 0.2, "whatever": 0.2,
    }

    def __init__(self, data_dir: str = "data/memory") -> None:
        """初始化智能记忆系统

        Args:
            data_dir: 记忆数据存储目录（相对于项目根目录）
        """
        self._data_dir: str = data_dir
        self._initialized: bool = False
        self._init_lock: Optional[asyncio.Lock] = None

        # 内存中的记忆存储（按类型分组）
        self._memories: dict[str, list[MemoryEntry]] = {
            mem_type.value: [] for mem_type in MemoryType
        }

        # TF-IDF 向量化器（仅保留用于关键词提取/重叠计算）
        self._vectorizer = SimpleTfidfVectorizer()

        # 真向量嵌入缓存（避免每次召回重复计算）
        self._emb_cache: dict[str, list[float]] = {}

        # 关联图谱（记忆 ID -> 关联记忆 ID 列表）
        self._association_graph: dict[str, set[str]] = {}

        # 统计信息
        self._stats: dict[str, Any] = {
            "total_stored": 0,
            "total_recalled": 0,
            "total_consolidated": 0,
            "total_forgotten": 0,
            "total_associations": 0,
        }

    async def initialize(self) -> None:
        """初始化记忆系统：加载数据目录中已有的记忆"""
        if self._initialized:
            return
        if self._init_lock is None:
            self._init_lock = asyncio.Lock()

        async with self._init_lock:
            if self._initialized:
                return

            try:
                logger.info(f"正在初始化记忆系统，数据目录: {self._data_dir}")

                # 确保数据目录存在
                os.makedirs(self._data_dir, exist_ok=True)

                # 加载各类型记忆
                for mem_type, filename in self._MEMORY_FILES.items():
                    await self._load_memory_file(mem_type, filename)

                # 重建关联图谱
                self._rebuild_association_graph()

                # 重建 TF-IDF 索引
                self._rebuild_tfidf_index()

                self._initialized = True
                total = sum(len(entries) for entries in self._memories.values())
                logger.info(f"记忆系统初始化完成，共加载 {total} 条记忆")
            except Exception as e:
                logger.error(f"记忆系统初始化失败: {e}", exc_info=True)
                raise

    # ----------------------------------------------------------------
    # 存储接口
    # ----------------------------------------------------------------

    async def store_working(self, entry: MemoryEntry) -> str:
        """存储工作记忆

        工作记忆用于保存当前对话的即时信息。
        自动评估重要性并提取关键词。

        Args:
            entry: 记忆条目

        Returns:
            记忆条目 ID
        """
        return await self._store_entry(entry, MemoryType.WORKING)

    async def store_episodic(self, entry: MemoryEntry) -> str:
        """存储情景记忆

        情景记忆保存具体的事件和交互记录。

        Args:
            entry: 记忆条目

        Returns:
            记忆条目 ID
        """
        return await self._store_entry(entry, MemoryType.EPISODIC)

    async def store_semantic(self, entry: MemoryEntry) -> str:
        """存储语义记忆

        语义记忆保存抽象知识和概念。

        Args:
            entry: 记忆条目

        Returns:
            记忆条目 ID
        """
        return await self._store_entry(entry, MemoryType.SEMANTIC)

    async def store_procedural(self, entry: MemoryEntry) -> str:
        """存储程序记忆

        程序记忆保存学到的技能和操作模式。

        Args:
            entry: 记忆条目

        Returns:
            记忆条目 ID
        """
        return await self._store_entry(entry, MemoryType.PROCEDURAL)

    async def _store_entry(
        self, entry: MemoryEntry, mem_type: MemoryType
    ) -> str:
        """通用记忆存储方法

        Args:
            entry: 记忆条目
            mem_type: 记忆类型

        Returns:
            记忆条目 ID
        """
        await self.initialize()

        # 确保条目有正确的类型
        entry.memory_type = mem_type.value

        # 自动评估重要性（如果未手动指定）
        if entry.importance <= 0 or entry.importance >= 1.0:
            entry.importance = self._assess_importance(entry.content)

        # 自动提取关键词
        if not entry.keywords:
            entry.keywords = self._extract_keywords(entry.content)

        # 计算衰减因子（初始为1.0）
        entry.decay_factor = 1.0

        # 存储到内存
        entries = self._memories[mem_type.value]

        # 检查容量限制
        max_count = self._MAX_ENTRIES.get(mem_type.value, 1000)
        if len(entries) >= max_count:
            # 按重要性排序，淘汰最低价值的
            entries.sort(key=lambda e: e.importance, reverse=True)
            evicted = entries.pop()
            logger.debug(f"记忆容量满，淘汰低价值记忆: {evicted.id}")

        entries.append(entry)

        # 建立关联
        await self.build_associations(entry)

        # 更新统计
        self._stats["total_stored"] += 1

        # 异步持久化（不阻塞）
        asyncio.create_task(self._persist_memory(mem_type.value))

        logger.debug(
            f"记忆已存储: id={entry.id}, type={mem_type.value}, "
            f"importance={entry.importance:.2f}"
        )
        return entry.id

    # ----------------------------------------------------------------
    # 检索接口
    # ----------------------------------------------------------------

    async def recall(
        self,
        query: str,
        top_k: int = 10,
        memory_types: Optional[list[str]] = None,
    ) -> list[MemoryEntry]:
        """智能召回记忆

        使用 TF-IDF 语义相似度 + 关键词匹配的混合检索策略。

        Args:
            query: 查询文本
            top_k: 返回的最大条目数
            memory_types: 限制搜索的记忆类型（None 表示搜索全部）

        Returns:
            按相关度排序的记忆条目列表
        """
        await self.initialize()

        start_time = time.monotonic()

        if not query or not query.strip():
            return []

        # 确定搜索范围
        target_types = memory_types or [mt.value for mt in MemoryType]

        # 收集候选记忆
        candidates: list[MemoryEntry] = []
        for mem_type in target_types:
            candidates.extend(self._memories.get(mem_type, []))

        if not candidates:
            return []

        # 计算查询的真向量嵌入
        query_emb = _embed_cached(query)

        # 计算每条记忆的相似度
        scored_entries: list[tuple[float, MemoryEntry]] = []
        for entry in candidates:
            if not entry.keywords and entry.content:
                # 延迟提取关键词
                entry.keywords = self._extract_keywords(entry.content)

            # 构建记忆文本并计算真向量语义相似度
            entry_text = " ".join(entry.keywords) + " " + entry.content
            similarity = _mem_cosine(query_emb, _embed_cached(entry_text))

            # 精确关键词匹配加分
            query_tokens = set(self._vectorizer.tokenize(query))
            entry_tokens = set(entry.keywords)
            keyword_overlap = len(query_tokens & entry_tokens)
            keyword_bonus = min(keyword_overlap * 0.1, 0.3)

            # 记忆保持率加权（衰减的记忆降低权重）
            retention = self._calculate_entry_retention(entry)
            retention_weight = 0.3 + 0.7 * retention

            # 综合评分
            final_score = (similarity + keyword_bonus) * retention_weight

            # 重要性加权
            final_score *= (0.5 + 0.5 * entry.importance)

            scored_entries.append((final_score, entry))

        # 按评分排序
        scored_entries.sort(key=lambda x: x[0], reverse=True)

        # 取 top_k 结果
        results = [entry for _, entry in scored_entries[:top_k]]

        # 更新访问记录
        for entry in results:
            entry.touch()

        elapsed_ms = (time.monotonic() - start_time) * 1000
        self._stats["total_recalled"] += len(results)

        logger.debug(
            f"记忆召回完成: query='{query[:50]}', "
            f"candidates={len(candidates)}, results={len(results)}, "
            f"elapsed={elapsed_ms:.1f}ms"
        )

        return results

    async def search_semantic(
        self, query: str, top_k: int = 5
    ) -> list[MemoryEntry]:
        """纯语义搜索

        仅使用 TF-IDF 语义相似度进行搜索。

        Args:
            query: 查询文本
            top_k: 返回的最大条目数

        Returns:
            按语义相似度排序的记忆条目列表
        """
        await self.initialize()

        if not query or not query.strip():
            return []

        query_emb = _embed_cached(query)

        # 搜索所有类型
        all_entries: list[MemoryEntry] = []
        for entries in self._memories.values():
            all_entries.extend(entries)

        scored: list[tuple[float, MemoryEntry]] = []
        for entry in all_entries:
            entry_text = " ".join(entry.keywords) + " " + entry.content
            similarity = _mem_cosine(query_emb, _embed_cached(entry_text))
            scored.append((similarity, entry))

        scored.sort(key=lambda x: x[0], reverse=True)
        results = [entry for _, entry in scored[:top_k] if _ > 0.05]

        for entry in results:
            entry.touch()

        return results

    # ----------------------------------------------------------------
    # 记忆巩固
    # ----------------------------------------------------------------

    async def consolidate(self, session_id: str) -> dict[str, Any]:
        """对话结束时执行记忆巩固

        将工作记忆中重要的条目转化为长期记忆，
        根据遗忘曲线更新所有记忆的衰减因子。

        Args:
            session_id: 要巩固的会话 ID

        Returns:
            巩固操作统计
        """
        await self.initialize()

        stats = {
            "session_id": session_id,
            "working_to_episodic": 0,
            "episodic_to_semantic": 0,
            "promoted_to_long_term": 0,
            "forgotten": 0,
            "associations_built": 0,
        }

        # 1. 将工作记忆中高重要性的条目转化为情景记忆
        working_entries = list(self._memories[MemoryType.WORKING.value])
        entries_to_promote: list[MemoryEntry] = []

        for entry in working_entries:
            if entry.session_id != session_id:
                continue

            # 高重要性的工作记忆提升为情景记忆
            if entry.importance >= 0.6:
                promoted = MemoryEntry(
                    content=entry.content,
                    memory_type=MemoryType.EPISODIC.value,
                    importance=entry.importance,
                    emotion=entry.emotion,
                    metadata={
                        **entry.metadata,
                        "consolidated_from": "working",
                        "original_id": entry.id,
                    },
                    session_id=session_id,
                )
                entries_to_promote.append(promoted)
                stats["working_to_episodic"] += 1

                # 非常重要的直接提升为长期记忆
                if entry.importance >= 0.8:
                    long_term_entry = MemoryEntry(
                        content=entry.content,
                        memory_type=MemoryType.LONG_TERM.value,
                        importance=entry.importance,
                        emotion=entry.emotion,
                        metadata={
                            **entry.metadata,
                            "consolidated_from": "working",
                            "original_id": entry.id,
                        },
                        session_id=session_id,
                    )
                    entries_to_promote.append(long_term_entry)
                    stats["promoted_to_long_term"] += 1

        # 执行提升
        for entry in entries_to_promote:
            await self._store_entry(
                entry,
                MemoryType(entry.memory_type),
            )

        # 2. 更新遗忘曲线
        await self._update_decay_factors()

        # 3. 清理过期的工作记忆
        await self._cleanup_working_memory(session_id)

        # 4. 更新统计
        self._stats["total_consolidated"] += (
            stats["working_to_episodic"] + stats["promoted_to_long_term"]
        )

        logger.info(f"记忆巩固完成: session={session_id}, stats={stats}")
        return stats

    async def forget_unimportant(self) -> int:
        """基于遗忘曲线清理低价值记忆

        清除保持率低于阈值且重要性低的记忆。

        Returns:
            清理的记忆条目数
        """
        await self.initialize()

        forgotten_count = 0

        for mem_type_value, entries in self._memories.items():
            # 工作记忆不应用遗忘（由 consolidate 管理）
            if mem_type_value == MemoryType.WORKING.value:
                continue

            to_keep: list[MemoryEntry] = []
            for entry in entries:
                retention = self._calculate_entry_retention(entry)
                should_keep = EbbinghausDecay.should_consolidate(
                    retention=retention,
                    importance=entry.importance,
                )

                # 反转逻辑：should_consolidate=True 意味着需要关注
                # 如果保持率太低且重要性也低，则遗忘
                if retention < 0.05 and entry.importance < 0.3:
                    # 从关联图谱中移除
                    self._remove_from_associations(entry.id)
                    forgotten_count += 1
                    logger.debug(f"遗忘记忆: id={entry.id}, type={mem_type_value}")
                else:
                    to_keep.append(entry)

            self._memories[mem_type_value] = to_keep

            # 持久化变更
            if forgotten_count > 0:
                asyncio.create_task(
                    self._persist_memory(mem_type_value)
                )

        self._stats["total_forgotten"] += forgotten_count

        if forgotten_count > 0:
            logger.info(f"记忆清理完成，共遗忘 {forgotten_count} 条记忆")

        return forgotten_count

    # ----------------------------------------------------------------
    # 记忆关联
    # ----------------------------------------------------------------

    async def build_associations(self, entry: MemoryEntry) -> int:
        """建立记忆之间的关联

        基于关键词重叠和语义相似度自动发现关联。

        Args:
            entry: 新存储的记忆条目

        Returns:
            建立的关联数量
        """
        if not entry.keywords and entry.content:
            entry.keywords = self._extract_keywords(entry.content)

        entry_keywords = set(entry.keywords)
        association_count = 0

        # 在所有记忆类型中查找关联
        for mem_type_value, entries in self._memories.items():
            for existing_entry in entries:
                if existing_entry.id == entry.id:
                    continue

                existing_keywords = set(existing_entry.keywords)
                overlap = entry_keywords & existing_keywords

                # 至少有2个共同关键词才建立关联
                if len(overlap) >= 2:
                    # 添加双向关联
                    if entry.id not in existing_entry.associations:
                        existing_entry.associations.append(entry.id)
                    if existing_entry.id not in entry.associations:
                        entry.associations.append(existing_entry.id)
                    association_count += 1

                    # 更新关联图谱
                    self._association_graph.setdefault(
                        entry.id, set()
                    ).add(existing_entry.id)
                    self._association_graph.setdefault(
                        existing_entry.id, set()
                    ).add(entry.id)

        self._stats["total_associations"] += association_count

        if association_count > 0:
            logger.debug(
                f"为记忆 {entry.id} 建立了 {association_count} 条关联"
            )

        return association_count

    # ----------------------------------------------------------------
    # 统计信息
    # ----------------------------------------------------------------

    def get_stats(self) -> dict[str, Any]:
        """获取记忆系统统计信息

        Returns:
            包含各维度统计的字典
        """
        type_counts: dict[str, int] = {}
        for mem_type, entries in self._memories.items():
            type_counts[mem_type] = len(entries)

        total_associations = sum(
            len(targets) for targets in self._association_graph.values()
        )

        # 计算平均重要性
        importance_by_type: dict[str, float] = {}
        for mem_type, entries in self._memories.items():
            if entries:
                avg = sum(e.importance for e in entries) / len(entries)
                importance_by_type[mem_type] = round(avg, 3)
            else:
                importance_by_type[mem_type] = 0.0

        return {
            "memory_counts_by_type": type_counts,
            "total_memories": sum(type_counts.values()),
            "total_association_edges": total_associations,
            "average_importance_by_type": importance_by_type,
            "operations": self._stats,
            "initialized": self._initialized,
            "has_jieba": HAS_JIEBA,
        }

    # ----------------------------------------------------------------
    # 内部方法
    # ----------------------------------------------------------------

    def _assess_importance(self, content: str) -> float:
        """评估记忆内容的重要性

        基于关键词匹配和内容特征自动评分。

        Args:
            content: 记忆内容文本

        Returns:
            0.0-1.0 的重要性评分
        """
        score = 0.5  # 默认中等重要性

        # 关键词匹配
        for keyword, weight in self._IMPORTANCE_KEYWORDS.items():
            if keyword in content:
                score = max(score, weight)

        # 长度加权：过短的内容通常不太重要
        if len(content) < 10:
            score = min(score, 0.3)
        elif len(content) > 200:
            score = min(score + 0.1, 1.0)

        # 包含数字/代码的内容可能更重要（技术细节）
        if re.search(r"\d+\.?\d*", content) or re.search(r"[{}()\[\]]", content):
            score = min(score + 0.05, 1.0)

        return round(max(0.0, min(1.0, score)), 3)

    def _extract_keywords(self, content: str) -> list[str]:
        """从内容中提取关键词

        Args:
            content: 文本内容

        Returns:
            关键词列表（最多15个）
        """
        tokens = self._vectorizer.tokenize(content)

        if not tokens:
            # 退化为简单分词
            words = re.findall(r"[\w]{2,}", content)
            return words[:15]

        # 使用词频选择关键词
        token_counts = Counter(tokens)
        top_keywords = [t for t, _ in token_counts.most_common(15)]

        return top_keywords

    def _calculate_entry_retention(self, entry: MemoryEntry) -> float:
        """计算单条记忆的当前保持率

        Args:
            entry: 记忆条目

        Returns:
            0.0-1.0 的保持率
        """
        try:
            created = datetime.fromisoformat(entry.created_at.replace("Z", "+00:00"))
            accessed = datetime.fromisoformat(entry.accessed_at.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)

            # 使用最后访问时间计算衰减
            hours_since = (now - accessed).total_seconds() / 3600
            retention = EbbinghausDecay.calculate_retention(
                hours_since_access=hours_since,
                review_count=entry.access_count,
                base_stability=entry.importance,  # 重要性高的记忆更稳定
            )
            return retention
        except (ValueError, TypeError):
            return 0.5  # 时间解析失败，给默认值

    async def _update_decay_factors(self) -> None:
        """更新所有记忆的衰减因子"""
        for mem_type_value, entries in self._memories.items():
            for entry in entries:
                retention = self._calculate_entry_retention(entry)
                entry.decay_factor = retention

    async def _cleanup_working_memory(self, session_id: str) -> None:
        """清理指定会话的工作记忆

        Args:
            session_id: 会话 ID
        """
        working_entries = self._memories[MemoryType.WORKING.value]
        self._memories[MemoryType.WORKING.value] = [
            e for e in working_entries if e.session_id != session_id
        ]
        await self._persist_memory(MemoryType.WORKING.value)

    def _rebuild_association_graph(self) -> None:
        """从现有记忆重建关联图谱"""
        self._association_graph.clear()
        for entries in self._memories.values():
            for entry in entries:
                if entry.associations:
                    self._association_graph[entry.id] = set(entry.associations)

    def _rebuild_tfidf_index(self) -> None:
        """重建 TF-IDF 索引"""
        all_documents: list[str] = []
        for entries in self._memories.values():
            for entry in entries:
                text = " ".join(entry.keywords) + " " + entry.content
                all_documents.append(text)

        if all_documents:
            self._vectorizer.clear_cache()
            self._vectorizer.fit(all_documents)

    def _remove_from_associations(self, entry_id: str) -> None:
        """从关联图谱中移除指定记忆

        Args:
            entry_id: 记忆 ID
        """
        # 移除该记忆的关联
        if entry_id in self._association_graph:
            associated_ids = self._association_graph.pop(entry_id)
            # 同时从被关联记忆中移除反向关联
            for assoc_id in associated_ids:
                if assoc_id in self._association_graph:
                    self._association_graph[assoc_id].discard(entry_id)

    # ----------------------------------------------------------------
    # 持久化
    # ----------------------------------------------------------------

    async def _load_memory_file(self, mem_type: str, filename: str) -> None:
        """从 JSON 文件加载记忆数据

        Args:
            mem_type: 记忆类型
            filename: 文件名
        """
        filepath = os.path.join(self._data_dir, filename)
        if not os.path.exists(filepath):
            logger.debug(f"记忆文件不存在，跳过: {filepath}")
            return

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)

            entries: list[MemoryEntry] = []
            for item in data:
                try:
                    entry = MemoryEntry.from_dict(item)
                    entries.append(entry)
                except (TypeError, ValueError) as e:
                    logger.warning(f"加载记忆条目失败: {e}")
                    continue

            self._memories[mem_type] = entries
            logger.info(f"加载了 {len(entries)} 条 {mem_type} 记忆")

        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"加载记忆文件失败: {filepath}, 错误: {e}")

    async def _persist_memory(self, mem_type: str) -> None:
        """将记忆数据持久化到 JSON 文件

        Args:
            mem_type: 记忆类型
        """
        filename = self._MEMORY_FILES.get(mem_type)
        if not filename:
            logger.warning(f"未知的记忆类型: {mem_type}，跳过持久化")
            return

        filepath = os.path.join(self._data_dir, filename)

        try:
            entries = self._memories.get(mem_type, [])
            data = [entry.to_dict() for entry in entries]

            # 原子写入：先写临时文件，再重命名
            temp_path = filepath + ".tmp"
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            os.replace(temp_path, filepath)

        except (IOError, TypeError) as e:
            logger.error(f"持久化记忆失败: {filepath}, 错误: {e}")

    async def persist_all(self) -> None:
        """持久化所有类型的记忆"""
        for mem_type in self._MEMORY_FILES:
            await self._persist_memory(mem_type)
        logger.info("所有记忆已持久化")


# ============================================================================
# 单例工厂
# ============================================================================

_intelligent_memory_instance: Optional[IntelligentMemory] = None
_intelligent_memory_lock: Optional[asyncio.Lock] = None


async def get_intelligent_memory() -> IntelligentMemory:
    """获取智能记忆系统的单例实例（延迟初始化）

    确保整个应用生命周期中只存在一个 IntelligentMemory 实例。

    Returns:
        IntelligentMemory 单例实例
    """
    global _intelligent_memory_instance, _intelligent_memory_lock

    if _intelligent_memory_instance is not None:
        return _intelligent_memory_instance

    if _intelligent_memory_lock is None:
        _intelligent_memory_lock = asyncio.Lock()

    async with _intelligent_memory_lock:
        if _intelligent_memory_instance is None:
            _intelligent_memory_instance = IntelligentMemory()
            await _intelligent_memory_instance.initialize()
            logger.info("智能记忆系统单例已创建")

    return _intelligent_memory_instance
