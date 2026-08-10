"""Provider-neutral web search, safe fetching, and evidence preparation."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
from html.parser import HTMLParser
import html
import http.client
import ipaddress
import re
import socket
import ssl
import threading
import time
from typing import Protocol
import unicodedata
from urllib.parse import (
    parse_qsl,
    urlencode,
    urljoin,
    urlsplit,
    urlunsplit,
)

import httpx

from app.core.config import Settings
from app.core.logger import get_logger
from app.core.retrieval_modes import WebSearchStatus
from app.services.untrusted_content_service import UntrustedContentSanitizer
from app.utils.text_utils import clean_text, truncate_text


logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class WebSearchHit:
    title: str
    url: str
    snippet: str = ""
    published_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class WebPageEvidence:
    title: str
    url: str
    domain: str
    content: str
    content_preview: str
    quality_score: float
    published_at: datetime | None
    accessed_at: datetime
    metadata: dict[str, str | int | float | bool | None] = field(
        default_factory=dict
    )


@dataclass(frozen=True, slots=True)
class SanitizedSearchQuery:
    query: str
    digest: str
    redaction_count: int


@dataclass(frozen=True, slots=True)
class WebSearchOutcome:
    status: WebSearchStatus
    evidence: tuple[WebPageEvidence, ...] = ()
    search_triggered: bool = False
    fallback_reason: str | None = None
    query_digest: str | None = None
    search_duration_ms: float = 0.0
    fetch_duration_ms: float = 0.0
    provider_status: str | None = None
    excluded_reasons: tuple[str, ...] = ()


class WebSearchProviderError(RuntimeError):
    def __init__(
        self,
        status: WebSearchStatus,
        message: str,
        *,
        provider_status: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.provider_status = provider_status


class WebSearchProvider(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def configured(self) -> bool: ...

    def search(
        self,
        query: str,
        *,
        limit: int,
        timeout_seconds: float,
    ) -> Sequence[WebSearchHit]: ...


class UnconfiguredWebSearchProvider:
    """Explicit unavailable provider; never returns a fake empty result."""

    def __init__(self, name: str = "disabled") -> None:
        self._name = name or "disabled"

    @property
    def name(self) -> str:
        return self._name

    @property
    def configured(self) -> bool:
        return False

    def search(
        self,
        query: str,
        *,
        limit: int,
        timeout_seconds: float,
    ) -> Sequence[WebSearchHit]:
        _ = query, limit, timeout_seconds
        raise WebSearchProviderError(
            WebSearchStatus.NOT_CONFIGURED,
            "联网搜索 Provider 尚未配置",
            provider_status="not_configured",
        )


class SearchQuerySanitizer:
    """Build a bounded query solely from the current user question."""

    _PATTERNS = (
        (
            re.compile(
                r"(?<![\w.+-])[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}",
                re.IGNORECASE,
            ),
            "[REDACTED_EMAIL]",
        ),
        (
            re.compile(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)"),
            "[REDACTED_PHONE]",
        ),
        (
            re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)"),
            "[REDACTED_ID]",
        ),
        (
            re.compile(r"(?<!\d)(?:\d[ -]?){15,19}(?!\d)"),
            "[REDACTED_CARD]",
        ),
        (
            re.compile(
                r"(?i)\b(?:api[_-]?key|secret|token|password|passwd)"
                r"\s*[:=]\s*[^\s,;]{6,}"
            ),
            "[REDACTED_SECRET]",
        ),
        (
            re.compile(
                r"(?i)\b(?:sk|ak|pk)[-_][A-Za-z0-9_-]{12,}\b"
            ),
            "[REDACTED_SECRET]",
        ),
        (
            re.compile(
                r"(?i)\b(?:客户|customer|账号|account)[-_ :：#]*"
                r"[A-Za-z0-9_-]{5,}\b"
            ),
            "[REDACTED_ACCOUNT]",
        ),
    )

    def __init__(self, max_chars: int) -> None:
        self.max_chars = max_chars

    def sanitize(self, question: str) -> SanitizedSearchQuery:
        query = unicodedata.normalize("NFKC", question)
        query = clean_text(query)
        redactions = 0
        for pattern, replacement in self._PATTERNS:
            query, count = pattern.subn(replacement, query)
            redactions += count
        query = clean_text(query[: self.max_chars])
        meaningful = re.sub(
            r"\[REDACTED_[A-Z_]+\]|[\W_]+",
            "",
            query,
            flags=re.UNICODE,
        )
        if len(meaningful) < 2:
            raise WebSearchProviderError(
                WebSearchStatus.QUERY_REJECTED,
                "联网查询脱敏后为空或失去搜索意义",
                provider_status="query_rejected",
            )
        return SanitizedSearchQuery(
            query=query,
            digest=sha256(query.encode("utf-8")).hexdigest(),
            redaction_count=redactions,
        )


def normalize_public_url(value: str) -> tuple[str, str]:
    parsed = urlsplit(value.strip())
    if (
        parsed.scheme.casefold() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("网页 URL 必须是不含凭据的 HTTP/HTTPS 地址")
    try:
        host = parsed.hostname.encode("idna").decode("ascii").casefold()
    except UnicodeError as exc:
        raise ValueError("网页 URL 域名无效") from exc
    port = parsed.port
    host_literal = f"[{host}]" if ":" in host else host
    netloc = host_literal
    if port is not None and not (
        (parsed.scheme.casefold() == "http" and port == 80)
        or (parsed.scheme.casefold() == "https" and port == 443)
    ):
        netloc = f"{host_literal}:{port}"
    filtered_query = urlencode(
        [
            (key, item)
            for key, item in parse_qsl(
                parsed.query,
                keep_blank_values=True,
            )
            if key.casefold()
            not in {"gclid", "fbclid"}
            and not key.casefold().startswith("utm_")
        ],
        doseq=True,
    )
    normalized = urlunsplit(
        (
            parsed.scheme.casefold(),
            netloc,
            parsed.path or "/",
            filtered_query,
            "",
        )
    )
    return normalized, host


class DomainPolicy:
    def __init__(
        self,
        allowed_domains: Sequence[str],
        blocked_domains: Sequence[str],
    ) -> None:
        self.allowed = tuple(allowed_domains)
        self.blocked = tuple(blocked_domains)

    @staticmethod
    def _matches(host: str, configured: str) -> bool:
        return host == configured or host.endswith(f".{configured}")

    def allowed_url(self, url: str) -> tuple[str, str]:
        normalized, host = normalize_public_url(url)
        if any(self._matches(host, item) for item in self.blocked):
            raise ValueError("domain_blocked")
        if self.allowed and not any(
            self._matches(host, item) for item in self.allowed
        ):
            raise ValueError("domain_not_allowed")
        return normalized, host


class _ReadableHtmlParser(HTMLParser):
    _SKIP = {"script", "style", "noscript", "svg", "form", "iframe"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip_depth = 0
        self.text: list[str] = []
        self.title_parts: list[str] = []
        self.in_title = False
        self.published_at: str | None = None

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        folded = tag.casefold()
        if folded in self._SKIP:
            self.skip_depth += 1
        if folded == "title":
            self.in_title = True
        if folded == "meta":
            values = {
                str(key).casefold(): str(value or "")
                for key, value in attrs
            }
            marker = (
                values.get("property")
                or values.get("name")
                or values.get("itemprop")
                or ""
            ).casefold()
            if marker in {
                "article:published_time",
                "datepublished",
                "date",
                "publishdate",
                "pubdate",
            }:
                self.published_at = values.get("content") or None
        if folded == "time":
            values = {
                str(key).casefold(): str(value or "")
                for key, value in attrs
            }
            self.published_at = (
                values.get("datetime") or self.published_at
            )

    def handle_endtag(self, tag: str) -> None:
        folded = tag.casefold()
        if folded in self._SKIP and self.skip_depth:
            self.skip_depth -= 1
        if folded == "title":
            self.in_title = False
        if folded in {"p", "div", "article", "main", "li", "h1", "h2", "h3"}:
            self.text.append("\n")

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        if self.in_title:
            self.title_parts.append(data)
        self.text.append(data)


@dataclass(frozen=True, slots=True)
class FetchedWebPage:
    url: str
    domain: str
    title: str
    content: str
    published_at: datetime | None
    accessed_at: datetime


@dataclass(frozen=True, slots=True)
class PinnedWebRequest:
    """An HTTP request whose connect address has already passed SSRF policy."""

    scheme: str
    hostname: str
    port: int
    connect_ip: str
    target: str
    host_header: str
    timeout_seconds: float
    max_response_bytes: int


@dataclass(frozen=True, slots=True)
class PinnedWebResponse:
    status_code: int
    headers: dict[str, str]
    body: bytes


class WebFetchTransport(Protocol):
    def send(self, request: PinnedWebRequest) -> PinnedWebResponse: ...


class _PinnedHTTPConnection(http.client.HTTPConnection):
    """Connect to a validated address without resolving the hostname again."""

    def __init__(self, request: PinnedWebRequest) -> None:
        super().__init__(
            host=request.hostname,
            port=request.port,
            timeout=request.timeout_seconds,
        )
        self._connect_ip = request.connect_ip

    def connect(self) -> None:
        self.sock = socket.create_connection(
            (self._connect_ip, self.port),
            self.timeout,
            self.source_address,
        )


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Pin TCP to the validated IP while retaining hostname SNI verification."""

    def __init__(self, request: PinnedWebRequest) -> None:
        super().__init__(
            host=request.hostname,
            port=request.port,
            timeout=request.timeout_seconds,
            context=ssl.create_default_context(),
        )
        self._connect_ip = request.connect_ip

    def connect(self) -> None:
        raw_socket = socket.create_connection(
            (self._connect_ip, self.port),
            self.timeout,
            self.source_address,
        )
        try:
            self.sock = self._context.wrap_socket(
                raw_socket,
                server_hostname=self.host,
            )
        except Exception:
            raw_socket.close()
            raise


class PinnedSocketTransport:
    """Minimal bounded HTTP transport used by the safe web fetcher."""

    _REDIRECT_STATUSES = {301, 302, 303, 307, 308}

    def send(self, request: PinnedWebRequest) -> PinnedWebResponse:
        connection: http.client.HTTPConnection
        if request.scheme == "https":
            connection = _PinnedHTTPSConnection(request)
        else:
            connection = _PinnedHTTPConnection(request)
        try:
            connection.request(
                "GET",
                request.target,
                headers={
                    "Host": request.host_header,
                    "User-Agent": "Local-RAG-Chat/0.1 safe-web-fetcher",
                    "Accept": "text/html,text/plain;q=0.9",
                    "Accept-Encoding": "identity",
                    "Connection": "close",
                },
            )
            response = connection.getresponse()
            headers = {
                key.casefold(): value
                for key, value in response.getheaders()
            }
            if response.status in self._REDIRECT_STATUSES:
                payload = b""
            else:
                declared_length = headers.get("content-length")
                if declared_length is not None:
                    try:
                        if int(declared_length) > request.max_response_bytes:
                            raise ValueError("response_too_large")
                    except ValueError as exc:
                        if str(exc) == "response_too_large":
                            raise
                        raise ValueError("invalid_content_length") from exc
                payload_buffer = bytearray()
                while True:
                    chunk = response.read(64 * 1024)
                    if not chunk:
                        break
                    payload_buffer.extend(chunk)
                    if len(payload_buffer) > request.max_response_bytes:
                        raise ValueError("response_too_large")
                payload = bytes(payload_buffer)
            return PinnedWebResponse(
                status_code=response.status,
                headers=headers,
                body=payload,
            )
        except (TimeoutError, socket.timeout) as exc:
            raise httpx.TimeoutException("web fetch timed out") from exc
        finally:
            connection.close()


class WebPageFetcher:
    """Fetch bounded public pages while revalidating every redirect."""

    def __init__(
        self,
        settings: Settings,
        *,
        resolver: Callable[..., Sequence[tuple]] = socket.getaddrinfo,
        transport: WebFetchTransport | None = None,
    ) -> None:
        self.settings = settings
        self.domain_policy = DomainPolicy(
            settings.WEB_SEARCH_ALLOWED_DOMAINS,
            settings.WEB_SEARCH_BLOCKED_DOMAINS,
        )
        self.resolver = resolver
        self.transport = transport or PinnedSocketTransport()

    def fetch(self, url: str) -> FetchedWebPage:
        current, domain = self.domain_policy.allowed_url(url)
        redirects = 0
        while True:
            address = self._resolve_public_address(domain)
            request = self._build_pinned_request(current, address)
            response = self.transport.send(request)
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("location")
                if (
                    not location
                    or redirects >= self.settings.WEB_FETCH_MAX_REDIRECTS
                ):
                    raise ValueError("redirect_rejected")
                current, domain = self.domain_policy.allowed_url(
                    urljoin(current, location)
                )
                redirects += 1
                continue
            if response.status_code >= 400:
                http_response = httpx.Response(
                    response.status_code,
                    request=httpx.Request("GET", current),
                )
                http_response.raise_for_status()
            content_encoding = response.headers.get(
                "content-encoding", "identity"
            ).strip().casefold()
            if content_encoding not in {"", "identity"}:
                raise ValueError("content_encoding_rejected")
            raw_content_type = response.headers.get("content-type", "")
            content_type = raw_content_type.split(";", 1)[0].strip().casefold()
            if content_type not in {
                "text/html",
                "application/xhtml+xml",
                "text/plain",
            }:
                raise ValueError("content_type_rejected")
            charset_match = re.search(
                r"(?:^|;)\s*charset\s*=\s*[\"']?([^;\"'\s]+)",
                raw_content_type,
                re.IGNORECASE,
            )
            encoding = charset_match.group(1) if charset_match else "utf-8"
            try:
                decoded = response.body.decode(encoding, errors="replace")
            except LookupError as exc:
                raise ValueError("encoding_rejected") from exc
            break
        accessed_at = datetime.now(UTC)
        if content_type == "text/plain":
            title = domain
            content = clean_text(decoded)
            published_at = None
        else:
            parser = _ReadableHtmlParser()
            parser.feed(decoded)
            parser.close()
            title = clean_text(" ".join(parser.title_parts)) or domain
            content = clean_text(html.unescape(" ".join(parser.text)))
            published_at = _parse_publication_date(parser.published_at)
        return FetchedWebPage(
            url=current,
            domain=domain,
            title=truncate_text(title, 500),
            content=content,
            published_at=published_at,
            accessed_at=accessed_at,
        )

    def _build_pinned_request(
        self,
        url: str,
        address: ipaddress.IPv4Address | ipaddress.IPv6Address,
    ) -> PinnedWebRequest:
        parsed = urlsplit(url)
        hostname = parsed.hostname
        if hostname is None:
            raise ValueError("invalid_host")
        scheme = parsed.scheme.casefold()
        port = parsed.port or (443 if scheme == "https" else 80)
        target = parsed.path or "/"
        if parsed.query:
            target = f"{target}?{parsed.query}"
        host_literal = f"[{hostname}]" if ":" in hostname else hostname
        default_port = (scheme == "https" and port == 443) or (
            scheme == "http" and port == 80
        )
        host_header = host_literal if default_port else f"{host_literal}:{port}"
        return PinnedWebRequest(
            scheme=scheme,
            hostname=hostname,
            port=port,
            connect_ip=str(address),
            target=target,
            host_header=host_header,
            timeout_seconds=self.settings.WEB_FETCH_TIMEOUT_SECONDS,
            max_response_bytes=self.settings.WEB_FETCH_MAX_RESPONSE_BYTES,
        )

    def _resolve_public_address(
        self, host: str
    ) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
        try:
            direct = ipaddress.ip_address(host)
        except ValueError:
            direct = None
        if direct is not None:
            addresses = (direct,)
        else:
            try:
                records = self.resolver(
                    host,
                    None,
                    type=socket.SOCK_STREAM,
                )
            except OSError as exc:
                raise ValueError("dns_resolution_failed") from exc
            addresses = tuple(
                ipaddress.ip_address(record[4][0])
                for record in records
            )
        if not addresses or any(not address.is_global for address in addresses):
            raise ValueError("non_public_address")
        return addresses[0]

    def _validate_public_host(self, host: str) -> None:
        """Compatibility shim for callers that only need policy validation."""

        self._resolve_public_address(host)


def _parse_publication_date(value: str | None) -> datetime | None:
    if not value:
        return None
    candidate = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


class WebSearchService:
    """Execute provider search and turn fetched pages into safe evidence."""

    _HIGH_RISK = re.compile(
        r"(医疗|诊断|用药|法律|诉讼|法规|金融|投资|证券|贷款|"
        r"\bmedical\b|\blegal\b|\bfinancial\b|\binvestment\b)",
        re.IGNORECASE,
    )
    _LOW_QUALITY_PATH = re.compile(
        r"/(?:search|tag|category|ads?|login|signup)(?:/|$)",
        re.IGNORECASE,
    )

    def __init__(
        self,
        provider: WebSearchProvider,
        fetcher: WebPageFetcher,
        settings: Settings,
        *,
        content_sanitizer: UntrustedContentSanitizer | None = None,
    ) -> None:
        self.provider = provider
        self.fetcher = fetcher
        self.settings = settings
        self.query_sanitizer = SearchQuerySanitizer(
            settings.WEB_SEARCH_QUERY_MAX_CHARS
        )
        self.content_sanitizer = (
            content_sanitizer or UntrustedContentSanitizer()
        )
        self._cache_lock = threading.Lock()
        self._search_cache: dict[
            str, tuple[float, tuple[WebSearchHit, ...]]
        ] = {}

    def search(
        self,
        question: str,
        *,
        cancel_check: Callable[[], bool] | None = None,
    ) -> WebSearchOutcome:
        cancel_check = cancel_check or (lambda: False)
        try:
            sanitized = self.query_sanitizer.sanitize(question)
        except WebSearchProviderError as exc:
            return WebSearchOutcome(
                status=exc.status,
                fallback_reason="web_query_rejected",
                provider_status=exc.provider_status,
            )
        if cancel_check():
            return WebSearchOutcome(
                status=WebSearchStatus.FAILED,
                fallback_reason="client_cancelled",
                query_digest=sanitized.digest,
                provider_status="cancelled",
            )
        if not self.provider.configured:
            return WebSearchOutcome(
                status=WebSearchStatus.NOT_CONFIGURED,
                fallback_reason="web_provider_not_configured",
                query_digest=sanitized.digest,
                provider_status="not_configured",
            )
        started = time.perf_counter()
        try:
            hits = self._cached_search(sanitized)
        except WebSearchProviderError as exc:
            return WebSearchOutcome(
                status=exc.status,
                search_triggered=True,
                fallback_reason=f"web_{exc.status.value}",
                query_digest=sanitized.digest,
                search_duration_ms=(
                    time.perf_counter() - started
                )
                * 1000,
                provider_status=exc.provider_status,
            )
        except TimeoutError:
            return WebSearchOutcome(
                status=WebSearchStatus.TIMEOUT,
                search_triggered=True,
                fallback_reason="web_timeout",
                query_digest=sanitized.digest,
                search_duration_ms=(
                    time.perf_counter() - started
                )
                * 1000,
                provider_status="timeout",
            )
        except Exception:
            logger.warning(
                "联网搜索失败 query_digest=%s provider=%s",
                sanitized.digest,
                self.provider.name,
                exc_info=True,
            )
            return WebSearchOutcome(
                status=WebSearchStatus.FAILED,
                search_triggered=True,
                fallback_reason="web_search_failed",
                query_digest=sanitized.digest,
                search_duration_ms=(
                    time.perf_counter() - started
                )
                * 1000,
                provider_status="failed",
            )
        search_duration = (time.perf_counter() - started) * 1000
        if not hits:
            return WebSearchOutcome(
                status=WebSearchStatus.SUCCESS,
                search_triggered=True,
                fallback_reason="web_no_results",
                query_digest=sanitized.digest,
                search_duration_ms=search_duration,
                provider_status="success",
            )
        fetch_started = time.perf_counter()
        evidence, exclusions = self._fetch_hits(
            hits,
            question=question,
            cancel_check=cancel_check,
        )
        fetch_duration = (time.perf_counter() - fetch_started) * 1000
        if evidence:
            status = (
                WebSearchStatus.PARTIAL
                if exclusions
                else WebSearchStatus.SUCCESS
            )
            fallback = "web_partial_fetch" if exclusions else None
        else:
            status = (
                WebSearchStatus.TIMEOUT
                if exclusions
                and all(reason == "fetch_timeout" for reason in exclusions)
                else WebSearchStatus.FAILED
            )
            fallback = "web_no_usable_sources"
        logger.info(
            "web_search query_digest=%s provider=%s status=%s "
            "results=%s usable=%s search_ms=%.3f fetch_ms=%.3f",
            sanitized.digest,
            self.provider.name,
            status.value,
            len(hits),
            len(evidence),
            search_duration,
            fetch_duration,
        )
        return WebSearchOutcome(
            status=status,
            evidence=tuple(evidence),
            search_triggered=True,
            fallback_reason=fallback,
            query_digest=sanitized.digest,
            search_duration_ms=search_duration,
            fetch_duration_ms=fetch_duration,
            provider_status="success",
            excluded_reasons=tuple(exclusions),
        )

    def _cached_search(
        self,
        sanitized: SanitizedSearchQuery,
    ) -> tuple[WebSearchHit, ...]:
        now = time.monotonic()
        with self._cache_lock:
            cached = self._search_cache.get(sanitized.digest)
            if cached is not None and cached[0] > now:
                return cached[1]
            if cached is not None:
                self._search_cache.pop(sanitized.digest, None)
        hits = tuple(
            self.provider.search(
                sanitized.query,
                limit=self.settings.WEB_SEARCH_RESULT_LIMIT,
                timeout_seconds=self.settings.WEB_SEARCH_TIMEOUT_SECONDS,
            )
        )
        ttl = self.settings.WEB_SEARCH_CACHE_TTL_SECONDS
        if ttl:
            with self._cache_lock:
                self._search_cache[sanitized.digest] = (
                    now + ttl,
                    hits,
                )
        return hits

    def _fetch_hits(
        self,
        hits: Sequence[WebSearchHit],
        *,
        question: str,
        cancel_check: Callable[[], bool],
    ) -> tuple[list[WebPageEvidence], list[str]]:
        selected: list[tuple[WebSearchHit, str, str]] = []
        seen_urls: set[str] = set()
        domains: Counter[str] = Counter()
        exclusions: list[str] = []
        for hit in hits:
            try:
                normalized, domain = self.fetcher.domain_policy.allowed_url(
                    hit.url
                )
            except (TypeError, ValueError) as exc:
                exclusions.append(str(exc) or "invalid_url")
                continue
            if normalized in seen_urls:
                exclusions.append("duplicate_url")
                continue
            if self._LOW_QUALITY_PATH.search(urlsplit(normalized).path):
                exclusions.append("low_quality_url")
                continue
            if (
                domains[domain]
                >= self.settings.WEB_FETCH_MAX_PAGES_PER_DOMAIN
            ):
                exclusions.append("domain_limit")
                continue
            seen_urls.add(normalized)
            domains[domain] += 1
            selected.append((hit, normalized, domain))
            if len(selected) >= self.settings.WEB_FETCH_MAX_PAGES:
                break
        if not selected:
            return [], exclusions
        executor = ThreadPoolExecutor(
            max_workers=min(4, len(selected)),
            thread_name_prefix="web-fetch",
        )
        futures = {
            executor.submit(self.fetcher.fetch, url): (hit, domain)
            for hit, url, domain in selected
        }
        pages: list[WebPageEvidence] = []
        try:
            for future in as_completed(
                futures,
                timeout=self.settings.WEB_TOTAL_TIMEOUT_SECONDS,
            ):
                if cancel_check():
                    exclusions.append("client_cancelled")
                    break
                hit, domain = futures[future]
                try:
                    page = future.result()
                except httpx.TimeoutException:
                    exclusions.append("fetch_timeout")
                    continue
                except Exception as exc:
                    exclusions.append(str(exc) or "fetch_failed")
                    continue
                sanitized = self.content_sanitizer.sanitize(page.content)
                exclusions.extend(sanitized.excluded_reasons)
                if len(sanitized.content) < 100:
                    exclusions.append(
                        sanitized.excluded_reasons[-1]
                        if sanitized.excluded_reasons
                        else "insufficient_content"
                    )
                    continue
                trusted = self._trusted_domain(domain)
                if self._HIGH_RISK.search(question) and not trusted:
                    exclusions.append("high_risk_source_untrusted")
                    continue
                quality = 0.55
                if trusted:
                    quality += 0.25
                if page.published_at or hit.published_at:
                    quality += 0.1
                if len(sanitized.content) >= 1000:
                    quality += 0.1
                pages.append(
                    WebPageEvidence(
                        title=page.title or clean_text(hit.title) or domain,
                        url=page.url,
                        domain=domain,
                        content=truncate_text(
                            sanitized.content,
                            self.settings.WEB_PAGE_MAX_CHARS,
                        ),
                        content_preview=truncate_text(
                            sanitized.content,
                            1000,
                        ),
                        quality_score=min(1.0, quality),
                        published_at=(
                            page.published_at or hit.published_at
                        ),
                        accessed_at=page.accessed_at,
                        metadata={
                            "provider": self.provider.name,
                            "trusted_domain": trusted,
                            "injection_segments_removed": (
                                sanitized.suspicious_segment_count
                            ),
                        },
                    )
                )
        except TimeoutError:
            exclusions.append("fetch_timeout")
        finally:
            for future in futures:
                future.cancel()
            executor.shutdown(wait=False, cancel_futures=True)
        deduplicated: dict[str, WebPageEvidence] = {}
        for page in sorted(
            pages,
            key=lambda item: (
                -item.quality_score,
                -(
                    item.published_at.timestamp()
                    if item.published_at is not None
                    else 0
                ),
                item.url,
            ),
        ):
            content_digest = sha256(
                clean_text(page.content).casefold().encode("utf-8")
            ).hexdigest()
            if content_digest in deduplicated:
                exclusions.append("duplicate_content")
                continue
            deduplicated[content_digest] = page
        return list(deduplicated.values()), exclusions

    def _trusted_domain(self, domain: str) -> bool:
        return (
            domain.endswith(".gov")
            or ".gov." in domain
            or domain.endswith(".edu")
            or ".edu." in domain
            or any(
                DomainPolicy._matches(domain, allowed)
                for allowed in self.settings.WEB_SEARCH_ALLOWED_DOMAINS
            )
        )
