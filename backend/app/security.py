from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from collections import defaultdict, deque
from collections.abc import Iterable
from http.cookies import SimpleCookie

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

SESSION_COOKIE = "autobili_session"


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


class SessionSigner:
    def __init__(self, secret: str, ttl_seconds: int = 43_200) -> None:
        self.key = hashlib.sha256(f"autobili-session:{secret}".encode("utf-8")).digest()
        self.share_key = hashlib.sha256(f"autobili-share:{secret}".encode("utf-8")).digest()
        self.ttl_seconds = ttl_seconds

    def issue(self, username: str, now: int | None = None) -> str:
        issued_at = int(time.time()) if now is None else now
        payload = {
            "u": username,
            "exp": issued_at + self.ttl_seconds,
            "n": secrets.token_urlsafe(12),
        }
        encoded = _b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
        signature = _b64encode(hmac.new(self.key, encoded.encode("ascii"), hashlib.sha256).digest())
        return f"{encoded}.{signature}"

    def verify(self, token: str | None, now: int | None = None) -> str | None:
        if not token:
            return None
        try:
            encoded, supplied = token.split(".", 1)
            expected = _b64encode(
                hmac.new(self.key, encoded.encode("ascii"), hashlib.sha256).digest()
            )
            if not secrets.compare_digest(supplied, expected):
                return None
            payload = json.loads(_b64decode(encoded))
            current = int(time.time()) if now is None else now
            if int(payload["exp"]) <= current:
                return None
            username = str(payload["u"])
            return username if username else None
        except (ValueError, KeyError, TypeError, json.JSONDecodeError):
            return None

    def share_hash(self, token: str) -> str:
        return hmac.new(self.share_key, token.encode("utf-8"), hashlib.sha256).hexdigest()


def cookie_value(scope: Scope, name: str = SESSION_COOKIE) -> str | None:
    headers = dict(scope.get("headers", []))
    raw = headers.get(b"cookie", b"").decode("latin-1")
    cookie = SimpleCookie()
    try:
        cookie.load(raw)
    except Exception:
        return None
    morsel = cookie.get(name)
    return morsel.value if morsel else None


class LoginThrottle:
    def __init__(self, max_attempts: int = 6, window_seconds: int = 600) -> None:
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self.failures: dict[str, deque[float]] = defaultdict(deque)

    def is_blocked(self, key: str, now: float | None = None) -> bool:
        current = time.monotonic() if now is None else now
        values = self.failures[key]
        while values and current - values[0] > self.window_seconds:
            values.popleft()
        return len(values) >= self.max_attempts

    def fail(self, key: str, now: float | None = None) -> None:
        self.failures[key].append(time.monotonic() if now is None else now)

    def clear(self, key: str) -> None:
        self.failures.pop(key, None)


class SessionAccessMiddleware:
    """Cookie gate for private API routes without triggering browser-native auth UI."""

    def __init__(
        self,
        app: ASGIApp,
        signer: SessionSigner,
        exempt_prefixes: Iterable[str] = (),
        allowed_origins: Iterable[str] = (),
    ) -> None:
        self.app = app
        self.signer = signer
        self.exempt_prefixes = tuple(exempt_prefixes)
        self.allowed_origins = frozenset(origin.rstrip("/") for origin in allowed_origins)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = str(scope.get("path", ""))
        if not path.startswith("/api/") or any(path.startswith(item) for item in self.exempt_prefixes):
            await self.app(scope, receive, send)
            return

        username = self.signer.verify(cookie_value(scope))
        if not username:
            response = JSONResponse(
                {"detail": "登录已过期，请重新登录"},
                status_code=401,
                headers={"Cache-Control": "no-store"},
            )
            await response(scope, receive, send)
            return

        method = str(scope.get("method", "GET")).upper()
        origin = dict(scope.get("headers", [])).get(b"origin")
        if method not in {"GET", "HEAD", "OPTIONS"} and origin:
            supplied_origin = origin.decode("latin-1").rstrip("/")
            if supplied_origin not in self.allowed_origins:
                response = JSONResponse({"detail": "请求来源校验失败"}, status_code=403)
                await response(scope, receive, send)
                return

        scope.setdefault("state", {})["username"] = username
        await self.app(scope, receive, send)
