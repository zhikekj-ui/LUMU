"""SKILL.md 技能包热加载器。

文件式技能包：skills/packs/<pack_name>/SKILL.md
与 SQLite 技能库（manager.py）互补：
  - SQLite 库 = 模型自己沉淀的经验（skill_save 工具写入）
  - SKILL.md 包 = 人类维护的技能包，git 可管理、放入即生效（热加载，无需重启）

SKILL.md 格式（frontmatter + 正文）：
    ---
    name: server-ops
    description: 服务器运维操作规范
    triggers: 部署,重启,nginx,systemd
    always: false
    ---
    # 正文（markdown，注入给模型的完整指令）

注入策略（在每条消息构建系统提示时调用，天然热加载）：
  - 索引块：所有包的 name+description 常驻系统提示（轻量）
  - 全文块：always: true 的包恒注入；用户消息命中 triggers 关键词的包注入
  - 其余包由模型通过 skill_pack_read 工具按需读取
"""
import os
from pathlib import Path

PACKS_DIR = Path(os.getenv("AGENT_HOME", str(Path(__file__).resolve().parent.parent))) / "skills" / "packs"

# mtime 缓存：path -> (mtime, parsed_dict)
_cache: dict = {}

MAX_INLINE_CHARS = 6000   # 单个包全文注入上限
MAX_TOTAL_INLINE = 15000  # 所有全文注入总上限


def _parse_skill_md(path: Path) -> dict | None:
    """解析 SKILL.md：frontmatter + 正文。解析失败返回 None。"""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None
    meta = {"name": path.parent.name, "description": "", "triggers": [], "always": False}
    body = text
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            fm, body = parts[1], parts[2]
            for line in fm.splitlines():
                line = line.strip()
                if ":" not in line:
                    continue
                k, _, v = line.partition(":")
                k, v = k.strip().lower(), v.strip().strip("\"'")
                if k == "name" and v:
                    meta["name"] = v
                elif k == "description":
                    meta["description"] = v
                elif k == "triggers":
                    meta["triggers"] = [t.strip().lower() for t in v.replace("，", ",").split(",") if t.strip()]
                elif k == "always":
                    meta["always"] = v.lower() in ("true", "yes", "1")
    meta["content"] = body.strip()
    return meta


def scan_packs() -> list[dict]:
    """扫描 packs 目录，带 mtime 缓存。每次调用都重新列目录（热加载核心）。"""
    packs = []
    if not PACKS_DIR.is_dir():
        return packs
    stale_keys = set(_cache.keys())
    try:
        for d in sorted(PACKS_DIR.iterdir()):
            md = d / "SKILL.md"
            if not (d.is_dir() and md.is_file()):
                continue
            key = str(md)
            stale_keys.discard(key)
            try:
                mtime = md.stat().st_mtime
            except OSError:
                continue
            cached = _cache.get(key)
            if cached and cached[0] == mtime:
                packs.append(cached[1])
                continue
            parsed = _parse_skill_md(md)
            if parsed:
                _cache[key] = (mtime, parsed)
                packs.append(parsed)
    except Exception:
        return packs
    # 清理已删除的包
    for k in stale_keys:
        _cache.pop(k, None)
    return packs


def get_pack(name: str) -> dict | None:
    for p in scan_packs():
        if p["name"] == name:
            return p
    return None


def build_skill_block(user_message: str | None = None) -> str:
    """构建注入系统提示的技能块：索引 + 命中/常驻包的全文。"""
    packs = scan_packs()
    if not packs:
        return ""
    lines = ["## 可用技能包（SKILL.md，放入 skills/packs/ 即热加载）"]
    inline: list[dict] = []
    msg = (user_message or "").lower()
    for p in packs:
        mark = ""
        hit = p["always"] or (msg and any(t in msg for t in p["triggers"]))
        if hit:
            inline.append(p)
            mark = "（已展开）"
        lines.append(f"- {p['name']}: {p['description']}{mark}")
    lines.append("未展开的技能包可用 skill_pack_read 工具读取全文后再执行任务。")

    total = 0
    for p in inline:
        content = p["content"][:MAX_INLINE_CHARS]
        if total + len(content) > MAX_TOTAL_INLINE:
            break
        total += len(content)
        lines.append(f"\n### [技能包] {p['name']}\n{content}")
    return "\n".join(lines)
