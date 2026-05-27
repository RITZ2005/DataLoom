from fastapi import APIRouter, Depends, HTTPException
from typing import Optional, Dict, Any, List
import logging
import json
import os
from psycopg2.extras import RealDictCursor

from app.core.agent import HybridAgent
from app.core.database import DatabaseManager
from app.utils.logging import log_full_exception, user_facing_error_message
from app.core.auth import get_current_user
from app.dependencies import (
    get_db, resolve_file_identifier, enforce_file_access, 
    get_or_load_agent, _load_board_agent, _get_trace_user_metadata
)
from app.schemas import (
    DashboardGenerateRequest, DashboardWidgetRequest, 
    CloneWidgetsRequest, UnifiedCompareRequest, DashboardFilterRequest,
    ChartBuilderRequest, TemplateCloneRequest
)
from app.config import logger

# Optional Langfuse  
try:
    from app.config import observe, langfuse_context
except ImportError:
    def observe(_func=None, *, name: str = "", **kwargs):
        def decorator(func): return func
        return _func if _func else decorator
    class _FakeLangfuseContext:
        def update_current_trace(self, **kwargs): pass
        def update_current_observation(self, **kwargs): pass
        def get_current_trace_id(self): return None
        def get_current_trace_url(self): return None
    langfuse_context = _FakeLangfuseContext()



router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def _get_trace_ids() -> tuple:
    """Return (trace_id, trace_url) from current context."""
    try:
        _tid = langfuse_context.get_current_trace_id()
        _turl = langfuse_context.get_current_trace_url() if _tid else None
        return _tid, _turl
    except:
        return None, None


def _enrich_dashboard_trace(name: str, current_user: dict, file_uuid: str, filename: str, table_name: str, 
                             session_id: Optional[str] = None, extra_input: Optional[dict] = None, 
                             tags: Optional[List[str]] = None, agent = None) -> str:
    """Enrich trace with dashboard context."""
    effective_session = session_id or f"dashboard-{file_uuid}"
    try:
        langfuse_context.update_current_trace(
            name=name,
            user_id=str(current_user.get("id") or current_user.get("email", "")),
            session_id=effective_session,
            input={"file_uuid": file_uuid, "filename": filename, "table_name": table_name, **(extra_input or {})},
            metadata={
                "file_uuid": file_uuid,
                "filename": filename,
                "table_name": table_name,
                **_get_trace_user_metadata(current_user),
            },
            tags=tags or [],
        )
    except:
        pass
    return effective_session


def _build_dashboard_trace_output(dashboard: dict, cache_hit: bool, effective_session_id: str, regenerate: bool = False, 
                                   agent = None, user_requirements: Optional[str] = None) -> dict:
    """Build dashboard trace output."""
    widgets = dashboard.get("widgets", []) if isinstance(dashboard, dict) else []
    widget_types = [w.get("type", "?") for w in widgets if isinstance(w, dict)]
    return {
        "status": "success",
        "cache_hit": cache_hit,
        "regenerate": regenerate,
        "widget_count": len(widget_types),
        "widget_types": widget_types,
        "session_id": effective_session_id,
        "user_requirements": user_requirements,
    }




# ============================================================================
# ENDPOINTS
# ============================================================================

@router.post("/{file_identifier}/generate")
@observe(name="dashboard.generate_custom")
async def generate_dashboard_custom(
    file_identifier: str,
    request: DashboardGenerateRequest,
    db: DatabaseManager = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Generate (or regenerate) a dashboard with optional user-defined requirements."""
    try:
        result = resolve_file_identifier(file_identifier, db, request.source_type)
        if not result:
            raise HTTPException(status_code=404, detail=f"File '{file_identifier}' not found")

        enforce_file_access(result, current_user)
        file_uuid, filename, table_name, _user_id = result

        agent = get_or_load_agent(file_uuid=file_uuid, filename=filename, load_existing=True, db=db, mode=request.mode)

        effective_session = _enrich_dashboard_trace(
            f"dashboard-generate-custom: {filename}",
            current_user, file_uuid, filename, table_name,
            session_id=request.session_id,
            extra_input={"user_requirements": request.user_requirements},
            tags=["dashboard", "generate-custom"],
            agent=agent,
        )

        agent.delete_dashboard()

        dashboard = agent.generate_kpi_dashboard(user_requirements=request.user_requirements)

        _tid, _turl = _get_trace_ids()
        langfuse_context.update_current_trace(
            output=_build_dashboard_trace_output(
                dashboard,
                cache_hit=False,
                effective_session_id=effective_session,
                regenerate=True,
                agent=agent,
                user_requirements=request.user_requirements,
            ),
        )
        dashboard["cache_hit"] = False
        dashboard["session_id"] = effective_session
        dashboard["trace_id"] = _tid
        dashboard["trace_url"] = _turl
        return dashboard
    except HTTPException:
        raise
    except Exception as e:
        log_full_exception(e, "Custom dashboard generation failed")
        raise HTTPException(status_code=500, detail=user_facing_error_message(e))


@router.get("/{file_identifier}")
@observe(name="dashboard.generate")
async def generate_dashboard(
    file_identifier: str,
    regenerate: bool = False,
    session_id: Optional[str] = None,
    source_type: Optional[str] = None,
    mode: Optional[str] = None,
    db: DatabaseManager = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Get AI-powered KPI dashboard for a file."""
    try:
        result = resolve_file_identifier(file_identifier, db, source_type)
        if not result:
            raise HTTPException(status_code=404, detail=f"File '{file_identifier}' not found")
        
        enforce_file_access(result, current_user)
        file_uuid, filename, table_name, _user_id = result

        agent = get_or_load_agent(file_uuid=file_uuid, filename=filename, load_existing=True, db=db, mode=mode)

        effective_session = _enrich_dashboard_trace(
            f"dashboard: {filename}" + (" (regenerate)" if regenerate else ""),
            current_user, file_uuid, filename, table_name,
            session_id=session_id,
            extra_input={"regenerate": regenerate},
            tags=["dashboard", "generate"],
            agent=agent,
        )
        
        if not regenerate:
            cached_dashboard = agent.load_dashboard()
            if cached_dashboard:
                _tid, _turl = _get_trace_ids()
                langfuse_context.update_current_trace(
                    output=_build_dashboard_trace_output(
                        cached_dashboard,
                        cache_hit=True,
                        effective_session_id=effective_session,
                        regenerate=regenerate,
                        agent=agent,
                    ),
                    tags=["dashboard", "generate", "cache-hit"],
                )
                cached_dashboard["cache_hit"] = True
                cached_dashboard["session_id"] = effective_session
                cached_dashboard["trace_id"] = _tid
                cached_dashboard["trace_url"] = _turl
                return cached_dashboard
        
        if regenerate:
            agent.delete_dashboard()
        
        dashboard = agent.generate_kpi_dashboard()

        _tid, _turl = _get_trace_ids()
        langfuse_context.update_current_trace(
            output=_build_dashboard_trace_output(
                dashboard,
                cache_hit=False,
                effective_session_id=effective_session,
                regenerate=regenerate,
                agent=agent,
            ),
            tags=["dashboard", "generate", "cache-miss"],
        )
        dashboard["cache_hit"] = False
        dashboard["session_id"] = effective_session
        dashboard["trace_id"] = _tid
        dashboard["trace_url"] = _turl
        
        return dashboard
    except HTTPException:
        raise
    except Exception as e:
        log_full_exception(e, "Dashboard generation failed")
        raise HTTPException(status_code=500, detail=user_facing_error_message(e))


@router.post("/{file_identifier}/widget")
@observe(name="dashboard.widget")
async def generate_dashboard_widget(
    file_identifier: str,
    request: DashboardWidgetRequest,
    db: DatabaseManager = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Generate a single dashboard widget from natural language query."""
    try:
        result = resolve_file_identifier(file_identifier, db, request.source_type)
        if not result:
            raise HTTPException(status_code=404, detail=f"File '{file_identifier}' not found")
        
        enforce_file_access(result, current_user)
        file_uuid, filename, table_name, _user_id = result

        _req_mode = getattr(request, "mode", None) if "request" in locals() else locals().get("mode")
        agent = get_or_load_agent(file_uuid=file_uuid, filename=filename, load_existing=True, db=db, mode=_req_mode)

        _enrich_dashboard_trace(
            f"dashboard-widget: {request.query[:80]}",
            current_user, file_uuid, filename, table_name,
            session_id=request.session_id,
            extra_input={"query": request.query, "compare_file_id": request.compare_file_id},
            tags=["dashboard", "widget"],
            agent=agent,
        )
        
        base_result = agent.generate_single_widget(
            request.query,
            widget_type_hint=request.widget_type_hint,
            chart_type_hint=request.chart_type_hint,
            filter_context_hint=request.filter_context_hint,
        )
        if isinstance(base_result, dict) and isinstance(base_result.get("widget"), dict):
            base_widget = base_result["widget"]
            base_widget.setdefault("origin_query", request.query)

        _tid, _turl = _get_trace_ids()

        if request.compare_file_id:
            cmp_result_record = resolve_file_identifier(request.compare_file_id, db, request.source_type)
            if not cmp_result_record:
                raise HTTPException(status_code=404, detail=f"Compare file '{request.compare_file_id}' not found")
            enforce_file_access(cmp_result_record, current_user)
            cmp_uuid, cmp_filename, cmp_table, _ = cmp_result_record

            cmp_agent = get_or_load_agent(file_uuid=cmp_uuid, filename=cmp_filename, load_existing=True, db=db, mode=getattr(request, 'mode', None) if 'request' in locals() else None)
            cmp_widget_result = cmp_agent.generate_single_widget(
                request.query,
                widget_type_hint=request.widget_type_hint,
                chart_type_hint=request.chart_type_hint,
                filter_context_hint=request.filter_context_hint,
            )
            if isinstance(cmp_widget_result, dict) and isinstance(cmp_widget_result.get("widget"), dict):
                cmp_widget = cmp_widget_result["widget"]
                cmp_widget.setdefault("origin_query", request.query)

            base_w = base_result.get("widget", {})
            cmp_w = cmp_widget_result.get("widget", {})

            shared_id = base_w.get("id", f"widget-dual-{__import__('uuid').uuid4().hex[:8]}")
            cmp_w["id"] = shared_id
            base_w["id"] = shared_id
            cmp_w["gridW"] = base_w.get("gridW", 3)
            cmp_w["gridH"] = base_w.get("gridH", 2)

            langfuse_context.update_current_trace(
                output={
                    "status": "success",
                    "dual": True,
                    "base_widget_type": base_w.get("type"),
                    "compare_widget_type": cmp_w.get("type"),
                    "query": request.query,
                },
            )

            return {
                "status": "success",
                "dual": True,
                "base_widget": base_w,
                "compare_widget": cmp_w,
                "trace_id": _tid,
                "trace_url": _turl,
            }

        langfuse_context.update_current_trace(
            output={
                "status": "success",
                "widget_type": base_result.get("widget", {}).get("type"),
                "query": request.query,
            },
        )
        base_result["trace_id"] = _tid
        base_result["trace_url"] = _turl
        return base_result
    except HTTPException:
        raise
    except Exception as e:
        log_full_exception(e, "Widget generation failed")
        raise HTTPException(status_code=500, detail=user_facing_error_message(e))


@router.post("/clone-widgets")
@observe(name="dashboard.clone_widgets")
async def clone_widgets_for_compare(
    request: CloneWidgetsRequest,
    db: DatabaseManager = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Clone dashboard widgets from base file to target file for comparison."""
    try:
        base_record = resolve_file_identifier(request.base_file_id, db)
        if not base_record:
            raise HTTPException(status_code=404, detail="Base file not found")
        enforce_file_access(base_record, current_user)

        target_record = resolve_file_identifier(request.target_file_id, db)
        if not target_record:
            raise HTTPException(status_code=404, detail="Target file not found")
        enforce_file_access(target_record, current_user)

        base_uuid, base_filename, _, _ = base_record
        target_uuid, target_filename, _, _ = target_record

        base_agent = get_or_load_agent(file_uuid=base_uuid, filename=base_filename, load_existing=True, db=db, mode=getattr(request, 'mode', None) if 'request' in locals() else None)

        effective_session = _enrich_dashboard_trace(
            f"dashboard-Compare Split : {base_filename} → {target_filename}",
            current_user, base_uuid, base_filename, "",
            session_id=request.session_id,
            extra_input={"base_file_id": request.base_file_id, "target_file_id": request.target_file_id},
            tags=["dashboard", "clone-widgets"],
            agent=base_agent,
        )

        base_dash = base_agent.load_dashboard()
        if not base_dash:
            base_dash = base_agent.generate_kpi_dashboard()
        base_widgets = base_dash.get("widgets", [])

        if not base_widgets:
            raise HTTPException(status_code=400, detail="Base file has no dashboard widgets to clone")

        target_agent = get_or_load_agent(file_uuid=target_uuid, filename=target_filename, load_existing=True, db=db, mode=getattr(request, 'mode', None) if 'request' in locals() else None)
        cloned_widgets = target_agent.clone_widgets_from_blueprints(base_widgets)

        try:
            target_fp = target_agent._build_file_fingerprint()
            dims = target_fp.get("dimensions", [])
            measures = target_fp.get("measures", [])
            fp_for_client = {
                "measures": [{"col": m["col"], "agg": m["agg"], "format_hint": m.get("format_hint", "number")}
                             for m in measures[:12]],
                "dimensions": [{"col": d["col"], "cardinality": d["cardinality"], "dim_type": d["dim_type"],
                                "top_values": d["top_values"]}
                               for d in dims[:10]],
            }
        except Exception:
            fp_for_client = {}

        _tid, _turl = _get_trace_ids()

        return {
            "status": "success",
            "filename": target_filename,
            "file_uuid": target_uuid,
            "total_rows": len(target_agent.df),
            "total_columns": len(target_agent.df.columns),
            "widgets": cloned_widgets,
            "fingerprint": fp_for_client,
            "session_id": effective_session,
            "trace_id": _tid,
            "trace_url": _turl,
        }
    except HTTPException:
        raise
    except Exception as e:
        log_full_exception(e, "Clone widgets failed")
        raise HTTPException(status_code=500, detail=user_facing_error_message(e))


@router.post("/compare-unified")
@observe(name="dashboard.compare_unified")
async def compare_unified(
    request: UnifiedCompareRequest,
    db: DatabaseManager = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Unified semantic comparison: merge data from both files into single widgets."""
    try:
        base_record = resolve_file_identifier(request.base_file_id, db)
        if not base_record:
            raise HTTPException(status_code=404, detail="Base file not found")
        enforce_file_access(base_record, current_user)

        cmp_record = resolve_file_identifier(request.compare_file_id, db)
        if not cmp_record:
            raise HTTPException(status_code=404, detail="Compare file not found")
        enforce_file_access(cmp_record, current_user)

        base_uuid, base_filename, _, _ = base_record
        cmp_uuid, cmp_filename, _, _ = cmp_record

        base_agent = get_or_load_agent(file_uuid=base_uuid, filename=base_filename, load_existing=True, db=db, mode=getattr(request, 'mode', None) if 'request' in locals() else None)
        cmp_agent = get_or_load_agent(file_uuid=cmp_uuid, filename=cmp_filename, load_existing=True, db=db, mode=getattr(request, 'mode', None) if 'request' in locals() else None)

        effective_session = _enrich_dashboard_trace(
            f"dashboard-compare-unified: {base_filename} vs {cmp_filename}",
            current_user, base_uuid, base_filename, "",
            session_id=request.session_id,
            extra_input={
                "base_file_id": request.base_file_id,
                "compare_file_id": request.compare_file_id,
            },
            tags=["dashboard", "compare-unified"],
            agent=base_agent,
        )

        base_dash = base_agent.load_dashboard()
        if not base_dash:
            base_dash = base_agent.generate_kpi_dashboard()
        base_widgets = base_dash.get("widgets", [])

        if not base_widgets:
            raise HTTPException(status_code=400, detail="Base file has no dashboard widgets")

        unified_widgets = base_agent.generate_unified_comparison(
            compare_agent=cmp_agent,
            base_widgets=base_widgets,
            base_label=base_filename.rsplit(".", 1)[0] if "." in base_filename else base_filename,
            compare_label=cmp_filename.rsplit(".", 1)[0] if "." in cmp_filename else cmp_filename,
        )

        try:
            fp = base_agent._build_file_fingerprint()
            dims = fp.get("dimensions", [])
            measures = fp.get("measures", [])
            fp_for_client = {
                "measures": [{"col": m["col"], "agg": m["agg"], "format_hint": m.get("format_hint", "number")}
                             for m in measures[:12]],
                "dimensions": [{"col": d["col"], "cardinality": d["cardinality"], "dim_type": d["dim_type"],
                                "top_values": d["top_values"]}
                               for d in dims[:10]],
            }
        except Exception:
            fp_for_client = {}

        _tid, _turl = _get_trace_ids()

        return {
            "status": "success",
            "view": "unified",
            "base_filename": base_filename,
            "compare_filename": cmp_filename,
            "base_file_uuid": base_uuid,
            "compare_file_uuid": cmp_uuid,
            "total_rows_base": len(base_agent.df),
            "total_rows_compare": len(cmp_agent.df),
            "widgets": unified_widgets,
            "fingerprint": fp_for_client,
            "session_id": effective_session,
            "trace_id": _tid,
            "trace_url": _turl,
        }

    except HTTPException:
        raise
    except Exception as e:
        log_full_exception(e, "Unified comparison failed")
        raise HTTPException(status_code=500, detail=user_facing_error_message(e))


@router.post("/{file_identifier}/filter")
@observe(name="dashboard.filter")
async def filter_dashboard(
    file_identifier: str,
    request: DashboardFilterRequest,
    db: DatabaseManager = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Cross-filter the dashboard using filtered data."""
    try:
        result = resolve_file_identifier(file_identifier, db, request.source_type)
        if not result:
            raise HTTPException(status_code=404, detail=f"File '{file_identifier}' not found")
        
        enforce_file_access(result, current_user)
        file_uuid, filename, table_name, _user_id = result
        
        _req_mode = getattr(request, "mode", None) if "request" in locals() else locals().get("mode")
        agent = get_or_load_agent(file_uuid=file_uuid, filename=filename, load_existing=True, db=db, mode=_req_mode)
        
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

        _tid, _turl = _get_trace_ids()
        _filtered_widgets = filtered.get("widgets", [])
        langfuse_context.update_current_trace(
            output={
                "status": "success",
                "widget_count": len(_filtered_widgets),
                "widget_types": [w.get("type", "?") for w in _filtered_widgets],
            },
        )
        filtered["trace_id"] = _tid
        filtered["trace_url"] = _turl
        
        return filtered
    except HTTPException:
        raise
    except Exception as e:
        log_full_exception(e, "Dashboard filter failed")
        raise HTTPException(status_code=500, detail=user_facing_error_message(e))


@router.post("/{file_identifier}/update-widgets")
@observe(name="dashboard.update_widgets")
async def update_dashboard_widgets(
    file_identifier: str,
    request: dict,
    db: DatabaseManager = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Update dashboard widgets after user adds/removes widgets."""
    try:
        result = resolve_file_identifier(file_identifier, db)
        if not result:
            raise HTTPException(status_code=404, detail=f"File '{file_identifier}' not found")

        enforce_file_access(result, current_user)
        file_uuid, filename, table_name, _user_id = result

        widgets = request.get('widgets', [])
        studio = request.get('studio')

        with db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM file_registry WHERE file_uuid = %s", (file_uuid,))
                in_registry = cur.fetchone() is not None

            if in_registry:
                dashboard_data = {
                    "status": "success",
                    "filename": filename,
                    "file_uuid": file_uuid,
                    "widgets": widgets,
                    "fingerprint": request.get("fingerprint") or {},
                }
                if isinstance(studio, dict):
                    dashboard_data["studio"] = studio
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO dashboards (dashboard_id, file_uuid, widgets_json, created_at, updated_at)
                        VALUES (%s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                        ON CONFLICT (dashboard_id) DO UPDATE
                        SET widgets_json = EXCLUDED.widgets_json, updated_at = CURRENT_TIMESTAMP
                        """,
                        (f"dash-{file_uuid}", file_uuid, json.dumps(dashboard_data, default=str)),
                    )
                conn.commit()

        _tid, _turl = _get_trace_ids()
        langfuse_context.update_current_trace(
            output={
                "status": "success",
                "widget_count": len(widgets),
            },
        )
        return {
            "status": "success",
            "message": f"Saved {len(widgets)} widgets",
            "widget_count": len(widgets),
            "trace_id": _tid,
            "trace_url": _turl,
        }
    except HTTPException:
        raise
    except Exception as e:
        log_full_exception(e, "Widget update failed")
        raise HTTPException(status_code=500, detail=user_facing_error_message(e))

@router.get("/{file_identifier}/schema")
@observe(name="dashboard.get_schema")
async def get_dashboard_schema(
    file_identifier: str,
    source_type: Optional[str] = None,
    mode: Optional[str] = None,
    db: DatabaseManager = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Return a lightweight schema of the dataset for the Chart Builder UI."""
    try:
        record = resolve_file_identifier(file_identifier, db, source_type)
        if not record:
            raise HTTPException(status_code=404, detail="File not found")
        enforce_file_access(record, current_user)
        file_uuid, filename, _table, _user_id = record
        
        agent = get_or_load_agent(file_uuid=file_uuid, filename=filename, load_existing=True, db=db, mode=mode)
        schema_data = agent.get_chart_schema()
        
        return {
            "status": "success",
            "file_uuid": file_uuid,
            **schema_data
        }
    except HTTPException:
        raise
    except Exception as e:
        log_full_exception(e, "Get chart schema failed")
        raise HTTPException(status_code=500, detail=user_facing_error_message(e))

@router.post("/{file_identifier}/clone-template-widgets")
@observe(name="dashboard.clone_template_widgets")
async def clone_template_widgets(
    file_identifier: str,
    request: TemplateCloneRequest,
    db: DatabaseManager = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Clone explicitly provided payload widgets (Chart Builder style)."""
    try:
        record = resolve_file_identifier(file_identifier, db, None)
        if not record:
            raise HTTPException(status_code=404, detail="File not found")
        enforce_file_access(record, current_user)
        file_uuid, filename, _table, _user_id = record
        
        _req_mode = getattr(request, "mode", None) if "request" in locals() else locals().get("mode")
        agent = get_or_load_agent(file_uuid=file_uuid, filename=filename, load_existing=True, db=db, mode=_req_mode)
        
        # Perform clone exactly identical to how monolith did it
        cloned_widgets = agent.clone_widgets_from_blueprints(request.template_widgets)
        fp = agent._build_file_fingerprint()
        
        return {
            "status": "success",
            "widgets": cloned_widgets,
            "fingerprint": fp
        }
    except HTTPException:
        raise
    except Exception as e:
        log_full_exception(e, "Clone template widgets failed")
        raise HTTPException(status_code=500, detail="Failed to clone blueprint widgets")

@router.post("/{file_identifier}/chart-builder")
@observe(name="dashboard.chart_builder")
async def generate_custom_chart(
    file_identifier: str,
    request: ChartBuilderRequest,
    db: DatabaseManager = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Generate a single chart widget interactively — no LLM, instant Pandas result."""
    try:
        record = resolve_file_identifier(file_identifier, db, request.source_type)
        if not record:
            raise HTTPException(status_code=404, detail="File not found")
        enforce_file_access(record, current_user)
        file_uuid, filename, _table, _user_id = record
        
        _req_mode = getattr(request, "mode", None) if "request" in locals() else locals().get("mode")
        agent = get_or_load_agent(file_uuid=file_uuid, filename=filename, load_existing=True, db=db, mode=_req_mode)
        
        widget = agent.generate_custom_chart_widget(
            chart_type=request.chart_type,
            dimension=request.dimension,
            measure=request.measure,
            aggregation=request.aggregation
        )
        
        return {
            "status": "success",
            "widget": widget
        }
    except HTTPException:
        raise
    except Exception as e:
        log_full_exception(e, "Custom chart generation failed")
        raise HTTPException(status_code=500, detail=user_facing_error_message(e))
