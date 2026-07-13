from __future__ import annotations

import asyncio
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from time import monotonic
from typing import Literal
from urllib.parse import urlsplit

import httpx

from ..config import Settings

ProxyMode = Literal["direct", "manual", "auto"]
ProxyProtocol = Literal["http", "https", "socks4", "socks5"]

POOL_URL = "https://proxy.scdn.io/api/get_proxy.php"
CHECK_URL = "https://api.ipify.org?format=json"
ALLOWED_PROTOCOLS = {"http", "https", "socks4", "socks5"}


class ProxyConfigurationError(ValueError):
    pass


class ProxyUnavailableError(RuntimeError):
    pass


@dataclass(slots=True)
class ProxyRuntimeState:
    mode: ProxyMode = "direct"
    protocol: ProxyProtocol = "https"
    country_code: str = "CN"
    pool_size: int = 5
    manual_proxy: str = ""
    active_proxy: str | None = None
    active_source: Literal["direct", "manual", "pool"] = "direct"
    exit_ip: str | None = None
    latency_ms: int | None = None
    last_checked_at: str | None = None
    last_error: str | None = None


@dataclass(slots=True)
class ProxyCheck:
    proxy: str
    reachable: bool
    latency_ms: int | None
    exit_ip: str | None
    message: str
    checked_at: str


class ProxyManager:
    """Persists the selected network route and validates pool candidates."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.path = settings.proxy_settings_path
        self._lock = asyncio.Lock()
        self._state = self._load()

    def _load(self) -> ProxyRuntimeState:
        if not self.path.exists():
            return ProxyRuntimeState()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            mode = payload.get("mode", "direct")
            protocol = payload.get("protocol", "https")
            if mode not in {"direct", "manual", "auto"} or protocol not in ALLOWED_PROTOCOLS:
                raise ValueError("invalid proxy settings")
            return ProxyRuntimeState(
                mode=mode,
                protocol=protocol,
                country_code=str(payload.get("country_code") or "").upper(),
                pool_size=max(1, min(20, int(payload.get("pool_size", 5)))),
                manual_proxy=str(payload.get("manual_proxy") or ""),
                active_proxy=payload.get("active_proxy") or None,
                active_source=payload.get("active_source", "direct"),
                exit_ip=payload.get("exit_ip") or None,
                latency_ms=payload.get("latency_ms"),
                last_checked_at=payload.get("last_checked_at") or None,
                last_error=payload.get("last_error") or None,
            )
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return ProxyRuntimeState(last_error="代理配置损坏，已恢复为直连")

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(asdict(self._state), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.chmod(temporary, 0o600)
        temporary.replace(self.path)

    @staticmethod
    def normalize_proxy(value: str, protocol: ProxyProtocol) -> str:
        raw = value.strip()
        if not raw:
            raise ProxyConfigurationError("请输入代理地址")
        if "://" not in raw:
            # Providers commonly call CONNECT-capable HTTP proxies "https" proxies.
            default_scheme = "http" if protocol in {"http", "https"} else protocol
            raw = f"{default_scheme}://{raw}"
        parsed = urlsplit(raw)
        scheme = parsed.scheme.casefold()
        if scheme not in ALLOWED_PROTOCOLS:
            raise ProxyConfigurationError("代理协议仅支持 HTTP、HTTPS、SOCKS4 或 SOCKS5")
        if parsed.username or parsed.password:
            raise ProxyConfigurationError("当前版本不保存带账号密码的代理")
        try:
            port = parsed.port
        except ValueError as exc:
            raise ProxyConfigurationError("代理端口超出有效范围") from exc
        if not parsed.hostname or port is None:
            raise ProxyConfigurationError("代理地址格式应为 IP:端口")
        if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise ProxyConfigurationError("代理地址不能包含路径、查询参数或片段")
        if not 1 <= port <= 65535:
            raise ProxyConfigurationError("代理端口超出有效范围")
        host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
        return f"{scheme}://{host}:{port}"

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def state(self) -> dict[str, object]:
        payload = asdict(self._state)
        payload["pool_api"] = POOL_URL
        return payload

    async def _check_proxy(self, server: str) -> ProxyCheck:
        started = monotonic()
        checked_at = self._now()
        scheme = urlsplit(server).scheme
        try:
            if scheme == "socks4":
                parsed = urlsplit(server)
                assert parsed.hostname and parsed.port
                _reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(parsed.hostname, parsed.port), timeout=5
                )
                writer.close()
                await writer.wait_closed()
                latency = round((monotonic() - started) * 1000)
                return ProxyCheck(
                    proxy=server,
                    reachable=True,
                    latency_ms=latency,
                    exit_ip=None,
                    message="SOCKS4 端口可连接，将由浏览器完成协议验证",
                    checked_at=checked_at,
                )
            timeout = httpx.Timeout(8, connect=5)
            async with httpx.AsyncClient(
                proxy=server,
                timeout=timeout,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                response = await client.get(CHECK_URL, headers={"Accept": "application/json"})
                response.raise_for_status()
                payload = response.json()
            latency = round((monotonic() - started) * 1000)
            exit_ip = str(payload.get("ip") or "").strip() or None
            return ProxyCheck(
                proxy=server,
                reachable=True,
                latency_ms=latency,
                exit_ip=exit_ip,
                message="代理出口可用",
                checked_at=checked_at,
            )
        except (OSError, ValueError, httpx.HTTPError, TimeoutError) as exc:
            detail = str(exc).casefold()
            if "certificate_verify_failed" in detail or "certificate verify failed" in detail:
                message = "TLS 证书被代理替换，可能泄露登录会话，已拒绝使用"
            elif isinstance(exc, (TimeoutError, httpx.TimeoutException)):
                message = "代理连接超时"
            else:
                message = f"代理不可用：{type(exc).__name__}"
            return ProxyCheck(
                proxy=server,
                reachable=False,
                latency_ms=None,
                exit_ip=None,
                message=message,
                checked_at=checked_at,
            )

    async def test(self, value: str | None = None, protocol: ProxyProtocol | None = None) -> ProxyCheck:
        selected_protocol = protocol or self._state.protocol
        candidate = value or self._state.active_proxy or self._state.manual_proxy
        server = self.normalize_proxy(candidate, selected_protocol)
        result = await self._check_proxy(server)
        async with self._lock:
            if server == self._state.active_proxy:
                self._state.exit_ip = result.exit_ip
                self._state.latency_ms = result.latency_ms
                self._state.last_checked_at = result.checked_at
                self._state.last_error = None if result.reachable else result.message
                self._save()
        return result

    async def _pool_candidates(
        self, protocol: ProxyProtocol, country_code: str, count: int
    ) -> list[str]:
        params: dict[str, str | int] = {"protocol": protocol, "count": count}
        if country_code:
            params["country_code"] = country_code
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(12, connect=6),
                follow_redirects=False,
                trust_env=False,
            ) as client:
                response = await client.get(POOL_URL, params=params)
                response.raise_for_status()
                payload = response.json()
        except (ValueError, httpx.HTTPError) as exc:
            raise ProxyUnavailableError(f"代理池请求失败：{type(exc).__name__}") from exc
        if payload.get("code") != 200:
            raise ProxyUnavailableError(str(payload.get("message") or "代理池返回错误"))
        raw_proxies = payload.get("data", {}).get("proxies", [])
        candidates: list[str] = []
        for raw in raw_proxies:
            try:
                normalized = self.normalize_proxy(str(raw), protocol)
            except ProxyConfigurationError:
                continue
            if normalized not in candidates:
                candidates.append(normalized)
        if not candidates:
            raise ProxyUnavailableError("代理池未返回有效地址")
        return candidates

    async def _select_pool_proxy(
        self,
        protocol: ProxyProtocol,
        country_code: str,
        count: int,
        previous: str | None,
    ) -> ProxyCheck:
        candidates = await self._pool_candidates(protocol, country_code, count)
        ordered = [candidate for candidate in candidates if candidate != previous]
        if previous in candidates:
            ordered.append(previous)
        failures: list[ProxyCheck] = []
        for offset in range(0, len(ordered), 4):
            batch = ordered[offset : offset + 4]
            results = await asyncio.gather(*(self._check_proxy(candidate) for candidate in batch))
            reachable = [result for result in results if result.reachable]
            if reachable:
                return min(reachable, key=lambda item: item.latency_ms or 1_000_000)
            failures.extend(results)
        tls_rejected = sum("TLS 证书" in result.message for result in failures)
        if tls_rejected:
            raise ProxyUnavailableError(
                f"代理池返回 {len(failures)} 个地址，其中 {tls_rejected} 个替换了 TLS 证书，已全部拒绝"
            )
        raise ProxyUnavailableError(f"代理池返回 {len(failures)} 个地址，但均未通过连通性检测")

    async def configure(
        self,
        *,
        mode: ProxyMode,
        protocol: ProxyProtocol,
        country_code: str,
        pool_size: int,
        manual_proxy: str,
    ) -> dict[str, object]:
        country = country_code.strip().upper()
        if country and (len(country) != 2 or not country.isalpha()):
            raise ProxyConfigurationError("国家代码应为两个字母，例如 CN")
        if not 1 <= pool_size <= 20:
            raise ProxyConfigurationError("代理池数量应在 1 到 20 之间")

        result: ProxyCheck | None = None
        normalized_manual = ""
        if mode == "manual":
            normalized_manual = self.normalize_proxy(manual_proxy, protocol)
            result = await self._check_proxy(normalized_manual)
            if not result.reachable:
                raise ProxyUnavailableError(result.message)
        elif mode == "auto":
            result = await self._select_pool_proxy(protocol, country, pool_size, None)

        async with self._lock:
            self._state = ProxyRuntimeState(
                mode=mode,
                protocol=protocol,
                country_code=country,
                pool_size=pool_size,
                manual_proxy=normalized_manual,
                active_proxy=result.proxy if result else None,
                active_source=("manual" if mode == "manual" else "pool" if mode == "auto" else "direct"),
                exit_ip=result.exit_ip if result else None,
                latency_ms=result.latency_ms if result else None,
                last_checked_at=result.checked_at if result else None,
                last_error=None,
            )
            self._save()
            return self.state()

    async def rotate(self) -> dict[str, object]:
        async with self._lock:
            if self._state.mode != "auto":
                raise ProxyConfigurationError("仅自动代理模式支持从代理池换线")
            protocol = self._state.protocol
            country = self._state.country_code
            count = self._state.pool_size
            previous = self._state.active_proxy
        result = await self._select_pool_proxy(protocol, country, count, previous)
        async with self._lock:
            self._state.active_proxy = result.proxy
            self._state.active_source = "pool"
            self._state.exit_ip = result.exit_ip
            self._state.latency_ms = result.latency_ms
            self._state.last_checked_at = result.checked_at
            self._state.last_error = None
            self._save()
            return self.state()

    async def ensure_active(self) -> str | None:
        async with self._lock:
            mode = self._state.mode
            active = self._state.active_proxy
            protocol = self._state.protocol
            country = self._state.country_code
            count = self._state.pool_size
        if mode == "direct":
            return None
        if active:
            return active
        if mode == "manual":
            raise ProxyConfigurationError("手动代理模式缺少有效地址")
        result = await self._select_pool_proxy(protocol, country, count, None)
        async with self._lock:
            self._state.active_proxy = result.proxy
            self._state.active_source = "pool"
            self._state.exit_ip = result.exit_ip
            self._state.latency_ms = result.latency_ms
            self._state.last_checked_at = result.checked_at
            self._state.last_error = None
            self._save()
        return result.proxy
