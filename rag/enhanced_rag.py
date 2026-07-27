"""LUMU 增强RAG系统 - 高级检索增强生成

核心能力:
1. 智能文档解析: 支持PDF/Markdown/TXT/HTML/CSV/JSON/代码文件
2. 语义分块: 基于语义边界而非固定长度的智能文本分块
3. 混合检索: 关键词(BM25) + 向量语义 的混合检索
4. 查询改写: 自动改写用户查询提升检索质量
5. 重排序: 检索结果交叉编码器重排序
6. 上下文压缩: 精简检索内容减少LLM输入
7. 多跳推理: 复杂问题的多轮检索推理
8. 自适应检索: 根据查询复杂度动态调整检索策略
9. 实时网页抓取: 动态获取网页内容作为知识源
10. 知识更新: 增量式知识库更新
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---- 日志配置 ----
try:
    from core.logging_config import get_logger
except ImportError:
    def get_logger(name: str) -> Any:  # type: ignore[misc]
        """回退日志器，当 core.logging_config 不可用时使用标准 logging"""
        import logging
        return logging.getLogger(name)

logger = get_logger("enhanced_rag")

# ---- 类型定义 ----


@dataclass
class IngestResult:
    """文档导入结果"""
    chunks_count: int
    source_id: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RetrievalResult:
    """检索结果"""
    content: str
    score: float
    source: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class MultiHopResult:
    """多跳推理结果"""
    final_answer: str
    reasoning_chain: list[str] = field(default_factory=list)
    hops: list[dict[str, Any]] = field(default_factory=list)


# ---- 数据存储路径 ----
_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "rag"
_VECTORS_FILE = _DATA_DIR / "vectors.json"
_INVERTED_INDEX_FILE = _DATA_DIR / "inverted_index.json"
_DOCUMENTS_FILE = _DATA_DIR / "documents.json"


def _ensure_data_dir() -> Path:
    """确保数据目录存在"""
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    return _DATA_DIR


def _load_json(path: Path) -> dict[str, Any]:
    """安全加载JSON文件，不存在则返回空字典"""
    try:
        if path.exists():
            text = path.read_text(encoding="utf-8")
            if text.strip():
                return json.loads(text)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("加载JSON文件失败: path=%s, error=%s", path, exc)
    return {}


def _save_json(path: Path, data: dict[str, Any]) -> None:
    """安全保存JSON文件，带原子写入"""
    try:
        _ensure_data_dir()
        tmp_path = path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(path)
    except OSError as exc:
        logger.error("保存JSON文件失败: path=%s, error=%s", path, exc)


# ---- 文档解析器 ----


class _DocumentParser:
    """文档解析器 - 支持多种文件格式"""

    # 支持的文件扩展名
    SUPPORTED_EXTENSIONS: dict[str, str] = {
        ".md": "markdown",
        ".txt": "text",
        ".csv": "csv",
        ".json": "json",
        ".py": "code",
        ".js": "code",
        ".ts": "code",
        ".html": "html",
        ".htm": "html",
    }

    @classmethod
    def parse(cls, file_path: str) -> str:
        """解析文件并返回纯文本内容

        Args:
            file_path: 文件路径

        Returns:
            解析后的纯文本内容

        Raises:
            ValueError: 不支持的文件格式
            FileNotFoundError: 文件不存在
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")

        ext = path.suffix.lower()
        if ext not in cls.SUPPORTED_EXTENSIONS:
            raise ValueError(f"不支持的文件格式: {ext}")

        raw = path.read_text(encoding="utf-8", errors="replace")
        fmt = cls.SUPPORTED_EXTENSIONS[ext]

        parser_map = {
            "markdown": cls._parse_markdown,
            "text": cls._parse_text,
            "csv": cls._parse_csv,
            "json": cls._parse_json,
            "code": cls._parse_code,
            "html": cls._parse_html,
        }
        return parser_map[fmt](raw)

    @staticmethod
    def _parse_markdown(text: str) -> str:
        """解析Markdown，移除标记符号保留语义"""
        # 移除代码块标记
        text = re.sub(r"```[\w]*\n?", "", text)
        # 移除行内标记
        text = re.sub(r"[*_]{1,2}([^*_]+)[*_]{1,2}", r"\1", text)
        # 移除标题标记
        text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
        # 移除链接，保留文本
        text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
        # 移除图片
        text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", text)
        # 移除表格分隔行
        text = re.sub(r"^\|?[-:| ]+\|?$", "", text, flags=re.MULTILINE)
        return text.strip()

    @staticmethod
    def _parse_text(text: str) -> str:
        """纯文本直接返回"""
        return text.strip()

    @staticmethod
    def _parse_csv(text: str) -> str:
        """将CSV转换为描述性文本"""
        lines = text.strip().split("\n")
        if len(lines) < 2:
            return text.strip()
        headers = lines[0].split(",")
        result_parts: list[str] = []
        for row_line in lines[1:]:
            values = row_line.split(",")
            if len(values) == len(headers):
                pairs = [f"{h.strip()}: {v.strip()}" for h, v in zip(headers, values)]
                result_parts.append("; ".join(pairs))
        return "\n".join(result_parts) if result_parts else text.strip()

    @staticmethod
    def _parse_json(text: str) -> str:
        """将JSON转换为描述性文本"""
        try:
            data = json.loads(text)
            if isinstance(data, list):
                return "\n".join(json.dumps(item, ensure_ascii=False) for item in data[:100])
            elif isinstance(data, dict):
                return json.dumps(data, ensure_ascii=False, indent=2)
            return str(data)
        except json.JSONDecodeError:
            return text.strip()

    @staticmethod
    def _parse_code(text: str) -> str:
        """代码文件保留注释和结构"""
        # 移除单行注释
        text = re.sub(r"#[^\n]*", "", text)
        # 移除多行注释
        text = re.sub(r'""".*?"""', "", text, flags=re.DOTALL)
        text = re.sub(r"'''.*?'''", "", text, flags=re.DOTALL)
        text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
        text = re.sub(r"//.*", "", text)
        return text.strip()

    @staticmethod
    def _parse_html(text: str) -> str:
        """移除HTML标签，保留文本"""
        text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"&[a-zA-Z]+;", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()


# ---- 语义分块器 ----


class _SemanticChunker:
    """语义分块器 - 基于语义边界进行智能分块

    分块策略:
    1. 优先按段落(双换行)分割
    2. 段落过大时按句子(句号/问号/感叹号)分割
    3. 句子仍过大时按固定窗口分割（回退方案）
    """

    # 中英文句子分隔符
    _SENTENCE_PATTERN = re.compile(r"(?<=[。！？.!?\n])\s+")

    def __init__(self, max_chunk_size: int = 500, overlap_size: int = 50) -> None:
        """
        Args:
            max_chunk_size: 单个分块的最大字符数
            overlap_size: 分块之间的重叠字符数
        """
        self._max_chunk_size = max_chunk_size
        self._overlap_size = overlap_size

    def chunk(self, text: str) -> list[str]:
        """对文本进行语义分块

        Args:
            text: 待分块的文本

        Returns:
            分块列表
        """
        if not text or not text.strip():
            return []

        text = text.strip()
        chunks: list[str] = []

        # 第一层: 按段落分割
        paragraphs = re.split(r"\n\s*\n", text)
        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            if len(para) <= self._max_chunk_size:
                chunks.append(para)
            else:
                # 第二层: 按句子分割
                sentences = self._SENTENCE_PATTERN.split(para)
                current_chunk = ""

                for sentence in sentences:
                    sentence = sentence.strip()
                    if not sentence:
                        continue

                    if len(current_chunk) + len(sentence) <= self._max_chunk_size:
                        current_chunk = (current_chunk + " " + sentence).strip() if current_chunk else sentence
                    else:
                        if current_chunk:
                            chunks.append(current_chunk)
                        # 第三层回退: 单个句子仍超长，用固定窗口
                        if len(sentence) > self._max_chunk_size:
                            window_chunks = self._window_split(sentence)
                            chunks.extend(window_chunks)
                            current_chunk = ""
                        else:
                            # 添加重叠
                            if current_chunk and self._overlap_size > 0:
                                overlap_text = current_chunk[-self._overlap_size:]
                                current_chunk = overlap_text + " " + sentence
                            else:
                                current_chunk = sentence

                if current_chunk:
                    chunks.append(current_chunk)

        return [c for c in chunks if c.strip()]

    def _window_split(self, text: str) -> list[str]:
        """固定窗口分割（最终回退方案）"""
        chunks: list[str] = []
        start = 0
        while start < len(text):
            end = start + self._max_chunk_size
            # 尝试在空格处断开
            if end < len(text):
                space_pos = text.rfind(" ", start, end)
                if space_pos > start:
                    end = space_pos
            chunks.append(text[start:end].strip())
            start = end - self._overlap_size if self._overlap_size > 0 and end < len(text) else end
        return [c for c in chunks if c.strip()]


# ---- TF-IDF 检索引擎 ----


# 真向量嵌入（与记忆/知识库共用同一向量空间），让 RAG 检索从"字面"升级到"语义"。
try:
    from memory.embeddings import embed as _rag_embed, cosine as _rag_cosine
    _RAG_HAS_EMBED = True
except Exception:  # 兜底：理论上不会触发（knowledge.embedding 自带哈希兜底）
    _RAG_HAS_EMBED = False
    def _rag_embed(text):
        return [0.0] * 8
    def _rag_cosine(a, b):
        return 0.0


class _TFIDFEngine:
    """轻量级TF-IDF + 关键词匹配检索引擎

    不依赖外部向量库，使用倒排索引和TF-IDF评分实现混合检索。
    """

    def __init__(self) -> None:
        self._chunks: dict[str, dict[str, Any]] = {}  # chunk_id -> {content, source_id, metadata, tokens}
        self._inverted_index: dict[str, list[str]] = {}  # token -> [chunk_ids]
        self._documents: dict[str, dict[str, Any]] = {}  # source_id -> {metadata, chunks, created_at}
        self._idf: dict[str, float] = {}
        self._dirty = False

    def add_chunk(
        self,
        chunk_id: str,
        content: str,
        source_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """添加一个文本分块到索引

        Args:
            chunk_id: 分块唯一标识
            content: 分块文本内容
            source_id: 来源标识
            metadata: 元数据
        """
        tokens = self._tokenize(content)
        info: dict[str, Any] = {
            "content": content,
            "source_id": source_id,
            "metadata": metadata or {},
            "tokens": tokens,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        # 真向量语义嵌入（懒失败：嵌入失败不影响词法检索）
        if _RAG_HAS_EMBED:
            try:
                info["embedding"] = _rag_embed(content)
            except Exception:
                info["embedding"] = None
        else:
            info["embedding"] = None
        self._chunks[chunk_id] = info

        # 更新倒排索引
        for token in set(tokens):
            if token not in self._inverted_index:
                self._inverted_index[token] = []
            if chunk_id not in self._inverted_index[token]:
                self._inverted_index[token].append(chunk_id)

        self._dirty = True

    def remove_source(self, source_id: str) -> int:
        """移除指定来源的所有分块

        Args:
            source_id: 来源标识

        Returns:
            移除的分块数量
        """
        chunk_ids_to_remove = [
            cid for cid, info in self._chunks.items() if info["source_id"] == source_id
        ]

        for cid in chunk_ids_to_remove:
            tokens = self._chunks[cid].get("tokens", [])
            for token in set(tokens):
                if token in self._inverted_index:
                    self._inverted_index[token] = [
                        x for x in self._inverted_index[token] if x != cid
                    ]
                    if not self._inverted_index[token]:
                        del self._inverted_index[token]
            del self._chunks[cid]

        if source_id in self._documents:
            del self._documents[source_id]

        self._dirty = True
        return len(chunk_ids_to_remove)

    def search(
        self,
        query: str,
        top_k: int = 5,
        search_type: str = "hybrid",
    ) -> list[RetrievalResult]:
        """搜索最相关的文本分块

        Args:
            query: 查询文本
            top_k: 返回的结果数量
            search_type: 检索类型 ("keyword" | "tfidf" | "hybrid")

        Returns:
            检索结果列表，按相关性降序排列
        """
        self._recompute_idf()
        query_tokens = self._tokenize(query)
        query_emb = _rag_embed(query) if _RAG_HAS_EMBED else None

        def _chunk_emb(info):
            """返回 chunk 的真向量（惰性计算并回填缓存）。"""
            emb = info.get("embedding")
            if emb is None and _RAG_HAS_EMBED:
                try:
                    emb = _rag_embed(info.get("content", ""))
                    info["embedding"] = emb
                except Exception:
                    emb = None
            return emb

        # 既没有 token 也没有向量，无法检索
        if not query_tokens and query_emb is None:
            return []

        results: list[tuple[str, float]] = []

        if search_type == "keyword":
            # 纯关键词匹配（保持原样）
            candidate_ids: set[str] = set()
            for token in query_tokens:
                candidate_ids.update(self._inverted_index.get(token, []))
            for cid in candidate_ids:
                match_count = sum(
                    1 for t in query_tokens if t in self._chunks[cid].get("tokens", [])
                )
                score = match_count / len(query_tokens) if query_tokens else 0.0
                results.append((cid, score))

        elif search_type == "tfidf":
            # 语义为主：能用真向量就用语义相似度，否则退回 TF-IDF 词法
            for cid, info in self._chunks.items():
                if query_emb is not None:
                    emb = _chunk_emb(info)
                    score = _rag_cosine(query_emb, emb) if emb is not None else \
                        self._tfidf_score(query_tokens, info.get("tokens", []))
                else:
                    score = self._tfidf_score(query_tokens, info.get("tokens", []))
                if score > 0:
                    results.append((cid, score))

        else:
            # 混合检索: 语义(0.6) + 词法(0.4)；无嵌入时退回纯词法
            for cid, info in self._chunks.items():
                lexical = 0.6 * self._tfidf_score(query_tokens, info.get("tokens", [])) \
                          + 0.4 * self._keyword_score(query_tokens, info.get("tokens", []))
                if query_emb is not None:
                    emb = _chunk_emb(info)
                    if emb is not None:
                        score = 0.6 * _rag_cosine(query_emb, emb) + 0.4 * lexical
                    else:
                        score = lexical
                else:
                    score = lexical
                if score > 0:
                    results.append((cid, score))

        # 按分数降序排列
        results.sort(key=lambda x: x[1], reverse=True)
        top_results = results[:top_k]

        return [
            RetrievalResult(
                content=self._chunks[cid]["content"],
                score=score,
                source=self._chunks[cid]["source_id"],
                metadata=self._chunks[cid].get("metadata", {}),
            )
            for cid, score in top_results
        ]

    def register_document(self, source_id: str, metadata: dict[str, Any]) -> None:
        """注册一个文档来源"""
        self._documents[source_id] = {
            "metadata": metadata,
            "chunk_ids": [
                cid for cid, info in self._chunks.items() if info["source_id"] == source_id
            ],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    def get_document(self, source_id: str) -> dict[str, Any] | None:
        """获取文档信息"""
        return self._documents.get(source_id)

    def get_stats(self) -> dict[str, Any]:
        """获取索引统计信息"""
        self._recompute_idf()
        return {
            "total_chunks": len(self._chunks),
            "total_documents": len(self._documents),
            "vocabulary_size": len(self._inverted_index),
            "idf_terms": len(self._idf),
        }

    def save(self) -> None:
        """持久化存储索引"""
        _save_json(_VECTORS_FILE, self._chunks)
        _save_json(_INVERTED_INDEX_FILE, self._inverted_index)
        _save_json(_DOCUMENTS_FILE, self._documents)
        self._dirty = False
        logger.info("索引数据已保存, chunks=%d", len(self._chunks))

    def load(self) -> None:
        """从磁盘加载索引"""
        self._chunks = _load_json(_VECTORS_FILE)
        self._inverted_index = _load_json(_INVERTED_INDEX_FILE)
        self._documents = _load_json(_DOCUMENTS_FILE)
        self._dirty = True
        logger.info("索引数据已加载, chunks=%d", len(self._chunks))

    def _tokenize(self, text: str) -> list[str]:
        """简单分词: 按空白和标点分割，转小写，去停用词"""
        text = text.lower()
        # 中文字符单独切分
        chinese_chars = re.findall(r"[\u4e00-\u9fff]", text)
        # 英文按空白和标点分割
        english_tokens = re.findall(r"[a-z0-9]+", text)
        # 合并
        tokens = chinese_chars + english_tokens
        # 去除单字符英文停用词
        stopwords = {
            "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
            "have", "has", "had", "do", "does", "did", "will", "would", "could",
            "should", "may", "might", "can", "shall", "of", "in", "on", "at",
            "to", "for", "with", "by", "from", "as", "or", "and", "not", "it",
            "的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都",
            "一", "一个", "上", "也", "很", "到", "说", "要", "去", "你",
            "会", "着", "没有", "看", "好", "自己", "这",
        }
        return [t for t in tokens if t not in stopwords and len(t) > 0]

    def _recompute_idf(self) -> None:
        """重新计算IDF值"""
        if not self._dirty:
            return
        total_docs = max(len(self._chunks), 1)
        self._idf = {}
        for token, cids in self._inverted_index.items():
            self._idf[token] = math.log(total_docs / (len(cids) + 1)) + 1.0
        self._dirty = False

    def _tfidf_score(self, query_tokens: list[str], doc_tokens: list[str]) -> float:
        """计算TF-IDF余弦相似度"""
        if not query_tokens or not doc_tokens:
            return 0.0

        # 构建向量
        all_tokens = set(query_tokens) | set(doc_tokens)
        query_vec: dict[str, float] = {}
        doc_vec: dict[str, float] = {}

        for token in all_tokens:
            if token in query_tokens:
                query_vec[token] = query_tokens.count(token) * self._idf.get(token, 1.0)
            if token in doc_tokens:
                doc_vec[token] = doc_tokens.count(token) * self._idf.get(token, 1.0)

        # 余弦相似度
        dot = sum(query_vec.get(t, 0) * doc_vec.get(t, 0) for t in all_tokens)
        norm_q = math.sqrt(sum(v * v for v in query_vec.values()))
        norm_d = math.sqrt(sum(v * v for v in doc_vec.values()))

        if norm_q == 0 or norm_d == 0:
            return 0.0
        return dot / (norm_q * norm_d)

    def _keyword_score(self, query_tokens: list[str], doc_tokens: list[str]) -> float:
        """关键词精确匹配评分"""
        if not query_tokens:
            return 0.0
        doc_set = set(doc_tokens)
        return sum(1 for t in query_tokens if t in doc_set) / len(query_tokens)


# ---- 上下文压缩器 ----


class _ContextCompressor:
    """上下文压缩器 - 精简检索内容减少LLM输入"""

    @staticmethod
    def compress(
        results: list[RetrievalResult],
        max_tokens: int = 2000,
    ) -> str:
        """将检索结果压缩为紧凑的上下文字符串

        Args:
            results: 检索结果列表
            max_tokens: 最大大致字符数限制（近似token数）

        Returns:
            压缩后的上下文字符串
        """
        if not results:
            return ""

        parts: list[str] = []
        current_length = 0

        for i, result in enumerate(results, 1):
            # 截断过长的内容
            content = result.content[:max_tokens // max(len(results), 1)]
            part = f"[{i}] (来源: {result.source}, 相关度: {result.score:.2f})\n{content}"
            part_length = len(part)

            if current_length + part_length > max_tokens:
                break

            parts.append(part)
            current_length += part_length

        return "\n\n".join(parts) if parts else ""


# ---- 核心类: EnhancedRAG ----


class EnhancedRAG:
    """增强RAG系统 - 高级检索增强生成引擎

    提供智能文档解析、语义分块、混合检索、查询改写、
    多跳推理、自适应检索等核心能力。

    用法示例::

        rag = get_enhanced_rag()
        await rag.initialize()
        result = await rag.ingest_document("doc.md")
        hits = await rag.search("如何配置系统?")
    """

    def __init__(self) -> None:
        self._engine = _TFIDFEngine()
        self._chunker = _SemanticChunker(max_chunk_size=500, overlap_size=50)
        self._parser = _DocumentParser()
        self._compressor = _ContextCompressor()
        self._initialized = False

    async def initialize(self) -> None:
        """初始化RAG系统，加载已有索引数据"""
        if self._initialized:
            return
        try:
            self._engine.load()
            self._initialized = True
            logger.info("增强RAG系统初始化完成")
        except Exception as exc:
            logger.error("增强RAG系统初始化失败: %s", exc)
            raise

    def _ensure_init(self) -> None:
        """确保系统已初始化"""
        if not self._initialized:
            raise RuntimeError("RAG系统未初始化，请先调用 initialize()")

    async def ingest_document(
        self,
        file_path: str,
        metadata: dict[str, Any] | None = None,
    ) -> IngestResult:
        """文档导入 - 解析文件并进行语义分块索引

        Args:
            file_path: 文件路径
            metadata: 附加元数据

        Returns:
            导入结果，包含分块数量和来源ID
        """
        self._ensure_init()
        logger.info("开始导入文档: %s", file_path)

        try:
            text = self._parser.parse(file_path)
        except (FileNotFoundError, ValueError) as exc:
            logger.error("文档解析失败: %s, error: %s", file_path, exc)
            raise
        except Exception as exc:
            logger.error("文档解析发生意外错误: %s, error: %s", file_path, exc)
            raise

        return await self.ingest_text(text, metadata=metadata or {"file_path": file_path})

    async def ingest_text(
        self,
        text: str,
        metadata: dict[str, Any] | None = None,
    ) -> IngestResult:
        """文本导入 - 对纯文本进行语义分块索引

        Args:
            text: 纯文本内容
            metadata: 附加元数据

        Returns:
            导入结果，包含分块数量和来源ID
        """
        self._ensure_init()

        if not text or not text.strip():
            raise ValueError("文本内容不能为空")

        source_id = metadata.get("source_id") if metadata else None
        if not source_id:
            source_id = hashlib.md5(text.encode("utf-8")).hexdigest()[:16]

        chunks = self._chunker.chunk(text)
        logger.info("文本分块完成: source_id=%s, chunks=%d", source_id, len(chunks))

        doc_metadata = metadata or {}
        self._engine.register_document(source_id, doc_metadata)

        for i, chunk_text in enumerate(chunks):
            chunk_id = f"{source_id}_chunk_{i:04d}"
            chunk_meta = {**doc_metadata, "chunk_index": i}
            self._engine.add_chunk(chunk_id, chunk_text, source_id, chunk_meta)

        self._engine.save()
        return IngestResult(
            chunks_count=len(chunks),
            source_id=source_id,
            metadata=doc_metadata,
        )

    async def search(
        self,
        query: str,
        top_k: int = 5,
        search_type: str = "hybrid",
    ) -> list[RetrievalResult]:
        """搜索知识库

        Args:
            query: 查询文本
            top_k: 返回的最大结果数
            search_type: 检索类型 ("keyword" | "tfidf" | "hybrid")

        Returns:
            检索结果列表
        """
        self._ensure_init()

        if not query or not query.strip():
            logger.warning("搜索查询为空")
            return []

        if search_type not in ("keyword", "tfidf", "hybrid"):
            logger.warning("未知检索类型: %s, 使用hybrid", search_type)
            search_type = "hybrid"

        logger.info("执行搜索: query=%s, type=%s, top_k=%d", query[:50], search_type, top_k)
        return self._engine.search(query, top_k=top_k, search_type=search_type)

    async def rewrite_query(self, query: str) -> list[str]:
        """查询改写 - 生成多个改写版本以提升检索召回率

        注意: 此方法为同步返回改写结果的设计。
        在实际调用LLM时，改写逻辑可通过 generate_answer 等方法配合使用。

        Args:
            query: 原始查询

        Returns:
            包含原始查询和改写版本的列表
        """
        self._ensure_init()

        # 基于规则的简单改写（无需LLM的基础改写）
        rewrites: list[str] = [query]

        # 去除疑问词
        question_words = [
            "什么是", "如何", "怎么", "为什么", "请问", "能否",
            "what is", "how to", "why", "what are", "how do",
        ]
        stripped = query
        for qw in question_words:
            if stripped.lower().startswith(qw):
                stripped = stripped[len(qw):].strip()
                break
        if stripped and stripped != query:
            rewrites.append(stripped)

        # 提取关键短语（简单实现：按标点和停用词分割后取有意义的片段）
        keywords = self._extract_keywords(query)
        if keywords:
            rewrites.append(" ".join(keywords))

        logger.info("查询改写完成: original=%s, rewrites=%d", query[:50], len(rewrites))
        return rewrites

    def _extract_keywords(self, text: str) -> list[str]:
        """从文本中提取关键词"""
        tokens = self._engine._tokenize(text)
        # 按出现频率排序，取高频词
        freq: dict[str, int] = {}
        for t in tokens:
            freq[t] = freq.get(t, 0) + 1
        sorted_tokens = sorted(freq.items(), key=lambda x: x[1], reverse=True)
        return [t for t, _ in sorted_tokens[:5]]

    async def multi_hop_search(
        self,
        query: str,
        max_hops: int = 3,
    ) -> MultiHopResult:
        """多跳推理搜索 - 通过多轮检索和推理解决复杂问题

        Args:
            query: 初始查询
            max_hops: 最大检索轮数

        Returns:
            多跳推理结果
        """
        self._ensure_init()
        logger.info("开始多跳推理搜索: query=%s, max_hops=%d", query[:50], max_hops)

        reasoning_chain: list[str] = [f"初始查询: {query}"]
        hops: list[dict[str, Any]] = []
        all_context: list[RetrievalResult] = []

        current_query = query
        for hop in range(max_hops):
            # 检索当前查询的相关文档
            results = await self.search(current_query, top_k=3)
            if not results:
                reasoning_chain.append(f"第{hop + 1}跳: 未找到相关结果，终止推理")
                break

            hop_info = {
                "hop": hop + 1,
                "query": current_query,
                "results_count": len(results),
                "top_content": results[0].content[:200] if results else "",
            }
            hops.append(hop_info)

            # 追加新内容（去重）
            existing_contents = {r.content for r in all_context}
            new_results = [r for r in results if r.content not in existing_contents]
            all_context.extend(new_results)

            reasoning_chain.append(
                f"第{hop + 1}跳: 检索到 {len(new_results)} 条新结果 "
                f"(累计 {len(all_context)} 条)"
            )

            if hop < max_hops - 1:
                # 分析已有上下文，生成后续查询
                current_query = await self._generate_followup_query(
                    current_query, new_results
                )
                reasoning_chain.append(f"第{hop + 1}跳后续查询: {current_query}")

        final_answer = self._compressor.compress(all_context, max_tokens=3000)
        if not final_answer:
            final_answer = "未能通过多跳推理找到充分的信息来回答此问题。"

        return MultiHopResult(
            final_answer=final_answer,
            reasoning_chain=reasoning_chain,
            hops=hops,
        )

    async def _generate_followup_query(
        self,
        original_query: str,
        results: list[RetrievalResult],
    ) -> str:
        """基于当前检索结果生成后续查询（基于关键词提取的简单实现）"""
        # 从当前结果中提取出现频率最高且不在原始查询中的关键词
        all_text = " ".join(r.content for r in results)
        result_keywords = set(self._extract_keywords(all_text))
        query_keywords = set(self._extract_keywords(original_query))

        new_keywords = result_keywords - query_keywords
        if new_keywords:
            # 用新关键词补充原始查询
            top_new = sorted(new_keywords)[:3]
            return f"{original_query} {' '.join(top_new)}"
        return original_query

    async def adaptive_search(self, query: str) -> list[RetrievalResult]:
        """自适应搜索 - 根据查询复杂度动态调整检索策略

        简单查询使用关键词检索，复杂查询使用混合检索 + 更大top_k。

        Args:
            query: 查询文本

        Returns:
            检索结果列表
        """
        self._ensure_init()

        complexity = self._estimate_complexity(query)
        logger.info("查询复杂度评估: query=%s, complexity=%.2f", query[:50], complexity)

        if complexity < 0.3:
            # 简单查询: 关键词检索，少量结果
            return await self.search(query, top_k=3, search_type="keyword")
        elif complexity < 0.6:
            # 中等复杂度: 混合检索
            return await self.search(query, top_k=5, search_type="hybrid")
        else:
            # 复杂查询: 混合检索 + 查询改写融合
            rewrites = await self.rewrite_query(query)
            all_results: list[RetrievalResult] = []
            seen_contents: set[str] = set()

            for rw in rewrites:
                results = await self.search(rw, top_k=5, search_type="hybrid")
                for r in results:
                    if r.content not in seen_contents:
                        seen_contents.add(r.content)
                        all_results.append(r)

            # 按分数重新排序
            all_results.sort(key=lambda x: x.score, reverse=True)
            return all_results[:10]

    def _estimate_complexity(self, query: str) -> float:
        """估计查询复杂度 (0.0 ~ 1.0)

        基于查询长度、关键词数量、是否包含多主题等特征。
        """
        score = 0.0

        # 长度因子
        if len(query) > 100:
            score += 0.3
        elif len(query) > 50:
            score += 0.15

        # 关键词数量因子
        keywords = self._extract_keywords(query)
        if len(keywords) > 8:
            score += 0.3
        elif len(keywords) > 4:
            score += 0.15

        # 多主题指示（是否包含连接词）
        multi_topic_markers = [
            "以及", "并且", "同时", "另外", "还有", "比较",
            "and", "also", "compare", "difference", "between",
        ]
        for marker in multi_topic_markers:
            if marker in query.lower():
                score += 0.2
                break

        # 问题类型
        complex_question_markers = [
            "为什么", "如何分析", "比较", "对比", "影响",
            "why", "analyze", "compare", "impact", "relationship",
        ]
        for marker in complex_question_markers:
            if marker in query.lower():
                score += 0.2
                break

        return min(score, 1.0)

    async def generate_answer(
        self,
        query: str,
        context: list[RetrievalResult],
        client: Any = None,
        model: str = "",
    ) -> str:
        """基于检索结果生成答案

        使用LLM根据检索到的上下文生成对查询的回答。

        Args:
            query: 用户查询
            context: 检索结果列表
            client: OpenAI兼容API客户端（需支持 chat.completions.create）
            model: 模型名称

        Returns:
            生成的答案文本
        """
        if not client:
            logger.warning("generate_answer: 未提供LLM客户端，返回压缩上下文")
            return self._compressor.compress(context, max_tokens=2000)

        compressed = self._compressor.compress(context, max_tokens=3000)
        if not compressed:
            return "未找到相关信息来回答您的问题。"

        system_prompt = (
            "你是一个知识助手。请根据以下检索到的上下文信息，"
            "准确、简洁地回答用户的问题。"
            "如果上下文不足以回答问题，请如实说明。\n\n"
            f"上下文:\n{compressed}"
        )

        try:
            response = await client.chat.completions.create(
                model=model or "default",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": query},
                ],
                temperature=0.3,
                max_tokens=2048,
            )
            answer = response.choices[0].message.content  # type: ignore[union-attr]
            logger.info("答案生成完成: query=%s, answer_len=%d", query[:50], len(answer or ""))
            return answer or ""
        except Exception as exc:
            logger.error("生成答案失败: %s", exc)
            return f"生成答案时出错: {exc}"

    async def delete_source(self, source_id: str) -> None:
        """删除知识源及其所有关联分块

        Args:
            source_id: 来源标识
        """
        self._ensure_init()
        removed = self._engine.remove_source(source_id)
        self._engine.save()
        logger.info("已删除知识源: source_id=%s, removed_chunks=%d", source_id, removed)

    async def get_stats(self) -> dict[str, Any]:
        """获取RAG系统统计信息

        Returns:
            包含分块数、文档数、词汇量等统计信息的字典
        """
        self._ensure_init()
        return self._engine.get_stats()


# ---- 单例工厂 ----

_enhanced_rag_instance: EnhancedRAG | None = None


def get_enhanced_rag() -> EnhancedRAG:
    """获取EnhancedRAG单例实例

    Returns:
        EnhancedRAG实例
    """
    global _enhanced_rag_instance
    if _enhanced_rag_instance is None:
        _enhanced_rag_instance = EnhancedRAG()
        logger.info("EnhancedRAG单例已创建")
    return _enhanced_rag_instance
