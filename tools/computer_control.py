"""Computer control tools — let the agent operate the local desktop.

Capabilities: screenshot, mouse move/click, keyboard input, hotkeys, scroll,
active-window query. Cross-platform via pyautogui.

依赖 pyautogui / Pillow 已写入 requirements.txt（控制电脑是 LUMU 标配能力），
本地有桌面环境时开箱即用；无图形显示的服务端自动降级为清晰提示。
"""
import os
import time
import logging
import tempfile

try:
    import pyautogui  # type: ignore
    _AVAILABLE = True
except Exception:
    _AVAILABLE = False

_UNAVAILABLE = "电脑操控工具需要本地桌面环境（控制电脑是 LUMU 标配能力，请先安装依赖：pip install pyautogui pillow）"


def _guard(fn):
    """统一兜底：未安装依赖 / 权限不足时给出清晰可操作提示，而非抛出天书报错。"""
    def wrap(*a, **k):
        if not _AVAILABLE:
            return _UNAVAILABLE
        try:
            return fn(*a, **k)
        except Exception as e:
            msg = str(e)
            hint = "（若提示权限不足：请到 系统设置 → 隐私与安全性 → 辅助功能，把启动 LUMU 的终端（Terminal.app / iTerm）加入白名单后重试。）"
            return "❌ 操作失败：%s %s" % (msg, hint)
    return wrap


def register(registry):
    registry.register(
        name="screenshot",
        description="截取当前屏幕并保存，返回路径供视觉能力查看。",
        parameters={"type": "object", "properties": {"path": {"type": "string", "description": "可选保存路径，缺省用临时文件"}}, "required": []},
        handler=_screenshot, toolset="computer", emoji="🖥️",
    )
    registry.register(
        name="mouse_click",
        description="在屏幕坐标 (x,y) 点击鼠标。",
        parameters={"type": "object", "properties": {"x": {"type": "integer"}, "y": {"type": "integer"}, "button": {"type": "string", "description": "left/right/middle，默认 left"}, "double": {"type": "boolean", "description": "是否双击"}}, "required": ["x", "y"]},
        handler=_guard(_mouse_click), toolset="computer", emoji="🖱️",
    )
    registry.register(
        name="mouse_move",
        description="移动鼠标到坐标 (x,y)。",
        parameters={"type": "object", "properties": {"x": {"type": "integer"}, "y": {"type": "integer"}}, "required": ["x", "y"]},
        handler=_guard(_mouse_move), toolset="computer", emoji="🖱️",
    )
    registry.register(
        name="type_text",
        description="在当前焦点输入文本。",
        parameters={"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
        handler=_guard(_type_text), toolset="computer", emoji="⌨️",
    )
    registry.register(
        name="key_press",
        description="按下单个按键，如 enter / esc / f5。",
        parameters={"type": "object", "properties": {"key": {"type": "string"}}, "required": ["key"]},
        handler=_guard(_key_press), toolset="computer", emoji="🔑",
    )
    registry.register(
        name="hotkey",
        description="组合键，keys 用逗号分隔，如 'ctrl,shift,esc'。",
        parameters={"type": "object", "properties": {"keys": {"type": "string", "description": "逗号分隔的按键"}}, "required": ["keys"]},
        handler=_guard(_hotkey), toolset="computer", emoji="🔑",
    )
    registry.register(
        name="scroll",
        description="滚动滚轮，amount 正为向上、负为向下。",
        parameters={"type": "object", "properties": {"amount": {"type": "integer"}}, "required": ["amount"]},
        handler=_guard(_scroll), toolset="computer", emoji="🔄",
    )
    registry.register(
        name="active_window",
        description="返回当前活动窗口标题。",
        parameters={"type": "object", "properties": {}, "required": []},
        handler=_guard(_active_window), toolset="computer", emoji="🪟",
    )


def _screenshot(path=None):
    if not _AVAILABLE:
        return _UNAVAILABLE
    try:
        if not path:
            home = os.getenv("AGENT_HOME") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            out_dir = os.path.join(home, "artifacts", "screenshots")
            os.makedirs(out_dir, exist_ok=True)
            path = os.path.join(out_dir, "lumu_shot_%d.png" % int(time.time()))
        img = pyautogui.screenshot()
        img.save(path)
        # 自动把产物交付给前端：对话中出现可预览/下载的卡片
        try:
            from tools.file_delivery import deliver_file
            deliver_file(path, name=os.path.basename(path), mime="image/png")
        except Exception as e:
            logging.warning("screenshot deliver failed: %s", e)
        return "✅ 截图已完成并发送到对话：%s" % path
    except Exception as e:
        msg = str(e)
        if "display" in msg.lower():
            hint = "\n（当前环境没有图形显示，控制电脑功能需在带桌面的本机运行。）"
        else:
            hint = "\n（若提示权限不足：请到 系统设置 → 隐私与安全性 → 屏幕录制（及辅助功能），把启动 LUMU 的终端加入白名单后重试。）"
        return "❌ 截图失败：%s%s" % (msg, hint)


def _mouse_click(x, y, button="left", double=False):
    if not _AVAILABLE:
        return _UNAVAILABLE
    pyautogui.click(x=x, y=y, button=button, clicks=2 if double else 1)
    return "已点击 (%s,%s)" % (x, y)


def _mouse_move(x, y):
    if not _AVAILABLE:
        return _UNAVAILABLE
    pyautogui.moveTo(x, y)
    return "鼠标移至 (%s,%s)" % (x, y)


def _type_text(text):
    if not _AVAILABLE:
        return _UNAVAILABLE
    pyautogui.write(text, interval=0.01)
    return "已输入文本（%d 字）" % len(text)


def _key_press(key):
    if not _AVAILABLE:
        return _UNAVAILABLE
    pyautogui.press(key)
    return "已按键 %s" % key


def _hotkey(keys):
    if not _AVAILABLE:
        return _UNAVAILABLE
    seq = [k.strip() for k in keys.split(",")]
    pyautogui.hotkey(*seq)
    return "已执行组合键 %s" % keys


def _scroll(amount):
    if not _AVAILABLE:
        return _UNAVAILABLE
    pyautogui.scroll(amount)
    return "已滚动 %s" % amount


def _active_window():
    if not _AVAILABLE:
        return _UNAVAILABLE
    try:
        return "活动窗口：%s" % pyautogui.getActiveWindowTitle()
    except Exception as e:
        return "获取窗口失败：%s" % e
