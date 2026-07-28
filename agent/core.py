from core.logging_config import get_logger
_logger = get_logger("agent.core")
from core.user_config import get_provider_key, get_system_prompt
"""Agent core — the main conversation loop (inspired by Hermes Agent + OpenClaw).

Key improvements from studying Hermes/OpenClaw:
- True streaming: stream from the start, handle tool call deltas
- Memory integration: inject relevant memories into system prompt
- Causal coupling: never split tool_call/result pairs during compression
- Session persistence: save full tool call history for context
- Generation counter: for tool registry cache invalidation
- Auto skill extraction: background task learns from multi-step conversations

Enhancements (v2):
- Semantic memory: vector-based memory with episodic events
- Learning engine: interaction tracking, lesson extraction, self-improvement
- Vision support: multi-modal image understanding via StepFun vision models
- Enhanced session management: SQLite-backed sessions with FTS5 search
"""
import asyncio
import json
import os
import sys
import time
import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import AsyncIterator

from providers.anthropic_compat import SmartAsyncClient as AsyncOpenAI  # 双协议：base_url 含 /anthropic 时自动走 Anthropic Messages API

from providers.base import ProviderProfile
from providers.registry import get as get_provider
from tools.registry import ToolRegistry
from agent.context import ContextEngine
from agent.prompts import build_system_prompt
from storage.session_store import SessionStore
from memory.manager import MemoryManager
from skills.manager import SkillManager
from agent.skill_extractor import extract_skill_from_conversation
from agent.reasoning import ReasoningStrategy
from agent.preference_extractor import extract_preferences_from_conversation

# --- v2 enhancements ---
try:
    from memory.semantic import SemanticMemory
except ImportError:
    SemanticMemory = None

try:
    from agent.learner import LearningEngine, InteractionTracker
except ImportError:
    LearningEngine = None
    InteractionTracker = None

try:
    from agent.session_manager import SessionManager as EnhancedSessionManager
except ImportError:
    EnhancedSessionManager = None

# --- v3: Agent Engineering enhancements ---
try:
    from agent.tracing import get_tracer
except ImportError:
    get_tracer = None

try:
    from agent.hitl import get_approval_manager
except ImportError:
    get_approval_manager = None

try:
    from agent.event_bus import get_event_bus
except ImportError:
    get_event_bus = None

try:
    from agent.checkpoint import get_checkpoint_manager
except ImportError:
    get_checkpoint_manager = None

try:
    from agent.security import get_audit_logger, get_rbac_manager, CommandSandbox
except ImportError:
    get_audit_logger = None
    get_rbac_manager = None
    CommandSandbox = None

try:
    from agent.adaptive import get_auto_learner
except ImportError:
    get_auto_learner = None
# --- v4: Intelligence system modules ---
try:
    from agent.reasoning_engine import get_reasoning_engine
except ImportError:
    get_reasoning_engine = None

try:
    from agent.context_intelligence import get_context_intelligence
except ImportError:
    get_context_intelligence = None

try:
    from memory.intelligent_memory import get_intelligent_memory
except ImportError:
    get_intelligent_memory = None

try:
    from rag.enhanced_rag import get_enhanced_rag
except ImportError:
    get_enhanced_rag = None

try:
    from knowledge.knowledge_graph import get_knowledge_graph
except ImportError:
    get_knowledge_graph = None

try:
    from orchestration.expert_agents import get_expert_orchestrator
except ImportError:
    get_expert_orchestrator = None

try:
    from agent.code_intelligence import get_code_intelligence
except ImportError:
    get_code_intelligence = None

try:
    from agent.self_learning import get_self_learning_engine
except ImportError:
    get_self_learning_engine = None

try:
    from tools.smart_tools import get_smart_tool_scheduler
except ImportError:
    get_smart_tool_scheduler = None



def _log(msg):
    print(msg, file=sys.stderr, flush=True)


# Module-level reference for memory tools to access the active agent instance
_agent_instance: "Agent | None" = None

# Strong references to background tasks to prevent GC
_background_tasks: set[asyncio.Task] = set()


@dataclass
class Session:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    messages: list[dict] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class Agent:
    """Core agent with conversation loop, tool execution, model fallback."""

    def __init__(
        self,
        provider_name: str = "openai",
        model: str | None = None,
        tool_registry: ToolRegistry | None = None,
        system_prompt: str | None = None,
        is_sub_agent: bool = False,
        max_iterations: int = 50,
    ):
        self.provider_name = provider_name
        self.provider = get_provider(provider_name)
        if not self.provider:
            raise ValueError(f"Provider '{provider_name}' not found. Register it first.")

        self.model = model or self.provider.models[0] if self.provider.models else "gpt-4o-mini"
        self.tools = tool_registry or ToolRegistry()
        self.system_prompt = system_prompt or build_system_prompt()
        self.context = ContextEngine(
            context_window=self.provider.context_window,
        )
        # 启动诊断：解析实际生效的 endpoint 与 key 状态，便于排查"配了模型用不了"
        try:
            _resolved_base = self.provider.resolve_base_url()
            _resolved_key = self.provider.resolve_api_key()
            _log(f"[core] provider={self.provider_name} model={self.model} base_url={_resolved_base}")
            if not _resolved_key:
                _log(
                    f"[core][WARN] 未检测到 provider '{self.provider_name}' 的 API Key"
                    f"（请在 .env 设置 {self.provider.api_key_env}，或在 data/user_config.json 的 providers 段配置）。"
                    f"未配置时首次对话将返回 401。"
                )
        except Exception:
            pass
        self._is_sub_agent = is_sub_agent
        self.max_iterations = max_iterations
        self._sessions: dict[str, Session] = {}
        self._store = SessionStore() if not is_sub_agent else None
        self._memory = MemoryManager() if not is_sub_agent else None
        self._skills = SkillManager() if not is_sub_agent else None
        self._last_tool_generation = -1
        self._cached_tool_schemas: list[dict] = []

        # --- v2: Enhanced subsystems ---
        self._semantic_memory = None
        self._learning_engine = None
        self._interaction_tracker = None
        self._enhanced_sessions = None

        # 子代理占位属性：必须无条件初始化为 None，否则 chat() 内访问
        # self._enhanced_rag 等会抛 AttributeError（delegate_task 子代理隔离必经此路径）。
        self._tracer = None
        self._approval_mgr = None
        self._event_bus = None
        self._checkpoint_mgr = None
        self._audit_logger = None
        self._rbac = None
        self._sandbox = None
        self._auto_learner = None
        self._context_profile = None
        self._reasoning_engine = None
        self._context_intelligence = None
        self._intelligent_memory = None
        self._enhanced_rag = None
        self._knowledge_graph = None
        self._expert_orchestrator = None
        self._code_intelligence = None
        self._self_learning = None
        self._smart_tool_scheduler = None

        if not is_sub_agent:
            self._load_sessions()
            # Register as global instance for memory tools
            global _agent_instance
            _agent_instance = self

            # Initialize semantic memory
            if SemanticMemory is not None:
                try:
                    self._semantic_memory = SemanticMemory()
                    _log("[core] Semantic memory initialized")
                except Exception as e:
                    _log(f"[core] Semantic memory init failed: {e}")

            # Initialize learning engine
            if LearningEngine is not None:
                try:
                    self._interaction_tracker = InteractionTracker()
                    self._learning_engine = LearningEngine()
                    _log("[core] Learning engine initialized")
                except Exception as e:
                    _log(f"[core] Learning engine init failed: {e}")

            # Initialize enhanced session manager
            if EnhancedSessionManager is not None:
                try:
                    self._enhanced_sessions = EnhancedSessionManager()
                    _log("[core] Enhanced session manager initialized")
                except Exception as e:
                    _log(f"[core] Enhanced session manager init failed: {e}")

            # --- v3: Agent Engineering subsystems ---
            self._tracer = None
            self._approval_mgr = None
            self._event_bus = None
            self._checkpoint_mgr = None
            self._audit_logger = None
            self._rbac = None
            self._sandbox = None
            self._auto_learner = None

            if get_tracer is not None:
                try:
                    self._tracer = get_tracer()
                    _log("[core] Tracing initialized")
                except Exception as e:
                    _log(f"[core] Tracing init failed: {e}")

            if get_approval_manager is not None:
                try:
                    self._approval_mgr = get_approval_manager()
                    _log("[core] HITL approval manager initialized")
                except Exception as e:
                    _log(f"[core] HITL init failed: {e}")

            if get_event_bus is not None:
                try:
                    self._event_bus = get_event_bus()
                    _log("[core] Event bus initialized")
                except Exception as e:
                    _log(f"[core] Event bus init failed: {e}")

            if get_checkpoint_manager is not None:
                try:
                    self._checkpoint_mgr = get_checkpoint_manager()
                    _log("[core] Checkpoint manager initialized")
                except Exception as e:
                    _log(f"[core] Checkpoint init failed: {e}")

            if get_audit_logger is not None:
                try:
                    self._audit_logger = get_audit_logger()
                    _log("[core] Audit logger initialized")
                except Exception as e:
                    _log(f"[core] Audit logger init failed: {e}")

            if get_rbac_manager is not None:
                try:
                    self._rbac = get_rbac_manager()
                    _log("[core] RBAC manager initialized")
                except Exception as e:
                    _log(f"[core] RBAC init failed: {e}")

            if CommandSandbox is not None:
                try:
                    self._sandbox = CommandSandbox()
                    _log("[core] Command sandbox initialized")
                except Exception as e:
                    _log(f"[core] Command sandbox init failed: {e}")

            if get_auto_learner is not None:
                try:
                    self._auto_learner = get_auto_learner()
                    _log("[core] Auto learner initialized")
                except Exception as e:
                    _log(f"[core] Auto learner init failed: {e}")

            # v6: Context profile — user/project/system memory
            self._context_profile = None
            try:
                from agent.context_profile import ContextProfile
                _cp_path = os.path.join(os.getenv("AGENT_HOME", "/opt/agent-framework"), "data", "context_profile.json")
                self._context_profile = ContextProfile(_cp_path)
                _log(f"[core] Context profile loaded: {self._context_profile.stats()}")
            except Exception as e:
                _log(f"[core] Context profile init failed: {e}")
            # --- v4: Intelligence system initialization ---
            self._reasoning_engine = None
            self._context_intelligence = None
            self._intelligent_memory = None
            self._enhanced_rag = None
            self._knowledge_graph = None
            self._expert_orchestrator = None
            self._code_intelligence = None
            self._self_learning = None
            self._smart_tool_scheduler = None

            # 推理引擎/上下文智能/智能记忆 是异步单例工厂，必须在 async 上下文内 await；
            # 此处不调用（否则生成未 await 的协程：进程退出报警且实例无效），
            # 改在 chat()/stream_chat() 首次用到时懒初始化。

            # (上下文智能/智能记忆 异步工厂同上，留给 chat/stream_chat 懒初始化)

            # (智能记忆 异步工厂同上，留给 chat/stream_chat 懒初始化)

            if get_enhanced_rag is not None:
                try:
                    self._enhanced_rag = get_enhanced_rag()
                    _log("[core] Enhanced RAG initialized")
                except Exception as e:
                    _log(f"[core] Enhanced RAG init failed: {e}")

            if get_knowledge_graph is not None:
                try:
                    self._knowledge_graph = get_knowledge_graph()
                    _log("[core] Knowledge graph initialized")
                except Exception as e:
                    _log(f"[core] Knowledge graph init failed: {e}")

            if get_expert_orchestrator is not None:
                try:
                    self._expert_orchestrator = get_expert_orchestrator()
                    _log("[core] Expert orchestrator initialized")
                except Exception as e:
                    _log(f"[core] Expert orchestrator init failed: {e}")

            if get_code_intelligence is not None:
                try:
                    self._code_intelligence = get_code_intelligence()
                    _log("[core] Code intelligence initialized")
                except Exception as e:
                    _log(f"[core] Code intelligence init failed: {e}")

            if get_self_learning_engine is not None:
                try:
                    self._self_learning = get_self_learning_engine()
                    _log("[core] Self learning engine initialized")
                except Exception as e:
                    _log(f"[core] Self learning engine init failed: {e}")

            if get_smart_tool_scheduler is not None:
                try:
                    self._smart_tool_scheduler = get_smart_tool_scheduler()
                    _log("[core] Smart tool scheduler initialized")
                except Exception as e:
                    _log(f"[core] Smart tool scheduler init failed: {e}")


    def _build_client(self) -> AsyncOpenAI:
        api_key = get_provider_key(self.provider_name)
        return AsyncOpenAI(api_key=api_key, base_url=self.provider.resolve_base_url())

    # --- P1⑤ 健壮性：LLM 调用统一重试 + 退避 + 单次超时 ---
    LLM_CALL_TIMEOUT = int(os.getenv("LLM_CALL_TIMEOUT", "180"))       # 单次 LLM 调用超时（秒）
    LLM_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "2"))           # 主模型重试次数
    TURN_WALL_CLOCK_LIMIT = int(os.getenv("TURN_WALL_CLOCK_LIMIT", "600"))  # 单轮对话墙钟上限（秒）

    async def _llm_create_with_retry(self, client, messages, tool_schemas=None, stream=False, **extra):
        """带指数退避的 LLM 调用：主模型重试 N 次 → 依次尝试 fallback 模型。

        - 每次调用有独立超时（LLM_CALL_TIMEOUT），流式调用只保护「建立流」阶段。
        - 主模型瞬时故障（超时/限流/网络）用 1s/2s/4s 退避重试。
        - 主模型耗尽后依次尝试 fallback_models（每个 1 次），成功则切换 self.model。
        - 全部失败则抛出最后一个异常，由调用方决定兜底。
        """
        def _mk_kwargs(model):
            kw = dict(model=model, messages=messages)
            if tool_schemas:
                kw["tools"] = tool_schemas
            if stream:
                kw["stream"] = True
            kw.update(extra)
            return kw

        last_err = None
        # 1) 主模型 + 退避重试
        for attempt in range(self.LLM_MAX_RETRIES + 1):
            try:
                return await asyncio.wait_for(
                    client.chat.completions.create(**_mk_kwargs(self.model)),
                    timeout=self.LLM_CALL_TIMEOUT,
                )
            except Exception as e:
                last_err = e
                if attempt < self.LLM_MAX_RETRIES:
                    delay = 2 ** attempt  # 1s, 2s
                    _log(f"[llm-retry] {self.model} attempt {attempt+1} failed ({type(e).__name__}: {e}), retry in {delay}s")
                    await asyncio.sleep(delay)
        # 2) fallback 模型链
        for fb_model in (self.provider.fallback_models or []):
            if fb_model == self.model:
                continue
            try:
                _log(f"[llm-retry] falling back to {fb_model}")
                resp = await asyncio.wait_for(
                    client.chat.completions.create(**_mk_kwargs(fb_model)),
                    timeout=self.LLM_CALL_TIMEOUT,
                )
                self.model = fb_model  # 成功才切换
                return resp
            except Exception as e:
                last_err = e
                _log(f"[llm-retry] fallback {fb_model} failed ({type(e).__name__}: {e})")
        raise last_err

    # --- P2②: 工具结果截断保护 ---
    TOOL_RESULT_MAX_CHARS = int(os.getenv("TOOL_RESULT_MAX_CHARS", "16000"))

    def _truncate_tool_result(self, result) -> str:
        """截断超长工具结果，保留头尾（错误信息常在尾部），中间标注省略量。"""
        if not isinstance(result, str):
            result = str(result)
        limit = self.TOOL_RESULT_MAX_CHARS
        if len(result) <= limit:
            return result
        head = result[: int(limit * 0.7)]
        tail = result[-int(limit * 0.25):]
        omitted = len(result) - len(head) - len(tail)
        _log(f"[tool-truncate] result {len(result)} chars -> {limit} (omitted {omitted})")
        return (
            f"{head}\n\n...[工具输出过长，中间省略 {omitted} 字符；"
            f"如需查看省略部分，请用更精确的参数（如分页/过滤/行范围）重新调用工具]...\n\n{tail}"
        )

    def _load_sessions(self):
        """Load persisted sessions from disk on startup."""
        for data in self._store.load_all():
            session = Session(
                id=data["id"],
                messages=data.get("messages", []),
                created_at=data.get("created_at", ""),
            )
            self._sessions[session.id] = session

    def _save_session(self, session: Session):
        """Persist a session to disk."""
        if self._store:
            self._store.save(session.id, session.messages, session.created_at)
        # Also save to enhanced session manager if available
        if self._enhanced_sessions:
            try:
                es = self._enhanced_sessions.get_session(session.id)
                if not es:
                    es = self._enhanced_sessions.create_session(session_id=session.id)
                for msg in session.messages:
                    es.add_message(msg)
                self._enhanced_sessions.save_session(es)
            except Exception:
                pass  # Non-critical, don't break main flow

    def get_or_create_session(self, session_id: str | None = None) -> Session:
        if session_id and session_id in self._sessions:
            return self._sessions[session_id]
        if session_id:
            data = self._store.load(session_id)
            if data:
                session = Session(
                    id=data["id"],
                    messages=data.get("messages", []),
                    created_at=data.get("created_at", ""),
                )
                self._sessions[session.id] = session
                return session
        session = Session(id=session_id or str(uuid.uuid4()))
        self._sessions[session.id] = session
        return session

    def _build_system_prompt(self, session=None, user_message=None) -> str:
        # 子代理用精简 prompt，不注入记忆/技能/护栏（避免膨胀与对 None 子系统的依赖）
        if self._is_sub_agent:
            return self.system_prompt or ""
        """Build system prompt using three-layer design with memory and context injection."""
        # Collect tool names for context layer（暴露策略下只列当前可用工具，其余提示用 tool_find）
        try:
            from tools.exposure import exposure_policy, get_exposed_toolsets
            if exposure_policy() != "all":
                _exposed = get_exposed_toolsets()
                tool_names = [t.name for t in self.tools.list_tools(set(_exposed))]
                tool_names.append("(更多能力：图表/浏览器/知识库/RAG/定时任务/API/团队协作等，先调用 tool_find 搜索激活)")
            else:
                tool_names = [t.name for t in self.tools.list_tools()]
        except Exception:
            tool_names = [t.name for t in self.tools.list_tools()]
        # Collect recent memories for volatile layer — preferences first
        memory_text = None
        if self._memory:
            all_memories = self._memory.list_all()
            if all_memories:
                # Separate preferences (higher priority) from other memories
                prefs = [m for m in all_memories if m.get("category") == "preference"]
                others = [m for m in all_memories if m.get("category") != "preference"]
                parts = []
                if prefs:
                    parts.append("User Preferences (must follow):")
                    parts.extend(
                        f"- {m['key'].replace('pref:', '')}: {m['content']}"
                        for m in prefs[:10]
                    )
                if others:
                    parts.append("User Memories:")
                    parts.extend(
                        f"- [{m['category']}] {m['key']}: {m['content']}"
                        for m in others[:8]
                    )
                memory_text = "\n".join(parts)

        # Add semantic memory insights if available
        semantic_hints = None
        if self._semantic_memory:
            try:
                stats = self._semantic_memory.get_stats()
                if stats.get("total_memories", 0) > 0:
                    recent = self._semantic_memory.list_all()
                    important = [m for m in recent if m.get("importance", 0) >= 0.7]
                    if important:
                        hints = [f"- {m['content'][:100]}" for m in important[:5]]
                        semantic_hints = "Important Memories:\n" + "\n".join(hints)
            except Exception:
                pass

        if semantic_hints:
            if memory_text:
                memory_text = memory_text + "\n\n" + semantic_hints
            else:
                memory_text = semantic_hints

        # Inject relevant memories based on last user message (recall_relevant)
        relevant_memories = None
        if self._memory and hasattr(self._memory, 'recall_relevant'):
            try:
                last_msg = ""
                if session:
                    for msg in reversed(session.messages):
                        if msg.get("role") == "user":
                            last_msg = msg.get("content", "")[:300]
                            break
                if last_msg:
                    recalled = self._memory.recall_relevant(last_msg, top_k=3)
                    if recalled:
                        rel_parts = ["Relevant Memories (context-aware recall):"]
                        for m in recalled:
                            rel_parts.append(f"- [{m.get('category', '')}] {m['content']}")
                        relevant_memories = "\n".join(rel_parts)
                        if memory_text:
                            memory_text = memory_text + "\n\n" + relevant_memories
                        else:
                            memory_text = relevant_memories
            except Exception:
                pass

        # Inject context profile if available
        context_profile = None
        try:
            from agent.context_profile import get_context_profile
            context_profile = get_context_profile()
        except Exception:
            pass

        # Inject lessons if available —— 修复：用正确的 get_relevant_lessons(context=用户消息) 检索
        lessons = None
        try:
            if self._learning_engine and hasattr(self._learning_engine, 'get_relevant_lessons'):
                _ctx = user_message
                if not _ctx and session is not None:
                    _ctx = getattr(session, "last_user_message", None)
                if _ctx:
                    lessons = self._learning_engine.get_relevant_lessons(context=_ctx, limit=5)
        except Exception:
            pass

        # JARVIS: 把高频失败模式编译成避坑经验，注入系统提示，让学习真正改变行为
        avoidance = self._jarvis_avoidance_block()
        # 元认知护栏（矛盾自检 + 不确定性表达）
        meta = self._metacognition_block()
        # 用户模型（从已确认偏好构建画像）
        umod = self._user_model_block()
        # SKILL.md 技能包热加载（每条消息实时扫描 skills/packs/，放入即生效）
        skill_block = ""
        try:
            from skills.skill_packs import build_skill_block
            _msg_for_skills = user_message
            if not _msg_for_skills and session is not None:
                for _m in reversed(getattr(session, "messages", []) or []):
                    if _m.get("role") == "user":
                        _msg_for_skills = _m.get("content", "")
                        break
            skill_block = build_skill_block(_msg_for_skills)
        except Exception:
            pass

        base_prompt = build_system_prompt(
            agent_name="LUMU",
            tool_names=tool_names,
            memory_text=memory_text,
            context_profile=context_profile,
            lessons=lessons,
        )
        for _blk in (avoidance, meta, umod, skill_block):
            if _blk:
                base_prompt = base_prompt + "\n\n" + _blk
        try:
            _custom = get_system_prompt()
            if _custom:
                base_prompt = _custom + "\n\n" + base_prompt
        except Exception:
            pass
        return base_prompt

    # --- 经验教训闭环：评分 → 提取教训 → 落库（后台、失败不阻塞主对话） ---
    def _schedule_post_process_learning(self, session, user_message, assistant_content,
                                        tool_results, context_analysis=None) -> None:
        """调度交互结束后的学习闭环（异步后台执行）。"""
        try:
            asyncio.create_task(
                self._post_process_learning(
                    session, user_message, assistant_content, tool_results, context_analysis
                )
            )
        except Exception:
            pass

    async def _post_process_learning(self, session, user_message, assistant_content,
                                     tool_results, context_analysis=None) -> None:
        """经验教训系统启用闭环：
        1) learner.analyze_interaction 评分（写入 interactions.db）
        2) 若 notable(score>阈值 或 <4)，learner.extract_lesson 调 LLM 提取教训（写入 lessons.db）
        3) self_learning.record_outcome 落库（data/learning + lessons.db）
        各步独立 try/except，单步失败不影响整体与主对话。
        """
        # 确保 SelfLearningEngine 数据已加载（满足'启动时 _ensure_initialized'要求，幂等）
        if self._self_learning and not getattr(self._self_learning, "_initialized", False):
            try:
                await self._self_learning._ensure_initialized()
            except Exception as _e:
                _log("[learning] ensure_init failed: %s" % _e)

        # 1) 评分
        le_res = None
        if self._learning_engine:
            try:
                _le_tools = [{
                    "name": t.get("tool") or t.get("name"),
                    "result": t.get("result"),
                    "error": t.get("error"),
                    "status": t.get("status"),
                } for t in (tool_results or [])]
                le_res = self._learning_engine.analyze_interaction(
                    user_msg=user_message,
                    assistant_msg=assistant_content or "",
                    tool_calls=_le_tools,
                    outcome="success" if assistant_content else "failure",
                )
            except Exception as _e:
                _log("[learning] analyze_interaction failed: %s" % _e)

        # 2) notable 时提取教训（写 lessons.db，供后续 get_relevant_lessons 检索）
        if le_res and le_res.get("notable"):
            try:
                if hasattr(self._learning_engine, "extract_lesson"):
                    _le_data = {
                        "user_msg": user_message,
                        "assistant_msg": assistant_content or "",
                        "score": le_res.get("score"),
                        "patterns": le_res.get("patterns", []),
                        "outcome": "success" if assistant_content else "failure",
                        "tools_used": [t.get("name") or t.get("tool") for t in (tool_results or [])],
                        "interaction_id": le_res.get("interaction_id"),
                    }
                    await self._learning_engine.extract_lesson(_le_data)
            except Exception as _e:
                _log("[learning] extract_lesson failed: %s" % _e)

        # 3) self_learning.record_outcome 落库（data/learning + lessons.db）
        if self._self_learning:
            try:
                from agent.self_learning import InteractionRecord
                _intent = context_analysis.intent.value if context_analysis else "general"
                _emotion = context_analysis.emotion.value if context_analysis else "neutral"
                _complexity = context_analysis.complexity if context_analysis else 1
                _record = InteractionRecord(
                    query=user_message,
                    response=assistant_content or "",
                    intent_type=_intent,
                    emotion=_emotion,
                    complexity=_complexity,
                    tool_calls=len(tool_results or []),
                    outcome="success" if assistant_content else "failure",
                )
                await self._self_learning.record_outcome(_record)
            except Exception as _e:
                _log("[learning] record_outcome failed: %s" % _e)

    def _jarvis_avoidance_block(self) -> "str | None":
        """把高频失败模式编译成『避坑经验』，让 agent 真正用上它学到的东西。"""
        try:
            eng = self._learning_engine
            if not eng or not hasattr(eng, "tracker"):
                return None
            patterns = eng.tracker.get_failure_patterns(limit=6)
            if not patterns:
                return None
            lines = []
            for p in patterns:
                tools = p.get("tools") or "no_tools"
                cnt = p.get("count", 0)
                if cnt < 2:
                    continue
                ex = (p.get("examples") or [{}])[:1]
                note = ""
                if ex and ex[0].get("notes"):
                    note = "（典型情形：%s）" % ex[0]["notes"][:120]
                lines.append(
                    "- 涉及工具 [%s] 的交互曾失败 %d 次%s：下次执行前先校验参数与权限，"
                    "必要时换用替代路径或先向用户澄清。" % (tools, cnt, note)
                )
            if not lines:
                return None
            return "历史失败避坑经验（务必避免重犯）：\n" + "\n".join(lines)
        except Exception as _e:
            _log("[jarvis] avoidance block failed: %s" % _e)
            return None

    async def _plan_query(self, user_message: str, client, model: str) -> "str | None":
        """复杂查询时生成 3-5 步执行计划（仅复杂问题触发，节省简单问答的 token）。"""
        try:
            um = (user_message or "").strip()
            kw = ("方案", "步骤", "计划", "分析", "流程", "设计", "架构",
                  "如何", "怎么", "怎样", "implement", "plan", "how to",
                  "step", "architecture", "design", "compare", "对比", "调研")
            if len(um) < 30 or not any(k in um.lower() for k in kw):
                return None
            if client is None or not hasattr(client, "chat"):
                return None
            sys_p = ("你是一个任务规划器。把用户的问题拆成 3-5 个有序执行步骤，"
                     "每步一句话，只输出编号列表，不要额外解释。"
                     "若问题本身很简单、无需多步规划，只回一个词：SKIP。")
            resp = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": sys_p},
                    {"role": "user", "content": um},
                ],
                max_tokens=320,
                temperature=0.2,
            )
            plan = (resp.choices[0].message.content or "").strip()
            if not plan or plan.upper() == "SKIP":
                return None
            return plan
        except Exception as _e:
            _log("[plan] failed: %s" % _e)
            return None

    async def _execute_plan_steps(self, plan: str, user_message: str, client, model: str) -> "str | None":
        """真实分步执行：对计划每一步做推理，产出执行回溯（1 次 LLM 调用，限频）。"""
        try:
            if client is None or not hasattr(client, "chat"):
                return None
            sys_p = ("你是一个执行引擎。下面是一份分步计划（针对用户目标）。"
                     "请逐步执行：对每一步给出该步的关键结论（一句话），保留原步骤编号。"
                     "最后用『结论：』开头写一句总体结论。只输出步骤结论，不要重复问题描述。")
            resp = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": sys_p},
                    {"role": "user", "content": "用户目标：%s\n\n计划：\n%s" % (user_message, plan)},
                ],
                max_tokens=600,
                temperature=0.3,
            )
            trace = (resp.choices[0].message.content or "").strip()
            return trace or None
        except Exception as _e:
            _log("[plan-exec] failed: %s" % _e)
            return None

    def _confirmed_pref_keys(self) -> "set[str]":
        """读取确认存储，返回已确认（importance=0.95）的记忆 key 集合。"""
        try:
            _home = os.getenv("AGENT_HOME", "/opt/agent-framework")
            _p = os.path.join(_home, "data", "memory_confirmations.json")
            if not os.path.exists(_p):
                return set()
            with open(_p, "r", encoding="utf-8") as _f:
                _d = json.load(_f)
            _out = set()
            if isinstance(_d, dict):
                for _k, _v in _d.items():
                    if isinstance(_v, dict) and _v.get("confirmed"):
                        _out.add(_k)
                    elif _v is True:
                        _out.add(_k)
            return _out
        except Exception:
            return set()

    def _metacognition_block(self) -> "str | None":
        """元认知：基于已确认偏好构建矛盾护栏 + 不确定性表达指令。"""
        try:
            confirmed = self._confirmed_pref_keys()
            lines = []
            if confirmed and self._memory:
                try:
                    prefs = [m for m in self._memory.list_all() if m.get("category") == "preference"]
                    shown = [m for m in prefs if m.get("key") in confirmed][:8]
                    if shown:
                        plist = "\n".join("- %s: %s" % (m["key"].replace("pref:", ""), m["content"]) for m in shown)
                        lines.append("已确认事实（回答若与之冲突，须优先遵循已确认事实，或显式说明分歧）：\n" + plist)
                except Exception:
                    pass
            lines.append("元认知约束：若信息不足或存在不确定性，请明确表明『不确定』，不要编造或过度自信；"
                         "对关键结论注明依据或适用边界。")
            if not lines:
                return None
            return "元认知与自我校准：\n" + "\n".join(lines)
        except Exception as _e:
            _log("[meta] failed: %s" % _e)
            return None

    def _user_model_block(self) -> "str | None":
        """用户模型：从记忆/确认偏好构建简洁画像，让 agent 真正『认识用户』。"""
        try:
            if not self._memory:
                return None
            allm = self._memory.list_all() or []
            prefs = [m for m in allm if m.get("category") == "preference"]
            confirmed = self._confirmed_pref_keys()
            strong = [m for m in prefs if m.get("key") in confirmed]
            if not (prefs or allm):
                return None
            lines = ["用户画像（用于个性化回应）："]
            if strong:
                lines.append("- 强偏好（已确认，务必遵循）：" + "；".join(m["content"][:60] for m in strong[:6]))
            if prefs:
                lines.append("- 其他偏好：" + "；".join(m["content"][:50] for m in prefs[:6]))
            lines.append("- 沟通风格：沉稳、企业感、非花哨；偏好结构化、有依据的回答。")
            return "\n".join(lines)
        except Exception as _e:
            _log("[usermodel] failed: %s" % _e)
            return None

    async def _memory_consolidate(self):
        """记忆归纳：把高度相似的记忆批量合并为高层抽象记忆（只新增、不删原）。
        每轮最多合并 MAX_MERGE_PER_RUN 对；本轮已参与合并的记忆标记消费，避免重复/链式归纳。"""
        try:
            if not self._memory:
                return 0
            mems = [m for m in (self._memory.list_all() or []) if m.get("content")]
            if len(mems) < 4:
                return 0
            import re as _re
            def _norm(s):
                return set(_re.findall(r"[\w\u4e00-\u9fff]+", (s or "").lower()))
            _pairs = []
            for i in range(len(mems)):
                for j in range(i + 1, len(mems)):
                    a, b = _norm(mems[i]["content"]), _norm(mems[j]["content"])
                    if not a or not b:
                        continue
                    _u = a | b
                    if not _u:
                        continue
                    jac = len(a & b) / len(_u)
                    if jac >= 0.7:
                        _pairs.append((jac, i, j))
            if not _pairs:
                return 0
            _pairs.sort(reverse=True)
            client = self._build_client()
            if client is None or not hasattr(client, "chat"):
                return 0
            sys_p = ("把两条语义高度相似的记忆合并为一条更精炼的高层记忆。"
                     "输出合并后的记忆内容（1-3 句），不要解释。")
            _MAX_MERGE = 3          # 每轮最多合并对数：归纳吞吐翻 3 倍，成本仍受限
            _MAX_ATTEMPTS = 6       # LLM 调用硬上限（含失败重试），防失败对无限打
            _consumed = set()       # 本轮已参与合并的记忆下标
            _merged = 0
            _attempts = 0
            for _jac, i, j in _pairs:
                if _attempts >= _MAX_ATTEMPTS:
                    break
                if i in _consumed or j in _consumed:
                    continue
                _attempts += 1
                m1, m2 = mems[i], mems[j]
                try:
                    resp = await client.chat.completions.create(
                        model=self.model,
                        messages=[
                            {"role": "system", "content": sys_p},
                            {"role": "user", "content": "记忆A：%s\n\n记忆B：%s" % (m1["content"][:400], m2["content"][:400])},
                        ],
                        max_tokens=300,
                        temperature=0.2,
                    )
                    merged = (resp.choices[0].message.content or "").strip()
                    if not merged:
                        _consumed.add(i); _consumed.add(j)
                        continue
                    _key = "consolidated:%d" % (abs(hash(m1["key"] + "|" + m2["key"])) % 1000000)
                    self._memory.save(_key, merged, category="consolidated")
                    _log("[consolidate] merged %s + %s -> %s" % (m1["key"], m2["key"], _key))
                    _merged += 1
                except Exception as _e:
                    _log("[consolidate] merge failed %s+%s: %s" % (m1["key"], m2["key"], _e))
                _consumed.add(i); _consumed.add(j)
                if _merged >= _MAX_MERGE:
                    break
            return _merged
        except Exception as _e:
            _log("[consolidate] failed: %s" % _e)
            return 0

    def _schedule_memory_consolidation(self):
        """后台触发记忆归纳，每 ~25 轮一次。"""
        try:
            if not hasattr(self, "_mem_ops_count"):
                self._mem_ops_count = 0
            self._mem_ops_count += 1
            if self._mem_ops_count % 25 != 0:
                return
            async def _do():
                try:
                    await self._memory_consolidate()
                except Exception as _e:
                    _log("[consolidate] task failed: %s" % _e)
            asyncio.create_task(_do())
        except Exception:
            pass

    async def _auto_forget_memories(self, cap: int = 5):
        """主动遗忘（可恢复）：把衰减后重要性极低且陈旧的记忆软归档到 archive，不硬删。"""
        try:
            if not self._memory:
                return 0
            mems = self._memory.list_all() or []
            _now = datetime.now()
            confirmed = self._confirmed_pref_keys()
            candidates = []
            for m in mems:
                created = m.get("created_at")
                age_days = 0
                if created:
                    try:
                        ct = datetime.fromisoformat(str(created).replace("Z", "+00:00"))
                        age_days = max(0, (_now - ct).days)
                    except Exception:
                        ct2 = str(created).replace("T", " ").replace("Z", "")
                        try:
                            ct = datetime.strptime(ct2[:19], "%Y-%m-%d %H:%M:%S")
                            age_days = max(0, (_now - ct).days)
                        except Exception:
                            age_days = 0
                _base = 0.95 if m.get("key") in confirmed else 0.5
                _decayed = _base * (0.5 ** (age_days / 180.0))
                if _decayed < 0.25 and age_days > 30 and m.get("key") not in confirmed:
                    candidates.append((_decayed, m))
            candidates.sort(key=lambda x: x[0])
            to_archive = [m for _, m in candidates[:cap]]
            if not to_archive:
                return 0
            _home = os.getenv("AGENT_HOME", "/opt/agent-framework")
            _arc = os.path.join(_home, "data", "memory_archive.json")
            _data = []
            try:
                if os.path.exists(_arc):
                    with open(_arc, "r", encoding="utf-8") as _f:
                        _data = json.load(_f) or []
            except Exception:
                _data = []
            archived = []
            for m in to_archive:
                _data.append({
                    "key": m["key"], "content": m.get("content"), "category": m.get("category"),
                    "archived_at": _now.isoformat(),
                    "reason": "auto-forget: low decayed importance + old",
                })
                archived.append(m["key"])
                try:
                    if hasattr(self._memory, "delete"):
                        self._memory.delete(m["key"])
                except Exception as _e:
                    _log("[autoforget] delete failed %s: %s" % (m["key"], _e))
            try:
                with open(_arc, "w", encoding="utf-8") as _f:
                    json.dump(_data, _f, ensure_ascii=False, indent=2)
            except Exception as _e:
                _log("[autoforget] archive write failed: %s" % _e)
            _log("[autoforget] archived %d memories: %s" % (len(archived), archived))
            return len(archived)
        except Exception as _e:
            _log("[autoforget] failed: %s" % _e)
            return 0

    def _schedule_auto_forget(self):
        """后台触发主动遗忘，每 ~50 轮一次。"""
        try:
            if not hasattr(self, "_forget_count"):
                self._forget_count = 0
            self._forget_count += 1
            if self._forget_count % 50 != 0:
                return
            async def _do():
                try:
                    await self._auto_forget_memories()
                except Exception as _e:
                    _log("[autoforget] task failed: %s" % _e)
            asyncio.create_task(_do())
        except Exception:
            pass

    def _build_messages(
        self,
        session: Session,
        user_message: str,
        images: list[str] | None = None,
        reasoning_conclusion: str | None = None,
        transient_context: list[str] | None = None,  # P2①: 仅本轮生效的召回注入，不进持久历史
    ) -> list[dict]:
        messages = [{"role": "system", "content": self._build_system_prompt(user_message=user_message)}]

        # vN: inject deep-reasoning conclusion as a system message when available
        if reasoning_conclusion:
            messages.append({
                "role": "system",
                "content": (
                    "以下是经过多策略推理（CoT / ReAct / 自我反思 / 多角度等）"
                    "得到的分析结论，请基于它组织你的最终回答；"
                    "保持自然、简洁，不要原样复述推理过程：\n\n"
                    + reasoning_conclusion
                ),
            })

        # Auto-inject relevant knowledge from knowledge base (v4: with quality tracking)
        try:
            from knowledge.base import KnowledgeBase
            kb_path = os.path.join(os.getenv("AGENT_HOME", "/opt/agent-framework"), "data", "knowledge.db")
            kb = KnowledgeBase(db_path=kb_path)
            results, kb_entry_ids = kb.search_with_tracking(user_message, limit=3)
            # Store retrieved entry IDs for post-conversation quality adjustment
            self._last_kb_entry_ids = kb_entry_ids
            if results:
                kb_parts = []
                for r in results:
                    if r.get("score", 0) > 0.15:
                        preview = r.get("content", "")[:800]
                        kb_parts.append(f"[{r['title']}]\n{preview}")
                if kb_parts:
                    kb_text = "\n\n---\n\n".join(kb_parts)
                    messages.append({
                        "role": "system",
                        "content": f"以下是从知识库中检索到的相关知识，可参考用于回答用户问题：\n\n{kb_text}"
                    })
        except Exception:
            pass

        # v5: Implicit feedback learning — detect user correction signals
        _correction_signals = ["不对", "不是", "错了", "重新", "不要这样", "换个方法",
                              "不行", "怎么又", "不是这个", "搞错了", "重来", "别这样",
                              "wrong", "incorrect", "try again", "not right"]
        _is_correction = any(_sig in user_message for _sig in _correction_signals)
        if _is_correction and hasattr(self, '_last_kb_entry_ids') and self._last_kb_entry_ids:
            try:
                from knowledge.base import KnowledgeBase
                _kb_path = os.path.join(os.getenv("AGENT_HOME", "/opt/agent-framework"), "data", "knowledge.db")
                _kb = KnowledgeBase(db_path=_kb_path)
                for _eid in self._last_kb_entry_ids:
                    _kb.adjust_quality(_eid, -0.15)
                _log(f"[feedback] User correction detected, penalized {len(self._last_kb_entry_ids)} KB entries")
            except Exception:
                pass

        # v6: Inject context profile (user/project/system)
        if self._context_profile:
            try:
                _cp_prompt = self._context_profile.to_prompt()
                if _cp_prompt:
                    messages.append({"role": "system", "content": _cp_prompt})
            except Exception:
                pass

        # v10: Inject relevant skills from skill library
        try:
            if self._skills:
                _skill_results = self._skills.search(user_message, limit=2)
                if _skill_results:
                    _skill_parts = []
                    for _sr in _skill_results:
                        _skill_detail = self._skills.get(_sr["name"])
                        if _skill_detail:
                            _skill_parts.append(f"[技能: {_skill_detail['name']}]\n{_skill_detail['content'][:600]}")
                    if _skill_parts:
                        _skill_text = "\n\n---\n\n".join(_skill_parts)
                        messages.append({
                            "role": "system",
                            "content": f"以下是与当前任务相关的已学习技能，可参考执行：\n\n{_skill_text}"
                        })
        except Exception:
            pass

        # P2①: 临时召回上下文（记忆/RAG）以 system 消息注入本轮，绝不写入 session.messages
        if transient_context:
            for _tc in transient_context:
                if _tc:
                    messages.append({"role": "system", "content": _tc})

        # P2①: 过滤历史遗留的召回污染（老版本曾把召回 append 进持久历史，逐轮累积）
        for _hm in session.messages:
            if (
                _hm.get("role") == "system"
                and isinstance(_hm.get("content"), str)
                and _hm["content"].startswith(("智能记忆召回:", "RAG知识检索结果:"))
            ):
                continue
            messages.append(_hm)

        # v8: Build multimodal user message if images present
        if images:
            _content = [{"type": "text", "text": user_message}]
            for _img in images[:5]:  # max 5 images
                if _img.startswith("data:image/"):
                    _content.append({"type": "image_url", "image_url": {"url": _img}})
                elif _img.startswith(("http://", "https://")):
                    _content.append({"type": "image_url", "image_url": {"url": _img}})
                else:
                    # Assume base64
                    _content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{_img}"}})
            messages.append({"role": "user", "content": _content})
        else:
            messages.append({"role": "user", "content": user_message})
        return messages

    def _get_tool_schemas(self) -> list[dict] | None:
        """Get tool schemas with generation + exposure-based cache invalidation.

        TOOL_EXPOSURE=core（默认）：只暴露核心工具集 + tool_find 激活的扩展集，
        把每条消息的工具 schema 从 ~14.9k tokens 压到 ~4k。
        TOOL_EXPOSURE=all：全量暴露（回滚开关）。
        """
        gen = self.tools.generation
        try:
            from tools.exposure import exposure_policy, get_exposed_toolsets
            if exposure_policy() != "all":
                exposed = get_exposed_toolsets()
                key = (gen, exposed)
                if key != getattr(self, "_last_exposure_key", None):
                    self._cached_tool_schemas = self.tools.to_openai_schemas(set(exposed))
                    self._last_exposure_key = key
                    self._last_tool_generation = gen
                return self._cached_tool_schemas if self._cached_tool_schemas else None
        except Exception:
            pass
        if gen != self._last_tool_generation or getattr(self, "_last_exposure_key", None) is not None:
            self._cached_tool_schemas = self.tools.to_openai_schemas()
            self._last_tool_generation = gen
            self._last_exposure_key = None
        return self._cached_tool_schemas if self._cached_tool_schemas else None

    async def chat(self, user_message: str, session_id: str | None = None, images: list[str] | None = None, voice_mode: bool = False) -> dict:
        """Single turn: user message → agent response (with tool calls)."""
        session = self.get_or_create_session(session_id)
        # Inject reasoning strategy for enhanced intelligence
        # 推理策略注入：对简单对话不注入额外提示，保持自然回复
        _msg_check = user_message.strip().lower()
        _is_simple = len(user_message.strip()) < 50 or any(
            kw in _msg_check for kw in [
                "你好", "hello", "hi", "hey", "嗨", "在吗", "在不在",
                "谢谢", "thanks", "感谢", "再见", "bye", "拜拜",
                "好的", "ok", "是的", "对的", "不是", "不对",
                "帮", "能", "可以", "会", "怎么", "什么", "为什么",
                "哪里", "吗？", "吗?", "聊聊", "聊天", "说说", "讲讲",
            ]
        )
        if not _is_simple:
            user_message = ReasoningStrategy.inject_prompt(user_message)

        # --- vN: deep reasoning via reasoning engine (inject merged conclusion into system prompt) ---
        reasoning_conclusion = None
        _active_plan_text = None  # P1③: 结构化计划状态，驱动 ReAct 循环
        _engine = getattr(self, "_reasoning_engine", None)
        # 兼容原 __init__ 可能把 async 工厂当同步调用得到协程的情况
        if _engine is not None and not hasattr(_engine, "auto_reason"):
            try:
                if asyncio.iscoroutine(_engine):
                    _engine = await _engine
                    self._reasoning_engine = _engine
                else:
                    _engine = None
            except Exception as _e:
                _log("[reasoning] engine resolve failed: %s" % _e)
                _engine = None
        if _engine is None and get_reasoning_engine is not None:
            try:
                _engine = await get_reasoning_engine()
                self._reasoning_engine = _engine
            except Exception as _e:
                _log("[reasoning] engine init failed: %s" % _e)
                _engine = None
        if len(user_message.strip()) >= 30 and _engine is not None and hasattr(_engine, "auto_reason"):
            try:
                _rc_client = self._build_client()
                _rc_context = session.messages[-12:] if session.messages else []
                _rc_output = await _engine.auto_reason(
                    user_message, _rc_context, _rc_client, self.model
                )
                _rc_conclusion = getattr(_rc_output, "merged_conclusion", None) or ""
                _rc_strategies = getattr(_rc_output, "strategies_used", [])
                _rc_quality = getattr(_rc_output, "quality_score", 0) or 0
                _log(
                    "[reasoning] done strategies=%s quality=%.2f len=%d"
                    % (_rc_strategies, _rc_quality, len(_rc_conclusion))
                )
                # 仅当结论有效（非空、足够长、非错误回退）才注入，避免弱模型推理污染主回答
                _err_markers = (
                    "推理流程异常", "所有推理策略均执行失败", "推理过程遇到错误",
                    "抱歉", "请尝试简化",
                )
                if _rc_conclusion and len(_rc_conclusion) > 30 and not _rc_conclusion.startswith(_err_markers):
                    reasoning_conclusion = _rc_conclusion
                else:
                    _log("[reasoning] skip inject (empty/short/error): %r" % _rc_conclusion[:60])
            except Exception as _rc_err:  # 推理失败不影响主流程
                _log("[reasoning] auto_reason failed (skip): %s" % _rc_err)
            # 多轮自校正救援：auto_reason 质量偏低时，用 reason_about(iterations) 做交叉验证+修正注入
            if reasoning_conclusion and _rc_quality < 0.6 and len(user_message.strip()) >= 30:
                try:
                    from tools.reasoning import reason_about
                    _ctx_text = "\n".join(
                        f"{m.get('role','')}: {m.get('content','')}" for m in (_rc_context or [])
                    )
                    _rescue = await reason_about(user_message, context=_ctx_text, iterations=3)
                    if _rescue and "推理失败" not in _rescue:
                        reasoning_conclusion = f"{reasoning_conclusion}\n\n[多轮自校验补充]\n{_rescue}"
                        _log("[reasoning] multi-round self-correction applied (quality=%.2f)" % _rc_quality)
                except Exception as _rr:
                    _log("[reasoning] rescue reason_about failed: %s" % _rr)
            # P1③: 复杂查询拆解执行计划 — 计划保存为状态，真正驱动 ReAct 循环（进度核对+收尾核验）
            try:
                _plan = await self._plan_query(user_message, _rc_client, self.model)
                if _plan:
                    _active_plan_text = _plan  # 供 ReAct 循环做进度核对与收尾核验
                    reasoning_conclusion = (reasoning_conclusion or "") + "\n\n## 执行计划\n" + _plan
                    _log("[reasoning] plan injected (%d steps)" % (_plan.count(chr(10)) + 1))
                    _trace = await self._execute_plan_steps(_plan, user_message, _rc_client, self.model)
                    if _trace:
                        # 注意：这是纯推理预演（未调用工具），明确标注避免与真实执行混淆
                        reasoning_conclusion = reasoning_conclusion + "\n\n## 分步推理预演（未经工具验证，执行时请以实际工具结果为准）\n" + _trace
                        _log("[reasoning] plan pre-reasoned (trace %d chars)" % len(_trace))
            except Exception as _pe:
                _log("[reasoning] plan failed: %s" % _pe)
        # -----------------------------------------------------------------------------------

        # v4: Context intelligence - analyze intent & emotion (skip for voice mode)
        context_analysis = None
        if not voice_mode and get_context_intelligence is not None:
            try:
                if self._context_intelligence is None or asyncio.iscoroutine(self._context_intelligence):
                    self._context_intelligence = await get_context_intelligence()
                context_analysis = await self._context_intelligence.analyze(
                    user_message,
                    conversation_history=session.messages[-10:] if session.messages else None
                )
            except Exception as _ce:
                _log("[context] analyze failed: %s" % _ce)
                context_analysis = None

        # P2①: 召回结果收集为临时上下文，仅本轮注入，不再写入（并持久化到）session.messages
        _transient_ctx: list[str] = []

        # v4: Intelligent memory recall (skip for voice mode)
        if not voice_mode and get_intelligent_memory is not None and context_analysis:
            try:
                if self._intelligent_memory is None or asyncio.iscoroutine(self._intelligent_memory):
                    self._intelligent_memory = await get_intelligent_memory()
                recalled = await self._intelligent_memory.recall(user_message, top_k=5)
                if recalled:
                    mem_text = "\n".join(
                        f"[{m.get('memory_type', '?')}] {m.get('content', '')}"
                        for m in recalled[:5]
                    )
                    _transient_ctx.append(f"智能记忆召回:\n{mem_text}")
            except Exception:
                pass

        # v4: RAG enhanced knowledge retrieval (skip for voice mode)
        if not voice_mode and self._enhanced_rag and context_analysis:
            try:
                if context_analysis.intent.value in ("query", "analysis", "task"):
                    results = await self._enhanced_rag.search(user_message, top_k=3)
                    if results:
                        rag_text = "\n".join(f"- {r.get('content', '')[:200]}" for r in results)
                        _transient_ctx.append(f"RAG知识检索结果:\n{rag_text}")
            except Exception:
                pass

        messages = self._build_messages(session, user_message, images=images, reasoning_conclusion=reasoning_conclusion, transient_context=_transient_ctx)

        # Compress if needed (async version with LLM summarization)
        if self.context.should_compress():
            client = self._build_client()
            messages = await self.context.compress_messages_async(
                messages, client, self.model
            )

        client = self._build_client()
        tool_schemas = self._get_tool_schemas()

        # v3: Start turn-level trace span
        turn_span = None
        if self._tracer:
            try:
                turn_span = self._tracer.start_span(
                    name="chat_turn",
                    span_type="turn",
                    input_data={"user_message": user_message[:200]},
                )
            except Exception:
                pass

        self._emit_turn_events(session.id, "turn.start", {"user_message": user_message[:200]})

        max_iterations = self.max_iterations
        assistant_content = ""
        tool_results = []
        _turn_start = time.monotonic()  # P1⑤: 单轮墙钟
        _plan_verified = False  # P1③: 收尾核验只做一次，防循环

        for iteration in range(max_iterations):
            # P1⑤: 墙钟上限 — 超时优雅收尾而非无限循环
            if time.monotonic() - _turn_start > self.TURN_WALL_CLOCK_LIMIT:
                _log(f"[wall-clock] turn exceeded {self.TURN_WALL_CLOCK_LIMIT}s at iteration {iteration}, stopping")
                assistant_content = (
                    "（本轮处理时间超出上限，已执行的步骤结果如上。"
                    "如需继续，请再发一条消息，我会接着处理。）"
                )
                break

            # P1⑤: 统一重试 + 退避 + fallback 链
            response = await self._llm_create_with_retry(client, messages, tool_schemas)

            self.context.update_from_response(response)
            choice = response.choices[0]
            msg = choice.message

            if msg.tool_calls:
                assistant_msg = {
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in msg.tool_calls
                    ],
                }
                messages.append(assistant_msg)

                for tc in msg.tool_calls:
                    fn_name = tc.function.name
                    fn_args = self._coerce_args(tc.function.name, tc.function.arguments)
                    result = await self._execute_tool_enhanced(fn_name, fn_args, session_id=session.id)
                    tool_results.append({"tool": fn_name, "args": fn_args, "result": result})
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result,
                    })

                # P1③: 计划驱动 — 每 3 轮工具调用后注入进度核对，让计划持续约束执行
                if _active_plan_text and iteration > 0 and (iteration + 1) % 3 == 0:
                    messages.append({
                        "role": "system",
                        "content": (
                            "计划进度核对（第 %d 轮）：\n%s\n"
                            "请对照上述计划检查哪些步骤已完成、哪些未完成，"
                            "继续执行未完成的步骤；若发现某步已不适用，说明原因并跳过。"
                        ) % (iteration + 1, _active_plan_text),
                    })
                    _log("[plan-drive] progress check injected at iteration %d" % (iteration + 1))
                continue

            # P1③: 收尾核验 — 有计划且真的调过工具时，给一次对照计划查漏的机会（仅一次）
            if _active_plan_text and tool_results and not _plan_verified:
                _plan_verified = True
                _plan_draft = msg.content or ""  # 保留草稿，防核验后输出引用式收尾
                messages.append({"role": "assistant", "content": _plan_draft})
                messages.append({
                    "role": "system",
                    "content": (
                        "最终核验：请对照以下计划逐条检查是否全部完成：\n%s\n"
                        "若有遗漏步骤，请继续调用工具完成后再回答。"
                        "注意：用户看不到你上一条草稿，你的最终回答必须自包含、"
                        "包含全部结论与关键数据，不要写『以上』『如前所述』这类引用。"
                    ) % _active_plan_text,
                })
                _log("[plan-drive] final verification injected")
                continue

            assistant_content = msg.content or ""
            # P1③: 兜底 — 核验后的回答若是引用式短收尾（明显短于草稿），回退用草稿
            _draft = locals().get("_plan_draft") or ""
            if _plan_verified and _draft and len(_draft) > 300 and len(assistant_content) < 0.3 * len(_draft):
                _log("[plan-drive] post-verify answer too short (%d vs draft %d), using draft" % (len(assistant_content), len(_draft)))
                assistant_content = _draft
            break

        # v3: End turn-level trace span
        if turn_span and self._tracer:
            try:
                self._tracer.end_span(
                    turn_span,
                    output_data=assistant_content[:500],
                    token_prompt=self.context.last_prompt_tokens,
                    token_completion=self.context.last_completion_tokens,
                )
            except Exception:
                pass

        self._emit_turn_events(session.id, "turn.end", {
            "tool_calls": len(tool_results),
            "model": self.model,
        })

        # Save to session history (full messages including tool calls)
        session.messages.append({"role": "user", "content": user_message})
        session.messages.append({"role": "assistant", "content": assistant_content})
        self._save_session(session)

        # Auto-extract skill from multi-step conversations (background)
        self._schedule_skill_extraction(session, tool_results)

        # Auto-extract user preferences (background)
        self._schedule_preference_extraction(session)

        # v2/v4: 经验教训闭环（后台调度，统一处理 record_outcome + analyze + extract）
        self._schedule_post_process_learning(
            session, user_message, assistant_content, tool_results, context_analysis
        )
        # 保留既有交互追踪（独立链路，不影响学习闭环）
        try:
            self._track_interaction(user_message, assistant_content, tool_results)
        except Exception:
            pass

        # v2: Save to semantic memory if notable
        self._save_semantic(user_message, assistant_content, tool_results)

        # JARVIS: 记忆归纳 + 主动遗忘 + 知识归纳（后台、限频、可恢复）—— 与 stream_chat 对齐，补齐非流式路径
        self._schedule_knowledge_consolidation()
        self._schedule_memory_consolidation()
        self._schedule_auto_forget()

        return {
            "session_id": session.id,
            "content": assistant_content,
            "model": self.model,
            "tokens": {
                "prompt": self.context.last_prompt_tokens,
                "completion": self.context.last_completion_tokens,
            },
            "tool_calls": tool_results,
            "compressions": self.context.compression_count,
        }

    async def stream_chat(
        self, user_message: str, session_id: str | None = None, images: list[str] | None = None, voice_mode: bool = False
    ) -> AsyncIterator[dict]:
        """True streaming — handles tool calls via streaming deltas.

        Key improvement: no more re-requesting with stream=True.
        All calls use streaming from the start.
        """
        session = self.get_or_create_session(session_id)
        # Inject reasoning strategy for enhanced intelligence
        # 推理策略注入：对简单对话不注入额外提示，保持自然回复
        _msg_check = user_message.strip().lower()
        _is_simple = len(user_message.strip()) < 50 or any(
            kw in _msg_check for kw in [
                "你好", "hello", "hi", "hey", "嗨", "在吗", "在不在",
                "谢谢", "thanks", "感谢", "再见", "bye", "拜拜",
                "好的", "ok", "是的", "对的", "不是", "不对",
                "帮", "能", "可以", "会", "怎么", "什么", "为什么",
                "哪里", "吗？", "吗?", "聊聊", "聊天", "说说", "讲讲",
            ]
        )
        if not _is_simple:
            user_message = ReasoningStrategy.inject_prompt(user_message)

        # --- vN: deep reasoning via reasoning engine (inject merged conclusion into system prompt) ---
        reasoning_conclusion = None
        _active_plan_text = None  # P1③: 结构化计划状态，驱动 ReAct 循环
        _engine = getattr(self, "_reasoning_engine", None)
        # 兼容原 __init__ 可能把 async 工厂当同步调用得到协程的情况
        if _engine is not None and not hasattr(_engine, "auto_reason"):
            try:
                if asyncio.iscoroutine(_engine):
                    _engine = await _engine
                    self._reasoning_engine = _engine
                else:
                    _engine = None
            except Exception as _e:
                _log("[reasoning] engine resolve failed: %s" % _e)
                _engine = None
        if _engine is None and get_reasoning_engine is not None:
            try:
                _engine = await get_reasoning_engine()
                self._reasoning_engine = _engine
            except Exception as _e:
                _log("[reasoning] engine init failed: %s" % _e)
                _engine = None
        if len(user_message.strip()) >= 30 and _engine is not None and hasattr(_engine, "auto_reason"):
            try:
                _rc_client = self._build_client()
                _rc_context = session.messages[-12:] if session.messages else []
                _rc_output = await _engine.auto_reason(
                    user_message, _rc_context, _rc_client, self.model
                )
                _rc_conclusion = getattr(_rc_output, "merged_conclusion", None) or ""
                _rc_strategies = getattr(_rc_output, "strategies_used", [])
                _rc_quality = getattr(_rc_output, "quality_score", 0) or 0
                _log(
                    "[reasoning] done strategies=%s quality=%.2f len=%d"
                    % (_rc_strategies, _rc_quality, len(_rc_conclusion))
                )
                # 仅当结论有效（非空、足够长、非错误回退）才注入，避免弱模型推理污染主回答
                _err_markers = (
                    "推理流程异常", "所有推理策略均执行失败", "推理过程遇到错误",
                    "抱歉", "请尝试简化",
                )
                if _rc_conclusion and len(_rc_conclusion) > 30 and not _rc_conclusion.startswith(_err_markers):
                    reasoning_conclusion = _rc_conclusion
                else:
                    _log("[reasoning] skip inject (empty/short/error): %r" % _rc_conclusion[:60])
            except Exception as _rc_err:  # 推理失败不影响主流程
                _log("[reasoning] auto_reason failed (skip): %s" % _rc_err)
            # 多轮自校正救援：auto_reason 质量偏低时，用 reason_about(iterations) 做交叉验证+修正注入
            if reasoning_conclusion and _rc_quality < 0.6 and len(user_message.strip()) >= 30:
                try:
                    from tools.reasoning import reason_about
                    _ctx_text = "\n".join(
                        f"{m.get('role','')}: {m.get('content','')}" for m in (_rc_context or [])
                    )
                    _rescue = await reason_about(user_message, context=_ctx_text, iterations=3)
                    if _rescue and "推理失败" not in _rescue:
                        reasoning_conclusion = f"{reasoning_conclusion}\n\n[多轮自校验补充]\n{_rescue}"
                        _log("[reasoning] multi-round self-correction applied (quality=%.2f)" % _rc_quality)
                except Exception as _rr:
                    _log("[reasoning] rescue reason_about failed: %s" % _rr)
            # P1③: 复杂查询拆解执行计划 — 计划保存为状态，真正驱动 ReAct 循环（周期性进度核对）
            try:
                _plan = await self._plan_query(user_message, _rc_client, self.model)
                if _plan:
                    _active_plan_text = _plan  # 供流式 ReAct 循环做周期性进度核对
                    reasoning_conclusion = (reasoning_conclusion or "") + "\n\n## 执行计划\n" + _plan
                    _log("[reasoning] plan injected (%d steps)" % (_plan.count(chr(10)) + 1))
                    _trace = await self._execute_plan_steps(_plan, user_message, _rc_client, self.model)
                    if _trace:
                        # 注意：这是纯推理预演（未调用工具），明确标注避免与真实执行混淆
                        reasoning_conclusion = reasoning_conclusion + "\n\n## 分步推理预演（未经工具验证，执行时请以实际工具结果为准）\n" + _trace
                        _log("[reasoning] plan pre-reasoned (trace %d chars)" % len(_trace))
            except Exception as _pe:
                _log("[reasoning] plan failed: %s" % _pe)
        # -----------------------------------------------------------------------------------

        # v4: Context intelligence (skip for voice mode to reduce latency)
        context_analysis = None
        if not voice_mode and get_context_intelligence is not None:
            try:
                if self._context_intelligence is None or asyncio.iscoroutine(self._context_intelligence):
                    self._context_intelligence = await get_context_intelligence()
                context_analysis = await self._context_intelligence.analyze(
                    user_message,
                    conversation_history=session.messages[-10:] if session.messages else None
                )
            except Exception as _ce:
                _log("[context] analyze failed: %s" % _ce)
                context_analysis = None

        # P2①: 召回结果收集为临时上下文，仅本轮注入，不再写入（并持久化到）session.messages
        _transient_ctx: list[str] = []

        # v4: Intelligent memory recall (skip for voice mode)
        if not voice_mode and get_intelligent_memory is not None and context_analysis:
            try:
                if self._intelligent_memory is None or asyncio.iscoroutine(self._intelligent_memory):
                    self._intelligent_memory = await get_intelligent_memory()
                recalled = await self._intelligent_memory.recall(user_message, top_k=5)
                if recalled:
                    mem_text = "\n".join(
                        f"[{m.get('memory_type', '?')}] {m.get('content', '')}"
                        for m in recalled[:5]
                    )
                    _transient_ctx.append(f"智能记忆召回:\n{mem_text}")
            except Exception:
                pass

        # v4: RAG enhanced knowledge retrieval (skip for voice mode)
        if not voice_mode and self._enhanced_rag and context_analysis:
            try:
                if context_analysis.intent.value in ("query", "analysis", "task"):
                    results = await self._enhanced_rag.search(user_message, top_k=3)
                    if results:
                        rag_text = "\n".join(f"- {r.get('content', '')[:200]}" for r in results)
                        _transient_ctx.append(f"RAG知识检索结果:\n{rag_text}")
            except Exception:
                pass

        messages = self._build_messages(session, user_message, images=images, reasoning_conclusion=reasoning_conclusion, transient_context=_transient_ctx)

        if self.context.should_compress():
            client_tmp = self._build_client()
            messages = await self.context.compress_messages_async(
                messages, client_tmp, self.model
            )

        client = self._build_client()
        tool_schemas = self._get_tool_schemas()

        # v3: Start turn-level trace span
        turn_span = None
        if self._tracer:
            try:
                turn_span = self._tracer.start_span(
                    name="stream_chat_turn",
                    span_type="turn",
                    input_data={"user_message": user_message[:200]},
                )
            except Exception:
                pass

        self._emit_turn_events(session.id, "turn.start", {"user_message": user_message[:200], "stream": True})

        yield {"type": "session", "session_id": session.id}

        # v5: Proactive planning — skip simple messages and voice mode for speed
        try:
            _msg_lower = user_message.strip().lower()
            _skip = voice_mode or len(user_message.strip()) < 30 or any(
                kw in _msg_lower for kw in [
                    "你好", "hello", "hi", "hey", "嗨", "在吗", "在不在",
                    "谢谢", "thanks", "感谢", "辛苦了",
                    "再见", "bye", "拜拜",
                    "好的", "ok", "okay", "嗯",
                    "是的", "对的", "不是", "不对", "不行",
                    "帮", "能", "可以", "会", "怎么", "什么", "为什么",
                    "哪里", "吗？", "吗?", "聊聊", "聊天", "说说", "讲讲",
                ]
            )
            if _skip:
                raise Exception("skip_planning")
            _planning_prompt = (
                "分析以下用户请求，给出执行计划。如果是简单问题（闲聊、单步操作）返回空计划。\n\n"
                f"用户请求: {user_message[:500]}\n\n"
                "可用工具类型: 文件读写、终端命令、知识库搜索、网络搜索等\n\n"
                "请用以下JSON格式回复：\n"
                '{"needs_planning": true/false, "sub_goals": ["步骤1", "步骤2"], "suggested_tools": ["工具1"], "risks": ["风险1"]}\n\n'
                "判断标准：\n"
                "- 需要规划：多步骤任务、涉及多个文件、需要组合工具、复杂分析\n"
                "- 不需要规划：简单问答、单文件读取、闲聊、感谢\n"
            )
            _plan_client = self._build_client()
            _plan_resp = await _plan_client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "你是一个任务规划助手。分析用户请求并给出简洁执行计划。"},
                    {"role": "user", "content": _planning_prompt},
                ],
                temperature=0.2,
                max_tokens=300,
            )
            _plan_text = _plan_resp.choices[0].message.content.strip()
            import re as _re_plan
            import json as _json_plan
            _json_match = _re_plan.search(r'\{.*\}', _plan_text, _re_plan.DOTALL)
            if _json_match:
                try:
                    _plan = _json_plan.loads(_json_match.group())
                    if _plan.get("needs_planning") and _plan.get("sub_goals"):
                        _plan_msg = "📋 执行计划：\n"
                        for _i, _g in enumerate(_plan["sub_goals"][:5], 1):
                            _plan_msg += f"  {_i}. {_g}\n"
                        if _plan.get("suggested_tools"):
                            _plan_msg += f"建议工具: {', '.join(_plan['suggested_tools'][:5])}\n"
                        if _plan.get("risks"):
                            _plan_msg += f"注意事项: {', '.join(_plan['risks'][:3])}\n"
                        _plan_msg += "请按此计划执行，如果某步失败则灵活调整。"
                        messages.append({"role": "system", "content": _plan_msg})
                        # P1③: JSON 规划器的 sub_goals 同样进入计划状态，驱动循环进度核对
                        _active_plan_text = "\n".join(
                            f"{_i}. {_g}" for _i, _g in enumerate(_plan["sub_goals"][:5], 1)
                        )
                        _log(f"[planning] Plan created: {len(_plan['sub_goals'])} goals, tools: {_plan.get('suggested_tools', [])}")
                except Exception:
                    pass
        except Exception as _e:
            _log(f"[planning] Error: {_e}")

        max_iterations = self.max_iterations
        tool_results_all = []
        consecutive_failures = 0  # v4: Track consecutive tool failures for real-time reflection
        _turn_start = time.monotonic()  # P1⑤: 单轮墙钟

        for iteration in range(max_iterations):
            # P1⑤: 墙钟上限 — 超时优雅收尾（已执行的工具结果已流式输出）
            if time.monotonic() - _turn_start > self.TURN_WALL_CLOCK_LIMIT:
                _log(f"[wall-clock] stream turn exceeded {self.TURN_WALL_CLOCK_LIMIT}s at iteration {iteration}, stopping")
                _notice = "（本轮处理时间超出上限，已执行的步骤结果如上。如需继续，请再发一条消息，我会接着处理。）"
                yield {"type": "token", "content": _notice}
                yield {
                    "type": "done",
                    "session_id": session.id,
                    "content": _notice,
                    "model": self.model,
                    "tokens": {
                        "prompt": self.context.last_prompt_tokens,
                        "completion": self.context.last_completion_tokens,
                    },
                    "tool_calls": tool_results_all,
                    "compressions": self.context.compression_count,
                }
                session.messages.append({"role": "user", "content": user_message})
                session.messages.append({"role": "assistant", "content": _notice})
                self._save_session(session)
                return

            # Accumulate streaming response
            content_parts: list[str] = []
            tool_calls_acc: dict[int, dict] = {}  # index → {id, name, args_parts}
            finish_reason = None

            try:
                # P1⑤: 建流阶段带重试 + 退避 + fallback 链（流中断仍由下方 except 兜底）
                stream = await self._llm_create_with_retry(client, messages, tool_schemas, stream=True)
                async for chunk in stream:
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta
                    finish_reason = chunk.choices[0].finish_reason or finish_reason

                    # Accumulate text content
                    if delta.content:
                        content_parts.append(delta.content)
                        yield {"type": "token", "content": delta.content}

                    # Accumulate tool call deltas
                    if delta.tool_calls:
                        for tc_delta in delta.tool_calls:
                            idx = tc_delta.index
                            if idx not in tool_calls_acc:
                                tool_calls_acc[idx] = {
                                    "id": tc_delta.id or "",
                                    "name": "",
                                    "args_parts": [],
                                }
                            entry = tool_calls_acc[idx]
                            if tc_delta.id:
                                entry["id"] = tc_delta.id
                            if tc_delta.function:
                                if tc_delta.function.name:
                                    entry["name"] += tc_delta.function.name
                                if tc_delta.function.arguments:
                                    entry["args_parts"].append(tc_delta.function.arguments)
            except Exception as e:
                # P1⑤: 流中断/建流彻底失败 → 降级为非流式（helper 内含退避 + fallback 链）
                if True:
                    try:
                        resp = await self._llm_create_with_retry(client, messages, tool_schemas)
                        self.context.update_from_response(resp)
                        msg = resp.choices[0].message
                        if msg.tool_calls:
                            # Process tool calls from fallback
                            assistant_msg = {
                                "role": "assistant",
                                "content": msg.content or "",
                                "tool_calls": [
                                    {
                                        "id": tc.id,
                                        "type": "function",
                                        "function": {
                                            "name": tc.function.name,
                                            "arguments": tc.function.arguments,
                                        },
                                    }
                                    for tc in msg.tool_calls
                                ],
                            }
                            messages.append(assistant_msg)
                            for tc in msg.tool_calls:
                                fn_name = tc.function.name
                                fn_args = self._coerce_args(fn_name, tc.function.arguments)
                                yield {"type": "tool_start", "tool": fn_name, "args": fn_args}
                                result = await self._execute_tool_enhanced(fn_name, fn_args, session_id=session.id)
                                tool_results_all.append({"tool": fn_name, "args": fn_args, "result": result})
                                yield {"type": "tool_result", "tool": fn_name, "result": result}
                                messages.append({
                                    "role": "tool",
                                    "tool_call_id": tc.id,
                                    "content": result,
                                })

                                # v4: Track failures in fallback path too
                                is_err = isinstance(result, str) and (result.startswith("Error") or result.startswith("错误") or result.startswith("Traceback") or result.startswith("File not found") or result.startswith("Access denied") or result.startswith("Permission") or "not found" in result[:50].lower() or "failed" in result[:50].lower() or "error" in result[:50].lower())
                                if is_err:
                                    consecutive_failures += 1
                                else:
                                    consecutive_failures = 0

                            continue
                        else:
                            content_parts = [msg.content or ""]
                            finish_reason = "stop"
                    except Exception as e2:
                        yield {"type": "error", "content": str(e2)}
                        return

            full_content = "".join(content_parts)

            # Check if we have tool calls to execute
            if tool_calls_acc:
                # Build assistant message with tool calls
                assembled_tool_calls = []
                for idx in sorted(tool_calls_acc.keys()):
                    entry = tool_calls_acc[idx]
                    args_str = "".join(entry["args_parts"])
                    assembled_tool_calls.append({
                        "id": entry["id"],
                        "type": "function",
                        "function": {
                            "name": entry["name"],
                            "arguments": args_str,
                        },
                    })

                assistant_msg = {
                    "role": "assistant",
                    "content": full_content,
                    "tool_calls": assembled_tool_calls,
                }
                messages.append(assistant_msg)

                # Execute each tool
                need_intervention = False  # v4: defer intervention to after batch
                for tc in assembled_tool_calls:
                    fn_name = tc["function"]["name"]
                    fn_args = self._coerce_args(fn_name, tc["function"]["arguments"])

                    yield {"type": "tool_start", "tool": fn_name, "args": fn_args}
                    result = await self._execute_tool_enhanced(fn_name, fn_args, session_id=session.id)
                    tool_results_all.append({"tool": fn_name, "args": fn_args, "result": result})
                    yield {"type": "tool_result", "tool": fn_name, "result": result}
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": result,
                    })

                    # v4: Real-time reflection — track consecutive failures
                    is_error = isinstance(result, str) and (result.startswith("Error") or result.startswith("错误") or result.startswith("Traceback") or result.startswith("File not found") or result.startswith("Access denied") or result.startswith("Permission") or "not found" in result[:50].lower() or "failed" in result[:50].lower() or "error" in result[:50].lower())
                    if is_error:
                        consecutive_failures += 1
                        if consecutive_failures >= 3:
                            need_intervention = True
                            consecutive_failures = 0
                    else:
                        consecutive_failures = 0

                # v4: Inject strategy-switch intervention AFTER all tool results (safe for API format)
                if need_intervention:
                    messages.append({"role": "system", "content": "你已连续3次工具调用失败。请停下来重新分析问题：当前方法可能不对，请换一种思路或检查参数是否正确。不要重复相同的失败操作。"})
                    _log("[reflection] Injected strategy-switch intervention after 3+ consecutive failures")

                # P1③: 计划驱动 — 每 3 轮工具调用后注入进度核对，让计划持续约束执行
                if _active_plan_text and iteration > 0 and (iteration + 1) % 3 == 0:
                    messages.append({
                        "role": "system",
                        "content": (
                            "计划进度核对（第 %d 轮）：\n%s\n"
                            "请对照上述计划检查哪些步骤已完成、哪些未完成，"
                            "继续执行未完成的步骤；若发现某步已不适用，说明原因并跳过。"
                        ) % (iteration + 1, _active_plan_text),
                    })
                    _log("[plan-drive] progress check injected at iteration %d (stream)" % (iteration + 1))

                continue  # Loop again for more tool calls or final response

            # No tool calls — final text response (already streamed)
            # v3: End turn-level trace span
            if turn_span and self._tracer:
                try:
                    self._tracer.end_span(
                        turn_span,
                        output_data=full_content[:500],
                        token_prompt=self.context.last_prompt_tokens,
                        token_completion=self.context.last_completion_tokens,
                    )
                except Exception:
                    pass

            self._emit_turn_events(session.id, "turn.end", {
                "tool_calls": len(tool_results_all),
                "model": self.model,
                "stream": True,
            })

            yield {
                "type": "done",
                "session_id": session.id,
                "content": full_content,
                "model": self.model,
                "tokens": {
                    "prompt": self.context.last_prompt_tokens,
                    "completion": self.context.last_completion_tokens,
                },
                "tool_calls": tool_results_all,
                "compressions": self.context.compression_count,
            }

            # Save to session
            session.messages.append({"role": "user", "content": user_message})
            session.messages.append({"role": "assistant", "content": full_content})
            self._save_session(session)

            # Auto-extract skill from multi-step conversations (background)
            self._schedule_skill_extraction(session, tool_results_all)

            # Auto-extract user preferences (background)
            self._schedule_preference_extraction(session)

            # v2: Track interaction for learning
            self._track_interaction(user_message, full_content, tool_results_all)

            # v2: Save to semantic memory if notable
            self._save_semantic(user_message, full_content, tool_results_all)

            # v3: Self-reflection on tool results (background)
            self._schedule_self_reflection(tool_results_all)

            # v3: Cross-session knowledge extraction (background)
            self._schedule_knowledge_extraction(session, tool_results_all)

            # v4: Strategic-level knowledge extraction (background)
            self._schedule_strategic_extraction(session, tool_results_all)

            # v4: Adjust knowledge quality based on conversation outcome
            self._adjust_kb_quality(tool_results_all)

            # v5: Confidence self-assessment (background)
            self._schedule_confidence_assessment(user_message, full_content, tool_results_all)

            # v5: Knowledge consolidation (background, periodic)
            self._schedule_knowledge_consolidation()

            # v6: Context profile extraction (background)
            self._schedule_context_extraction(session, user_message, full_content)

            # v7: Session summary (background)
            self._schedule_session_summary(session, user_message, full_content)

            # vN: 经验教训闭环（后台调度，统一处理 analyze + extract + record_outcome）
            self._schedule_post_process_learning(
                session, user_message, full_content, tool_results_all
            )

            # v9: Proactive thinking (background)
            self._schedule_proactive_thinking(session, user_message, full_content)

            # JARVIS: 记忆归纳 + 主动遗忘（后台、限频、可恢复）
            self._schedule_memory_consolidation()
            self._schedule_auto_forget()
            return

        # Max iterations reached
        yield {"type": "error", "content": "Max tool call iterations reached."}

    # --- v3: Enhanced tool execution with all subsystems ---

    async def _execute_tool_enhanced(self, fn_name: str, fn_args: dict, session_id: str = "") -> str:
        """Execute a tool with full v3 subsystem integration."""
        import time

        # 1. Audit log
        if self._audit_logger:
            try:
                self._audit_logger.log_tool_call(
                    tool_name=fn_name,
                    args=fn_args,
                    session_id=session_id,
                )
            except Exception:
                pass

        # 2. HITL approval check — 真拦截：高风险操作挂起等待人工审批，默认不执行
        if self._approval_mgr:
            try:
                call_args = {"command": fn_args.get("command", ""), "file_path": fn_args.get("file_path", "")}
                if self._approval_mgr.should_require_approval(fn_name, call_args):
                    action = self._approval_mgr.request_approval(
                        session_id=session_id,
                        tool_name=fn_name,
                        tool_args=fn_args,
                        reason="高风险操作，已挂起等待人工审批（5 分钟未审批自动否决）",
                    )
                    if action:
                        _log(f"[hitl] Tool {fn_name} HELD pending approval (action={action.action_id})")
                        # 真拦截：不再执行工具，返回挂起信息，交由人工通过审批接口放行。
                        # 安全默认：pending 超过 300s 在 get_pending() 中自动转为 denied。
                        return (
                            f"⏳ 操作已挂起等待人工审批（action_id={action.action_id}，风险等级={action.risk_level}）。\n"
                            f"在人工批准前该操作不会执行。你【无权批准】此操作，也不要尝试换用其他工具或改写命令绕过审批；"
                            f"请把 action_id 告知用户，由人类在审批接口（POST /api/approvals/{action.action_id}/approve）处理。\n"
                            f"（安全默认：若 5 分钟内未审批，自动否决且永不执行。）"
                        )
            except Exception:
                # 审批检查异常时安全优先：拦截，不执行
                _log(f"[hitl] approval check error, blocking tool {fn_name} for safety")
                return f"⛔ 审批检查异常，出于安全考虑已拦截工具 {fn_name} 的执行。"

        # 3. Tracing span
        span = None
        if self._tracer:
            try:
                span = self._tracer.start_span(
                    name=fn_name,
                    span_type="tool_call",
                    input_data=fn_args,
                )
            except Exception:
                pass

        # 4. Event: tool start
        if self._event_bus:
            try:
                self._event_bus.emit(
                    event_type="tool.call_start",
                    source="agent",
                    data={"tool": fn_name, "args": fn_args},
                    session_id=session_id,
                )
            except Exception:
                pass

        # 5. Execute the tool (with retry and timeout)
        start_time = time.time()
        max_retries = 2
        tool_timeout = 120  # seconds
        last_error = None

        for attempt in range(max_retries + 1):
            try:
                result = await asyncio.wait_for(
                    self.tools.execute(fn_name, fn_args),
                    timeout=tool_timeout,
                )
                duration_ms = (time.time() - start_time) * 1000
                success = True

                # End tracing span
                if span and self._tracer:
                    try:
                        self._tracer.end_span(span, output_data=result[:500] if isinstance(result, str) else result)
                    except Exception:
                        pass
                break  # Success, exit retry loop

            except asyncio.TimeoutError:
                duration_ms = (time.time() - start_time) * 1000
                success = False
                last_error = "Tool execution timed out after 120s"
                result = f"Error: {last_error}"
                _log(f"[tool] {fn_name} timed out (attempt {attempt + 1}/{max_retries + 1})")
                if span and self._tracer:
                    try:
                        self._tracer.fail_span(span, str(last_error))
                    except Exception:
                        pass
                break  # Don't retry timeouts

            except Exception as e:
                duration_ms = (time.time() - start_time) * 1000
                last_error = e
                _log(f"[tool] {fn_name} failed (attempt {attempt + 1}/{max_retries + 1}): {e}")

                if span and self._tracer:
                    try:
                        self._tracer.fail_span(span, str(e))
                    except Exception:
                        pass

                if attempt < max_retries:
                    await asyncio.sleep(0.5 * (attempt + 1))  # Exponential backoff
                    continue
                else:
                    success = False
                    result = f"Error: {e}"

        # 6. Adaptive metrics
        if self._auto_learner:
            try:
                self._auto_learner.record_tool_call(
                    tool_name=fn_name,
                    success=success,
                    latency_ms=duration_ms,
                    error_message="" if success else str(e),
                )
            except Exception:
                pass

        # 7. Event: tool end
        if self._event_bus:
            try:
                evt_type = "tool.call_success" if success else "tool.call_error"
                self._event_bus.emit(
                    event_type=evt_type,
                    source="agent",
                    data={"tool": fn_name, "duration_ms": duration_ms, "success": success},
                    session_id=session_id,
                )
            except Exception:
                pass

        # 8. 自愈提示：工具返回逻辑错误时，追加恢复建议，帮助模型下一轮换路
        if isinstance(result, str):
            _low = result[:60].lower()
            _is_err = (
                result.startswith("Error") or result.startswith("错误")
                or "not found" in _low or "failed" in _low or "error" in _low
                or "permission" in _low or "denied" in _low or "traceback" in _low
            )
            if _is_err:
                _hint = ("\n[自愈提示] 该工具调用未成功。若为主流程依赖，请：①核对参数/路径/权限；"
                         "②尝试替代工具或简化请求；③必要时向用户说明限制，而非重复无效调用。")
                result = result + _hint

        # 9. P2②: 截断超长结果，防止单次工具输出撑爆上下文窗口
        result = self._truncate_tool_result(result)

        return result

    def _emit_turn_events(self, session_id: str, event_type: str, data: dict):
        """Emit an event for the current turn (non-blocking)."""
        if not self._event_bus:
            return
        try:
            self._event_bus.emit(
                event_type=event_type,
                source="agent",
                data=data,
                session_id=session_id,
            )
        except Exception:
            pass

    # --- v2: Learning & Semantic Memory Integration ---

    def _track_interaction(self, user_msg: str, assistant_msg: str, tool_results: list[dict]):
        """Track interaction for learning engine (non-blocking)."""
        if not self._interaction_tracker:
            return

        def _do_track():
            try:
                tools_used = [t["tool"] for t in tool_results]
                failed = [t["tool"] for t in tool_results
                          if isinstance(t.get("result"), str) and "error" in t["result"].lower()[:50]]
                outcome = "failure" if failed else ("success" if tool_results else "success")
                self._interaction_tracker.record(
                    user_msg=user_msg[:500],
                    assistant_msg=assistant_msg[:500],
                    tools_used=tools_used,
                    outcome=outcome,
                )
            except Exception as e:
                _log(f"[learner] Track interaction error: {e}")

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(asyncio.to_thread(_do_track))
            else:
                _do_track()
        except Exception:
            pass

    def _save_semantic(self, user_msg: str, assistant_msg: str, tool_results: list[dict]):
        """Save notable interactions to semantic memory (non-blocking)."""
        if not self._semantic_memory:
            return

        # Only save if there were tool calls (multi-step interactions are more valuable)
        if not tool_results:
            return

        def _do_save():
            try:
                content = f"User: {user_msg[:200]}\nAssistant: {assistant_msg[:200]}"
                tools = [t["tool"] for t in tool_results]
                importance = min(1.0, 0.3 + len(tool_results) * 0.1)
                key = f"interaction:{hashlib.md5(content.encode('utf-8')).hexdigest()}"
                self._semantic_memory.save(
                    key=key,
                    content=content,
                    category="interaction",
                    metadata={"tools": tools},
                    importance=importance,
                )
                # Also record as episodic event
                self._semantic_memory.record_event(
                    event_type="tool_execution",
                    description=f"Executed {len(tool_results)} tools: {', '.join(tools)}",
                    metadata={"tools": tools, "user_msg": user_msg[:100]},
                )
            except Exception as e:
                _log(f"[semantic] Save error: {e}")

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(asyncio.to_thread(_do_save))
            else:
                _do_save()
        except Exception:
            pass

    def _schedule_skill_extraction(self, session: Session, tool_results: list[dict]):
        """Schedule background skill extraction if this turn had tool calls."""
        if not tool_results or not self._skills:
            return

        _log(f"[skill_extractor] Scheduling extraction from {len(session.messages)} msgs, {len(tool_results)} tool calls")

        # Snapshot what we need for the background task
        messages_snapshot = list(session.messages[-20:])
        model_snapshot = self.model
        skill_mgr = self._skills
        provider_api_key_env = self.provider.api_key_env
        provider_base_url = self.provider.resolve_base_url()

        async def _do_extract():
            try:
                _log("[skill_extractor] Background task STARTED")
                api_key = get_provider_key(self.provider_name)
                client = AsyncOpenAI(api_key=api_key, base_url=provider_base_url)
                result = await extract_skill_from_conversation(
                    messages=messages_snapshot,
                    client=client,
                    model=model_snapshot,
                    skill_manager=skill_mgr,
                )
                if result:
                    _log(f"[skill_extractor] Auto-extracted skill: {result['name']}")
                else:
                    _log("[skill_extractor] No skill extracted (LLM decided not to)")
            except Exception as e:
                _log(f"[skill_extractor] Extraction error: {e}")
                import traceback
                traceback.print_exc(file=sys.stderr)
                sys.stderr.flush()

        task = asyncio.create_task(_do_extract())
        _background_tasks.add(task)
        task.add_done_callback(lambda t: _background_tasks.discard(t))
        _log(f"[skill_extractor] Background task created, pending tasks: {len(_background_tasks)}")

    def _schedule_self_reflection(self, tool_results: list[dict]):
        """v3: Background self-reflection on tool call results.

        For each tool call, evaluates the result and records
        valuable lessons (failures, edge cases, special usage) to the knowledge base.
        Skips ordinary successful calls.
        """
        if not tool_results:
            return

        _log(f"[reflection] Scheduling reflection on {len(tool_results)} tool calls")

        # Snapshot for background task
        results_snapshot = [
            {
                "tool": t["tool"],
                "args": t.get("args", {}),
                "result": str(t.get("result", ""))[:500],
            }
            for t in tool_results
        ]
        model_snapshot = self.model
        provider_base_url = self.provider.resolve_base_url()

        async def _do_reflect():
            try:
                import re as re_mod
                from knowledge.base import KnowledgeBase

                api_key = get_provider_key(self.provider_name)
                client = AsyncOpenAI(api_key=api_key, base_url=provider_base_url)
                kb_path = os.path.join(os.getenv("AGENT_HOME", "/opt/agent-framework"), "data", "knowledge.db")
                kb = KnowledgeBase(db_path=kb_path)

                for tr in results_snapshot:
                    result_str = tr["result"]
                    is_error = result_str.startswith("Error") or result_str.startswith("错误") or result_str.startswith("Traceback")

                    prompt = f"""分析以下工具调用，提取可复用的经验教训。只提取有价值的经验，普通成功调用不需要记录。

工具: {tr['tool']}
参数: {json.dumps(tr['args'], ensure_ascii=False)[:200]}
结果: {result_str[:300]}
状态: {'失败' if is_error else '成功'}

请用以下JSON格式回复（如果经验不值得记录，返回空对象）：
{{"title": "简短标题", "lesson": "具体经验教训", "tags": "关键词1,关键词2"}}

只提取：失败原因和规避方法、特殊用法、边界情况、性能注意事项。
如果调用很普通（如正常读取文件成功），返回 {{}}。"""

                    try:
                        resp = await client.chat.completions.create(
                            model=model_snapshot,
                            messages=[
                                {"role": "system", "content": "你是一个工具调用分析助手。只提取有价值的经验，普通调用跳过。"},
                                {"role": "user", "content": prompt},
                            ],
                            temperature=0.3,
                            max_tokens=300,
                        )

                        content = resp.choices[0].message.content.strip()
                        _log(f"[reflection] {tr['tool']} response: {content[:100]}")
                        if content and content.strip() != "{}": 
                            json_match = re_mod.search(r'\{.*\}', content, re_mod.DOTALL)
                            if json_match:
                                data = json.loads(json_match.group())
                                if data.get("title") and data.get("lesson"):
                                    # Check for duplicates
                                    existing = kb.search(data["title"], limit=3)
                                    is_dup = any(
                                        e.get("score", 0) > 0.85 for e in existing
                                    )
                                    if not is_dup:
                                        kb.add(
                                            title=data["title"],
                                            content=data["lesson"],
                                            category="tool_lesson",
                                            tags=data.get("tags", tr["tool"]),
                                            source="self_reflection",
                                            metadata=json.dumps({
                                                "tool": tr["tool"],
                                                "is_error": is_error,
                                            }, ensure_ascii=False),
                                        )
                                        _log(f"[reflection] Saved lesson: {data['title']}")
                                    else:
                                        _log(f"[reflection] Duplicate skipped: {data['title']}")
                    except json.JSONDecodeError:
                        pass  # LLM didn't return valid JSON, skip
                    except Exception as e:
                        _log(f"[reflection] Error processing {tr['tool']}: {e}")

            except Exception as e:
                _log(f"[reflection] Error: {e}")
                import traceback
                traceback.print_exc(file=sys.stderr)
                sys.stderr.flush()

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                task = asyncio.ensure_future(_do_reflect())
                _background_tasks.add(task)
                task.add_done_callback(lambda t: _background_tasks.discard(t))
            else:
                asyncio.run(_do_reflect())
        except Exception:
            pass

    def _schedule_knowledge_extraction(self, session: Session, tool_results: list[dict]):
        """v3: Background cross-session knowledge extraction.

        Analyzes conversation patterns and extracts reusable knowledge
        (recurring user needs, effective tool combinations, best practices).
        Writes to knowledge base with deduplication.
        """
        # Snapshot for background task
        messages_snapshot = list(session.messages[-30:])
        tools_snapshot = [
            {
                "tool": t["tool"],
                "args": t.get("args", {}),
                "result": str(t.get("result", ""))[:200],
            }
            for t in tool_results
        ]
        model_snapshot = self.model
        provider_base_url = self.provider.resolve_base_url()

        _log(f"[knowledge] Scheduling extraction from {len(messages_snapshot)} msgs, {len(tools_snapshot)} tools")

        async def _do_extract():
            try:
                import re as re_mod
                from knowledge.base import KnowledgeBase

                api_key = get_provider_key(self.provider_name)
                client = AsyncOpenAI(api_key=api_key, base_url=provider_base_url)

                # Build conversation summary
                conv_lines = []
                for m in messages_snapshot:
                    role = "用户" if m.get("role") == "user" else "AI"
                    content = m.get("content", "")
                    if content and isinstance(content, str):
                        conv_lines.append(f"{role}: {content[:150]}")
                conv_summary = "\n".join(conv_lines)

                tools_summary = "\n".join([
                    f"- {t['tool']}({json.dumps(t['args'], ensure_ascii=False)[:100]}): {t['result'][:100]}"
                    for t in tools_snapshot
                ]) if tools_snapshot else "无工具调用"

                prompt = f"""分析以下对话，提取1-3条可复用的知识或模式。只提取那些在未来类似场景中可能有用的知识。

对话:
{conv_summary}

工具调用:
{tools_summary}

请用以下JSON数组格式回复（如果没有值得提取的知识，返回空数组 []）：
[{{"title": "简短标题", "content": "具体经验/模式/最佳实践", "tags": "关键词1,关键词2", "category": "learned"}}]

提取标准：
- 用户反复询问的模式（如"用户经常问X，最佳做法是Y"）
- 工具调用的有效组合方式
- 解决特定类型问题的最佳路径
- 常见错误和规避方法
- 用户偏好和习惯模式
- 特定场景下的最佳实践
不要提取：闲聊内容、一次性问题、没有通用性的细节。
注意：策略级知识（问题类型→工具路径映射）请标记category为"strategy"。"""

                resp = await client.chat.completions.create(
                    model=model_snapshot,
                    messages=[
                        {"role": "system", "content": "你是一个知识提取助手。从对话中提取可复用的知识。"},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.3,
                    max_tokens=800,
                )

                content = resp.choices[0].message.content.strip()
                if content and content.strip() != "[]":
                    json_match = re_mod.search(r'\[.*\]', content, re_mod.DOTALL)
                    if json_match:
                        items = json.loads(json_match.group())

                        kb_path = os.path.join(os.getenv("AGENT_HOME", "/opt/agent-framework"), "data", "knowledge.db")
                        kb = KnowledgeBase(db_path=kb_path)

                        for item in items:
                            if not item.get("title") or not item.get("content"):
                                continue

                            # Check for duplicates
                            existing = kb.search(item["title"], limit=3)
                            is_dup = any(
                                e.get("score", 0) > 0.80 for e in existing
                            )

                            if not is_dup:
                                kb.add(
                                    title=item["title"],
                                    content=item["content"],
                                    category=item.get("category", "learned"),
                                    tags=item.get("tags", ""),
                                    source="cross_session",
                                    metadata=json.dumps({
                                        "extracted_from": session.id,
                                        "tool_count": len(tools_snapshot),
                                    }, ensure_ascii=False),
                                )
                                _log(f"[knowledge] Extracted: {item['title']}")
                            else:
                                _log(f"[knowledge] Duplicate skipped: {item['title']}")

            except Exception as e:
                _log(f"[knowledge] Extraction error: {e}")
                import traceback
                traceback.print_exc(file=sys.stderr)
                sys.stderr.flush()

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                task = asyncio.ensure_future(_do_extract())
                _background_tasks.add(task)
                task.add_done_callback(lambda t: _background_tasks.discard(t))
            else:
                asyncio.run(_do_extract())
        except Exception:
            pass


    def _schedule_preference_extraction(self, session: Session):
        """Schedule background preference extraction if conversation is substantive."""
        if not self._memory:
            return

        # Count user messages — need at least 3 for meaningful preference extraction
        user_msgs = [m for m in session.messages if m.get("role") == "user" and m.get("content")]
        if len(user_msgs) < 3:
            return

        _log(f"[pref_extractor] Scheduling extraction from {len(user_msgs)} user messages")

        # Snapshot for background task
        messages_snapshot = list(session.messages[-30:])
        model_snapshot = self.model
        memory_mgr = self._memory
        provider_api_key_env = self.provider.api_key_env
        provider_base_url = self.provider.resolve_base_url()

        async def _do_extract():
            try:
                _log("[pref_extractor] Background task STARTED")
                api_key = get_provider_key(self.provider_name)
                client = AsyncOpenAI(api_key=api_key, base_url=provider_base_url)
                result = await extract_preferences_from_conversation(
                    messages=messages_snapshot,
                    client=client,
                    model=model_snapshot,
                    memory_manager=memory_mgr,
                )
                if result:
                    keys = [p["key"] for p in result]
                    _log(f"[pref_extractor] Extracted {len(result)} preferences: {keys}")
                else:
                    _log("[pref_extractor] No preferences extracted")
            except Exception as e:
                _log(f"[pref_extractor] Extraction error: {e}")
                import traceback
                traceback.print_exc(file=sys.stderr)
                sys.stderr.flush()

        task = asyncio.create_task(_do_extract())
        _background_tasks.add(task)
        task.add_done_callback(lambda t: _background_tasks.discard(t))
        _log(f"[pref_extractor] Background task created, pending tasks: {len(_background_tasks)}")

    def _adjust_kb_quality(self, tool_results_all: list[dict]):
        """v4: Adjust quality scores of retrieved KB entries based on conversation outcome.

        If the conversation involved tool failures, retrieved knowledge may be less relevant.
        If tools succeeded, boost the knowledge that was injected.
        """
        try:
            entry_ids = getattr(self, "_last_kb_entry_ids", [])
            if not entry_ids:
                return

            from knowledge.base import KnowledgeBase
            kb_path = os.path.join(os.getenv("AGENT_HOME", "/opt/agent-framework"), "data", "knowledge.db")
            kb = KnowledgeBase(db_path=kb_path)

            # Count successes and failures
            total_tools = len(tool_results_all)
            failures = sum(1 for t in tool_results_all if isinstance(t.get("result"), str) and (t["result"].startswith("Error") or t["result"].startswith("错误") or t["result"].startswith("Traceback") or t["result"].startswith("File not found") or t["result"].startswith("Access denied") or "not found" in t["result"][:50].lower() or "failed" in t["result"][:50].lower() or "error" in t["result"][:50].lower()))

            if total_tools == 0:
                # No tools used — small boost to retrieved knowledge (it was referenced)
                for eid in entry_ids:
                    kb.adjust_quality(eid, 0.02)
            elif failures == 0:
                # All tools succeeded — boost retrieved knowledge
                for eid in entry_ids:
                    kb.adjust_quality(eid, 0.1)
            else:
                failure_ratio = failures / total_tools
                if failure_ratio > 0.5:
                    # More than half failed — penalize retrieved knowledge
                    for eid in entry_ids:
                        kb.adjust_quality(eid, -0.1)
                else:
                    # Mixed outcome — slight penalty
                    for eid in entry_ids:
                        kb.adjust_quality(eid, -0.03)

            # Evict low-quality entries periodically
            kb.evict_low_quality(threshold=0.15, min_age_days=14, max_entries=200)

        except Exception as e:
            _log(f"[kb_quality] Adjustment error: {e}")

    def _schedule_strategic_extraction(self, session: Session, tool_results_all: list[dict]):
        """v4: Extract strategic-level knowledge — task type to optimal tool path mappings.

        Unlike _schedule_knowledge_extraction (operational lessons), this records
        higher-level patterns: "for X type of problem, use A→B→C tool path".
        """
        if len(tool_results_all) < 2:
            return  # Need at least 2 tools to have a meaningful path

        messages_snapshot = list(session.messages[-30:])
        tools_snapshot = [
            {"tool": t["tool"], "args": t.get("args", {}), "result": str(t.get("result", ""))[:200]}
            for t in tool_results_all
        ]
        model_snapshot = self.model
        provider_base_url = self.provider.resolve_base_url()

        _log(f"[strategic] Scheduling strategic extraction from {len(tools_snapshot)} tools")

        async def _do_strategic():
            try:
                import re as re_mod
                from knowledge.base import KnowledgeBase

                api_key = get_provider_key(self.provider_name)
                client = AsyncOpenAI(api_key=api_key, base_url=provider_base_url)

                # Build conversation summary
                conv_lines = []
                for m in messages_snapshot:
                    role = "用户" if m.get("role") == "user" else "AI"
                    content = m.get("content", "")
                    if content and isinstance(content, str):
                        conv_lines.append(f"{role}: {content[:150]}")
                conv_summary = "\n".join(conv_lines)

                # Build tool path
                tool_path = " → ".join([t["tool"] for t in tools_snapshot])
                tools_detail = "\n".join([
                    f"{i+1}. {t['tool']}({json.dumps(t['args'], ensure_ascii=False)[:80]}): {'失败' if t['result'].startswith('Error') or t['result'].startswith('错误') else '成功'}"
                    for i, t in enumerate(tools_snapshot)
                ])

                prompt = f"""分析以下对话和工具调用路径，提取策略级知识（不是操作细节，而是问题类型→解决路径的映射）。

对话:
{conv_summary}

工具调用路径: {tool_path}

详细调用:
{tools_detail}

请用以下JSON数组格式回复（如果没有策略级知识，返回空数组 []）：
[{{"title": "策略：简短描述问题类型", "content": "问题类型描述。推荐工具路径：A→B→C。理由：为什么这个路径有效。注意事项：需避免的常见错误。", "tags": "策略,问题类型,工具路径", "category": "strategy"}}]

提取标准：
- 识别对话中用户的问题类型（如"文件查找"、"代码分析"、"系统诊断"）
- 记录成功的工具组合路径（如read_file→grep→write_file）
- 记录失败路径和应该避免的做法
- 关注"什么类型的问题用什么路径解决最有效"
不要提取：单个工具的使用方法（那是操作知识）、一次性细节、没有通用性的内容。"""

                resp = await client.chat.completions.create(
                    model=model_snapshot,
                    messages=[
                        {"role": "system", "content": "你是一个策略分析助手。从对话中提取问题类型到解决路径的策略级知识。"},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.3,
                    max_tokens=800,
                )

                content = resp.choices[0].message.content.strip()
                if content and content.strip() != "[]":
                    # Strip markdown code blocks
                    content = re_mod.sub(r'^```(?:json)?\s*', '', content)
                    content = re_mod.sub(r'\s*```$', '', content)

                    json_match = re_mod.search(r'\[.*\]', content, re_mod.DOTALL)
                    if json_match:
                        try:
                            items = json.loads(json_match.group())
                        except json.JSONDecodeError:
                            # Try line-by-line extraction
                            items = []
                            for line in json_match.group().split("\n"):
                                line = line.strip().rstrip(",")
                                if line.startswith("{"):
                                    try:
                                        items.append(json.loads(line))
                                    except:
                                        pass

                        kb_path = os.path.join(os.getenv("AGENT_HOME", "/opt/agent-framework"), "data", "knowledge.db")
                        kb = KnowledgeBase(db_path=kb_path)

                        for item in items:
                            if not item.get("title") or not item.get("content"):
                                continue

                            existing = kb.search(item["title"], limit=3)
                            is_dup = any(e.get("score", 0) > 0.80 for e in existing)

                            if not is_dup:
                                kb.add(
                                    title=item["title"],
                                    content=item["content"],
                                    category=item.get("category", "strategy"),
                                    tags=item.get("tags", ""),
                                    source="strategic_extraction",
                                    metadata=json.dumps({
                                        "extracted_from": session.id,
                                        "tool_path": tool_path,
                                        "tool_count": len(tools_snapshot),
                                    }, ensure_ascii=False),
                                )
                                _log(f"[strategic] Extracted: {item['title']}")
                            else:
                                _log(f"[strategic] Duplicate skipped: {item['title']}")

            except Exception as e:
                _log(f"[strategic] Extraction error: {e}")
                import traceback
                traceback.print_exc(file=sys.stderr)
                sys.stderr.flush()

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                task = asyncio.ensure_future(_do_strategic())
                _background_tasks.add(task)
                task.add_done_callback(lambda t: _background_tasks.discard(t))
            else:
                asyncio.run(_do_strategic())
        except Exception:
            pass

    def _schedule_confidence_assessment(self, user_msg: str, assistant_msg: str,
                                          tool_results: list[dict]):
        """v5: Background confidence self-assessment.

        Evaluates how confident the agent should be in its response.
        Low confidence triggers KB quality adjustment and logging.
        """
        if len(assistant_msg) < 20:
            return

        _msg_snap = user_msg[:300]
        _resp_snap = assistant_msg[:500]
        _tool_count = len(tool_results)
        _fail_count = sum(1 for t in tool_results if isinstance(t.get("result"), str)
                         and any(x in t["result"][:50].lower() for x in ["error", "not found", "failed", "denied"]))
        _model_snap = self.model
        _provider_url = self.provider.resolve_base_url()

        _log(f"[confidence] Scheduling assessment (tools={_tool_count}, failures={_fail_count})")

        async def _do_assess():
            try:
                _api_key = get_provider_key(self.provider_name)
                _client = AsyncOpenAI(api_key=_api_key, base_url=_provider_url)

                _prompt = (
                    f"评估以下AI回答的置信度。\n\n"
                    f"用户问题: {_msg_snap}\n\n"
                    f"AI回答: {_resp_snap}\n\n"
                    f"工具调用: {_tool_count}次, 失败{_fail_count}次\n\n"
                    "请用JSON格式回复：\n"
                    '{"confidence": 0.0, "reasoning": "原因", "weak_areas": ["方面"]}\n\n'
                    "判断标准：\n"
                    "- 0.8-1.0: 有工具验证、事实确凿、逻辑清晰\n"
                    "- 0.5-0.8: 基于已有知识但未验证、部分推测\n"
                    "- 0.0-0.5: 无工具调用且涉及不确定事实、或工具多次失败后给出\n"
                )

                _resp = await _client.chat.completions.create(
                    model=_model_snap,
                    messages=[
                        {"role": "system", "content": "你是一个回答质量评估助手。"},
                        {"role": "user", "content": _prompt},
                    ],
                    temperature=0.2,
                    max_tokens=200,
                )

                _content = _resp.choices[0].message.content.strip()
                import re as _re_conf
                import json as _json_conf
                _jm = _re_conf.search(r'\{.*\}', _content, _re_conf.DOTALL)
                if _jm:
                    try:
                        _result = _json_conf.loads(_jm.group())
                        _conf = float(_result.get("confidence", 0.5))
                        _log(f"[confidence] Score: {_conf:.2f} - {_result.get('reasoning', '')[:80]}")

                        if _conf < 0.4 and hasattr(self, '_last_kb_entry_ids') and self._last_kb_entry_ids:
                            try:
                                from knowledge.base import KnowledgeBase
                                _kp = os.path.join(os.getenv("AGENT_HOME", "/opt/agent-framework"), "data", "knowledge.db")
                                _kb = KnowledgeBase(db_path=_kp)
                                for _eid in self._last_kb_entry_ids:
                                    _kb.adjust_quality(_eid, -0.1)
                                _log(f"[confidence] Low confidence ({_conf:.2f}), penalized KB entries")
                            except Exception:
                                pass

                        if _conf > 0.8 and _tool_count > 0 and hasattr(self, '_last_kb_entry_ids') and self._last_kb_entry_ids:
                            try:
                                from knowledge.base import KnowledgeBase
                                _kp = os.path.join(os.getenv("AGENT_HOME", "/opt/agent-framework"), "data", "knowledge.db")
                                _kb = KnowledgeBase(db_path=_kp)
                                for _eid in self._last_kb_entry_ids:
                                    _kb.adjust_quality(_eid, 0.05)
                                _log(f"[confidence] High confidence ({_conf:.2f}), boosted KB entries")
                            except Exception:
                                pass

                    except Exception:
                        pass
            except Exception as _e:
                _log(f"[confidence] Assessment error: {_e}")

        try:
            _loop = asyncio.get_event_loop()
            if _loop.is_running():
                _task = asyncio.ensure_future(_do_assess())
                _background_tasks.add(_task)
                _task.add_done_callback(lambda t: _background_tasks.discard(t))
            else:
                asyncio.run(_do_assess())
        except Exception:
            pass

    def _schedule_knowledge_consolidation(self):
        """v5: Background knowledge consolidation — merge similar KB entries.

        Runs periodically to prevent KB bloat. Finds entries with high
        similarity (score > 0.85) and merges them into a single refined entry.
        """
        _log("[consolidation] Scheduling knowledge consolidation")

        async def _do_consolidate():
            try:
                from knowledge.base import KnowledgeBase
                _kp = os.path.join(os.getenv("AGENT_HOME", "/opt/agent-framework"), "data", "knowledge.db")
                _kb = KnowledgeBase(db_path=_kp)

                _all = _kb.list_entries(limit=200)
                if len(_all) < 10:
                    _log("[consolidation] Too few entries, skipping")
                    return

                _checked = set()
                _to_merge = []

                for _entry in _all:
                    _eid = _entry["id"]
                    if _eid in _checked:
                        continue
                    _title = _entry["title"]
                    _cat = _entry.get("category", "")

                    _similar = _kb.search(_title, limit=5)
                    for _sim in _similar:
                        _sid = _sim["id"]
                        if _sid == _eid or _sid in _checked:
                            continue
                        if _sim.get("score", 0) > 0.85 and _sim.get("category") == _cat:
                            _to_merge.append((_eid, _sid, _title, _sim.get("title", ""), _sim.get("content", "")))
                            _checked.add(_sid)
                    _checked.add(_eid)

                if not _to_merge:
                    _log("[consolidation] No similar entries found")
                    return

                _log(f"[consolidation] Found {len(_to_merge)} similar pairs to merge")

                _api_key = get_provider_key(self.provider_name)
                _client = AsyncOpenAI(api_key=_api_key, base_url=self.provider.resolve_base_url())

                _merged = 0
                for _pair in _to_merge[:10]:
                    _eid1, _eid2, _t1, _t2, _c2 = _pair
                    _e1 = _kb.get(_eid1)
                    if not _e1 or not _kb.get(_eid2):
                        continue

                    _prompt = (
                        f"合并以下两条相似的知识条目为一条更精炼的条目。\n\n"
                        f"条目1:\n标题: {_e1['title']}\n内容: {_e1['content']}\n\n"
                        f"条目2:\n标题: {_t2}\n内容: {_c2}\n\n"
                        "请用JSON格式回复：\n"
                        '{"title": "合并后的标题", "content": "合并后的内容", "tags": "关键词1,关键词2"}'
                    )

                    _resp = await _client.chat.completions.create(
                        model=self.model,
                        messages=[
                            {"role": "system", "content": "你是一个知识合并助手。将相似的知识条目合并为一条精炼的条目。"},
                            {"role": "user", "content": _prompt},
                        ],
                        temperature=0.2,
                        max_tokens=400,
                    )

                    _content = _resp.choices[0].message.content.strip()
                    import re as _re_m
                    import json as _json_m
                    _jm = _re_m.search(r'\{.*\}', _content, _re_m.DOTALL)
                    if _jm:
                        try:
                            _mg = _json_m.loads(_jm.group())
                            if _mg.get("title") and _mg.get("content"):
                                _kb.add(
                                    title=_mg["title"],
                                    content=_mg["content"],
                                    category=_e1.get("category", "general"),
                                    tags=_mg.get("tags", "").split(",") if _mg.get("tags") else [],
                                    source="consolidated",
                                    metadata=json.dumps({"merged_from": [_eid1, _eid2]}, ensure_ascii=False),
                                )
                                _kb.delete(_eid1)
                                _kb.delete(_eid2)
                                _merged += 1
                                _log(f"[consolidation] Merged: {_mg['title'][:50]}")
                        except Exception as _e:
                            _log(f"[consolidation] JSON parse error: {_e}")

                _log(f"[consolidation] Complete: merged {_merged} pairs")

            except Exception as _e:
                _log(f"[consolidation] Error: {_e}")
                import traceback
                traceback.print_exc(file=sys.stderr)
                sys.stderr.flush()

        try:
            _loop = asyncio.get_event_loop()
            if _loop.is_running():
                _task = asyncio.ensure_future(_do_consolidate())
                _background_tasks.add(_task)
                _task.add_done_callback(lambda t: _background_tasks.discard(t))
            else:
                asyncio.run(_do_consolidate())
        except Exception:
            pass

    def _schedule_context_extraction(self, session: Session, user_msg: str, assistant_msg: str):
        """v6: Background context profile extraction.

        Analyzes conversation to extract/update user profile, projects, systems.
        Runs after every conversation, merges into context_profile.json.
        """
        if not self._context_profile:
            return
        if len(user_msg) < 5:
            return

        _msgs = [m for m in session.messages[-20:] if isinstance(m.get("content", ""), str)]
        _msgs.append({"role": "user", "content": user_msg})
        _msgs.append({"role": "assistant", "content": assistant_msg[:1000]})
        _msgs_snapshot = [
            {"role": "用户" if m["role"] == "user" else "AI", "content": m["content"][:200]}
            for m in _msgs
        ]
        _model_snap = self.model
        _provider_url = self.provider.resolve_base_url()
        _profile_ref = self._context_profile

        _log("[context] Scheduling context extraction")

        async def _do_extract():
            try:
                _api_key = get_provider_key(self.provider_name)
                _client = AsyncOpenAI(api_key=_api_key, base_url=_provider_url)

                _conv = "\n".join([f"{m['role']}: {m['content']}" for m in _msgs_snapshot])
                _existing = json.dumps(_profile_ref.data, ensure_ascii=False)

                _prompt = (
                    f"分析以下对话，提取关于用户的信息。更新到现有画像中（只提取新信息或变化）。\n\n"
                    f"对话:\n{_conv}\n\n"
                    f"现有画像:\n{_existing[:500]}\n\n"
                    "请用JSON格式回复（只包含需要更新的字段，没有新信息就返回空对象{}）：\n"
                    '{"user": {"name": "", "role": "", "expertise": [], "communication_style": ""}, '
                    '"projects": [{"name": "", "type": "", "technologies": []}], '
                    '"systems": [{"name": "", "type": "", "address": "", "details": ""}], '
                    '"common_tasks": [], "recent_topics": []}\n\n'
                    "提取标准：\n"
                    "- 用户身份：名字、职业、技能领域\n"
                    "- 项目：用户正在做的项目名称、技术栈\n"
                    "- 系统：服务器、开发环境、服务地址\n"
                    "- 常见任务：用户反复需要做的事情\n"
                    "- 近期话题：本次对话讨论的主题\n"
                    "不要提取：闲聊内容、一次性细节、无法确认的猜测"
                )

                _resp = await _client.chat.completions.create(
                    model=_model_snap,
                    messages=[
                        {"role": "system", "content": "你是一个用户画像提取助手。从对话中提取关于用户的结构化信息。"},
                        {"role": "user", "content": _prompt},
                    ],
                    temperature=0.2,
                    max_tokens=500,
                )

                _content = _resp.choices[0].message.content.strip()
                import re as _re_ctx
                import json as _json_ctx
                _jm = _re_ctx.search(r'\{.*\}', _content, _re_ctx.DOTALL)
                if _jm:
                    try:
                        _extracted = _json_ctx.loads(_jm.group())
                        if _extracted and _extracted != {}:
                            _profile_ref.update_from_llm(_extracted)
                            _log(f"[context] Profile updated: {_profile_ref.stats()}")
                        else:
                            _log("[context] No new info to extract")
                    except Exception as _e:
                        _log(f"[context] JSON parse error: {_e}")
            except Exception as _e:
                _log(f"[context] Extraction error: {_e}")

        try:
            _loop = asyncio.get_event_loop()
            if _loop.is_running():
                _task = asyncio.ensure_future(_do_extract())
                _background_tasks.add(_task)
                _task.add_done_callback(lambda t: _background_tasks.discard(t))
            else:
                asyncio.run(_do_extract())
        except Exception:
            pass

    def _schedule_session_summary(self, session: Session, user_msg: str, assistant_msg: str):
        """v7: Background session summary generation.

        Generates a concise handoff summary after each conversation,
        stores it in context_profile so next session knows what was discussed.
        """
        if not self._context_profile:
            return
        if len(user_msg) < 5:
            return

        _msgs = [m for m in session.messages[-20:] if isinstance(m.get("content", ""), str)]
        _msgs.append({"role": "user", "content": user_msg})
        _msgs.append({"role": "assistant", "content": assistant_msg[:1500]})
        _msgs_snapshot = [
            {"role": "用户" if m["role"] == "user" else "AI", "content": m["content"][:300]}
            for m in _msgs
        ]
        _model_snap = self.model
        _provider_url = self.provider.resolve_base_url()
        _profile_ref = self._context_profile

        _log("[session] Scheduling session summary")

        async def _do_summary():
            try:
                _api_key = get_provider_key(self.provider_name)
                _client = AsyncOpenAI(api_key=_api_key, base_url=_provider_url)

                _conv = "\n".join([f"{m['role']}: {m['content']}" for m in _msgs_snapshot])
                _recent_sessions = _profile_ref.data.get("session_history", [])[-2:]
                _recent_str = json.dumps(_recent_sessions, ensure_ascii=False) if _recent_sessions else "无"

                _prompt = (
                    f"分析以下对话，生成一份简短的交接摘要。\n\n"
                    f"对话:\n{_conv}\n\n"
                    f"最近对话:\n{_recent_str}\n\n"
                    "请用JSON格式回复：\n"
                    '{"topic": "本次对话的主要话题(一句话)", '
                    '"summary": "对话摘要(2-3句话,包含关键决策和结果)", '
                    '"pending": ["待完成的任务1", "待完成的任务2"], '
                    '"next_steps": "下次应该继续做什么"}\n\n'
                    "要求：\n"
                    "- topic: 用短语概括，如'调试LUMU知识库'或'设计前端UI'\n"
                    "- summary: 包含做了什么、结果如何\n"
                    "- pending: 如果有未完成的任务就列出，没有就空数组\n"
                    "- next_steps: 下次该做什么，一句话"
                )

                _resp = await _client.chat.completions.create(
                    model=_model_snap,
                    messages=[
                        {"role": "system", "content": "你是一个对话摘要助手。生成简短准确的交接摘要。"},
                        {"role": "user", "content": _prompt},
                    ],
                    temperature=0.2,
                    max_tokens=400,
                )

                _content = _resp.choices[0].message.content.strip()
                import re as _re_ss
                import json as _json_ss
                import time as _time_ss
                _jm = _re_ss.search(r'\{.*\}', _content, _re_ss.DOTALL)
                if _jm:
                    try:
                        _data = _json_ss.loads(_jm.group())
                        if _data and _data.get("topic"):
                            _ts = _time_ss.strftime("%Y-%m-%dT%H:%M:%S")
                            _profile_ref.add_session_summary(
                                timestamp=_ts,
                                topic=_data.get("topic", ""),
                                summary=_data.get("summary", ""),
                                pending=_data.get("pending", []),
                                next_steps=_data.get("next_steps", ""),
                            )
                            _log(f"[session] Summary saved: {_data.get('topic')}")
                    except Exception as _e:
                        _log(f"[session] JSON parse error: {_e}")
            except Exception as _e:
                _log(f"[session] Summary error: {_e}")

        try:
            _loop = asyncio.get_event_loop()
            if _loop.is_running():
                _task = asyncio.ensure_future(_do_summary())
                _background_tasks.add(_task)
                _task.add_done_callback(lambda t: _background_tasks.discard(t))
            else:
                asyncio.run(_do_summary())
        except Exception:
            pass

    def _schedule_proactive_thinking(self, session: Session, user_msg: str, assistant_msg: str):
        """v9: Background proactive thinking.

        Reviews the conversation and knowledge base to generate proactive
        insights — observations, suggestions, patterns the agent noticed.
        Stored in context_profile and injected into future conversations.
        """
        if not self._context_profile:
            return
        if len(user_msg) < 10:
            return

        _msgs = [m for m in session.messages[-15:] if isinstance(m.get("content", ""), str)]
        _msgs.append({"role": "user", "content": user_msg})
        _msgs.append({"role": "assistant", "content": assistant_msg[:1000]})
        _msgs_snapshot = [
            {"role": "用户" if m["role"] == "user" else "AI", "content": m["content"][:200]}
            for m in _msgs
        ]
        _model_snap = self.model
        _provider_url = self.provider.resolve_base_url()
        _profile_ref = self._context_profile

        _log("[proactive] Scheduling proactive thinking")

        async def _do_think():
            try:
                _api_key = get_provider_key(self.provider_name)
                _client = AsyncOpenAI(api_key=_api_key, base_url=_provider_url)

                _conv = "\n".join([f"{m['role']}: {m['content']}" for m in _msgs_snapshot])
                _existing_insights = _profile_ref.data.get("proactive_insights", [])
                _insights_str = json.dumps(_existing_insights, ensure_ascii=False) if _existing_insights else "无"

                _prompt = (
                    f"分析以下对话，生成1-2条主动观察或建议。这些观察将在未来对话中注入，帮助AI更好地服务用户。\n\n"
                    f"对话:\n{_conv}\n\n"
                    f"已有观察:\n{_insights_str}\n\n"
                    "请用JSON格式回复：\n"
                    '{"insights": [{"insight": "观察内容(一句话)", "category": "observation|suggestion|pattern"}]}\n\n'
                    "要求：\n"
                    "- 只提取有价值的、可复用的观察\n"
                    "- 比如：用户偏好、常见问题模式、潜在风险、改进建议\n"
                    "- 不要提取闲聊内容或一次性细节\n"
                    "- 如果没有有价值的观察，返回空数组 {\"insights\": []}"
                )

                _resp = await _client.chat.completions.create(
                    model=_model_snap,
                    messages=[
                        {"role": "system", "content": "你是一个主动思考助手。从对话中提取有价值的观察和建议。"},
                        {"role": "user", "content": _prompt},
                    ],
                    temperature=0.3,
                    max_tokens=300,
                )

                _content = _resp.choices[0].message.content.strip()
                import re as _re_pt
                import json as _json_pt
                _jm = _re_pt.search(r'\{.*\}', _content, _re_pt.DOTALL)
                if _jm:
                    try:
                        _data = _json_pt.loads(_jm.group())
                        _insights = _data.get("insights", [])
                        for _ins in _insights[:2]:
                            if _ins.get("insight"):
                                _profile_ref.add_insight(
                                    insight=_ins["insight"],
                                    category=_ins.get("category", "observation"),
                                )
                        if _insights:
                            _log(f"[proactive] Added {len(_insights)} insights")
                        else:
                            _log("[proactive] No new insights")
                    except Exception as _e:
                        _log(f"[proactive] JSON parse error: {_e}")
            except Exception as _e:
                _log(f"[proactive] Thinking error: {_e}")

        try:
            _loop = asyncio.get_event_loop()
            if _loop.is_running():
                _task = asyncio.ensure_future(_do_think())
                _background_tasks.add(_task)
                _task.add_done_callback(lambda t: _background_tasks.discard(t))
            else:
                asyncio.run(_do_think())
        except Exception:
            pass

    def _coerce_args(self, tool_name: str, args_str: str) -> dict:
        """Parse and coerce tool arguments (from Hermes pattern).

        LLMs often output "42" instead of 42, or "true" instead of True.
        This handles those cases gracefully.
        """
        try:
            args = json.loads(args_str) if isinstance(args_str, str) else args_str
        except json.JSONDecodeError:
            return {}

        # Get tool schema for type information
        tool = self.tools.get(tool_name)
        if not tool:
            return args

        schema_props = tool.parameters.get("properties", {})
        for key, value in args.items():
            if key not in schema_props:
                continue
            expected_type = schema_props[key].get("type")
            args[key] = _coerce_value(value, expected_type)

        return args

    def list_sessions(self) -> list[dict]:
        return [
            {"id": s.id, "messages": len(s.messages), "created_at": s.created_at}
            for s in self._sessions.values()
        ]

    def clear_session(self, session_id: str):
        """Delete a session completely — from memory and disk."""
        if session_id in self._sessions:
            del self._sessions[session_id]
        self._store.delete(session_id)

    # --- Memory access ---
    @property
    def memory(self):
        return self._memory

    @property
    def skills(self):
        return self._skills

    @property
    def semantic_memory(self):
        return self._semantic_memory

    @property
    def learning_engine(self):
        return self._learning_engine


def _coerce_value(value, expected_type: str | None):
    """Coerce a value to the expected JSON schema type (from Hermes pattern)."""
    if expected_type is None or value is None:
        return value
    if expected_type == "integer":
        try:
            return int(value)
        except (ValueError, TypeError):
            return value
    if expected_type == "number":
        try:
            return float(value)
        except (ValueError, TypeError):
            return value
    if expected_type == "boolean":
        if isinstance(value, str):
            if value.lower() in ("true", "yes", "1"):
                return True
            if value.lower() in ("false", "no", "0"):
                return False
        return value
    if expected_type == "string":
        if not isinstance(value, str):
            return str(value)
        return value
    if expected_type == "array":
        if not isinstance(value, list):
            return [value]
        return value
    return value
