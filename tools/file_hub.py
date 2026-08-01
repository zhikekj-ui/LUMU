"""LUMU 文件下发通道。

职责：
- register_file(): agent 把生成的文件登记进来，拷贝到受控存储 data/files/，分配 fid。
- flush_session_files(): 取走某会话已登记的文件，转为 SSE `file` 事件，并清空。
- get_file_meta(): 供 /api/files/{fid} 路由取元数据并下载。

fid 即临时下载令牌（UUID，不可猜），无需额外鉴权；文件生命周期随进程。
会话归属通过 contextvars 自动捕获（deliver_file 工具在对话上下文中调用），
回退到 "__default__"，避免跨会话串台。
"""
import os
import json
import uuid
import shutil
import logging
import contextvars

logger = logging.getLogger("lumu")

AGENT_HOME = os.getenv("AGENT_HOME", "/opt/agent-framework")
FILE_STORE = os.path.join(AGENT_HOME, "data", "files")

# 当前对话会话 id（在 chat_stream 入口 set），用于精确归属文件
_CUR_SESSION = contextvars.ContextVar("lumu_session", default="__default__")

# session_id -> [meta]
_SESSION_FILES: dict[str, list[dict]] = {}
# fid -> meta（含真实存储路径）
_FILE_INDEX: dict[str, dict] = {}

# 索引持久化到磁盘：进程重启后 /api/files/{fid} 仍可下载（文件本体本就落盘在 data/files/）
_INDEX_PATH = os.path.join(FILE_STORE, ".index.json")


def _save_index():
    try:
        os.makedirs(FILE_STORE, exist_ok=True)
        tmp = _INDEX_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(_FILE_INDEX, fh, ensure_ascii=False)
        os.replace(tmp, _INDEX_PATH)
    except Exception as e:
        logger.warning("save file index failed: %s", e)


def _load_index():
    try:
        # 1) 若已持久化索引，先载入（剔除磁盘已删除的失效条目）
        if os.path.isfile(_INDEX_PATH):
            with open(_INDEX_PATH, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            _FILE_INDEX.update({k: v for k, v in data.items() if os.path.isfile(v.get("path", ""))})
        # 2) 始终扫描磁盘：把索引里缺失的磁盘文件补进索引（磁盘为最终真相源）
        if os.path.isdir(FILE_STORE):
            for fn in os.listdir(FILE_STORE):
                if fn.startswith("."):
                    continue
                full = os.path.join(FILE_STORE, fn)
                if not os.path.isfile(full):
                    continue
                fid, _ext = os.path.splitext(fn)
                if fid not in _FILE_INDEX:
                    _FILE_INDEX[fid] = {
                        "id": fid, "name": fn,
                        "mime": guess_mime(full),
                        "size": os.path.getsize(full),
                        "path": full,
                    }
        if _FILE_INDEX:
            logger.info("file index loaded: %d entries", len(_FILE_INDEX))
            _save_index()
    except Exception as e:
        logger.warning("load file index failed: %s", e)


_MIME_MAP = {
    ".mp3": "audio/mpeg", ".wav": "audio/wav", ".ogg": "audio/ogg", ".m4a": "audio/mp4",
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
    ".svg": "image/svg+xml", ".webp": "image/webp",
    ".mp4": "video/mp4", ".webm": "video/webm",
    ".pdf": "application/pdf", ".zip": "application/zip", ".json": "application/json",
    ".md": "text/markdown", ".txt": "text/plain", ".csv": "text/csv",
    ".py": "text/plain", ".js": "text/plain", ".html": "text/html", ".css": "text/css",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def guess_mime(path: str) -> str:
    return _MIME_MAP.get(os.path.splitext(path)[1].lower(), "application/octet-stream")


def register_file(session_id, path: str, name: str | None = None, mime: str | None = None) -> str | None:
    """登记文件到下发通道，返回 fid；失败返回 None。session_id 为 None 时取当前上下文会话。"""
    try:
        sid = session_id or _CUR_SESSION.get()
        p = path if os.path.isabs(path) else os.path.join(AGENT_HOME, path)
        if not os.path.isfile(p):
            logger.warning("register_file: not a file: %s", p)
            return None
        os.makedirs(FILE_STORE, exist_ok=True)
        fid = str(uuid.uuid4())
        ext = os.path.splitext(p)[1] or ""
        dest = os.path.join(FILE_STORE, fid + ext)
        shutil.copy2(p, dest)
        size = os.path.getsize(dest)
        meta = {
            "id": fid,
            "name": name or os.path.basename(p),
            "mime": mime or guess_mime(p),
            "size": size,
            "path": dest,
        }
        _FILE_INDEX[fid] = meta
        _SESSION_FILES.setdefault(sid, []).append(meta)
        _save_index()
        logger.info("register_file ok: %s -> %s (%s) session=%s", p, fid, meta["name"], sid)
        return fid
    except Exception as e:
        logger.warning("register_file failed: %s", e)
        return None


def flush_session_files(session_id: str) -> list[dict]:
    """取走该会话已登记的文件，转为 SSE `file` 事件列表并清空。"""
    out = []
    for key in (session_id, "__default__"):
        for m in _SESSION_FILES.pop(key, []):
            out.append({
                "type": "file",
                "file": {"id": m["id"], "name": m["name"], "mime": m["mime"], "size": m["size"]},
            })
    return out


def get_file_meta(fid: str) -> dict | None:
    return _FILE_INDEX.get(fid)


# 模块加载末尾再执行索引加载（确保 guess_mime 等均已定义）
_load_index()
