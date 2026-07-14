from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from time import monotonic
from typing import Literal
from urllib.parse import urlsplit

import httpx

from ..config import Settings

ProxyMode = Literal["direct", "manual", "auto"]
ProxyProtocol = Literal["http", "https", "socks4", "socks5"]
ProxyPoolProvider = Literal["smart", "scdn", "zdopen"]
ProxyPlatformScope = Literal["taptap", "all"]

SCDN_POOL_URL = "https://proxy.scdn.io/api/get_proxy.php"
ZDOPEN_POOL_URL = "http://www.zdopen.com/FreeProxy/Get/"
POOL_URLS = {"scdn": SCDN_POOL_URL, "zdopen": ZDOPEN_POOL_URL}
CHECK_URL = "https://api.ipify.org?format=json"
TARGET_URLS = {
    "bilibili": "https://www.bilibili.com/robots.txt",
    "taptap": "https://www.taptap.cn/robots.txt",
}
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
    pool_provider: ProxyPoolProvider = "smart"
    platform_scope: ProxyPlatformScope = "taptap"
    allow_tls_interception: bool = False
    auto_rotate_on_risk: bool = True
    risk_rotation_limit: int = 2
    zdopen_app_id: str = ""
    zdopen_akey: str = ""
    manual_proxy: str = ""
    active_proxy: str | None = None
    active_source: Literal["direct", "manual", "pool"] = "direct"
    exit_ip: str | None = None
    latency_ms: int | None = None
    last_checked_at: str | None = None
    last_error: str | None = None
    target_results: dict[str, bool] = field(default_factory=dict)
    active_provider: str | None = None
    tls_intercepted: bool = False


@dataclass(slots=True)
class ProxyCheck:
    proxy: str
    reachable: bool
    latency_ms: int | None
    exit_ip: str | None
    message: str
    checked_at: str
    targets: dict[str, bool] = field(default_factory=dict)
    provider: str | None = None
    tls_intercepted: bool = False


class ProxyManager:
    """Persists the selected network route and validates pool candidates."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.path = settings.proxy_settings_path
        self._lock = asyncio.Lock()
        self._state = self._load()
        self._rejected_until: dict[tuple[str, bool, str], float] = {}

    def _load(self) -> ProxyRuntimeState:
        if not self.path.exists():
            return ProxyRuntimeState(
                zdopen_app_id=self.settings.zdopen_app_id or "",
                zdopen_akey=self.settings.zdopen_akey_value,
            )
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            mode = payload.get("mode", "direct")
            protocol = payload.get("protocol", "https")
            provider = payload.get("pool_provider", "smart")
            platform_scope = payload.get("platform_scope", "taptap")
            if (
                mode not in {"direct", "manual", "auto"}
                or protocol not in ALLOWED_PROTOCOLS
                or provider not in {"smart", "scdn", "zdopen"}
                or platform_scope not in {"taptap", "all"}
            ):
                raise ValueError("invalid proxy settings")
            return ProxyRuntimeState(
                mode=mode,
                protocol=protocol,
                country_code=str(payload.get("country_code") or "").upper(),
                pool_size=max(1, min(100, int(payload.get("pool_size", 5)))),
                pool_provider=provider,
                platform_scope=platform_scope,
                allow_tls_interception=bool(payload.get("allow_tls_interception", False)),
                auto_rotate_on_risk=bool(payload.get("auto_rotate_on_risk", True)),
                risk_rotation_limit=max(
                    0, min(5, int(payload.get("risk_rotation_limit", 2)))
                ),
                zdopen_app_id=str(
                    payload.get("zdopen_app_id") or self.settings.zdopen_app_id or ""
                ),
                zdopen_akey=str(
                    payload.get("zdopen_akey") or self.settings.zdopen_akey_value
                ),
                manual_proxy=str(payload.get("manual_proxy") or ""),
                active_proxy=payload.get("active_proxy") or None,
                active_source=payload.get("active_source", "direct"),
                exit_ip=payload.get("exit_ip") or None,
                latency_ms=payload.get("latency_ms"),
                last_checked_at=payload.get("last_checked_at") or None,
                last_error=payload.get("last_error") or None,
                target_results={
                    str(key): bool(value)
                    for key, value in dict(payload.get("target_results") or {}).items()
                },
                active_provider=payload.get("active_provider") or None,
                tls_intercepted=bool(payload.get("tls_intercepted", False)),
            )
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return ProxyRuntimeState(
                zdopen_app_id=self.settings.zdopen_app_id or "",
                zdopen_akey=self.settings.zdopen_akey_value,
                last_error="代理配置损坏，已恢复为直连",
            )

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
        payload.pop("zdopen_akey", None)
        payload["zdopen_configured"] = bool(
            self._state.zdopen_app_id and self._state.zdopen_akey
        )
        payload["pool_api"] = POOL_URLS.get(
            self._state.pool_provider, SCDN_POOL_URL
        )
        payload["pool_apis"] = POOL_URLS
        return payload

    @staticmethod
    def _is_certificate_error(exc: Exception) -> bool:
        detail = str(exc).casefold()
        return "certificate_verify_failed" in detail or "certificate verify failed" in detail

    async def _check_proxy(
        self,
        server: str,
        *,
        allow_tls_interception: bool | None = None,
        platform_scope: ProxyPlatformScope | None = None,
        provider: str | None = None,
    ) -> ProxyCheck:
        started = monotonic()
        checked_at = self._now()
        scheme = urlsplit(server).scheme
        allow_interception = (
            self._state.allow_tls_interception
            if allow_tls_interception is None
            else allow_tls_interception
        )
        scope = platform_scope or self._state.platform_scope
        required_targets = {"taptap"} if scope == "taptap" else set(TARGET_URLS)

        async def probe(*, verify: bool) -> tuple[str | None, dict[str, bool]]:
            timeout = httpx.Timeout(8, connect=5)
            async with httpx.AsyncClient(
                proxy=server,
                timeout=timeout,
                follow_redirects=True,
                trust_env=False,
                verify=verify,
            ) as client:
                response = await client.get(CHECK_URL, headers={"Accept": "application/json"})
                response.raise_for_status()
                payload = response.json()
                targets: dict[str, bool] = {}
                for name, url in TARGET_URLS.items():
                    try:
                        target_response = await client.get(
                            url,
                            headers={
                                "Accept": "text/plain,text/html;q=0.8",
                                "Range": "bytes=0-2047",
                            },
                        )
                        targets[name] = (
                            target_response.status_code < 500
                            and target_response.status_code != 407
                        )
                    except (OSError, httpx.HTTPError, TimeoutError):
                        targets[name] = False
                        if name in required_targets:
                            raise
                failed = [name for name in required_targets if not targets.get(name)]
                if failed:
                    raise ProxyUnavailableError(f"目标站不可用：{'、'.join(sorted(failed))}")
            return str(payload.get("ip") or "").strip() or None, targets

        try:
            if scheme == "socks4":
                return ProxyCheck(
                    proxy=server,
                    reachable=False,
                    latency_ms=None,
                    exit_ip=None,
                    message="SOCKS4 无法完成目标站 TLS 验证，已拒绝接入登录会话",
                    checked_at=checked_at,
                    targets={key: False for key in TARGET_URLS},
                    provider=provider,
                )
            exit_ip, targets = await probe(verify=True)
            latency = round((monotonic() - started) * 1000)
            checked_label = "TapTap" if scope == "taptap" else "B站与 TapTap"
            return ProxyCheck(
                proxy=server,
                reachable=True,
                latency_ms=latency,
                exit_ip=exit_ip,
                message=f"代理已通过出口与{checked_label}严格 TLS 检测",
                checked_at=checked_at,
                targets=targets,
                provider=provider,
            )
        except (OSError, ValueError, httpx.HTTPError, ProxyUnavailableError, TimeoutError) as exc:
            active_exc: Exception = exc
            if self._is_certificate_error(exc) and allow_interception:
                try:
                    exit_ip, targets = await probe(verify=False)
                    return ProxyCheck(
                        proxy=server,
                        reachable=True,
                        latency_ms=round((monotonic() - started) * 1000),
                        exit_ip=exit_ip,
                        message="代理替换了 TLS 证书，已按显式兼容设置接入",
                        checked_at=checked_at,
                        targets=targets,
                        provider=provider,
                        tls_intercepted=True,
                    )
                except Exception as compatibility_exc:
                    active_exc = compatibility_exc
            if self._is_certificate_error(active_exc):
                message = "TLS 证书被代理替换，可能泄露登录会话，已拒绝使用"
            elif isinstance(active_exc, (TimeoutError, httpx.TimeoutException)):
                message = "代理连接超时"
            elif isinstance(active_exc, ProxyUnavailableError):
                message = str(active_exc)
            else:
                message = f"代理不可用：{type(active_exc).__name__}"
            return ProxyCheck(
                proxy=server,
                reachable=False,
                latency_ms=None,
                exit_ip=None,
                message=message,
                checked_at=checked_at,
                targets={key: False for key in TARGET_URLS},
                provider=provider,
            )
        except Exception as exc:
            # Some SOCKS transports expose httpcore exceptions directly instead
            # of wrapping them as httpx.HTTPError. Treat them as candidate-local.
            return ProxyCheck(
                proxy=server,
                reachable=False,
                latency_ms=None,
                exit_ip=None,
                message=f"代理握手异常：{type(exc).__name__}",
                checked_at=checked_at,
                targets={key: False for key in TARGET_URLS},
                provider=provider,
            )

    async def _check_direct(self) -> ProxyCheck:
        started = monotonic()
        checked_at = self._now()
        try:
            timeout = httpx.Timeout(10, connect=6)
            async with httpx.AsyncClient(
                timeout=timeout,
                follow_redirects=True,
                trust_env=False,
            ) as client:
                response = await client.get(CHECK_URL, headers={"Accept": "application/json"})
                response.raise_for_status()
                exit_ip = str(response.json().get("ip") or "").strip() or None
                targets = {}
                for name, url in TARGET_URLS.items():
                    target_response = await client.get(
                        url,
                        headers={"Accept": "text/plain,text/html;q=0.8", "Range": "bytes=0-2047"},
                    )
                    targets[name] = target_response.status_code < 500
            reachable = all(targets.values())
            failed = "、".join(name for name, available in targets.items() if not available)
            return ProxyCheck(
                proxy="DIRECT",
                reachable=reachable,
                latency_ms=round((monotonic() - started) * 1000),
                exit_ip=exit_ip,
                message="直连已通过出口、B站与 TapTap 检测"
                if reachable
                else f"直连目标站不可用：{failed}",
                checked_at=checked_at,
                targets=targets,
            )
        except (OSError, ValueError, httpx.HTTPError, TimeoutError) as exc:
            return ProxyCheck(
                proxy="DIRECT",
                reachable=False,
                latency_ms=None,
                exit_ip=None,
                message=f"直连检测失败：{type(exc).__name__}",
                checked_at=checked_at,
                targets={key: False for key in TARGET_URLS},
            )

    async def test(
        self,
        value: str | None = None,
        protocol: ProxyProtocol | None = None,
        *,
        allow_tls_interception: bool | None = None,
        platform_scope: ProxyPlatformScope | None = None,
    ) -> ProxyCheck:
        selected_protocol = protocol or self._state.protocol
        candidate = value or self._state.active_proxy or self._state.manual_proxy
        if not candidate and self._state.mode == "direct":
            server = "DIRECT"
            result = await self._check_direct()
        else:
            server = self.normalize_proxy(candidate, selected_protocol)
            result = await self._check_proxy(
                server,
                allow_tls_interception=allow_tls_interception,
                platform_scope=platform_scope,
            )
        async with self._lock:
            if server == self._state.active_proxy or server == "DIRECT" and self._state.mode == "direct":
                self._state.exit_ip = result.exit_ip
                self._state.latency_ms = result.latency_ms
                self._state.last_checked_at = result.checked_at
                self._state.last_error = None if result.reachable else result.message
                self._state.target_results = result.targets
                self._state.tls_intercepted = result.tls_intercepted
                self._save()
        return result

    async def _scdn_candidates(
        self, protocol: ProxyProtocol, country_code: str, count: int
    ) -> list[tuple[str, str]]:
        params: dict[str, str | int] = {
            "protocol": protocol,
            "count": min(20, count),
        }
        if country_code:
            params["country_code"] = country_code
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(12, connect=6),
                follow_redirects=False,
                trust_env=False,
            ) as client:
                response = await client.get(SCDN_POOL_URL, params=params)
                response.raise_for_status()
                payload = response.json()
        except (ValueError, httpx.HTTPError) as exc:
            raise ProxyUnavailableError(f"代理池请求失败：{type(exc).__name__}") from exc
        if payload.get("code") != 200:
            raise ProxyUnavailableError(str(payload.get("message") or "代理池返回错误"))
        raw_proxies = payload.get("data", {}).get("proxies", [])
        candidates: list[tuple[str, str]] = []
        for raw in raw_proxies:
            try:
                normalized = self.normalize_proxy(str(raw), protocol)
            except ProxyConfigurationError:
                continue
            candidate = (normalized, "scdn")
            if candidate not in candidates:
                candidates.append(candidate)
        if not candidates:
            raise ProxyUnavailableError("SCDN 代理池未返回有效地址")
        return candidates

    async def _zdopen_candidates(
        self,
        protocol: ProxyProtocol,
        country_code: str,
        count: int,
        app_id: str,
        akey: str,
    ) -> list[tuple[str, str]]:
        if not app_id or not akey:
            raise ProxyConfigurationError("ZDOpen 需要配置应用 ID 与 akey")
        protocol_type = {"http": 1, "socks4": 2, "socks5": 3, "https": 4}[protocol]
        common_params: dict[str, str | int] = {
            "akey": akey,
            "count": min(100, count),
            "dalu": 1 if country_code in {"", "CN"} else 0,
            "protocol_type": protocol_type,
            "level_type": 1,
            "lastcheck_type": 2,
            "sleep_type": 2,
            "return_type": 3,
        }
        payload: dict[str, object] = {}
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(15, connect=6),
                follow_redirects=False,
                trust_env=False,
            ) as client:
                for index, app_id_field in enumerate(("api", "app_id")):
                    response = await client.get(
                        ZDOPEN_POOL_URL,
                        params={**common_params, app_id_field: app_id},
                    )
                    response.raise_for_status()
                    raw_payload = response.json()
                    if not isinstance(raw_payload, dict):
                        raise ValueError("invalid ZDOpen response")
                    payload = raw_payload
                    if str(payload.get("code")) != "12003" or index == 1:
                        break
                    await asyncio.sleep(1.05)
        except (ValueError, httpx.HTTPError) as exc:
            raise ProxyUnavailableError(f"ZDOpen 请求失败：{type(exc).__name__}") from exc
        if str(payload.get("code")) != "10001":
            raise ProxyUnavailableError(str(payload.get("msg") or "ZDOpen 返回错误"))
        data = payload.get("data")
        raw_proxies = data.get("proxy_list", []) if isinstance(data, dict) else []
        candidates: list[tuple[str, str]] = []
        for raw in raw_proxies:
            if not isinstance(raw, dict):
                continue
            returned_protocol = str(raw.get("protocol") or protocol).casefold()
            if returned_protocol not in ALLOWED_PROTOCOLS:
                continue
            try:
                normalized = self.normalize_proxy(
                    f"{raw.get('ip', '')}:{raw.get('port', '')}",
                    returned_protocol,  # type: ignore[arg-type]
                )
            except ProxyConfigurationError:
                continue
            candidate = (normalized, "zdopen")
            if candidate not in candidates:
                candidates.append(candidate)
        if not candidates:
            raise ProxyUnavailableError("ZDOpen 未返回有效地址")
        return candidates

    async def _pool_candidates(
        self,
        protocol: ProxyProtocol,
        country_code: str,
        count: int,
        *,
        pool_provider: ProxyPoolProvider,
        zdopen_app_id: str,
        zdopen_akey: str,
    ) -> list[tuple[str, str]]:
        providers = (
            ["zdopen", "scdn"]
            if pool_provider == "smart" and zdopen_app_id and zdopen_akey
            else ["scdn"]
            if pool_provider == "smart"
            else [pool_provider]
        )
        candidates: list[tuple[str, str]] = []
        failures: list[str] = []
        for provider in providers:
            try:
                rows = (
                    await self._scdn_candidates(protocol, country_code, count)
                    if provider == "scdn"
                    else await self._zdopen_candidates(
                        protocol,
                        country_code,
                        count,
                        zdopen_app_id,
                        zdopen_akey,
                    )
                )
                for row in rows:
                    if row not in candidates:
                        candidates.append(row)
            except (ProxyConfigurationError, ProxyUnavailableError) as exc:
                failures.append(f"{provider}: {exc}")
                if pool_provider != "smart":
                    raise
        if not candidates:
            raise ProxyUnavailableError("；".join(failures) or "代理池未返回有效地址")
        return candidates

    async def _select_pool_proxy(
        self,
        protocol: ProxyProtocol,
        country_code: str,
        count: int,
        previous: str | None,
        *,
        pool_provider: ProxyPoolProvider,
        allow_tls_interception: bool,
        platform_scope: ProxyPlatformScope,
        zdopen_app_id: str,
        zdopen_akey: str,
    ) -> ProxyCheck:
        candidates = await self._pool_candidates(
            protocol,
            country_code,
            count,
            pool_provider=pool_provider,
            zdopen_app_id=zdopen_app_id,
            zdopen_akey=zdopen_akey,
        )
        now = monotonic()

        def cache_key(server: str) -> tuple[str, bool, str]:
            return server, allow_tls_interception, platform_scope

        ordered = [
            candidate
            for candidate in candidates
            if candidate[0] != previous
            and self._rejected_until.get(cache_key(candidate[0]), 0) <= now
        ]
        if not ordered:
            raise ProxyUnavailableError("代理池没有新的候选节点，近期失败地址仍在冷却")
        failures: list[ProxyCheck] = []
        tls_fallback: ProxyCheck | None = None
        for offset in range(0, len(ordered), 8):
            batch = ordered[offset : offset + 8]
            raw_results = await asyncio.gather(
                *(
                    self._check_proxy(
                        server,
                        allow_tls_interception=allow_tls_interception,
                        platform_scope=platform_scope,
                        provider=provider,
                    )
                    for server, provider in batch
                ),
                return_exceptions=True,
            )
            results = [
                result
                if isinstance(result, ProxyCheck)
                else ProxyCheck(
                    proxy=candidate[0],
                    reachable=False,
                    latency_ms=None,
                    exit_ip=None,
                    message=f"代理握手异常：{type(result).__name__}",
                    checked_at=self._now(),
                    targets={key: False for key in TARGET_URLS},
                    provider=candidate[1],
                )
                for candidate, result in zip(batch, raw_results, strict=True)
            ]
            for result in results:
                if not result.reachable:
                    self._rejected_until[cache_key(result.proxy)] = now + 600
            strict = [
                result
                for result in results
                if result.reachable and not result.tls_intercepted
            ]
            if strict:
                return min(strict, key=lambda item: item.latency_ms or 1_000_000)
            compatible = [
                result
                for result in results
                if result.reachable and result.tls_intercepted
            ]
            if compatible:
                batch_fallback = min(
                    compatible, key=lambda item: item.latency_ms or 1_000_000
                )
                if (
                    tls_fallback is None
                    or (batch_fallback.latency_ms or 1_000_000)
                    < (tls_fallback.latency_ms or 1_000_000)
                ):
                    tls_fallback = batch_fallback
            failures.extend(result for result in results if not result.reachable)
        if tls_fallback:
            return tls_fallback
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
        pool_provider: ProxyPoolProvider = "smart",
        platform_scope: ProxyPlatformScope = "taptap",
        allow_tls_interception: bool = False,
        auto_rotate_on_risk: bool = True,
        risk_rotation_limit: int = 2,
        zdopen_app_id: str = "",
        zdopen_akey: str = "",
    ) -> dict[str, object]:
        country = country_code.strip().upper()
        if country and (len(country) != 2 or not country.isalpha()):
            raise ProxyConfigurationError("国家代码应为两个字母，例如 CN")
        if not 1 <= pool_size <= 100:
            raise ProxyConfigurationError("代理池数量应在 1 到 100 之间")
        if not 0 <= risk_rotation_limit <= 5:
            raise ProxyConfigurationError("风控自动换线次数应在 0 到 5 之间")
        resolved_app_id = zdopen_app_id.strip() or self._state.zdopen_app_id
        resolved_akey = zdopen_akey.strip() or self._state.zdopen_akey
        if resolved_akey and not re.fullmatch(r"[0-9a-fA-F]{16,32}", resolved_akey):
            raise ProxyConfigurationError("ZDOpen akey 应为 16 或 32 位十六进制字符串")
        if pool_provider == "zdopen" and not (resolved_app_id and resolved_akey):
            raise ProxyConfigurationError("选择 ZDOpen 前请配置应用 ID 与 akey")

        result: ProxyCheck | None = None
        normalized_manual = ""
        if mode == "manual":
            normalized_manual = self.normalize_proxy(manual_proxy, protocol)
            result = await self._check_proxy(
                normalized_manual,
                allow_tls_interception=allow_tls_interception,
                platform_scope=platform_scope,
                provider="manual",
            )
            if not result.reachable:
                raise ProxyUnavailableError(result.message)
        elif mode == "auto":
            result = await self._select_pool_proxy(
                protocol,
                country,
                pool_size,
                None,
                pool_provider=pool_provider,
                allow_tls_interception=allow_tls_interception,
                platform_scope=platform_scope,
                zdopen_app_id=resolved_app_id,
                zdopen_akey=resolved_akey,
            )
        else:
            result = await self._check_direct()

        async with self._lock:
            self._state = ProxyRuntimeState(
                mode=mode,
                protocol=protocol,
                country_code=country,
                pool_size=pool_size,
                pool_provider=pool_provider,
                platform_scope=platform_scope,
                allow_tls_interception=allow_tls_interception,
                auto_rotate_on_risk=auto_rotate_on_risk,
                risk_rotation_limit=risk_rotation_limit,
                zdopen_app_id=resolved_app_id,
                zdopen_akey=resolved_akey,
                manual_proxy=normalized_manual,
                active_proxy=result.proxy if result and mode != "direct" else None,
                active_source=("manual" if mode == "manual" else "pool" if mode == "auto" else "direct"),
                exit_ip=result.exit_ip if result else None,
                latency_ms=result.latency_ms if result else None,
                last_checked_at=result.checked_at if result else None,
                last_error=None if result and result.reachable else result.message if result else None,
                target_results=result.targets if result else {},
                active_provider=result.provider if result else None,
                tls_intercepted=result.tls_intercepted if result else False,
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
            provider = self._state.pool_provider
            allow_tls = self._state.allow_tls_interception
            scope = self._state.platform_scope
            app_id = self._state.zdopen_app_id
            akey = self._state.zdopen_akey
        result = await self._select_pool_proxy(
            protocol,
            country,
            count,
            previous,
            pool_provider=provider,
            allow_tls_interception=allow_tls,
            platform_scope=scope,
            zdopen_app_id=app_id,
            zdopen_akey=akey,
        )
        async with self._lock:
            self._state.active_proxy = result.proxy
            self._state.active_source = "pool"
            self._state.exit_ip = result.exit_ip
            self._state.latency_ms = result.latency_ms
            self._state.last_checked_at = result.checked_at
            self._state.last_error = None
            self._state.target_results = result.targets
            self._state.active_provider = result.provider
            self._state.tls_intercepted = result.tls_intercepted
            self._save()
            return self.state()

    async def ensure_active(self, platform: Literal["bilibili", "taptap"] = "taptap") -> str | None:
        async with self._lock:
            mode = self._state.mode
            active = self._state.active_proxy
            protocol = self._state.protocol
            country = self._state.country_code
            count = self._state.pool_size
            provider = self._state.pool_provider
            scope = self._state.platform_scope
            allow_tls = self._state.allow_tls_interception
            app_id = self._state.zdopen_app_id
            akey = self._state.zdopen_akey
        if mode == "direct" or (scope == "taptap" and platform == "bilibili"):
            return None
        if active:
            return active
        if mode == "manual":
            raise ProxyConfigurationError("手动代理模式缺少有效地址")
        result = await self._select_pool_proxy(
            protocol,
            country,
            count,
            None,
            pool_provider=provider,
            allow_tls_interception=allow_tls,
            platform_scope=scope,
            zdopen_app_id=app_id,
            zdopen_akey=akey,
        )
        async with self._lock:
            self._state.active_proxy = result.proxy
            self._state.active_source = "pool"
            self._state.exit_ip = result.exit_ip
            self._state.latency_ms = result.latency_ms
            self._state.last_checked_at = result.checked_at
            self._state.last_error = None
            self._state.target_results = result.targets
            self._state.active_provider = result.provider
            self._state.tls_intercepted = result.tls_intercepted
            self._save()
        return result.proxy

    def ignore_https_errors(self, platform: Literal["bilibili", "taptap"]) -> bool:
        applies = self._state.platform_scope == "all" or platform == "taptap"
        return bool(
            applies
            and self._state.mode != "direct"
            and self._state.allow_tls_interception
            and self._state.tls_intercepted
        )

    def risk_rotation_policy(self) -> tuple[bool, int]:
        return self._state.auto_rotate_on_risk, self._state.risk_rotation_limit
