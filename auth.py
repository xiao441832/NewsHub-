"""JWT 认证模块 — 支持 Cookie 跨页面同步"""
import hashlib
import hmac
import json
import base64
import time
from typing import Optional

SECRET = "newshub-secret-key-change-in-production"
TOKEN_EXPIRE = 86400 * 7  # 7 天过期


def _b64encode(data: bytes) -> str:
    """URL-safe Base64 编码"""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64decode(s: str) -> bytes:
    """URL-safe Base64 解码"""
    s += "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s)


def create_token(user_id: int, username: str) -> str:
    """生成 JWT Token"""
    header = _b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = _b64encode(json.dumps({
        "user_id": user_id,
        "username": username,
        "exp": int(time.time()) + TOKEN_EXPIRE,
    }).encode())
    sig_input = f"{header}.{payload}".encode()
    signature = _b64encode(hmac.new(SECRET.encode(), sig_input, hashlib.sha256).digest())
    return f"{header}.{payload}.{signature}"


def verify_token(token: str) -> Optional[dict]:
    """验证 JWT Token，返回 payload 或 None"""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        header, payload, signature = parts
        sig_input = f"{header}.{payload}".encode()
        expected = _b64encode(hmac.new(SECRET.encode(), sig_input, hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            return None
        data = json.loads(_b64decode(payload))
        if data.get("exp", 0) < time.time():
            return None
        return data
    except Exception:
        return None


def hash_password(password: str) -> str:
    """密码 SHA-256 哈希"""
    return hashlib.sha256(password.encode()).hexdigest()


def get_current_user_from_request(request) -> Optional[dict]:
    """从请求中提取当前用户 — 优先 Cookie，其次 Authorization Header

    返回示例: {"user_id": 1, "username": "test"} 或 None
    """
    token = None

    # 1. 优先从 Cookie 读取（页面跳转自动携带）
    token = request.cookies.get("access_token")

    # 2. Cookie 没有则从 Authorization Header 读取（兼容 fetch 请求）
    if not token:
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]

    if not token:
        return None

    return verify_token(token)
