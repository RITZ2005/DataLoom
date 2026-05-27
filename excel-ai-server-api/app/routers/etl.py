"""
ETL Router — API endpoints for the Code-First ETL pipeline.

Endpoints:
  POST /api/etl/connect         — Test connection + return available tables
  POST /api/etl/preview-table   — Fetch sample rows from external DB
  POST /api/etl/dry-run         — Run full pipeline on 100 rows
  POST /api/etl/execute-job     — Dispatch full ETL job (background)
  GET  /api/etl/job/{job_id}    — Poll job status
  GET  /api/etl/connections     — List saved connections
  DELETE /api/etl/connections/{connection_id} — Remove connection
"""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import uuid
import math
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, Dict
from pathlib import Path
import pandas as pd

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Body

from app.core.auth import get_current_user
from app.core.database import DatabaseManager
from app.core.etl.connectors.base_connector import ConnectionConfig
from app.core.etl.connectors.factory import create_connector
from app.core.etl.sandbox.executor import ETLExecutor
from app.core.etl.loader import ETLLoader
from app.core.schema_utils import get_workspace_schema_name
from app.schemas.etl import (
    ETLConnectRequest,
    ETLConnectResponse,
    ETLConnectionInfo,
    ETLConnectionListResponse,
    ETLDatasetInput,
    ETLDatasetListResponse,
    ETLDatasetConnection,
    ETLDatasetJob,
    ETLDatasetTable,
    ETLDryRunRequest,
    ETLDryRunResponse,
    ETLDeltaSyncRequest,
    ETLExecuteRequest,
    ETLJobResponse,
    ETLJobStatusResponse,
    ETLPreviewRequest,
    ETLPreviewResponse,
    ETLGenerateTransformRequest,
    ETLGenerateTransformResponse,
    ETLSyncUpdateRequest,
    ETLSyncUpdateResponse,
    TableInfo,
)
from app.utils.logging import logger, log_full_exception
from app.core.agent import ChatOpenAI

router = APIRouter(prefix="/api/etl", tags=["ETL"])

# In-memory connector cache (connection_id → connector instance)
# Connectors are short-lived — they stay alive during the wizard flow
_active_connectors: Dict[str, Any] = {}


def _get_db() -> DatabaseManager:
    return DatabaseManager()


def _get_or_restore_connector(connection_id: str, user_id: str) -> dict[str, Any]:
    """Return an active connector from memory, or rebuild it from saved connection metadata."""
    cached = _active_connectors.get(connection_id)
    if cached:
        return cached

    db = _get_db()
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT db_type, host, port, database_name, username, password
                FROM etl_system.etl_connections
                WHERE connection_id = %s AND created_by = %s
                """,
                (connection_id, user_id),
            )
            row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Connection not found or not owned by you")

    config = ConnectionConfig(
        db_type=row[0],
        host=row[1],
        port=row[2],
        database=row[3],
        username=row[4],
        password=row[5],
        auth_source=None,
    )

    try:
        connector = create_connector(config)
        connector.connect()
        if not connector.test_connection():
            raise HTTPException(status_code=400, detail="Saved connection failed test. Please reconnect.")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to restore source connection: {str(e)}")

    restored = {
        "connector": connector,
        "config": config,
        "user_id": user_id,
    }
    _active_connectors[connection_id] = restored
    return restored



def _normalize_extract_datasets(
    table_names: list[str] | None,
    datasets: list[ETLDatasetInput] | None,
) -> list[dict[str, str]]:
    """Merge legacy table_names and new dataset definitions into one extract plan."""
    normalized: list[dict[str, str]] = []

    for table in table_names or []:
        if table and table.strip():
            normalized.append({"table_name": table.strip()})

    for d in datasets or []:
        model_data = d.model_dump()
        table_name = (model_data.get("table_name") or "").strip()
        custom_query = (model_data.get("custom_query") or "").strip()
        output_name = (model_data.get("output_name") or "").strip()
        sync_column = (model_data.get("sync_column") or "").strip()
        if table_name:
            normalized.append({"table_name": table_name, "sync_column": sync_column})
        elif custom_query:
            normalized.append({"custom_query": custom_query, "output_name": output_name, "sync_column": sync_column})

    return normalized


def _dataset_names_for_job(datasets: list[dict[str, str]]) -> list[str]:
    names: list[str] = []
    for idx, d in enumerate(datasets):
        if d.get("table_name"):
            names.append(d["table_name"])
        else:
            names.append(d.get("output_name") or f"dataset_{idx + 1}")
    return names


def _is_missing_value(value: Any) -> bool:
    if value is None:
        return True
    try:
        missing = pd.isna(value)
    except Exception:
        return False
    try:
        return bool(missing)
    except Exception:
        return False


def _to_json_safe(value: Any) -> Any:
    """Convert pandas/numpy-rich values into plain JSON-safe Python types."""
    if _is_missing_value(value):
        return None

    if isinstance(value, dict):
        return {str(k): _to_json_safe(v) for k, v in value.items()}

    if isinstance(value, (list, tuple, set)):
        return [_to_json_safe(v) for v in value]

    if isinstance(value, (datetime, date, time)):
        return value.isoformat()

    if isinstance(value, timedelta):
        return str(value)

    if isinstance(value, Decimal):
        value = float(value)

    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")

    if hasattr(value, "tolist") and not isinstance(value, (str, bytes)):
        try:
            converted = value.tolist()
        except Exception:
            converted = value
        if converted is not value:
            return _to_json_safe(converted)

    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        try:
            converted = value.item()
        except Exception:
            converted = value
        if converted is not value:
            return _to_json_safe(converted)

    if isinstance(value, float):
        return None if math.isnan(value) or math.isinf(value) else value

    if isinstance(value, Path):
        return str(value)

    if isinstance(value, (str, int, bool)):
        return value

    return str(value)


def _sanitize_preview_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{str(k): _to_json_safe(v) for k, v in row.items()} for row in rows]


def _build_preview_records(df: pd.DataFrame, limit: int = 20) -> list[dict[str, Any]]:
    return _sanitize_preview_rows(df.head(limit).to_dict(orient="records"))


# ═══════════════════════════════════════════════════════════════════════════
# POST /api/etl/connect
# ═══════════════════════════════════════════════════════════════════════════
@router.post("/connect", response_model=ETLConnectResponse)
async def etl_connect(
    req: ETLConnectRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Connect to an external database and return available tables/collections.
    The connection is saved for subsequent preview/extract operations.
    """
    db = _get_db()

    # Pre-populate properties if using a saved connection
    if req.connection_id:
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT db_type, host, port, database_name, username, password
                    FROM etl_system.etl_connections WHERE connection_id = %s
                    """,
                    (req.connection_id,),
                )
                row = cur.fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="Connection not found")
                
                req.db_type = row[0]
                req.host = row[1]
                req.port = row[2]
                req.database = row[3]
                req.username = row[4]
                req.password = row[5]

    try:
        config = ConnectionConfig(
            db_type=req.db_type,
            host=req.host,
            port=req.port,
            username=req.username,
            password=req.password,
            database=req.database,
            auth_source=req.auth_source,
        )

        connector = create_connector(config)
        connector.connect()

        if not connector.test_connection():
            raise HTTPException(status_code=400, detail="Connection test failed — check your credentials and host.")

        tables_raw = connector.list_tables()
        tables = [
            TableInfo(
                name=t["name"],
                row_count=t.get("row_count"),
                columns=t.get("columns"),
            )
            for t in tables_raw
        ]

        # Generate connection ID if it's new
        connection_id = req.connection_id or str(uuid.uuid4())
        _active_connectors[connection_id] = {
            "connector": connector,
            "config": config,
            "user_id": str(current_user.get("id", "")),
        }

        # Persist new connection metadata (with plain-text password for now)
        if not req.connection_id:
            conn_name = req.connection_name or f"{req.db_type}://{req.host}/{req.database}"
            with db.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO etl_system.etl_connections
                            (connection_id, name, db_type, host, port, database_name, username, password, created_by)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (connection_id) 
                        DO UPDATE SET
                            password = EXCLUDED.password,
                            last_used_at = CURRENT_TIMESTAMP
                        """,
                        (connection_id, conn_name, req.db_type, req.host, req.port,
                         req.database, req.username, req.password, str(current_user.get("id", ""))),
                    )
                conn.commit()
        else:
            # Just update last_used_at
            with db.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("UPDATE etl_system.etl_connections SET last_used_at = CURRENT_TIMESTAMP WHERE connection_id = %s", (connection_id,))
                conn.commit()

        logger.info(
            "[ETL] Connected to %s://%s:%s/%s — %d tables found",
            req.db_type, req.host, req.port, req.database, len(tables),
        )

        return ETLConnectResponse(
            connection_id=connection_id,
            db_type=req.db_type,
            database=req.database,
            tables=tables,
        )

    except HTTPException:
        raise
    except Exception as e:
        log_full_exception(e, "ETL connect failed")
        raise HTTPException(status_code=500, detail=f"Connection failed: {str(e)}")


# ═══════════════════════════════════════════════════════════════════════════
# POST /api/etl/preview-table
# ═══════════════════════════════════════════════════════════════════════════
@router.post("/preview-table", response_model=ETLPreviewResponse)
async def etl_preview_table(
    req: ETLPreviewRequest,
    current_user: dict = Depends(get_current_user),
):
    """Fetch sample rows from an external database table for preview."""
    cached = _get_or_restore_connector(req.connection_id, str(current_user.get("id", "")))

    connector = cached["connector"]

    try:
        rows = _sanitize_preview_rows(connector.preview_table(req.table_name, limit=req.limit))
        columns = list(rows[0].keys()) if rows else []

        return ETLPreviewResponse(
            table_name=req.table_name,
            rows=rows,
            total_rows=len(rows),
            columns=columns,
        )

    except Exception as e:
        log_full_exception(e, f"ETL preview failed for table {req.table_name}")
        raise HTTPException(status_code=500, detail=f"Preview failed: {str(e)}")


# ═══════════════════════════════════════════════════════════════════════════
# POST /api/etl/dry-run
# ═══════════════════════════════════════════════════════════════════════════
@router.post("/dry-run", response_model=ETLDryRunResponse)
async def etl_dry_run(
    req: ETLDryRunRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Run the full ETL pipeline on only 100 rows for quick preview.
    Extract → Transform (sandbox) → return output preview.
    """
    cached = _get_or_restore_connector(req.connection_id, str(current_user.get("id", "")))

    connector = cached["connector"]
    work_dir = tempfile.mkdtemp(prefix="etl_dryrun_")

    try:
        input_dir = os.path.join(work_dir, "input")
        output_dir = os.path.join(work_dir, "output")
        script_path = os.path.join(work_dir, "transform.py")

        # 1. Extract (only 100 rows via fast native extraction)
        os.makedirs(input_dir, exist_ok=True)
        import pandas as pd
        normalized_datasets = _normalize_extract_datasets(req.table_names, req.datasets)
        for d in normalized_datasets:
            if d.get("custom_query"):
                # Dry-run has no persisted high-water mark yet; use a safe default.
                is_time = any(w in d["custom_query"].lower() for w in ['date', 'time', 'at', 'stamp', 'created', 'updated'])
                val = "1970-01-01 00:00:00" if is_time else "0"
                d["custom_query"] = re.sub(r"['\"]?\{\{\s*LAST_SYNC_VALUE\s*\}\}['\"]?", f"'{val}'", d["custom_query"], flags=re.IGNORECASE)
        connector.extract_to_parquet(
            table_names=[d["table_name"] for d in normalized_datasets if d.get("table_name")],
            datasets=normalized_datasets,
            output_dir=input_dir,
            limit=100,
        )

        # 2. Write user script
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(req.transform_script)

        # 3. Run sandbox (with row_limit for safety)
        executor = ETLExecutor(timeout=30)  # Short timeout for dry-run
        result = executor.run_transform(
            input_dir=input_dir,
            output_dir=output_dir,
            script_path=script_path,
        )

        if not result.success:
            return ETLDryRunResponse(
                success=False,
                duration_seconds=result.duration_seconds,
                error=result.stderr,
                stdout=result.stdout,
            )

        # 4. Read output parquets and return preview
        output_tables = []
        for pq_file in sorted(Path(output_dir).glob("*.parquet")):
            df = pd.read_parquet(pq_file)
            output_tables.append({
                "name": pq_file.stem,
                "row_count": len(df),
                "columns": [str(col) for col in df.columns.tolist()],
                "preview": _build_preview_records(df),
            })

        return ETLDryRunResponse(
            success=True,
            duration_seconds=result.duration_seconds,
            output_tables=output_tables,
            stdout=result.stdout,
        )

    except Exception as e:
        log_full_exception(e, "ETL dry-run failed")
        return ETLDryRunResponse(
            success=False,
            error=f"Dry-run failed: {str(e)}",
        )
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


# ═══════════════════════════════════════════════════════════════════════════
# POST /api/etl/execute-job
# ═══════════════════════════════════════════════════════════════════════════
@router.post("/execute-job", response_model=ETLJobResponse)
async def etl_execute_job(
    req: ETLExecuteRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
):
    """
    Submit a full ETL pipeline job. Runs in the background:
    Extract (full data) → Transform (sandbox) → Load (PostgreSQL).
    """
    cached = _get_or_restore_connector(req.connection_id, str(current_user.get("id", "")))

    if req.job_id:
        job_id = req.job_id
    else:
        job_id = str(uuid.uuid4())
    user_id = str(current_user.get("id", ""))

    normalized_datasets = _normalize_extract_datasets(req.table_names, req.datasets)

    if not req.workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id is required for ETL execution")

    pipeline_name = (req.pipeline_name or "").strip()
    if not pipeline_name:
        if normalized_datasets:
            first_dataset = normalized_datasets[0]
            pipeline_name = (first_dataset.get("output_name") or first_dataset.get("table_name") or "").strip()
        if not pipeline_name and req.table_names:
            pipeline_name = req.table_names[0].strip()
        if not pipeline_name:
            pipeline_name = f"Pipeline {job_id[:8]}"

    if not req.sync_column:
        for nd in normalized_datasets:
            if nd.get("sync_column"):
                req.sync_column = nd["sync_column"]
                break

    if not req.sync_column:
        for nd in normalized_datasets:
            q = nd.get('custom_query', '')
            if '{{LAST_SYNC_VALUE}}' in q:
                import re
                match = re.search(r'([A-Za-z0-9_]+)\s*(>|<|=|>=|<=)\s*[\'\"]*\{\{\s*LAST_SYNC_VALUE\s*\}\}[\'\"]*', q, re.IGNORECASE)
                if match:
                    req.sync_column = match.group(1)
                    break

    # Create job record
    db = _get_db()
    
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            if req.job_id:
                cur.execute(
                    """
                    UPDATE etl_system.etl_jobs
                    SET connection_id = %s, status = %s, source_tables = %s, transform_script = %s, started_at = %s, target_table = %s, sync_mode = %s, sync_column = %s, workspace_id = %s, pipeline_name = %s, primary_keys = %s
                    WHERE job_id = %s AND created_by = %s
                    """,
                    (req.connection_id, "pending",
                     json.dumps(normalized_datasets), req.transform_script,
                     datetime.utcnow(), req.target_table, req.sync_mode, req.sync_column, req.workspace_id, pipeline_name, json.dumps(req.primary_keys) if req.primary_keys else None,
                     job_id, user_id),
                )
                if cur.rowcount == 0:
                     raise HTTPException(status_code=404, detail="Job not found or unauthorized")
            else:
                cur.execute(
                    """
                    INSERT INTO etl_system.etl_jobs
                        (job_id, connection_id, status, source_tables, transform_script, created_by, started_at, target_table, sync_mode, sync_column, workspace_id, pipeline_name, primary_keys)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (job_id, req.connection_id, "pending",
                     json.dumps(normalized_datasets), req.transform_script,
                     user_id, datetime.utcnow(), req.target_table, req.sync_mode, req.sync_column, req.workspace_id, pipeline_name, json.dumps(req.primary_keys) if req.primary_keys else None),
                )
        conn.commit()

    # Dispatch background task
    background_tasks.add_task(
        _run_full_etl_pipeline,
        job_id=job_id,
        connection_id=req.connection_id,
        table_names=[d["table_name"] for d in normalized_datasets if d.get("table_name")],
        datasets=normalized_datasets,
        transform_script=req.transform_script,
        user_id=user_id,
        target_table=req.target_table,
        pipeline_name=pipeline_name,
        sync_mode=req.sync_mode,
        workspace_id=req.workspace_id,
        primary_keys=req.primary_keys,
    )

    return ETLJobResponse(job_id=job_id, status="pending")


# ═══════════════════════════════════════════════════════════════════════════
# GET /api/etl/job/{job_id}
# ═══════════════════════════════════════════════════════════════════════════
@router.get("/job/{job_id}", response_model=ETLJobStatusResponse)
async def etl_job_status(
    job_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Poll the status of an ETL job."""
    db = _get_db()
    
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT job_id, status, source_tables, output_tables,
                       error_message, started_at, completed_at, created_at,
                      target_table, sync_mode, high_water_mark, sync_column, sync_mode_type, pipeline_name, primary_keys
                FROM etl_system.etl_jobs WHERE job_id = %s
                """,
                (job_id,),
            )
            row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Job not found")

    return ETLJobStatusResponse(
        job_id=row[0],
        status=row[1],
        source_tables=row[2],
        output_tables=row[3],
        error_message=row[4],
        started_at=str(row[5]) if row[5] else None,
        completed_at=str(row[6]) if row[6] else None,
        created_at=str(row[7]) if row[7] else None,
        target_table=row[8],
        sync_mode=row[9],
        high_water_mark=row[10],
        sync_column=row[11],
        sync_mode_type=row[12],
        pipeline_name=row[13],
        primary_keys=row[14],
    )


# ═══════════════════════════════════════════════════════════════════════════
# DELETE /api/etl/job/{job_id}
# ═══════════════════════════════════════════════════════════════════════════
@router.delete("/job/{job_id}")
async def etl_delete_job(
    job_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Delete an ETL pipeline and its associated tables."""
    db = _get_db()
    user_id = str(current_user.get("id"))
    
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT workspace_id FROM etl_system.etl_jobs WHERE job_id = %s AND created_by = %s",
                (job_id, user_id)
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Pipeline not found or not owned by you")
            
            workspace_id = row[0]
            
            cur.execute(
                "SELECT table_name FROM etl_system.etl_tables WHERE job_id = %s",
                (job_id,)
            )
            tables = cur.fetchall()
            
            for (full_table_name,) in tables:
                try:
                    cur.execute(f"DROP TABLE IF EXISTS {full_table_name} CASCADE")
                except Exception as e:
                    logger.warning(f"Failed to drop table {full_table_name}: {e}")
                
                parts = full_table_name.replace('"', '').split('.')
                if len(parts) == 2:
                    raw_table_name = parts[1]
                    cur.execute(
                        "DELETE FROM etl_system.tables_metadata WHERE workspace_id = %s AND table_name = %s",
                        (workspace_id, raw_table_name)
                    )
                    cur.execute(
                        "DELETE FROM etl_system.columns_metadata WHERE workspace_id = %s AND table_name = %s",
                        (workspace_id, raw_table_name)
                    )
            
            cur.execute("DELETE FROM etl_system.etl_jobs WHERE job_id = %s", (job_id,))
            
        conn.commit()
        
    return {"message": "Pipeline and associated tables deleted"}


# ═══════════════════════════════════════════════════════════════════════════
# GET /api/etl/connection/{connection_id}/jobs
# ═══════════════════════════════════════════════════════════════════════════
@router.get("/connection/{connection_id}/jobs")
async def etl_get_connection_jobs(
    connection_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Get all previously created pipelines (jobs) for a specific connection."""
    db = _get_db()
    user_id = str(current_user.get("id"))
    
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                                    SELECT job_id, status, source_tables, output_tables, created_at, completed_at,
                                            target_table, sync_mode, high_water_mark, sync_column, sync_mode_type, pipeline_name
                FROM etl_system.etl_jobs
                WHERE connection_id = %s AND created_by = %s
                ORDER BY created_at DESC
                """,
                (connection_id, user_id)
            )
            rows = cur.fetchall()

    jobs = []
    for r in rows:
        try:
            source_tables = json.loads(r[2]) if isinstance(r[2], str) else r[2]
            out_tables = json.loads(r[3]) if isinstance(r[3], str) else r[3]
        except Exception:
            source_tables = []
            out_tables = []

        target_table = r[6]
        if not target_table and isinstance(out_tables, list) and out_tables:
            first_out = out_tables[0]
            if isinstance(first_out, dict):
                target_table = first_out.get("table_name") or first_out.get("full_table_name")

        pipeline_name = None
        if len(r) > 11 and r[11]:
            pipeline_name = r[11]
        elif isinstance(source_tables, list) and source_tables:
            first_source = source_tables[0]
            if isinstance(first_source, dict):
                pipeline_name = first_source.get("output_name") or first_source.get("table_name")
            elif isinstance(first_source, str):
                pipeline_name = first_source
        if not pipeline_name:
            pipeline_name = f"Pipeline {str(r[0])[:8]}"
            
        jobs.append({
            "job_id": r[0],
            "status": r[1],
            "source_tables": source_tables,
            "output_tables": out_tables,
            "created_at": str(r[4]) if r[4] else None,
            "completed_at": str(r[5]) if r[5] else None,
            "target_table": target_table,
            "sync_mode": r[7],
            "high_water_mark": r[8],
            "sync_column": r[9],
            "sync_mode_type": r[10] or "hwm",
            "pipeline_name": pipeline_name,
        })
    return jobs


# ═══════════════════════════════════════════════════════════════════════════
# POST /api/etl/job/{job_id}/sync
# ═══════════════════════════════════════════════════════════════════════════
@router.post("/job/{job_id}/sync", response_model=ETLSyncUpdateResponse)
async def etl_delta_sync(
    job_id: str,
    req: ETLDeltaSyncRequest = Body(default_factory=ETLDeltaSyncRequest),
    current_user: dict = Depends(get_current_user),
):
    """
    Incremental/Delta Pull: Fetch new entries from the source DB using High-Water Mark.
    Replaces {{LAST_SYNC_VALUE}} in the original query with the actual MAX value from the target table.
    """
    db = _get_db()
    
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT connection_id, source_tables, transform_script, output_tables, created_by, high_water_mark, target_table, sync_column, sync_mode_type, workspace_id, primary_keys
                FROM etl_system.etl_jobs
                WHERE job_id = %s
                """,
                (job_id,)
            )
            row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Pipeline job not found")

    connection_id, source_tables_json, transform_script, output_tables_json, created_by, saved_hwm, db_target_table, db_sync_column, sync_mode_type, workspace_id, primary_keys_json = row
    primary_keys = primary_keys_json if isinstance(primary_keys_json, list) else (json.loads(primary_keys_json) if primary_keys_json else None)
    sync_mode_type = sync_mode_type or 'hwm'
    target_table_name = db_target_table
    actual_sync_column = db_sync_column or req.sync_column
    
    if str(current_user.get("id")) != str(created_by):
        raise HTTPException(status_code=403, detail="Not authorized to sync this pipeline")

    try:
        source_tables = source_tables_json if isinstance(source_tables_json, list) else json.loads(source_tables_json)
        output_tables = output_tables_json if isinstance(output_tables_json, list) else json.loads(output_tables_json)
    except Exception:
        raise HTTPException(status_code=400, detail="Pipeline metadata is corrupted")

    if not target_table_name and output_tables:
        target_table_name = output_tables[0].get("table_name")

    if not source_tables:
        raise HTTPException(
            status_code=400,
            detail=(
                "This pipeline does not have source metadata for Delta Sync. "
                "Please recreate this pipeline from Step 3."
            ),
        )

    # Build per-source delta datasets so multi-source pipelines keep working.
    parsed_output_tables = output_tables if isinstance(output_tables, list) else []
    target_by_source: Dict[str, str] = {}
    for out in parsed_output_tables:
        if isinstance(out, dict):
            src = (out.get("source_name") or "").strip()
            dst = (out.get("table_name") or "").strip()
            if src and dst:
                target_by_source[src] = dst

    source_specs: list[dict[str, Any]] = []
    for idx, source in enumerate(source_tables):
        if isinstance(source, dict):
            source_name = (source.get("output_name") or source.get("table_name") or f"dataset_{idx + 1}").strip()
            original_query = (source.get("custom_query") or "").strip()
            table_name = (source.get("table_name") or "").strip() or None
            source_sync_column = (source.get("sync_column") or req.sync_column or db_sync_column or "").strip() or None
        else:
            source_label = str(source).strip()
            source_name = source_label or f"dataset_{idx + 1}"
            original_query = ""
            table_name = None if source_label.lower().startswith("dataset_") else source_label
            source_sync_column = (req.sync_column or db_sync_column or "").strip() or None

        if not original_query:
            if table_name and source_sync_column:
                original_query = f"SELECT * FROM {table_name} WHERE {source_sync_column} > {{{{LAST_SYNC_VALUE}}}}"
            elif table_name and sync_mode_type == 'flag':
                # In flag mode with table sources, user is expected to maintain filtering logic upstream.
                # Keep query executable without forcing full-table overwrite.
                original_query = f"SELECT * FROM {table_name}"
            else:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Source '{source_name}' is missing delta criteria. Provide sync_column or a custom query "
                        "with {{LAST_SYNC_VALUE}} (or use flag-mode query filters)."
                    ),
                )

        source_specs.append(
            {
                "source_name": source_name,
                "original_query": original_query,
                "sync_column": source_sync_column,
                "target_table": target_by_source.get(source_name) or target_table_name,
            }
        )

    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id is required for delta sync")

    cached = _get_or_restore_connector(connection_id, str(created_by))
        
    connector = cached["connector"]
    config = cached.get("config")

    schema_name = get_workspace_schema_name(workspace_id)
    
    loader = ETLLoader(db)
    datasets: list[dict[str, str]] = []
    hwm_values: Dict[str, str] = {}

    for spec in source_specs:
        query = spec["original_query"]
        sync_col = spec["sync_column"]
        target_for_hwm = spec["target_table"]

        if "{{LAST_SYNC_VALUE}}" in query:
            if not sync_col:
                match = re.search(
                    r'([A-Za-z0-9_]+)\s*(>|<|=|>=|<=)\s*[\'\"]*\{\{\s*LAST_SYNC_VALUE\s*\}\}[\'\"]*',
                    query,
                    re.IGNORECASE,
                )
                if match:
                    sync_col = match.group(1)
                    spec["sync_column"] = sync_col

            if not sync_col:
                raise HTTPException(status_code=400, detail=f"Sync column not found for source '{spec['source_name']}' while using {{LAST_SYNC_VALUE}}.")

            current_max = None
            if target_for_hwm:
                current_max = loader.get_max_value(target_for_hwm, sync_col, schema_name)

            if current_max is not None:
                val = str(current_max)
            else:
                is_time = sync_col and any(w in sync_col.lower() for w in ['date', 'time', 'at', 'stamp', 'created', 'updated'])
                val = "1970-01-01 00:00:00" if is_time else "0"

            query = re.sub(r"['\"]?\{\{\s*LAST_SYNC_VALUE\s*\}\}['\"]?", f"'{val}'", query, flags=re.IGNORECASE)
            hwm_values[spec["source_name"]] = str(current_max) if current_max is not None else val

        datasets.append({"custom_query": query, "output_name": spec["source_name"]})

    # Persist inferred sync column from LAST_SYNC_VALUE query for future runs.
    if not db_sync_column:
        inferred = next((s.get("sync_column") for s in source_specs if s.get("sync_column")), None)
        if inferred:
            with db.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("UPDATE etl_system.etl_jobs SET sync_column = %s WHERE job_id = %s", (inferred, job_id))
                conn.commit()
    
    work_dir = tempfile.mkdtemp(prefix=f"etl_sync_{job_id[:8]}_")
    try:
        input_dir = os.path.join(work_dir, "input")
        output_dir = os.path.join(work_dir, "output")
        script_path = os.path.join(work_dir, "transform.py")
        os.makedirs(input_dir, exist_ok=True)

        # 1. EXTRACT NEW DATA with dynamic queries (supports multi-source pipelines)
        connector.extract_to_parquet(
            table_names=[],
            datasets=datasets,
            output_dir=input_dir,
        )

        # 2. TRANSFORM
        base_script = transform_script or (
            "import pandas as pd\n"
            "from typing import Dict\n\n"
            "def transform(tables: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:\n"
            "    return tables\n"
        )
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(base_script)

        executor = ETLExecutor()
        result = executor.run_transform(
            input_dir=input_dir,
            output_dir=output_dir,
            script_path=script_path,
        )

        if not result.success:
            error_msg = result.stderr or "Transform failed with no error message"
            raise HTTPException(status_code=400, detail=f"Transform failure: {error_msg}")

        # Preview transformed rows before loading when requested by user.
        preview_tables: list[dict[str, Any]] = []
        total_new_rows = 0
        output_path = Path(output_dir)
        for pq_file in sorted(output_path.glob("*.parquet")):
            df = pd.read_parquet(pq_file, engine="pyarrow")
            row_count = int(len(df.index))
            total_new_rows += row_count
            preview_tables.append(
                {
                    "table_name": pq_file.stem,
                    "row_count": row_count,
                    "columns": [str(col) for col in list(df.columns)],
                    "preview": _build_preview_records(df),
                }
            )

        if req.preview_only:
            return ETLSyncUpdateResponse(
                success=True,
                loaded_tables=[],
                message=(
                    "No new rows found for this delta run."
                    if total_new_rows == 0
                    else f"Found {total_new_rows} new rows across {len(preview_tables)} table(s). Review and continue to load."
                ),
                preview_tables=preview_tables,
                total_new_rows=total_new_rows,
                requires_confirmation=total_new_rows > 0,
            )
            
        # 3. LOAD (APPEND)
        # For multi-output pipelines, do not force all outputs into a single target table.
        load_target_table = target_table_name if len(preview_tables) <= 1 else None
        loaded_tables = loader.load_to_postgres(
            parquet_dir=output_dir,
            user_id=created_by,
            job_id=job_id,
            replace=False,  # Append mode
            target_table_name=load_target_table,
            schema_name=schema_name,
            primary_keys=primary_keys
        )

        row_count = sum(t.get("row_count", 0) for t in loaded_tables)
        
        # 4. Update the high-water mark for next time automatically
        hwm_updated_value = None
        effective_sync_column = actual_sync_column or next((s.get("sync_column") for s in source_specs if s.get("sync_column")), None)
        if effective_sync_column and target_table_name:
            new_max = loader.get_max_value(target_table_name, effective_sync_column, schema_name)
            if new_max is not None:
                hwm_updated_value = str(new_max)
                with db.get_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "UPDATE etl_system.etl_jobs SET high_water_mark = %s WHERE job_id = %s",
                            (hwm_updated_value, job_id)
                        )
                    conn.commit()

        # Keep pipeline metadata fresh for UI visibility.
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE etl_system.etl_jobs SET output_tables = %s, completed_at = %s WHERE job_id = %s",
                    (json.dumps(loaded_tables), datetime.utcnow(), job_id),
                )
            conn.commit()

        return ETLSyncUpdateResponse(
            success=True,
            loaded_tables=loaded_tables,
            preview_tables=preview_tables,
            total_new_rows=row_count,
            requires_confirmation=False,
            message=(
                f"Sync successful! Appended {row_count} new rows. Last sync updated to {hwm_updated_value}."
                if effective_sync_column and hwm_updated_value is not None else
                f"Sync successful! Appended {row_count} new rows."
            )
        )

    except HTTPException:
        raise
    except pd.errors.DatabaseError as e:
        # Source-side SQL errors should be exposed as 400 with actionable context.
        log_full_exception(e, "Sync SQL execution failed")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        log_full_exception(e, "Sync failed")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

# ═══════════════════════════════════════════════════════════════════════════
# GET /api/etl/connections
# ═══════════════════════════════════════════════════════════════════════════
@router.get("/connections", response_model=ETLConnectionListResponse)
async def etl_list_connections(
    current_user: dict = Depends(get_current_user),
):
    """List all saved ETL connections for the current user."""
    db = _get_db()
    user_id = str(current_user.get("id", ""))

    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT connection_id, name, db_type, host, port, database_name,
                       created_at, last_used_at
                  FROM etl_system.etl_connections
                WHERE created_by = %s
                ORDER BY created_at DESC
                """,
                (user_id,),
            )
            rows = cur.fetchall()

    connections = [
        ETLConnectionInfo(
            connection_id=r[0],
            name=r[1],
            db_type=r[2],
            host=r[3],
            port=r[4],
            database_name=r[5],
            created_at=str(r[6]) if r[6] else None,
            last_used_at=str(r[7]) if r[7] else None,
        )
        for r in rows
    ]

    return ETLConnectionListResponse(connections=connections)


# ═══════════════════════════════════════════════════════════════════════════
# DELETE /api/etl/connections/{connection_id}
# ═══════════════════════════════════════════════════════════════════════════
@router.delete("/connections/{connection_id}")
async def etl_delete_connection(
    connection_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Remove a saved ETL connection."""
    db = _get_db()
    user_id = str(current_user.get("id", ""))

    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM etl_system.etl_connections WHERE connection_id = %s AND created_by = %s",
                (connection_id, user_id),
            )
            deleted = cur.rowcount
        conn.commit()

    # Also remove from in-memory cache
    _active_connectors.pop(connection_id, None)

    if deleted == 0:
        raise HTTPException(status_code=404, detail="Connection not found or not owned by you")

    return {"message": "Connection deleted", "connection_id": connection_id}


# ═══════════════════════════════════════════════════════════════════════════
# GET /api/etl/datasets
# ═══════════════════════════════════════════════════════════════════════════
@router.get("/datasets", response_model=ETLDatasetListResponse)
async def etl_list_datasets(
    current_user: dict = Depends(get_current_user),
):
    """List all ETL datasets grouped by connection and job."""
    db = _get_db()
    user_id = str(current_user.get("id", ""))

    with db.get_connection() as conn:
        with conn.cursor() as cur:
            # Get connections
            cur.execute(
                """
                SELECT connection_id, name, db_type, database_name
                FROM etl_system.etl_connections
                WHERE created_by = %s
                ORDER BY created_at DESC
                """,
                (user_id,),
            )
            conns = cur.fetchall()

            # Get jobs
            cur.execute(
                """
                SELECT job_id, connection_id, status, started_at, completed_at
                FROM etl_system.etl_jobs
                WHERE created_by = %s
                ORDER BY created_at DESC
                """,
                (user_id,),
            )
            jobs = cur.fetchall()

            # Get tables
            cur.execute(
                """
                SELECT t.table_id, t.job_id, t.table_name, t.source_name, t.row_count, t.column_stats, t.created_at
                FROM etl_system.etl_tables t
                JOIN etl_system.etl_jobs j ON t.job_id = j.job_id
                WHERE j.created_by = %s
                ORDER BY t.table_name ASC
                """,
                (user_id,),
            )
            tables = cur.fetchall()

    tables_by_job = {}
    for t in tables:
        (table_id, job_id, table_name, source_name, row_count, column_stats, created_at) = t
        if job_id not in tables_by_job:
            tables_by_job[job_id] = []
        tables_by_job[job_id].append(ETLDatasetTable(
            table_id=table_id,
            table_name=table_name,
            source_name=source_name,
            row_count=row_count,
            column_stats=column_stats if isinstance(column_stats, dict) else (json.loads(column_stats) if column_stats else None),
            created_at=str(created_at) if created_at else None
        ))

    jobs_by_conn = {}
    for j in jobs:
        (job_id, connection_id, status, started_at, completed_at) = j
        if connection_id not in jobs_by_conn:
            jobs_by_conn[connection_id] = []
        jobs_by_conn[connection_id].append(ETLDatasetJob(
            job_id=job_id,
            status=status,
            started_at=str(started_at) if started_at else None,
            completed_at=str(completed_at) if completed_at else None,
            tables=tables_by_job.get(job_id, [])
        ))

    response_conns = []
    for c in conns:
        (connection_id, name, db_type, database_name) = c
        c_jobs = jobs_by_conn.get(connection_id, [])
        # Include if has any tables
        if any(j.tables for j in c_jobs):
            response_conns.append(ETLDatasetConnection(
                connection_id=connection_id,
                name=name,
                db_type=db_type,
                database_name=database_name,
                jobs=[j for j in c_jobs if j.tables]
            ))

    return ETLDatasetListResponse(connections=response_conns)


# ═══════════════════════════════════════════════════════════════════════════
# Background ETL Pipeline
# ═══════════════════════════════════════════════════════════════════════════
def _update_job_status(
    job_id: str,
    status: str,
    error_message: str = None,
    output_tables: list = None,
) -> None:
    """Update the ETL job status in the database."""
    db = _get_db()
    
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            if status in ("complete", "failed"):
                cur.execute(
                    """
                    UPDATE etl_system.etl_jobs
                    SET status = %s, error_message = %s, output_tables = %s, completed_at = %s
                    WHERE job_id = %s
                    """,
                    (status, error_message,
                     json.dumps(output_tables) if output_tables else None,
                     datetime.utcnow(), job_id),
                )
            else:
                cur.execute(
                    "UPDATE etl_system.etl_jobs SET status = %s WHERE job_id = %s",
                    (status, job_id),
                )
        conn.commit()


def _auto_profile_workspace_tables(
    db: DatabaseManager,
    workspace_id: str,
    loaded_tables: list[dict[str, Any]],
) -> None:
    """Auto-profile newly loaded workspace tables to populate schema_info and schema embeddings."""
    if not workspace_id or not loaded_tables:
        logger.info(
            "[ETL] Auto-profile skipped | workspace_id=%s | reason=no workspace or no loaded tables",
            workspace_id,
        )
        return

    try:
        from app.core.agents.profiler import ProfilerAgent
    except Exception as e:
        logger.warning("[ETL] Skipping auto-profile: ProfilerAgent import failed: %s", e)
        return

    embed_model = None
    try:
        from app.core.llm import create_workspace_llm
        _, embed_model = create_workspace_llm()
    except Exception as e:
        logger.warning("[ETL] Embedding model unavailable for auto-profile: %s", e)

    logger.info(
        "[ETL] Auto-profile started | workspace_id=%s | loaded_tables=%d | embeddings_enabled=%s",
        workspace_id,
        len(loaded_tables),
        bool(embed_model),
    )

    profiler = ProfilerAgent(db=db, llm=None, embed_model=embed_model)
    success_count = 0
    fail_count = 0

    for tbl in loaded_tables:
        schema_name = tbl.get("schema_name")
        table_name = tbl.get("table_name")
        if not schema_name or not table_name:
            logger.warning(
                "[ETL] Auto-profile skip row | workspace_id=%s | missing schema_name/table_name | row=%s",
                workspace_id,
                tbl,
            )
            continue

        try:
            profiler.profile_table(workspace_id=workspace_id, schema_name=schema_name, table_name=table_name)
            success_count += 1
            logger.info(
                "[ETL] Auto-profiled table after load | workspace_id=%s | schema=%s | table=%s",
                workspace_id,
                schema_name,
                table_name,
            )
        except Exception as e:
            fail_count += 1
            logger.warning(
                "[ETL] Auto-profile failed for %s.%s (workspace=%s): %s",
                schema_name,
                table_name,
                workspace_id,
                e,
            )

    logger.info(
        "[ETL] Auto-profile completed | workspace_id=%s | success=%d | failed=%d",
        workspace_id,
        success_count,
        fail_count,
    )


def _run_full_etl_pipeline(
    job_id: str,
    connection_id: str,
    table_names: list,
    datasets: list[dict[str, str]] | None,
    transform_script: str,
    user_id: str,
    target_table: str | None = None,
    pipeline_name: str | None = None,
    sync_mode: str = "overwrite",
    workspace_id: str | None = None,
    primary_keys: list[str] | None = None,
) -> None:
    """
    Full ETL pipeline executed as a background task.
    Extract → Transform (sandbox) → Load (PostgreSQL).
    """
    work_dir = tempfile.mkdtemp(prefix=f"etl_job_{job_id[:8]}_")

    try:
        try:
            cached = _get_or_restore_connector(connection_id, user_id)
        except HTTPException as e:
            _update_job_status(job_id, "failed", error_message=e.detail)
            return

        connector = cached["connector"]
        config = cached.get("config")
        if not workspace_id:
            raise HTTPException(status_code=400, detail="workspace_id is required for ETL execution")
        schema_name = get_workspace_schema_name(workspace_id)

        input_dir = os.path.join(work_dir, "input")
        output_dir = os.path.join(work_dir, "output")
        script_path = os.path.join(work_dir, "transform.py")

        # ── Phase 1: EXTRACT ─────────────────────────────────────────
        logger.info("[ETL Job %s] Phase 1: Extracting datasets...", job_id[:8])
        _update_job_status(job_id, "extracting")

        if datasets:
            for d in datasets:
                if "custom_query" in d and d["custom_query"]:
                    is_time = any(w in d["custom_query"].lower() for w in ['date', 'time', 'at', 'stamp', 'created', 'updated'])
                    val = "1970-01-01 00:00:00" if is_time else "0"
                    d["custom_query"] = re.sub(r"['\"]?\{\{\s*LAST_SYNC_VALUE\s*\}\}['\"]?", f"'{val}'", d["custom_query"], flags=re.IGNORECASE)

        connector.extract_to_parquet(
            table_names=table_names,
            datasets=datasets,
            output_dir=input_dir,
        )

        # ── Phase 2: TRANSFORM ───────────────────────────────────────
        logger.info("[ETL Job %s] Phase 2: Running transform...", job_id[:8])
        _update_job_status(job_id, "transforming")

        with open(script_path, "w", encoding="utf-8") as f:
            f.write(transform_script)

        executor = ETLExecutor()
        result = executor.run_transform(
            input_dir=input_dir,
            output_dir=output_dir,
            script_path=script_path,
        )

        if not result.success:
            error_msg = result.stderr or "Transform failed with no error message"
            if result.timed_out:
                error_msg = f"Transform timed out after {executor.timeout}s. Check for infinite loops."
            _update_job_status(job_id, "failed", error_message=error_msg)
            return

        # ── Phase 3: LOAD ────────────────────────────────────────────
        logger.info("[ETL Job %s] Phase 3: Loading to PostgreSQL...", job_id[:8])
        _update_job_status(job_id, "loading")

        db = _get_db()
        loader = ETLLoader(db)

        replace = sync_mode.lower() == "overwrite"

        loaded_tables = loader.load_to_postgres(
            parquet_dir=output_dir,
            user_id=user_id,
            job_id=job_id,
            replace=replace,
            target_table_name=target_table,
            schema_name=schema_name,
            workspace_id=workspace_id,
            primary_keys=primary_keys,
        )

        logger.info(
            "[ETL Job %s] Load phase output | workspace_id=%s | loaded_tables=%s",
            job_id[:8],
            workspace_id,
            [t.get("table_name") for t in loaded_tables],
        )

        if workspace_id:
            _auto_profile_workspace_tables(db=db, workspace_id=workspace_id, loaded_tables=loaded_tables)

        # ── Mark job complete FIRST so frontend stops polling immediately ──
        _update_job_status(job_id, "complete", output_tables=loaded_tables)
        logger.info(
            "[ETL Job %s] ✅ Pipeline complete! Loaded %d table(s)",
            job_id[:8], len(loaded_tables),
        )

        # Update connection last_used_at
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE etl_system.etl_connections SET last_used_at = %s WHERE connection_id = %s",
                    (datetime.utcnow(), connection_id),
                )
            conn.commit()

        # ── Dashboard generation deferred until user clicks Board tab ──
        # (removed auto-trigger to reduce pipeline latency — dashboard is
        #  auto-generated on first GET /api/workspaces/{id}/dashboard)

    except Exception as e:
        log_full_exception(e, f"ETL Job {job_id[:8]} failed")
        _update_job_status(job_id, "failed", error_message=str(e))

    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


@router.post("/sync-update", response_model=ETLSyncUpdateResponse)
async def etl_sync_update(
    req: ETLSyncUpdateRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Sync changes from source DB into an existing destination table using append mode.
    """
    cached = _get_or_restore_connector(req.connection_id, str(current_user.get("id", "")))

    connector = cached["connector"]
    user_id = str(current_user.get("id", ""))
    if not req.workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id is required for sync update")

    schema_name = get_workspace_schema_name(req.workspace_id)
    normalized_datasets = _normalize_extract_datasets(req.table_names, req.datasets)
    if not normalized_datasets:
        raise HTTPException(status_code=400, detail="No extract dataset provided")

    work_dir = tempfile.mkdtemp(prefix="etl_sync_update_")
    try:
        input_dir = os.path.join(work_dir, "input")
        output_dir = os.path.join(work_dir, "output")
        script_path = os.path.join(work_dir, "transform.py")

        os.makedirs(input_dir, exist_ok=True)
        connector.extract_to_parquet(
            table_names=[d["table_name"] for d in normalized_datasets if d.get("table_name")],
            datasets=normalized_datasets,
            output_dir=input_dir,
        )

        transform_script = req.transform_script or (
            "import pandas as pd\n"
            "from typing import Dict\n\n"
            "def transform(tables: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:\n"
            "    return tables\n"
        )
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(transform_script)

        executor = ETLExecutor()
        result = executor.run_transform(
            input_dir=input_dir,
            output_dir=output_dir,
            script_path=script_path,
        )
        if not result.success:
            raise HTTPException(status_code=400, detail=result.stderr or "Sync transform failed")

        db = _get_db()
        loader = ETLLoader(db)
        sync_job_id = str(uuid.uuid4())
        loaded_tables = loader.load_to_postgres(
            parquet_dir=output_dir,
            user_id=user_id,
            job_id=sync_job_id,
            replace=False,
            target_table_name=req.target_table_name,
            schema_name=schema_name,
            workspace_id=req.workspace_id,
        )

        with db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE etl_system.etl_connections SET last_used_at = %s WHERE connection_id = %s",
                    (datetime.utcnow(), req.connection_id),
                )
            conn.commit()

        # Dashboard generation deferred to user clicking Board tab

        return ETLSyncUpdateResponse(
            success=True,
            loaded_tables=loaded_tables,
            message="Sync update completed",
        )
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)



# ═══════════════════════════════════════════════════════════════════════════
# POST /api/etl/generate-transform
# ═══════════════════════════════════════════════════════════════════════════
@router.post("/generate-transform", response_model=ETLGenerateTransformResponse)
async def generate_transform(
    req: ETLGenerateTransformRequest,
    current_user: dict = Depends(get_current_user),
):
    try:
        from langchain_openai import ChatOpenAI
        llm = ChatOpenAI(temperature=0.2, model="gpt-4o")
        
        system_prompt = """You are a Python data engineering expert. Produce only valid Python code.

The user is building an ETL pipeline. They need a transform script.
The script must have this exact signature:
```python
import pandas as pd
from typing import Dict

def transform(tables: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
    # Your transformation logic goes here
    
    return tables
```

Available tables:
{tables}

User instructions: {prompt}

Return ONLY the python code. No markdown formatting, no explanations.
"""
        table_info = [t.model_dump() if hasattr(t, 'model_dump') else t.dict() for t in req.tables]
        table_str = json.dumps(table_info, indent=2)
        
        messages = [
            ("system", system_prompt.replace("{tables}", table_str).replace("{prompt}", req.prompt))
        ]
        
        response = llm.invoke(messages)
        code = response.content.replace("```python\n", "").replace("```", "").strip()
        
        return ETLGenerateTransformResponse(script=code)
    except Exception as e:
        logger.error(f"Error generating transform: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate Python script")


# ═══════════════════════════════════════════════════════════════════════════
# PATCH /api/etl/job/{job_id}/sync-config
# ═══════════════════════════════════════════════════════════════════════════
from pydantic import BaseModel as _PydanticBaseModel

class _SyncConfigRequest(_PydanticBaseModel):
    sync_column: str | None = None
    sync_mode_type: str | None = None  # 'hwm' | 'flag'
    pipeline_name: str | None = None

@router.patch("/job/{job_id}/sync-config")
async def etl_update_sync_config(
    job_id: str,
    req: _SyncConfigRequest,
    current_user: dict = Depends(get_current_user),
):
    """Update sync_column and/or sync_mode_type on an existing pipeline job."""
    db = _get_db()
    user_id = str(current_user.get("id", ""))

    updates = []
    params = []
    if req.sync_column is not None:
        updates.append("sync_column = %s")
        params.append(req.sync_column)
    if req.sync_mode_type is not None:
        if req.sync_mode_type not in ('hwm', 'flag'):
            raise HTTPException(status_code=400, detail="sync_mode_type must be 'hwm' or 'flag'")
        updates.append("sync_mode_type = %s")
        params.append(req.sync_mode_type)
    if req.pipeline_name is not None:
        updates.append("pipeline_name = %s")
        params.append(req.pipeline_name)

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    params.extend([job_id, user_id])
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE etl_system.etl_jobs SET {', '.join(updates)} WHERE job_id = %s AND created_by = %s",
                tuple(params),
            )
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="Pipeline not found")
        conn.commit()

    return {"message": "Sync config updated", "job_id": job_id}


# ═══════════════════════════════════════════════════════════════════════════
# GET /api/etl/job/{job_id}/detail
# ═══════════════════════════════════════════════════════════════════════════
@router.get("/job/{job_id}/detail")
async def etl_get_job_detail(
    job_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Return all configuration fields for a pipeline job (used to pre-fill the edit wizard)."""
    db = _get_db()
    user_id = str(current_user.get("id", ""))

    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT job_id, connection_id, source_tables, transform_script,
                       target_table, sync_mode, sync_column, sync_mode_type, workspace_id, pipeline_name, primary_keys
                FROM etl_system.etl_jobs
                WHERE job_id = %s AND created_by = %s
                """,
                (job_id, user_id),
            )
            row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Pipeline not found")

    source_tables = row[2]
    if isinstance(source_tables, str):
        try:
            source_tables = json.loads(source_tables)
        except Exception:
            source_tables = []

    return {
        "job_id": row[0],
        "connection_id": row[1],
        "source_tables": source_tables,
        "transform_script": row[3],
        "target_table": row[4],
        "sync_mode": row[5],
        "sync_column": row[6],
        "sync_mode_type": row[7] or 'hwm',
        "workspace_id": row[8],
        "pipeline_name": row[9],
        "primary_keys": row[10] if isinstance(row[10], list) else (json.loads(row[10]) if row[10] else []),
    }


# ═══════════════════════════════════════════════════════════════════════════
# PUT /api/etl/job/{job_id}
# ═══════════════════════════════════════════════════════════════════════════
class _UpdateJobRequest(_PydanticBaseModel):
    source_tables: list | None = None
    transform_script: str | None = None
    target_table: str | None = None
    sync_mode: str | None = None
    sync_column: str | None = None
    sync_mode_type: str | None = None
    pipeline_name: str | None = None
    primary_keys: list | None = None

@router.put("/job/{job_id}")
async def etl_update_job(
    job_id: str,
    req: _UpdateJobRequest,
    current_user: dict = Depends(get_current_user),
):
    """Update an existing pipeline job's configuration in-place (without re-running)."""
    db = _get_db()
    user_id = str(current_user.get("id", ""))

    updates = []
    params = []
    if req.source_tables is not None:
        updates.append("source_tables = %s")
        params.append(json.dumps(req.source_tables))
    if req.transform_script is not None:
        updates.append("transform_script = %s")
        params.append(req.transform_script)
    if req.target_table is not None:
        updates.append("target_table = %s")
        params.append(req.target_table)
    if req.sync_mode is not None:
        updates.append("sync_mode = %s")
        params.append(req.sync_mode)
    if req.sync_column is not None:
        updates.append("sync_column = %s")
        params.append(req.sync_column)
    if req.sync_mode_type is not None:
        if req.sync_mode_type not in ('hwm', 'flag'):
            raise HTTPException(status_code=400, detail="sync_mode_type must be 'hwm' or 'flag'")
        updates.append("sync_mode_type = %s")
        params.append(req.sync_mode_type)
    if req.primary_keys is not None:
        updates.append("primary_keys = %s")
        params.append(json.dumps(req.primary_keys))

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    params.extend([job_id, user_id])
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE etl_system.etl_jobs SET {', '.join(updates)} WHERE job_id = %s AND created_by = %s",
                tuple(params),
            )
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="Pipeline not found")
        conn.commit()

    return {"message": "Pipeline updated", "job_id": job_id}
