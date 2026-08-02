"""访问守卫 —— 安全策略跟着「暴露面」走，不跟着「用户身份」走。

设计取向（LUMU 是个人智能体，不是多租户 SaaS）：

  * 只在本机监听、且请求确实来自本机  → 零鉴权、无登录、打开即用。
    个人使用的绝大多数场景走这条路，用户完全无感。
  * 一旦对外暴露（绑定非环回地址 / 经反向代理 / 请求来源非环回 /
    显式声明 LUMU_PUBLIC=1） → 必须携带访问口令。
  * 口令在首次需要时于本机随机生成，写入 data/access_token（0600），
    并在启动横幅里打印成一条可直接点击的带 token 链接。
    点一次，浏览器种下 cookie，之后长期免输。
  * 想彻底关掉：LUMU_NO_AUTH=1（启动时会红字警告）。

仓库里不存放任何密钥；口令永远是运行时本机生成的，
因此开源分发的产物中不含任何可用凭据。
"""

from __future__ import annotations

import os
import secrets
import stat
from pathlib import Path

# 环回地址集合。空串代表拿不到 client（例如 ASGI 测试客户端），按本机处理。
LOOPBACK = {"127.0.0.1", "localhost", "::1", "0:0:0:0:0:0:0:1", ""}

_TRUE = {"1", "true", "yes", "on"}

# 单进程内缓存，避免每个请求都读盘
_cached_token: str | None = None


# ---------------------------------------------------------------- 基础路径

def _home() -> Path:
    env = os.getenv("AGENT_HOME", "").strip()
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent


def _token_file() -> Path:
    return _home() / "data" / "access_token"


# ---------------------------------------------------------------- 开关判定

def auth_disabled() -> bool:
    """用户显式关闭鉴权。"""
    return os.getenv("LUMU_NO_AUTH", "").strip().lower() in _TRUE


def declared_public() -> bool:
    """用户显式声明「这个实例是对外的」（反代场景推荐显式打开）。"""
    return os.getenv("LUMU_PUBLIC", "").strip().lower() in _TRUE


def bind_is_public() -> bool:
    """监听地址是否非环回（0.0.0.0 / 具体外网 IP 等）。"""
    try:
        import config
        host = (getattr(config, "HOST", "") or "").strip()
    except Exception:
        return True  # 判不出来时从严
    return host not in LOOPBACK


def request_is_exposed(request) -> bool:
    """这一次请求是否来自「对外暴露」的路径。

    命中任一即视为暴露：
      1. 监听地址非环回；
      2. 显式声明 LUMU_PUBLIC=1；
      3. 带反向代理特征头（nginx/caddy 等一律会设置）；
      4. 请求来源 IP 非环回。
    """
    if bind_is_public() or declared_public():
        return True
    try:
        h = request.headers
        if h.get("x-forwarded-for") or h.get("x-real-ip") or h.get("x-forwarded-proto"):
            return True
        client = request.client.host if request.client else ""
        if client and client not in LOOPBACK:
            return True
    except Exception:
        return True  # 判不出来时从严
    return False


# ---------------------------------------------------------------- 口令管理

def get_token(create: bool = True) -> str:
    """取当前访问口令；不存在则生成并落盘（0600）。

    优先级：LUMU_TOKEN > API_KEY（兼容旧配置）> data/access_token > 新生成
    """
    global _cached_token

    for key in ("LUMU_TOKEN", "API_KEY"):
        val = os.getenv(key, "").strip()
        if val:
            return val

    if _cached_token:
        return _cached_token

    path = _token_file()
    try:
        if path.exists():
            val = path.read_text(encoding="utf-8").strip()
            if val:
                _cached_token = val
                return val
    except Exception:
        pass

    if not create:
        return ""

    token = secrets.token_urlsafe(24)
    persisted = False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # 目录可写但旧文件属主不同的情况下，open(w) 会失败 —— 先删再建
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass
        path.write_text(token, encoding="utf-8")
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)  # 0600
        persisted = True
    except Exception:
        pass  # 写不进去也不影响本次运行，只是重启后会换一个
    _cached_token = token
    _announce(token, persisted)
    return token


def _announce(token: str, persisted: bool) -> None:
    """口令刚生成时打印一次，让用户能从终端 / journalctl 里捞到它。"""
    try:
        import config
        port = getattr(config, "PORT", "")
    except Exception:
        port = ""
    where = str(_token_file()) if persisted else "（未能落盘，重启后会更换）"
    print(
        "\n\033[33m[access] 本实例被外部访问，已启用访问口令。\033[0m\n"
        f"  访问链接： http://127.0.0.1:{port}/?token={token}\n"
        f"  （挂域名的话把主机名换成你的域名）\n"
        f"  口令文件： {where}\n",
        flush=True,
    )


def rotate_token() -> str:
    """作废旧口令，生成新的（用于「口令泄露了怎么办」）。"""
    global _cached_token
    _cached_token = None
    try:
        _token_file().unlink(missing_ok=True)
    except Exception:
        pass
    return get_token(create=True)


def extract_token(request, authorization: str = "") -> str:
    """从请求里取口令：Authorization 头 / ?token= / cookie / X-Lumu-Token。"""
    if authorization and authorization.startswith("Bearer "):
        candidate = authorization[7:].strip()
        if candidate:
            return candidate
    try:
        val = request.query_params.get("token")
        if val:
            return val.strip()
    except Exception:
        pass
    try:
        val = request.cookies.get("lumu_token")
        if val:
            return val.strip()
    except Exception:
        pass
    try:
        val = request.headers.get("x-lumu-token")
        if val:
            return val.strip()
    except Exception:
        pass
    return ""


def token_matches(request, authorization: str = "") -> bool:
    got = extract_token(request, authorization)
    if not got:
        return False
    return secrets.compare_digest(got, get_token())


# ---------------------------------------------------------------- 守卫入口

def check(request, authorization: str = "") -> None:
    """FastAPI 依赖用的检查函数；不通过则抛 HTTPException。"""
    from fastapi import HTTPException

    if auth_disabled():
        return
    if not request_is_exposed(request):
        return  # 本机直连：零鉴权，打开即用

    # 先取（必要时生成并落盘）口令，确保「第一次有人从外面敲门」就能在
    # 服务端日志/口令文件里拿到它 —— 否则用户永远不知道口令是什么。
    expected = get_token()

    got = extract_token(request, authorization)
    if not got:
        raise HTTPException(
            status_code=401,
            detail="需要访问口令：本实例可被外部访问。口令见服务端日志"
                   "（journalctl -u lumu-agent | grep token=）或 data/access_token 文件。",
        )
    if not secrets.compare_digest(got, expected):
        raise HTTPException(status_code=403, detail="访问口令不正确")


# ---------------------------------------------------------------- 启动横幅

def startup_banner(host: str, port: int) -> None:
    """在终端打印当前的访问方式；这是用户拿到口令的唯一入口。"""
    line = "─" * 62

    if auth_disabled():
        print(f"\n\033[31m{line}\n"
              f"  ⚠  LUMU_NO_AUTH=1：访问守卫已关闭，任何人都能调用本实例。\n"
              f"     若本服务能被公网访问，请立刻取消该设置。\n"
              f"{line}\033[0m\n", flush=True)
        return

    exposed = bind_is_public() or declared_public()

    if not exposed:
        print(f"\n\033[36m{line}\033[0m\n"
              f"  LUMU 已启动 · \033[36m仅限本机\033[0m（{host}:{port}）\n"
              f"  打开即用，无需口令：\033[4mhttp://127.0.0.1:{port}\033[0m\n"
              f"  提示：若通过反向代理对外提供服务，请在环境变量中设置\n"
              f"        LUMU_PUBLIC=1，届时会自动启用一次性访问口令。\n"
              f"\033[36m{line}\033[0m\n", flush=True)
        return

    token = get_token()
    print(f"\n\033[33m{line}\033[0m\n"
          f"  LUMU 已启动 · \033[33m对外暴露\033[0m（{host}:{port}）\n"
          f"  已启用访问口令，请用下面这条链接打开一次（之后本机免输）：\n\n"
          f"      \033[36mhttp://{'127.0.0.1' if host in LOOPBACK else host}:{port}/?token={token}\033[0m\n\n"
          f"  若挂在域名后面，把主机名换成你的域名即可。\n"
          f"  口令文件：{_token_file()}\n"
          f"\033[33m{line}\033[0m\n", flush=True)


# ---------------------------------------------------------------- 未授权页

def unauthorized_page() -> str:
    """对外暴露且未授权时，首页返回的引导页（而不是一堆红色报错）。"""
    return """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>LUMU · 需要访问口令</title>
<style>
  :root{color-scheme:dark}
  *{box-sizing:border-box}
  body{margin:0;min-height:100vh;display:grid;place-items:center;
       background:#07090d;color:#e6edf3;
       font:15px/1.7 -apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif}
  .card{max-width:560px;padding:44px 40px;border:1px solid #1b2430;border-radius:14px;
        background:linear-gradient(180deg,#0c1017,#090c12)}
  .mark{width:34px;height:34px;border-radius:9px;border:1px solid #234;
        display:grid;place-items:center;margin-bottom:22px}
  .mark i{width:12px;height:12px;border-radius:50%;background:#7fdcff;display:block;
          box-shadow:0 0 14px #7fdcff66}
  h1{margin:0 0 14px;font-size:21px;font-weight:600;letter-spacing:.2px}
  p{margin:0 0 14px;color:#9fb0c0}
  code{background:#111823;border:1px solid #1e2a38;border-radius:6px;
       padding:3px 8px;font-size:13px;color:#7fdcff;
       font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
  .cmd{display:block;margin:16px 0 20px;padding:13px 15px;background:#0a0f16;
       border:1px solid #1b2430;border-radius:9px;color:#ffb454;font-size:13px;
       font-family:ui-monospace,SFMono-Regular,Menlo,monospace;overflow-x:auto}
  .foot{margin-top:26px;padding-top:18px;border-top:1px solid #161e28;
        font-size:13px;color:#63758a}
</style></head><body>
<div class="card">
  <div class="mark"><i></i></div>
  <h1>需要访问口令</h1>
  <p>这个 LUMU 实例可以被外部网络访问，因此启用了访问口令。它没有账号体系，也不需要注册——只要用带口令的链接打开一次就行。</p>
  <p>口令在服务启动时打印在终端。如果是用 systemd 托管的：</p>
  <code class="cmd">journalctl -u lumu-agent --no-pager | grep -m1 "token="</code>
  <p>把那条 <code>…/?token=…</code> 链接在浏览器里打开一次，之后这台设备就不用再输了。</p>
  <div class="foot">只在本机使用？把监听地址设回 <code>127.0.0.1</code> 并去掉反向代理，即可完全免口令。</div>
</div></body></html>"""
