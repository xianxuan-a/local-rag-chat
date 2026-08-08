"""Server-side ownership, hidden 404, Job ownership, and admin-only maintenance."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from fastapi.testclient import TestClient
from starlette.datastructures import Headers

from app.core.security import AuthRateLimiter, RateLimitRule
from app.database.migrations import upgrade_database
from app.main import create_app
from app.services import auth_service as auth_service_module
from tests.conftest import make_test_settings


class _FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def _request(peer: str, **headers: str):
    return SimpleNamespace(
        client=SimpleNamespace(host=peer),
        headers=Headers(headers),
    )


def _test_limiter(
    clock: _FakeClock,
    *,
    max_keys: int = 100,
    ttl_seconds: float = 60,
    trusted_proxy_cidrs: tuple[str, ...] = (),
    trusted_proxy_hosts: tuple[str, ...] = (),
    resolver=None,
) -> AuthRateLimiter:
    return AuthRateLimiter(
        max_keys=max_keys,
        ttl_seconds=ttl_seconds,
        trusted_proxy_cidrs=trusted_proxy_cidrs,
        trusted_proxy_hosts=trusted_proxy_hosts,
        clock=clock,
        fingerprint_key=b"rate-limit-test-fingerprint-key",
        resolver=resolver,
    )

def _register_and_login(client, username: str) -> str:
    password = f"{username}-password-123"
    registered = client.post(
        "/api/auth/register",
        json={
            "username": username,
            "email": f"{username}@example.com",
            "password": password,
        },
    )
    assert registered.status_code == 201
    login = client.post(
        "/api/auth/login",
        json={"identity": username.upper(), "password": password},
    )
    assert login.status_code == 200
    return login.json()["data"]["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_user_resource_chain_and_admin_only_maintenance(client) -> None:
    alice_token = _register_and_login(client, "alice-owner")
    bob_token = _register_and_login(client, "bob-owner")

    alice_kb = client.post(
        "/api/knowledge-bases",
        headers=_auth(alice_token),
        json={"name": "alice-private"},
    )
    assert alice_kb.status_code == 201
    knowledge_base_id = alice_kb.json()["data"]["id"]
    assert client.get(
        f"/api/knowledge-bases/{knowledge_base_id}",
        headers=_auth(bob_token),
    ).status_code == 404
    assert client.get(
        f"/api/knowledge-bases/{knowledge_base_id}"
    ).status_code == 200

    uploaded = client.post(
        "/api/files/upload",
        headers=_auth(alice_token),
        data={"knowledge_base_id": knowledge_base_id},
        files={"file": ("private.txt", b"private", "text/plain")},
    )
    assert uploaded.status_code == 201
    file_id = uploaded.json()["data"]["id"]
    assert client.get(
        f"/api/files/{file_id}", headers=_auth(bob_token)
    ).status_code == 404

    session = client.post(
        "/api/sessions",
        headers=_auth(alice_token),
        json={
            "knowledge_base_id": knowledge_base_id,
            "title": "private session",
        },
    )
    assert session.status_code == 201
    session_id = session.json()["data"]["id"]
    assert client.get(
        f"/api/sessions/{session_id}",
        headers=_auth(bob_token),
        params={"knowledge_base_id": knowledge_base_id},
    ).status_code == 404

    submitted = client.post(
        f"/api/files/{file_id}/process", headers=_auth(alice_token)
    )
    assert submitted.status_code == 202
    job_id = submitted.json()["data"]["id"]
    assert client.get(
        f"/api/jobs/{job_id}", headers=_auth(bob_token)
    ).status_code == 404

    assert client.post(
        f"/api/knowledge-bases/{knowledge_base_id}/rebuild",
        headers=_auth(alice_token),
    ).status_code == 403
    assert client.post(
        "/api/backups", headers=_auth(alice_token)
    ).status_code == 403
    assert client.put(
        "/api/settings",
        headers=_auth(alice_token),
        json={
            "chat_model": None,
            "retrieval_top_k": 5,
            "retrieval_score_threshold": None,
            "rag_context_max_chars": 12000,
        },
    ).status_code == 403
    assert client.patch(
        f"/api/knowledge-bases/{knowledge_base_id}",
        headers=_auth(bob_token),
        json={"name": "hidden-update"},
    ).status_code == 404
    assert client.post(
        "/api/retrieval",
        headers=_auth(bob_token),
        json={
            "knowledge_base_id": knowledge_base_id,
            "query": "private",
            "top_k": 5,
            "score_threshold": None,
        },
    ).status_code == 404


def test_failure_backoff_uses_monotonic_clock_and_recovers() -> None:
    clock = _FakeClock()
    limiter = _test_limiter(clock)
    rule = RateLimitRule("login_combination", 3, 30, 2, 16)
    keys = [(rule, "203.0.113.10\0alice")]

    assert limiter.record_failures(keys) is None
    assert limiter.record_failures(keys) is None
    first_block = limiter.record_failures(keys)
    assert first_block is not None
    assert first_block.retry_after == 2
    assert limiter.check_failures(keys) == first_block

    clock.advance(2)
    assert limiter.check_failures(keys) is None
    second_block = limiter.record_failures(keys)
    assert second_block is not None
    assert second_block.retry_after == 4

    clock.advance(31)
    assert limiter.check_failures(keys) is None
    assert limiter.record_failures(keys) is None


def test_ip_account_and_combination_dimensions_cannot_be_switched_away() -> None:
    clock = _FakeClock()
    ip_rule = RateLimitRule("login_ip", 2, 60, 3, 30)
    account_rule = RateLimitRule("login_account", 2, 60, 3, 30)
    pair_rule = RateLimitRule("login_combination", 50, 60, 3, 30)

    by_ip = _test_limiter(clock)
    assert by_ip.record_failures(
        [(ip_rule, "203.0.113.1"), (account_rule, "alice"), (pair_rule, "1-a")]
    ) is None
    ip_block = by_ip.record_failures(
        [(ip_rule, "203.0.113.1"), (account_rule, "bob"), (pair_rule, "1-b")]
    )
    assert ip_block is not None
    assert ip_block.dimension == "login_ip"

    by_account = _test_limiter(clock)
    assert by_account.record_failures(
        [(ip_rule, "203.0.113.1"), (account_rule, "alice"), (pair_rule, "1-a")]
    ) is None
    account_block = by_account.record_failures(
        [(ip_rule, "203.0.113.2"), (account_rule, "alice"), (pair_rule, "2-a")]
    )
    assert account_block is not None
    assert account_block.dimension == "login_account"


def test_success_reset_does_not_clear_source_ip_attack_state() -> None:
    clock = _FakeClock()
    limiter = _test_limiter(clock)
    ip_rule = RateLimitRule("login_ip", 2, 60, 2, 20)
    account_rule = RateLimitRule("login_account", 2, 60, 2, 20)
    pair_rule = RateLimitRule("login_combination", 2, 60, 2, 20)
    first = [
        (ip_rule, "203.0.113.8"),
        (account_rule, "alice"),
        (pair_rule, "203.0.113.8\0alice"),
    ]
    assert limiter.record_failures(first) is None
    limiter.reset(first[1:])

    decision = limiter.record_failures(
        [
            (ip_rule, "203.0.113.8"),
            (account_rule, "bob"),
            (pair_rule, "203.0.113.8\0bob"),
        ]
    )

    assert decision is not None
    assert decision.dimension == "login_ip"


def test_attempt_limiter_is_atomic_under_concurrency() -> None:
    clock = _FakeClock()
    limiter = _test_limiter(clock)
    rule = RateLimitRule("register_ip", 10, 60)

    def consume(_index: int) -> bool:
        return limiter.consume_attempts([(rule, "198.51.100.2")]) is None

    with ThreadPoolExecutor(max_workers=16) as pool:
        outcomes = list(pool.map(consume, range(64)))

    assert outcomes.count(True) == 10
    assert outcomes.count(False) == 54


def test_limiter_ttl_cleanup_and_lru_key_bound() -> None:
    clock = _FakeClock()
    limiter = _test_limiter(clock, max_keys=3, ttl_seconds=10)
    rule = RateLimitRule("register_target", 5, 10)

    for target in ("one", "two", "three", "four"):
        assert limiter.consume_attempts([(rule, target)]) is None
    assert limiter.size == 3

    clock.advance(11)
    assert limiter.cleanup() == 3
    assert limiter.size == 0


def test_forwarded_headers_require_an_explicit_trusted_proxy() -> None:
    clock = _FakeClock()
    untrusted = _test_limiter(clock)
    spoofed = _request(
        "198.51.100.20",
        **{"X-Forwarded-For": "203.0.113.99"},
    )
    assert untrusted.client_ip(spoofed) == "198.51.100.20"

    trusted = _test_limiter(
        clock,
        trusted_proxy_cidrs=("10.10.0.0/24", "192.0.2.40/32"),
    )
    proxied = _request(
        "10.10.0.5",
        **{
            "X-Forwarded-For": (
                "203.0.113.7, 192.0.2.40, 10.10.0.4"
            )
        },
    )
    assert trusted.client_ip(proxied) == "203.0.113.7"
    invalid = _request(
        "10.10.0.5",
        **{"X-Forwarded-For": "203.0.113.7, invalid"},
    )
    assert trusted.client_ip(invalid) == "10.10.0.5"
    appended_by_proxy = _request(
        "10.10.0.5",
        **{"X-Forwarded-For": "invalid-spoof, 203.0.113.8"},
    )
    assert trusted.client_ip(appended_by_proxy) == "203.0.113.8"

    hostname_trusted = _test_limiter(
        clock,
        trusted_proxy_hosts=("frontend",),
        resolver=lambda hostname: ("10.20.0.9",)
        if hostname == "frontend"
        else (),
    )
    assert hostname_trusted.client_ip(
        _request(
            "10.20.0.9",
            **{
                "X-Forwarded-For": "198.51.100.9",
                "Forwarded": "for=203.0.113.250",
            },
        )
    ) == "198.51.100.9"


def test_login_returns_429_retry_after_and_hides_identity(
    tmp_path,
) -> None:
    settings = make_test_settings(
        tmp_path,
        LOGIN_RATE_LIMIT_IP_ATTEMPTS=50,
        LOGIN_RATE_LIMIT_ACCOUNT_ATTEMPTS=50,
        LOGIN_RATE_LIMIT_COMBINATION_ATTEMPTS=2,
        LOGIN_RATE_LIMIT_WINDOW_SECONDS=30,
        LOGIN_RATE_LIMIT_BACKOFF_BASE_SECONDS=3,
        LOGIN_RATE_LIMIT_BACKOFF_MAX_SECONDS=30,
    )
    settings.ensure_directories()
    upgrade_database(settings.DATABASE_URL)
    app = create_app(settings)
    clock = _FakeClock()
    app.state.auth_rate_limiter = _test_limiter(clock)

    with TestClient(
        app,
        raise_server_exceptions=False,
        client=("198.51.100.30", 50000),
    ) as client:
        bootstrap = client.post(
            "/api/auth/bootstrap",
            headers={"X-Bootstrap-Secret": "test-bootstrap-secret"},
            json={
                "username": "limited-admin",
                "email": "limited-admin@example.com",
                "password": "test-password-123",
            },
        )
        assert bootstrap.status_code == 200
        bad_payload = {
            "identity": "LIMITED-ADMIN@example.com",
            "password": "wrong-password-123",
        }
        assert client.post("/api/auth/login", json=bad_payload).status_code == 401
        limited = client.post(
            "/api/auth/login",
            json=bad_payload,
            headers={"Origin": "http://localhost:5173"},
        )
        assert limited.status_code == 429
        assert limited.headers["Retry-After"] == "3"
        assert "Retry-After" in limited.headers["Access-Control-Expose-Headers"]
        assert limited.json() == {
            "code": 429,
            "message": "尝试次数过多，请稍后再试",
            "data": {"retry_after": 3},
        }
        correct = client.post(
            "/api/auth/login",
            json={**bad_payload, "password": "test-password-123"},
        )
        assert correct.status_code == 429

        clock.advance(3)
        recovered = client.post(
            "/api/auth/login",
            json={**bad_payload, "password": "test-password-123"},
        )
        assert recovered.status_code == 200
        assert client.post("/api/auth/login", json=bad_payload).status_code == 401
        assert client.post("/api/auth/login", json=bad_payload).status_code == 429
        metrics = client.get(
            "/metrics",
            headers={"X-Metrics-Scrape-Token": "test-metrics-token"},
        )
        assert metrics.status_code == 200
        assert "local_rag_auth_rate_limit_events_total" in metrics.text
        assert "LIMITED-ADMIN" not in metrics.text

    log_text = (settings.LOG_DIR / "app.log").read_text(encoding="utf-8")
    assert "LIMITED-ADMIN" not in log_text
    assert "198.51.100.30" not in log_text
    assert "dimension=login_combination" in log_text


def test_login_unknown_and_existing_accounts_share_the_same_error(
    tmp_path,
    monkeypatch,
) -> None:
    settings = make_test_settings(tmp_path)
    settings.ensure_directories()
    upgrade_database(settings.DATABASE_URL)
    app = create_app(settings)
    checked_hashes: list[str] = []
    original_verify = auth_service_module.verify_password

    def recording_verify(password: str, password_hash: str) -> bool:
        checked_hashes.append(password_hash)
        return original_verify(password, password_hash)

    monkeypatch.setattr(auth_service_module, "verify_password", recording_verify)
    with TestClient(app, raise_server_exceptions=False) as client:
        bootstrap = client.post(
            "/api/auth/bootstrap",
            headers={"X-Bootstrap-Secret": "test-bootstrap-secret"},
            json={
                "username": "enumeration-admin",
                "email": "enumeration@example.com",
                "password": "test-password-123",
            },
        )
        assert bootstrap.status_code == 200
        existing = client.post(
            "/api/auth/login",
            json={
                "identity": "enumeration-admin",
                "password": "wrong-password-123",
            },
        )
        missing = client.post(
            "/api/auth/login",
            json={
                "identity": "does-not-exist",
                "password": "wrong-password-123",
            },
        )

    assert existing.status_code == missing.status_code == 401
    assert existing.json() == missing.json()
    assert len(checked_hashes) == 2
    assert all(value.startswith("$2b$") for value in checked_hashes)


def test_registration_and_bootstrap_have_independent_quotas(tmp_path) -> None:
    settings = make_test_settings(
        tmp_path,
        REGISTER_RATE_LIMIT_IP_ATTEMPTS=2,
        REGISTER_RATE_LIMIT_TARGET_ATTEMPTS=10,
        REGISTER_RATE_LIMIT_WINDOW_SECONDS=20,
        BOOTSTRAP_RATE_LIMIT_IP_ATTEMPTS=10,
        BOOTSTRAP_RATE_LIMIT_GLOBAL_ATTEMPTS=2,
        BOOTSTRAP_RATE_LIMIT_WINDOW_SECONDS=20,
        TRUSTED_PROXY_CIDRS=["127.0.0.1/32"],
    )
    settings.ensure_directories()
    upgrade_database(settings.DATABASE_URL)
    app = create_app(settings)
    clock = _FakeClock()
    app.state.auth_rate_limiter = _test_limiter(
        clock, trusted_proxy_cidrs=("127.0.0.1/32",)
    )

    with TestClient(
        app,
        raise_server_exceptions=False,
        client=("127.0.0.1", 50000),
    ) as client:
        for index in range(2):
            response = client.post(
                "/api/auth/register",
                headers={"X-Forwarded-For": f"203.0.113.{index + 1}"},
                json={
                    "username": f"register-{index}",
                    "email": f"register-{index}@example.com",
                    "password": "test-password-123",
                },
            )
            assert response.status_code == 201
        registration_limited = client.post(
            "/api/auth/register",
            headers={"X-Forwarded-For": "203.0.113.1"},
            json={
                "username": "register-third",
                "email": "register-third@example.com",
                "password": "test-password-123",
            },
        )
        assert registration_limited.status_code == 201
        same_ip_limited = client.post(
            "/api/auth/register",
            headers={"X-Forwarded-For": "203.0.113.1"},
            json={
                "username": "register-fourth",
                "email": "register-fourth@example.com",
                "password": "test-password-123",
            },
        )
        assert same_ip_limited.status_code == 429

        bootstrap_payload = {
            "username": "bootstrap-admin",
            "email": "bootstrap-admin@example.com",
            "password": "test-password-123",
        }
        for index in range(2):
            denied = client.post(
                "/api/auth/bootstrap",
                headers={
                    "X-Bootstrap-Secret": "wrong-secret",
                    "X-Forwarded-For": f"198.51.100.{index + 1}",
                },
                json=bootstrap_payload,
            )
            assert denied.status_code == 403
        globally_limited = client.post(
            "/api/auth/bootstrap",
            headers={
                "X-Bootstrap-Secret": "test-bootstrap-secret",
                "X-Forwarded-For": "198.51.100.3",
            },
            json=bootstrap_payload,
        )
        assert globally_limited.status_code == 429
        assert globally_limited.headers["Retry-After"] == "20"


def test_registration_target_and_bootstrap_ip_thresholds(tmp_path) -> None:
    registration_settings = make_test_settings(
        tmp_path / "registration",
        REGISTER_RATE_LIMIT_IP_ATTEMPTS=50,
        REGISTER_RATE_LIMIT_TARGET_ATTEMPTS=2,
        REGISTER_RATE_LIMIT_WINDOW_SECONDS=15,
    )
    registration_settings.ensure_directories()
    upgrade_database(registration_settings.DATABASE_URL)
    registration_app = create_app(registration_settings)
    registration_app.state.auth_rate_limiter = _test_limiter(_FakeClock())
    payload = {
        "username": "same-target",
        "email": "same-target@example.com",
        "password": "test-password-123",
    }
    with TestClient(registration_app, raise_server_exceptions=False) as client:
        assert client.post("/api/auth/register", json=payload).status_code == 201
        assert client.post("/api/auth/register", json=payload).status_code == 409
        limited = client.post("/api/auth/register", json=payload)
        assert limited.status_code == 429
        assert limited.headers["Retry-After"] == "15"

    bootstrap_settings = make_test_settings(
        tmp_path / "bootstrap",
        BOOTSTRAP_RATE_LIMIT_IP_ATTEMPTS=2,
        BOOTSTRAP_RATE_LIMIT_GLOBAL_ATTEMPTS=50,
        BOOTSTRAP_RATE_LIMIT_WINDOW_SECONDS=15,
    )
    bootstrap_settings.ensure_directories()
    upgrade_database(bootstrap_settings.DATABASE_URL)
    bootstrap_app = create_app(bootstrap_settings)
    bootstrap_app.state.auth_rate_limiter = _test_limiter(_FakeClock())
    bootstrap_payload = {
        "username": "limited-bootstrap",
        "email": "limited-bootstrap@example.com",
        "password": "test-password-123",
    }
    with TestClient(bootstrap_app, raise_server_exceptions=False) as client:
        for _index in range(2):
            assert client.post(
                "/api/auth/bootstrap",
                headers={"X-Bootstrap-Secret": "wrong-secret"},
                json=bootstrap_payload,
            ).status_code == 403
        limited = client.post(
            "/api/auth/bootstrap",
            headers={"X-Bootstrap-Secret": "test-bootstrap-secret"},
            json=bootstrap_payload,
        )
        assert limited.status_code == 429
        assert limited.headers["Retry-After"] == "15"
