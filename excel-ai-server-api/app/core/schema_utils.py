from __future__ import annotations

import re


def sanitize_sql_identifier(value: str | None) -> str:
    raw = str(value or "").strip().lower()
    cleaned = re.sub(r"[^a-z0-9_]+", "_", raw)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned or "unknown"


def get_tenant_schema_name(user_id: str | None) -> str:
    return f"tenant_usr_{sanitize_sql_identifier(user_id)}"


def split_qualified_table_name(table_name: str | None) -> tuple[str | None, str | None]:
    if not table_name:
        return None, None

    raw = str(table_name).strip()
    if "." not in raw:
        return None, raw.strip('"\'') or None

    schema_part, table_part = raw.split(".", 1)
    schema_name = schema_part.strip().strip('"\'') or None
    bare_table_name = table_part.strip().strip('"\'') or None
    return schema_name, bare_table_name


def qualify_table_name(schema_name: str, table_name: str) -> str:
    return f'"{schema_name}"."{table_name}"'


def get_workspace_schema_name(workspace_id: str | None) -> str:
    """Generate a PostgreSQL schema name for a workspace: ws_{sanitized_id}."""
    return f"ws_{sanitize_sql_identifier(workspace_id)}"