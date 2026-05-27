"""
Workspace Router — API endpoints for Workspace + Semantic Layer management.

Endpoints:
  POST   /api/workspaces                          — Create workspace
  GET    /api/workspaces                          — List user workspaces
  GET    /api/workspaces/{workspace_id}           — Get workspace detail + tables
  DELETE /api/workspaces/{workspace_id}           — Delete workspace

  GET    /api/workspaces/{workspace_id}/tables     — List tables in workspace
  PATCH  /api/workspaces/{workspace_id}/tables/{table_name}/description — Update table description
  GET    /api/workspaces/{workspace_id}/tables/{table_name}/columns     — List columns
  PATCH  /api/workspaces/{workspace_id}/columns/{column_id}/description — Update column description

  GET    /api/workspaces/{workspace_id}/semantic   — Get full semantic layer
  POST   /api/workspaces/{workspace_id}/semantic/metrics    — Create metric
  POST   /api/workspaces/{workspace_id}/semantic/dimensions — Create dimension
  POST   /api/workspaces/{workspace_id}/semantic/synonyms   — Create synonym
  DELETE /api/workspaces/{workspace_id}/semantic/metrics/{metric_id}
  DELETE /api/workspaces/{workspace_id}/semantic/dimensions/{dimension_id}
  DELETE /api/workspaces/{workspace_id}/semantic/synonyms/{synonym_id}
"""
from __future__ import annotations

import json
import uuid
from typing import Any, List, Optional, Dict
from pydantic import BaseModel

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from psycopg2.extras import RealDictCursor, Json

from app.core.auth import get_current_user
from app.core.database import DatabaseManager
from app.core.schema_utils import get_workspace_schema_name
from app.schemas.workspace import (
    WorkspaceCreateRequest,
    WorkspaceUpdateRequest,
    WorkspaceResponse,
    WorkspaceListResponse,
    WorkspaceDetailResponse,
    TableMetadataResponse,
    ColumnMetadataResponse,
    UpdateTableDescriptionRequest,
    UpdateColumnDescriptionRequest,
    SemanticMetricRequest,
    SemanticMetricResponse,
    SemanticDimensionRequest,
    SemanticDimensionResponse,
    SemanticSynonymRequest,
    SemanticSynonymResponse,
    SemanticLayerResponse,
)
from app.utils.logging import logger, log_full_exception

router = APIRouter(prefix="/api/workspaces", tags=["Workspaces"])


def _get_db() -> DatabaseManager:
    return DatabaseManager()


# ═══════════════════════════════════════════════════════════════════════════
# WORKSPACE CRUD
# ═══════════════════════════════════════════════════════════════════════════

@router.post("", response_model=WorkspaceResponse)
async def create_workspace(
    req: WorkspaceCreateRequest,
    current_user: dict = Depends(get_current_user),
):
    """Create a new workspace with its own PostgreSQL schema."""
    db = _get_db()
    user_id = str(current_user.get("id", ""))
    workspace_id = str(uuid.uuid4())
    schema_name = get_workspace_schema_name(workspace_id)

    try:
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                # Create the physical schema
                cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema_name}";')

                # Grant read-only access to the AI role
                import os
                readonly_user = os.getenv("ETL_READONLY_USER", "ai_readonly")
                try:
                    cur.execute(f'GRANT USAGE ON SCHEMA "{schema_name}" TO "{readonly_user}";')
                except Exception:
                    pass

                # Register in etl_system.workspaces
                cur.execute(
                    """
                    INSERT INTO etl_system.workspaces
                        (workspace_id, name, schema_name, description, created_by)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (workspace_id, req.name, schema_name, req.description, user_id),
                )
            conn.commit()

        logger.info("[Workspace] ✅ Created workspace '%s' (schema=%s)", req.name, schema_name)

        return WorkspaceResponse(
            workspace_id=workspace_id,
            name=req.name,
            schema_name=schema_name,
            description=req.description,
            created_by=user_id,
            table_count=0,
        )
    except Exception as e:
        log_full_exception(e, "Workspace creation failed")
        raise HTTPException(status_code=500, detail=f"Failed to create workspace: {str(e)}")


@router.get("", response_model=WorkspaceListResponse)
async def list_workspaces(
    current_user: dict = Depends(get_current_user),
):
    """List all workspaces for the current user."""
    db = _get_db()
    user_id = str(current_user.get("id", ""))

    with db.get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT w.workspace_id, w.name, w.schema_name, w.description,
                       w.created_by, w.created_at::text as created_at,
                       COUNT(tm.metadata_id) as table_count
                FROM etl_system.workspaces w
                LEFT JOIN etl_system.tables_metadata tm ON tm.workspace_id = w.workspace_id
                WHERE w.created_by = %s
                GROUP BY w.workspace_id, w.name, w.schema_name, w.description,
                         w.created_by, w.created_at
                ORDER BY w.created_at DESC
                """,
                (user_id,),
            )
            rows = cur.fetchall()

    workspaces = [
        WorkspaceResponse(
            workspace_id=r["workspace_id"],
            name=r["name"],
            schema_name=r["schema_name"],
            description=r["description"],
            created_by=r["created_by"],
            created_at=r["created_at"],
            table_count=r["table_count"],
        )
        for r in rows
    ]

    return WorkspaceListResponse(workspaces=workspaces)


@router.get("/{workspace_id}", response_model=WorkspaceDetailResponse)
async def get_workspace_detail(
    workspace_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Get workspace detail with all tables and their column metadata."""
    db = _get_db()
    user_id = str(current_user.get("id", ""))

    with db.get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Fetch workspace
            cur.execute(
                """
                SELECT workspace_id, name, schema_name, description,
                       created_by, created_at::text as created_at
                FROM etl_system.workspaces
                WHERE workspace_id = %s AND created_by = %s
                """,
                (workspace_id, user_id),
            )
            ws = cur.fetchone()
            if not ws:
                raise HTTPException(status_code=404, detail="Workspace not found")

            # Fetch tables
            cur.execute(
                """
                SELECT metadata_id, table_name, schema_name, description, row_count
                FROM etl_system.tables_metadata
                WHERE workspace_id = %s
                ORDER BY table_name
                """,
                (workspace_id,),
            )
            tables_raw = cur.fetchall()

            # Fetch columns per table
            cur.execute(
                """
                SELECT column_id, table_name, column_name, data_type,
                       description, sample_values, stats
                FROM etl_system.columns_metadata
                WHERE workspace_id = %s
                ORDER BY table_name, column_name
                """,
                (workspace_id,),
            )
            columns_raw = cur.fetchall()

    # Group columns by table
    columns_by_table: dict[str, list] = {}
    for c in columns_raw:
        t = c["table_name"]
        if t not in columns_by_table:
            columns_by_table[t] = []
        columns_by_table[t].append(
            ColumnMetadataResponse(
                column_id=c["column_id"],
                column_name=c["column_name"],
                data_type=c["data_type"],
                description=c["description"],
                sample_values=c["sample_values"] if isinstance(c["sample_values"], list) else (json.loads(c["sample_values"]) if c["sample_values"] else None),
                stats=c["stats"] if isinstance(c["stats"], dict) else (json.loads(c["stats"]) if c["stats"] else None),
            )
        )

    tables = [
        TableMetadataResponse(
            metadata_id=t["metadata_id"],
            table_name=t["table_name"],
            schema_name=t["schema_name"],
            description=t["description"],
            row_count=t["row_count"],
            columns=columns_by_table.get(t["table_name"], []),
        )
        for t in tables_raw
    ]

    return WorkspaceDetailResponse(
        workspace_id=ws["workspace_id"],
        name=ws["name"],
        schema_name=ws["schema_name"],
        description=ws["description"],
        created_by=ws["created_by"],
        created_at=ws["created_at"],
        table_count=len(tables),
        tables=tables,
    )


@router.patch("/{workspace_id}", response_model=WorkspaceResponse)
async def update_workspace(
    workspace_id: str,
    req: WorkspaceUpdateRequest,
    current_user: dict = Depends(get_current_user),
):
    """Update workspace name and description attributes."""
    db = _get_db()
    user_id = str(current_user.get("id", ""))

    with db.get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT workspace_id, name, schema_name, description, created_by FROM etl_system.workspaces WHERE workspace_id = %s AND created_by = %s",
                (workspace_id, user_id),
            )
            ws = cur.fetchone()
            if not ws:
                raise HTTPException(status_code=404, detail="Workspace not found")

            new_name = req.name if req.name is not None else ws["name"]
            new_description = req.description if req.description is not None else ws["description"]

            cur.execute(
                """
                UPDATE etl_system.workspaces
                SET name = %s, description = %s
                WHERE workspace_id = %s
                """,
                (new_name, new_description, workspace_id),
            )

            cur.execute(
                """
                SELECT COUNT(tm.metadata_id) as table_count
                FROM etl_system.tables_metadata tm
                WHERE tm.workspace_id = %s
                """,
                (workspace_id,),
            )
            cnt_row = cur.fetchone()
            table_count = cnt_row["table_count"] if cnt_row else 0

        conn.commit()

    logger.info("[Workspace] ✅ Updated workspace '%s' (%s)", workspace_id, new_name)

    return WorkspaceResponse(
        workspace_id=workspace_id,
        name=new_name,
        schema_name=ws["schema_name"],
        description=new_description,
        created_by=user_id,
        table_count=table_count,
    )


@router.delete("/{workspace_id}")
async def delete_workspace(
    workspace_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Delete a workspace and its PostgreSQL schema."""
    db = _get_db()
    user_id = str(current_user.get("id", ""))

    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT schema_name FROM etl_system.workspaces WHERE workspace_id = %s AND created_by = %s",
                (workspace_id, user_id),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Workspace not found")

            schema_name = row[0]

            # Drop all related metadata
            cur.execute("DELETE FROM etl_system.dashboard_widgets WHERE workspace_id = %s", (workspace_id,))
            cur.execute("DELETE FROM etl_system.workspace_dashboards WHERE workspace_id = %s", (workspace_id,))
            cur.execute("DELETE FROM etl_system.semantic_vectors WHERE workspace_id = %s", (workspace_id,))
            cur.execute("DELETE FROM etl_system.semantic_synonyms WHERE workspace_id = %s", (workspace_id,))
            cur.execute("DELETE FROM etl_system.semantic_dimensions WHERE workspace_id = %s", (workspace_id,))
            cur.execute("DELETE FROM etl_system.semantic_metrics WHERE workspace_id = %s", (workspace_id,))
            cur.execute("DELETE FROM etl_system.columns_metadata WHERE workspace_id = %s", (workspace_id,))
            cur.execute("DELETE FROM etl_system.tables_metadata WHERE workspace_id = %s", (workspace_id,))
            cur.execute("DELETE FROM etl_system.workspaces WHERE workspace_id = %s", (workspace_id,))

            # Drop the physical schema
            cur.execute(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE;')
        conn.commit()

    logger.info("[Workspace] 🗑️ Deleted workspace %s (schema=%s)", workspace_id, schema_name)
    return {"message": "Workspace deleted", "workspace_id": workspace_id}


# ═══════════════════════════════════════════════════════════════════════════
# WORKSPACE SHARING
# ═══════════════════════════════════════════════════════════════════════════

@router.post("/{workspace_id}/share/toggle")
async def toggle_workspace_sharing(
    workspace_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Toggle sharing on/off for a workspace. Generates a share_token if needed."""
    db = _get_db()
    user_id = str(current_user.get("id", ""))

    with db.get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT workspace_id, is_shared, share_token FROM etl_system.workspaces WHERE workspace_id = %s AND created_by = %s",
                (workspace_id, user_id),
            )
            ws = cur.fetchone()
            if not ws:
                raise HTTPException(status_code=404, detail="Workspace not found")

            new_is_shared = not ws.get("is_shared", False)
            share_token = ws.get("share_token") or str(uuid.uuid4())

            cur.execute(
                "UPDATE etl_system.workspaces SET is_shared = %s, share_token = %s WHERE workspace_id = %s",
                (new_is_shared, share_token, workspace_id),
            )
        conn.commit()

    logger.info(
        "[Workspace] Sharing %s for workspace %s (token=%s)",
        "enabled" if new_is_shared else "disabled",
        workspace_id,
        share_token if new_is_shared else "N/A",
    )

    return {
        "status": "success",
        "workspace_id": workspace_id,
        "is_shared": new_is_shared,
        "share_token": share_token if new_is_shared else None,
    }


@router.get("/{workspace_id}/share/status")
async def get_workspace_share_status(
    workspace_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Get the current sharing status and token for a workspace."""
    db = _get_db()
    user_id = str(current_user.get("id", ""))

    with db.get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT is_shared, share_token FROM etl_system.workspaces WHERE workspace_id = %s AND created_by = %s",
                (workspace_id, user_id),
            )
            ws = cur.fetchone()
            if not ws:
                raise HTTPException(status_code=404, detail="Workspace not found")

    is_shared = ws.get("is_shared", False)
    return {
        "workspace_id": workspace_id,
        "is_shared": is_shared,
        "share_token": ws.get("share_token") if is_shared else None,
    }

# ═══════════════════════════════════════════════════════════════════════════
# TABLE METADATA
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/{workspace_id}/tables")
async def list_workspace_tables(
    workspace_id: str,
    current_user: dict = Depends(get_current_user),
):
    """List all tables in a workspace with basic metadata."""
    db = _get_db()

    with db.get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Verify ownership
            cur.execute(
                "SELECT 1 FROM etl_system.workspaces WHERE workspace_id = %s AND created_by = %s",
                (workspace_id, str(current_user.get("id", ""))),
            )
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Workspace not found")

            cur.execute(
                """
                SELECT metadata_id, table_name, schema_name, description, row_count,
                       created_at::text as created_at
                FROM etl_system.tables_metadata
                WHERE workspace_id = %s
                ORDER BY table_name
                """,
                (workspace_id,),
            )
            tables = cur.fetchall()

    return {"workspace_id": workspace_id, "tables": tables}


@router.patch("/{workspace_id}/tables/{table_name}/description")
async def update_table_description(
    workspace_id: str,
    table_name: str,
    req: UpdateTableDescriptionRequest,
    current_user: dict = Depends(get_current_user),
):
    """Update a table's business description (user-editable semantic context)."""
    db = _get_db()

    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE etl_system.tables_metadata
                SET description = %s, updated_at = CURRENT_TIMESTAMP
                WHERE workspace_id = %s AND table_name = %s
                """,
                (req.description, workspace_id, table_name),
            )
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="Table not found in workspace")
        conn.commit()

    return {"message": "Description updated", "table_name": table_name}


@router.get("/{workspace_id}/tables/{table_name}/columns")
async def list_table_columns(
    workspace_id: str,
    table_name: str,
    current_user: dict = Depends(get_current_user),
):
    """List columns for a specific table with metadata."""
    db = _get_db()

    with db.get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT column_id, column_name, data_type, description,
                       sample_values, stats
                FROM etl_system.columns_metadata
                WHERE workspace_id = %s AND table_name = %s
                ORDER BY column_name
                """,
                (workspace_id, table_name),
            )
            columns = cur.fetchall()

    return {"workspace_id": workspace_id, "table_name": table_name, "columns": columns}


@router.patch("/{workspace_id}/columns/{column_id}/description")
async def update_column_description(
    workspace_id: str,
    column_id: str,
    req: UpdateColumnDescriptionRequest,
    current_user: dict = Depends(get_current_user),
):
    """Update a column's business description."""
    db = _get_db()

    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE etl_system.columns_metadata
                SET description = %s
                WHERE workspace_id = %s AND column_id = %s
                """,
                (req.description, workspace_id, column_id),
            )
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="Column not found")
        conn.commit()

    return {"message": "Column description updated", "column_id": column_id}


# ═══════════════════════════════════════════════════════════════════════════
# SEMANTIC LAYER CRUD
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/{workspace_id}/semantic", response_model=SemanticLayerResponse)
async def get_semantic_layer(
    workspace_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Get the full semantic layer (metrics + dimensions + synonyms) for a workspace."""
    db = _get_db()

    with db.get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Verify ownership
            cur.execute(
                "SELECT 1 FROM etl_system.workspaces WHERE workspace_id = %s AND created_by = %s",
                (workspace_id, str(current_user.get("id", ""))),
            )
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Workspace not found")

            # Metrics
            cur.execute(
                "SELECT metric_id, workspace_id, name, formula, description, related_tables, created_at::text as created_at FROM etl_system.semantic_metrics WHERE workspace_id = %s ORDER BY name",
                (workspace_id,),
            )
            metrics = [SemanticMetricResponse(**r) for r in cur.fetchall()]

            # Dimensions
            cur.execute(
                "SELECT dimension_id, workspace_id, name, table_name, column_name, description, dim_type, created_at::text as created_at FROM etl_system.semantic_dimensions WHERE workspace_id = %s ORDER BY name",
                (workspace_id,),
            )
            dimensions = [SemanticDimensionResponse(**r) for r in cur.fetchall()]

            # Synonyms
            cur.execute(
                "SELECT synonym_id, workspace_id, keyword, mapped_to, mapped_type, created_at::text as created_at FROM etl_system.semantic_synonyms WHERE workspace_id = %s ORDER BY keyword",
                (workspace_id,),
            )
            synonyms = [SemanticSynonymResponse(**r) for r in cur.fetchall()]

    return SemanticLayerResponse(
        workspace_id=workspace_id,
        metrics=metrics,
        dimensions=dimensions,
        synonyms=synonyms,
    )


# ── Metrics ──

@router.post("/{workspace_id}/semantic/metrics", response_model=SemanticMetricResponse)
async def create_metric(
    workspace_id: str,
    req: SemanticMetricRequest,
    current_user: dict = Depends(get_current_user),
):
    """Create a semantic metric (e.g., Net Revenue = SUM(gross) - SUM(tax))."""
    db = _get_db()
    user_id = str(current_user.get("id", ""))
    metric_id = str(uuid.uuid4())

    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO etl_system.semantic_metrics
                    (metric_id, workspace_id, name, formula, description, related_tables, created_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (metric_id, workspace_id, req.name, req.formula, req.description,
                 req.related_tables, user_id),
            )
        conn.commit()

    return SemanticMetricResponse(
        metric_id=metric_id,
        workspace_id=workspace_id,
        name=req.name,
        formula=req.formula,
        description=req.description,
        related_tables=req.related_tables,
    )


@router.delete("/{workspace_id}/semantic/metrics/{metric_id}")
async def delete_metric(
    workspace_id: str,
    metric_id: str,
    current_user: dict = Depends(get_current_user),
):
    db = _get_db()
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM etl_system.semantic_metrics WHERE metric_id = %s AND workspace_id = %s",
                (metric_id, workspace_id),
            )
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="Metric not found")
        conn.commit()
    return {"message": "Metric deleted", "metric_id": metric_id}


# ── Dimensions ──

@router.post("/{workspace_id}/semantic/dimensions", response_model=SemanticDimensionResponse)
async def create_dimension(
    workspace_id: str,
    req: SemanticDimensionRequest,
    current_user: dict = Depends(get_current_user),
):
    """Create a semantic dimension (e.g., date = orders.created_at)."""
    db = _get_db()
    user_id = str(current_user.get("id", ""))
    dimension_id = str(uuid.uuid4())

    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO etl_system.semantic_dimensions
                    (dimension_id, workspace_id, name, table_name, column_name, description, dim_type, created_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (dimension_id, workspace_id, req.name, req.table_name, req.column_name,
                 req.description, req.dim_type, user_id),
            )
        conn.commit()

    return SemanticDimensionResponse(
        dimension_id=dimension_id,
        workspace_id=workspace_id,
        name=req.name,
        table_name=req.table_name,
        column_name=req.column_name,
        description=req.description,
        dim_type=req.dim_type,
    )


@router.delete("/{workspace_id}/semantic/dimensions/{dimension_id}")
async def delete_dimension(
    workspace_id: str,
    dimension_id: str,
    current_user: dict = Depends(get_current_user),
):
    db = _get_db()
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM etl_system.semantic_dimensions WHERE dimension_id = %s AND workspace_id = %s",
                (dimension_id, workspace_id),
            )
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="Dimension not found")
        conn.commit()
    return {"message": "Dimension deleted", "dimension_id": dimension_id}


# ── Synonyms ──

@router.post("/{workspace_id}/semantic/synonyms", response_model=SemanticSynonymResponse)
async def create_synonym(
    workspace_id: str,
    req: SemanticSynonymRequest,
    current_user: dict = Depends(get_current_user),
):
    """Create a synonym mapping (e.g., sales → revenue_usd)."""
    db = _get_db()
    user_id = str(current_user.get("id", ""))
    synonym_id = str(uuid.uuid4())

    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO etl_system.semantic_synonyms
                    (synonym_id, workspace_id, keyword, mapped_to, mapped_type, created_by)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (synonym_id, workspace_id, req.keyword, req.mapped_to, req.mapped_type, user_id),
            )
        conn.commit()

    return SemanticSynonymResponse(
        synonym_id=synonym_id,
        workspace_id=workspace_id,
        keyword=req.keyword,
        mapped_to=req.mapped_to,
        mapped_type=req.mapped_type,
    )


@router.delete("/{workspace_id}/semantic/synonyms/{synonym_id}")
async def delete_synonym(
    workspace_id: str,
    synonym_id: str,
    current_user: dict = Depends(get_current_user),
):
    db = _get_db()
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM etl_system.semantic_synonyms WHERE synonym_id = %s AND workspace_id = %s",
                (synonym_id, workspace_id),
            )
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="Synonym not found")
        conn.commit()
    return {"message": "Synonym deleted", "synonym_id": synonym_id}


# ═══════════════════════════════════════════════════════════════════════════
# WORKSPACE CHAT (RAG-to-SQL)
# ═══════════════════════════════════════════════════════════════════════════

from pydantic import BaseModel as _BaseModel


class WorkspaceChatRequest(_BaseModel):
    question: str
    session_id: str | None = None
    title: str | None = None


class WorkspaceReportSummarizeRequest(_BaseModel):
    question: str
    sql_query: str
    columns: list[str]
    data: list[dict]

class WorkspaceExecuteSqlRequest(_BaseModel):
    title: str
    sql_query: str


class WorkspacePinWidgetRequest(_BaseModel):
    title: str
    widget_type: str = "table"
    chart_type: str | None = None
    sql_query: str
    config: dict | None = None
    origin_question: str | None = None


class WorkspaceDashboardSaveRequest(_BaseModel):
    name: str | None = None
    layout_json: dict | list | None = None
    widgets: list[dict] | None = None


class WorkspaceWidgetRequest(_BaseModel):
    query: str
    widget_type_hint: str | None = None
    chart_type_hint: str | None = None

class WorkspaceCustomWidgetRequest(_BaseModel):
    title: str
    sql_query: str
    widget_type_hint: str = "chart"
    chart_type_hint: str | None = None

class WorkspaceChartBuilderRequest(_BaseModel):
    chart_type: str
    dimension: str
    measure: str | None = None
    aggregation: str = "sum"


class WorkspaceRelationshipRequest(_BaseModel):
    source_table: str
    source_column: str
    target_table: str
    target_column: str
    relationship_type: str = "foreign_key"


@router.get("/{workspace_id}/chat/history")
async def get_chat_history(
    workspace_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Return the last 50 chat messages for this workspace."""
    db = _get_db()
    user_id = str(current_user.get("id", ""))

    with db.get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Verify ownership
            cur.execute(
                "SELECT 1 FROM etl_system.workspaces WHERE workspace_id = %s AND created_by = %s",
                (workspace_id, user_id),
            )
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Workspace not found")

            cur.execute(
                """
                SELECT id, role, content, sql_query, columns, data, row_count,
                       ai_summary, created_at::text as created_at
                FROM etl_system.workspace_chat_messages
                WHERE workspace_id = %s
                ORDER BY created_at ASC, id ASC
                LIMIT 50
                """,
                (workspace_id,),
            )
            rows = cur.fetchall()

    messages = []
    for i, r in enumerate(rows):
        msg = {
            "id": r["id"],
            "role": r["role"],
            "content": r["content"],
            "created_at": r["created_at"],
        }
        if r["sql_query"]:
            question = None
            if i > 0 and rows[i-1]["role"] == "user":
                question = rows[i-1]["content"]

            msg["chatResponse"] = {
                "sql": r["sql_query"],
                "columns": r["columns"] or [],
                "data": r["data"] or [],
                "row_count": r["row_count"] or 0,
                "ai_summary": r["ai_summary"] or "",
                "question": question,
            }
        messages.append(msg)
    return {"workspace_id": workspace_id, "messages": messages}


@router.delete("/{workspace_id}/chat/history")
async def clear_chat_history(
    workspace_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Clear all chat messages for this workspace."""
    db = _get_db()
    user_id = str(current_user.get("id", ""))

    with db.get_connection() as conn:
        with conn.cursor() as cur:
            # Verify ownership
            cur.execute(
                "SELECT 1 FROM etl_system.workspaces WHERE workspace_id = %s AND created_by = %s",
                (workspace_id, user_id),
            )
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Workspace not found")

            cur.execute(
                "DELETE FROM etl_system.workspace_chat_messages WHERE workspace_id = %s",
                (workspace_id,),
            )
            deleted_count = cur.rowcount

        conn.commit()

    return {
        "workspace_id": workspace_id,
        "deleted_count": deleted_count,
        "message": "Chat history cleared",
    }


@router.delete("/{workspace_id}/chat/history/{message_id}")
async def delete_chat_history_item(
    workspace_id: str,
    message_id: int,
    current_user: dict = Depends(get_current_user),
):
    """Clear a specific chat message for this workspace."""
    db = _get_db()
    user_id = str(current_user.get("id", ""))

    with db.get_connection() as conn:
        with conn.cursor() as cur:
            # Verify ownership
            cur.execute(
                "SELECT 1 FROM etl_system.workspaces WHERE workspace_id = %s AND created_by = %s",
                (workspace_id, user_id),
            )
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Workspace not found")

            cur.execute(
                "DELETE FROM etl_system.workspace_chat_messages WHERE id = %s AND workspace_id = %s",
                (message_id, workspace_id),
            )
            deleted_count = cur.rowcount

        conn.commit()

    if deleted_count == 0:
        raise HTTPException(status_code=404, detail="Message not found")

    return {
        "workspace_id": workspace_id,
        "message_id": message_id,
        "message": "Message deleted",
    }


@router.post("/{workspace_id}/chat")
async def workspace_chat(
    workspace_id: str,
    req: WorkspaceChatRequest,
    current_user: dict = Depends(get_current_user),
):
    """Chat with workspace data using RAG-to-SQL pipeline."""
    db = _get_db()
    user_id = str(current_user.get("id", ""))
    logger.info(
        "[Workspace] Chat request received | workspace_id=%s | user_id=%s | session_id=%s | question=%s",
        workspace_id,
        user_id,
        req.session_id,
        req.question,
    )

    # Verify workspace ownership
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM etl_system.workspaces WHERE workspace_id = %s AND created_by = %s",
                (workspace_id, user_id),
            )
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Workspace not found")

    # Initialize the workspace SQL agent
    from app.core.agents.workspace_sql import WorkspaceSqlAgent

    # Setup LLM + embed model (DRY factory)
    from app.core.llm import create_workspace_llm
    llm, embed_model = create_workspace_llm()

    agent = WorkspaceSqlAgent(
        db=db,
        workspace_id=workspace_id,
        llm=llm,
        embed_model=embed_model,
    )

    result = agent.chat(req.question)
    logger.info(
        "[Workspace] Chat response ready | workspace_id=%s | user_id=%s | status=%s | row_count=%s | sql=%s",
        workspace_id,
        user_id,
        result.get("status"),
        result.get("row_count"),
        result.get("sql"),
    )

    # Persist chat history only if it's explicitly titled (e.g., from Reports)
    if not req.title:
        return result

    try:
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                # Format user message content if title is present
                user_content = f"[Title: {req.title}] {req.question}" if req.title else req.question

                sql_query = result.get("sql")
                existing = None
                
                if sql_query:
                    cur.execute(
                        "SELECT id, created_at FROM etl_system.workspace_chat_messages WHERE workspace_id = %s AND sql_query = %s ORDER BY created_at DESC LIMIT 1",
                        (workspace_id, sql_query)
                    )
                    existing = cur.fetchone()

                if existing:
                    # Update the existing assistant message
                    cur.execute(
                        """
                        UPDATE etl_system.workspace_chat_messages
                        SET content = %s,
                            columns = %s,
                            data = %s,
                            row_count = %s
                        WHERE id = %s
                        """,
                        (
                            result.get("explanation") or result.get("answer") or "",
                            json.dumps(result.get("columns") or []),
                            json.dumps(result.get("data") or [], default=str),
                            result.get("row_count"),
                            existing[0]
                        )
                    )
                    # Update the corresponding user message
                    cur.execute(
                        """
                        UPDATE etl_system.workspace_chat_messages
                        SET content = %s
                        WHERE id = (
                            SELECT id FROM etl_system.workspace_chat_messages
                            WHERE workspace_id = %s AND role = 'user' AND created_at <= %s
                            ORDER BY created_at DESC LIMIT 1
                        )
                        """,
                        (user_content, workspace_id, existing[1])
                    )
                else:
                    # User message
                    cur.execute(
                        """
                        INSERT INTO etl_system.workspace_chat_messages
                            (workspace_id, user_id, role, content)
                        VALUES (%s, %s, 'user', %s)
                        """,
                        (workspace_id, user_id, user_content),
                    )
                    # Assistant message
                    cur.execute(
                        """
                        INSERT INTO etl_system.workspace_chat_messages
                            (workspace_id, user_id, role, content, sql_query, columns, data, row_count)
                        VALUES (%s, %s, 'assistant', %s, %s, %s, %s, %s)
                        """,
                        (
                            workspace_id,
                            user_id,
                            result.get("explanation") or result.get("answer") or "",
                        result.get("sql"),
                            json.dumps(result.get("columns") or []),
                            json.dumps(result.get("data") or [], default=str),
                            result.get("row_count"),
                        ),
                    )
            conn.commit()
    except Exception as e:
        logger.warning("[Workspace] Failed to persist chat history: %s", e)

    return result

@router.post("/{workspace_id}/report/execute_custom_sql")
async def execute_custom_sql(
    workspace_id: str,
    req: WorkspaceExecuteSqlRequest,
    current_user: dict = Depends(get_current_user),
):
    """Execute raw SQL safely against the workspace schema and save history."""
    db = _get_db()
    user_id = str(current_user.get("id", ""))
    
    # Verify workspace ownership
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM etl_system.workspaces WHERE workspace_id = %s AND created_by = %s",
                (workspace_id, user_id),
            )
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Workspace not found")

    from app.core.agents.workspace_sql import WorkspaceSqlAgent
    agent = WorkspaceSqlAgent(db=db, workspace_id=workspace_id)
    
    try:
        # Validate that the query only contains SELECT
        sql_upper = req.sql_query.upper().strip()
        dangerous_keywords = ["DROP", "DELETE", "INSERT", "UPDATE", "ALTER", "CREATE", "TRUNCATE", "GRANT", "REVOKE"]
        for kw in dangerous_keywords:
            if kw in sql_upper.split():
                raise HTTPException(status_code=400, detail=f"SQL query contains forbidden keyword: {kw}")

        if not sql_upper.startswith("SELECT") and not sql_upper.startswith("WITH"):
            raise HTTPException(status_code=400, detail="Only SELECT/WITH queries are allowed")

        results, columns = agent._execute_sql(req.sql_query)
        row_count = len(results)
        
        # Persist chat history so it shows up in the sidebar
        try:
            with db.get_connection() as conn:
                with conn.cursor() as cur:
                    # Check if query already exists to update it instead of creating duplicate
                    cur.execute(
                        "SELECT id, created_at FROM etl_system.workspace_chat_messages WHERE workspace_id = %s AND sql_query = %s ORDER BY created_at DESC LIMIT 1",
                        (workspace_id, req.sql_query)
                    )
                    existing = cur.fetchone()
                    
                    if existing:
                        # Update the existing assistant message
                        cur.execute(
                            """
                            UPDATE etl_system.workspace_chat_messages
                            SET columns = %s,
                                data = %s,
                                row_count = %s
                            WHERE id = %s
                            """,
                            (json.dumps(columns), json.dumps(results, default=str), row_count, existing[0])
                        )
                        # Update the corresponding user message (the one directly preceding it)
                        cur.execute(
                            """
                            UPDATE etl_system.workspace_chat_messages
                            SET content = %s
                            WHERE id = (
                                SELECT id FROM etl_system.workspace_chat_messages
                                WHERE workspace_id = %s AND role = 'user' AND created_at <= %s
                                ORDER BY created_at DESC LIMIT 1
                            )
                            """,
                            (req.title, workspace_id, existing[1])
                        )
                    else:
                        # User message (we use title as content)
                        cur.execute(
                            """
                            INSERT INTO etl_system.workspace_chat_messages
                                (workspace_id, user_id, role, content)
                            VALUES (%s, %s, 'user', %s)
                            """,
                            (workspace_id, user_id, req.title),
                        )
                        # Assistant message
                        cur.execute(
                            """
                            INSERT INTO etl_system.workspace_chat_messages
                                (workspace_id, user_id, role, content, sql_query, columns, data, row_count)
                            VALUES (%s, %s, 'assistant', %s, %s, %s, %s, %s)
                            """,
                            (
                                workspace_id,
                                user_id,
                                "Custom Query Executed",
                                req.sql_query,
                                json.dumps(columns),
                                json.dumps(results, default=str),
                                row_count,
                            ),
                        )
                conn.commit()
        except Exception as e:
            logger.warning("[Workspace] Failed to persist custom SQL history: %s", e)

        return {
            "status": "success",
            "question": req.title,
            "sql": req.sql_query,
            "columns": columns,
            "data": results,
            "row_count": row_count,
        }
    except Exception as e:
        logger.warning("[Workspace] Custom SQL execution failed: %s", e)
        raise HTTPException(status_code=400, detail=str(e))



# ═══════════════════════════════════════════════════════════════════════════
# REPORT SUMMARIZATION
# ═══════════════════════════════════════════════════════════════════════════

@router.post("/{workspace_id}/report/summarize")
async def summarize_workspace_report(
    workspace_id: str,
    req: WorkspaceReportSummarizeRequest,
    current_user: dict = Depends(get_current_user),
):
    """Generate an AI summary of a workspace report."""
    db = _get_db()
    user_id = str(current_user.get("id", ""))
    
    # Verify workspace ownership
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM etl_system.workspaces WHERE workspace_id = %s AND created_by = %s",
                (workspace_id, user_id),
            )
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Workspace not found")

    from app.core.llm import create_workspace_llm
    from langchain_core.messages import HumanMessage
    
    llm, _ = create_workspace_llm()
    
    import pandas as pd
    
    # Generate Pandas Statistical Profile
    profile_str = "No data available."
    if req.data:
        try:
            df = pd.DataFrame(req.data)
            
            # Numeric stats
            numeric_cols = df.select_dtypes(include=['number']).columns
            numeric_stats = df[numeric_cols].describe().to_string() if not numeric_cols.empty else "No numeric columns."
            
            # Categorical stats
            cat_cols = df.select_dtypes(exclude=['number']).columns
            cat_stats_list = []
            for col in cat_cols:
                vc = df[col].value_counts().head(5).to_dict()
                unique_count = df[col].nunique()
                cat_stats_list.append(f"Column '{col}' ({unique_count} unique values). Top 5: {vc}")
            
            cat_stats = "\n".join(cat_stats_list) if not cat_cols.empty else "No categorical columns."
            
            profile_str = f"Dataset Shape: {len(df)} rows, {len(df.columns)} columns.\n\n"
            profile_str += f"### Numeric Column Statistics:\n{numeric_stats}\n\n"
            profile_str += f"### Categorical Column Top Values:\n{cat_stats}"
        except Exception as e:
            logger.warning(f"[Workspace] Pandas profiling failed: {e}")
            profile_str = f"Failed to generate full statistical profile. (Error: {e})"
    
    data_sample = req.data[:5] # Just 5 rows for visual context
    data_str = json.dumps(data_sample, default=str)
    
    prompt = f"""You are an expert Data Analyst AI.
The user requested a report based on this question/query: "{req.question}"

The system executed the following SQL query to retrieve the data:
```sql
{req.sql_query}
```

The resulting columns are: {', '.join(req.columns)}

Here is the exact Mathematical Profile of the ENTIRE dataset generated by Pandas:
```text
{profile_str}
```

And here is a small 5-row sample for visual context:
{data_str}

Please provide a comprehensive analytical report in Markdown format.
Focus on:
1. Summarizing how the data is spread and distributed based on the Mathematical Profile.
2. Identifying key insights, trends, or anomalies.
3. Providing actionable takeaways if applicable.

Format your response with clear headings, bullet points, and concise language. Do NOT include the raw data or SQL query in your response, just the analytical insights.
"""
    
    try:
        from app.core.llm import invoke_llm_with_retry
        response_content = invoke_llm_with_retry(llm, [HumanMessage(content=prompt)], context_name="Report Summarization")
        
        if req.sql_query:
            with db.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE etl_system.workspace_chat_messages
                        SET ai_summary = %s
                        WHERE id = (
                            SELECT id FROM etl_system.workspace_chat_messages
                            WHERE workspace_id = %s AND sql_query = %s
                            ORDER BY created_at DESC LIMIT 1
                        )
                        """,
                        (response_content, workspace_id, req.sql_query)
                    )
                conn.commit()

        return {"status": "success", "summary": response_content}
    except Exception as e:
        logger.warning(f"[Workspace] Report summarization failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate AI report summary.")

# ═══════════════════════════════════════════════════════════════════════════
# SHARE A SPECIFIC REPORT (Snapshot)
# ═══════════════════════════════════════════════════════════════════════════

class _ShareReportRequest(BaseModel):
    title: str = ""
    question: str = ""
    sql_query: str = ""
    columns: list = []
    data: list = []
    row_count: int = 0
    ai_summary: str = ""


@router.post("/{workspace_id}/report/share")
async def share_report_snapshot(
    workspace_id: str,
    request: _ShareReportRequest,
    current_user: dict = Depends(get_current_user),
):
    """Save a report snapshot and return a public share token."""
    db = _get_db()
    user_id = str(current_user.get("id", ""))

    with db.get_connection() as conn:
        with conn.cursor() as cur:
            # Verify ownership
            cur.execute(
                "SELECT 1 FROM etl_system.workspaces WHERE workspace_id = %s AND created_by = %s",
                (workspace_id, user_id),
            )
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Workspace not found")

            import uuid
            report_id = str(uuid.uuid4())
            share_token = str(uuid.uuid4())

            cur.execute(
                """
                INSERT INTO etl_system.shared_reports
                    (report_id, workspace_id, share_token, title, question, sql_query,
                     columns, data, row_count, ai_summary, created_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    report_id, workspace_id, share_token,
                    request.title, request.question, request.sql_query,
                    Json(request.columns), Json(request.data),
                    request.row_count, request.ai_summary or None, user_id,
                ),
            )
            conn.commit()

    return {
        "status": "success",
        "report_id": report_id,
        "share_token": share_token,
    }


# ═══════════════════════════════════════════════════════════════════════════
# AUTO-PROFILING
# ═══════════════════════════════════════════════════════════════════════════

@router.post("/{workspace_id}/profile")
async def profile_workspace(
    workspace_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Run auto-profiling on all tables in the workspace (LLM-powered descriptions + embeddings)."""
    db = _get_db()
    user_id = str(current_user.get("id", ""))

    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM etl_system.workspaces WHERE workspace_id = %s AND created_by = %s",
                (workspace_id, user_id),
            )
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Workspace not found")

    # Setup LLM + embed model (DRY factory)
    from app.core.llm import create_workspace_llm
    from app.core.agents.profiler import ProfilerAgent
    llm, embed_model = create_workspace_llm()

    profiler = ProfilerAgent(db=db, llm=llm, embed_model=embed_model)
    results = profiler.profile_workspace(workspace_id)

    return {
        "status": "success",
        "workspace_id": workspace_id,
        "profiled_tables": len(results),
        "results": results,
    }


@router.post("/{workspace_id}/profile/{table_name}")
async def profile_table(
    workspace_id: str,
    table_name: str,
    current_user: dict = Depends(get_current_user),
):
    """Run auto-profiling on a specific table."""
    db = _get_db()
    user_id = str(current_user.get("id", ""))

    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT schema_name FROM etl_system.workspaces WHERE workspace_id = %s AND created_by = %s",
                (workspace_id, user_id),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Workspace not found")
            schema_name = row[0]

    # Setup LLM + embed model (DRY factory)
    from app.core.llm import create_workspace_llm
    from app.core.agents.profiler import ProfilerAgent
    llm, embed_model = create_workspace_llm()

    profiler = ProfilerAgent(db=db, llm=llm, embed_model=embed_model)
    result = profiler.profile_table(workspace_id, schema_name, table_name)

    return {"status": "success", "workspace_id": workspace_id, "table_name": table_name, **result}

# ═══════════════════════════════════════════════════════════════════════════
# WORKSPACE RELATIONSHIPS  (Task 6)
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/{workspace_id}/relationships")
async def list_workspace_relationships(
    workspace_id: str,
    current_user: dict = Depends(get_current_user),
):
    """List all relationships (FK, inferred) for a workspace."""
    db = _get_db()
    user_id = str(current_user.get("id", ""))

    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM etl_system.workspaces WHERE workspace_id = %s AND created_by = %s",
                (workspace_id, user_id),
            )
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Workspace not found")

            cur.execute(
                """SELECT relationship_id, source_table, source_column,
                          target_table, target_column, relationship_type, inferred_by
                     FROM etl_system.workspace_relationships
                    WHERE workspace_id = %s
                    ORDER BY source_table, source_column""",
                (workspace_id,),
            )
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]

    return {"status": "success", "workspace_id": workspace_id, "relationships": rows}


@router.post("/{workspace_id}/relationships")
async def create_workspace_relationship(
    workspace_id: str,
    req: WorkspaceRelationshipRequest,
    current_user: dict = Depends(get_current_user),
):
    """Create a user-defined relationship between two columns."""
    db = _get_db()
    user_id = str(current_user.get("id", ""))
    rel_id = f"rel-{uuid.uuid4().hex[:12]}"

    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM etl_system.workspaces WHERE workspace_id = %s AND created_by = %s",
                (workspace_id, user_id),
            )
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Workspace not found")

            cur.execute(
                """INSERT INTO etl_system.workspace_relationships
                       (relationship_id, workspace_id, source_table, source_column,
                        target_table, target_column, relationship_type, inferred_by, created_by)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, 'user', %s)
                   ON CONFLICT (relationship_id) DO NOTHING""",
                (rel_id, workspace_id, req.source_table, req.source_column,
                 req.target_table, req.target_column, req.relationship_type, user_id),
            )
        conn.commit()

    logger.info("[Workspace] Relationship created: %s.%s → %s.%s", req.source_table, req.source_column, req.target_table, req.target_column)
    return {
        "status": "success",
        "relationship_id": rel_id,
        "source_table": req.source_table,
        "source_column": req.source_column,
        "target_table": req.target_table,
        "target_column": req.target_column,
        "relationship_type": req.relationship_type,
    }


@router.delete("/{workspace_id}/relationships/{relationship_id}")
async def delete_workspace_relationship(
    workspace_id: str,
    relationship_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Delete a relationship by ID."""
    db = _get_db()
    user_id = str(current_user.get("id", ""))

    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM etl_system.workspaces WHERE workspace_id = %s AND created_by = %s",
                (workspace_id, user_id),
            )
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Workspace not found")

            cur.execute(
                "DELETE FROM etl_system.workspace_relationships WHERE relationship_id = %s AND workspace_id = %s",
                (relationship_id, workspace_id),
            )
            deleted = cur.rowcount
        conn.commit()

    if not deleted:
        raise HTTPException(status_code=404, detail="Relationship not found")

    return {"status": "success", "message": "Relationship deleted", "relationship_id": relationship_id}


# ═══════════════════════════════════════════════════════════════════════════
# WORKSPACE DASHBOARDS (Chat-to-Widget)
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/{workspace_id}/dashboard/stream")
async def stream_workspace_dashboard(
    workspace_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Stream dashboard widgets as NDJSON for progressive UI rendering.

    Each line is a JSON object representing one widget. After all widgets
    are streamed, they are auto-persisted to DB for instant cache on refresh.
    Final line is a summary event: {"event": "complete", "widget_count": N}.
    """
    db = _get_db()
    user_id = str(current_user.get("id", ""))

    async def event_generator():
        from app.core.agents.workspace_sql import WorkspaceSqlAgent
        from app.core.llm import create_workspace_llm

        _llm = None
        try:
            _llm, _ = create_workspace_llm()
        except Exception:
            pass

        agent = WorkspaceSqlAgent(db=db, workspace_id=workspace_id, llm=_llm)
        generated = agent.generate_workspace_dashboard()

        widgets = generated.get("widgets", []) if generated.get("status") == "success" else []

        # Yield widgets one-by-one for progressive rendering
        for w in widgets:
            yield json.dumps(w, default=str) + "\n"

        # ── Auto-persist all generated widgets to DB ──
        if widgets:
            try:
                with db.get_connection() as conn:
                    with conn.cursor() as cur:
                        # Get or create default dashboard
                        cur.execute(
                            "SELECT dashboard_id FROM etl_system.workspace_dashboards WHERE workspace_id = %s LIMIT 1",
                            (workspace_id,),
                        )
                        row = cur.fetchone()
                        if row:
                            dashboard_id = row[0]
                        else:
                            dashboard_id = f"dash-{workspace_id}"
                            cur.execute(
                                "INSERT INTO etl_system.workspace_dashboards (dashboard_id, workspace_id, name, created_by) VALUES (%s, %s, 'Default Dashboard', %s)",
                                (dashboard_id, workspace_id, user_id),
                            )

                        # Clear auto-generated widgets only — preserve user-pinned ones
                        cur.execute("DELETE FROM etl_system.dashboard_widgets WHERE workspace_id = %s AND origin_question IS NULL", (workspace_id,))
                        for gw in widgets:
                            wid = gw.get("id") or f"ws-auto-{uuid.uuid4().hex[:8]}"
                            cur.execute(
                                """INSERT INTO etl_system.dashboard_widgets
                                    (widget_id, dashboard_id, workspace_id, title, widget_type,
                                     chart_type, sql_query, config, pinned_by)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                                ON CONFLICT (widget_id) DO UPDATE SET
                                    title = EXCLUDED.title,
                                    widget_type = EXCLUDED.widget_type,
                                    chart_type = EXCLUDED.chart_type,
                                    sql_query = EXCLUDED.sql_query,
                                    config = EXCLUDED.config""",
                                (
                                    wid, dashboard_id, workspace_id,
                                    gw.get("title", ""), gw.get("type", "kpi"),
                                    gw.get("chartType") or gw.get("chart_type"),
                                    gw.get("sql_query", ""),
                                    json.dumps(gw, default=str),
                                    user_id,
                                ),
                            )
                    conn.commit()
                logger.info("[Workspace] Stream: persisted %d widgets", len(widgets))
            except Exception as e:
                logger.warning("[Workspace] Stream: persist failed: %s", e)

        # Final completion event
        yield json.dumps({"event": "complete", "widget_count": len(widgets)}, default=str) + "\n"

    return StreamingResponse(event_generator(), media_type="application/x-ndjson")

@router.get("/{workspace_id}/dashboard")
async def get_workspace_dashboard(
    workspace_id: str,
    regenerate: bool = False,
    current_user: dict = Depends(get_current_user),
):
    """Get the workspace dashboard — auto-generates widgets on first load if empty."""
    db = _get_db()
    user_id = str(current_user.get("id", ""))

    with db.get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT 1 FROM etl_system.workspaces WHERE workspace_id = %s AND created_by = %s",
                (workspace_id, user_id),
            )
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Workspace not found")

            # Get or create default dashboard
            cur.execute(
                "SELECT dashboard_id, name, layout_json FROM etl_system.workspace_dashboards WHERE workspace_id = %s LIMIT 1",
                (workspace_id,),
            )
            dashboard = cur.fetchone()

            if not dashboard:
                # Auto-create default dashboard
                dashboard_id = f"dash-{workspace_id}"
                cur.execute(
                    """
                    INSERT INTO etl_system.workspace_dashboards (dashboard_id, workspace_id, name, created_by)
                    VALUES (%s, %s, 'Default Dashboard', %s)
                    """,
                    (dashboard_id, workspace_id, user_id),
                )
                conn.commit()
                dashboard = {"dashboard_id": dashboard_id, "name": "Default Dashboard", "layout_json": None}

            # Get existing widgets — query by workspace_id to find ALL widgets
            # (incremental and full-gen may have different dashboard_id values)
            cur.execute(
                """
                SELECT widget_id, title, widget_type, chart_type, sql_query, config,
                       origin_question, pinned_by, created_at::text as created_at
                FROM etl_system.dashboard_widgets
                WHERE workspace_id = %s
                ORDER BY created_at ASC
                """,
                (workspace_id,),
            )
            saved_widgets = [dict(w) for w in cur.fetchall()]
            
            # Explicitly commit to end the read transaction and release any snapshot
            conn.commit()

    # If no widgets exist (or regenerate requested), auto-generate a dashboard
    if not saved_widgets or regenerate:
        # Separate pinned widgets from auto-generated ones (preserve on regenerate)
        pinned_widgets = [w for w in saved_widgets if w.get("origin_question")] if regenerate else []

        try:
            from app.core.agents.workspace_sql import WorkspaceSqlAgent
            from app.core.llm import create_workspace_llm

            # Setup LLM for intelligent widget planning (DRY factory)
            _llm = None
            try:
                _llm, _ = create_workspace_llm()
            except Exception as llm_err:
                logger.warning("[Workspace] LLM init for dashboard failed: %s", llm_err)

            agent = WorkspaceSqlAgent(db=db, workspace_id=workspace_id, llm=_llm)
            generated = agent.generate_workspace_dashboard()

            if generated.get("status") == "success" and generated.get("widgets"):
                gen_widgets = generated["widgets"]

                # ── Persist generated widgets to DB ──
                try:
                    with db.get_connection() as conn2:
                        with conn2.cursor() as cur2:
                            # Clear auto-generated widgets only — preserve user-pinned ones
                            cur2.execute(
                                "DELETE FROM etl_system.dashboard_widgets WHERE workspace_id = %s AND origin_question IS NULL",
                                (workspace_id,),
                            )
                            for gw in gen_widgets:
                                wid = gw.get("id") or f"ws-auto-{uuid.uuid4().hex[:8]}"
                                gw["id"] = wid
                                cur2.execute(
                                    """
                                    INSERT INTO etl_system.dashboard_widgets
                                        (widget_id, dashboard_id, workspace_id, title, widget_type,
                                         chart_type, sql_query, config, pinned_by)
                                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                                    ON CONFLICT (widget_id) DO UPDATE SET
                                        title = EXCLUDED.title,
                                        widget_type = EXCLUDED.widget_type,
                                        chart_type = EXCLUDED.chart_type,
                                        sql_query = EXCLUDED.sql_query,
                                        config = EXCLUDED.config
                                    """,
                                    (
                                        wid, dashboard["dashboard_id"], workspace_id,
                                        gw.get("title", ""), gw.get("type", "kpi"),
                                        gw.get("chartType") or gw.get("chart_type"),
                                        gw.get("sql_query") or "",
                                        json.dumps(gw, default=str),
                                        user_id,
                                    ),
                                )
                        conn2.commit()
                    logger.info("[Workspace] Persisted %d auto-generated widgets", len(gen_widgets))
                except Exception as save_err:
                    logger.warning("[Workspace] Widget persist failed: %s", save_err)

                return {
                    "status": "success",
                    "workspace_id": workspace_id,
                    "dashboard_id": dashboard["dashboard_id"],
                    "dashboard_name": dashboard["name"],
                    "layout_json": dashboard["layout_json"],
                    "widgets": gen_widgets,
                    "fingerprint": generated.get("fingerprint", {}),
                    "auto_generated": True,
                    "cache_hit": False,
                }
        except Exception as e:
            logger.warning("[Workspace] Auto-generation failed: %s", e)

        # Auto-generation failed — return whatever pinned widgets exist (or empty dashboard)
        if not saved_widgets and not pinned_widgets:
            return {
                "status": "success",
                "workspace_id": workspace_id,
                "dashboard_id": dashboard["dashboard_id"],
                "dashboard_name": dashboard["name"],
                "layout_json": dashboard["layout_json"],
                "widgets": [],
                "auto_generated": False,
                "cache_hit": False,
                "message": "No tables loaded yet. Load data via ETL to generate dashboard.",
            }

    # ── Detect newly added tables that lack widgets (Incremental generation on-demand) ──
    if saved_widgets and not regenerate:
        try:
            with db.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT table_name FROM etl_system.tables_metadata WHERE workspace_id = %s", (workspace_id,))
                    all_db_tables = {row[0] for row in cur.fetchall()}
            
            widget_tables = set()
            for w in saved_widgets:
                conf = w.get("config")
                if conf:
                    if isinstance(conf, str):
                        try:
                            conf = json.loads(conf)
                        except Exception:
                            conf = {}
                    if isinstance(conf, dict) and conf.get("source_table") and not conf["source_table"].startswith("_"):
                        widget_tables.add(conf["source_table"])
            
            missing_tables = list(all_db_tables - widget_tables)
            if missing_tables:
                logger.info("[Workspace] Found %d new tables missing widgets: %s. Triggering incremental update.", len(missing_tables), missing_tables)
                from app.core.agents.workspace_sql import WorkspaceSqlAgent
                from app.core.llm import create_workspace_llm
                _llm, _ = create_workspace_llm()
                agent = WorkspaceSqlAgent(db=db, workspace_id=workspace_id, llm=_llm)
                
                inc_result = agent.update_incremental_dashboard(list_of_new_tables=missing_tables)
                
                if inc_result.get("status") == "success" and inc_result.get("new_widgets"):
                    import datetime
                    for nw in inc_result["new_widgets"]:
                        saved_widgets.append({
                            "widget_id": nw.get("id"),
                            "title": nw.get("title", ""),
                            "widget_type": nw.get("type", "kpi"),
                            "chart_type": nw.get("chartType", "bar"),
                            "sql_query": nw.get("sql_query", ""),
                            "config": json.dumps(nw),
                            "origin_question": None,
                            "pinned_by": user_id,
                            "created_at": str(datetime.datetime.utcnow()),
                        })
        except Exception as e:
            logger.warning("[Workspace] Incremental dashboard update failed: %s", e)

    # ── Return cached widgets from DB (config JSONB is the primary source) ──
    # The full widget object (including chartData, value, items, gridW, gridH)
    # was stored in the `config` JSONB column during generation. Use it as the
    # primary source and overlay DB metadata only for canonical fields.
    widgets_for_client = []
    for w in saved_widgets:
        # Start from config JSONB (contains full widget with computed data)
        config = w.get("config")
        if config:
            if isinstance(config, str):
                try:
                    config = json.loads(config)
                except Exception:
                    config = {}
        if not isinstance(config, dict):
            config = {}

        # Handle nested config: if config contains a nested "config" key,
        # flatten it (this happens when incremental builder wraps config)
        if "config" in config and isinstance(config["config"], dict):
            inner = config.pop("config")
            # Merge inner config values (gridW, gridH, etc.) into outer
            for k, v in inner.items():
                if k not in config:
                    config[k] = v

        # Use config as base, then overlay canonical DB fields
        widget = {**config}
        # Always use DB columns as canonical source for these fields
        widget["id"] = w["widget_id"]
        widget["title"] = w["title"] or config.get("title", "")
        widget["type"] = w["widget_type"] or config.get("type", "kpi")
        widget["chartType"] = w.get("chart_type") or config.get("chartType") or config.get("chart_type")
        widget["chart_type"] = widget["chartType"]  # Ensure both keys exist
        widget["sql_query"] = w.get("sql_query") or config.get("sql_query", "")
        widget["origin_question"] = w.get("origin_question")
        widget["pinned_by"] = w.get("pinned_by")
        widget["created_at"] = w.get("created_at")

        widgets_for_client.append(widget)

    # Determine cache timestamp from earliest widget creation
    cache_timestamp = None
    for w in saved_widgets:
        ts = w.get("created_at")
        if ts and (cache_timestamp is None or str(ts) < str(cache_timestamp)):
            cache_timestamp = ts

    logger.info("[Workspace] Returning %d cached widgets for workspace %s", len(widgets_for_client), workspace_id)

    return {
        "status": "success",
        "workspace_id": workspace_id,
        "dashboard_id": dashboard["dashboard_id"],
        "dashboard_name": dashboard["name"],
        "layout_json": dashboard["layout_json"],
        "widgets": widgets_for_client,
        "cache_hit": True,
        "cached_at": cache_timestamp,
    }


@router.post("/{workspace_id}/dashboard/save")
async def save_workspace_dashboard(
    workspace_id: str,
    req: WorkspaceDashboardSaveRequest,
    current_user: dict = Depends(get_current_user),
):
    """Save the full workspace dashboard configuration (layout + widgets).
    
    IMPORTANT: This endpoint is designed to be NON-DESTRUCTIVE to widget data.
    When called from the frontend's GridStack change handler, it only updates
    layout positions (gridX/Y/W/H) — it does NOT overwrite the config JSONB
    that contains the full widget payload (chartData, value, items, etc.)
    which was persisted during dashboard generation.
    """
    db = _get_db()
    user_id = str(current_user.get("id", ""))

    with db.get_connection() as conn:
        with conn.cursor() as cur:
            # Check workspace ownership
            cur.execute(
                "SELECT 1 FROM etl_system.workspaces WHERE workspace_id = %s AND created_by = %s",
                (workspace_id, user_id),
            )
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Workspace not found")

            # Get or create dashboard
            cur.execute(
                "SELECT dashboard_id FROM etl_system.workspace_dashboards WHERE workspace_id = %s LIMIT 1",
                (workspace_id,),
            )
            row = cur.fetchone()
            if row:
                dashboard_id = row[0]
                cur.execute(
                    "UPDATE etl_system.workspace_dashboards SET layout_json = %s WHERE dashboard_id = %s",
                    (json.dumps(req.layout_json) if req.layout_json else None, dashboard_id)
                )
            else:
                dashboard_id = f"dash-{workspace_id}"
                cur.execute(
                    """
                    INSERT INTO etl_system.workspace_dashboards (dashboard_id, workspace_id, name, layout_json, created_by)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (dashboard_id, workspace_id, req.name or 'Default Dashboard', json.dumps(req.layout_json) if req.layout_json else None, user_id),
                )
            
            # Update widget layout positions only (non-destructive)
            # Never overwrite config JSONB — it contains chartData/value/items
            # from the generation step.
            if req.widgets is not None:
                for w in req.widgets:
                    wid = w.get("id")
                    if not wid:
                        continue
                    
                    # Only update layout fields and title — preserve config JSONB
                    grid_w = w.get("gridW", w.get("w"))
                    grid_h = w.get("gridH", w.get("h"))
                    grid_x = w.get("gridX", w.get("x"))
                    grid_y = w.get("gridY", w.get("y"))
                    title = w.get("title", "")
                    
                    # Update layout in config JSONB without overwriting the whole object
                    cur.execute(
                        """
                        UPDATE etl_system.dashboard_widgets
                        SET title = COALESCE(NULLIF(%s, ''), title),
                            config = jsonb_set(
                                jsonb_set(
                                    jsonb_set(
                                        jsonb_set(config, '{gridW}', %s::jsonb, true),
                                        '{gridH}', %s::jsonb, true),
                                    '{gridX}', %s::jsonb, true),
                                '{gridY}', %s::jsonb, true)
                        WHERE widget_id = %s AND workspace_id = %s
                        """,
                        (
                            title,
                            json.dumps(grid_w) if grid_w is not None else '6',
                            json.dumps(grid_h) if grid_h is not None else '3',
                            json.dumps(grid_x) if grid_x is not None else '0',
                            json.dumps(grid_y) if grid_y is not None else '0',
                            wid, workspace_id,
                        )
                    )
            conn.commit()
    
    return {"status": "success", "message": "Dashboard saved successfully"}


@router.post("/{workspace_id}/dashboard/pin")
async def pin_widget_to_dashboard(
    workspace_id: str,
    req: WorkspacePinWidgetRequest,
    current_user: dict = Depends(get_current_user),
):
    """Pin a chat-generated SQL result as a permanent dashboard widget."""
    db = _get_db()
    user_id = str(current_user.get("id", ""))
    widget_id = str(uuid.uuid4())

    with db.get_connection() as conn:
        with conn.cursor() as cur:
            # Get or create dashboard
            cur.execute(
                "SELECT dashboard_id FROM etl_system.workspace_dashboards WHERE workspace_id = %s LIMIT 1",
                (workspace_id,),
            )
            row = cur.fetchone()
            if row:
                dashboard_id = row[0]
            else:
                dashboard_id = f"dash-{workspace_id}"
                cur.execute(
                    """
                    INSERT INTO etl_system.workspace_dashboards (dashboard_id, workspace_id, name, created_by)
                    VALUES (%s, %s, 'Default Dashboard', %s)
                    """,
                    (dashboard_id, workspace_id, user_id),
                )

            # Insert widget
            cur.execute(
                """
                INSERT INTO etl_system.dashboard_widgets
                    (widget_id, dashboard_id, workspace_id, title, widget_type, chart_type,
                     sql_query, config, origin_question, pinned_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    widget_id, dashboard_id, workspace_id,
                    req.title, req.widget_type, req.chart_type,
                    req.sql_query,
                    json.dumps(req.config) if req.config else None,
                    req.origin_question, user_id,
                ),
            )
        conn.commit()

    logger.info("[Workspace] 📌 Pinned widget '%s' to dashboard %s", req.title, dashboard_id)

    return {
        "status": "success",
        "widget_id": widget_id,
        "dashboard_id": dashboard_id,
        "message": f"Widget '{req.title}' pinned to dashboard",
    }


@router.delete("/{workspace_id}/dashboard/widgets/{widget_id}")
async def unpin_widget(
    workspace_id: str,
    widget_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Remove a widget from the workspace dashboard."""
    db = _get_db()

    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM etl_system.dashboard_widgets WHERE widget_id = %s AND workspace_id = %s",
                (widget_id, workspace_id),
            )
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="Widget not found")
        conn.commit()

    return {"message": "Widget removed", "widget_id": widget_id}

class RefreshRequest(BaseModel):
    filters: Optional[Dict[str, Any]] = None

@router.post("/{workspace_id}/dashboard/widgets/{widget_id}/refresh")
async def refresh_workspace_widget(
    workspace_id: str,
    widget_id: str,
    req: Optional[RefreshRequest] = None,
    current_user: dict = Depends(get_current_user),
):
    """Re-execute a widget's SQL query and return fresh data."""
    db = _get_db()
    user_id = str(current_user.get("id", ""))

    with db.get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """SELECT widget_id, title, widget_type, chart_type, sql_query, config
                   FROM etl_system.dashboard_widgets
                   WHERE widget_id = %s AND workspace_id = %s""",
                (widget_id, workspace_id),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Widget not found")

    sql_query = row.get("sql_query", "").strip()
    if not sql_query:
        # Return existing config as-is (no SQL to refresh)
        config = row.get("config")
        if isinstance(config, str):
            try:
                config = json.loads(config)
            except Exception:
                config = {}
        return {"status": "success", "widget": config or dict(row)}

    # Execute the SQL
    from app.core.agents.workspace_sql import WorkspaceSqlAgent
    agent = WorkspaceSqlAgent(db=db, workspace_id=workspace_id)

    try:
        # Apply filters if provided
        final_sql = sql_query
        if req and req.filters:
            final_sql = agent.apply_filters_to_sql(sql_query, req.filters)
            
        results, columns = agent._execute_sql(final_sql)
    except Exception as e:
        return {"status": "error", "message": f"SQL execution failed: {e}"}

    w_type = row.get("widget_type", "kpi")
    config = row.get("config")
    if isinstance(config, str):
        try:
            config = json.loads(config)
        except Exception:
            config = {}
    if not isinstance(config, dict):
        config = {}

    # Rebuild widget data from fresh results
    refreshed = {**config, "id": widget_id, "title": row["title"], "type": w_type}

    if w_type == "kpi" and results and columns:
        val = results[0].get(columns[0], "N/A")
        try:
            refreshed["value"] = agent._format_number(float(val), agent._infer_format_hint(row["title"]))
        except (ValueError, TypeError):
            refreshed["value"] = str(val)

    elif w_type == "chart" and results and len(columns) >= 2:
        label_col, value_col = columns[0], columns[1]
        
        def safe_float(r, value_col):
            try:
                return float(r.get(value_col, 0))
            except (ValueError, TypeError):
                return 0.0
                
        refreshed["chartData"] = {
            "labels": [str(r.get(label_col, "")) for r in results[:30]],
            "series": [{
                "name": value_col.replace("_", " ").title(),
                "data": [safe_float(r, value_col) for r in results[:30]],
            }],
        }

    elif w_type == "list" and results and len(columns) >= 2:
        label_col, value_col = columns[0], columns[1]
        items = []
        for r in results[:10]:
            lbl = str(r.get(label_col, ""))
            try:
                val_fmt = agent._format_number(float(r.get(value_col, 0)), agent._infer_format_hint(row["title"]))
            except (ValueError, TypeError):
                val_fmt = str(r.get(value_col, ""))
            items.append({"label": lbl, "value": val_fmt})
        refreshed["items"] = items

    elif w_type == "table" and results and columns:
        refreshed["data"] = results[:200]
        refreshed["columns"] = columns

    return {"status": "success", "widget": refreshed}


@router.post("/{workspace_id}/dashboard/widget")
async def generate_workspace_widget(
    workspace_id: str,
    req: WorkspaceWidgetRequest,
    current_user: dict = Depends(get_current_user),
):
    """Generate a single dashboard widget from a natural language query."""
    db = _get_db()
    user_id = str(current_user.get("id", ""))

    # Verify ownership
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM etl_system.workspaces WHERE workspace_id = %s AND created_by = %s",
                (workspace_id, user_id),
            )
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Workspace not found")

    # Setup LLM + embed model (DRY factory)
    from app.core.llm import create_workspace_llm
    llm, embed_model = create_workspace_llm()

    from app.core.agents.workspace_sql import WorkspaceSqlAgent
    agent = WorkspaceSqlAgent(db=db, workspace_id=workspace_id, llm=llm, embed_model=embed_model)
    result = agent.generate_single_widget(
        query=req.query,
        widget_type_hint=req.widget_type_hint,
        chart_type_hint=req.chart_type_hint,
    )
    
    if result.get("status") == "success" and "widget" in result:
        widget = result["widget"]
        # Save the new widget into the database so it will be persisted across refreshes
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                # Make sure the dashboard exists before inserting widget
                cur.execute(
                    "SELECT dashboard_id FROM etl_system.workspace_dashboards WHERE workspace_id = %s LIMIT 1",
                    (workspace_id,)
                )
                row = cur.fetchone()
                if row:
                    dashboard_id = row[0]
                else:
                    dashboard_id = f"dash-{workspace_id}"
                    cur.execute(
                        """
                        INSERT INTO etl_system.workspace_dashboards (dashboard_id, workspace_id, name, created_by)
                        VALUES (%s, %s, 'Default Dashboard', %s)
                        """,
                        (dashboard_id, workspace_id, user_id),
                    )
                
                # Insert the newly generated widget
                cur.execute(
                    """
                    INSERT INTO etl_system.dashboard_widgets
                        (widget_id, dashboard_id, workspace_id, title, widget_type, chart_type,
                         sql_query, config, origin_question)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (widget_id) DO UPDATE SET 
                        config = EXCLUDED.config, title = EXCLUDED.title, sql_query = EXCLUDED.sql_query
                    """,
                    (
                        widget["id"], dashboard_id, workspace_id,
                        widget.get("title", req.query[:80]),
                        widget.get("type", "chart"),
                        widget.get("chartType"),
                        widget.get("sql_query"),
                        json.dumps(widget, default=str),
                        req.query
                    ),
                )
            conn.commit()

    return result


@router.post("/{workspace_id}/dashboard/widget/custom")
async def create_workspace_custom_widget(
    workspace_id: str,
    req: WorkspaceCustomWidgetRequest,
    current_user: dict = Depends(get_current_user),
):
    """Create a completely custom widget manually via SQL without LLM generation."""
    db = _get_db()
    user_id = str(current_user.get("id", ""))

    # Verify ownership
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM etl_system.workspaces WHERE workspace_id = %s AND created_by = %s",
                (workspace_id, user_id),
            )
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Workspace not found")

    from app.core.agents.workspace_sql import WorkspaceSqlAgent
    agent = WorkspaceSqlAgent(db=db, workspace_id=workspace_id)
    
    try:
        results, columns = agent._execute_sql(req.sql_query)
    except Exception as e:
        return {"status": "error", "message": f"SQL execution failed: {e}", "sql_query": req.sql_query}
        
    widget_id = "wid-" + str(uuid.uuid4())[:8]
    w_type = req.widget_type_hint or "kpi"
    
    widget_config = {
        "id": widget_id,
        "title": req.title,
        "type": w_type,
        "chartType": req.chart_type_hint if w_type == "chart" else None,
        "sql_query": req.sql_query,
        "description": "Custom user widget",
    }
    
    if w_type == "kpi" and results and columns:
        val = results[0].get(columns[0], "N/A")
        try:
            widget_config["value"] = agent._format_number(float(val), agent._infer_format_hint(req.title))
        except (ValueError, TypeError):
            widget_config["value"] = str(val)

    elif w_type == "chart" and results and len(columns) >= 2:
        label_col, value_col = columns[0], columns[1]
        
        def safe_float(r, val_col):
            try:
                return float(r.get(val_col, 0))
            except (ValueError, TypeError):
                return 0.0
                
        widget_config["chartData"] = {
            "labels": [str(r.get(label_col, "")) for r in results[:30]],
            "series": [{
                "name": value_col.replace("_", " ").title(),
                "data": [safe_float(r, value_col) for r in results[:30]],
            }],
        }
        
    elif w_type == "list" and results and len(columns) >= 2:
        label_col, value_col = columns[0], columns[1]
        items = []
        for r in results[:10]:
            lbl = str(r.get(label_col, ""))
            try:
                val_fmt = agent._format_number(float(r.get(value_col, 0)), agent._infer_format_hint(req.title))
            except (ValueError, TypeError):
                val_fmt = str(r.get(value_col, ""))
            items.append({"label": lbl, "value": val_fmt})
        widget_config["items"] = items

    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT dashboard_id FROM etl_system.workspace_dashboards WHERE workspace_id = %s LIMIT 1",
                (workspace_id,)
            )
            row = cur.fetchone()
            if row:
                dashboard_id = row[0]
            else:
                dashboard_id = f"dash-{workspace_id}"
                cur.execute(
                    """
                    INSERT INTO etl_system.workspace_dashboards (dashboard_id, workspace_id, name, created_by)
                    VALUES (%s, %s, 'Default Dashboard', %s)
                    """,
                    (dashboard_id, workspace_id, user_id),
                )
            
            cur.execute(
                """
                INSERT INTO etl_system.dashboard_widgets
                    (widget_id, dashboard_id, workspace_id, title, widget_type, chart_type,
                     sql_query, config, origin_question)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    widget_id, dashboard_id, workspace_id,
                    req.title, w_type, req.chart_type_hint, 
                    req.sql_query, json.dumps(widget_config, default=str), "Custom Widget"
                ),
            )
        conn.commit()

    return {"status": "success", "widget": widget_config}


@router.get("/{workspace_id}/dashboard/schema")
async def get_workspace_chart_schema(
    workspace_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Return dimensions and measures for the Chart Builder sidebar."""
    db = _get_db()
    user_id = str(current_user.get("id", ""))

    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM etl_system.workspaces WHERE workspace_id = %s AND created_by = %s",
                (workspace_id, user_id),
            )
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Workspace not found")

    from app.core.agents.workspace_sql import WorkspaceSqlAgent
    agent = WorkspaceSqlAgent(db=db, workspace_id=workspace_id)
    schema = agent.get_chart_schema()

    return {"status": "success", "workspace_id": workspace_id, **schema}


@router.post("/{workspace_id}/dashboard/chart-builder")
async def workspace_chart_builder(
    workspace_id: str,
    req: WorkspaceChartBuilderRequest,
    current_user: dict = Depends(get_current_user),
):
    """Generate a chart widget from explicit Chart Builder parameters."""
    db = _get_db()
    user_id = str(current_user.get("id", ""))

    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM etl_system.workspaces WHERE workspace_id = %s AND created_by = %s",
                (workspace_id, user_id),
            )
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Workspace not found")

    from app.core.agents.workspace_sql import WorkspaceSqlAgent
    agent = WorkspaceSqlAgent(db=db, workspace_id=workspace_id)
    result = agent.generate_custom_chart(
        chart_type=req.chart_type,
        dimension=req.dimension,
        measure=req.measure,
        aggregation=req.aggregation,
    )
    if result.get("status") == "success" and "widget" in result:
        widget = result["widget"]
        # Save the new widget into the database so it will be persisted across refreshes
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT dashboard_id FROM etl_system.workspace_dashboards WHERE workspace_id = %s LIMIT 1",
                    (workspace_id,)
                )
                row = cur.fetchone()
                if row:
                    dashboard_id = row[0]
                else:
                    dashboard_id = f"dash-{workspace_id}"
                    cur.execute(
                        """
                        INSERT INTO etl_system.workspace_dashboards (dashboard_id, workspace_id, name, created_by)
                        VALUES (%s, %s, 'Default Dashboard', %s)
                        """,
                        (dashboard_id, workspace_id, user_id),
                    )
                
                cur.execute(
                    """
                    INSERT INTO etl_system.dashboard_widgets
                        (widget_id, dashboard_id, workspace_id, title, widget_type, chart_type,
                         sql_query, config, origin_question)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (widget_id) DO UPDATE SET 
                        config = EXCLUDED.config, title = EXCLUDED.title, sql_query = EXCLUDED.sql_query
                    """,
                    (
                        widget.get("id", f"wid-{__import__('uuid').uuid4().hex[:8]}"), dashboard_id, workspace_id,
                        widget.get("title", f"Custom {req.chart_type.capitalize()} Chart"),
                        widget.get("type", "chart"),
                        widget.get("chartType") or req.chart_type,
                        widget.get("sql_query", ""),
                        json.dumps(widget, default=str),
                        "Chart Builder"
                    ),
                )
            conn.commit()

    return result


# ═══════════════════════════════════════════════════════════════════════════
# ETL NAVIGATION HELPER
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/{workspace_id}/etl-connection")
async def get_workspace_etl_connection(
    workspace_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Return the most recent ETL connection_id used for this workspace, for deep linking."""
    db = _get_db()
    user_id = str(current_user.get("id", ""))

    with db.get_connection() as conn:
        with conn.cursor() as cur:
            # Verify ownership
            cur.execute(
                "SELECT 1 FROM etl_system.workspaces WHERE workspace_id = %s AND created_by = %s",
                (workspace_id, user_id),
            )
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Workspace not found")

            # Find latest ETL job for this workspace
            cur.execute(
                """
                SELECT connection_id, job_id
                FROM etl_system.etl_jobs
                WHERE workspace_id = %s AND created_by = %s
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (workspace_id, user_id),
            )
            row = cur.fetchone()

    if not row:
        return {"workspace_id": workspace_id, "connection_id": None, "job_id": None}

    return {"workspace_id": workspace_id, "connection_id": row[0], "job_id": row[1]}
