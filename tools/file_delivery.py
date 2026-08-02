"""deliver_file — 将 agent 生成的文件交付给前端用户。

注册约定与 tools/file_ops.py 一致：由核心 discovery 调用 register(registry) 注入实例。
会话归属通过 contextvars 自动捕获（见 tools/file_hub._CUR_SESSION），无需显式传 session。
"""
def deliver_file(path: str, name: str = "", mime: str = "") -> str:
    """将本地生成的文件（报告/图片/音频/压缩包等）交付给前端用户，使其在对话中出现可下载文件卡片。"""
    from tools.file_hub import register_file
    # session_id=None -> 由 file_hub 的 contextvar 捕获当前对话会话，精确归属、不串台
    fid = register_file(None, path, name or None, mime or None)
    if not fid:
        return f"❌ 文件交付失败：找不到 {path}（请确认路径存在）"
    return f"✅ 已交付文件给用户（fid={fid}）。前端对话将出现下载卡片，用户可点击下载/预览。"


def register(registry):
    registry.register(
        name="deliver_file",
        description=(
            "将你生成的文件交付给前端用户，使其在对话中出现可下载卡片。"
            "path 为服务器文件路径（绝对，或相对 /opt/agent-framework）。"
            "当用户要你'发文件给我 / 导出结果 / 生成可下载内容 / 把报告发我'时使用此工具。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "要交付的文件服务器路径"},
                "name": {"type": "string", "description": "显示给用户的文件名（可选，默认用原文件名）"},
                "mime": {"type": "string", "description": "MIME 类型（可选，默认按扩展名猜测，如 image/png、application/pdf）"},
            },
            "required": ["path"],
        },
        handler=deliver_file,
        toolset="file",
        is_async=False,
        emoji="📎",
    )
