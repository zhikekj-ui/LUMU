"""Computer control tools — let the agent operate the local desktop.

Capabilities: screenshot, mouse move/click, keyboard input, hotkeys, scroll,
active-window query. Cross-platform via pyautogui.

依赖 pyautogui / Pillow 已写入 requirements.txt（控制电脑是 LUMU 标配能力），
本地有桌面环境时开箱即用；无图形显示的服务端自动降级为清晰提示。
"""
import os
import sys
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
        description="截取【本机桌面屏幕】（你运行的这台电脑的真实显示器画面，不是网页）。保存为图片并交付对话，可供视觉能力查看。注意：截网页请用 browser_screenshot，本工具只截本机桌面。",
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


class _ScreenPermissionError(RuntimeError):
    """macOS 屏幕录制未授权的明确信号，供上层给出精准指引。"""


def _is_blank_png(path):
    """极简判断：截图是否接近纯色（macOS 屏幕录制未授权时常产出纯黑/纯白空白图）。"""
    try:
        from PIL import Image
        with Image.open(path) as im:
            im = im.convert("RGB")
            extrema = im.getextrema()
            # 三通道极差都很小 => 接近纯色（大概率权限被拒的空白屏）
            return all((hi - lo) < 10 for (lo, hi) in extrema)
    except Exception:
        return False


def _capture_to(path):
    """跨平台截图到 path。

    主路 pyautogui（macOS 走 Quartz/CG，不依赖外部二进制、不依赖 PATH）；
    macOS 额外用绝对路径 /usr/sbin/screencapture 兜底，彻底排除「PATH 缺
    /usr/sbin 导致 [Errno 2] No such file or directory」这类环境差异。
    """
    errors = []

    # 1) pyautogui 主路（已在本机真机验证可用）
    try:
        img = pyautogui.screenshot()
        if img is None:
            errors.append("pyautogui.screenshot() 返回空")
        else:
            img.save(path)
            if _is_blank_png(path):
                raise _ScreenPermissionError("pyautogui 截到纯色空白图（macOS 屏幕录制未授权）")
            return
    except _ScreenPermissionError:
        raise
    except Exception as e:
        errors.append("pyautogui: %s" % e)

    # 2) macOS 原生兜底：绝对路径，绝不依赖 PATH
    if sys.platform == "darwin" and os.path.exists("/usr/sbin/screencapture"):
        import subprocess as _sp
        try:
            _sp.run(["/usr/sbin/screencapture", "-x", "-t", "png", path], check=True)
            if _is_blank_png(path):
                raise _ScreenPermissionError("screencapture 截到纯色空白图（macOS 屏幕录制未授权）")
            return
        except _ScreenPermissionError:
            raise
        except _sp.CalledProcessError as e:
            raise _ScreenPermissionError("screencapture 被系统拒绝（退出码 %s，macOS 屏幕录制未授权）" % e.returncode)
        except Exception as e:
            errors.append("screencapture: %s" % e)

    raise RuntimeError("无可用的截图后端（%s）" % "; ".join(errors))


def _screenshot(path=None):
    if not _AVAILABLE:
        return _UNAVAILABLE
    try:
        if not path:
            home = os.getenv("AGENT_HOME") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            out_dir = os.path.join(home, "artifacts", "screenshots")
            os.makedirs(out_dir, exist_ok=True)
            path = os.path.join(out_dir, "lumu_shot_%d.png" % int(time.time()))
        _capture_to(path)
        # 自动把产物交付给前端：对话中出现可预览/下载的卡片
        try:
            from tools.file_delivery import deliver_file
            deliver_file(path, name=os.path.basename(path), mime="image/png")
        except Exception as e:
            logging.warning("screenshot deliver failed: %s", e)
        return "✅ 截图已完成并发送到对话：%s" % path
    except Exception as e:
        msg = str(e)
        if isinstance(e, _ScreenPermissionError) or any(k in msg for k in ("屏幕录制", "Screen Recording", "TCC", "Operation not permitted", "non-zero exit status")):
            hint = ("\n\n🔒 macOS 屏幕录制权限未授权，无法截取桌面：\n"
                    "1. 打开 系统设置 → 隐私与安全性 → 屏幕录制\n"
                    "2. 在右侧列表找到「启动 LUMU 的那个终端」（Terminal.app 或 iTerm），勾选启用\n"
                    "3. 完全退出该终端再重新打开，然后重新运行 `python run.py`\n"
                    "（注意：用 launchd / 后台自启的进程不在白名单内，必须从你授权过的终端前台启动 LUMU）")
        elif "display" in msg.lower():
            hint = "\n（当前环境没有图形显示，控制电脑功能需在带桌面的本机运行。）"
        else:
            hint = "\n（截图失败，请检查系统权限或重试。）"
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
