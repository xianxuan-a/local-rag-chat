"""Normalized schema comparison without raw SQLite DDL string matching."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

from sqlalchemy import Engine, MetaData, Table, inspect
from sqlalchemy.engine.reflection import Inspector
from sqlalchemy.sql.schema import (
    CheckConstraint,
    ForeignKeyConstraint,
    UniqueConstraint,
)


def _normalize_space(value: str | None) -> str | None:
    if value is None:
        return None
    return re.sub(r"\s+", " ", value.strip()).casefold()


def _normalize_default(value: Any) -> str | None:
    normalized = _normalize_space(None if value is None else str(value))
    if normalized is None:
        return None
    while (
        len(normalized) >= 2
        and normalized[0] == "("
        and normalized[-1] == ")"
    ):
        normalized = normalized[1:-1].strip()
    if (
        len(normalized) >= 2
        and normalized[0] == normalized[-1]
        and normalized[0] in {"'", '"'}
    ):
        normalized = normalized[1:-1]
    return normalized


def _type_contract(type_: Any) -> tuple[str, int | None]:
    text = str(type_).upper()
    length = getattr(type_, "length", None)
    if "INT" in text:
        affinity = "INTEGER"
    elif any(token in text for token in ("CHAR", "CLOB", "TEXT")):
        affinity = "TEXT"
    elif "BLOB" in text or not text:
        affinity = "BLOB"
    elif any(token in text for token in ("REAL", "FLOA", "DOUB")):
        affinity = "REAL"
    else:
        affinity = "NUMERIC"
    return affinity, length


def _sorted_tuple(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted(values))


def describe_database(
    engine: Engine, table_names: Iterable[str] | None = None
) -> dict[str, Any]:
    inspector = inspect(engine)
    selected = set(table_names or inspector.get_table_names())
    return {
        name: _describe_inspected_table(inspector, name)
        for name in sorted(selected)
        if name != "alembic_version"
    }


def _describe_inspected_table(inspector: Inspector, name: str) -> dict[str, Any]:
    pk = inspector.get_pk_constraint(name).get("constrained_columns") or []
    pk_positions = {column: index + 1 for index, column in enumerate(pk)}
    columns = tuple(sorted(
        (
            column["name"],
            *_type_contract(column["type"]),
            bool(column["nullable"]),
            _normalize_default(column.get("default")),
            pk_positions.get(column["name"], 0),
        )
        for column in inspector.get_columns(name)
    ))
    foreign_keys = _sorted_tuple(
        "|".join(
            (
                ",".join(item.get("constrained_columns") or []),
                str(item.get("referred_table")),
                ",".join(item.get("referred_columns") or []),
                str((item.get("options") or {}).get("ondelete") or "").upper(),
            )
        )
        for item in inspector.get_foreign_keys(name)
    )
    uniques = _sorted_tuple(
        ",".join(item.get("column_names") or [])
        for item in inspector.get_unique_constraints(name)
    )
    checks = _sorted_tuple(
        _normalize_space(str(item.get("sqltext") or "")) or ""
        for item in inspector.get_check_constraints(name)
    )
    indexes = _sorted_tuple(
        "|".join(
            (
                ",".join(item.get("column_names") or []),
                "1" if item.get("unique") else "0",
                _normalize_space(
                    str((item.get("dialect_options") or {}).get("sqlite_where") or "")
                )
                or "",
            )
        )
        for item in inspector.get_indexes(name)
        if not str(item.get("name") or "").startswith("sqlite_autoindex")
    )
    return {
        "columns": columns,
        "foreign_keys": foreign_keys,
        "uniques": uniques,
        "checks": checks,
        "indexes": indexes,
    }


def describe_metadata(
    metadata: MetaData, table_names: Iterable[str] | None = None
) -> dict[str, Any]:
    selected = set(table_names or metadata.tables)
    return {
        name: _describe_metadata_table(metadata.tables[name])
        for name in sorted(selected)
    }


def _describe_metadata_table(table: Table) -> dict[str, Any]:
    pk_positions = {
        column.name: index + 1
        for index, column in enumerate(table.primary_key.columns)
    }
    columns = tuple(sorted(
        (
            column.name,
            *_type_contract(column.type),
            bool(column.nullable),
            _normalize_default(
                None if column.server_default is None else column.server_default.arg
            ),
            pk_positions.get(column.name, 0),
        )
        for column in table.columns
    ))
    foreign_keys: list[str] = []
    uniques: list[str] = []
    checks: list[str] = []
    for constraint in table.constraints:
        if isinstance(constraint, ForeignKeyConstraint):
            foreign_keys.append(
                "|".join(
                    (
                        ",".join(element.parent.name for element in constraint.elements),
                        constraint.elements[0].column.table.name,
                        ",".join(element.column.name for element in constraint.elements),
                        str(constraint.ondelete or "").upper(),
                    )
                )
            )
        elif isinstance(constraint, UniqueConstraint):
            uniques.append(",".join(column.name for column in constraint.columns))
        elif isinstance(constraint, CheckConstraint):
            checks.append(_normalize_space(str(constraint.sqltext)) or "")
    indexes = [
        "|".join(
            (
                ",".join(column.name for column in index.columns),
                "1" if index.unique else "0",
                _normalize_space(
                    str(index.dialect_options["sqlite"].get("where") or "")
                )
                or "",
            )
        )
        for index in table.indexes
    ]
    return {
        "columns": columns,
        "foreign_keys": tuple(sorted(foreign_keys)),
        "uniques": tuple(sorted(uniques)),
        "checks": tuple(sorted(checks)),
        "indexes": tuple(sorted(indexes)),
    }


@dataclass(frozen=True)
class SchemaDifference:
    table: str
    expected: Any
    actual: Any


def compare_schema(
    expected: dict[str, Any], actual: dict[str, Any]
) -> list[SchemaDifference]:
    return [
        SchemaDifference(
            table=table,
            expected=expected.get(table),
            actual=actual.get(table),
        )
        for table in sorted(set(expected) | set(actual))
        if expected.get(table) != actual.get(table)
    ]
