"""Computer control tools — let the agent operate the local desktop.

Capabilities: screenshot, mouse move/click, keyboard input, hotkeys, scroll,
active-window query. Cross-platform via pyautogui.

Optional dependency (NOT in core requirements to avoid breaking headless
installs):  pip install pyautogui pillow
On a server without a display these tools register but return a clear
"needs desktop environment" message instead of failing.
"""
import os
import tempfile

try:
    import pyautogui  # type: ignore
    _AVAILABLE = True
except Exception:
    _AVAILABLE = False

_UNAVAILABLE = "电脑操控工具需要本地桌面环境（请 pip install pyautogui pillow）"


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
        handler=_mouse_click, toolset="computer", emoji="🖱️",
    )
    registry.register(
        name="mouse_move",
        description="移动鼠标到坐标 (x,y)。",
        parameters={"type": "object", "properties": {"x": {"type": "integer"}, "y": {"type": "integer"}}, "required": ["x", "y"]},
        handler=_mouse_move, toolset="computer", emoji="🖱️",
    )
    registry.register(
        name="type_text",
        description="在当前焦点输入文本。",
        parameters={"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
        handler=_type_text, toolset="computer", emoji="⌨️",
    )
    registry.register(
        name="key_press",
        description="按下单个按键，如 enter / esc / f5。",
        parameters={"type": "object", "properties": {"key": {"type": "string"}}, "required": ["key"]},
        handler=_key_press, toolset="computer", emoji="🔑",
    )
    registry.register(
        name="hotkey",
        description="组合键，keys 用逗号分隔，如 'ctrl,shift,esc'。",
        parameters={"type": "object", "properties": {"keys": {"type": "string", "description": "逗号分隔的按键"}}, "required": ["keys"]},
        handler=_hotkey, toolset="computer", emoji="🔑",
    )
    registry.register(
        name="scroll",
        description="滚动滚轮，amount 正为向上、负为向下。",
        parameters={"type": "object", "properties": {"amount": {"type": "integer"}}, "required": ["amount"]},
        handler=_scroll, toolset="computer", emoji="🔄",
    )
    registry.register(
        name="active_window",
        description="返回当前活动窗口标题。",
        parameters={"type": "object", "properties": {}, "required": []},
        handler=_active_window, toolset="computer", emoji="🪟",
    )


def _screenshot(path=None):
    if not _AVAILABLE:
        return _UNAVAILABLE
    try:
        if not path:
            path = os.path.join(tempfile.gettempdir(), "lumu_shot_%d.png" % os.getpid())
        pyautogui.screenshot().save(path)
        return "截图已保存：%s" % path
    except Exception as e:
        return "截图失败：%s" % e


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
