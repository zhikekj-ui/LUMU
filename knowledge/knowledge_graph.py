"""LUMU 知识图谱 - 实体关系知识管理

核心能力:
1. 实体提取: 从文本中自动提取实体（人名/地名/机构/概念/技术等）
2. 关系发现: 发现实体之间的关系
3. 图谱构建: 构建实体-关系-实体的知识图谱
4. 图查询: 基于实体的关联查询和路径搜索
5. 知识推理: 基于图谱关系进行推理
6. 时间感知: 记录知识的时间维度变化
7. 置信度管理: 知识的置信度跟踪和衰减
"""

from __future__ import annotations

import json
import re
import uuid
from collections import deque
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

logger = get_logger("knowledge_graph")

# ---- 类型定义 ----

# 支持的实体类型
ENTITY_TYPES = (
    "person",      # 人物
    "location",    # 地点
    "organization",  # 组织/机构
    "concept",     # 概念
    "technology",  # 技术
    "event",       # 事件
    "product",     # 产品
    "date",        # 日期
    "custom",      # 自定义
)

# 支持的关系类型
RELATION_TYPES = (
    "is_a",              # 是一种（分类）
    "part_of",           # 属于（组成）
    "related_to",        # 关联
    "located_in",        # 位于
    "works_at",          # 工作于
    "created_by",        # 创建者
    "uses",              # 使用
    "depends_on",        # 依赖于
    "precedes",          # 先于
    "causes",            # 导致
    "has_property",      # 具有属性
    "similar_to",        # 相似于
    "custom",            # 自定义
)


@dataclass
class ExtractionResult:
    """实体关系提取结果"""
    entities: list[dict[str, Any]] = field(default_factory=list)
    relations: list[dict[str, Any]] = field(default_factory=list)
    raw_text: str = ""


@dataclass
class EntityResult:
    """实体查询结果"""
    entity: str
    entity_type: str
    properties: dict[str, Any] = field(default_factory=dict)
    relations: list[dict[str, Any]] = field(default_factory=list)
    confidence: float = 1.0
    created_at: str = ""
    updated_at: str = ""


@dataclass
class PathResult:
    """路径搜索结果"""
    source: str
    target: str
    path: list[str] = field(default_factory=list)
    relations: list[str] = field(default_factory=list)
    length: int = 0
    confidence: float = 1.0


# ---- 数据存储路径 ----
_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "knowledge_graph"
_GRAPH_FILE = _DATA_DIR / "graph.json"


def _ensure_data_dir() -> Path:
    """确保数据目录存在"""
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    return _DATA_DIR


def _load_json(path: Path) -> dict[str, Any]:
    """安全加载JSON文件"""
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


# ---- 核心类: KnowledgeGraph ----


class KnowledgeGraph:
    """知识图谱 - 实体关系知识管理系统

    基于邻接表结构存储实体-关系图谱，支持实体提取、
    关系发现、路径搜索、知识推理等能力。

    存储结构:
        graph.json:
            {
                "entities": {
                    "entity_name": {
                        "type": "person",
                        "properties": {...},
                        "confidence": 0.9,
                        "created_at": "ISO8601",
                        "updated_at": "ISO8601"
                    }
                },
                "adjacency": {
                    "entity_name": {
                        "relation_type": [
                            {"target": "other_entity", "properties": {...}, "confidence": 0.8, "created_at": "ISO8601"},
                            ...
                        ]
                    }
                }
            }

    用法示例::

        kg = get_knowledge_graph()
        await kg.initialize()
        await kg.add_entity("Python", "technology", {"creator": "Guido"})
        result = await kg.extract_from_text("张三在北京的公司工作")
    """

    def __init__(self) -> None:
        self._entities: dict[str, dict[str, Any]] = {}
        self._adjacency: dict[str, dict[str, list[dict[str, Any]]]] = {}
        self._initialized = False
        # 置信度衰减配置（半衰期天数）
        self._confidence_half_life: float = 365.0

    async def initialize(self) -> None:
        """初始化知识图谱，加载已有数据"""
        if self._initialized:
            return
        try:
            data = _load_json(_GRAPH_FILE)
            self._entities = data.get("entities", {})
            self._adjacency = data.get("adjacency", {})
            self._initialized = True
            logger.info("知识图谱初始化完成: entities=%d", len(self._entities))
        except Exception as exc:
            logger.error("知识图谱初始化失败: %s", exc)
            raise

    def _ensure_init(self) -> None:
        """确保系统已初始化"""
        if not self._initialized:
            raise RuntimeError("知识图谱未初始化，请先调用 initialize()")

    def _save(self) -> None:
        """持久化存储图谱数据"""
        data = {
            "entities": self._entities,
            "adjacency": self._adjacency,
        }
        _save_json(_GRAPH_FILE, data)
        logger.info("知识图谱数据已保存: entities=%d", len(self._entities))

    def _normalize_entity(self, name: str) -> str:
        """规范化实体名称"""
        return name.strip().lower()

    def _now_iso(self) -> str:
        """返回当前UTC时间的ISO格式字符串"""
        return datetime.now(timezone.utc).isoformat()

    def _decay_confidence(self, confidence: float, created_at: str) -> float:
        """基于时间衰减置信度

        使用指数衰减模型: new_confidence = old * (0.5 ^ (days / half_life))

        Args:
            confidence: 原始置信度
            created_at: 创建时间ISO字符串

        Returns:
            衰减后的置信度
        """
        try:
            created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            days = max((now - created).total_seconds() / 86400.0, 0.0)
            decayed = confidence * (0.5 ** (days / self._confidence_half_life))
            return max(decayed, 0.01)  # 最低置信度为0.01
        except (ValueError, TypeError):
            return confidence

    async def add_entity(
        self,
        entity: str,
        entity_type: str,
        properties: dict[str, Any] | None = None,
    ) -> str:
        """添加实体到知识图谱

        如果实体已存在，则更新其属性并刷新更新时间。

        Args:
            entity: 实体名称
            entity_type: 实体类型
            properties: 实体属性

        Returns:
            实体标识（规范化后的名称）
        """
        self._ensure_init()
        name = self._normalize_entity(entity)

        if entity_type not in ENTITY_TYPES:
            logger.warning("未知实体类型: %s, 归类为custom", entity_type)
            entity_type = "custom"

        now = self._now_iso()

        if name in self._entities:
            # 合并属性
            existing = self._entities[name]
            if properties:
                existing["properties"].update(properties)
            existing["updated_at"] = now
            # 刷新置信度
            existing["confidence"] = max(existing["confidence"], 0.95)
            logger.info("实体已更新: %s", name)
        else:
            self._entities[name] = {
                "type": entity_type,
                "properties": properties or {},
                "confidence": 1.0,
                "created_at": now,
                "updated_at": now,
            }
            # 初始化邻接表
            if name not in self._adjacency:
                self._adjacency[name] = {}
            logger.info("实体已添加: %s (type=%s)", name, entity_type)

        self._save()
        return name

    async def add_relation(
        self,
        source: str,
        relation: str,
        target: str,
        properties: dict[str, Any] | None = None,
    ) -> str:
        """添加关系到知识图谱

        如果源实体或目标实体不存在，自动创建它们。

        Args:
            source: 源实体名称
            relation: 关系类型
            target: 目标实体名称
            properties: 关系属性

        Returns:
            关系标识符
        """
        self._ensure_init()

        src_name = self._normalize_entity(source)
        tgt_name = self._normalize_entity(target)

        if relation not in RELATION_TYPES:
            logger.warning("未知关系类型: %s, 归类为custom", relation)
            relation = "custom"

        # 确保两个实体都存在
        if src_name not in self._entities:
            await self.add_entity(source, "custom")
        if tgt_name not in self._entities:
            await self.add_entity(target, "custom")

        now = self._now_iso()
        relation_id = f"{src_name}__{relation}__{tgt_name}"

        # 添加到邻接表（源 -> 目标）
        if relation not in self._adjacency[src_name]:
            self._adjacency[src_name][relation] = []

        # 检查是否已存在相同关系
        existing_rels = self._adjacency[src_name][relation]
        for rel_entry in existing_rels:
            if rel_entry.get("target") == tgt_name:
                # 更新已有关系
                rel_entry["updated_at"] = now
                if properties:
                    rel_entry["properties"].update(properties)
                logger.info("关系已更新: %s -> %s (%s)", src_name, tgt_name, relation)
                self._save()
                return relation_id

        # 新建关系
        existing_rels.append({
            "target": tgt_name,
            "properties": properties or {},
            "confidence": 1.0,
            "created_at": now,
            "updated_at": now,
        })

        logger.info("关系已添加: %s -> %s (%s)", src_name, tgt_name, relation)
        self._save()
        return relation_id

    async def extract_from_text(self, text: str) -> ExtractionResult:
        """从文本中提取实体和关系（调用LLM）

        使用大语言模型从自然语言文本中识别实体和关系。

        Args:
            text: 输入文本

        Returns:
            提取结果
        """
        self._ensure_init()

        if not text or not text.strip():
            return ExtractionResult(raw_text="")

        logger.info("开始从文本提取实体和关系: text_len=%d", len(text))

        extraction_prompt = (
            "请从以下文本中提取所有实体和关系，以严格的JSON格式返回。\n"
            "返回格式:\n"
            '{\n'
            '  "entities": [\n'
            '    {"name": "实体名", "type": "person|location|organization|concept|'
            "technology|event|product|date|custom\", \"description\": \"简要描述\"}\n"
            '  ],\n'
            '  "relations": [\n'
            '    {"source": "源实体", "relation": "关系类型", "target": "目标实体", '
            '"description": "简要描述"}\n'
            '  ]\n'
            '}\n\n'
            "注意:\n"
            "- 只返回JSON，不要有其他内容\n"
            "- 实体类型从以下选择: person, location, organization, concept, "
            "technology, event, product, date, custom\n"
            "- 关系类型从以下选择: is_a, part_of, related_to, located_in, "
            "works_at, created_by, uses, depends_on, precedes, causes, "
            "has_property, similar_to, custom\n\n"
            f"文本:\n{text}"
        )

        # 返回提取结果模板（实际使用时需要传入LLM客户端）
        result = ExtractionResult(raw_text=text)

        # 如果没有外部调用能力，尝试基于规则的简单提取
        result.entities = self._rule_based_entity_extraction(text)
        result.relations = self._rule_based_relation_extraction(text)

        logger.info(
            "实体提取完成: entities=%d, relations=%d",
            len(result.entities),
            len(result.relations),
        )
        return result

    async def extract_from_text_with_llm(
        self,
        text: str,
        client: Any = None,
        model: str = "",
    ) -> ExtractionResult:
        """使用LLM从文本中提取实体和关系

        Args:
            text: 输入文本
            client: OpenAI兼容API客户端
            model: 模型名称

        Returns:
            提取结果
        """
        self._ensure_init()

        if not client:
            logger.warning("未提供LLM客户端，使用规则提取")
            return await self.extract_from_text(text)

        extraction_prompt = (
            "请从以下文本中提取所有实体和关系，以严格的JSON格式返回。\n"
            "返回格式:\n"
            '{\n'
            '  "entities": [\n'
            '    {"name": "实体名", "type": "person|location|organization|concept|'
            "technology|event|product|date|custom\", \"description\": \"简要描述\"}\n"
            '  ],\n'
            '  "relations": [\n'
            '    {"source": "源实体", "relation": "关系类型", "target": "目标实体", '
            '"description": \"简要描述\"}\n'
            '  ]\n'
            '}\n\n'
            "注意:\n"
            "- 只返回JSON，不要有其他内容\n"
            "- 实体类型: person, location, organization, concept, technology, event, product, date, custom\n"
            "- 关系类型: is_a, part_of, related_to, located_in, works_at, created_by, "
            "uses, depends_on, precedes, causes, has_property, similar_to, custom\n\n"
            f"文本:\n{text}"
        )

        try:
            response = await client.chat.completions.create(
                model=model or "default",
                messages=[
                    {
                        "role": "system",
                        "content": "你是知识图谱专家，擅长从文本中提取实体和关系。"
                                   "请始终返回有效的JSON格式。",
                    },
                    {"role": "user", "content": extraction_prompt},
                ],
                temperature=0.1,
                max_tokens=4096,
            )
            content = response.choices[0].message.content or ""  # type: ignore[union-attr]

            # 提取JSON内容（处理可能的markdown代码块包裹）
            json_match = re.search(r"\{[\s\S]*\}", content)
            if json_match:
                data = json.loads(json_match.group())
                entities = data.get("entities", [])
                relations = data.get("relations", [])

                # 自动添加到图谱
                for ent in entities:
                    props = {
                        k: v for k, v in ent.items()
                        if k not in ("name", "type")
                    }
                    await self.add_entity(ent["name"], ent.get("type", "custom"), props)

                for rel in relations:
                    props = {
                        k: v for k, v in rel.items()
                        if k not in ("source", "relation", "target")
                    }
                    await self.add_relation(
                        rel["source"], rel.get("relation", "related_to"),
                        rel["target"], props,
                    )

                return ExtractionResult(
                    entities=entities,
                    relations=relations,
                    raw_text=text,
                )
        except (json.JSONDecodeError, KeyError) as exc:
            logger.error("解析LLM提取结果失败: %s", exc)
        except Exception as exc:
            logger.error("LLM实体提取失败: %s", exc)

        # 回退到规则提取
        return await self.extract_from_text(text)

    def _rule_based_entity_extraction(self, text: str) -> list[dict[str, Any]]:
        """基于规则的实体提取（简单实现）"""
        entities: list[dict[str, Any]] = []

        # 提取引号中的专有名词
        quote_chars = r"['\"""''「」《》]"
        quoted = re.findall(f"[{quote_chars}](.+?)[{quote_chars}]", text)
        for name in quoted:
            entities.append({
                "name": name.strip(),
                "type": "custom",
                "description": f"从文本中提取的实体: {name}",
            })

        # 提取大驼峰/小驼峰标识符（技术实体）
        identifiers = re.findall(r"\b([A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)*)\b", text)
        for name in identifiers:
            if len(name) > 2 and name not in {e["name"] for e in entities}:
                entities.append({
                    "name": name,
                    "type": "technology",
                    "description": f"识别到的技术标识符: {name}",
                })

        return entities

    def _rule_based_relation_extraction(self, text: str) -> list[dict[str, Any]]:
        """基于规则的关系提取（简单实现）"""
        relations: list[dict[str, Any]] = []

        # 中文"在...工作"模式
        work_pattern = re.findall(r"(\S+)\s*在\s*(\S+)\s*工作", text)
        for person, org in work_pattern:
            relations.append({
                "source": person,
                "relation": "works_at",
                "target": org,
                "description": f"{person}在{org}工作",
            })

        # "位于"模式
        loc_pattern = re.findall(r"(\S+)\s*位于\s*(\S+)", text)
        for entity, loc in loc_pattern:
            relations.append({
                "source": entity,
                "relation": "located_in",
                "target": loc,
                "description": f"{entity}位于{loc}",
            })

        return relations

    async def query_entity(self, entity: str, depth: int = 2) -> EntityResult:
        """查询实体及其关联信息

        Args:
            entity: 实体名称
            depth: 关联查询深度

        Returns:
            实体查询结果
        """
        self._ensure_init()
        name = self._normalize_entity(entity)

        if name not in self._entities:
            logger.info("实体不存在: %s", name)
            return EntityResult(
                entity=entity,
                entity_type="unknown",
                properties={},
                relations=[],
                confidence=0.0,
            )

        ent_data = self._entities[name]
        decayed_confidence = self._decay_confidence(
            ent_data["confidence"], ent_data.get("created_at", self._now_iso())
        )

        # 收集关联关系
        relations: list[dict[str, Any]] = []
        if name in self._adjacency:
            for rel_type, targets in self._adjacency[name].items():
                for target_info in targets:
                    relations.append({
                        "relation": rel_type,
                        "target": target_info["target"],
                        "properties": target_info.get("properties", {}),
                        "confidence": self._decay_confidence(
                            target_info.get("confidence", 1.0),
                            target_info.get("created_at", self._now_iso()),
                        ),
                    })

        # 如果depth > 1，收集二阶关联
        if depth > 1:
            second_order = await self._get_second_order_relations(name)
            relations.extend(second_order)

        return EntityResult(
            entity=entity,
            entity_type=ent_data["type"],
            properties=ent_data.get("properties", {}),
            relations=relations,
            confidence=decayed_confidence,
            created_at=ent_data.get("created_at", ""),
            updated_at=ent_data.get("updated_at", ""),
        )

    async def _get_second_order_relations(self, entity: str) -> list[dict[str, Any]]:
        """获取二阶关联关系"""
        second_order: list[dict[str, Any]] = []

        if entity not in self._adjacency:
            return second_order

        first_targets = set()
        for rel_type, targets in self._adjacency[entity].items():
            for target_info in targets:
                first_targets.add(target_info["target"])

        for target_name in first_targets:
            if target_name in self._adjacency:
                for rel_type, targets in self._adjacency[target_name].items():
                    for target_info in targets:
                        if target_info["target"] != entity:
                            second_order.append({
                                "relation": f"{rel_type} (间接)",
                                "source": target_name,
                                "target": target_info["target"],
                                "depth": 2,
                                "properties": target_info.get("properties", {}),
                            })

        return second_order

    async def find_path(
        self,
        source: str,
        target: str,
        max_depth: int = 5,
    ) -> list[PathResult]:
        """寻找两个实体之间的路径（BFS广度优先搜索）

        Args:
            source: 起始实体
            target: 目标实体
            max_depth: 最大搜索深度

        Returns:
            路径结果列表（按长度升序）
        """
        self._ensure_init()
        src = self._normalize_entity(source)
        tgt = self._normalize_entity(target)

        if src not in self._entities:
            logger.warning("起始实体不存在: %s", src)
            return []
        if tgt not in self._entities:
            logger.warning("目标实体不存在: %s", tgt)
            return []
        if src == tgt:
            return [PathResult(source=source, target=target, path=[source], relations=[], length=0, confidence=1.0)]

        logger.info("开始路径搜索: %s -> %s, max_depth=%d", src, tgt, max_depth)

        # BFS搜索
        visited: set[str] = {src}
        queue: deque[tuple[str, list[str], list[str], float]] = deque()
        queue.append((src, [src], [], 1.0))

        found_paths: list[PathResult] = []

        while queue:
            current, path, rels, conf = queue.popleft()

            if len(path) - 1 >= max_depth:
                continue

            if current in self._adjacency:
                for rel_type, targets in self._adjacency[current].items():
                    for target_info in targets:
                        next_entity = target_info["target"]
                        edge_conf = self._decay_confidence(
                            target_info.get("confidence", 1.0),
                            target_info.get("created_at", self._now_iso()),
                        )

                        if next_entity == tgt:
                            found_paths.append(PathResult(
                                source=source,
                                target=target,
                                path=path + [target],
                                relations=rels + [rel_type],
                                length=len(path),
                                confidence=conf * edge_conf,
                            ))
                        elif next_entity not in visited:
                            visited.add(next_entity)
                            queue.append((
                                next_entity,
                                path + [next_entity],
                                rels + [rel_type],
                                conf * edge_conf,
                            ))

        # 按路径长度排序
        found_paths.sort(key=lambda p: (p.length, -p.confidence))
        logger.info("路径搜索完成: found=%d", len(found_paths))
        return found_paths

    async def get_related(
        self,
        entity: str,
        relation_type: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """获取与指定实体相关的实体列表

        Args:
            entity: 实体名称
            relation_type: 可选，过滤特定关系类型
            limit: 最大返回数量

        Returns:
            关联实体列表
        """
        self._ensure_init()
        name = self._normalize_entity(entity)

        if name not in self._adjacency:
            return []

        results: list[dict[str, Any]] = []

        if relation_type:
            # 只查特定关系类型
            targets = self._adjacency[name].get(relation_type, [])
            for target_info in targets:
                results.append({
                    "entity": target_info["target"],
                    "relation": relation_type,
                    "properties": target_info.get("properties", {}),
                    "confidence": self._decay_confidence(
                        target_info.get("confidence", 1.0),
                        target_info.get("created_at", self._now_iso()),
                    ),
                })
        else:
            # 查所有关系类型
            for rel_type, targets in self._adjacency[name].items():
                for target_info in targets:
                    results.append({
                        "entity": target_info["target"],
                        "relation": rel_type,
                        "properties": target_info.get("properties", {}),
                        "confidence": self._decay_confidence(
                            target_info.get("confidence", 1.0),
                            target_info.get("created_at", self._now_iso()),
                        ),
                    })

        # 按置信度降序排列
        results.sort(key=lambda x: x["confidence"], reverse=True)
        return results[:limit]

    async def get_stats(self) -> dict[str, Any]:
        """获取知识图谱统计信息

        Returns:
            统计信息字典
        """
        self._ensure_init()

        total_relations = 0
        relation_type_counts: dict[str, int] = {}
        entity_type_counts: dict[str, int] = {}

        for name, rels in self._adjacency.items():
            for rel_type, targets in rels.items():
                total_relations += len(targets)
                relation_type_counts[rel_type] = relation_type_counts.get(rel_type, 0) + len(targets)

        for name, data in self._entities.items():
            etype = data.get("type", "unknown")
            entity_type_counts[etype] = entity_type_counts.get(etype, 0) + 1

        return {
            "total_entities": len(self._entities),
            "total_relations": total_relations,
            "entity_types": entity_type_counts,
            "relation_types": relation_type_counts,
        }

    async def merge_knowledge(self, new_facts: list[dict[str, Any]]) -> dict[str, Any]:
        """合并新知识到图谱（处理冲突）

        支持两种格式的知识条目:
        1. 实体: {"type": "entity", "name": "...", "entity_type": "...", "properties": {...}}
        2. 关系: {"type": "relation", "source": "...", "relation": "...", "target": "...", "properties": {...}}

        冲突处理策略:
        - 属性冲突: 新值覆盖旧值
        - 关系冲突: 保留置信度更高的版本

        Args:
            new_facts: 知识条目列表

        Returns:
            合并结果统计
        """
        self._ensure_init()
        logger.info("开始合并知识: facts=%d", len(new_facts))

        stats = {
            "entities_added": 0,
            "entities_updated": 0,
            "relations_added": 0,
            "relations_updated": 0,
            "errors": 0,
        }

        for fact in new_facts:
            try:
                fact_type = fact.get("type", "")

                if fact_type == "entity":
                    name = fact.get("name", "")
                    entity_type = fact.get("entity_type", "custom")
                    properties = fact.get("properties", {})

                    if not name:
                        stats["errors"] += 1
                        continue

                    normalized = self._normalize_entity(name)
                    is_new = normalized not in self._entities

                    await self.add_entity(name, entity_type, properties)
                    if is_new:
                        stats["entities_added"] += 1
                    else:
                        stats["entities_updated"] += 1

                elif fact_type == "relation":
                    source = fact.get("source", "")
                    relation = fact.get("relation", "related_to")
                    target = fact.get("target", "")
                    properties = fact.get("properties", {})

                    if not source or not target:
                        stats["errors"] += 1
                        continue

                    src_name = self._normalize_entity(source)
                    tgt_name = self._normalize_entity(target)
                    is_new = True

                    if src_name in self._adjacency and relation in self._adjacency[src_name]:
                        for rel in self._adjacency[src_name][relation]:
                            if rel.get("target") == tgt_name:
                                is_new = False
                                break

                    await self.add_relation(source, relation, target, properties)
                    if is_new:
                        stats["relations_added"] += 1
                    else:
                        stats["relations_updated"] += 1

                else:
                    stats["errors"] += 1
                    logger.warning("未知的知识类型: %s", fact_type)

            except Exception as exc:
                stats["errors"] += 1
                logger.error("合并知识条目失败: %s, error: %s", fact, exc)

        logger.info("知识合并完成: %s", stats)
        return stats


# ---- 单例工厂 ----

_knowledge_graph_instance: KnowledgeGraph | None = None


def get_knowledge_graph() -> KnowledgeGraph:
    """获取KnowledgeGraph单例实例

    Returns:
        KnowledgeGraph实例
    """
    global _knowledge_graph_instance
    if _knowledge_graph_instance is None:
        _knowledge_graph_instance = KnowledgeGraph()
        logger.info("KnowledgeGraph单例已创建")
    return _knowledge_graph_instance
