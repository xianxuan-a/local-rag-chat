"""FastAPI application factory and route registration."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import time
from typing import Any
from uuid import UUID, uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.cors import CORSMiddleware

from app.api import (
    auth,
    backups,
    chat,
    dashboard,
    evaluations,
    files,
    health,
    indexes,
    jobs,
    knowledge_base,
    metrics,
    retrieval,
    sessions,
    settings as settings_api,
    users,
)
from app.core.config import Settings, get_settings
from app.core.exceptions import AppException
from app.core.instance_lock import InstanceLock, instance_lock_path
from app.core.logger import configure_logging, get_logger
from app.core.observability import (
    HTTP_DURATION,
    HTTP_ERRORS,
    HTTP_REQUESTS,
)
from app.core.response import error_response
from app.core.security import AuthRateLimiter
from app.database.sqlite import init_database
from app.services.runtime_coordinator import RuntimeCoordinator
from app.services.job_handlers import build_default_job_handlers
from app.services.job_worker import JobWorker
from app.models import RuntimeState
from app.services.product_settings_service import ProductSettingsService
from app.services.chat_history_service import ChatHistoryService


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build an application instance, optionally with isolated test settings."""
    app_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        app_settings.ensure_directories()
        configure_logging(app_settings)
        if not app_settings.AUTH_REQUIRED:
            get_logger(__name__).warning(
                "本地单用户免登录模式已启用；生产环境禁止使用"
            )
        process_lock = InstanceLock(instance_lock_path(app_settings.DATA_DIR))
        process_lock.acquire()
        engine = None
        runtime = None
        job_worker = None
        try:
            engine, session_factory = init_database(app_settings.DATABASE_URL)
            application.state.instance_lock = process_lock
            application.state.engine = engine
            application.state.session_factory = session_factory
            application.state.settings = app_settings
            with session_factory() as settings_db:
                product_settings_service = ProductSettingsService(
                    settings_db, app_settings
                )
                product_settings = (
                    product_settings_service.load_snapshot()
                    if product_settings_service.has_persistent_settings()
                    else None
                )
            with session_factory() as recovery_db:
                recovered_chat_messages = ChatHistoryService(
                    recovery_db
                ).recover_incomplete_messages()
                if recovered_chat_messages:
                    get_logger(__name__).warning(
                        "启动时恢复了 %s 条遗留流式回答",
                        recovered_chat_messages,
                    )
            runtime = RuntimeCoordinator(app_settings, product_settings)
            application.state.rag_runtime = runtime
            job_worker = JobWorker(
                session_factory=session_factory,
                settings=app_settings,
                runtime=runtime,
                handlers=build_default_job_handlers(
                    session_factory=session_factory,
                    settings=app_settings,
                    runtime=runtime,
                ),
            )
            application.state.job_worker = job_worker
            job_worker.start()
            missing_chat_settings = (
                runtime.effective_settings().missing_chat_configuration()
            )
            if missing_chat_settings:
                get_logger(__name__).warning(
                    "RAG 聊天暂不可用，缺少配置：%s",
                    ", ".join(missing_chat_settings),
                )
            get_logger(__name__).info(
                "%s %s started",
                app_settings.APP_NAME,
                app_settings.APP_VERSION,
            )
            yield
        finally:
            if job_worker is not None:
                job_worker.stop()
            if runtime is not None:
                runtime.close()
            if engine is not None:
                engine.dispose()
            process_lock.release()
            get_logger(__name__).info("Application stopped")

    application = FastAPI(
        title=app_settings.APP_NAME,
        description="Local RAG knowledge-base indexing and question-answering API",
        version=app_settings.APP_VERSION,
        debug=app_settings.DEBUG,
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=app_settings.CORS_ALLOWED_ORIGINS,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID", "Retry-After"],
    )
    application.state.settings = app_settings
    application.state.auth_rate_limiter = AuthRateLimiter.from_settings(
        app_settings
    )
    application.dependency_overrides[get_settings] = lambda: app_settings
    _register_exception_handlers(application)
    _register_routes(application, app_settings.API_PREFIX)
    return application


def _register_routes(application: FastAPI, api_prefix: str) -> None:
    application.include_router(auth.router, prefix=api_prefix)
    application.include_router(dashboard.router, prefix=api_prefix)
    application.include_router(jobs.router, prefix=api_prefix)
    application.include_router(evaluations.router, prefix=api_prefix)
    application.include_router(evaluations.datasets_router, prefix=api_prefix)
    application.include_router(indexes.router, prefix=api_prefix)
    application.include_router(backups.router, prefix=api_prefix)
    application.include_router(knowledge_base.router, prefix=api_prefix)
    application.include_router(files.router, prefix=api_prefix)
    application.include_router(settings_api.router, prefix=api_prefix)
    application.include_router(users.router, prefix=api_prefix)
    application.include_router(retrieval.router, prefix=api_prefix)
    application.include_router(chat.router, prefix=api_prefix)
    application.include_router(sessions.router, prefix=api_prefix)
    application.include_router(metrics.router)
    application.include_router(health.router)

    @application.middleware("http")
    async def reject_business_writes_while_draining(
        request: Request, call_next: Any
    ):
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            path = request.url.path
            is_read_only_login = path == f"{api_prefix}/auth/login"
            is_control_cancel = (
                path.startswith(f"{api_prefix}/jobs/")
                and path.endswith("/cancel")
            )
            if not is_read_only_login and not is_control_cancel:
                session_factory = getattr(
                    request.app.state, "session_factory", None
                )
                if session_factory is not None:
                    with session_factory() as database_session:
                        if database_session.get(
                            RuntimeState, "BACKUP_DRAINING"
                        ) is not None:
                            return error_response(
                                code=409,
                                message=(
                                    "在线备份正在 draining 或运行，"
                                    "暂时拒绝业务写请求"
                                ),
                                status_code=409,
                            )
        return await call_next(request)

    @application.middleware("http")
    async def request_observability(request: Request, call_next: Any):
        supplied = request.headers.get("X-Request-ID", "")
        try:
            request_id = str(UUID(supplied))
        except (TypeError, ValueError):
            request_id = str(uuid4())
        request.state.request_id = request_id
        started = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            route = request.scope.get("route")
            route_label = getattr(route, "path", None) or "<unmatched>"
            method = request.method
            status = str(status_code)
            duration = max(0.0, time.perf_counter() - started)
            HTTP_REQUESTS.labels(method, route_label, status).inc()
            HTTP_DURATION.labels(method, route_label).observe(duration)
            if status_code >= 400:
                HTTP_ERRORS.labels(method, route_label, status).inc()
            get_logger("app.http").info(
                "request_id=%s user_id=%s method=%s route=%s status=%s duration_ms=%.3f",
                request_id,
                getattr(request.state, "user_id", None),
                method,
                route_label,
                status,
                duration * 1000,
            )


def _register_exception_handlers(application: FastAPI) -> None:
    @application.exception_handler(AppException)
    async def handle_app_exception(_request: Request, exc: AppException):
        return error_response(
            code=exc.code,
            message=exc.message,
            status_code=exc.status_code,
            data=exc.data,
            headers=exc.headers,
        )

    @application.exception_handler(RequestValidationError)
    async def handle_validation_exception(
        _request: Request, exc: RequestValidationError
    ):
        return error_response(
            code=422,
            message="request validation failed",
            status_code=422,
            data={"errors": exc.errors()},
        )

    @application.exception_handler(StarletteHTTPException)
    async def handle_http_exception(
        _request: Request, exc: StarletteHTTPException
    ):
        message = exc.detail if isinstance(exc.detail, str) else "HTTP request failed"
        return error_response(
            code=exc.status_code,
            message=message,
            status_code=exc.status_code,
        )

    @application.exception_handler(Exception)
    async def handle_unexpected_exception(request: Request, exc: Exception):
        get_logger(__name__).error(
            (
                "Unhandled application error request_id=%s user_id=%s "
                "method=%s path=%s error_type=%s"
            ),
            getattr(request.state, "request_id", None),
            getattr(request.state, "user_id", None),
            request.method,
            request.url.path,
            type(exc).__name__,
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        return error_response(
            code=500,
            message="internal server error",
            status_code=500,
        )


app = create_app()
