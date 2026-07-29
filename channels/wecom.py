"""企业微信（WeCom / 微信企业号）自建应用渠道适配器。

接入方式（回调式）：
1. 在「企业微信管理后台 → 应用管理 → 自建应用」拿到 CorpID / AgentID / Secret。
2. 在应用「接收消息 → 设置API接收」填写：
     URL:  https://<域名>:8000/api/channels/wecom/callback
     Token / EncodingAESKey（与 .env 的 WECHAT_WORK_TOKEN / WECHAT_WORK_AES_KEY 对应）。
3. 填齐 .env：WECHAT_WORK_CORP_ID / WECHAT_WORK_AGENT_ID / WECHAT_WORK_SECRET。
4. 回调 URL 需公网可达 + HTTPS（建议 Nginx 反代终止 TLS）。
   初期可选「明文模式」（EncodingAESKey 留空），先跑通再升级加密。

依赖：AES 解密需 `pip install pycryptodome`（明文模式可不装）。
"""
import time
import xml.etree.ElementTree as ET
import hashlib
import base64
from channels.base import BaseChannel


class WeComChannel(BaseChannel):
    name = "wecom"
    API = "https://qyapi.weixin.qq.com/cgi-bin"

    def __init__(self, corp_id: str, agent_id: str, secret: str, token: str = "", aes_key: str = ""):
        super().__init__()
        self._corp_id = corp_id
        self._agent_id = agent_id
        self._secret = secret
        self._token = token
        self._aes_key = aes_key  # 43-char EncodingAESKey（明文模式为空）
        self._access_token = None
        self._token_expire = 0
        self._session = None

    async def start(self):
        import aiohttp
        self._session = aiohttp.ClientSession()
        self.enabled = True
        # 企微是回调推送，不主动拉消息；仅预热 token
        try:
            await self._ensure_token()
        except Exception as e:
            print(f"[wecom] token preheat skipped: {e}")

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
        url = f"{self.API}/gettoken?corpid={self._corp_id}&corpsecret={self._secret}"
        async with self._session.get(url) as resp:
            data = await resp.json()
        if data.get("errcode", 0) != 0:
            raise RuntimeError(f"WeCom gettoken failed: {data}")
        self._access_token = data["access_token"]
        self._token_expire = time.time() + data.get("expires_in", 7200)
        return self._access_token

    # ---- 主动发消息 ----
    async def send_message(self, chat_id: str, text: str, reply_to: str | None = None):
        try:
            tok = await self._ensure_token()
        except Exception as e:
            print(f"[wecom] send failed (token): {e}")
            return
        url = f"{self.API}/message/send?access_token={tok}"
        # 企微单条文本上限 2048 字节，中文约 600 字，超长拆分
        chunks = [text[i:i + 600] for i in range(0, len(text), 600)] or [text]
        for c in chunks:
            payload = {
                "touser": chat_id,
                "msgtype": "text",
                "agentid": int(self._agent_id) if str(self._agent_id).isdigit() else self._agent_id,
                "text": {"content": c},
            }
            try:
                async with self._session.post(url, json=payload) as resp:
                    await resp.json()
            except Exception as e:
                print(f"[wecom] send chunk error: {e}")

    # ---- 回调 ----
    async def handle_callback(self, raw: bytes, request):
        """企业微信回调：GET 校验 / POST 消息。返回平台要求的明文响应。"""
        from fastapi import HTTPException
        params = dict(request.query_params)
        if request.method == "GET":
            # URL 校验：msg_signature, timestamp, nonce, echostr
            msg_sig = params.get("msg_signature", "")
            timestamp = params.get("timestamp", "")
            nonce = params.get("nonce", "")
            echostr = params.get("echostr", "")
            plain = self._verify_and_decrypt(msg_sig, timestamp, nonce, echostr)
            if plain is None:
                raise HTTPException(status_code=400, detail="bad signature")
            return plain
        # POST 消息
        body = raw.decode("utf-8", "ignore")
        msg_sig = params.get("msg_signature", "")
        timestamp = params.get("timestamp", "")
        nonce = params.get("nonce", "")
        content = self._verify_and_decrypt(msg_sig, timestamp, nonce, body)
        if content is None:
            raise HTTPException(status_code=400, detail="bad signature")
        user_id, text = self._parse_xml(content)
        if not text:
            return "success"
        metadata = {"user_key": f"wecom:{user_id}"}
        reply = await self._on_message("wecom", user_id, user_id, text, metadata)
        if reply:
            await self.send_message(user_id, reply)
        return "success"

    # ---- 验签 + 解密 ----
    def _verify_and_decrypt(self, msg_sig, timestamp, nonce, data_b64_or_xml):
        if self._aes_key:
            encrypt = None
            if data_b64_or_xml.strip().startswith("<xml"):
                try:
                    root = ET.fromstring(data_b64_or_xml)
                    encrypt = root.findtext("Encrypt")
                except Exception:
                    encrypt = None
            else:
                encrypt = data_b64_or_xml  # echostr 密文
            if encrypt:
                signature = hashlib.sha1(
                    "".join(sorted([self._token, timestamp, nonce, encrypt])).encode()
                ).hexdigest()
                if msg_sig and signature != msg_sig:
                    return None
                return self._aes_decrypt(encrypt)
        # 明文模式：直接返回原文（echostr / XML 明文）
        return data_b64_or_xml

    def _aes_decrypt(self, encrypt_b64: str) -> str | None:
        try:
            from Crypto.Cipher import AES
        except ImportError:
            print("[wecom] pycryptodome required for AES mode: pip install pycryptodome")
            return None
        key = (self._aes_key + "=").encode()
        aes = AES.new(key, AES.MODE_CBC, key[:16])
        raw = aes.decrypt(base64.b64decode(encrypt_b64))
        pad = raw[-1]
        if pad < 1 or pad > 32:
            return None
        raw = raw[:-pad]
        msg_len = int.from_bytes(raw[:4], "big")
        return raw[4:4 + msg_len].decode("utf-8", "ignore")

    @staticmethod
    def _parse_xml(xml_str: str):
        try:
            root = ET.fromstring(xml_str)
            user = root.findtext("FromUserName", "")
            content = root.findtext("Content", "")
            return user, content
        except Exception:
            return "", ""

    def get_status(self) -> dict:
        return {"name": self.name, "enabled": self.enabled, "platform": "wecom"}
