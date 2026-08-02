"""Runtime self-introspection tool — lets LUMU query EVERYTHING about itself.

LUMU 即运行时本体。用户问“你是谁 / 你用的什么模型 / 你有哪些能力 / 你的记忆 /
你的配置 / 你的运行环境 / 你支持哪些模型 / 你是哪个版本”等一切关于自身的问题时，
它应当能 *查询* 自己的真实实时状态，而不是猜或调不存在的接口。
本工具读取全局 agent 实例 (_agent_instance) 与其配置/记忆模块，返回结构化全景。

安全约定（隐私红线）：
- 所有密钥一律脱敏：只给“已配置/未配置”布尔或掩码，绝不返回明文。
- 长期记忆只统计条数与分类，绝不输出记忆正文。
- system prompt 只给状态 + 长度 + 预览，绝不返回全文（避免暴露实现细节与循环）。
"""
import os
import sys
import time
import json
import platform
import socket


def get_runtime_info() -> str:
    A = "  "
    lines = []
    lines.append("【LUMU 本体自我认知 · 实时全景】")
    lines.append(f"{A}身份：LUMU —— 开源 AI agent 框架，本体即当前运行实例")
    lines.append(f"{A}说明：以下均为 LUMU 此刻真实状态，可据实回答关于自身的一切问题。")

    # ── 全局 agent 实例 ──
    try:
        from agent.core import _agent_instance
        a = _agent_instance
    except Exception:
        a = None
    if a is None:
        return "运行时信息不可用：agent 实例尚未初始化。"

    # ── 1. 当前模型与供应商 ──
    provider = getattr(a, "provider", None)
    provider_name = getattr(a, "provider_name", "")
    provider_disp = (getattr(provider, "display_name", "") or provider_name) if provider else provider_name
    model = getattr(a, "model", "")

    base_host = ""
    try:
        if provider and hasattr(provider, "resolve_base_url"):
            b = provider.resolve_base_url()
            if b:
                from urllib.parse import urlparse
                base_host = urlparse(b).netloc or b
    except Exception:
        base_host = ""

    key_cfg = False
    try:
        if provider and hasattr(provider, "resolve_api_key"):
            k = provider.resolve_api_key()
            key_cfg = bool(k and len(k) > 8)
    except Exception:
        key_cfg = False

    lines.append(f"\n{A}一、当前运行模型")
    lines.append(f"{A*2}底层大模型：{model}")
    lines.append(f"{A*2}供应商：{provider_disp}（内部名 {provider_name}）")
    lines.append(f"{A*2}API 端点 host：{base_host or '未知'}（已脱敏，不含路径/密钥）")
    lines.append(f"{A*2}API Key 已配置：{'是' if key_cfg else '否'}")

    # ── 2. 能力清单（域 + 工具数） ──
    tool_count = "?"
    try:
        ts = a.tools.list_toolsets()
        domain_count = len(ts)
        tool_count = sum(len(v) for v in ts.values())
        lines.append(f"\n{A}二、能力清单")
        lines.append(f"{A*2}能力域：{domain_count} 个，工具：{tool_count} 个")
        for dom, tools in ts.items():
            lines.append(f"{A*2}- {dom}：{len(tools)} 个工具")
    except Exception as e:
        lines.append(f"\n{A}二、能力清单：读取失败（{e}）")

    # ── 3. 已加载技能 ──
    try:
        sk = a.skills.list_all() if getattr(a, "skills", None) else []
        names = [
            (s.get("name") if isinstance(s, dict) else getattr(s, "name", str(s)))
            for s in sk
        ]
        names = [str(n) for n in names if n]
        lines.append(f"\n{A}三、已加载技能：{len(names)} 个")
        if names:
            lines.append(f"{A*2}" + "、".join(names))
    except Exception as e:
        lines.append(f"\n{A}三、已加载技能：读取失败（{e}）")

    # ── 4. 长期记忆（只统计，不输出正文） ──
    try:
        mm = a.memory
        all_mem = mm.list_all(None) if hasattr(mm, "list_all") else []
        total = len(all_mem)
        cats = {}
        for m in all_mem:
            c = m.get("category", "general") if isinstance(m, dict) else "general"
            cats[c] = cats.get(c, 0) + 1
        cat_line = "、".join(f"{k}×{v}" for k, v in cats.items()) or "无"
        lines.append(f"\n{A}四、长期记忆")
        lines.append(f"{A*2}已存条目：{total} 条（按分类：{cat_line}）")
        lines.append(f"{A*2}说明：记忆正文受隐私保护，此处仅统计数量与分类，不输出内容。")
    except Exception as e:
        lines.append(f"\n{A}四、长期记忆：读取失败（{e}）")

    # ── 5. 系统提示词状态（不返回全文） ──
    try:
        from core.user_config import get_system_prompt
        sp = get_system_prompt() or ""
        customized = len(sp) > 0
        has_identity = ("LUMU" in sp) or ("你是" in sp) or ("身份" in sp)
        preview = sp[:200].replace("\n", " ")
        lines.append(f"\n{A}五、系统提示词（system prompt）")
        lines.append(f"{A*2}已自定义：{'是' if customized else '否'}（长度 {len(sp)} 字）")
        lines.append(f"{A*2}含身份设定：{'是' if has_identity else '未知'}")
        if customized:
            lines.append(f"{A*2}预览（前 200 字）：{preview}{'…' if len(sp) > 200 else ''}")
    except Exception as e:
        lines.append(f"\n{A}五、系统提示词：读取失败（{e}）")

    # ── 6. 用户配置偏好（密钥脱敏） ──
    try:
        from core.user_config import (
            load_config, get_model_preference, get_tts_config,
            get_stt_config, get_embedding_config,
        )
        cfg = load_config()
        pref = get_model_preference()
        lines.append(f"\n{A}六、用户配置偏好（密钥已脱敏）")
        lines.append(f"{A*2}模型偏好：{pref.get('provider', '?')} / {pref.get('model', '?')}")
        provs = cfg.get("providers", {}) if isinstance(cfg, dict) else {}
        prov_names = [k for k in provs.keys() if k != "api_key"]
        lines.append(f"{A*2}已配置供应商：{('、'.join(prov_names)) if prov_names else '无'}")
        tts = get_tts_config() or {}
        tts_state = "已配置" if (isinstance(tts, dict) and (tts.get("default_provider") or tts.get("mimo_api_key"))) else "未配置"
        lines.append(f"{A*2}TTS 语音合成：{tts_state}")
        stt = get_stt_config() or {}
        stt_state = "已配置" if (isinstance(stt, dict) and (stt.get("enabled") or stt.get("api_key"))) else "未配置/默认可用"
        lines.append(f"{A*2}STT 语音识别：{stt_state}")
        emb = get_embedding_config() or {}
        emb_state = "已配置" if (isinstance(emb, dict) and emb.get("embedding_model")) else "未配置"
        lines.append(f"{A*2}Embedding：{emb_state}")
    except Exception as e:
        lines.append(f"\n{A}六、用户配置偏好：读取失败（{e}）")

    # ── 7. 运行环境 ──
    lines.append(f"\n{A}七、运行环境")
    lines.append(f"{A*2}Python：{sys.version.split()[0]} | 系统：{platform.system()} {platform.release()}")
    lines.append(f"{A*2}主机名：{socket.gethostname()} | 工作目录：{os.getcwd()}")

    # ── 8. 版本与运行时长 ──
    try:
        import subprocess
        commit = subprocess.run(
            ["git", "-C", "/opt/agent-framework", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        git_commit = commit.stdout.strip() or "未知"
    except Exception:
        git_commit = "未知"
    uptime_line = ""
    try:
        clk = os.sysconf(os.sysconf_names["SC_CLK_TCK"])
        with open("/proc/self/stat") as f:
            starttime = int(f.read().split()[21])
        btime = None
        with open("/proc/stat") as f:
            for ln in f:
                if ln.startswith("btime"):
                    btime = int(ln.split()[1])
        if btime is not None:
            started = btime + starttime / clk
            up = int(time.time() - started)
            uptime_line = f" | 已运行：{up // 86400}天{(up % 86400) // 3600}时{(up % 3600) // 60}分"
    except Exception:
        pass
    lines.append(f"\n{A}八、版本与运行时")
    lines.append(f"{A*2}部署版本（git commit）：{git_commit}{uptime_line}")
    lines.append(f"{A*2}本次加载时工具总数：{locals().get('tool_count', '?')}")

    return "\n".join(lines)


def register(registry):
    registry.register(
        name="get_runtime_info",
        description=(
            "查询 LUMU 本体关于自身的一切真实实时信息：身份、当前运行的底层模型与供应商、"
            "API 配置状态、全部能力域与工具数量、已加载技能、长期记忆统计、系统提示词状态、"
            "用户配置偏好、运行环境、部署版本与运行时长。当用户问“你是谁 / 你是什么 / 介绍下你自己 / "
            "你用的什么模型 / 你有哪些能力 / 你的记忆 / 你的配置 / 你的运行环境 / 你支持哪些模型 / "
            "你是哪个版本 / 查一下你的状态”等一切关于 LUMU 自身的问题时，调用此工具获取精确实时数据并据实回答。"
        ),
        handler=get_runtime_info,
        toolset="system",
        emoji="🪞",
        parameters={},
    )
