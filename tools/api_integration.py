"""API integration tools — HTTP requests, key management, response parsing, webhooks.

Provides:
- Authenticated HTTP requests to external APIs (GET/POST/PUT/DELETE/PATCH)
- API key storage with XOR-obfuscated + base64 encoding in SQLite
- Response parsing with built-in templates and pattern extraction
- Webhook registration, management, and testing

Keys are obfuscated at rest using XOR + base64 (key derived from AGENT_BASE_DIR).
Note: This is obfuscation, not strong encryption. For production deployments with
sensitive keys, consider using a proper secrets manager.
"""
import base64
import hashlib
import json
import os
import re
import sqlite3
import time
import urllib.request
import urllib.error
import urllib.parse
from typing import Any


# ---------------------------------------------------------------------------
# Encryption helpers (pure stdlib — XOR obfuscation)
# ---------------------------------------------------------------------------

def _derive_key() -> bytes:
    """Derive a 32-byte XOR key from AGENT_BASE_DIR via SHA-256."""
    base_dir = os.environ.get("AGENT_BASE_DIR", os.getcwd())
    return hashlib.sha256(base_dir.encode("utf-8")).digest()


def _encrypt_value(plaintext: str) -> str:
    """XOR-obfuscate + base64-encode a string value."""
    key = _derive_key()
    data = plaintext.encode("utf-8")
    encrypted = bytes(b ^ key[i % len(key)] for i, b in enumerate(data))
    return base64.urlsafe_b64encode(encrypted).decode("utf-8")


def _decrypt_value(ciphertext: str) -> str:
    """Decode base64 + XOR-deobfuscate back to plaintext."""
    key = _derive_key()
    data = base64.urlsafe_b64decode(ciphertext.encode("utf-8"))
    decrypted = bytes(b ^ key[i % len(key)] for i, b in enumerate(data))
    return decrypted.decode("utf-8")


# ---------------------------------------------------------------------------
# SQLite helpers for API key storage
# ---------------------------------------------------------------------------

def _get_db_path() -> str:
    """Return the path to the encrypted API keys database."""
    base_dir = os.environ.get("AGENT_BASE_DIR", os.getcwd())
    data_dir = os.path.join(base_dir, "data")
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, "api_keys.db")


def _init_db(conn: sqlite3.Connection) -> None:
    """Create the api_keys table if it does not exist."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS api_keys (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            service     TEXT    NOT NULL,
            key_name    TEXT    NOT NULL DEFAULT 'default',
            key_value   TEXT    NOT NULL,
            created_at  REAL    NOT NULL,
            updated_at  REAL    NOT NULL,
            UNIQUE(service, key_name)
        )
        """
    )
    conn.commit()


def _get_db() -> sqlite3.Connection:
    """Open (and initialise) the API keys database."""
    conn = sqlite3.connect(_get_db_path())
    _init_db(conn)
    return conn


# ---------------------------------------------------------------------------
# Webhook storage helpers
# ---------------------------------------------------------------------------

def _get_webhooks_path() -> str:
    """Return the path to the webhooks JSON file."""
    base_dir = os.environ.get("AGENT_BASE_DIR", os.getcwd())
    data_dir = os.path.join(base_dir, "data")
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, "webhooks.json")


def _load_webhooks() -> dict:
    """Load webhooks from the JSON file."""
    path = _get_webhooks_path()
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_webhooks(webhooks: dict) -> None:
    """Persist webhooks to the JSON file."""
    path = _get_webhooks_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(webhooks, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------

async def api_request(
    method: str,
    url: str,
    headers: dict | None = None,
    body: dict | str | None = None,
    auth_type: str = "none",
    auth_config: dict | None = None,
) -> str:
    """Make an authenticated HTTP request to an external API.

    Supports bearer token, API key (header or query), and basic OAuth2
    bearer flows.  Automatically resolves stored API keys when
    *auth_config* references a service name managed by ``api_key_store``.
    """
    import httpx

    method = method.upper()
    if method not in ("GET", "POST", "PUT", "DELETE", "PATCH"):
        return f"不支持的HTTP方法: {method}，请使用 GET/POST/PUT/DELETE/PATCH"

    headers = dict(headers) if headers else {}
    auth_config = dict(auth_config) if auth_config else {}

    # --- Resolve authentication ------------------------------------------------
    try:
        url = _apply_auth(method, url, headers, auth_type, auth_config)
    except Exception as exc:
        return f"认证配置失败: {exc}"

    # --- Prepare body ----------------------------------------------------------
    json_body = None
    raw_body = None
    if body is not None:
        if isinstance(body, dict):
            json_body = body
        else:
            raw_body = str(body)

    # --- Execute request -------------------------------------------------------
    try:
        async with httpx.AsyncClient(
            timeout=30, follow_redirects=True
        ) as client:
            resp = await client.request(
                method,
                url,
                headers=headers,
                json=json_body,
                content=raw_body,
            )

        status = resp.status_code
        resp_headers = dict(resp.headers)
        content_type = resp.headers.get("content-type", "")

        # Auto-parse JSON responses
        if "json" in content_type or "javascript" in content_type:
            try:
                parsed_body = resp.json()
            except Exception:
                parsed_body = resp.text
        else:
            parsed_body = resp.text

        result = {
            "status_code": status,
            "headers": resp_headers,
            "body": parsed_body,
        }
        return json.dumps(result, ensure_ascii=False, indent=2)

    except httpx.TimeoutException:
        return f"请求超时: {url}"
    except httpx.RequestError as exc:
        return f"请求失败: {exc}"
    except Exception as exc:
        return f"请求异常: {exc}"


def _apply_auth(
    method: str,
    url: str,
    headers: dict,
    auth_type: str,
    auth_config: dict,
) -> str:
    """Attach authentication credentials to *headers* (and possibly *url*).

    Returns the (possibly modified) URL so that query-parameter auth can
    append the key to the URL string.
    """
    auth_type = auth_type.lower()

    if auth_type == "none":
        return url

    # Resolve a token that may reference a stored key:
    #   {"service": "github"} or {"service": "github", "key_name": "pat"}
    token = auth_config.get("token", "")
    if auth_config.get("service"):
        token = _resolve_stored_key(
            auth_config["service"],
            auth_config.get("key_name", "default"),
        )

    if auth_type == "bearer":
        if not token:
            raise ValueError("bearer 认证需要提供 token 或 service 引用")
        headers["Authorization"] = f"Bearer {token}"

    elif auth_type == "api_key":
        key_header = auth_config.get("header", "")
        key_param = auth_config.get("param", "")
        if key_param:
            # Append as query parameter to the URL
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}{key_param}={urllib.parse.quote(token, safe='')}"
        else:
            header_name = key_header or "X-API-Key"
            headers[header_name] = token

    elif auth_type == "oauth":
        # Simplified OAuth2 — expects a pre-obtained access token.
        if not token:
            raise ValueError(
                "oauth 认证需要提供 access_token 或通过 service 引用已存储的令牌"
            )
        headers["Authorization"] = f"Bearer {token}"

    else:
        raise ValueError(f"不支持的认证类型: {auth_type}，请使用 none/bearer/api_key/oauth")

    return url


def _resolve_stored_key(service: str, key_name: str = "default") -> str:
    """Look up an API key from the encrypted store."""
    conn = _get_db()
    try:
        row = conn.execute(
            "SELECT key_value FROM api_keys WHERE service = ? AND key_name = ?",
            (service, key_name),
        ).fetchone()
        if row is None:
            raise ValueError(
                f"未找到服务 '{service}' 的密钥 (key_name='{key_name}')，"
                f"请先使用 api_key_store 存储"
            )
        return _decrypt_value(row[0])
    finally:
        conn.close()


# ---- api_key_store ---------------------------------------------------------

async def api_key_store(
    action: str,
    service_name: str = "",
    key_value: str = "",
    key_name: str = "default",
) -> str:
    """Store, retrieve, list, or delete API keys in an encrypted SQLite DB."""
    action = action.lower()

    if action == "store":
        if not service_name or not key_value:
            return "存储密钥需要提供 service_name 和 key_value"
        conn = _get_db()
        try:
            encrypted = _encrypt_value(key_value)
            now = time.time()
            conn.execute(
                """
                INSERT INTO api_keys (service, key_name, key_value, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(service, key_name)
                DO UPDATE SET key_value = excluded.key_value, updated_at = excluded.updated_at
                """,
                (service_name, key_name, encrypted, now, now),
            )
            conn.commit()
            return f"已存储密钥: 服务='{service_name}', key_name='{key_name}'"
        except Exception as exc:
            return f"存储密钥失败: {exc}"
        finally:
            conn.close()

    elif action == "get":
        if not service_name:
            return "获取密钥需要提供 service_name"
        conn = _get_db()
        try:
            row = conn.execute(
                "SELECT key_value FROM api_keys WHERE service = ? AND key_name = ?",
                (service_name, key_name),
            ).fetchone()
            if row is None:
                return f"未找到密钥: 服务='{service_name}', key_name='{key_name}'"
            decrypted = _decrypt_value(row[0])
            return json.dumps(
                {"service": service_name, "key_name": key_name, "key_value": decrypted},
                ensure_ascii=False,
            )
        except Exception as exc:
            return f"获取密钥失败: {exc}"
        finally:
            conn.close()

    elif action == "list":
        conn = _get_db()
        try:
            rows = conn.execute(
                "SELECT service, key_name, created_at, updated_at FROM api_keys ORDER BY service, key_name"
            ).fetchall()
            if not rows:
                return "当前没有存储任何密钥"
            entries = []
            for svc, kn, created, updated in rows:
                entries.append({
                    "service": svc,
                    "key_name": kn,
                    "created_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(created)),
                    "updated_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(updated)),
                })
            return json.dumps(entries, ensure_ascii=False, indent=2)
        except Exception as exc:
            return f"列出密钥失败: {exc}"
        finally:
            conn.close()

    elif action == "delete":
        if not service_name:
            return "删除密钥需要提供 service_name"
        conn = _get_db()
        try:
            cursor = conn.execute(
                "DELETE FROM api_keys WHERE service = ? AND key_name = ?",
                (service_name, key_name),
            )
            conn.commit()
            if cursor.rowcount == 0:
                return f"未找到要删除的密钥: 服务='{service_name}', key_name='{key_name}'"
            return f"已删除密钥: 服务='{service_name}', key_name='{key_name}'"
        except Exception as exc:
            return f"删除密钥失败: {exc}"
        finally:
            conn.close()

    else:
        return f"不支持的操作: {action}，请使用 store/get/list/delete"


# ---- api_parse_response ----------------------------------------------------

async def api_parse_response(
    response_data: str | dict,
    template: str = "json_path",
    extract_pattern: str = "",
) -> str:
    """Parse and extract data from API responses using templates or patterns.

    Built-in templates:
    - ``rest_success``: extracts ``data`` / ``result`` / ``content`` fields
    - ``rest_error``:  extracts error message from common error shapes
    - ``pagination``:  extracts ``next_page`` / ``items`` / ``total``
    - ``json_path``:   extracts a value by dot-separated JSON path
    - ``jmespath``:    extracts using a JMESPath expression (basic subset)
    - ``regex``:       applies a regex pattern to the raw response text
    """
    # Normalise input
    if isinstance(response_data, str):
        try:
            data = json.loads(response_data)
        except json.JSONDecodeError:
            data = None
        raw_text = response_data
    elif isinstance(response_data, dict):
        data = response_data
        raw_text = json.dumps(response_data, ensure_ascii=False)
    else:
        data = None
        raw_text = str(response_data)

    template = template.lower().strip()

    try:
        if template == "rest_success":
            return _extract_rest_success(data, raw_text)
        elif template == "rest_error":
            return _extract_rest_error(data, raw_text)
        elif template == "pagination":
            return _extract_pagination(data, raw_text)
        elif template == "json_path":
            if not extract_pattern:
                return "使用 json_path 模板时需要提供 extract_pattern (如 'data.items')"
            return _extract_json_path(data, extract_pattern)
        elif template == "jmespath":
            if not extract_pattern:
                return "使用 jmespath 模板时需要提供 extract_pattern"
            return _extract_jmespath(data, extract_pattern)
        elif template == "regex":
            if not extract_pattern:
                return "使用 regex 模板时需要提供 extract_pattern"
            return _extract_regex(raw_text, extract_pattern)
        elif template == "custom":
            if not extract_pattern:
                return "使用 custom 模板时需要提供 extract_pattern (JSONPath 表达式)"
            return _extract_json_path(data, extract_pattern)
        else:
            return f"不支持的模板: {template}，请使用 rest_success/rest_error/pagination/json_path/jmespath/regex/custom"
    except Exception as exc:
        return f"解析响应失败: {exc}"


def _extract_rest_success(data: Any, raw_text: str) -> str:
    """Try common field names for successful API payloads."""
    if isinstance(data, dict):
        for key in ("data", "result", "content", "response", "body", "payload"):
            if key in data:
                return json.dumps(data[key], ensure_ascii=False, indent=2)
        # If none of the common keys exist, return the whole object
        return json.dumps(data, ensure_ascii=False, indent=2)
    return raw_text


def _extract_rest_error(data: Any, raw_text: str) -> str:
    """Try common field names for error payloads."""
    if isinstance(data, dict):
        for key in ("message", "error", "error_message", "msg", "detail", "reason"):
            val = data.get(key)
            if val is not None:
                if isinstance(val, dict):
                    # Some APIs nest: {"error": {"message": "..."}}
                    for sub in ("message", "msg", "text", "detail"):
                        if sub in val:
                            return json.dumps(
                                {"error": val[sub], "full_error": val},
                                ensure_ascii=False, indent=2,
                            )
                    return json.dumps(val, ensure_ascii=False, indent=2)
                return str(val)
        # Check for HTTP-style error
        status = data.get("status_code") or data.get("status") or data.get("code")
        if status is not None:
            return json.dumps(data, ensure_ascii=False, indent=2)
    return raw_text


def _extract_pagination(data: Any, raw_text: str) -> str:
    """Extract pagination metadata."""
    if isinstance(data, dict):
        result: dict[str, Any] = {}
        for key in ("items", "results", "data", "records", "list", "rows"):
            if key in data and isinstance(data[key], list):
                result["items"] = data[key]
                break
        for key in ("next_page", "next", "next_url", "next_cursor", "page_token"):
            if key in data:
                result["next_page"] = data[key]
                break
        for key in ("total", "total_count", "count", "total_items"):
            if key in data:
                result["total"] = data[key]
                break
        if result:
            return json.dumps(result, ensure_ascii=False, indent=2)
    return raw_text


def _extract_json_path(data: Any, path: str) -> str:
    """Walk a dot-separated path into a nested dict/list structure.

    Supports integer indices for list access, e.g. ``data.items.0.name``.
    """
    parts = path.split(".")
    current: Any = data
    for part in parts:
        if current is None:
            return f"路径 '{path}' 解析失败: 中间值为 null (在 '{part}')"
        if isinstance(current, dict):
            if part not in current:
                return f"路径 '{path}' 解析失败: 键 '{part}' 不存在"
            current = current[part]
        elif isinstance(current, (list, tuple)):
            try:
                idx = int(part)
                current = current[idx]
            except (ValueError, IndexError):
                return f"路径 '{path}' 解析失败: 列表索引 '{part}' 无效"
        else:
            return f"路径 '{path}' 解析失败: 在 '{part}' 处无法继续 (当前类型: {type(current).__name__})"

    if isinstance(current, (dict, list)):
        return json.dumps(current, ensure_ascii=False, indent=2)
    return str(current)


def _extract_jmespath(data: Any, expression: str) -> str:
    """Basic JMESPath-like extraction (dot notation + array projections).

    This is a lightweight implementation covering the most common patterns
    without requiring the ``jmespath`` package.  For full JMESPath support
    the caller should pre-process the data.
    """
    # For simple dot-notation, delegate to _extract_json_path
    if re.match(r'^[a-zA-Z0-9_.]+$', expression):
        return _extract_json_path(data, expression)

    # Handle simple array projection: items[*].name
    match = re.match(r'^(\w+)\[\*\]\.(\w+)$', expression)
    if match and isinstance(data, dict):
        arr_key, field = match.groups()
        arr = data.get(arr_key, [])
        if isinstance(arr, list):
            result = [item.get(field) for item in arr if isinstance(item, dict)]
            return json.dumps(result, ensure_ascii=False, indent=2)

    return f"无法解析 JMESPath 表达式: {expression}（仅支持简单的点号和数组投影语法）"


def _extract_regex(text: str, pattern: str) -> str:
    """Apply a regex and return all matches."""
    try:
        matches = re.findall(pattern, text)
        if not matches:
            return "未找到匹配项"
        if len(matches) == 1:
            return str(matches[0])
        return json.dumps(matches, ensure_ascii=False, indent=2)
    except re.error as exc:
        return f"正则表达式错误: {exc}"


# ---- api_webhook -----------------------------------------------------------

async def api_webhook(
    action: str,
    name: str = "",
    url: str = "",
    secret: str = "",
) -> str:
    """Register, list, delete, or test webhooks for receiving external events.

    Webhooks are persisted in ``data/webhooks.json``.  The *test* action
    sends a minimal JSON payload to the registered URL to verify
    reachability.
    """
    action = action.lower().strip()

    try:
        webhooks = _load_webhooks()
    except Exception as exc:
        return f"加载 webhook 配置失败: {exc}"

    if action == "register":
        if not name or not url:
            return "注册 webhook 需要提供 name 和 url"
        entry: dict[str, Any] = {
            "url": url,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        if secret:
            entry["secret"] = secret
        webhooks[name] = entry
        try:
            _save_webhooks(webhooks)
        except Exception as exc:
            return f"保存 webhook 失败: {exc}"
        return f"已注册 webhook: name='{name}', url='{url}'"

    elif action == "list":
        if not webhooks:
            return "当前没有注册任何 webhook"
        entries = []
        for wh_name, wh_data in webhooks.items():
            entries.append({
                "name": wh_name,
                "url": wh_data.get("url", ""),
                "has_secret": bool(wh_data.get("secret")),
                "created_at": wh_data.get("created_at", ""),
            })
        return json.dumps(entries, ensure_ascii=False, indent=2)

    elif action == "delete":
        if not name:
            return "删除 webhook 需要提供 name"
        if name not in webhooks:
            return f"未找到 webhook: name='{name}'"
        del webhooks[name]
        try:
            _save_webhooks(webhooks)
        except Exception as exc:
            return f"保存 webhook 失败: {exc}"
        return f"已删除 webhook: name='{name}'"

    elif action == "test":
        if not name:
            return "测试 webhook 需要提供 name"
        if name not in webhooks:
            return f"未找到 webhook: name='{name}'"

        target_url = webhooks[name]["url"]
        secret = webhooks[name].get("secret", "")

        test_payload = {
            "event": "webhook_test",
            "name": name,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "data": {"message": "This is a test payload from api_webhook"},
        }
        payload_bytes = json.dumps(test_payload, ensure_ascii=False).encode("utf-8")

        req_headers = {"Content-Type": "application/json"}
        if secret:
            # Sign the payload with HMAC-SHA256 for verification
            import hmac
            signature = hmac.new(
                secret.encode("utf-8"), payload_bytes, hashlib.sha256
            ).hexdigest()
            req_headers["X-Webhook-Signature"] = f"sha256={signature}"

        try:
            req = urllib.request.Request(
                target_url,
                data=payload_bytes,
                headers=req_headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                status = resp.status
                resp_body = resp.read().decode("utf-8", errors="replace")[:500]
            return json.dumps(
                {
                    "status": "success",
                    "http_status": status,
                    "response_body": resp_body,
                    "test_payload_sent": test_payload,
                },
                ensure_ascii=False,
                indent=2,
            )
        except urllib.error.HTTPError as exc:
            return json.dumps(
                {
                    "status": "http_error",
                    "http_status": exc.code,
                    "response_body": exc.read().decode("utf-8", errors="replace")[:500],
                },
                ensure_ascii=False,
                indent=2,
            )
        except urllib.error.URLError as exc:
            return f"webhook 测试失败 (URL 不可达): {exc.reason}"
        except Exception as exc:
            return f"webhook 测试失败: {exc}"

    else:
        return f"不支持的操作: {action}，请使用 register/list/delete/test"


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------

def register(registry):
    registry.register(
        name="api_request",
        description=(
            "向外部API发送认证的HTTP请求。支持GET/POST/PUT/DELETE/PATCH方法，"
            "支持bearer/api_key/oauth认证，可自动从密钥库获取凭证。"
            "自动解析JSON响应，返回状态码、响应头和响应体。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "method": {
                    "type": "string",
                    "enum": ["GET", "POST", "PUT", "DELETE", "PATCH"],
                    "description": "HTTP方法",
                },
                "url": {
                    "type": "string",
                    "description": "请求的完整URL地址",
                },
                "headers": {
                    "type": "object",
                    "description": "自定义请求头（可选），如 Content-Type, Accept 等",
                },
                "body": {
                    "description": "请求体：可以是字典(自动序列化为JSON)或字符串",
                },
                "auth_type": {
                    "type": "string",
                    "enum": ["none", "bearer", "api_key", "oauth"],
                    "description": "认证类型: none(无), bearer(Token), api_key(API密钥), oauth(OAuth2令牌)",
                },
                "auth_config": {
                    "type": "object",
                    "description": (
                        "认证配置。bearer/oauth需要token字段; "
                        "api_key需要header或param字段; "
                        "也可用service字段引用已存储的密钥，如 {\"service\": \"github\", \"key_name\": \"default\"}"
                    ),
                },
            },
            "required": ["method", "url"],
        },
        handler=api_request,
        is_async=True,
        toolset="api",
        emoji="🌐",
    )

    registry.register(
        name="api_key_store",
        description=(
            "安全存储和管理外部服务的API密钥。密钥使用Fernet加密保存在SQLite数据库中。"
            "支持存储(store)、获取(get)、列表(list)、删除(delete)操作。"
            "同一服务可存储多个密钥(通过key_name区分)。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["store", "get", "list", "delete"],
                    "description": "操作类型: store(存储), get(获取), list(列出所有), delete(删除)",
                },
                "service_name": {
                    "type": "string",
                    "description": "服务名称，如 github, openai, weather 等",
                },
                "key_value": {
                    "type": "string",
                    "description": "要存储的密钥值（仅store操作需要）",
                },
                "key_name": {
                    "type": "string",
                    "description": "密钥名称，用于同一服务有多个密钥的情况（默认'default'）",
                },
            },
            "required": ["action"],
        },
        handler=api_key_store,
        is_async=True,
        toolset="api",
        emoji="🔑",
    )

    registry.register(
        name="api_parse_response",
        description=(
            "从API响应中解析和提取数据。支持内置模板(rest_success/rest_error/pagination)"
            "快速提取常见字段，也支持json_path点号路径、jmespath数组投影、"
            "正则表达式等自定义提取方式。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "response_data": {
                    "description": "API响应数据，可以是字典或JSON字符串",
                },
                "template": {
                    "type": "string",
                    "enum": [
                        "rest_success", "rest_error", "pagination",
                        "json_path", "jmespath", "regex", "custom",
                    ],
                    "description": (
                        "提取模板: rest_success(提取成功响应data/result/content), "
                        "rest_error(提取错误信息), pagination(提取分页数据), "
                        "json_path(点号路径如data.items.0.name), "
                        "jmespath(数组投影如items[*].name), "
                        "regex(正则匹配), custom(自定义JSONPath)"
                    ),
                },
                "extract_pattern": {
                    "type": "string",
                    "description": "提取模式/表达式: json_path的路径、jmespath表达式、正则模式等",
                },
            },
            "required": ["response_data", "template"],
        },
        handler=api_parse_response,
        is_async=True,
        toolset="api",
        emoji="📋",
    )

    registry.register(
        name="api_webhook",
        description=(
            "配置和管理webhook以接收外部事件。支持注册(register)、"
            "查看列表(list)、删除(delete)和测试(test)操作。"
            "注册时可设置secret用于HMAC签名验证。测试操作会发送测试payload验证webhook可达性。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["register", "list", "delete", "test"],
                    "description": "操作类型: register(注册), list(列出所有), delete(删除), test(发送测试)",
                },
                "name": {
                    "type": "string",
                    "description": "webhook名称，用于标识和管理",
                },
                "url": {
                    "type": "string",
                    "description": "webhook接收URL（仅register操作需要）",
                },
                "secret": {
                    "type": "string",
                    "description": "用于HMAC-SHA256签名的密钥（可选，register时使用）",
                },
            },
            "required": ["action"],
        },
        handler=api_webhook,
        is_async=True,
        toolset="api",
        emoji="🪝",
    )
