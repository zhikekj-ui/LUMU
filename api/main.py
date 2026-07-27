import time
import uuid
import os
from slowapi.errors import RateLimitExceeded
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from middleware.rate_limit import limiter, rate_limit_exceeded_handler
from core.logging_config import configure_logging, get_logger

"""FastAPI application — API routes + static file serving."""
import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Header, Depends, Request, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agent.core import Agent
from tools.registry import ToolRegistry
from providers.registry import discover_providers
from plugins.loader import PluginLoader
from mcp.bridge import MCPBridge
from scheduler.scheduler import scheduler
import config
from core.user_config import (
    load_config, save_config, get_provider_key, set_provider_key,
    get_tts_config, set_tts_config, get_stt_config,
    get_model_preference, set_model_preference,
    get_system_prompt, set_system_prompt,
    get_embedding_config, set_embedding_config,
)

# --- Bootstrap ---
discover_providers()

tool_registry = ToolRegistry()
tool_registry.discover()

# Load plugins
plugin_loader = PluginLoader()
plugin_loader.discover()
plugin_loader.register_tools(tool_registry)

# MCP bridge
mcp_bridge = MCPBridge()

# Load saved model preference (overrides .env defaults)
_saved_pref = get_model_preference()
_init_provider = _saved_pref.get("provider", config.DEFAULT_PROVIDER)
_init_model = _saved_pref.get("model", config.DEFAULT_MODEL)

agent = Agent(
    provider_name=_init_provider,
    model=_init_model,
    tool_registry=tool_registry,
)

# Wire scheduler to agent
scheduler.set_agent(agent)


# --- Lifespan ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: initialize logging
    configure_logging(log_level="INFO", json_format=False)
    logger = get_logger("lifespan")
    logger.info("Agent Framework starting up")
    # Startup: connect MCP servers
    await mcp_bridge.connect_all(tool_registry)
    # Start scheduler
    await scheduler.start()
    # Start channels
    try:
        from channels.router import channel_router
        await channel_router.start_all(agent)
    except Exception as e:
        print(f"[channels] Startup error: {e}")
    yield
    # Shutdown: stop scheduler + disconnect MCP + stop channels
    await scheduler.stop()
    await mcp_bridge.disconnect_all()
    try:
        from channels.router import channel_router
        await channel_router.stop_all()
    except Exception:
        pass


app = FastAPI(title="Agent Framework", version="0.5.0", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

# Let plugins register API routes
plugin_loader.register_routes(app)

STATIC_DIR = Path(__file__).parent / "static"


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "provider": config.DEFAULT_PROVIDER,
        "model": config.DEFAULT_MODEL,
        "tools_loaded": len(getattr(tool_registry, "_tools", {})),
    }


@app.get("/metrics")
async def metrics():
    from fastapi import Response
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


# --- Auth ---
logger_auth = get_logger("auth")

async def verify_api_key(authorization: str = Header(default="")):
    """Validate Bearer token. Skipped if API_KEY is not set."""
    if not config.API_KEY:
        return
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    token = authorization[7:]
    if token != config.API_KEY:
        logger_auth.warning("invalid_api_key_attempt", token_prefix=token[:8] if token else None)
        raise HTTPException(status_code=403, detail="Invalid API key")


# --- Request models ---
class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    images: list[str] | None = None  # v8: base64 or URL images


class MemoryRequest(BaseModel):
    key: str
    content: str
    category: str = "general"
    confirmed: bool = False
    importance: float = None
    metadata: dict = None
    store: str = "primary"  # primary=MemoryManager / semantic=SemanticMemory


class LoginRequest(BaseModel):
    email: str
    password: str


# --- Routes ---
@app.get("/", response_class=HTMLResponse)
async def index():
    html = (STATIC_DIR / "index.html").read_text()
    return HTMLResponse(
        content=html,
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@limiter.limit("10/minute")
@app.post("/api/chat")
async def chat(req: ChatRequest, request: Request, _=Depends(verify_api_key)):
    try:
        result = await agent.chat(req.message, req.session_id, images=req.images)
        return JSONResponse(result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@limiter.limit("20/minute")
@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest, request: Request, _=Depends(verify_api_key)):
    """SSE streaming endpoint — yields tokens as they arrive."""

    async def event_generator():
        try:
            async for event in agent.stream_chat(req.message, req.session_id, images=req.images):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# --- Sessions ---
@app.get("/api/sessions")
async def list_sessions(_=Depends(verify_api_key)):
    """List all sessions with preview text."""
    result = []
    for s in agent._sessions.values():
        preview = ""
        for m in s.messages:
            if m.get("role") == "user":
                preview = m["content"][:40]
                break
        result.append({
            "id": s.id,
            "preview": preview,
            "message_count": len(s.messages),
        })
    return result


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str, _=Depends(verify_api_key)):
    """Get full message history for a session."""
    session = agent.get_or_create_session(session_id)
    return {
        "id": session.id,
        "messages": session.messages,
    }


@app.delete("/api/sessions/{session_id}")
async def clear_session(session_id: str, _=Depends(verify_api_key)):
    """Delete a session — requires auth."""
    agent.clear_session(session_id)
    return {"ok": True}


@app.post("/api/sessions")
async def create_session(_=Depends(verify_api_key)):
    """Create a new chat session and return its id."""
    new_id = str(uuid.uuid4())
    session = agent.get_or_create_session(new_id)
    return {"id": session.id, "preview": "", "message_count": 0}


@app.post("/api/auth/login")
async def auth_login(req: LoginRequest, request: Request):
    """Authenticate admin user and return a session token."""
    admin_email = os.getenv("ADMIN_EMAIL", "zhikexx@163.com")
    admin_password = os.getenv("ADMIN_PASSWORD", "mm369369")
    if req.email == admin_email and req.password == admin_password:
        token = config.API_KEY or "lumu-session-token"
        return {"access_token": token, "user": {"email": req.email, "role": "super_admin"}}
    raise HTTPException(status_code=401, detail="邮箱或密码错误")


# --- Memory ---
# --- Memory confirmation store（非破坏性、隔离的 JSON 存储，不碰 MemoryManager 表结构）---
_MEM_CONFIRM_PATH = os.path.join(os.getenv("AGENT_HOME", "/opt/agent-framework"), "data", "memory_confirmations.json")

def _load_confirms() -> dict:
    try:
        with open(_MEM_CONFIRM_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _save_confirm(key: str, confirmed: bool):
    data = _load_confirms()
    if confirmed:
        data[key] = True
    else:
        data.pop(key, None)
    try:
        os.makedirs(os.path.dirname(_MEM_CONFIRM_PATH), exist_ok=True)
        with open(_MEM_CONFIRM_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


@app.get("/api/memory")
async def list_memories(category: str = "", _=Depends(verify_api_key)):
    """List all memories, optionally filtered by category."""
    items = agent.memory.list_all(category if category else None)
    confirms = _load_confirms()
    # 归一化（非破坏性）：确保前端三级置信度分级始终有 importance 字段
    for it in items:
        if not isinstance(it, dict):
            continue
        if it.get("importance") is None:
            md = it.get("metadata") or {}
            it["importance"] = md.get("confidence", 0.6)
        key = it.get("key")
        if key in confirms and confirms[key]:
            it["importance"] = max(float(it.get("importance") or 0), 0.95)
            md = it.get("metadata") or {}
            md["confirmed"] = True
            it["metadata"] = md
            it["confirmed"] = True
    return items


@app.post("/api/memory")
async def save_memory(req: MemoryRequest, _=Depends(verify_api_key)):
    """统一写入路由：store=primary(默认,MemoryManager) 或 semantic(SemanticMemory)。"""
    if req.store == "semantic" and agent.semantic_memory is not None:
        imp = req.importance if req.importance is not None else 0.6
        meta = dict(req.metadata or {})
        if req.confirmed:
            meta["confirmed"] = True
            imp = max(float(imp or 0), 0.95)
        agent.semantic_memory.save(req.key, req.content, req.category, importance=imp, metadata=meta)
    else:
        agent.memory.save(req.key, req.content, req.category)
    if req.confirmed:
        _save_confirm(req.key, True)
    return {"ok": True, "key": req.key, "store": req.store}


@app.delete("/api/memory/{key}")
async def delete_memory(key: str, _=Depends(verify_api_key)):
    """Delete a memory by key."""
    agent.memory.delete(key)
    return {"ok": True, "key": key}


@app.get("/api/memory/search")
async def search_memories(q: str = "", limit: int = 5, _=Depends(verify_api_key)):
    """Search memories by keyword."""
    if not q:
        return []
    return agent.memory.search(q, limit)


@app.get("/api/memory/conflicts")
async def memory_conflicts(_=Depends(verify_api_key)):
    """非破坏性只读：扫描记忆库识别近似重复与可能矛盾的条目。"""
    import re as _re
    items = agent.memory.list_all() or []

    def _tok(s):
        s = (s or "").lower()
        toks = set(_re.findall(r"[a-z0-9]+", s))
        toks.update(_re.findall(r"[一-鿿]", s))
        return toks

    def _jac(a, b):
        if not a or not b:
            return 0.0
        return len(a & b) / len(a | b)

    flags = []
    n = len(items)
    seen = set()
    for i in range(n):
        for j in range(i + 1, n):
            a, b = items[i], items[j]
            jc = _jac(_tok(a.get("content")), _tok(b.get("content")))
            if jc >= 0.55:
                flags.append({
                    "type": "duplicate",
                    "keys": [a.get("key"), b.get("key")],
                    "similarity": round(jc, 2),
                    "detail": "内容高度近似，可能为重复记忆",
                })
                seen.add((i, j))
    # 同分类内的潜在矛盾：含相反极性词
    polarity = [("喜欢", "不喜欢"), ("偏好", "不偏好"), ("要", "不要"),
                ("需要", "不需要"), ("是", "不是"), ("应该", "不应该")]
    for i in range(n):
        for j in range(i + 1, n):
            if (i, j) in seen:
                continue
            a, b = items[i], items[j]
            if a.get("category") != b.get("category"):
                continue
            ca, cb = (a.get("content") or ""), (b.get("content") or "")
            for pos, neg in polarity:
                if (pos in ca and neg in cb) or (neg in ca and pos in cb):
                    flags.append({
                        "type": "conflict",
                        "keys": [a.get("key"), b.get("key")],
                        "detail": f"同分类下出现相反表述（{pos}/{neg}）",
                    })
                    break
    return {"conflicts": flags, "total": n}


# --- 统一记忆总线：聚合多存储层（MemoryManager + SemanticMemory）为单一只读视图 ---
@app.get("/api/memory/unified")
async def memory_unified(_=Depends(verify_api_key)):
    """非破坏性只读：合并 MemoryManager 与 SemanticMemory，按 key 去重并归一化 importance。"""
    confirms = _load_confirms()
    merged = {}
    for it in (agent.memory.list_all() or []):
        if not isinstance(it, dict):
            continue
        key = it.get("key")
        if key is None:
            continue
        imp = it.get("importance")
        if imp is None:
            imp = (it.get("metadata") or {}).get("confidence", 0.6)
        if key in confirms and confirms[key]:
            imp = max(float(imp or 0), 0.95)
        merged[key] = {
            "key": key,
            "content": it.get("content", ""),
            "category": it.get("category", "general"),
            "importance": float(imp or 0.6),
            "store": "primary",
            "created_at": it.get("created_at"),
            "confirmed": bool(key in confirms and confirms[key]),
        }
    if agent.semantic_memory is not None:
        for it in (agent.semantic_memory.list_all(limit=2000) or []):
            if not isinstance(it, dict):
                continue
            key = it.get("key")
            if key is None:
                continue
            imp = it.get("importance")
            if imp is None:
                imp = (it.get("metadata") or {}).get("confidence", 0.5)
            if key in confirms and confirms[key]:
                imp = max(float(imp or 0), 0.95)
            if key in merged:
                base = merged[key]
                base["importance"] = float(max(base.get("importance", 0), imp or 0))
                base["store"] = "both"
                base["access_count"] = it.get("access_count", 0)
                base["semantic_created_at"] = it.get("created_at")
                if imp is not None:
                    base["confirmed"] = base.get("confirmed") or bool((it.get("metadata") or {}).get("confirmed"))
            else:
                merged[key] = {
                    "key": key,
                    "content": it.get("content", ""),
                    "category": it.get("category", "general"),
                    "importance": float(imp or 0.5),
                    "store": "semantic",
                    "created_at": it.get("created_at"),
                    "access_count": it.get("access_count", 0),
                    "confirmed": bool((it.get("metadata") or {}).get("confirmed")),
                }
    return {"memories": list(merged.values()), "total": len(merged)}


# --- 时间衰减 + 主动遗忘（notes 方案3，非破坏性只读视图 + 显式遗忘动作）---
@app.get("/api/memory/decay")
async def memory_decay(_=Depends(verify_api_key)):
    """非破坏性只读：基于记忆年龄计算衰减后的 importance，标注遗忘候选。"""
    import datetime as _dt
    HALF_LIFE_DAYS = 180.0
    FORGET_THRESHOLD = 0.4
    items = []
    try:
        items = (await memory_unified()).get("memories", [])
    except Exception:
        items = (agent.memory.list_all() or [])
    now = _dt.datetime.now(_dt.timezone.utc)
    out = []
    for m in items:
        created = m.get("created_at") or m.get("semantic_created_at")
        age_days = None
        base_imp = float(m.get("importance") or 0.6)
        if created:
            s = str(created).replace("Z", "").replace("T", " ").strip()
            ct = None
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d"):
                try:
                    ct = _dt.datetime.strptime(s.split("+")[0], fmt)
                    break
                except Exception:
                    ct = None
            if ct is not None:
                ct = ct.replace(tzinfo=_dt.timezone.utc)
                age_days = max(0, (now - ct).days)
        decayed = base_imp * (0.5 ** (age_days / HALF_LIFE_DAYS)) if age_days is not None else base_imp
        out.append({
            "key": m.get("key"),
            "importance": round(base_imp, 3),
            "decayed_importance": round(decayed, 3),
            "age_days": age_days,
            "forget_candidate": bool(decayed < FORGET_THRESHOLD),
            "store": m.get("store"),
        })
    forget_count = sum(1 for o in out if o["forget_candidate"])
    return {"decay": out, "total": len(out), "forget_candidates": forget_count,
            "half_life_days": HALF_LIFE_DAYS, "threshold": FORGET_THRESHOLD}


class ForgetRequest(BaseModel):
    keys: list[str] = []
    store: str = "all"  # all / primary / semantic


@app.post("/api/memory/forget")
async def memory_forget(req: ForgetRequest, _=Depends(verify_api_key)):
    """主动遗忘：删除指定 key（默认双库）。显式动作，不自动批量删。"""
    deleted = []
    for key in req.keys:
        if req.store in ("all", "primary") and agent.memory is not None:
            try:
                agent.memory.delete(key)
            except Exception:
                pass
        if req.store in ("all", "semantic") and agent.semantic_memory is not None:
            try:
                agent.semantic_memory.delete(key)
            except Exception:
                pass
        deleted.append(key)
        _save_confirm(key, False)
    return {"ok": True, "deleted": deleted, "store": req.store}

# --- 保守版主动遗忘：归档（可恢复，隔离存储 data/memory_archive.json，非破坏）---
def _archive_path():
    import os as _os
    p = _os.path.join("data", "memory_archive.json")
    _os.makedirs("data", exist_ok=True)
    return p


def _load_archive() -> dict:
    import json as _json, os as _os
    p = _archive_path()
    if not _os.path.exists(p):
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            return _json.load(f)
    except Exception:
        return {}


def _save_archive(d: dict):
    import json as _json
    with open(_archive_path(), "w", encoding="utf-8") as f:
        _json.dump(d, f, ensure_ascii=False, indent=1)


class ArchiveRequest(BaseModel):
    keys: list[str] = []


@app.post("/api/memory/archive")
async def memory_archive(req: ArchiveRequest, _=Depends(verify_api_key)):
    """归档：先完整快照到 data/memory_archive.json，再从双库移除。可随时恢复，显式动作不自动批量。"""
    import datetime as _dt
    uni = await memory_unified()
    by_key = {m["key"]: m for m in uni.get("memories", [])}
    arch = _load_archive()
    archived, missing = [], []
    for key in req.keys:
        m = by_key.get(key)
        if m is None:
            missing.append(key)
            continue
        m = dict(m)
        m["archived_at"] = _dt.datetime.now(_dt.timezone.utc).isoformat()
        arch[key] = m
        if agent.memory is not None:
            try:
                agent.memory.delete(key)
            except Exception:
                pass
        if agent.semantic_memory is not None:
            try:
                agent.semantic_memory.delete(key)
            except Exception:
                pass
        _save_confirm(key, False)
        archived.append(key)
    _save_archive(arch)
    return {"ok": True, "archived": archived, "missing": missing, "total_archived": len(arch)}


@app.get("/api/memory/archived")
async def memory_archived(_=Depends(verify_api_key)):
    """归档区列表（只读）。"""
    arch = _load_archive()
    items = sorted(arch.values(), key=lambda x: x.get("archived_at") or "", reverse=True)
    return {"archived": items, "total": len(items)}


@app.post("/api/memory/restore")
async def memory_restore(req: ArchiveRequest, _=Depends(verify_api_key)):
    """从归档区恢复记忆到原存储，并移出归档。"""
    arch = _load_archive()
    restored, missing = [], []
    for key in req.keys:
        m = arch.get(key)
        if m is None:
            missing.append(key)
            continue
        store = m.get("store") or "primary"
        content = m.get("content", "")
        category = m.get("category", "general")
        imp = float(m.get("importance") or 0.6)
        if store in ("primary", "both") and agent.memory is not None:
            try:
                agent.memory.save(key, content, category)
            except Exception:
                pass
        if store in ("semantic", "both") and agent.semantic_memory is not None:
            try:
                agent.semantic_memory.save(key, content, category, importance=imp, metadata={"restored": True})
            except Exception:
                pass
        if m.get("confirmed"):
            _save_confirm(key, True)
        del arch[key]
        restored.append(key)
    _save_archive(arch)
    return {"ok": True, "restored": restored, "missing": missing, "total_archived": len(arch)}



# --- 记忆智能维护（归纳 / 主动遗忘） ---
@app.post("/api/memory/consolidate")
async def memory_consolidate(_=Depends(verify_api_key)):
    """记忆归纳：把高度相似的记忆合并为一条高层抽象记忆（只新增、不删原）。手动触发。"""
    try:
        n = await agent._memory_consolidate()
        return {"ok": True, "consolidated": n}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/memory/auto-forget")
async def memory_auto_forget(cap: int = 5, _=Depends(verify_api_key)):
    """主动遗忘（可恢复）：软归档衰减后重要性极低且陈旧的记忆（不硬删，归档到 memory_archive.json）。手动触发。"""
    try:
        n = await agent._auto_forget_memories(cap=max(1, min(cap, 20)))
        return {"ok": True, "archived": n}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# --- Skills ---
class SkillRequest(BaseModel):
    name: str
    description: str
    content: str
    tags: str = ""


@app.get("/api/skills")
async def list_skills(tag: str = "", _=Depends(verify_api_key)):
    """List all saved skills."""
    return agent.skills.list_all(tag if tag else "")


@app.get("/api/skills/{skill_name}")
async def get_skill_api(skill_name: str, _=Depends(verify_api_key)):
    """Get full details of a skill."""
    skill = agent.skills.get(skill_name)
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found")
    return skill


@app.post("/api/skills")
async def save_skill_api(req: SkillRequest, _=Depends(verify_api_key)):
    """Save or update a skill."""
    is_new = agent.skills.save(req.name, req.description, req.content, req.tags)
    return {"ok": True, "name": req.name, "created": is_new}


@app.delete("/api/skills/{skill_name}")
async def delete_skill_api(skill_name: str, _=Depends(verify_api_key)):
    """Delete a skill."""
    if agent.skills.delete(skill_name):
        return {"ok": True, "name": skill_name}
    raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found")


@app.get("/api/skills/search")
async def search_skills(q: str = "", limit: int = 5, _=Depends(verify_api_key)):
    """Search skills by keyword."""
    if not q:
        return []
    return agent.skills.search(q, limit)


# --- Cron Jobs ---
@app.get("/api/cron")
async def list_cron_jobs(_=Depends(verify_api_key)):
    """List all scheduled cron jobs."""
    return scheduler.list_jobs()


@app.get("/api/cron/logs")
async def cron_run_logs(job_id: str = "", limit: int = 20, _=Depends(verify_api_key)):
    """Get cron job execution logs."""
    return scheduler.get_run_logs(job_id, limit)


@app.delete("/api/cron/{job_id}")
async def delete_cron_job(job_id: str, _=Depends(verify_api_key)):
    """Delete a cron job."""
    if scheduler.delete_job(job_id):
        return {"ok": True}
    raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")


# --- Channels ---
class WebhookMessage(BaseModel):
    text: str
    user_id: str = "webhook_user"
    chat_id: str = "default"
    metadata: dict = {}


@app.post("/api/webhook/{channel_name}")
async def webhook_message(channel_name: str, msg: WebhookMessage, _=Depends(verify_api_key)):
    """Receive a message via webhook channel."""
    try:
        from channels.router import channel_router
        result = await channel_router.route(
            channel_name=channel_name,
            chat_id=msg.chat_id,
            user_id=msg.user_id,
            text=msg.text,
            metadata=msg.metadata,
        )
        return {"ok": True, "reply": result}
    except ImportError:
        raise HTTPException(status_code=501, detail="Channels not available")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- Health ---
@app.get("/api/health")
async def health():
    data = {
        "status": "ok",
        "model": agent.model,
        "provider": agent.provider_name,
        "tools": len(tool_registry.list_tools()),
        "toolsets": list(tool_registry.list_toolsets().keys()),
        "sessions": len(agent._sessions),
        "memories": len(agent.memory.list_all()),
        "skills": len(agent.skills.list_all()),
        "plugins": list(plugin_loader.plugins.keys()),
        "mcp_servers": len(mcp_bridge.get_server_info()),
        "cron_jobs": len(scheduler.list_jobs()),
    }
    try:
        from channels.router import channel_router
        data["channels"] = [c["name"] for c in channel_router.get_status() if c.get("enabled")]
    except Exception:
        data["channels"] = []
    return data


# Mount static files last
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/assets", StaticFiles(directory=str(STATIC_DIR / "assets")), name="assets")


# --- User Config (Provider API Keys + TTS/STT) ---
from providers.registry import list_providers


class ProviderKeyRequest(BaseModel):
    api_key: str


class TTSConfigRequest(BaseModel):
    provider: str | None = None
    mimo_api_key: str | None = None


class ModelSwitchRequest(BaseModel):
    provider: str
    model: str


@app.get("/api/config")
async def get_config(_=Depends(verify_api_key)):
    """Get full user configuration (keys masked)."""
    cfg = load_config()
    # Mask API keys for security
    for pname, pcfg in cfg.get("providers", {}).items():
        key = pcfg.get("api_key", "")
        if key and len(key) > 8:
            pcfg["api_key"] = key[:4] + "****" + key[-4:]
    tts = cfg.get("tts", {})
    if tts.get("mimo_api_key") and len(tts["mimo_api_key"]) > 8:
        tts["mimo_api_key"] = tts["mimo_api_key"][:4] + "****"
    return cfg


@app.get("/api/config/providers")
async def get_provider_configs(_=Depends(verify_api_key)):
    """List all providers with their configuration status."""
    providers = list_providers()
    result = []
    for p in providers:
        key = get_provider_key(p.name)
        has_key = bool(key and len(key) > 4)
        result.append({
            "name": p.name,
            "display_name": p.display_name,
            "base_url": p.base_url,
            "models": p.models,
            "context_window": p.context_window,
            "supports_vision": p.supports_vision,
            "api_key_configured": has_key,
            "anthropic_base_url": getattr(p, "anthropic_base_url", "") or "",
            "active_base_url": p.resolve_base_url(),
            "active_protocol": ("anthropic" if ("/anthropic" in p.resolve_base_url() or p.resolve_base_url().rstrip("/").endswith("/api/coding")) else "openai"),
            "api_key_preview": (key[:4] + "****" + key[-4:]) if has_key and len(key) > 8 else ("已配置" if has_key else ""),
        })
    return {"providers": result, "total": len(result), "system_prompt": get_system_prompt()}


@app.post("/api/config/provider/{provider_name}/key")
async def set_provider_api_key(provider_name: str, req: ProviderKeyRequest, _=Depends(verify_api_key)):
    """Set API key for a provider."""
    if not req.api_key or len(req.api_key.strip()) < 4:
        raise HTTPException(status_code=400, detail="API key too short")
    set_provider_key(provider_name, req.api_key.strip())
    return {"ok": True, "provider": provider_name, "message": f"{provider_name} API Key 已保存"}


@app.get("/api/config/tts")
async def get_tts_configuration(_=Depends(verify_api_key)):
    """Get TTS configuration."""
    tts = get_tts_config()
    if tts.get("mimo_api_key") and len(tts["mimo_api_key"]) > 8:
        tts["mimo_api_key"] = tts["mimo_api_key"][:4] + "****"
    return tts


@app.post("/api/config/tts")
async def update_tts_configuration(req: TTSConfigRequest, _=Depends(verify_api_key)):
    """Update TTS configuration."""
    set_tts_config(provider=req.provider, mimo_api_key=req.mimo_api_key)
    return {"ok": True, "message": "TTS 配置已更新"}


@app.get("/api/config/stt")
async def get_stt_configuration(_=Depends(verify_api_key)):
    """Get STT configuration."""
    return get_stt_config()


@app.post("/api/config/model")
async def switch_model(req: ModelSwitchRequest, _=Depends(verify_api_key)):
    """Switch the active model (and optionally provider)."""
    from providers.registry import get as get_provider

    provider = get_provider(req.provider)
    if not provider:
        raise HTTPException(status_code=404, detail=f"Provider '{req.provider}' not found")
    if req.model not in provider.models:
        raise HTTPException(status_code=400, detail=f"Model '{req.model}' not available for '{req.provider}'")

    # Update agent
    if agent.provider_name != req.provider:
        agent.provider_name = req.provider
        agent.provider = provider
        # Rebuild context engine for new provider's context window
        from agent.context import ContextEngine
        agent.context = ContextEngine(context_window=provider.context_window)
    agent.model = req.model

    # Persist model preference
    set_model_preference(req.provider, req.model)

    return {
        "ok": True,
        "provider": req.provider,
        "model": req.model,
        "message": f"已切换到 {provider.display_name} / {req.model}"
    }


class SystemPromptRequest(BaseModel):
    system_prompt: str


@app.post("/api/config/system-prompt")
async def set_system_prompt_api(req: SystemPromptRequest, _=Depends(verify_api_key)):
    """Save custom system prompt."""
    try:
        set_system_prompt(req.system_prompt)
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- Embedding Config ---
class EmbeddingConfigRequest(BaseModel):
    base_url: str = ""
    model: str = ""
    api_key: str = ""


@app.get("/api/config/embedding")
async def get_embedding_config_api(_=Depends(verify_api_key)):
    """Get embedding API configuration."""
    cfg = get_embedding_config()
    # Mask API key for security
    if cfg.get("api_key") and len(cfg["api_key"]) > 8:
        cfg["api_key_masked"] = cfg["api_key"][:4] + "****" + cfg["api_key"][-4:]
        cfg["api_key"] = True
    else:
        cfg["api_key_masked"] = ""
        cfg["api_key"] = bool(cfg.get("api_key"))
    return cfg


@app.post("/api/config/embedding")
async def set_embedding_config_api(req: EmbeddingConfigRequest, _=Depends(verify_api_key)):
    """Save embedding API configuration."""
    try:
        # Don't overwrite existing key with empty string
        existing = get_embedding_config()
        api_key = req.api_key if req.api_key.strip() else existing.get("api_key", "")
        set_embedding_config(
            api_key=api_key,
            base_url=req.base_url.strip(),
            model=req.model.strip(),
        )
        cfg = get_embedding_config()
        if cfg.get("api_key") and len(cfg["api_key"]) > 8:
            cfg["api_key_masked"] = cfg["api_key"][:4] + "****" + cfg["api_key"][-4:]
            cfg["api_key"] = True
        else:
            cfg["api_key_masked"] = ""
            cfg["api_key"] = bool(cfg.get("api_key"))
        return cfg
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/kb/reembed")
async def reembed_knowledge(_=Depends(verify_api_key)):
    """Re-embed all knowledge entries using current embedding method."""
    try:
        from knowledge.base import KnowledgeBase
        import os
        kb_path = os.path.join(os.getenv("AGENT_HOME", "/opt/agent-framework"), "data", "knowledge.db")
        kb = KnowledgeBase(db_path=kb_path)
        result = kb.reembed_all()
        from knowledge.embedding import get_embedding_info
        result["embedding_info"] = get_embedding_info()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- Knowledge Base Documents ---

@app.get("/api/kb/documents")
async def list_kb_documents(_=Depends(verify_api_key)):
    """List knowledge base documents with stats."""
    try:
        from knowledge.base import KnowledgeBase
        import os
        kb_path = os.path.join(os.getenv("AGENT_HOME", "/opt/agent-framework"), "data", "knowledge.db")
        kb = KnowledgeBase(db_path=kb_path)
        entries = kb.list_entries()
        stats = kb.stats()
        return {"documents": entries, "stats": stats}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/kb/documents")
async def upload_kb_document(file: UploadFile = File(...), _=Depends(verify_api_key)):
    """Upload a document to the knowledge base.

    Supports txt, md, pdf, docx files. Text is extracted and stored.
    """
    try:
        from knowledge.base import KnowledgeBase
        import os
        kb_path = os.path.join(os.getenv("AGENT_HOME", "/opt/agent-framework"), "data", "knowledge.db")
        kb = KnowledgeBase(db_path=kb_path)

        # Read file content
        raw = await file.read()
        filename = file.filename or "untitled"
        ext = os.path.splitext(filename)[1].lower()

        # Extract text based on file type
        if ext in (".txt", ".md"):
            content = raw.decode("utf-8", errors="ignore")
        elif ext == ".pdf":
            # Placeholder: PDF text extraction not implemented inline
            content = f"[PDF content placeholder for {filename}]"
        elif ext == ".docx":
            # Placeholder: DOCX text extraction not implemented inline
            content = f"[DOCX content placeholder for {filename}]"
        else:
            # Fallback: try utf-8 decode
            content = raw.decode("utf-8", errors="ignore")

        title = os.path.splitext(filename)[0]
        entry = kb.add(
            title=title,
            content=content,
            category="uploaded",
            source=filename,
        )
        return {"status": "ok", "entry": entry}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/kb/documents/{entry_id}")
async def delete_kb_document(entry_id: str, _=Depends(verify_api_key)):
    """Delete a knowledge base document by entry id."""
    try:
        from knowledge.base import KnowledgeBase
        import os
        kb_path = os.path.join(os.getenv("AGENT_HOME", "/opt/agent-framework"), "data", "knowledge.db")
        kb = KnowledgeBase(db_path=kb_path)
        result = kb.delete(entry_id)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/kb/stats")
async def kb_stats(_=Depends(verify_api_key)):
    """Get knowledge base statistics and categories."""
    try:
        from knowledge.base import KnowledgeBase
        import os
        kb_path = os.path.join(os.getenv("AGENT_HOME", "/opt/agent-framework"), "data", "knowledge.db")
        kb = KnowledgeBase(db_path=kb_path)
        stats = kb.stats()
        categories = kb.list_categories()
        return {"stats": stats, "categories": categories}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- Inference Parameters ---

class ParamsRequest(BaseModel):
    temperature: float = 0.7
    top_p: float = 0.9


@app.get("/api/config/params")
async def get_inference_params(_=Depends(verify_api_key)):
    """Get inference parameters (temperature, top_p)."""
    try:
        cfg = load_config()
        params = cfg.get("inference_params", {})
        return {
            "temperature": params.get("temperature", 0.7),
            "top_p": params.get("top_p", 0.9),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/config/params")
async def save_inference_params(req: ParamsRequest, _=Depends(verify_api_key)):
    """Save inference parameters (temperature, top_p) to user config."""
    try:
        cfg = load_config()
        cfg.setdefault("inference_params", {})
        cfg["inference_params"]["temperature"] = req.temperature
        cfg["inference_params"]["top_p"] = req.top_p
        save_config(cfg)
        return {"status": "ok", "temperature": req.temperature, "top_p": req.top_p}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- System Prompt (GET) ---

@app.get("/api/config/system-prompt")
async def get_system_prompt_api(_=Depends(verify_api_key)):
    """Get current system prompt."""
    try:
        return {"system_prompt": get_system_prompt()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- Knowledge Graph (sphere) ---

@app.get("/api/kb/graph")
async def kb_graph(_=Depends(verify_api_key)):
    """返回知识记忆生命球体的节点/边/统计，供前端 Canvas2D 渲染。"""
    import os, sqlite3, json, math
    from collections import defaultdict, Counter
    base = os.getenv("AGENT_HOME", "/opt/agent-framework")
    data_dir = os.path.join(base, "data")

    def _vec(blob):
        if blob is None:
            return None
        if isinstance(blob, (bytes, bytearray)):
            try:
                import array
                a = array.array("f")
                a.frombytes(bytes(blob))
                if len(a) > 0:
                    return list(a)
            except Exception:
                pass
            return None
        try:
            arr = json.loads(blob) if isinstance(blob, str) else blob
            if isinstance(arr, list) and len(arr) > 0:
                return [float(x) for x in arr]
        except Exception:
            pass
        return None

    def _conn(name):
        return sqlite3.connect(os.path.join(data_dir, name))

    nodes = []
    vecs = {}
    try:
        c = _conn("knowledge.db")
        for r in c.execute("SELECT id, title, content, category, embedding FROM knowledge"):
            v = _vec(r[4]); nid = "k:%s" % r[0]
            nodes.append({"id": nid, "type": "knowledge", "label": r[1] or "知识", "text": (r[2] or "")[:240], "category": r[3] or ""})
            if v: vecs[nid] = v
        c.close()
    except Exception as e:
        logger_auth.warning("kb_graph_knowledge", err=str(e))
    try:
        c = _conn("memory.db")
        for r in c.execute("SELECT id, key, content, category, graph_vec FROM memories"):
            v = _vec(r[4]); nid = "m:%s" % r[0]
            nodes.append({"id": nid, "type": "user_memory", "label": r[1] or (r[2] or "")[:30], "text": (r[2] or "")[:240], "category": r[3] or ""})
            if v: vecs[nid] = v
        c.close()
    except Exception as e:
        logger_auth.warning("kb_graph_memory", err=str(e))
    try:
        c = _conn("semantic_memory.db")
        for r in c.execute("SELECT id, key, content, category, graph_vec FROM semantic_memories"):
            v = _vec(r[4]); nid = "s:%s" % r[0]
            nodes.append({"id": nid, "type": "semantic", "label": r[1] or (r[2] or "")[:30], "text": (r[2] or "")[:240], "category": r[3] or ""})
            if v: vecs[nid] = v
        for r in c.execute("SELECT id, event_type, description, details, graph_vec FROM episodic_events"):
            v = _vec(r[4]); nid = "e:%s" % r[0]
            nodes.append({"id": nid, "type": "episodic", "label": r[1] or "事件", "text": ((r[2] or "") + " " + (r[3] or ""))[:240], "category": ""})
            if v: vecs[nid] = v
        c.close()
    except Exception as e:
        logger_auth.warning("kb_graph_semantic", err=str(e))
    try:
        c = _conn("lessons.db")
        for r in c.execute("SELECT id, title, lesson_type, description, graph_vec FROM lessons"):
            v = _vec(r[4]); nid = "l:%s" % r[0]
            nodes.append({"id": nid, "type": "lesson", "label": r[1] or "经验", "text": (r[3] or "")[:240], "category": r[2] or ""})
            if v: vecs[nid] = v
        c.close()
    except Exception as e:
        logger_auth.warning("kb_graph_lessons", err=str(e))

    # 斐波那契球面坐标，保证前端 3D 投影有有效 x/y/z
    N = len(nodes)
    golden = math.pi * (3 - math.sqrt(5))
    for i, n in enumerate(nodes):
        if N == 1:
            n["x"], n["y"], n["z"] = 0.0, 0.0, 1.0
        else:
            yy = 1 - (i / (N - 1)) * 2
            rad = math.sqrt(max(0.0, 1 - yy * yy))
            theta = golden * i
            n["x"] = round(math.cos(theta) * rad, 4)
            n["y"] = round(yy, 4)
            n["z"] = round(math.sin(theta) * rad, 4)

    node_by_id = {n["id"]: n for n in nodes}
    type_of = {n["id"]: n["type"] for n in nodes}

    edges = []
    CROSS_THRESH = 0.42
    try:
        import numpy as np
        ids = list(vecs.keys())
        if ids:
            M = np.array([vecs[i] for i in ids], dtype=np.float32)
            norms = np.linalg.norm(M, axis=1, keepdims=True)
            Mn = M / (norms + 1e-9)
            S = (Mn @ Mn.T).tolist()
            intra_cap = defaultdict(list)
            per_node_cross = defaultdict(list)
            N = len(ids)
            for i in range(N):
                for j in range(i + 1, N):
                    s = S[i][j]
                    if s < 0.3:
                        continue
                    ti = type_of[ids[i]]; tj = type_of[ids[j]]
                    if ti == tj:
                        if s > 0.3:
                            intra_cap[ids[i]].append((s, ids[j]))
                            intra_cap[ids[j]].append((s, ids[i]))
                    elif s >= CROSS_THRESH:
                        per_node_cross[ids[i]].append((s, ids[j]))
                        per_node_cross[ids[j]].append((s, ids[i]))
            for nid, lst in intra_cap.items():
                lst.sort(reverse=True)
                for s, other in lst[:3]:
                    edges.append({"source": nid, "target": other, "rel": "related", "weight": round(s, 3)})
            for nid, lst in per_node_cross.items():
                lst.sort(reverse=True)
                for s, other in lst[:4]:
                    edges.append({"source": nid, "target": other, "rel": "semantic", "weight": round(s, 3)})
    except Exception as e:
        logger_auth.warning("kb_graph_sim", err=str(e))

    # 手动语义关系 (P1-3)
    manual_pairs = set()
    try:
        c = _conn("graph.db")
        c.execute("CREATE TABLE IF NOT EXISTS graph_relations(id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT, target TEXT, rel TEXT, note TEXT, created_at TEXT)")
        for r in c.execute("SELECT id, source, target, rel, note FROM graph_relations"):
            rid, src, tgt, rel, note = r
            if src in node_by_id and tgt in node_by_id:
                edges.append({"source": src, "target": tgt, "rel": rel, "manual": True, "rid": rid, "note": note})
                manual_pairs.add((src, tgt) if src < tgt else (tgt, src))
        c.close()
    except Exception as e:
        logger_auth.warning("kb_graph_manual", err=str(e))

    # 手动边优先：剔除同 pair 的自动边
    if manual_pairs:
        edges = [e for e in edges if e.get("manual") or ((e["source"], e["target"]) if e["source"] < e["target"] else (e["target"], e["source"])) not in manual_pairs]

    # 节点重要度：类型基线 + 连接度归一化（驱动前端节点点半径）
    deg = Counter()
    for e in edges:
        deg[e["source"]] = deg.get(e["source"], 0) + 1
        deg[e["target"]] = deg.get(e["target"], 0) + 1
    type_base = {"knowledge": 0.8, "user_memory": 0.65, "semantic": 0.5, "episodic": 0.4, "lesson": 0.6}
    mdr = math.sqrt(max(deg.values())) if deg else 1.0
    for n in nodes:
        d = deg.get(n["id"], 0)
        norm = (math.sqrt(d) / mdr) if mdr > 0 else 0.0
        n["importance"] = round(min(1.2, type_base.get(n["type"], 0.5) + norm * 0.5), 3)

    stats = {
        "total": len(nodes),
        "edges": len(edges),
        "knowledge": sum(1 for n in nodes if n["type"] == "knowledge"),
        "user_memory": sum(1 for n in nodes if n["type"] == "user_memory"),
        "semantic": sum(1 for n in nodes if n["type"] == "semantic"),
        "episodic": sum(1 for n in nodes if n["type"] == "episodic"),
        "lesson": sum(1 for n in nodes if n["type"] == "lesson"),
    }
    return {"nodes": nodes, "edges": edges, "stats": stats}


class RelationRequest(BaseModel):
    source: str
    target: str
    rel: str
    note: str | None = None


@app.post("/api/kb/graph/relations")
async def add_relation(req: RelationRequest, _=Depends(verify_api_key)):
    """新增手动语义关系 (P1-3)。"""
    import os, sqlite3
    from datetime import datetime
    base = os.getenv("AGENT_HOME", "/opt/agent-framework")
    c = sqlite3.connect(os.path.join(base, "data", "graph.db"))
    c.execute("CREATE TABLE IF NOT EXISTS graph_relations(id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT, target TEXT, rel TEXT, note TEXT, created_at TEXT)")
    cur = c.execute("INSERT INTO graph_relations(source, target, rel, note, created_at) VALUES(?,?,?,?,?)",
                    (req.source, req.target, req.rel, req.note, datetime.utcnow().isoformat()))
    rid = cur.lastrowid
    c.commit(); c.close()
    return {"id": rid, "source": req.source, "target": req.target, "rel": req.rel, "manual": True}


@app.delete("/api/kb/graph/relations/{rel_id}")
async def del_relation(rel_id: int, _=Depends(verify_api_key)):
    """删除手动语义关系 (P1-3)。"""
    import os, sqlite3
    base = os.getenv("AGENT_HOME", "/opt/agent-framework")
    c = sqlite3.connect(os.path.join(base, "data", "graph.db"))
    c.execute("DELETE FROM graph_relations WHERE id=?", (rel_id,))
    c.commit(); c.close()
    return {"ok": True}


@app.get("/api/timeline")
async def get_timeline(limit: int = 300, offset: int = 0, _=Depends(verify_api_key)):
    """会话事件时间线 (P1-4)：把每轮展开为 user/tool/assistant 事件。"""
    import os, sqlite3, json
    base = os.getenv("AGENT_HOME", "/opt/agent-framework")
    c = sqlite3.connect(os.path.join(base, "data", "interactions.db"))
    try:
        total = list(c.execute("SELECT COUNT(*) FROM interactions"))[0][0]
    except Exception:
        total = 0
    rows = list(c.execute(
        "SELECT id, timestamp, user_msg, assistant_msg, tools_used, outcome, score FROM interactions ORDER BY id DESC LIMIT ? OFFSET ?",
        (limit, offset)))
    events = []
    for r in rows:
        iid, ts, um, am, tu, outcome, score = r
        events.append({"id": "%s-u" % iid, "turn_id": iid, "kind": "user", "ts": ts, "text": um or "", "meta": {}})
        try:
            tools = json.loads(tu) if tu else []
        except Exception:
            tools = []
        if isinstance(tools, list):
            for t in tools:
                if isinstance(t, str):
                    tname = t
                elif isinstance(t, dict):
                    tname = t.get("name") or t.get("tool") or "工具"
                else:
                    tname = str(t)
                events.append({"id": "%s-t" % iid, "turn_id": iid, "kind": "tool", "ts": ts, "text": tname, "meta": {}})
        events.append({"id": "%s-a" % iid, "turn_id": iid, "kind": "assistant", "ts": ts, "text": am or "", "meta": {"outcome": outcome, "score": score}})
    c.close()
    return {"events": events, "total": total, "limit": limit, "offset": offset}


# --- Learning loop (SelfLearningEngine) ---
@app.get("/api/learning/insights")
async def learning_insights(_=Depends(verify_api_key)):
    """只读：返回失败模式、统计与近期经验教训（持续学习闭环的可见层）。"""
    try:
        from agent.learner import LearningEngine
        eng = LearningEngine()
        stats = eng.tracker.get_stats()
        failures = eng.tracker.get_failure_patterns(limit=10)
        lessons = eng.lessons_db.get_all(limit=20)
        return {"stats": stats, "failure_patterns": failures, "lessons": lessons}
    except Exception as e:
        return {"stats": {}, "failure_patterns": [], "lessons": [], "error": str(e)}


@app.post("/api/learning/scan")
async def learning_scan(_=Depends(verify_api_key)):
    """主动扫描近期会话，喂入 SelfLearningEngine 形成持续学习闭环。"""
    try:
        from agent.learner import LearningEngine
        eng = LearningEngine()
        sessions = list(agent._sessions.values())[-20:] if hasattr(agent, "_sessions") else []
        count = 0
        for s in sessions:
            msgs = getattr(s, "messages", None) or []
            user_msgs = [m for m in msgs if getattr(m, "role", "") == "user"]
            asst_msgs = [m for m in msgs if getattr(m, "role", "") == "assistant"]
            if not user_msgs or not asst_msgs:
                continue
            user_msg = user_msgs[0].content if hasattr(user_msgs[0], "content") else ""
            asst_msg = asst_msgs[-1].content if hasattr(asst_msgs[-1], "content") else ""
            tool_calls = []
            for m in msgs:
                for tc in (getattr(m, "tool_calls", None) or []):
                    name = getattr(tc, "name", None) or (
                        getattr(tc, "function", None) and getattr(tc.function, "name"))
                    err = getattr(tc, "error", None)
                    if name:
                        tool_calls.append({"name": name, "error": err})
            # 仅当有真实工具调用或明显成功时才记录
            eng.analyze_interaction(user_msg, asst_msg, tool_calls=tool_calls,
                                    outcome="success" if tool_calls else "partial")
            count += 1
        return {"ok": True, "scanned": count}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# --- Skills auto-extraction ---
class SessionExtractRequest(BaseModel):
    session_id: str = ""


async def _llm_chat(prompt: str, max_tokens: int = 2000) -> str:
    """复用 reasoning.py 的 LLM 调用模式（OpenAI 兼容）。"""
    from openai import AsyncOpenAI
    from providers.registry import get as get_provider
    import config
    provider = get_provider(config.DEFAULT_PROVIDER)
    api_key = os.getenv(provider.api_key_env, "")
    client = AsyncOpenAI(api_key=api_key, base_url=provider.base_url)
    resp = await client.chat.completions.create(
        model=config.DEFAULT_MODEL,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens, temperature=0.4,
    )
    return resp.choices[0].message.content or ""


@app.post("/api/skills/extract-from-session")
async def extract_skill_from_session(req: SessionExtractRequest, _=Depends(verify_api_key)):
    """从一次会话的工具编排链自动起草可复用技能（直接保存为技能草稿）。"""
    try:
        if not req.session_id:
            return {"ok": False, "error": "session_id required"}
        session = agent.get_or_create_session(req.session_id)
        msgs = getattr(session, "messages", []) or []
        tool_chain = []
        user_prompt = ""
        for m in msgs:
            role = getattr(m, "role", "")
            if role == "user" and not user_prompt:
                c = getattr(m, "content", "")
                user_prompt = c if isinstance(c, str) else ""
            if role == "assistant":
                for tc in (getattr(m, "tool_calls", None) or []):
                    fn = getattr(tc, "function", None)
                    name = getattr(tc, "name", None) or (fn and getattr(fn, "name"))
                    args = fn and getattr(fn, "arguments", "")
                    if name:
                        tool_chain.append({"name": name, "args": args})
        if not tool_chain:
            return {"ok": False, "error": "该会话未检测到工具调用，无法提取技能"}
        chain_text = "\n".join(
            f"{i+1}. {t['name']}" + (f"({t['args']})" if t.get("args") else "")
            for i, t in enumerate(tool_chain))
        prompt = (
            "你是技能提取器。根据下面的对话意图与工具编排链，起草一个可复用技能。\n"
            f"用户意图：{user_prompt[:400]}\n"
            f"工具编排链：\n{chain_text}\n\n"
            "只输出 JSON：{\"name\":\"snake_case_name\",\"description\":\"何时使用\","
            "\"content\":\"逐步操作 markdown\",\"tags\":\"逗号分隔标签\"}"
        )
        text = await _llm_chat(prompt, max_tokens=1500)
        import re as _re
        m = _re.search(r"\{[\s\S]*\}", text)
        data = json.loads(m.group()) if m else {}
        name = data.get("name")
        if not name:
            return {"ok": False, "error": "LLM 未返回有效技能"}
        is_new = agent.skills.save(name, data.get("description", ""),
                                   data.get("content", ""), data.get("tags", ""))
        return {"ok": True, "name": name, "created": is_new, "skill": data}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# --- Feedback ---

class FeedbackRequest(BaseModel):
    session_id: str
    message_index: int
    feedback: str  # "like" or "dislike"


@app.post("/api/feedback")
async def submit_feedback(req: FeedbackRequest, _=Depends(verify_api_key)):
    """Record message feedback (like/dislike)."""
    try:
        logger = get_logger("feedback")
        logger.info(
            "message_feedback",
            session_id=req.session_id,
            message_index=req.message_index,
            feedback=req.feedback,
        )
        return {"status": "ok", "message": "Feedback recorded"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



# --- 自定义轻量限流中间件（兜底全端点；slowapi 装饰器在该环境未触发）---
import time
from collections import defaultdict, deque
from fastapi import Request
from fastapi.responses import JSONResponse

_rl_hits = defaultdict(deque)

@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    path = request.url.path
    if path in ("/health", "/metrics", "/") or path.startswith("/static") or path.startswith("/api/health"):
        return await call_next(request)
    client = request.client.host if request.client else "unknown"
    now = time.time()
    limit = 10 if path == "/api/auth/login" else 60
    dq = _rl_hits[client]
    while dq and dq[0] <= now - 60:
        dq.popleft()
    if len(dq) >= limit:
        retry = int(60 - (now - dq[0])) + 1
        return JSONResponse(status_code=429, content={"error": "rate_limit_exceeded", "retry_after": retry})
    dq.append(now)
    return await call_next(request)


# --- Provider protocol switching (OpenAI-compatible vs Anthropic) ---
class ProviderProtocolRequest(BaseModel):
    protocol: str  # "openai" | "anthropic"


@app.post("/api/config/provider/{provider_name}/protocol")
async def set_provider_protocol(provider_name: str, req: ProviderProtocolRequest, _=Depends(verify_api_key)):
    """Switch a provider between its OpenAI-compatible and Anthropic-compatible endpoint."""
    from providers.registry import get as _get_provider
    from core.user_config import set_provider_override
    p = _get_provider(provider_name)
    if not p:
        raise HTTPException(status_code=404, detail=f"Provider '{provider_name}' not found")
    proto = (req.protocol or "").strip().lower()
    if proto == "anthropic":
        aurl = getattr(p, "anthropic_base_url", "") or ""
        if not aurl:
            raise HTTPException(status_code=400, detail=f"'{p.display_name}' 未提供 Anthropic 兼容端点")
        set_provider_override(provider_name, {"base_url": aurl})
    elif proto == "openai":
        set_provider_override(provider_name, {})
    else:
        raise HTTPException(status_code=400, detail="protocol 必须是 openai 或 anthropic")
    return {"ok": True, "provider": provider_name, "protocol": proto, "base_url": p.resolve_base_url()}
