"""Explicit Alembic helpers; application startup only verifies, never migrates."""

from __future__ import annotations

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, inspect, text

from app.core.config import PROJECT_ROOT


def alembic_config(database_url: str | None = None) -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    if database_url:
        config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def head_revision() -> str:
    revision = ScriptDirectory.from_config(alembic_config()).get_current_head()
    if revision is None:
        raise RuntimeError("Alembic 未定义 head revision")
    return revision


def current_revision(engine: Engine) -> str | None:
    if not inspect(engine).has_table("alembic_version"):
        return None
    with engine.connect() as connection:
        return connection.scalar(text("SELECT version_num FROM alembic_version"))


def verify_database_at_head(engine: Engine) -> None:
    current = current_revision(engine)
    expected = head_revision()
    if current != expected:
        raise RuntimeError(
            "数据库 Schema 未就绪："
            f"current={current or 'unversioned'}, head={expected}。"
            "应用不会自动建表或迁移；请先对数据库副本执行迁移并在停机窗口切换。"
        )


def upgrade_database(database_url: str, revision: str = "head") -> None:
    config = alembic_config(database_url)
    command.upgrade(config, revision)


def stamp_database(database_url: str, revision: str) -> None:
    config = alembic_config(database_url)
    command.stamp(config, revision)
