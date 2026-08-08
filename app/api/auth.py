"""Authentication and explicit bootstrap routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request, status
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentUser
from app.core.config import Settings, get_settings
from app.core.exceptions import RateLimitException, ValidationException
from app.core.logger import get_logger
from app.core.observability import AUTH_RATE_LIMIT_EVENTS
from app.core.response import ApiResponse, success_response
from app.core.security import (
    AuthRateLimiter,
    RateLimitDecision,
    RateLimitRule,
    normalize_identity,
    secrets_equal,
)
from app.database.sqlite import get_db
from app.schemas.auth import (
    BootstrapAdminRequest,
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from app.services.auth_service import AuthService
from app.services.runtime_coordinator import RuntimeCoordinator, get_runtime_coordinator


router = APIRouter(prefix="/auth", tags=["auth"])
DatabaseSession = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]
RagRuntime = Annotated[RuntimeCoordinator, Depends(get_runtime_coordinator)]


def _limiter(
    request: Request, settings: Settings
) -> AuthRateLimiter | None:
    if not settings.AUTH_RATE_LIMIT_ENABLED:
        return None
    return request.app.state.auth_rate_limiter


def _reject_rate_limited(
    request: Request,
    endpoint: str,
    decision: RateLimitDecision,
) -> None:
    AUTH_RATE_LIMIT_EVENTS.labels(endpoint, decision.dimension).inc()
    get_logger("app.security").warning(
        (
            "event=auth_rate_limited request_id=%s endpoint=%s "
            "dimension=%s key_digest=%s retry_after=%s"
        ),
        getattr(request.state, "request_id", None),
        endpoint,
        decision.dimension,
        decision.key_digest,
        decision.retry_after,
    )
    raise RateLimitException(decision.retry_after)


def _login_rules(
    settings: Settings,
    source_ip: str,
    normalized_identity: str,
) -> list[tuple[RateLimitRule, str]]:
    common = {
        "window_seconds": settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS,
        "backoff_base_seconds": (
            settings.LOGIN_RATE_LIMIT_BACKOFF_BASE_SECONDS
        ),
        "backoff_max_seconds": settings.LOGIN_RATE_LIMIT_BACKOFF_MAX_SECONDS,
    }
    return [
        (
            RateLimitRule(
                "login_ip", settings.LOGIN_RATE_LIMIT_IP_ATTEMPTS, **common
            ),
            source_ip,
        ),
        (
            RateLimitRule(
                "login_account",
                settings.LOGIN_RATE_LIMIT_ACCOUNT_ATTEMPTS,
                **common,
            ),
            normalized_identity,
        ),
        (
            RateLimitRule(
                "login_combination",
                settings.LOGIN_RATE_LIMIT_COMBINATION_ATTEMPTS,
                **common,
            ),
            f"{source_ip}\0{normalized_identity}",
        ),
    ]


@router.post(
    "/register",
    response_model=ApiResponse[UserResponse],
    status_code=status.HTTP_201_CREATED,
)
def register(
    payload: RegisterRequest,
    request: Request,
    db: DatabaseSession,
    settings: AppSettings,
    runtime: RagRuntime,
):
    if not settings.ALLOW_REGISTRATION:
        raise ValidationException("当前部署未开放用户注册", status_code=403)
    limiter = _limiter(request, settings)
    if limiter is not None:
        source_ip = limiter.client_ip(request)
        target_rules = [
            (
                RateLimitRule(
                    "register_target",
                    settings.REGISTER_RATE_LIMIT_TARGET_ATTEMPTS,
                    settings.REGISTER_RATE_LIMIT_WINDOW_SECONDS,
                ),
                f"username:{normalize_identity(payload.username)}",
            )
        ]
        if payload.email:
            target_rules.append(
                (
                    RateLimitRule(
                        "register_target",
                        settings.REGISTER_RATE_LIMIT_TARGET_ATTEMPTS,
                        settings.REGISTER_RATE_LIMIT_WINDOW_SECONDS,
                    ),
                    f"email:{normalize_identity(payload.email)}",
                )
            )
        decision = limiter.consume_attempts(
            [
                (
                    RateLimitRule(
                        "register_ip",
                        settings.REGISTER_RATE_LIMIT_IP_ATTEMPTS,
                        settings.REGISTER_RATE_LIMIT_WINDOW_SECONDS,
                    ),
                    source_ip,
                ),
                *target_rules,
            ]
        )
        if decision is not None:
            _reject_rate_limited(request, "register", decision)
    with runtime.business_write("register"):
        user = AuthService(db, settings).register(payload)
    return success_response(
        UserResponse.model_validate(user), status_code=status.HTTP_201_CREATED
    )


@router.post("/login", response_model=ApiResponse[TokenResponse])
def login(
    payload: LoginRequest,
    request: Request,
    db: DatabaseSession,
    settings: AppSettings,
):
    limiter = _limiter(request, settings)
    rules: list[tuple[RateLimitRule, str]] = []
    if limiter is not None:
        rules = _login_rules(
            settings,
            limiter.client_ip(request),
            normalize_identity(payload.identity),
        )
        decision = limiter.check_failures(rules)
        if decision is not None:
            _reject_rate_limited(request, "login", decision)
    try:
        user, token, jti = AuthService(db, settings).login(payload)
    except ValidationException as exc:
        if limiter is not None and exc.status_code == 401:
            decision = limiter.record_failures(rules)
            if decision is not None:
                _reject_rate_limited(request, "login", decision)
        raise
    if limiter is not None:
        limiter.reset(rules[1:])
    return success_response(
        TokenResponse(
            access_token=token,
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            jti=jti,
            user=UserResponse.model_validate(user),
        )
    )


@router.post("/bootstrap", response_model=ApiResponse[UserResponse])
def bootstrap_admin(
    payload: BootstrapAdminRequest,
    request: Request,
    db: DatabaseSession,
    settings: AppSettings,
    runtime: RagRuntime,
    bootstrap_secret: Annotated[str, Header(alias="X-Bootstrap-Secret")],
):
    limiter = _limiter(request, settings)
    if limiter is not None:
        decision = limiter.consume_attempts(
            [
                (
                    RateLimitRule(
                        "bootstrap_ip",
                        settings.BOOTSTRAP_RATE_LIMIT_IP_ATTEMPTS,
                        settings.BOOTSTRAP_RATE_LIMIT_WINDOW_SECONDS,
                    ),
                    limiter.client_ip(request),
                ),
                (
                    RateLimitRule(
                        "bootstrap_global",
                        settings.BOOTSTRAP_RATE_LIMIT_GLOBAL_ATTEMPTS,
                        settings.BOOTSTRAP_RATE_LIMIT_WINDOW_SECONDS,
                    ),
                    "global",
                ),
            ]
        )
        if decision is not None:
            _reject_rate_limited(request, "bootstrap", decision)
    if not secrets_equal(
        bootstrap_secret, settings.BOOTSTRAP_SECRET.get_secret_value()
    ):
        raise ValidationException("bootstrap Secret 无效", status_code=403)
    with runtime.business_write("bootstrap_admin"):
        user = AuthService(db, settings).bootstrap_admin(payload)
    return success_response(UserResponse.model_validate(user))


@router.get("/me", response_model=ApiResponse[UserResponse])
def me(user: CurrentUser):
    return success_response(UserResponse.model_validate(user))
