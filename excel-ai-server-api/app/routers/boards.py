from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from typing import Dict, Optional, Any, List
import logging
import json
import uuid
import secrets
import tempfile
import os
from psycopg2.extras import RealDictCursor

from app.core import DatabaseManager, HybridAgent
from app.utils.logging import log_full_exception, user_facing_error_message
from app.core.auth import get_current_user
from app.dependencies import get_db, get_agent, get_or_load_agent, _get_trace_user_metadata
from app.schemas import BoardListResponse, BoardInfo, BoardCreateRequest, ActiveFileRequest, BoardDashboardSaveRequest, BoardPublishRequest, BoardScreenState
from app.config import logger

# Optional Langfuse
from app.config import observe, langfuse_context


router = APIRouter(prefix="/api/boards", tags=["boards"])


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def _extract_board_file_metadata(column_stats_json: Any) -> dict:
    """Extract metadata from board file column_stats."""
    if isinstance(column_stats_json, str):
        try:
            stats = json.loads(column_stats_json)
        except:
            stats = {}
    elif isinstance(column_stats_json, dict):
        stats = column_stats_json
    else:
        stats = {}
    
    return {
        "total_rows": stats.get("total_rows", 0),
        "total_columns": stats.get("total_columns", len(stats.get("columns", {}))),
        "columns": list(stats.get("columns", {}).keys()) if "columns" in stats else [],
    }


def _normalize_board_studio_state(studio_data: Any) -> dict:
    """Normalize board studio state for consistency."""
    if isinstance(studio_data, str):
        try:
            studio = json.loads(studio_data)
        except:
            studio = {}
    elif isinstance(studio_data, dict):
        studio = studio_data
    else:
        studio = {}
    
    # Ensure required keys exist
    studio.setdefault("screens", [])
    studio.setdefault("active_screen_id", None)
    studio.setdefault("active_theme", "light")
    studio.setdefault("screen_widgets", {})
    studio.setdefault("file_screen_widgets", {})
    studio.setdefault("screen_share_tokens", {})
    studio.setdefault("screen_thumbnails", {})
    studio.setdefault("file_screen_thumbnails", {})
    
    return studio


def _load_board_agent(file_uuid: str, board_id: str, db: DatabaseManager):
    """Load a HybridAgent from a board_files row."""
    try:
        with db.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT file_uuid, filename, table_name, column_stats FROM board_files WHERE file_uuid = %s AND board_id = %s",
                    (file_uuid, board_id)
                )
                row = cur.fetchone()
                if not row:
                    return None

        obj = object.__new__(HybridAgent)
        obj.db = db
        obj.file_uuid = row["file_uuid"]
        obj.filename = row["filename"]
        obj.table_name = row["table_name"]
        obj.user_id = None
        obj.project_id = None
        obj.subproject_id = None
        obj.progress_callback = None
        obj.sheet_name = None
        obj.file_group_id = None
        obj.is_deleted = False

        stats = row.get("column_stats")
        if isinstance(stats, str):
            try: stats = json.loads(stats)
            except: stats = {}
        elif stats is None:
            stats = {}
        obj.column_stats = stats

        if 'columns' in stats and isinstance(stats['columns'], dict):
            obj.columns = list(stats['columns'].keys())
        else:
            obj.columns = obj._get_columns_from_db_schema()

        import warnings
        import pandas as pd
        cols = [c for c in obj.columns if c != 'row_embedding']
        cols_join = ", ".join(f'"{c}"' for c in cols)
        with db.get_connection() as conn:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                obj.df = pd.read_sql(f"SELECT {cols_join} FROM {obj.table_name}", conn)

        try:
            from langchain_ollama import ChatOllama  # type: ignore[import-not-found]
            _LANGCHAIN_OLLAMA_AVAILABLE = True
        except ImportError:
            ChatOllama = None  # type: ignore[assignment]
            _LANGCHAIN_OLLAMA_AVAILABLE = False
        _lf_callbacks = None
        try:
            _lf_cb = langfuse_context.get_current_langchain_handler()
            if _lf_cb:
                _lf_callbacks = [_lf_cb]
        except Exception:
            _lf_callbacks = None
        from app.core.llm import create_workspace_llm
        obj.llm, _ = create_workspace_llm(temperature=0, streaming=False, callbacks=_lf_callbacks)

        obj.embed_model = None
        obj.embedding_dim = 0
        obj.semantic_cache = None
        obj.semantic_cache_threshold = 0
        obj._last_normalized_query = None
        obj.pandas_agent = None
        obj.code_fixer_callback = None

        return obj
    except Exception as e:
        log_full_exception(e, f"Failed to load board agent for {file_uuid}")
        return None


def _resolve_saved_board_dashboard(saved_widgets: Any, active_file_uuid: str):
    """Return saved dashboard_data when it matches active file; otherwise None."""
    if not saved_widgets:
        return None
    dashboard_data = saved_widgets if isinstance(saved_widgets, dict) else json.loads(saved_widgets)
    saved_file = dashboard_data.get("file_uuid")
    studio = _normalize_board_studio_state(dashboard_data.get("studio"))
    file_map = studio.get("file_screen_widgets") if isinstance(studio, dict) else None
    has_file_entry = isinstance(file_map, dict) and active_file_uuid in file_map

    if saved_file == active_file_uuid or has_file_entry:
        return dashboard_data
    return None


def _resolve_board_widgets_for_file(dashboard_data: Dict[str, Any], active_file_uuid: str) -> List[Dict[str, Any]]:
    """Resolve the widget blueprint for the active file."""
    if not isinstance(dashboard_data, dict):
        return []

    studio = _normalize_board_studio_state(dashboard_data.get("studio"))
    active_screen_id = studio.get("active_screen_id")

    file_map = studio.get("file_screen_widgets")
    if isinstance(file_map, dict) and isinstance(active_file_uuid, str) and active_file_uuid:
        by_file = file_map.get(active_file_uuid)
        if isinstance(by_file, dict):
            widgets = by_file.get(active_screen_id)
            if isinstance(widgets, list):
                return [w for w in widgets if isinstance(w, dict)]

    screen_widgets = studio.get("screen_widgets")
    if isinstance(screen_widgets, dict):
        widgets = screen_widgets.get(active_screen_id)
        if isinstance(widgets, list):
            return [w for w in widgets if isinstance(w, dict)]

    widgets = dashboard_data.get("widgets")
    if isinstance(widgets, list):
        return [w for w in widgets if isinstance(w, dict)]

    return []


def _save_board_widgets(board_id: str, dashboard_data: dict, db: DatabaseManager, studio_state: Any = None):
    """Persist widget layout to insight_boards.widgets_json."""
    try:
        normalized_studio = _normalize_board_studio_state(studio_state if studio_state is not None else dashboard_data.get("studio"))
        dashboard_data = dict(dashboard_data)
        dashboard_data["studio"] = normalized_studio
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE insight_boards SET widgets_json = %s, studio_state_json = %s WHERE board_id = %s",
                    (json.dumps(dashboard_data, default=str), json.dumps(normalized_studio, default=str), board_id)
                )
            conn.commit()
    except Exception as e:
        logger.error(f"Failed to save board widgets: {e}")


def _preserve_board_widget_fields(base_widget: dict, cloned_widget: dict) -> dict:
    """Preserve custom fields from base widget in cloned result."""
    if not isinstance(base_widget, dict) or not isinstance(cloned_widget, dict):
        return cloned_widget
    preserved = dict(cloned_widget)
    preserved.setdefault("id", base_widget.get("id"))
    preserved.setdefault("gridW", base_widget.get("gridW", 3))
    preserved.setdefault("gridH", base_widget.get("gridH", 2))
    preserved.setdefault("gridX", base_widget.get("gridX", 0))
    preserved.setdefault("gridY", base_widget.get("gridY", 0))
    return preserved


def _build_board_dashboard_payload(
    widgets: list,
    file_uuid: str,
    old_data: dict,
    studio_state: dict,
) -> dict:
    """Build complete dashboard payload for boards table."""
    return {
        "status": "success",
        "filename": old_data.get("filename", ""),
        "file_uuid": file_uuid,
        "total_rows": old_data.get("total_rows", 0),
        "total_columns": old_data.get("total_columns", 0),
        "widgets": widgets,
        "fingerprint": old_data.get("fingerprint", {}),
        "studio": studio_state,
    }


def _get_trace_ids() -> tuple:
    """Return (trace_id, trace_url) from current context."""
    try:
        _tid = langfuse_context.get_current_trace_id()
        _turl = langfuse_context.get_current_trace_url() if _tid else None
        return _tid, _turl
    except:
        return None, None


# ============================================================================
# ENDPOINTS
# ============================================================================

@router.get("", response_model=BoardListResponse)
@observe(name="board.list")
async def list_boards(
    db: DatabaseManager = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """List all Insight Boards for the current user."""
    try:
        with db.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT b.board_id, b.name, b.created_on, b.active_file_uuid, "
                    "b.is_shared, b.share_token, "
                    "(SELECT COUNT(*) FROM board_files bf WHERE bf.board_id = b.board_id) AS file_count "
                    "FROM insight_boards b WHERE b.created_by = %s ORDER BY b.created_on DESC",
                    (current_user.get("id"),)
                )
                rows = cur.fetchall()
        boards = [
            BoardInfo(
                board_id=r["board_id"],
                name=r["name"],
                created_on=str(r["created_on"]) if r.get("created_on") else None,
                active_file_uuid=r.get("active_file_uuid"),
                is_shared=r.get("is_shared", False),
                share_token=r.get("share_token"),
                file_count=r.get("file_count", 0),
            )
            for r in rows
        ]
        return BoardListResponse(boards=boards)
    except Exception as e:
        logger.error(f"Failed to list boards: {e}")
        raise HTTPException(status_code=500, detail="Error listing boards")


@router.post("", response_model=BoardInfo)
@observe(name="board.create")
async def create_board(
    request: BoardCreateRequest,
    db: DatabaseManager = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Create a new empty Insight Board."""
    board_id = str(uuid.uuid4())
    try:
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO insight_boards (board_id, name, created_by) VALUES (%s, %s, %s)",
                    (board_id, request.name, current_user.get("id"))
                )
            conn.commit()
        return BoardInfo(board_id=board_id, name=request.name)
    except Exception as e:
        logger.error(f"Failed to create board: {e}")
        raise HTTPException(status_code=500, detail="Error creating board")


@router.delete("/{board_id}")
@observe(name="board.delete")
async def delete_board(
    board_id: str,
    db: DatabaseManager = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Delete an Insight Board and its files (CASCADE)."""
    try:
        with db.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT board_id FROM insight_boards WHERE board_id = %s AND created_by = %s",
                    (board_id, current_user.get("id"))
                )
                if not cur.fetchone():
                    raise HTTPException(status_code=404, detail="Board not found")
                cur.execute("SELECT table_name FROM board_files WHERE board_id = %s", (board_id,))
                for row in cur.fetchall():
                    cur.execute(f"DROP TABLE IF EXISTS {row['table_name']}")
                cur.execute("DELETE FROM insight_boards WHERE board_id = %s", (board_id,))
            conn.commit()
        return {"status": "success", "board_id": board_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete board: {e}")
        raise HTTPException(status_code=500, detail="Error deleting board")


@router.post("/{board_id}/upload")
@observe(name="board.upload_file")
async def upload_board_file(
    board_id: str,
    file: UploadFile = File(...),
    db: DatabaseManager = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Lightweight file upload for Insight Boards — DataFrame only, no embeddings."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="File name is required")

    allowed_extensions = ['.xlsx', '.csv', '.xls']
    file_ext = os.path.splitext(file.filename)[1].lower()
    if file_ext not in allowed_extensions:
        raise HTTPException(status_code=400, detail=f"Only {allowed_extensions} files are supported")

    with db.get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT board_id, template_columns FROM insight_boards WHERE board_id = %s AND created_by = %s",
                (board_id, current_user.get("id"))
            )
            board_row = cur.fetchone()
            if not board_row:
                raise HTTPException(status_code=404, detail="Board not found")

    existing_template = board_row.get("template_columns")
    if isinstance(existing_template, str):
        try:
            existing_template = json.loads(existing_template)
        except Exception:
            existing_template = None

    file_uuid = str(uuid.uuid4())
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as tmp:
            contents = await file.read()
            tmp.write(contents)
            tmp_path = tmp.name

        agent = HybridAgent.from_dataframe(tmp_path, file.filename, file_uuid)
        stats_json = json.dumps(agent.column_stats, default=str)

        file_columns = {c: str(agent.df[c].dtype) for c in agent.df.columns}

        compatible = True
        missing_columns: list[str] = []
        extra_columns: list[str] = []
        is_first_file = existing_template is None

        if not is_first_file:
            template_col_names = set(existing_template.keys())
            file_col_names = set(file_columns.keys())
            missing_columns = sorted(template_col_names - file_col_names)
            extra_columns = sorted(file_col_names - template_col_names)
            compatible = len(missing_columns) == 0

            if not compatible:
                if tmp_path and os.path.exists(tmp_path):
                    os.unlink(tmp_path)
                raise HTTPException(
                    status_code=400,
                    detail=f"File is incompatible with the board template. Missing columns: {', '.join(missing_columns)}"
                )

        with db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO board_files (file_uuid, board_id, filename, table_name, column_stats) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (file_uuid, board_id, file.filename, agent.table_name, stats_json)
                )
                if is_first_file:
                    cur.execute(
                        "UPDATE insight_boards SET active_file_uuid = %s, template_columns = %s "
                        "WHERE board_id = %s AND active_file_uuid IS NULL",
                        (file_uuid, json.dumps(file_columns), board_id)
                    )
                else:
                    cur.execute(
                        "UPDATE insight_boards SET active_file_uuid = %s "
                        "WHERE board_id = %s AND active_file_uuid IS NULL",
                        (file_uuid, board_id)
                    )
            conn.commit()

        return {
            "status": "success",
            "file_uuid": file_uuid,
            "filename": file.filename,
            "table_name": agent.table_name,
            "rows": len(agent.df),
            "columns": agent.columns,
            "compatible": compatible,
            "is_first_file": is_first_file,
            "missing_columns": missing_columns,
            "extra_columns": extra_columns,
        }
    except HTTPException:
        raise
    except Exception as e:
        log_full_exception(e, "Board file upload failed")
        raise HTTPException(status_code=500, detail=user_facing_error_message(e))
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)


@router.get("/{board_id}/dashboard")
@observe(name="board.get_dashboard")
async def get_board_dashboard(
    board_id: str,
    db: DatabaseManager = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Load an Insight Board's dashboard."""
    try:
        with db.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT board_id, name, created_on, active_file_uuid, "
                    "widgets_json, studio_state_json, is_shared, share_token, published_file_uuid "
                    "FROM insight_boards WHERE board_id = %s",
                    (board_id,)
                )
                board = cur.fetchone()
                if not board:
                    raise HTTPException(status_code=404, detail="Board not found")

                if current_user.get("role") != "admin":
                    cur.execute(
                        "SELECT 1 FROM insight_boards WHERE board_id = %s AND created_by = %s",
                        (board_id, current_user.get("id"))
                    )
                    if not cur.fetchone():
                        raise HTTPException(status_code=403, detail="Access denied")

                cur.execute(
                    "SELECT file_uuid, filename, table_name, column_stats, created_on "
                    "FROM board_files WHERE board_id = %s ORDER BY created_on DESC",
                    (board_id,)
                )
                files = []
                for r in cur.fetchall():
                    row = dict(r)
                    metadata = _extract_board_file_metadata(row.pop("column_stats", None))
                    row.update(metadata)
                    files.append(row)

        active_file_uuid = board.get("active_file_uuid")
        saved_widgets = board.get("widgets_json")
        saved_studio_state = board.get("studio_state_json")
        normalized_studio_state = _normalize_board_studio_state(saved_studio_state)

        board_as_project = {
            "project_id": board["board_id"],
            "name": board["name"],
            "created_on": str(board["created_on"]) if board.get("created_on") else None,
            "color": None,
            "is_dashboard": True,
            "active_file_uuid": active_file_uuid,
            "is_shared": board.get("is_shared", False),
            "share_token": board.get("share_token"),
            "screen_share_tokens": normalized_studio_state.get("screen_share_tokens", {}),
            "published_file_uuid": board.get("published_file_uuid"),
        }

        _tid, _turl = _get_trace_ids()

        if not active_file_uuid or not files:
            return {"project": board_as_project, "files": files, "dashboard_data": None, "trace_id": _tid, "trace_url": _turl}

        dashboard_data = _resolve_saved_board_dashboard(saved_widgets, active_file_uuid)
        if dashboard_data:
            dashboard_data["studio"] = _normalize_board_studio_state(dashboard_data.get("studio") or saved_studio_state)
            return {"project": board_as_project, "files": files, "dashboard_data": dashboard_data, "trace_id": _tid, "trace_url": _turl}

        board_file = next((f for f in files if f["file_uuid"] == active_file_uuid), None)
        if not board_file:
            return {"project": board_as_project, "files": files, "dashboard_data": None, "trace_id": _tid, "trace_url": _turl}

        _agent = _load_board_agent(active_file_uuid, board_id, db)
        if _agent:
            dashboard_data = _agent.generate_kpi_dashboard()
            dashboard_data["studio"] = _normalize_board_studio_state(saved_studio_state)
            _save_board_widgets(board_id, dashboard_data, db, dashboard_data.get("studio"))
            return {"project": board_as_project, "files": files, "dashboard_data": dashboard_data, "trace_id": _tid, "trace_url": _turl}

        return {"project": board_as_project, "files": files, "dashboard_data": None, "trace_id": _tid, "trace_url": _turl}
    except HTTPException:
        raise
    except Exception as e:
        log_full_exception(e, "Failed to get board dashboard")
        raise HTTPException(status_code=500, detail="Error loading board dashboard")


@router.post("/{board_id}/dashboard/save")
@observe(name="board.save_dashboard")
async def save_board_dashboard(
    board_id: str,
    request: BoardDashboardSaveRequest,
    db: DatabaseManager = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Save Insight Board widget layout."""
    widgets = request.widgets or []
    try:
        with db.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT board_id, active_file_uuid, widgets_json, studio_state_json, is_shared FROM insight_boards WHERE board_id = %s AND created_by = %s",
                    (board_id, current_user.get("id"))
                )
                board = cur.fetchone()
                if not board:
                    raise HTTPException(status_code=404, detail="Board not found")

                old_data = board.get("widgets_json") or {}
                if isinstance(old_data, str):
                    try: old_data = json.loads(old_data)
                    except: old_data = {}

                studio_state = _normalize_board_studio_state({
                    "screens": [screen.dict() for screen in request.screens] if request.screens else None,
                    "active_screen_id": request.active_screen_id,
                    "active_theme": request.active_theme,
                    "thumbnail_version": request.thumbnail_version,
                    "screen_widgets": request.screen_widgets,
                    "file_screen_widgets": request.file_screen_widgets,
                    "file_screen_needs_generation": request.file_screen_needs_generation,
                    "file_screen_pending_templates": request.file_screen_pending_templates,
                    "screen_thumbnails": request.screen_thumbnails,
                    "file_screen_thumbnails": request.file_screen_thumbnails,
                    "screen_share_tokens": (old_data.get("studio") or {}).get("screen_share_tokens") if isinstance(old_data.get("studio"), dict) else None,
                    "design": request.design,
                })

                if bool(board.get("is_shared")):
                    screens = studio_state.get("screens") if isinstance(studio_state, dict) else []
                    valid_screen_ids = {
                        s.get("id") for s in screens
                        if isinstance(s, dict) and isinstance(s.get("id"), str)
                    }
                    existing_tokens = dict(studio_state.get("screen_share_tokens") or {}) if isinstance(studio_state, dict) else {}
                    used_tokens: set[str] = set()
                    for screen_id in valid_screen_ids:
                        token_value = existing_tokens.get(screen_id)
                        token_value = token_value.strip() if isinstance(token_value, str) else ""
                        if not token_value or token_value in used_tokens:
                            token_value = secrets.token_urlsafe(16)
                            while token_value in used_tokens:
                                token_value = secrets.token_urlsafe(16)
                        existing_tokens[screen_id] = token_value
                        used_tokens.add(token_value)
                    studio_state["screen_share_tokens"] = {
                        sid: tok for sid, tok in existing_tokens.items()
                        if sid in valid_screen_ids and isinstance(tok, str) and tok
                    }

                dashboard_data = _build_board_dashboard_payload(
                    widgets=widgets,
                    file_uuid=board.get("active_file_uuid") or old_data.get("file_uuid", ""),
                    old_data=old_data,
                    studio_state=studio_state,
                )
                cur.execute(
                    "UPDATE insight_boards SET widgets_json = %s, studio_state_json = %s WHERE board_id = %s",
                    (json.dumps(dashboard_data, default=str), json.dumps(studio_state, default=str), board_id)
                )
            conn.commit()
        return {"status": "success", "message": "Board dashboard saved", "studio": studio_state}
    except HTTPException:
        raise
    except Exception as e:
        log_full_exception(e, "Failed to save board dashboard")
        raise HTTPException(status_code=500, detail="Error saving board dashboard")


@router.put("/{board_id}/active-file")
@observe(name="board.update_active_file")
async def update_board_active_file(
    board_id: str,
    request: ActiveFileRequest,
    db: DatabaseManager = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Switch the active data source for an Insight Board."""
    try:
        with db.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT active_file_uuid, is_shared, share_token FROM insight_boards WHERE board_id = %s AND created_by = %s",
                    (board_id, current_user.get("id"))
                )
                board_state = cur.fetchone()
                if not board_state:
                    raise HTTPException(status_code=404, detail="Board not found or unauthorized")

                cur.execute(
                    "SELECT 1 FROM board_files WHERE file_uuid = %s AND board_id = %s",
                    (request.file_uuid, board_id)
                )
                if not cur.fetchone():
                    raise HTTPException(status_code=400, detail="File does not belong to this board")

                old_file_uuid = board_state.get("active_file_uuid")
                old_share_token = board_state.get("share_token")
                file_changed = old_file_uuid != request.file_uuid
                next_share_token = old_share_token
                if file_changed and (old_share_token or board_state.get("is_shared")):
                    cur.execute(
                        """
                        SELECT share_token
                        FROM insight_boards
                        WHERE created_by = %s
                          AND active_file_uuid = %s
                          AND board_id <> %s
                          AND share_token IS NOT NULL
                        ORDER BY is_shared DESC, created_on DESC
                        LIMIT 1
                        """,
                        (current_user.get("id"), request.file_uuid, board_id),
                    )
                    token_row = cur.fetchone()
                    next_share_token = token_row.get("share_token") if token_row and token_row.get("share_token") else secrets.token_urlsafe(16)

                cur.execute(
                    "UPDATE insight_boards SET active_file_uuid = %s, share_token = %s WHERE board_id = %s AND created_by = %s RETURNING board_id",
                    (request.file_uuid, next_share_token, board_id, current_user.get("id"))
                )
                if not cur.fetchone():
                    raise HTTPException(status_code=404, detail="Board not found or unauthorized")
            conn.commit()

        with db.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT widgets_json, studio_state_json FROM insight_boards WHERE board_id = %s", (board_id,))
                row = cur.fetchone()
                saved_data = row.get("widgets_json") if row else None
                saved_studio_state = row.get("studio_state_json") if row else None

        _agent = _load_board_agent(request.file_uuid, board_id, db)
        if not _agent:
            _tid, _turl = _get_trace_ids()
            return {"status": "success", "active_file_uuid": request.file_uuid, "dashboard_data": None, "trace_id": _tid, "trace_url": _turl}

        if saved_data:
            if isinstance(saved_data, str):
                try: saved_data = json.loads(saved_data)
                except: saved_data = {}
            source_blueprint_file_uuid = old_file_uuid or request.file_uuid
            base_widgets = _resolve_board_widgets_for_file(saved_data, source_blueprint_file_uuid)
            if base_widgets:
                cloned = [_preserve_board_widget_fields(base_widget, cloned_widget) for base_widget, cloned_widget in zip(base_widgets, _agent.clone_widgets_from_blueprints(base_widgets))]
                fp = _agent._build_file_fingerprint()
                dashboard_data = _agent._build_response_envelope(cloned, fp)
                dashboard_data["studio"] = _normalize_board_studio_state(saved_data.get("studio") or saved_studio_state)
                _save_board_widgets(board_id, dashboard_data, db, dashboard_data.get("studio"))
                _tid, _turl = _get_trace_ids()
                return {"status": "success", "active_file_uuid": request.file_uuid, "dashboard_data": dashboard_data, "trace_id": _tid, "trace_url": _turl}

        dashboard_data = _agent.generate_kpi_dashboard()
        dashboard_data["studio"] = _normalize_board_studio_state(saved_studio_state)
        _save_board_widgets(board_id, dashboard_data, db, dashboard_data.get("studio"))
        _tid, _turl = _get_trace_ids()
        return {"status": "success", "active_file_uuid": request.file_uuid, "dashboard_data": dashboard_data, "trace_id": _tid, "trace_url": _turl}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to switch board active file: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{board_id}/active-file-stream")
@observe(name="board.update_active_file_stream")
async def update_board_active_file_stream(
    board_id: str,
    request: ActiveFileRequest,
    db: DatabaseManager = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Stream widgets one-by-one as NDJSON for side-by-side loading."""
    with db.get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT active_file_uuid, is_shared, share_token FROM insight_boards WHERE board_id = %s AND created_by = %s",
                (board_id, current_user.get("id"))
            )
            board_state = cur.fetchone()
            if not board_state:
                raise HTTPException(status_code=404, detail="Board not found or unauthorized")

            cur.execute(
                "SELECT 1 FROM board_files WHERE file_uuid = %s AND board_id = %s",
                (request.file_uuid, board_id)
            )
            if not cur.fetchone():
                raise HTTPException(status_code=400, detail="File does not belong to this board")

            old_file_uuid = board_state.get("active_file_uuid")
            old_share_token = board_state.get("share_token")
            file_changed = old_file_uuid != request.file_uuid
            next_share_token = old_share_token
            if file_changed and (old_share_token or board_state.get("is_shared")):
                cur.execute(
                    """
                    SELECT share_token
                    FROM insight_boards
                    WHERE created_by = %s
                      AND active_file_uuid = %s
                      AND board_id <> %s
                      AND share_token IS NOT NULL
                    ORDER BY is_shared DESC, created_on DESC
                    LIMIT 1
                    """,
                    (current_user.get("id"), request.file_uuid, board_id),
                )
                token_row = cur.fetchone()
                next_share_token = token_row.get("share_token") if token_row and token_row.get("share_token") else secrets.token_urlsafe(16)

            cur.execute(
                "UPDATE insight_boards SET active_file_uuid = %s, share_token = %s WHERE board_id = %s AND created_by = %s RETURNING board_id",
                (request.file_uuid, next_share_token, board_id, current_user.get("id"))
            )
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Board not found or unauthorized")
        conn.commit()

    with db.get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT widgets_json, studio_state_json FROM insight_boards WHERE board_id = %s", (board_id,))
            row = cur.fetchone()
            saved_data = row.get("widgets_json") if row else None
            saved_studio_state = row.get("studio_state_json") if row else None

    _agent = _load_board_agent(request.file_uuid, board_id, db)
    if not _agent:
        raise HTTPException(status_code=404, detail="Could not load agent for file")

    base_widgets = []
    if saved_data:
        if isinstance(saved_data, str):
            try:
                saved_data = json.loads(saved_data)
            except Exception:
                saved_data = {}
        source_blueprint_file_uuid = old_file_uuid or request.file_uuid
        base_widgets = _resolve_board_widgets_for_file(saved_data, source_blueprint_file_uuid)

    def _stream_widgets():
        all_cloned = []
        normalized_studio = _normalize_board_studio_state((saved_data or {}).get("studio") if isinstance(saved_data, dict) else saved_studio_state)
        if base_widgets:
            for index, widget in enumerate(_agent.clone_widgets_from_blueprints_iter(base_widgets)):
                base_widget = base_widgets[index] if index < len(base_widgets) else {}
                preserved_widget = _preserve_board_widget_fields(base_widget, widget)
                all_cloned.append(preserved_widget)
                yield json.dumps({"type": "widget", "widget": preserved_widget}, default=str) + "\n"
        else:
            dashboard_data = _agent.generate_kpi_dashboard()
            widgets = dashboard_data.get("widgets", []) if dashboard_data else []
            for w in widgets:
                all_cloned.append(w)
                yield json.dumps({"type": "widget", "widget": w}, default=str) + "\n"

        fp = _agent._build_file_fingerprint()
        dashboard_data = _agent._build_response_envelope(all_cloned, fp)
        dashboard_data["studio"] = normalized_studio
        _save_board_widgets(board_id, dashboard_data, db, normalized_studio)
        _tid, _turl = _get_trace_ids()
        yield json.dumps({
            "type": "done",
            "active_file_uuid": request.file_uuid,
            "fingerprint": fp,
            "total_widgets": len(all_cloned),
            "trace_id": _tid,
            "trace_url": _turl,
        }, default=str) + "\n"

    return StreamingResponse(_stream_widgets(), media_type="application/x-ndjson")


@router.post("/{board_id}/share")
@observe(name="board.toggle_share")
async def toggle_board_share(
    board_id: str,
    body: BoardPublishRequest = BoardPublishRequest(),
    db: DatabaseManager = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Toggle public sharing for an Insight Board."""
    try:
        with db.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT is_shared, share_token, active_file_uuid, widgets_json, studio_state_json FROM insight_boards WHERE board_id = %s AND created_by = %s",
                    (board_id, current_user.get("id"))
                )
                board = cur.fetchone()
                if not board:
                    raise HTTPException(status_code=404, detail="Board not found")

                new_is_shared = not board["is_shared"]
                share_token = board["share_token"]

                saved_data = board.get("widgets_json")
                if isinstance(saved_data, str):
                    try:
                        saved_data = json.loads(saved_data)
                    except Exception:
                        saved_data = {}
                elif not isinstance(saved_data, dict):
                    saved_data = {}

                studio_state = _normalize_board_studio_state(
                    board.get("studio_state_json")
                    or saved_data.get("studio")
                )
                screen_ids = [
                    s.get("id") for s in studio_state.get("screens", [])
                    if isinstance(s, dict) and isinstance(s.get("id"), str)
                ]
                active_screen_id = studio_state.get("active_screen_id")
                requested_screen_id = body.active_screen_id if isinstance(body.active_screen_id, str) else None
                if requested_screen_id in screen_ids:
                    active_screen_id = requested_screen_id
                    studio_state["active_screen_id"] = requested_screen_id
                if active_screen_id not in screen_ids:
                    active_screen_id = screen_ids[0] if screen_ids else None

                screen_tokens: Dict[str, str] = dict(studio_state.get("screen_share_tokens") or {})
                if new_is_shared:
                    used_tokens: set[str] = set()
                    for screen_id in screen_ids:
                        token_value = screen_tokens.get(screen_id)
                        token_value = token_value.strip() if isinstance(token_value, str) else ""
                        if not token_value or token_value in used_tokens:
                            token_value = secrets.token_urlsafe(16)
                            while token_value in used_tokens:
                                token_value = secrets.token_urlsafe(16)
                        screen_tokens[screen_id] = token_value
                        used_tokens.add(token_value)
                    if active_screen_id and isinstance(screen_tokens.get(active_screen_id), str):
                        share_token = screen_tokens.get(active_screen_id)
                    elif not share_token:
                        share_token = secrets.token_urlsafe(16)
                        if active_screen_id:
                            screen_tokens[active_screen_id] = share_token

                if active_screen_id and isinstance(body.widgets, list):
                    active_file_uuid = board.get("active_file_uuid")
                    screen_widgets = studio_state.get("screen_widgets")
                    if not isinstance(screen_widgets, dict):
                        screen_widgets = {}
                    screen_widgets[active_screen_id] = [w for w in body.widgets if isinstance(w, dict)]
                    studio_state["screen_widgets"] = screen_widgets

                    if isinstance(active_file_uuid, str) and active_file_uuid:
                        file_screen_widgets = studio_state.get("file_screen_widgets")
                        if not isinstance(file_screen_widgets, dict):
                            file_screen_widgets = {}
                        by_file = file_screen_widgets.get(active_file_uuid)
                        if not isinstance(by_file, dict):
                            by_file = {}
                        by_file[active_screen_id] = [w for w in body.widgets if isinstance(w, dict)]
                        file_screen_widgets[active_file_uuid] = by_file
                        studio_state["file_screen_widgets"] = file_screen_widgets

                studio_state["screen_share_tokens"] = {
                    sid: tok for sid, tok in screen_tokens.items()
                    if sid in set(screen_ids) and isinstance(tok, str) and tok
                }
                saved_data["studio"] = studio_state

                published_file_uuid = None
                published_widgets_json = None

                if new_is_shared:
                    published_file_uuid = board.get("active_file_uuid")
                    if body.widgets is not None:
                        published_widgets_json = {
                            "widgets": body.widgets,
                            "fingerprint": (saved_data or {}).get("fingerprint") if isinstance(saved_data, dict) else None,
                            "studio": studio_state,
                        }
                    else:
                        published_widgets_json = saved_data

                cur.execute(
                    """UPDATE insight_boards
                       SET is_shared = %s, share_token = %s,
                           published_file_uuid = %s, published_widgets_json = %s,
                           widgets_json = %s, studio_state_json = %s
                       WHERE board_id = %s""",
                    (
                        new_is_shared,
                        share_token,
                        published_file_uuid,
                        json.dumps(published_widgets_json) if published_widgets_json is not None else None,
                        json.dumps(saved_data, default=str),
                        json.dumps(studio_state, default=str),
                        board_id,
                    )
                )
            conn.commit()

        return {
            "status": "success",
            "is_shared": new_is_shared,
            "share_token": share_token if new_is_shared else None,
            "share_tokens_by_screen": studio_state.get("screen_share_tokens", {}) if new_is_shared else {},
            "active_screen_id": active_screen_id if new_is_shared else None,
            "published_file_uuid": published_file_uuid if new_is_shared else None,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to toggle board share: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{board_id}/publish")
@observe(name="board.publish")
async def publish_board(
    board_id: str,
    body: BoardPublishRequest = BoardPublishRequest(),
    db: DatabaseManager = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Freeze current board state as published snapshot for shared viewers."""
    try:
        with db.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT active_file_uuid, widgets_json FROM insight_boards WHERE board_id = %s AND created_by = %s",
                    (board_id, current_user.get("id"))
                )
                board = cur.fetchone()
                if not board:
                    raise HTTPException(status_code=404, detail="Board not found or unauthorized")

                if body.widgets is not None:
                    saved_data = board.get("widgets_json")
                    if isinstance(saved_data, str):
                        try: saved_data = json.loads(saved_data)
                        except: saved_data = {}
                    elif saved_data is None:
                        saved_data = {}
                    publish_payload = {
                        "status": "success",
                        "file_uuid": board.get("active_file_uuid"),
                        "widgets": body.widgets,
                        "fingerprint": saved_data.get("fingerprint", {}),
                    }
                    widgets_for_publish = json.dumps(publish_payload, default=str)
                else:
                    widgets_for_publish = board.get("widgets_json")
                    if isinstance(widgets_for_publish, dict):
                        widgets_for_publish = json.dumps(widgets_for_publish)
                cur.execute(
                    """UPDATE insight_boards
                       SET published_file_uuid = %s, published_widgets_json = %s::jsonb
                       WHERE board_id = %s""",
                    (board.get("active_file_uuid"), widgets_for_publish, board_id)
                )
            conn.commit()

        return {"status": "success", "message": "Board published successfully", "published_file_uuid": board.get("active_file_uuid")}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to publish board: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{board_id}/unpublish")
@observe(name="board.unpublish")
async def unpublish_board(
    board_id: str,
    db: DatabaseManager = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Clear published snapshot so shared viewers see the live dashboard state."""
    try:
        with db.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "UPDATE insight_boards SET published_file_uuid = NULL, published_widgets_json = NULL "
                    "WHERE board_id = %s AND created_by = %s RETURNING board_id",
                    (board_id, current_user.get("id"))
                )
                if not cur.fetchone():
                    raise HTTPException(status_code=404, detail="Board not found or unauthorized")
            conn.commit()
        return {"status": "success", "message": "Published snapshot cleared — shared view is now live"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to unpublish board: {e}")
        raise HTTPException(status_code=500, detail=str(e))
