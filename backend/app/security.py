from __future__ import annotations

import base64
import binascii
import secrets
from collections.abc import Iterable

from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send


def basic_authorization_is_valid(
    authorization: bytes | None,
    username: str,
    password: str,
) -> bool:
    if not authorization:
        return False
    try:
        scheme, encoded = authorization.decode("ascii").split(" ", 1)
        if scheme.casefold() != "basic":
            return False
        decoded = base64.b64decode(encoded, validate=True).decode("utf-8")
        supplied_username, supplied_password = decoded.split(":", 1)
    except (ValueError, UnicodeDecodeError, binascii.Error):
        return False
    return secrets.compare_digest(supplied_username, username) and secrets.compare_digest(
        supplied_password, password
    )


class SharedAccessMiddleware:
    """Small HTTP Basic gate for a single-operator private deployment."""

    def __init__(
        self,
        app: ASGIApp,
        username: str,
        password: str,
        exempt_paths: Iterable[str] = (),
    ) -> None:
        self.app = app
        self.username = username
        self.password = password
        self.exempt_paths = frozenset(exempt_paths)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") in self.exempt_paths:
            await self.app(scope, receive, send)
            return

        authorization = dict(scope.get("headers", [])).get(b"authorization")
        if basic_authorization_is_valid(authorization, self.username, self.password):
            await self.app(scope, receive, send)
            return

        response = Response(
            "Authentication required",
            status_code=401,
            headers={
                "WWW-Authenticate": 'Basic realm="Autobili", charset="UTF-8"',
                "Cache-Control": "no-store",
            },
        )
        await response(scope, receive, send)
