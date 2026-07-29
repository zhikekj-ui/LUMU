"""钉钉（DingTalk）企业内部应用渠道适配器。

接入方式（回调式）：
1. 在「钉钉开放平台 → 企业内部应用」拿到 AppKey / AppSecret / AgentId。
2. 在「事件订阅 → 基础信息」填写：
     回调 URL: https://<域名>:8000/api/channels/dingtalk/callback
     （签名 Token / AES Key 与 .env 的 DINGTALK_TOKEN / DINGTALK_AES_KEY 对应）。
3. 填齐 .env：DINGTALK_APP_KEY / DINGTALK_APP_SECRET / DINGTALK_AGENT_ID。
4. 订阅事件：接收消息（org_message / 流式）/ 机器人消息等。
5. 回调 URL 需公网可达 + HTTPS。
   初期可选「不加密」（AES Key 留空），先跑通再升级加密。

注意：钉钉企业内部应用接收「用户发给应用的消息」事件结构随配置不同，
本适配器做了多分支兼容（机器人 webhook / 事件订阅 message）。具体字段需
在给凭证后实测对齐（属"预留 + 待验证"点）。
"""
import time
import json
import base64
import hmac
import hashlib
from channels.base import BaseChannel


class DingTalkChannel(BaseChannel):
    name = "dingtalk"
    API = "https://oapi.dingtalk.com"

    def __init__(self, app_key: str, app_secret: str, agent_id: str = "", token: str = "", aes_key: str = ""):
        super().__init__()
        self._app_key = app_key
        self._app_secret = app_secret
        self._agent_id = agent_id
        self._token = token
        self._aes_key = aes_key
        self._access_token = None
        self._token_expire = 0
        self._session = None

    async def start(self):
        import aiohttp
        self._session = aiohttp.ClientSession()
        self.enabled = True
        try:
            await self._ensure_token()
        except Exception as e:
            print(f"[dingtalk] token preheat skipped: {e}")

    async def stop(self):
        if self._session:
            await self._session.close()
        self.enabled = False

    # ---- access_token ----
    async def _ensure_token(self):
        if self._access_token and time.time() < self._token_expire - 60:
            return self._access_token
        if not self._session:
            import aiohttp
            self._session = aiohttp.ClientSession()
        url = f"{self.API}/gettoken?appkey={self._app_key}&appsecret={self._app_secret}"
        async with self._session.get(url) as resp:
            data = await resp.json()
        if data.get("errcode", 0) != 0:
            raise RuntimeError(f"DingTalk gettoken failed: {data}")
        self._access_token = data["access_token"]
        self._token_expire = time.time() + data.get("expires_in", 7200)
        return self._access_token

    # ---- 主动发消息（工作通知）----
    async def send_message(self, chat_id: str, text: str, reply_to: str | None = None):
        try:
            tok = await self._ensure_token()
        except Exception as e:
            print(f"[dingtalk] send failed (token): {e}")
            return
        url = f"{self.API}/topapi/message/corpconversation/send?access_token={tok}"
        agent_id = int(self._agent_id) if str(self._agent_id).isdigit() else self._agent_id
        chunks = [text[i:i + 1500] for i in range(0, len(text), 1500)] or [text]
        for c in chunks:
            payload = {
                "agent_id": agent_id,
                "userid_list": chat_id,
                "msg": {"msgtype": "text", "text": {"content": c}},
            }
            try:
                async with self._session.post(url, json=payload) as resp:
                    await resp.json()
            except Exception as e:
                print(f"[dingtalk] send chunk error: {e}")

    # ---- 回调 ----
    async def handle_callback(self, raw: bytes, request):
        from fastapi import HTTPException
        body = raw.decode("utf-8", "ignore")
        try:
            data = json.loads(body)
        except Exception:
            data = {}

        # URL 校验
        if data.get("type") == "check_url":
            return {"challenge": data.get("challenge", "")}

        # 验签：signature = base64(hmac-sha256(token, timestamp + "\n" + body))
        ts = request.headers.get("timestamp", "")
        sig = request.headers.get("sign", "") or request.headers.get("signature", "")
        if self._token and sig:
            h = base64.b64encode(
                hmac.new(self._token.encode(), (ts + "\n" + body).encode(), hashlib.sha256).digest()
            ).decode()
            if h != sig:
                raise HTTPException(status_code=400, detail="bad signature")

        # AES 解密（若配置）
        if self._aes_key and "encrypt" in data:
            body = self._aes_decrypt(data["encrypt"])
            try:
                data = json.loads(body)
            except Exception:
                data = {}

        # 提取消息（多分支兼容）
        text = ""
        user_id = ""
        event = data.get("event", {}) or {}
        if "text" in data and isinstance(data.get("text"), str):  # 机器人 webhook 消息
            text = data.get("text", "")
            user_id = data.get("senderId", "") or data.get("userId", "")
        elif "content" in event:
            try:
                c = json.loads(event.get("content", "{}"))
                text = c.get("content", "")
            except Exception:
                text = ""
            user_id = event.get("senderId", "") or event.get("unionId", "") or event.get("senderUserId", "")
        if not text:
            return "success"
        metadata = {"user_key": f"dingtalk:{user_id}"}
        reply = await self._on_message("dingtalk", user_id, user_id, text, metadata)
        if reply:
            await self.send_message(user_id, reply)
        return "success"

    def _aes_decrypt(self, encrypt_b64: str) -> str:
        try:
            from Crypto.Cipher import AES
        except ImportError:
            print("[dingtalk] pycryptodome required for encrypt mode: pip install pycryptodome")
            return ""
        key = self._aes_key.encode()
        aes = AES.new(key, AES.MODE_CBC, key)
        raw = aes.decrypt(base64.b64decode(encrypt_b64))
        pad = raw[-1]
        if pad < 1 or pad > 32:
            return ""
        raw = raw[:-pad]
        return raw.decode("utf-8", "ignore")

    def get_status(self) -> dict:
        return {"name": self.name, "enabled": self.enabled, "platform": "dingtalk"}
