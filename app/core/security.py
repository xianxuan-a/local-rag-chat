"""Identity normalization, bcrypt boundaries, and JWT primitives."""

from __future__ import annotations

import secrets
import socket
import unicodedata
from collections import OrderedDict, deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import timedelta
from hashlib import blake2b
from ipaddress import IPv4Address, IPv6Address, ip_address, ip_network
from math import ceil
from threading import RLock
from time import monotonic
from typing import Any
from uuid import uuid4

import bcrypt
import jwt

from app.core.config import Settings
from app.core.exceptions import ConfigurationException, ValidationException
from app.models import utc_now


@dataclass(frozen=True)
class RateLimitRule:
    """One bounded authentication rate-limit dimension."""

    dimension: str
    limit: int
    window_seconds: float
    backoff_base_seconds: float = 0.0
    backoff_max_seconds: float = 0.0


@dataclass(frozen=True)
class RateLimitDecision:
    """Safe rate-limit result containing no raw identity or address."""

    dimension: str
    key_digest: str
    retry_after: int


@dataclass
class _RateBucket:
    attempts: deque[float] = field(default_factory=deque)
    blocked_until: float = 0.0
    last_seen: float = 0.0


class AuthRateLimiter:
    """Thread-safe, process-local limiter for the supported single worker."""

    def __init__(
        self,
        *,
        max_keys: int,
        ttl_seconds: float,
        trusted_proxy_cidrs: Sequence[str] = (),
        trusted_proxy_hosts: Sequence[str] = (),
        clock: Callable[[], float] = monotonic,
        fingerprint_key: bytes | None = None,
        resolver: Callable[[str], Sequence[str]] | None = None,
    ) -> None:
        self.max_keys = max_keys
        self.ttl_seconds = ttl_seconds
        self._clock = clock
        self._fingerprint_key = fingerprint_key or secrets.token_bytes(32)
        self._trusted_proxy_networks = tuple(
            ip_network(value, strict=False) for value in trusted_proxy_cidrs
        )
        self._trusted_proxy_hosts = tuple(trusted_proxy_hosts)
        self._resolver = resolver or self._resolve_host
        self._proxy_host_cache: dict[
            str, tuple[float, tuple[IPv4Address | IPv6Address, ...]]
        ] = {}
        self._buckets: OrderedDict[tuple[str, str], _RateBucket] = (
            OrderedDict()
        )
        self._lock = RLock()
        self._operations = 0

    @classmethod
    def from_settings(cls, settings: Settings) -> "AuthRateLimiter":
        return cls(
            max_keys=settings.AUTH_RATE_LIMIT_MAX_KEYS,
            ttl_seconds=settings.AUTH_RATE_LIMIT_TTL_SECONDS,
            trusted_proxy_cidrs=settings.TRUSTED_PROXY_CIDRS,
            trusted_proxy_hosts=settings.TRUSTED_PROXY_HOSTS,
        )

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._buckets)

    def client_ip(self, request: Any) -> str:
        """Resolve the client through a configured, right-to-left proxy chain."""

        client = getattr(request, "client", None)
        direct = str(getattr(client, "host", "unknown") or "unknown")
        try:
            direct_address = ip_address(direct)
        except ValueError:
            return direct
        direct = str(direct_address)
        if not self._is_trusted_proxy(direct_address):
            return direct

        x_forwarded_for = request.headers.get("X-Forwarded-For")
        forwarded = request.headers.get("Forwarded")
        if x_forwarded_for:
            selected = self._select_x_forwarded_for(x_forwarded_for)
        elif forwarded:
            selected = self._select_forwarded(forwarded)
        else:
            return direct
        return str(selected) if selected is not None else direct

    def check_failures(
        self,
        keys: Sequence[tuple[RateLimitRule, str]],
    ) -> RateLimitDecision | None:
        now = self._clock()
        with self._lock:
            self._maintain(now)
            decisions: list[RateLimitDecision] = []
            for rule, raw_key in keys:
                bucket_id = self._bucket_id(rule.dimension, raw_key)
                bucket = self._buckets.get(bucket_id)
                if bucket is None:
                    continue
                self._prune(bucket, rule, now)
                bucket.last_seen = now
                self._buckets.move_to_end(bucket_id)
                if bucket.blocked_until > now:
                    decisions.append(
                        self._decision(rule, bucket_id, bucket.blocked_until - now)
                    )
            return self._longest(decisions)

    def record_failures(
        self,
        keys: Sequence[tuple[RateLimitRule, str]],
    ) -> RateLimitDecision | None:
        now = self._clock()
        with self._lock:
            self._maintain(now)
            decisions: list[RateLimitDecision] = []
            for rule, raw_key in keys:
                bucket_id, bucket = self._get_or_create(rule, raw_key, now)
                self._prune(bucket, rule, now)
                bucket.attempts.append(now)
                bucket.last_seen = now
                failure_count = len(bucket.attempts)
                if failure_count >= rule.limit:
                    exponent = min(failure_count - rule.limit, 30)
                    cooldown = min(
                        rule.backoff_base_seconds * (2**exponent),
                        rule.backoff_max_seconds,
                    )
                    bucket.blocked_until = max(
                        bucket.blocked_until, now + cooldown
                    )
                    decisions.append(
                        self._decision(rule, bucket_id, cooldown)
                    )
            return self._longest(decisions)

    def consume_attempts(
        self,
        keys: Sequence[tuple[RateLimitRule, str]],
    ) -> RateLimitDecision | None:
        """Atomically consume registration/bootstrap request quotas."""

        now = self._clock()
        with self._lock:
            self._maintain(now)
            prepared: list[
                tuple[RateLimitRule, str, _RateBucket | None]
            ] = []
            decisions: list[RateLimitDecision] = []
            for rule, raw_key in keys:
                bucket_id = self._bucket_id(rule.dimension, raw_key)
                bucket = self._buckets.get(bucket_id)
                if bucket is not None:
                    self._prune(bucket, rule, now)
                    bucket.last_seen = now
                    self._buckets.move_to_end(bucket_id)
                    if len(bucket.attempts) >= rule.limit:
                        retry = bucket.attempts[0] + rule.window_seconds - now
                        decisions.append(
                            self._decision(rule, bucket_id, retry)
                        )
                prepared.append((rule, raw_key, bucket))
            limited = self._longest(decisions)
            if limited is not None:
                return limited
            for rule, raw_key, bucket in prepared:
                if bucket is None:
                    _created_id, bucket = self._get_or_create(
                        rule, raw_key, now
                    )
                bucket.attempts.append(now)
                bucket.last_seen = now
            return None

    def reset(self, keys: Sequence[tuple[RateLimitRule, str]]) -> None:
        with self._lock:
            for rule, raw_key in keys:
                self._buckets.pop(
                    self._bucket_id(rule.dimension, raw_key), None
                )

    def cleanup(self) -> int:
        with self._lock:
            return self._cleanup(self._clock())

    def _get_or_create(
        self,
        rule: RateLimitRule,
        raw_key: str,
        now: float,
    ) -> tuple[tuple[str, str], _RateBucket]:
        bucket_id = self._bucket_id(rule.dimension, raw_key)
        bucket = self._buckets.get(bucket_id)
        if bucket is None:
            while len(self._buckets) >= self.max_keys:
                self._buckets.popitem(last=False)
            bucket = _RateBucket(last_seen=now)
            self._buckets[bucket_id] = bucket
        else:
            self._buckets.move_to_end(bucket_id)
        return bucket_id, bucket

    def _bucket_id(self, dimension: str, raw_key: str) -> tuple[str, str]:
        digest = blake2b(
            f"{dimension}\0{raw_key}".encode("utf-8"),
            key=self._fingerprint_key,
            digest_size=12,
        ).hexdigest()
        return dimension, digest

    def _maintain(self, now: float) -> None:
        self._operations += 1
        if self._operations % 64 == 0 or len(self._buckets) >= self.max_keys:
            self._cleanup(now)

    def _cleanup(self, now: float) -> int:
        expired = [
            bucket_id
            for bucket_id, bucket in self._buckets.items()
            if now - bucket.last_seen >= self.ttl_seconds
            and bucket.blocked_until <= now
        ]
        for bucket_id in expired:
            self._buckets.pop(bucket_id, None)
        return len(expired)

    @staticmethod
    def _prune(bucket: _RateBucket, rule: RateLimitRule, now: float) -> None:
        threshold = now - rule.window_seconds
        while bucket.attempts and bucket.attempts[0] <= threshold:
            bucket.attempts.popleft()
        if not bucket.attempts and bucket.blocked_until <= now:
            bucket.blocked_until = 0.0

    @staticmethod
    def _decision(
        rule: RateLimitRule,
        bucket_id: tuple[str, str],
        retry: float,
    ) -> RateLimitDecision:
        return RateLimitDecision(
            dimension=rule.dimension,
            key_digest=bucket_id[1],
            retry_after=max(1, ceil(retry)),
        )

    @staticmethod
    def _longest(
        decisions: Sequence[RateLimitDecision],
    ) -> RateLimitDecision | None:
        return max(decisions, key=lambda item: item.retry_after, default=None)

    def _is_trusted_proxy(
        self, address: IPv4Address | IPv6Address
    ) -> bool:
        if any(address in network for network in self._trusted_proxy_networks):
            return True
        now = self._clock()
        with self._lock:
            for hostname in self._trusted_proxy_hosts:
                cached = self._proxy_host_cache.get(hostname)
                if cached is None or cached[0] <= now:
                    try:
                        resolved = tuple(
                            ip_address(value) for value in self._resolver(hostname)
                        )
                    except (OSError, ValueError):
                        resolved = ()
                    cached = (now + 30.0, resolved)
                    self._proxy_host_cache[hostname] = cached
                if address in cached[1]:
                    return True
        return False

    @staticmethod
    def _resolve_host(hostname: str) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    result[4][0]
                    for result in socket.getaddrinfo(
                        hostname, None, type=socket.SOCK_STREAM
                    )
                }
            )
        )

    def _select_x_forwarded_for(
        self, value: str
    ) -> IPv4Address | IPv6Address | None:
        return self._select_forwarded_values(value.split(","), len(value))

    def _select_forwarded(
        self, value: str
    ) -> IPv4Address | IPv6Address | None:
        if len(value) > 2048:
            return None
        raw_addresses: list[str] = []
        for element in value.split(","):
            parameters = {
                key.strip().casefold(): item.strip()
                for parameter in element.split(";")
                if "=" in parameter
                for key, item in (parameter.split("=", 1),)
            }
            if "for" not in parameters:
                return None
            raw_addresses.append(parameters["for"])
        return self._select_forwarded_values(raw_addresses, len(value))

    def _select_forwarded_values(
        self,
        raw_addresses: Sequence[str],
        header_length: int,
    ) -> IPv4Address | IPv6Address | None:
        if header_length > 2048 or not 1 <= len(raw_addresses) <= 20:
            return None
        leftmost: IPv4Address | IPv6Address | None = None
        for raw_value in reversed(raw_addresses):
            try:
                address = self._parse_forwarded_address(raw_value)
            except ValueError:
                return None
            leftmost = address
            if not self._is_trusted_proxy(address):
                return address
        return leftmost

    @staticmethod
    def _parse_forwarded_address(value: str) -> IPv4Address | IPv6Address:
        candidate = value.strip().strip('"')
        if (
            not candidate
            or candidate.casefold() == "unknown"
            or candidate.startswith("_")
        ):
            raise ValueError("forwarded address is not an IP literal")
        if candidate.startswith("["):
            closing = candidate.find("]")
            if closing < 0:
                raise ValueError("invalid bracketed forwarded address")
            address_text = candidate[1:closing]
            suffix = candidate[closing + 1 :]
            if suffix and not (suffix.startswith(":") and suffix[1:].isdigit()):
                raise ValueError("invalid forwarded port")
        elif candidate.count(":") == 1:
            address_text, possible_port = candidate.rsplit(":", 1)
            if not possible_port.isdigit():
                address_text = candidate
        else:
            address_text = candidate
        return ip_address(address_text)


def normalize_identity(value: str) -> str:
    return unicodedata.normalize("NFKC", value.strip()).casefold()


def validate_password_bytes(password: str) -> bytes:
    encoded = password.encode("utf-8")
    if len(password) < 8:
        raise ValidationException("密码必须至少包含 8 个字符")
    if len(encoded) > 72:
        raise ValidationException("密码不能超过 bcrypt 的 72 个 UTF-8 字节限制")
    return encoded


def hash_password(password: str) -> str:
    return bcrypt.hashpw(validate_password_bytes(password), bcrypt.gensalt()).decode(
        "ascii"
    )


def verify_password(password: str, password_hash: str) -> bool:
    try:
        encoded = validate_password_bytes(password)
        return bcrypt.checkpw(encoded, password_hash.encode("ascii"))
    except (ValueError, TypeError, ValidationException):
        return False


def create_access_token(user_id: str, settings: Settings) -> tuple[str, str]:
    secret = settings.JWT_SECRET.get_secret_value()
    if not secret:
        raise ConfigurationException(
            "JWT_SECRET 未配置；请显式运行 scripts/init_secrets.py"
        )
    now = utc_now()
    jti = str(uuid4())
    token = jwt.encode(
        {
            "sub": str(user_id),
            "jti": jti,
            "iat": now,
            "exp": now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        },
        secret,
        algorithm=settings.JWT_ALGORITHM,
    )
    return token, jti


def decode_access_token(token: str, settings: Settings) -> dict[str, object]:
    secret = settings.JWT_SECRET.get_secret_value()
    if not secret:
        raise ConfigurationException("JWT_SECRET 未配置")
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=[settings.JWT_ALGORITHM],
            options={"require": ["sub", "jti", "iat", "exp"]},
        )
    except jwt.PyJWTError as exc:
        raise ValidationException("访问令牌无效或已过期", status_code=401) from exc
    return payload


def secrets_equal(provided: str, expected: str) -> bool:
    return bool(expected) and secrets.compare_digest(
        provided.encode("utf-8"), expected.encode("utf-8")
    )
