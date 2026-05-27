import json
import os
from typing import List

from fastapi import APIRouter, Depends, HTTPException

from app.config import LANGFUSE_AVAILABLE, langfuse_client, langfuse_context, observe
from app.dependencies import (
    _get_trace_user_metadata,
    enforce_file_access,
    get_agent,
    get_db,
    infer_source_type,
    resolve_file_identifier,
)
from app.schemas.query import (
    BatchQueryRequest,
    BatchQueryResponse,
    BatchQueryResultItem,
    QueryRequest,
    QueryResponse,
)
from app.services.langfuse_sso import build_langfuse_session_url
from app.utils.logging import log_full_exception, logger, user_facing_error_message
from app.core.auth import get_current_user

router = APIRouter(prefix="/api", tags=["query"])


@observe(as_type="span", name="api.query.resolve_file")
def _trace_resolve_file_context(identifier, db, current_user: dict):
    langfuse_context.update_current_observation(input={"identifier": identifier})
    resolved = resolve_file_identifier(identifier, db)
    if not resolved:
        langfuse_context.update_current_observation(output={"found": False})
        return None

    enforce_file_access(resolved, current_user)
    file_uuid, filename, table_name, _user_id = resolved
    langfuse_context.update_current_observation(
        output={
            "found": True,
            "file_uuid": file_uuid,
            "filename": filename,
            "table_name": table_name,
        }
    )
    return resolved


@observe(as_type="span", name="api.query.cache_lookup")
def _trace_cache_lookup(agent, query: str, use_cache: bool):
    langfuse_context.update_current_observation(
        input={"use_cache": bool(use_cache), "query_preview": query[:200]}
    )
    if not use_cache:
        if hasattr(agent, "last_cache_trace"):
            agent.last_cache_trace = {
                "status": "skipped",
                "decision": "cache_disabled_by_request",
                "cache_hit": False,
                "query_preview": (query or "")[:300],
            }
        langfuse_context.update_current_observation(
            output={
                "cache_checked": False,
                "cache_hit": False,
                "cache_details": getattr(agent, "last_cache_trace", {}),
            }
        )
        return None

    cached = agent.check_cache(query)
    langfuse_context.update_current_observation(
        output={
            "cache_checked": True,
            "cache_hit": bool(cached),
            "query_type": cached.get("query_type") if cached else None,
            "cache_details": getattr(agent, "last_cache_trace", {}),
        }
    )
    return cached


@observe(as_type="span", name="api.query.decide_intent")
def _trace_decide_intent(agent, query: str) -> str:
    langfuse_context.update_current_observation(input={"query_preview": query[:200]})
    query_type = agent.decide_intent(query)
    langfuse_context.update_current_observation(output={"query_type": query_type})
    return query_type


@observe(as_type="span", name="api.query.execute_path")
def _trace_execute_path(agent, query_type: str, query: str):
    langfuse_context.update_current_observation(
        input={"query_type": query_type, "query_preview": query[:200]}
    )

    sql_table_names = getattr(agent, "sql_table_names", None)
    fallback_table_names = [agent.table_name] if getattr(agent, "table_name", None) else None
    sql_scope = sql_table_names or fallback_table_names

    if query_type == "METADATA":
        result = agent.run_metadata_path(query)
    elif query_type == "ANALYTICAL":
        result = agent.run_analytical_path(query)
    elif query_type == "PLOT":
        result = agent.run_plot_path(query)
    elif query_type == "SQL_AGENT":
        result = agent.run_sql_agent_path(query, table_names=sql_scope)
    else:
        result = agent.run_semantic_path(query)
    return result


@observe(as_type="span", name="api.query.cache_save")
def _trace_cache_save(agent, query: str, query_type: str, result):
    langfuse_context.update_current_observation(input={"query_type": query_type})
    agent.save_to_cache(query, query_type, result)
    langfuse_context.update_current_observation(
        output={
            "saved": True,
            "cache_save_details": getattr(agent, "last_cache_save_trace", {}),
        }
    )


def _flush_langfuse_now() -> None:
    """Best-effort flush so traces are queryable immediately in Langfuse UI."""
    if not (LANGFUSE_AVAILABLE and langfuse_client is not None):
        return
    try:
        langfuse_client.flush()
    except Exception as exc:
        logger.debug("[langfuse] flush skipped due to error: %s", exc)


@router.post("/query", response_model=QueryResponse)
@observe(name="api.query")
async def analyze_query(
    request: QueryRequest,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        requested_source_type = (request.source_type or "").strip().lower() or None
        if requested_source_type and requested_source_type not in {"file", "database"}:
            raise HTTPException(status_code=400, detail="source_type must be either 'file' or 'database'")

        identifier = request.file_uuid if request.file_uuid else request.filename
        if not identifier:
            raise HTTPException(status_code=400, detail="file_uuid or filename required")

        result = resolve_file_identifier(identifier, db, requested_source_type)
        if not result:
            raise HTTPException(status_code=404, detail=f"File '{identifier}' not found")

        enforce_file_access(result, current_user)

        file_uuid, filename, table_name, _user_id = result

        actual_source_type = infer_source_type(file_uuid, db)
        if requested_source_type and actual_source_type != "unknown" and requested_source_type != actual_source_type:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Source type mismatch: requested '{requested_source_type}' but resolved '{actual_source_type}'. "
                    "Please select the correct source."
                ),
            )

        _trace_name = f"query: {request.query[:80]}" if request.query else "query"
        _trace_user_meta = _get_trace_user_metadata(current_user)
        langfuse_context.update_current_trace(
            name=_trace_name,
            user_id=str(current_user.get("id") or current_user.get("email", "")),
            session_id=request.session_id,
            input={"query": request.query, "file_uuid": file_uuid, "use_cache": request.use_cache},
            metadata={
                "file_uuid": file_uuid,
                "filename": filename,
                "table_name": table_name,
                "source_type_requested": requested_source_type,
                "source_type_resolved": actual_source_type,
                "trace_debug_map": {
                    "final_output": "trace.output.response",
                    "pipeline_spans": [
                        "api.query.resolve_file",
                        "api.query.cache_lookup",
                        "api.query.decide_intent",
                        "api.query.execute_path",
                        "api.query.cache_save",
                    ],
                },
                **_trace_user_meta,
            },
            tags=["api-query"],
        )

        agent = get_agent(file_uuid=file_uuid, filename=filename, load_existing=True)

        cached_result = _trace_cache_lookup(agent, request.query, bool(request.use_cache))
        if cached_result:
            _cache_details = getattr(agent, "last_cache_trace", {})
            langfuse_context.update_current_trace(
                output={
                    "status": "success",
                    "query_type": cached_result.get("query_type"),
                    "cache_hit": True,
                    "cache": {
                        "lookup": _cache_details,
                        "save": {
                            "status": "skipped",
                            "decision": "served_from_cache",
                            "saved": False,
                        },
                    },
                },
                tags=["api-query", "cache-hit"],
            )
            _tid = langfuse_context.get_current_trace_id()
            _turl = langfuse_context.get_current_trace_url()
            if not _turl and _tid:
                _lf_host = os.getenv("LANGFUSE_HOST", "http://localhost:3000").rstrip("/")
                _lf_proj = os.getenv("LANGFUSE_PROJECT_ID", "")
                if _lf_proj:
                    _turl = f"{_lf_host}/project/{_lf_proj}/traces/{_tid}"
            if _tid:
                _flush_langfuse_now()
            _session_url = build_langfuse_session_url(request.session_id) if (request.session_id and _tid) else None
            return QueryResponse(
                status="success",
                data=cached_result.get("response_data"),
                query_type=cached_result.get("query_type"),
                cache_hit=True,
                trace_id=_tid,
                trace_url=_turl,
                session_id=request.session_id,
                session_url=_session_url,
            )

        query_type = _trace_decide_intent(agent, request.query)
        logger.info("Query Type: %s | Query: %s | File UUID: %s", query_type, request.query, file_uuid)

        langfuse_context.update_current_trace(tags=["api-query", query_type.lower()])

        result = _trace_execute_path(agent, query_type, request.query)

        try:
            _trace_cache_save(agent, request.query, query_type, result)
        except Exception as cache_error:
            logger.warning("Failed to save semantic cache: %s", cache_error)

        _cache_lookup_details = getattr(agent, "last_cache_trace", {})
        _cache_save_details = getattr(agent, "last_cache_save_trace", {})
        langfuse_context.update_current_trace(
            output={
                "status": "success",
                "query_type": query_type,
                "cache_hit": False,
                "cache": {
                    "lookup": _cache_lookup_details,
                    "save": _cache_save_details,
                },
            },
        )
        _tid = langfuse_context.get_current_trace_id()
        _turl = langfuse_context.get_current_trace_url()
        if not _turl and _tid:
            _lf_host = os.getenv("LANGFUSE_HOST", "http://localhost:3000").rstrip("/")
            _lf_proj = os.getenv("LANGFUSE_PROJECT_ID", "")
            if _lf_proj:
                _turl = f"{_lf_host}/project/{_lf_proj}/traces/{_tid}"
        if _tid:
            _flush_langfuse_now()
        _session_url = build_langfuse_session_url(request.session_id) if (request.session_id and _tid) else None
        return QueryResponse(
            status="success",
            data=result,
            query_type=query_type,
            cache_hit=False,
            trace_id=_tid,
            trace_url=_turl,
            session_id=request.session_id,
            session_url=_session_url,
        )
    except HTTPException:
        raise
    except Exception as e:
        langfuse_context.update_current_trace(
            output={"status": "error", "error": str(e)[:300]},
            tags=["api-query", "error"],
        )
        log_full_exception(e, "Query processing failed")
        raise HTTPException(status_code=500, detail=user_facing_error_message(e))


@observe(as_type="span", name="batch.execute_single_query")
def _trace_batch_single_query(agent, question: str):
    langfuse_context.update_current_observation(input={"query_preview": question[:200]})
    cached = agent.check_cache(question)
    if cached:
        data = cached.get("response_data", "")
        query_type = cached.get("query_type", "METADATA")
        cache_hit = True
    else:
        query_type = agent.decide_intent(question)
        if query_type == "METADATA":
            data = agent.run_metadata_path(question)
        elif query_type == "ANALYTICAL":
            data = agent.run_analytical_path(question)
        elif query_type == "PLOT":
            data = agent.run_plot_path(question)
        elif query_type == "SQL_AGENT":
            sql_table_names = getattr(agent, "sql_table_names", None)
            fallback_table_names = [agent.table_name] if getattr(agent, "table_name", None) else None
            data = agent.run_sql_agent_path(question, table_names=sql_table_names or fallback_table_names)
        else:
            data = agent.run_semantic_path(question)
        cache_hit = False
        try:
            agent.save_to_cache(question, query_type, data)
        except Exception:
            pass

    langfuse_context.update_current_observation(
        output={"query_type": query_type, "cache_hit": cache_hit}
    )
    return data, query_type, cache_hit


@router.post("/query/batch", response_model=BatchQueryResponse)
@observe(name="api.bookmarked_question")
async def batch_execute_queries(
    request: BatchQueryRequest,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        file_result = resolve_file_identifier(request.file_uuid, db)
        if not file_result:
            raise HTTPException(status_code=404, detail=f"File '{request.file_uuid}' not found")

        enforce_file_access(file_result, current_user)
        file_uuid, filename, table_name, _user_id = file_result
        user_id = current_user.get("id")

        _trace_user_meta = _get_trace_user_metadata(current_user)
        langfuse_context.update_current_trace(
            name=f"Bookmarked Question: {filename} ({len(request.questions)} Qs)",
            user_id=str(current_user.get("id") or current_user.get("email", "")),
            session_id=request.session_id,
            input={
                "file_uuid": file_uuid,
                "filename": filename,
                "question_count": len(request.questions),
                "questions": [q[:100] for q in request.questions],
            },
            metadata={
                "file_uuid": file_uuid,
                "filename": filename,
                "table_name": table_name,
                **_trace_user_meta,
            },
            tags=["bookmarked-question"],
        )

        agent = get_agent(file_uuid=file_uuid, filename=filename, load_existing=True)

        results: list = []
        successful = 0
        failed = 0

        for question in request.questions:
            try:
                import time as _time

                start = _time.time()

                data, query_type, cache_hit = _trace_batch_single_query(agent, question)
                elapsed = _time.time() - start

                _tid = langfuse_context.get_current_trace_id()
                _turl = langfuse_context.get_current_trace_url()
                if not _turl and _tid:
                    _lf_host = os.getenv("LANGFUSE_HOST", "http://localhost:3000").rstrip("/")
                    _lf_proj = os.getenv("LANGFUSE_PROJECT_ID", "")
                    if _lf_proj:
                        _turl = f"{_lf_host}/project/{_lf_proj}/traces/{_tid}"

                display_content = data if isinstance(data, str) else json.dumps(data, default=str)
                metadata_json = json.dumps(
                    {
                        "sourceQuery": question,
                        "auto_replay": True,
                        "traceId": _tid,
                        "traceUrl": _turl,
                        "langfuseSessionId": request.session_id,
                    }
                )
                with db.get_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """INSERT INTO chat_history (user_id, file_uuid, role, content, query_type, metadata)
                               VALUES (%s, %s, 'user', %s, %s, %s)""",
                            (user_id, file_uuid, question, query_type, metadata_json),
                        )
                        cur.execute(
                            """INSERT INTO chat_history (user_id, file_uuid, role, content, query_type, cache_hit, response_time, metadata)
                               VALUES (%s, %s, 'assistant', %s, %s, %s, %s, %s)""",
                            (user_id, file_uuid, display_content, query_type, cache_hit, elapsed, metadata_json),
                        )
                    conn.commit()

                results.append(
                    BatchQueryResultItem(
                        question=question,
                        status="success",
                        data=display_content,
                        query_type=query_type,
                        trace_id=_tid,
                        trace_url=_turl,
                    )
                )
                successful += 1

            except Exception as qe:
                logger.warning("Batch query failed for '%s': %s", question[:60], qe)
                results.append(
                    BatchQueryResultItem(
                        question=question,
                        status="error",
                        error=str(qe)[:200],
                    )
                )
                failed += 1

        langfuse_context.update_current_trace(
            output={
                "status": "success",
                "total": len(request.questions),
                "successful": successful,
                "failed": failed,
            },
        )

        return BatchQueryResponse(
            status="success",
            file_uuid=file_uuid,
            results=results,
            total=len(request.questions),
            successful=successful,
            failed=failed,
        )
    except HTTPException:
        raise
    except Exception as e:
        langfuse_context.update_current_trace(
            output={"status": "error", "error": str(e)[:300]},
            tags=["bookmarked-question", "error"],
        )
        log_full_exception(e, "Batch query execution failed")
        raise HTTPException(status_code=500, detail=user_facing_error_message(e))
