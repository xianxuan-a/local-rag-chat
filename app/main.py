"""FastAPI application factory and route registration."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import chat, files, knowledge_base, sessions
from app.core.config import Settings, get_settings
from app.core.exceptions import AppException
from app.core.logger import configure_logging, get_logger
from app.core.response import error_response, success_response
from app.database.sqlite import init_database


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build an application instance, optionally with isolated test settings."""
    app_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        app_settings.ensure_directories()
        configure_logging(app_settings)
        engine, session_factory = init_database(app_settings.DATABASE_URL)
        application.state.engine = engine
        application.state.session_factory = session_factory
        application.state.settings = app_settings
        get_logger(__name__).info(
            "%s %s started", app_settings.APP_NAME, app_settings.APP_VERSION
        )
        try:
            yield
        finally:
            engine.dispose()
            get_logger(__name__).info("Application stopped")

    application = FastAPI(
        title=app_settings.APP_NAME,
        description="Local RAG knowledge-base API (initialization phase)",
        version=app_settings.APP_VERSION,
        debug=app_settings.DEBUG,
        lifespan=lifespan,
    )
    application.state.settings = app_settings
    application.dependency_overrides[get_settings] = lambda: app_settings
    _register_exception_handlers(application)
    _register_routes(application, app_settings.API_PREFIX)
    return application


def _register_routes(application: FastAPI, api_prefix: str) -> None:
    application.include_router(knowledge_base.router, prefix=api_prefix)
    application.include_router(files.router, prefix=api_prefix)
    application.include_router(chat.router, prefix=api_prefix)
    application.include_router(sessions.router, prefix=api_prefix)

    @application.get("/health")
    def health_check():
        return success_response({"status": "ok"})


def _register_exception_handlers(application: FastAPI) -> None:
    @application.exception_handler(AppException)
    async def handle_app_exception(_request: Request, exc: AppException):
        return error_response(
            code=exc.code,
            message=exc.message,
            status_code=exc.status_code,
            data=exc.data,
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
    async def handle_unexpected_exception(_request: Request, exc: Exception):
        get_logger(__name__).error(
            "Unhandled application error",
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        return error_response(
            code=500,
            message="internal server error",
            status_code=500,
        )


app = create_app()
