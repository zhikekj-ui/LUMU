"""LUMU 上下文智能系统

核心能力:
1. 意图识别: 理解用户真实意图（信息查询/任务执行/代码开发/闲聊/情感倾诉）
2. 情感分析: 分析用户情绪（积极/消极/中性/焦虑/急躁/满意）
3. 个性化适配: 根据用户画像调整回复风格
4. 上下文追踪: 理解对话上下文中的指代、省略、隐含信息
5. 话题检测: 自动识别当前话题和话题切换
6. 紧急度评估: 判断请求紧急程度
7. 多语言检测: 自动检测用户使用的语言
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
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
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False
    logger.warning("openai 包未安装，LLM 增强分析功能将不可用")


# ============================================================================
# 数据模型
# ============================================================================


class IntentType(Enum):
    """用户意图类型枚举"""
    QUERY = "query"            # 信息查询
    TASK = "task"              # 任务执行
    CODE = "code"              # 代码开发
    CHITCHAT = "chitchat"      # 闲聊
    EMOTIONAL = "emotional"    # 情感倾诉
    FEEDBACK = "feedback"      # 反馈/纠正
    CREATIVE = "creative"      # 创意/写作
    ANALYSIS = "analysis"      # 分析/推理


class EmotionType(Enum):
    """情感类型枚举"""
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"
    ANXIOUS = "anxious"
    IMPATIENT = "impatient"
    SATISFIED = "satisfied"
    CONFUSED = "confused"


@dataclass
class ContextAnalysis:
    """上下文分析结果

    Attributes:
        intent: 识别出的用户意图
        confidence: 意图识别置信度 0.0-1.0
        emotion: 识别出的情感类型
        emotion_confidence: 情感识别置信度 0.0-1.0
        language: 检测到的语言代码 ("zh", "en", "ja" etc)
        topic: 当前话题
        urgency: 紧急度 1-5
        complexity: 复杂度 1-5
        references: 指代解析结果列表
        suggestions: 建议的响应策略列表
    """
    intent: IntentType = IntentType.QUERY
    confidence: float = 0.0
    emotion: EmotionType = EmotionType.NEUTRAL
    emotion_confidence: float = 0.0
    language: str = "zh"
    topic: str = ""
    urgency: int = 1
    complexity: int = 1
    references: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典"""
        return {
            "intent": self.intent.value,
            "confidence": self.confidence,
            "emotion": self.emotion.value,
            "emotion_confidence": self.emotion_confidence,
            "language": self.language,
            "topic": self.topic,
            "urgency": self.urgency,
            "complexity": self.complexity,
            "references": self.references,
            "suggestions": self.suggestions,
        }


# ============================================================================
# 上下文智能核心
# ============================================================================


class ContextIntelligence:
    """LUMU 上下文智能系统

    提供意图识别、情感分析、语言检测、指代解析、
    紧急度评估等上下文理解能力。

    意图识别使用规则引擎（关键词匹配+启发式规则）实现基本分类，
    情感分析使用内置中英文情感词典，
    语言检测使用 Unicode 范围检测，
    同时支持通过 LLM 进行更精确的分析。

    Usage:
        ctx = get_context_intelligence()
        analysis = ctx.analyze("帮我写一个Python爬虫", conversation_history=[...])
        print(analysis.intent)  # IntentType.CODE
        print(analysis.emotion)  # EmotionType.NEUTRAL
    """

    # 意图关键词映射（按优先级排列）
    _INTENT_KEYWORDS: dict[IntentType, list[str]] = {
        IntentType.CODE: [
            "代码", "编程", "函数", "类", "API", "bug", "debug",
            "Python", "Java", "JavaScript", "TypeScript", "Go", "Rust",
            "SQL", "HTML", "CSS", "React", "Vue", "Django", "Flask",
            "FastAPI", "Spring", "算法", "数据结构", "编译",
            "爬虫", "脚本", "程序", "部署", "测试",
            "code", "programming", "function", "class", "debug",
            "algorithm", "deploy", "script", "refactor",
        ],
        IntentType.CREATIVE: [
            "写一篇", "写一个", "创作", "故事", "小说", "诗歌",
            "文案", "广告", "标题", "口号", "宣传", "设计",
            "write", "story", "poem", "creative", "design",
            "draft", "article", "blog", "essay",
        ],
        IntentType.ANALYSIS: [
            "分析", "评估", "对比", "比较", "趋势", "统计",
            "原因", "为什么", "推理", "推导", "论证",
            "风险", "可行性", "SWOT", "优缺点",
            "analyze", "evaluate", "compare", "trend", "statistics",
            "assess", "reason", "risk", "feasibility",
        ],
        IntentType.EMOTIONAL: [
            "心情", "感觉", "压力", "焦虑", "烦", "累",
            "开心", "高兴", "难过", "伤心", "孤独", "迷茫",
            "我最近", "我真的", "好烦", "好累", "受不了",
            "sad", "happy", "stressed", "anxious", "lonely",
            "depressed", "tired", "frustrated", "overwhelmed",
        ],
        IntentType.FEEDBACK: [
            "不对", "错了", "不是这样", "重新", "修改",
            "不满意", "换一个", "改一下", "调整", "修正",
            "wrong", "incorrect", "fix", "modify", "change",
            "redo", "retry", "not right", "adjust",
        ],
        IntentType.TASK: [
            "帮我", "请帮我", "麻烦", "需要", "执行",
            "操作", "完成", "处理", "发送", "创建", "删除",
            "安排", "预约", "设置", "配置", "安装",
            "help", "please", "do", "execute", "create", "delete",
            "setup", "install", "configure", "schedule",
        ],
        IntentType.CHITCHAT: [
            "你好", "嗨", "在吗", "哈哈", "谢谢", "无聊",
            "聊天", "怎么样", "最近", "天气", "笑话",
            "hello", "hi", "hey", "thanks", "bored",
            "chat", "how are you", "joke",
        ],
        IntentType.QUERY: [
            "是什么", "什么是", "怎么", "如何", "为什么",
            "哪里", "谁", "多少", "什么时候", "哪个",
            "介绍", "解释", "说明", "定义", "含义",
            "what", "how", "why", "where", "who", "when",
            "which", "explain", "define", "describe", "tell me",
        ],
    }

    # 中文积极情感词
    _ZH_POSITIVE_WORDS: set[str] = {
        "谢谢", "感谢", "开心", "高兴", "满意", "棒", "好",
        "不错", "厉害", "优秀", "完美", "赞", "喜欢", "爱",
        "希望", "期待", "成功", "进步", "舒服", "愉快",
        "有趣", "精彩", "太好了", "很好", "非常好", "真棒",
        "辛苦了", "了不起", "漂亮", "方便", "实用", "靠谱",
        "专业", "迅速", "及时", "多谢",
    }

    # 中文消极情感词
    _ZH_NEGATIVE_WORDS: set[str] = {
        "生气", "愤怒", "讨厌", "烦", "恶心", "差劲",
        "糟糕", "失败", "错误", "问题", "不行",
        "坏", "笨", "蠢", "无聊", "失望", "绝望",
        "害怕", "担心", "压力", "痛苦", "困难",
        "着急", "崩溃", "受不了", "无语", "过分",
    }

    # 中文焦虑词
    _ZH_ANXIOUS_WORDS: set[str] = {
        "焦虑", "紧张", "不安", "担心", "害怕", "恐惧",
        "压力", "着急", "慌", "忐忑", "忧虑", "恐慌",
        "睡不着", "失眠", "心慌", "烦躁", "坐立不安",
    }

    # 中文急躁词
    _ZH_IMPATIENT_WORDS: set[str] = {
        "快点", "赶紧", "马上", "立即", "等不及", "太慢",
        "催", "急", "着急", "能不能", "到底", "算了",
        "快点吧", "怎么还没", "什么时候", "别废话",
    }

    # 中文困惑词
    _ZH_CONFUSED_WORDS: set[str] = {
        "不懂", "不理解", "不明白", "困惑", "迷惑", "疑惑",
        "什么意思", "搞不懂", "不清楚", "不确定",
        "看不懂", "听不懂", "怎么说", "怎么办",
    }

    # 英文积极情感词
    _EN_POSITIVE_WORDS: set[str] = {
        "thanks", "thank", "great", "good", "nice", "excellent",
        "awesome", "wonderful", "amazing", "perfect", "love",
        "happy", "glad", "helpful", "fantastic", "brilliant",
        "impressive", "outstanding", "superb", "beautiful",
        "appreciate", "enjoy", "pleased", "satisfied",
    }

    # 英文消极情感词
    _EN_NEGATIVE_WORDS: set[str] = {
        "bad", "terrible", "horrible", "awful", "worst", "hate",
        "angry", "frustrated", "disappointed", "sad", "upset",
        "annoyed", "useless", "stupid", "broken", "wrong",
        "fail", "error", "bug", "issue", "problem",
    }

    # 英文焦虑词
    _EN_ANXIOUS_WORDS: set[str] = {
        "anxious", "worried", "nervous", "scared", "afraid",
        "stress", "stressed", "panic", "fear", "concerned",
    }

    # 英文急躁词
    _EN_IMPATIENT_WORDS: set[str] = {
        "hurry", "rush", "asap", "quick", "fast", "now",
        "immediately", "urgent", "cannot wait", "slow",
    }

    # 英文困惑词
    _EN_CONFUSED_WORDS: set[str] = {
        "confused", "don\'t understand", "unclear", "not sure",
        "puzzled", "lost", "uncertain", "huh",
    }

    # 语言检测 Unicode 范围
    _LANGUAGE_RANGES: list[tuple[str, list[tuple[int, int]]]] = [
        ("zh", [
            (0x4E00, 0x9FFF),    # CJK Unified Ideographs
            (0x3400, 0x4DBF),    # CJK Extension A
            (0x3000, 0x303F),    # CJK Symbols
            (0xFF00, 0xFFEF),    # Fullwidth Forms
        ]),
        ("ja", [
            (0x3040, 0x309F),    # Hiragana
            (0x30A0, 0x30FF),    # Katakana
        ]),
        ("ko", [
            (0xAC00, 0xD7AF),    # Hangul Syllables
            (0x1100, 0x11FF),    # Hangul Jamo
        ]),
        ("ru", [
            (0x0400, 0x04FF),    # Cyrillic
        ]),
        ("ar", [
            (0x0600, 0x06FF),    # Arabic
        ]),
        ("en", []),  # 英文通过排除法判断
    ]

    # 中文代词映射
    _ZH_PRONOUNS: dict[str, str] = {
        "你": "AI助手", "你们": "AI助手团队",
        "我": "用户", "我们": "用户方",
        "它": "前文提到的对象",
        "这个": "前文提到的内容", "那个": "前文更早提到的内容",
        "这些": "前文提到的多个内容", "那些": "前文更早提到的多个内容",
        "上面": "前文内容", "刚才": "上一轮对话的内容",
        "之前": "更早的对话内容", "上一步": "上一步操作的结果",
    }

    # 紧急度关键词
    _URGENCY_KEYWORDS: list[tuple[str, int]] = [
        ("紧急", 5), ("urgent", 5), ("immediately", 5),
        ("立即", 5), ("马上", 4), ("立刻", 5),
        ("asap", 5), ("right now", 4), ("emergency", 5),
        ("尽快", 4), ("抓紧", 4), ("hurry", 4),
        ("急", 3), ("着急", 3), ("等等我", 3),
        ("顺便", 1), ("有空", 1), ("不急", 1),
    ]

    # 话题关键词
    _TOPIC_KEYWORDS: dict[str, list[str]] = {
        "编程开发": ["代码", "编程", "Python", "Java", "bug", "API", "code"],
        "人工智能": ["AI", "机器学习", "深度学习", "GPT", "LLM", "模型"],
        "数据分析": ["数据", "统计", "可视化", "图表", "data"],
        "写作创作": ["写作", "文章", "小说", "文案", "write"],
        "日常对话": ["你好", "谢谢", "再见", "hello"],
        "技术问题": ["报错", "错误", "异常", "debug", "error"],
        "学习教育": ["学习", "课程", "考试", "作业"],
        "工作办公": ["工作", "会议", "项目", "报告"],
    }

    def __init__(self) -> None:
        """初始化上下文智能系统"""
        self._initialized: bool = False
        self._init_lock: Optional[asyncio.Lock] = None
        self._conversation_topics: dict[str, str] = {}
        self._user_profiles: dict[str, dict[str, Any]] = {}
        self._analysis_count: int = 0

    async def _ensure_initialized(self) -> None:
        """确保系统已初始化"""
        if self._initialized:
            return
        if self._init_lock is None:
            self._init_lock = asyncio.Lock()
        async with self._init_lock:
            if self._initialized:
                return
            self._initialized = True
            logger.info("上下文智能系统初始化完成")

    # ----------------------------------------------------------------
    # 完整分析入口
    # ----------------------------------------------------------------

    async def analyze(
        self,
        message: str,
        conversation_history: Optional[list[dict[str, Any]]] = None,
    ) -> ContextAnalysis:
        """完整的上下文分析

        对用户消息执行全维度的上下文分析，包括
        意图识别、情感分析、语言检测、指代解析、
        紧急度评估和话题检测。

        Args:
            message: 用户消息文本
            conversation_history: 对话历史（可选）

        Returns:
            ContextAnalysis 包含所有分析维度的结果
        """
        await self._ensure_initialized()

        analysis = ContextAnalysis()
        history = conversation_history or []

        if not message or not message.strip():
            return analysis

        message_stripped = message.strip()

        try:
            # 1. 语言检测
            analysis.language = self.detect_language(message_stripped)

            # 2. 意图识别
            intent, intent_conf = self.detect_intent(message_stripped)
            analysis.intent = intent
            analysis.confidence = intent_conf

            # 3. 情感分析
            emotion, emotion_conf = self.analyze_emotion(message_stripped)
            analysis.emotion = emotion
            analysis.emotion_confidence = emotion_conf

            # 4. 紧急度评估
            analysis.urgency = self.assess_urgency(message_stripped)

            # 5. 话题检测
            analysis.topic = self._detect_topic(message_stripped)

            # 6. 复杂度评估
            analysis.complexity = self._assess_complexity(message_stripped)

            # 7. 指代解析（需要对话历史）
            if history:
                analysis.references = self.resolve_references(
                    message_stripped, history
                )

            # 8. 生成响应策略建议
            analysis.suggestions = self.suggest_response_strategy(analysis)

            self._analysis_count += 1

            logger.debug(
                f"上下文分析完成: intent={intent.value}, "
                f"emotion={emotion.value}, lang={analysis.language}, "
                f"urgency={analysis.urgency}, topic={analysis.topic}"
            )

        except Exception as e:
            logger.error(f"上下文分析失败: {e}", exc_info=True)
            analysis.intent = IntentType.QUERY
            analysis.emotion = EmotionType.NEUTRAL
            analysis.confidence = 0.3

        return analysis

    async def analyze_with_llm(
        self,
        message: str,
        conversation_history: Optional[list[dict[str, Any]]] = None,
        client: Any = None,
        model: str = "gpt-4o-mini",
    ) -> ContextAnalysis:
        """使用 LLM 进行更精确的上下文分析

        先用规则引擎做基础分析，再可选地调用 LLM 进行修正。
        如果 client 为 None，则仅返回规则引擎的分析结果。

        Args:
            message: 用户消息
            conversation_history: 对话历史
            client: OpenAI 兼容的异步客户端（可选）
            model: 模型名称

        Returns:
            ContextAnalysis 分析结果
        """
        analysis = await self.analyze(message, conversation_history)

        if client is None or not HAS_OPENAI:
            logger.debug("未提供 LLM 客户端，使用规则引擎分析结果")
            return analysis

        try:
            history_context = ""
            if conversation_history:
                for msg in conversation_history[-5:]:
                    role = msg.get("role", "unknown")
                    content = msg.get("content", "")[:200]
                    history_context += f"{role}: {content}\n"

            llm_prompt = (
                "请分析以下用户消息的上下文信息，严格按 JSON 格式回复。\n\n"
                f"用户消息: {message}\n"
            )
            if history_context:
                llm_prompt += f"\n最近对话历史:\n{history_context}\n"

            llm_prompt += (
                "\n请按以下 JSON 格式回复（不要包含其他文本）：\n"
                "{\n"
                '  "intent": "<query|task|code|chitchat|emotional|feedback|creative|analysis>",\n'
                '  "emotion": "<positive|negative|neutral|anxious|impatient|satisfied|confused>",\n'
                '  "topic": "<话题描述>",\n'
                '  "urgency": <1-5>,\n'
                '  "complexity": <1-5>,\n'
                '  "confidence": <0.0-1.0>\n'
                "}"
            )

            messages = [
                {
                    "role": "system",
                    "content": (
                        "你是一个上下文分析专家，负责分析用户消息的意图、情感和特征。"
                        "你只输出 JSON 格式的分析结果。"
                    ),
                },
                {"role": "user", "content": llm_prompt},
            ]

            response = await asyncio.wait_for(
                client.chat.completions.create(
                    model=model,
                    messages=messages,  # type: ignore[arg-type]
                    temperature=0.1,
                    max_tokens=500,
                ),
                timeout=30.0,
            )

            content = ""
            if response.choices:
                content = (response.choices[0].message.content or "").strip()

            if content:
                json_str = content.strip()
                if "```json" in json_str:
                    json_str = json_str.split("```json")[1].split("```")[0].strip()
                elif "```" in json_str:
                    json_str = json_str.split("```")[1].split("```")[0].strip()

                llm_result = json.loads(json_str)
                llm_conf = float(llm_result.get("confidence", 0.8))

                try:
                    llm_intent = IntentType(llm_result.get("intent", ""))
                    if llm_conf > analysis.confidence:
                        analysis.intent = llm_intent
                        analysis.confidence = llm_conf
                except ValueError:
                    pass

                try:
                    llm_emotion = EmotionType(llm_result.get("emotion", ""))
                    if llm_conf > analysis.emotion_confidence:
                        analysis.emotion = llm_emotion
                        analysis.emotion_confidence = llm_conf
                except ValueError:
                    pass

                if llm_result.get("topic"):
                    analysis.topic = str(llm_result["topic"])
                if llm_result.get("urgency"):
                    analysis.urgency = int(llm_result["urgency"])
                if llm_result.get("complexity"):
                    analysis.complexity = int(llm_result["complexity"])

                logger.debug("LLM 增强分析完成，已修正分析结果")

        except asyncio.TimeoutError:
            logger.warning("LLM 增强分析超时，使用规则引擎结果")
        except Exception as e:
            logger.warning(f"LLM 增强分析失败: {e}，使用规则引擎结果")

        analysis.suggestions = self.suggest_response_strategy(analysis)
        return analysis

    # ----------------------------------------------------------------
    # 意图识别
    # ----------------------------------------------------------------

    def detect_intent(self, message: str) -> tuple[IntentType, float]:
        """识别用户消息的意图

        基于关键词匹配和启发式规则实现意图分类。
        使用加权评分机制，每个匹配的关键词增加对应意图的分数。

        Args:
            message: 用户消息文本

        Returns:
            (intent, confidence) 元组
        """
        if not message or not message.strip():
            return (IntentType.QUERY, 0.1)

        message_lower = message.strip().lower()

        scores: dict[IntentType, float] = {}
        match_counts: dict[IntentType, int] = {}

        for intent, keywords in self._INTENT_KEYWORDS.items():
            score = 0.0
            matches = 0
            for keyword in keywords:
                keyword_lower = keyword.lower()
                if keyword_lower in message_lower:
                    weight = min(len(keyword_lower) / 4.0, 2.0)
                    score += weight
                    matches += 1
            scores[intent] = score
            match_counts[intent] = matches

        if not scores or max(scores.values()) == 0:
            return self._heuristic_intent(message)

        best_intent = max(scores, key=lambda k: scores[k])
        best_score = scores[best_intent]

        sorted_scores = sorted(scores.values(), reverse=True)
        if len(sorted_scores) > 1 and sorted_scores[0] > 0:
            gap_ratio = (sorted_scores[0] - sorted_scores[1]) / sorted_scores[0]
            confidence = min(0.5 + gap_ratio * 0.4 + best_score * 0.05, 0.95)
        else:
            confidence = min(0.4 + best_score * 0.1, 0.85)

        if match_counts[best_intent] >= 3:
            confidence = min(confidence + 0.1, 0.95)

        return (best_intent, round(confidence, 3))

    def _heuristic_intent(self, message: str) -> tuple[IntentType, float]:
        """启发式意图判断（当关键词匹配无效时使用）

        Args:
            message: 用户消息

        Returns:
            (intent, confidence) 元组
        """
        stripped = message.strip()
        if stripped.endswith("?") or stripped.endswith("？"):  # fullwidth question mark
            return (IntentType.QUERY, 0.5)
        if stripped.endswith("!") or stripped.endswith("！"):  # '！'
            if any(w in message for w in self._ZH_POSITIVE_WORDS | self._EN_POSITIVE_WORDS):
                return (IntentType.EMOTIONAL, 0.4)
            return (IntentType.TASK, 0.4)
        if len(stripped) < 10:
            return (IntentType.CHITCHAT, 0.3)
        return (IntentType.QUERY, 0.3)

    # ----------------------------------------------------------------
    # 情感分析
    # ----------------------------------------------------------------

    def analyze_emotion(self, message: str) -> tuple[EmotionType, float]:
        """分析用户消息中的情感

        基于内置中英文情感词典进行情感分类。
        使用加权评分机制，同时考虑情感词的密度和强度。

        Args:
            message: 用户消息文本

        Returns:
            (emotion, confidence) 元组
        """
        if not message or not message.strip():
            return (EmotionType.NEUTRAL, 0.3)

        message_lower = message.strip().lower()

        emotion_scores: dict[EmotionType, float] = {
            EmotionType.POSITIVE: 0.0,
            EmotionType.NEGATIVE: 0.0,
            EmotionType.ANXIOUS: 0.0,
            EmotionType.IMPATIENT: 0.0,
            EmotionType.CONFUSED: 0.0,
        }

        # 中文情感词匹配
        for word in self._ZH_POSITIVE_WORDS:
            if word in message:
                emotion_scores[EmotionType.POSITIVE] += 1.0
        for word in self._ZH_NEGATIVE_WORDS:
            if word in message:
                emotion_scores[EmotionType.NEGATIVE] += 1.0
        for word in self._ZH_ANXIOUS_WORDS:
            if word in message:
                emotion_scores[EmotionType.ANXIOUS] += 1.5
        for word in self._ZH_IMPATIENT_WORDS:
            if word in message:
                emotion_scores[EmotionType.IMPATIENT] += 1.5
        for word in self._ZH_CONFUSED_WORDS:
            if word in message:
                emotion_scores[EmotionType.CONFUSED] += 1.2

        # 英文情感词匹配
        for word in self._EN_POSITIVE_WORDS:
            if word in message_lower:
                emotion_scores[EmotionType.POSITIVE] += 1.0
        for word in self._EN_NEGATIVE_WORDS:
            if word in message_lower:
                emotion_scores[EmotionType.NEGATIVE] += 1.0
        for word in self._EN_ANXIOUS_WORDS:
            if word in message_lower:
                emotion_scores[EmotionType.ANXIOUS] += 1.5
        for word in self._EN_IMPATIENT_WORDS:
            if word in message_lower:
                emotion_scores[EmotionType.IMPATIENT] += 1.5
        for word in self._EN_CONFUSED_WORDS:
            if word in message_lower:
                emotion_scores[EmotionType.CONFUSED] += 1.2

        # 感叹号增强
        exclam_count = message.count("!") + message.count("！")
        if exclam_count > 0:
            for et in [EmotionType.POSITIVE, EmotionType.NEGATIVE]:
                if emotion_scores[et] > 0:
                    emotion_scores[et] += exclam_count * 0.3

        # 问号增强困惑感
        question_count = message.count("?") + message.count("？")
        if question_count > 2:
            emotion_scores[EmotionType.CONFUSED] += 0.5

        max_score = max(emotion_scores.values())

        if max_score == 0:
            return (EmotionType.NEUTRAL, 0.6)

        # 判断是否为满意情感（积极 + 任务完成暗示）
        satisfied_markers = ["谢谢", "感谢", "解决了", "搞定了", "好了", "可以了",
                            "thanks", "thank you", "solved", "resolved", "got it"]
        if any(m in message_lower for m in satisfied_markers):
            if emotion_scores[EmotionType.POSITIVE] > 0:
                emotion_scores[EmotionType.SATISFIED] = emotion_scores[EmotionType.POSITIVE] + 0.5
                max_score = max(max_score, emotion_scores[EmotionType.SATISFIED])

        best_emotion = max(emotion_scores, key=lambda k: emotion_scores[k])
        total_score = sum(emotion_scores.values())
        confidence = min(max_score / total_score * 1.2, 0.95) if total_score > 0 else 0.3

        return (best_emotion, round(confidence, 3))

    # ----------------------------------------------------------------
    # 语言检测
    # ----------------------------------------------------------------

    def detect_language(self, text: str) -> str:
        """检测文本使用的语言

        基于 Unicode 字符范围进行语言检测。
        支持中文、日文、韩文、俄文、阿拉伯文、英文等。

        Args:
            text: 输入文本

        Returns:
            语言代码字符串 ("zh", "en", "ja", "ko", "ru", "ar")
        """
        if not text or not text.strip():
            return "zh"

        # 统计各语言范围的字符数
        lang_counts: dict[str, int] = {}
        for char in text:
            code_point = ord(char)
            for lang, ranges in self._LANGUAGE_RANGES:
                if not ranges:
                    continue
                for start, end in ranges:
                    if start <= code_point <= end:
                        lang_counts[lang] = lang_counts.get(lang, 0) + 1
                        break

        # 统计英文字母数量
        en_count = sum(1 for c in text if c.isascii() and c.isalpha())
        lang_counts["en"] = lang_counts.get("en", 0) + en_count

        if not lang_counts:
            return "zh"

        # 返回字符数最多的语言
        best_lang = max(lang_counts, key=lambda k: lang_counts[k])
        return best_lang

    # ----------------------------------------------------------------
    # 指代解析
    # ----------------------------------------------------------------

    def resolve_references(
        self, message: str, history: list[dict[str, Any]]
    ) -> list[str]:
        """解析消息中的指代关系

        根据对话历史，解析用户消息中的代词和省略指代。

        Args:
            message: 当前用户消息
            history: 对话历史列表

        Returns:
            指代解析结果列表（解析出的指代内容）
        """
        references: list[str] = []
        if not history or not message:
            return references

        # 获取最近几轮的上下文内容
        recent_contexts: list[str] = []
        for msg in reversed(history[-10:]):
            content = msg.get("content", "")
            if isinstance(content, str) and content.strip():
                recent_contexts.append(content.strip())

        if not recent_contexts:
            return references

        # 检测中文代词
        for pronoun, description in self._ZH_PRONOUNS.items():
            if pronoun in message:
                # 从上下文中查找指代目标
                resolved = self._find_reference_target(
                    pronoun, description, recent_contexts
                )
                if resolved:
                    references.append(f"'{pronoun}' -> {resolved}")

        # 检测省略：如果消息很短且上一轮是提问，可能是对上一轮的回应
        if len(message.strip()) < 15 and recent_contexts:
            references.append(f"[省略] 可能指代: {recent_contexts[0][:50]}")

        return references

    @staticmethod
    def _find_reference_target(
        pronoun: str, description: str, contexts: list[str]
    ) -> str:
        """在上下文中查找指代目标

        Args:
            pronoun: 代词
            description: 代词描述
            contexts: 上下文列表（按时间倒序）

        Returns:
            解析出的指代内容
        """
        # 简单策略：取最近一个非空上下文的前100字符
        for ctx in contexts[:3]:
            if ctx and len(ctx) > 5:
                return ctx[:100] + ("..." if len(ctx) > 100 else "")
        return ""

    # ----------------------------------------------------------------
    # 紧急度评估
    # ----------------------------------------------------------------

    def assess_urgency(self, message: str) -> int:
        """评估用户请求的紧急程度

        基于关键词匹配判断紧急度，返回 1-5 的整数等级。

        Args:
            message: 用户消息

        Returns:
            1-5 的紧急度等级（5 最紧急）
        """
        if not message:
            return 1

        max_urgency = 1
        message_lower = message.lower()

        for keyword, level in self._URGENCY_KEYWORDS:
            if keyword.lower() in message_lower:
                max_urgency = max(max_urgency, level)

        return max_urgency

    # ----------------------------------------------------------------
    # 响应策略建议
    # ----------------------------------------------------------------

    def suggest_response_strategy(
        self, analysis: ContextAnalysis
    ) -> list[str]:
        """根据分析结果建议响应策略

        Args:
            analysis: 上下文分析结果

        Returns:
            建议的响应策略列表
        """
        suggestions: list[str] = []

        # 基于意图的策略
        intent_strategies: dict[IntentType, list[str]] = {
            IntentType.QUERY: ["提供准确信息", "引用可信来源", "结构化回答"],
            IntentType.TASK: ["确认任务细节", "分步骤执行", "提供进度反馈"],
            IntentType.CODE: ["提供可运行代码", "添加注释", "说明依赖"],
            IntentType.CHITCHAT: ["友好回应", "自然对话风格", "适当幽默"],
            IntentType.EMOTIONAL: ["表达共情", "温和语气", "避免说教"],
            IntentType.FEEDBACK: ["承认问题", "提供修正方案", "询问更多细节"],
            IntentType.CREATIVE: ["发挥创意", "提供多个版本", "鼓励性反馈"],
            IntentType.ANALYSIS: ["数据支撑", "多角度分析", "结论先行"],
        }

        strategies = intent_strategies.get(analysis.intent, [])
        suggestions.extend(strategies[:2])

        # 基于情感的策略调整
        if analysis.emotion == EmotionType.ANXIOUS:
            suggestions.append("语气安抚，缓解焦虑")
        elif analysis.emotion == EmotionType.IMPATIENT:
            suggestions.append("直接回答，减少铺垫")
        elif analysis.emotion == EmotionType.SATISFIED:
            suggestions.append("确认满意度，询问其他需求")
        elif analysis.emotion == EmotionType.CONFUSED:
            suggestions.append("分步解释，使用比喻")

        # 基于紧急度的策略
        if analysis.urgency >= 4:
            suggestions.append("优先处理，简洁回复")

        # 基于复杂度的策略
        if analysis.complexity >= 4:
            suggestions.append("先提供概要再展开细节")

        return suggestions[:5]  # 最多5条建议

    # ----------------------------------------------------------------
    # 内部方法
    # ----------------------------------------------------------------

    def _detect_topic(self, message: str) -> str:
        """检测当前话题

        Args:
            message: 用户消息

        Returns:
            话题描述
        """
        message_lower = message.lower()
        best_topic = "通用"
        best_score = 0

        for topic, keywords in self._TOPIC_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw.lower() in message_lower)
            if score > best_score:
                best_score = score
                best_topic = topic

        return best_topic

    @staticmethod
    def _assess_complexity(message: str) -> int:
        """评估消息复杂度

        Args:
            message: 用户消息

        Returns:
            1-5 的复杂度等级
        """
        complexity = 1

        # 长度加权
        if len(message) > 200:
            complexity += 1
        if len(message) > 500:
            complexity += 1

        # 问题数量
        question_marks = message.count("?") + message.count("？")
        if question_marks > 2:
            complexity += 1

        # 复杂词汇
        complex_words = ["分析", "比较", "设计", "架构", "优化",
                         "analyze", "compare", "design", "optimize"]
        if any(w in message for w in complex_words):
            complexity += 1

        return min(complexity, 5)


# ============================================================================
# 单例工厂
# ============================================================================

_context_intelligence_instance: Optional[ContextIntelligence] = None
_context_intelligence_lock: Optional[asyncio.Lock] = None


async def get_context_intelligence() -> ContextIntelligence:
    """获取上下文智能系统的单例实例（延迟初始化）

    确保整个应用生命周期中只存在一个 ContextIntelligence 实例。

    Returns:
        ContextIntelligence 单例实例
    """
    global _context_intelligence_instance, _context_intelligence_lock

    if _context_intelligence_instance is not None:
        return _context_intelligence_instance

    if _context_intelligence_lock is None:
        _context_intelligence_lock = asyncio.Lock()

    async with _context_intelligence_lock:
        if _context_intelligence_instance is None:
            _context_intelligence_instance = ContextIntelligence()
            await _context_intelligence_instance._ensure_initialized()
            logger.info("上下文智能系统单例已创建")

    return _context_intelligence_instance
