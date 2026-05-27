from fastapi import APIRouter, Depends, HTTPException, Request
from typing import Optional
from datetime import datetime, timedelta
import uuid
import os
import json

from app.dependencies import get_db
from app.schemas import SharedDashboardFilterRequest
from app.core import DatabaseManager
from app.utils.logging import log_full_exception, user_facing_error_message
from app.core.auth import get_current_user
from app.services.langfuse_sso import (
    build_langfuse_project_url as _build_langfuse_project_url,
    build_langfuse_session_url as _build_langfuse_session_url,
    build_langfuse_trace_url as _build_langfuse_trace_url,
    build_langfuse_traces_url as _build_langfuse_traces_url,
    load_langfuse_cookies_from_redis as _load_langfuse_cookies_from_redis,
    _user_langfuse_cookies,
    _sso_keys,
)
from app.dependencies import resolve_file_identifier, enforce_file_access, get_agent
from app.config import logger
from psycopg2.extras import RealDictCursor

try:
    from app.config import observe
except ImportError:
    def observe(_func=None, *, name: str = "", **kwargs):
        def decorator(func):
            return func
        return _func if _func else decorator

# Helper function imports (will be available once projects.py and boards.py are extracted)
load_project_dashboard = None
_load_board_agent = None
_normalize_board_studio_state = None

try:
    from app.routers.projects import load_project_dashboard
except ImportError:
    pass

try:
    from app.routers.boards import _load_board_agent, _normalize_board_studio_state
except ImportError:
    pass

router = APIRouter(tags=["langfuse", "share"])


@router.get("/api/langfuse-token")
@observe(name="langfuse.token")
async def get_langfuse_token(
    request: Request,
    session_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    target: Optional[str] = None,   # "session" | "traces" | "project" (default)
    current_user: dict = Depends(get_current_user)
):
    """
    Step 1 of per-user SSO (requires Vue JWT).
    - Looks up the cached Langfuse session cookies for the logged-in user.
    - Mints a short-lived one-time key tied to that user's email.
    - Returns a `sso_url` pointing at /api/langfuse-sso?key=<key> on
      localhost:8000.  Vue opens that URL in a new tab.
    If the background task (fired at login) hasn't finished yet, returns 503
    so the Vue 'Refresh session' button can retry in a moment.
    """
    email = current_user["email"]
    
    # Check in-memory cache first, then Redis (survives restarts)
    cookies = _user_langfuse_cookies.get(email)
    if not cookies or not any("session" in k.lower() for k in cookies):
        cookies = _load_langfuse_cookies_from_redis(email)
        if cookies and any("session" in k.lower() for k in cookies):
            _user_langfuse_cookies[email] = cookies  # Populate in-memory cache
            logger.info(f"[langfuse-token] Restored cookies from Redis for {email}")
        else:
            # Auto-refresh: try to re-establish Langfuse session before giving up
            from app.services.langfuse_sso import ensure_langfuse_user
            user_password = current_user.get("password", email)  # fallback
            refreshed = await ensure_langfuse_user(email, user_password, current_user.get("name", ""))
            if refreshed:
                cookies = _user_langfuse_cookies.get(email)
                logger.info(f"[langfuse-token] Auto-refreshed Langfuse session for {email}")
            if not cookies or not any("session" in k.lower() for k in (cookies or {})):
                raise HTTPException(
                    status_code=503,
                    detail=(
                        "Langfuse session not ready yet. "
                        "Wait a moment and click \"Refresh session\"."
                    ),
                )

    key = str(uuid.uuid4())
    if trace_id:
        target_langfuse_url = _build_langfuse_trace_url(trace_id)
    elif target == "traces":
        target_langfuse_url = _build_langfuse_traces_url(session_id)
    elif session_id:
        target_langfuse_url = _build_langfuse_session_url(session_id)
    else:
        target_langfuse_url = _build_langfuse_traces_url()
    _sso_keys[key] = (email, datetime.utcnow() + timedelta(seconds=60), target_langfuse_url)

    configured_fastapi_base = os.getenv("FASTAPI_BASE_URL", "").rstrip("/")
    # Prefer request-derived host so remote devices never get localhost links.
    forwarded_host = (request.headers.get("x-forwarded-host") or "").split(",")[0].strip()
    forwarded_proto = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip()
    request_host = forwarded_host or request.headers.get("host") or request.url.netloc
    request_proto = forwarded_proto or request.url.scheme
    request_fastapi_base = f"{request_proto}://{request_host}".rstrip("/")

    if configured_fastapi_base and "localhost" not in configured_fastapi_base and "127.0.0.1" not in configured_fastapi_base:
        fastapi_base = configured_fastapi_base
    else:
        fastapi_base = request_fastapi_base

    return {
        "sso_url": f"{fastapi_base}/api/langfuse-sso?key={key}",
        "langfuse_url": target_langfuse_url,
        "session_id": session_id,
    }


@router.get("/api/langfuse-sso", include_in_schema=False)
@observe(name="langfuse.sso_redirect")
async def langfuse_sso_redirect(key: str):
    """
    Step 2 of SSO (no JWT required — the one-time key IS the credential).
    - Validates the key (consumed immediately, 60 s TTL).
    - Sets every Langfuse NextAuth session cookie in the browser response.
    - Issues a 302 redirect to localhost:3000.
    
    Because this response comes from localhost:8000 and the redirect target
    is also localhost:3000, both share the `localhost` cookie domain — so
    the browser carries the freshly-set cookies into the redirect and
    Langfuse sees a valid session without showing a login page.
    """
    # Validate one-time key  (entry is (email, expiry, target_url))
    entry = _sso_keys.pop(key, None)           # consume immediately
    if entry is None:
        raise HTTPException(status_code=401, detail="SSO link expired or invalid. Please go back and try again.")
    if len(entry) >= 3:
        sso_email, expiry, target_langfuse_url = entry
    else:
        sso_email, expiry = entry
        target_langfuse_url = _build_langfuse_project_url()
    if datetime.utcnow() > expiry:
        raise HTTPException(status_code=401, detail="SSO link has expired. Please go back and try again.")

    cookies = _user_langfuse_cookies.get(sso_email, {})
    langfuse_url = target_langfuse_url or _build_langfuse_project_url()

    from fastapi.responses import RedirectResponse as _RR
    response = _RR(url=langfuse_url, status_code=302)

    # Plant the user's Langfuse session cookies.  No `domain=` so they become
    # host-only for `localhost` and are sent to every localhost port.
    for name, value in cookies.items():
        response.set_cookie(
            key=name,
            value=value,
            httponly=True,
            samesite="lax",
            path="/",
            secure=False,
        )
    return response


@router.get("/api/share/{token}")
@observe(name="share.get_dashboard")
async def get_shared_dashboard(
    token: str,
    db: DatabaseManager = Depends(get_db)
):
    """Public read-only endpoint for shared dashboards (projects AND boards)."""
    try:
        with db.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Try projects first
                cur.execute(
                    "SELECT project_id, name, active_file_uuid, is_shared, color FROM projects WHERE share_token = %s",
                    (token,)
                )
                proj = cur.fetchone()

                if proj and proj["is_shared"]:
                    # Existing project-based share path
                    if not proj["active_file_uuid"]:
                        return {"project_name": proj["name"], "dashboard_data": None, "widgets": []}

                    dashboard_data = None
                    if load_project_dashboard:
                        try:
                            dashboard_data = load_project_dashboard(proj["project_id"], db)
                        except:
                            pass
                    
                    if not dashboard_data:
                        result = resolve_file_identifier(proj["active_file_uuid"], db)
                        if result:
                            f_uuid, f_name, _table, _uid = result
                            agent = get_agent(file_uuid=f_uuid, filename=f_name, load_existing=True)
                            dashboard_data = agent.generate_kpi_dashboard()

                    return {
                        "project_id": proj["project_id"],
                        "project_name": proj["name"],
                        "color": proj.get("color"),
                        "file_uuid": proj["active_file_uuid"],
                        "dashboard_data": dashboard_data,
                        "source": "project",
                    }

                # Try insight_boards
                cur.execute(
                    """
                    SELECT board_id, name, active_file_uuid, is_shared, widgets_json, studio_state_json, published_file_uuid, published_widgets_json,
                           (
                               SELECT key
                               FROM jsonb_each_text(COALESCE(studio_state_json->'screen_share_tokens', '{}'::jsonb)) AS s(key, value)
                               WHERE s.value = %s
                               LIMIT 1
                           ) AS shared_screen_id
                    FROM insight_boards
                    WHERE share_token = %s
                    """,
                    (token, token)
                )
                board = cur.fetchone()
                shared_screen_id = None
                if board:
                    shared_screen_id = board.get("shared_screen_id")
                if not board:
                    cur.execute(
                        """
                        SELECT board_id, name, active_file_uuid, is_shared, widgets_json, studio_state_json, published_file_uuid, published_widgets_json,
                               (
                                   SELECT key
                                   FROM jsonb_each_text(COALESCE(studio_state_json->'screen_share_tokens', '{}'::jsonb)) AS s(key, value)
                                   WHERE s.value = %s
                                   LIMIT 1
                               ) AS shared_screen_id
                        FROM insight_boards
                        WHERE is_shared = TRUE
                          AND EXISTS (
                              SELECT 1
                              FROM jsonb_each_text(COALESCE(studio_state_json->'screen_share_tokens', '{}'::jsonb)) AS s(key, value)
                              WHERE s.value = %s
                          )
                        LIMIT 1
                        """,
                        (token, token),
                    )
                    board = cur.fetchone()
                    if board:
                        shared_screen_id = board.get("shared_screen_id")
                if not board or not board["is_shared"]:
                    raise HTTPException(status_code=404, detail="Dashboard not found or no longer shared")

                pub_widgets = board.get("published_widgets_json")
                pub_file = board.get("published_file_uuid")
                active_file = board.get("active_file_uuid")

                dashboard_data = None
                if pub_file and pub_widgets:
                    # FROZEN MODE: serve the saved snapshot for the frozen file
                    dashboard_data = pub_widgets if isinstance(pub_widgets, dict) else json.loads(pub_widgets)
                else:
                    # LIVE MODE: serve the latest saved board state (no regeneration)
                    if board.get("widgets_json"):
                        dashboard_data = board["widgets_json"] if isinstance(board["widgets_json"], dict) else json.loads(board["widgets_json"])
                    # Optional fallback if state is missing
                    elif active_file and _load_board_agent:
                        try:
                            _agent = _load_board_agent(active_file, board["board_id"], db)
                            if _agent:
                                dashboard_data = _agent.generate_kpi_dashboard()
                        except:
                            pass

                if shared_screen_id and isinstance(dashboard_data, dict) and _normalize_board_studio_state:
                    try:
                        # Use board studio_state_json as the authoritative source for per-screen mappings.
                        studio = _normalize_board_studio_state(board.get("studio_state_json") or dashboard_data.get("studio"))
                        valid_screen_ids = {
                            s.get("id") for s in studio.get("screens", [])
                            if isinstance(s, dict) and isinstance(s.get("id"), str)
                        }
                        if shared_screen_id in valid_screen_ids:
                            studio["active_screen_id"] = shared_screen_id
                            dashboard_data["studio"] = studio
                            widgets_for_screen = []
                            file_for_widgets = pub_file or active_file
                            file_map = studio.get("file_screen_widgets") if isinstance(studio, dict) else None
                            if isinstance(file_for_widgets, str) and isinstance(file_map, dict):
                                by_file = file_map.get(file_for_widgets)
                                if isinstance(by_file, dict) and isinstance(by_file.get(shared_screen_id), list):
                                    widgets_for_screen = [w for w in by_file.get(shared_screen_id) if isinstance(w, dict)]
                            if not widgets_for_screen:
                                screen_widgets = studio.get("screen_widgets") if isinstance(studio, dict) else None
                                if isinstance(screen_widgets, dict) and isinstance(screen_widgets.get(shared_screen_id), list):
                                    widgets_for_screen = [w for w in screen_widgets.get(shared_screen_id) if isinstance(w, dict)]
                            dashboard_data["widgets"] = widgets_for_screen
                    except:
                        pass

                return {
                    "project_id": board["board_id"],
                    "project_name": board["name"],
                    "color": None,
                    "file_uuid": pub_file or active_file,
                    "dashboard_data": dashboard_data,
                    "screen_id": shared_screen_id,
                    "source": "board",
                }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch shared dashboard: {e}")
        raise HTTPException(status_code=500, detail="Error fetching shared dashboard")


@router.post("/api/share/{token}/filter")
@observe(name="share.filter_dashboard")
async def filter_shared_dashboard(
    token: str,
    request: SharedDashboardFilterRequest,
    db: DatabaseManager = Depends(get_db)
):
    """
    Public cross-filter endpoint for shared dashboards.
    No authentication required — share token acts as the access key.
    Accepts single {column, value} or multi {filters: {col: val, ...}}.
    """
    try:
        # Resolve file_uuid from share token (projects or boards)
        file_uuid = None
        with db.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT active_file_uuid FROM projects WHERE share_token = %s AND is_shared = TRUE",
                    (token,)
                )
                row = cur.fetchone()
                if row:
                    file_uuid = row["active_file_uuid"]
                else:
                    cur.execute(
                        "SELECT COALESCE(published_file_uuid, active_file_uuid) AS file_uuid "
                        "FROM insight_boards WHERE share_token = %s AND is_shared = TRUE",
                        (token,)
                    )
                    brow = cur.fetchone()
                    if brow:
                        file_uuid = brow["file_uuid"]
                    else:
                        cur.execute(
                            """
                            SELECT COALESCE(published_file_uuid, active_file_uuid) AS file_uuid
                            FROM insight_boards
                            WHERE is_shared = TRUE
                              AND EXISTS (
                                  SELECT 1
                                  FROM jsonb_each_text(COALESCE(studio_state_json->'screen_share_tokens', '{}'::jsonb)) AS s(key, value)
                                  WHERE s.value = %s
                              )
                            LIMIT 1
                            """,
                            (token,),
                        )
                        brow = cur.fetchone()
                        if brow:
                            file_uuid = brow["file_uuid"]

        if not file_uuid:
            raise HTTPException(status_code=404, detail="Shared dashboard not found or no longer shared")

        result = resolve_file_identifier(file_uuid, db)
        if not result:
            raise HTTPException(status_code=404, detail="Data file not found")
        f_uuid, filename, _table, _uid = result

        # Check if this is a board file — use lightweight agent loader
        agent = None
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT board_id FROM board_files WHERE file_uuid = %s", (f_uuid,))
                board_row = cur.fetchone()
        if board_row and _load_board_agent:
            try:
                agent = _load_board_agent(f_uuid, board_row[0], db)
            except:
                pass
        if not agent:
            agent = get_agent(file_uuid=f_uuid, filename=filename, load_existing=True)

        filter_payload = {}
        if request.filters:
            filter_payload = {"filters": request.filters}
        elif request.column and request.value:
            filter_payload = {"column": request.column, "value": request.value}
        else:
            raise HTTPException(status_code=400, detail="Provide 'column'+'value' or 'filters' dict")

        filtered = agent.generate_filtered_dashboard(filter_payload)

        if filtered.get("status") == "error":
            raise HTTPException(status_code=400, detail=filtered.get("detail", "Filter failed"))

        return filtered
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Shared dashboard filter failed: {e}")
        raise HTTPException(status_code=500, detail="Filter failed — please try again")


# ═══════════════════════════════════════════════════════════════════════════
# WORKSPACE SHARING (Dashboard + Chat)
# ═══════════════════════════════════════════════════════════════════════════

def _resolve_workspace_from_token(token: str, db: DatabaseManager) -> dict:
    """Resolve a workspace share_token to workspace metadata. Raises 404 if invalid."""
    with db.get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT workspace_id, name, schema_name, is_shared FROM etl_system.workspaces WHERE share_token = %s",
                (token,),
            )
            ws = cur.fetchone()
    if not ws or not ws.get("is_shared"):
        raise HTTPException(status_code=404, detail="Workspace not found or sharing disabled")
    return ws


@router.get("/api/share/workspace/{token}")
@observe(name="share.workspace_dashboard")
async def get_shared_workspace_dashboard(
    token: str,
    db: DatabaseManager = Depends(get_db),
):
    """Public read-only endpoint for shared workspace dashboards. No auth required."""
    try:
        ws = _resolve_workspace_from_token(token, db)
        workspace_id = ws["workspace_id"]

        with db.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Get dashboard
                cur.execute(
                    "SELECT dashboard_id, name, layout_json FROM etl_system.workspace_dashboards WHERE workspace_id = %s LIMIT 1",
                    (workspace_id,),
                )
                dashboard = cur.fetchone()

                if not dashboard:
                    return {
                        "workspace_name": ws["name"],
                        "workspace_id": workspace_id,
                        "widgets": [],
                        "message": "No dashboard exists for this workspace yet.",
                    }

                # Get widgets
                cur.execute(
                    """
                    SELECT widget_id, title, widget_type, chart_type, sql_query, config,
                           origin_question, created_at::text as created_at
                    FROM etl_system.dashboard_widgets
                    WHERE workspace_id = %s
                    ORDER BY created_at ASC
                    """,
                    (workspace_id,),
                )
                saved_widgets = [dict(w) for w in cur.fetchall()]

        # Build client-friendly widget list (same logic as workspace.py)
        widgets_for_client = []
        for w in saved_widgets:
            config = w.get("config")
            if config:
                if isinstance(config, str):
                    try:
                        config = json.loads(config)
                    except Exception:
                        config = {}
            if not isinstance(config, dict):
                config = {}
            if "config" in config and isinstance(config["config"], dict):
                inner = config.pop("config")
                for k, v in inner.items():
                    if k not in config:
                        config[k] = v

            widget = {**config}
            widget["id"] = w["widget_id"]
            widget["title"] = w["title"] or config.get("title", "")
            widget["type"] = w["widget_type"] or config.get("type", "kpi")
            widget["chartType"] = w.get("chart_type") or config.get("chartType") or config.get("chart_type")
            widget["chart_type"] = widget["chartType"]
            widget["sql_query"] = w.get("sql_query") or config.get("sql_query", "")
            widgets_for_client.append(widget)

        return {
            "workspace_name": ws["name"],
            "workspace_id": workspace_id,
            "dashboard_id": dashboard["dashboard_id"],
            "dashboard_name": dashboard["name"],
            "layout_json": dashboard["layout_json"],
            "widgets": widgets_for_client,
            "source": "workspace",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Shared workspace dashboard failed: {e}")
        raise HTTPException(status_code=500, detail="Error fetching shared workspace dashboard")


from pydantic import BaseModel as _PydanticBaseModel

class _SharedWorkspaceChatRequest(_PydanticBaseModel):
    question: str

class _SharedReportChatRequest(_PydanticBaseModel):
    question: str
    title: str = ""

class _SharedReportSqlRequest(_PydanticBaseModel):
    title: str = "Custom SQL Report"
    sql_query: str

class _SharedReportSummarizeRequest(_PydanticBaseModel):
    question: str
    sql_query: str
    columns: list
    data: list


@router.post("/api/share/workspace/{token}/chat")
@observe(name="share.workspace_chat")
async def shared_workspace_chat(
    token: str,
    request: _SharedWorkspaceChatRequest,
    db: DatabaseManager = Depends(get_db),
):
    """Public chat endpoint for shared workspace chatbots. No auth required.
    
    Resolves the share token to a workspace and runs the RAG-to-SQL pipeline.
    """
    try:
        ws = _resolve_workspace_from_token(token, db)
        workspace_id = ws["workspace_id"]

        from app.core.agents.workspace_sql import WorkspaceSqlAgent
        from app.core.llm import create_workspace_llm

        llm, embed_model = create_workspace_llm()
        agent = WorkspaceSqlAgent(
            db=db,
            workspace_id=workspace_id,
            llm=llm,
            embed_model=embed_model,
        )

        result = agent.chat(request.question)
        logger.info(
            "[SharedChat] workspace=%s | question=%s | status=%s | rows=%s",
            workspace_id,
            request.question,
            result.get("status"),
            result.get("row_count"),
        )

        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Shared workspace chat failed: {e}")
        raise HTTPException(status_code=500, detail="Chat failed — please try again")


# ═══════════════════════════════════════════════════════════════════════════
# SHARED WORKSPACE REPORT ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════

@router.post("/api/share/workspace/{token}/report/chat")
@observe(name="share.workspace_report_chat")
async def shared_workspace_report_chat(
    token: str,
    request: _SharedReportChatRequest,
    db: DatabaseManager = Depends(get_db),
):
    """Public AI-driven report endpoint for shared workspaces. No auth required."""
    try:
        ws = _resolve_workspace_from_token(token, db)
        workspace_id = ws["workspace_id"]

        from app.core.agents.workspace_sql import WorkspaceSqlAgent
        from app.core.llm import create_workspace_llm

        llm, embed_model = create_workspace_llm()
        agent = WorkspaceSqlAgent(
            db=db, workspace_id=workspace_id, llm=llm, embed_model=embed_model,
        )

        result = agent.chat(request.question)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Shared workspace report chat failed: {e}")
        raise HTTPException(status_code=500, detail="Report generation failed")


@router.post("/api/share/workspace/{token}/report/execute_custom_sql")
@observe(name="share.workspace_report_sql")
async def shared_workspace_report_sql(
    token: str,
    request: _SharedReportSqlRequest,
    db: DatabaseManager = Depends(get_db),
):
    """Public custom SQL report endpoint for shared workspaces. SELECT-only, no auth."""
    try:
        ws = _resolve_workspace_from_token(token, db)
        workspace_id = ws["workspace_id"]

        # Safety: only allow SELECT/WITH
        sql_upper = request.sql_query.upper().strip()
        dangerous = ["DROP", "DELETE", "INSERT", "UPDATE", "ALTER", "CREATE", "TRUNCATE", "GRANT", "REVOKE"]
        for kw in dangerous:
            if kw in sql_upper.split():
                raise HTTPException(status_code=400, detail=f"Forbidden keyword: {kw}")
        if not sql_upper.startswith("SELECT") and not sql_upper.startswith("WITH"):
            raise HTTPException(status_code=400, detail="Only SELECT/WITH queries are allowed")

        from app.core.agents.workspace_sql import WorkspaceSqlAgent
        agent = WorkspaceSqlAgent(db=db, workspace_id=workspace_id)
        results, columns = agent._execute_sql(request.sql_query)

        return {
            "status": "success",
            "question": request.title,
            "sql": request.sql_query,
            "columns": columns,
            "data": results,
            "row_count": len(results),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Shared workspace report SQL failed: {e}")
        raise HTTPException(status_code=500, detail="SQL execution failed")


@router.post("/api/share/workspace/{token}/report/summarize")
@observe(name="share.workspace_report_summarize")
async def shared_workspace_report_summarize(
    token: str,
    request: _SharedReportSummarizeRequest,
    db: DatabaseManager = Depends(get_db),
):
    """Public AI summarization for shared workspace reports. No auth required."""
    try:
        ws = _resolve_workspace_from_token(token, db)

        from app.core.llm import create_workspace_llm
        from langchain_core.messages import HumanMessage

        llm, _ = create_workspace_llm()

        # Build a compact data summary (limit rows for token efficiency)
        data_sample = request.data[:50] if len(request.data) > 50 else request.data
        import pandas as pd
        df = pd.DataFrame(data_sample, columns=request.columns)
        describe_str = df.describe(include='all').to_string()

        prompt = f"""You are a data analyst. Analyze this dataset and provide a comprehensive report.

Question/Title: "{request.question}"
SQL Query: {request.sql_query}

Statistical Profile:
{describe_str}

Data Sample ({len(data_sample)} of {len(request.data)} rows):
{df.head(20).to_string(index=False)}

Please provide a comprehensive analytical report in Markdown format.
Include: key findings, trends, outliers, and actionable recommendations."""

        from app.core.llm import invoke_llm_with_retry
        response_content = invoke_llm_with_retry(llm, [HumanMessage(content=prompt)], context_name="Report Summary")

        return {"status": "success", "summary": response_content}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Shared report summarization failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate AI report summary.")


# ═══════════════════════════════════════════════════════════════════════════
# PUBLIC: VIEW A SHARED REPORT SNAPSHOT (no auth)
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/api/share/report/{token}")
async def get_shared_report(
    token: str,
    db: DatabaseManager = Depends(get_db),
):
    """Public endpoint to view a shared report snapshot. No auth required."""
    with db.get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT sr.report_id, sr.title, sr.question, sr.sql_query,
                       sr.columns, sr.data, sr.row_count, sr.ai_summary,
                       sr.created_at::text as created_at,
                       w.name as workspace_name
                FROM etl_system.shared_reports sr
                JOIN etl_system.workspaces w ON w.workspace_id = sr.workspace_id
                WHERE sr.share_token = %s
                """,
                (token,),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Shared report not found or has been removed.")

    return dict(row)
