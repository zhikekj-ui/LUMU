"""飞书（Feishu / Lark）企业自建应用渠道适配器。

接入方式（回调式）：
1. 在「飞书开放平台 → 企业自建应用」拿到 App ID / App Secret。
2. 在「事件订阅」填写：
     请求网址 URL: https://<域名>:8000/api/channels/feishu/callback
     Verification Token / Encrypt Key（与 .env 的 FEISHU_VERIFY_TOKEN / FEISHU_ENCRYPT_KEY 对应）。
3. 订阅事件：接收消息 im.message.receive_v1 等。
4. 填齐 .env：FEISHU_APP_ID / FEISHU_APP_SECRET。
5. 回调 URL 需公网可达 + HTTPS。
   初期可选「不加密」（Encrypt Key 留空），先跑通再升级加密。

注意：飞书新版使用 X-Lark-Signature 头（基于 Encrypt Key 的 HMAC-SHA256）。
旧版使用 Verification Token 的 SHA1 校验——本适配器在配置了 Encrypt Key 时走新版签名。
"""
import time
import json
import base64
import hmac
import hashlib
from channels.base import BaseChannel


class FeishuChannel(BaseChannel):
    name = "feishu"
    API = "https://open.feishu.cn/open-apis"
    JSON_OK = {"code": 0, "msg": "success", "data": {}}

    def __init__(self, app_id: str, app_secret: str, verify_token: str = "", encrypt_key: str = ""):
        super().__init__()
        self._app_id = app_id
        self._app_secret = app_secret
        self._verify_token = verify_token
        self._encrypt_key = encrypt_key
        self._tenant_token = None
        self._token_expire = 0
        self._session = None

    async def start(self):
        import aiohttp
        self._session = aiohttp.ClientSession()
        self.enabled = True
        try:
            await self._ensure_token()
        except Exception as e:
            print(f"[feishu] token preheat skipped: {e}")

    async def stop(self):
        if self._session:
            await self._session.close()
        self.enabled = False

    # ---- tenant_access_token ----
    async def _ensure_token(self):
        if self._tenant_token and time.time() < self._token_expire - 60:
            return self._tenant_token
        if not self._session:
            import aiohttp
            self._session = aiohttp.ClientSession()
        url = f"{self.API}/auth/v3/tenant_access_token/internal"
        async with self._session.post(url, json={"app_id": self._app_id, "app_secret": self._app_secret}) as resp:
            data = await resp.json()
        if data.get("code", 0) != 0:
            raise RuntimeError(f"Feishu token failed: {data}")
        self._tenant_token = data["tenant_access_token"]
        self._token_expire = time.time() + data.get("expire", 7200)
        return self._tenant_token

    # ---- 主动发消息 ----
    async def send_message(self, chat_id: str, text: str, reply_to: str | None = None):
        try:
            tok = await self._ensure_token()
        except Exception as e:
            print(f"[feishu] send failed (token): {e}")
            return
        url = f"{self.API}/im/v1/messages?receive_id_type=user_id"
        headers = {"Authorization": f"Bearer {tok}"}
        chunks = [text[i:i + 2000] for i in range(0, len(text), 2000)] or [text]
        for c in chunks:
            payload = {
                "receive_id": chat_id,
                "msg_type": "text",
                "content": json.dumps({"text": c}),
            }
            try:
                async with self._session.post(url, json=payload, headers=headers) as resp:
                    await resp.json()
            except Exception as e:
                print(f"[feishu] send chunk error: {e}")

    # ---- 回调 ----
    async def handle_callback(self, raw: bytes, request):
        from fastapi import HTTPException
        body = raw.decode("utf-8", "ignore")
        try:
            data = json.loads(body)
        except Exception:
            data = {}

        # URL 校验
        if data.get("type") == "url_verification":
            return {"challenge": data.get("challenge", "")}

        # 验签（新版 X-Lark-Signature）
        ts = request.headers.get("X-Lark-Request-Timestamp", "")
        nonce = request.headers.get("X-Lark-Request-Nonce", "")
        sig = request.headers.get("X-Lark-Signature", "")
        if self._encrypt_key and sig:
            h = base64.b64encode(
                hmac.new(self._encrypt_key.encode(), (ts + nonce + body).encode(), hashlib.sha256).digest()
            ).decode()
            if h != sig:
                raise HTTPException(status_code=400, detail="bad signature")

        # 解密（若加密）
        if self._encrypt_key and "encrypt" in data:
            body = self._aes_decrypt(data["encrypt"])
            try:
                data = json.loads(body)
            except Exception:
                data = {}

        # 提取消息：im.message.receive_v1
        event = data.get("event", {}) or {}
        msg = event.get("message", {}) or {}
        if not msg:
            return self.JSON_OK  # 投递已读回执等无关事件
        sender = event.get("sender", {}) or {}
        user_id = (
            sender.get("sender_id", {}).get("open_id")
            or sender.get("open_id")
            or msg.get("sender", {}).get("sender_id", {}).get("open_id")
            or event.get("operator", {}).get("open_id", "")
        )
        try:
            content_obj = json.loads(msg.get("content", "{}"))
            text = content_obj.get("text", "")
        except Exception:
            text = ""
        if not text:
            return self.JSON_OK
        metadata = {"user_key": f"feishu:{user_id}"}
        reply = await self._on_message("feishu", user_id, user_id, text, metadata)
        if reply:
            await self.send_message(user_id, reply)
        return self.JSON_OK

    def _aes_decrypt(self, encrypt_b64: str) -> str:
        try:
            from Crypto.Cipher import AES
        except ImportError:
            print("[feishu] pycryptodome required for encrypt mode: pip install pycryptodome")
            return ""
        key = self._encrypt_key.encode()
        aes = AES.new(key, AES.MODE_CBC, key)
        raw = aes.decrypt(base64.b64decode(encrypt_b64))
        pad = raw[-1]
        if pad < 1 or pad > 32:
            return ""
        raw = raw[:-pad]
        return raw.decode("utf-8", "ignore")

    def get_status(self) -> dict:
        return {"name": self.name, "enabled": self.enabled, "platform": "feishu"}
