from __future__ import annotations

import json
import warnings
from typing import Optional

import pandas as pd
from fastapi import HTTPException
from app.core.auth import get_current_admin, get_current_user

from app.core.agent import HybridAgent
from app.core.database import DatabaseManager
from app.utils.audit import log_audit_event
from app.utils.logging import log_full_exception, user_facing_error_message


def get_db():
    """Dependency to get database manager."""
    return DatabaseManager()


def infer_source_type(identifier: str, db: DatabaseManager) -> str:
    """Infer source domain for an identifier: database, file, or unknown."""
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM etl_system.etl_connections WHERE connection_id = %s",
                (identifier,),
            )
            if cur.fetchone():
                return "database"

            cur.execute(
                "SELECT 1 FROM etl_system.etl_tables WHERE table_id = %s",
                (identifier,),
            )
            if cur.fetchone():
                return "database"

            cur.execute(
                "SELECT 1 FROM file_registry WHERE file_uuid = %s",
                (identifier,),
            )
            if cur.fetchone():
                return "file"

            cur.execute(
                "SELECT 1 FROM board_files WHERE file_uuid = %s",
                (identifier,),
            )
            if cur.fetchone():
                return "file"

    return "unknown"


def resolve_file_identifier(identifier: str, db: DatabaseManager, source_type: Optional[str] = None):
    """
    Resolve file identifier to file_uuid, filename, table_name, and created_by.
    Tries file_registry (UUID then filename), then falls back to board_files.
    Returns: (file_uuid, filename, table_name, created_by) tuple.
    """
    normalized_source_type = (source_type or "").strip().lower() or None
    if normalized_source_type not in {None, "file", "database"}:
        normalized_source_type = None

    with db.get_connection() as conn:
        with conn.cursor() as cur:
            if normalized_source_type in {None, "database"}:
                cur.execute(
                    "SELECT connection_id, name, created_by FROM etl_system.etl_connections WHERE connection_id = %s",
                    (identifier,),
                )
                result = cur.fetchone()
                if result:
                    return (result[0], result[1], "__DATABASE_CONNECTION__", result[2])

                cur.execute(
                    "SELECT t.table_id as file_uuid, t.table_name as filename, t.table_name, j.created_by "
                    "FROM etl_system.etl_tables t "
                    "JOIN etl_system.etl_jobs j ON t.job_id = j.job_id "
                    "WHERE t.table_id = %s",
                    (identifier,)
                )
                result = cur.fetchone()
                if result:
                    return result

            if normalized_source_type in {None, "file"}:
                cur.execute(
                    "SELECT file_uuid, filename, table_name, created_by FROM file_registry WHERE file_uuid = %s",
                    (identifier,),
                )
                result = cur.fetchone()
                if result:
                    return result

                cur.execute(
                    "SELECT file_uuid, filename, table_name, created_by FROM file_registry WHERE filename = %s",
                    (identifier,),
                )
                result = cur.fetchone()
                if result:
                    return result

                cur.execute(
                    "SELECT bf.file_uuid, bf.filename, bf.table_name, ib.created_by "
                    "FROM board_files bf JOIN insight_boards ib ON bf.board_id = ib.board_id "
                    "WHERE bf.file_uuid = %s",
                    (identifier,),
                )
                result = cur.fetchone()
                if result:
                    return result

    return None


def enforce_file_access(file_record: tuple, current_user: dict):
    """Ensure user can access a file based on ownership and role."""
    if current_user.get("role") == "admin":
        return

    owner_id = file_record[3]
    if not owner_id:
        raise HTTPException(status_code=403, detail="File access denied")

    if str(owner_id) != str(current_user.get("id")):
        raise HTTPException(status_code=403, detail="File access denied")


def _get_trace_user_metadata(current_user: dict) -> dict:
    """Return consistent user identity metadata for Langfuse traces."""
    return {
        "user_id": str(current_user.get("id") or ""),
        "user_email": str(current_user.get("email") or ""),
        "user_name": str(current_user.get("name") or ""),
        "username": str(current_user.get("username") or ""),
        "user_role": str(current_user.get("role") or ""),
    }


def get_agent(
    file_uuid: str = None,
    filename: str = None,
    load_existing: bool = True,
    user_id: str = None,
    mode: str = None,
):
    """Helper to initialize HybridAgent - supports both UUID and filename."""
    try:
        agent = HybridAgent(
            file_uuid=file_uuid,
            filename=filename,
            load_existing=load_existing,
            user_id=user_id,
            mode=mode,
        )
        return agent
    except Exception as e:
        log_full_exception(e, "Failed to initialize agent")
        raise HTTPException(status_code=400, detail=user_facing_error_message(e))


def get_or_load_agent(
    file_uuid: str = None,
    filename: str = None,
    load_existing: bool = True,
    user_id: str = None,
    db: DatabaseManager = None,
    mode: str = None,
):
    """Initialize agent: checks board_files first if db is provided, else standard file_registry flow."""
    if db and load_existing and file_uuid:
        try:
            with db.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT board_id FROM board_files WHERE file_uuid = %s", (file_uuid,))
                    res = cur.fetchone()
                    if res:
                        agent = _load_board_agent(file_uuid, res[0], db)
                        if agent:
                            agent.mode = mode
                            return agent
        except Exception:
            pass  # Fall back to get_agent if db lookup fails

    return get_agent(file_uuid=file_uuid, filename=filename, load_existing=load_existing, user_id=user_id, mode=mode)


def _load_board_agent(file_uuid: str, board_id: str, db: DatabaseManager):
    """Load a HybridAgent from a board_files row."""
    try:
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT file_uuid, filename, table_name, column_stats FROM board_files WHERE file_uuid = %s AND board_id = %s",
                    (file_uuid, board_id)
                )
                row = cur.fetchone()
                if not row:
                    return None

        obj = object.__new__(HybridAgent)
        obj.db = db
        obj.file_uuid = row["file_uuid"] if hasattr(row, '__getitem__') and isinstance(row, dict) else row[0]
        obj.filename = row["filename"] if hasattr(row, '__getitem__') and isinstance(row, dict) else row[1]
        obj.table_name = row["table_name"] if hasattr(row, '__getitem__') and isinstance(row, dict) else row[2]
        obj.user_id = None
        obj.project_id = None
        obj.subproject_id = None
        obj.progress_callback = None
        obj.sheet_name = None
        obj.file_group_id = None
        obj.is_deleted = False

        stats = row.get("column_stats") if hasattr(row, 'get') else row[3]
        if isinstance(stats, str):
            try: stats = json.loads(stats)
            except: stats = {}
        obj.column_stats = stats or {}

        if 'columns' in (stats or {}) and isinstance((stats or {}).get('columns'), dict):
            obj.columns = list((stats or {})['columns'].keys())
        else:
            with db.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(f"SELECT column_name FROM information_schema.columns WHERE table_name = %s ORDER BY ordinal_position", (obj.table_name,))
                    obj.columns = [c[0] for c in cur.fetchall()]

        import warnings
        import pandas as pd
        cols = [c for c in obj.columns if c != 'row_embedding']
        cols_join = ", ".join(f'"{c}"' for c in cols)
        with db.get_connection() as conn:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                obj.df = pd.read_sql(f"SELECT {cols_join} FROM {obj.table_name}", conn)

        return obj
    except Exception as e:
        log_full_exception(e, f"Failed to load board agent for {file_uuid}")
        return None


__all__ = [
    "enforce_file_access",
    "get_agent",
    "get_current_admin",
    "get_current_user",
    "get_db",
    "get_or_load_agent",
    "_load_board_agent",
    "log_audit_event",
    "infer_source_type",
    "resolve_file_identifier",
    "_get_trace_user_metadata",
]
