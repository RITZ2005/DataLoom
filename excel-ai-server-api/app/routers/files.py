from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Form
from fastapi.responses import StreamingResponse
from typing import List, Optional, Dict, Any
import tempfile
import os
import json
import uuid
import asyncio
import pandas as pd
import logging

from app.core import HybridAgent, DatabaseManager
from app.utils.logging import log_full_exception, user_facing_error_message
from app.core.auth import get_current_user
from app.services.progress_manager import set_progress, get_progress, clear_progress, create_progress_callback
from app.dependencies import get_db, resolve_file_identifier, enforce_file_access, get_agent, _get_trace_user_metadata
from app.schemas import FileInfo, UploadRawResponse, ExtractSheetRequest, BulkFileIdsRequest, FileListResponse, FileMoveRequest, FileMetadataUpdateRequest, BulkMoveRequest
from app.utils.audit import log_audit_event
from app.config import logger

# ============================================================================
# LANGFUSE OBSERVABILITY  (optional – gracefully disabled when not installed)
# ============================================================================
try:
    from app.config import observe, langfuse_context  # type: ignore
    _LANGFUSE_AVAILABLE = True
except ImportError:
    _LANGFUSE_AVAILABLE = False

    def observe(_func=None, *, name: str = "", **kwargs):  # type: ignore[misc]
        """No-op replacement for langfuse.decorators.observe."""
        def decorator(func):
            return func
        if _func is not None:
            return _func
        return decorator

    class _FakeLangfuseContext:  # type: ignore[no-redef]
        def update_current_trace(self, **kwargs) -> None: pass
        def update_current_observation(self, **kwargs) -> None: pass
        def get_current_trace_id(self) -> None: return None
        def get_current_trace_url(self) -> None: return None

    langfuse_context = _FakeLangfuseContext()  # type: ignore[assignment]


# Create router
router = APIRouter(prefix="/api/files", tags=["files"])

# ============================================================================
# GLOBAL STATE
# ============================================================================

# In-process registry: temp_id → {path, filename, user_id}
_raw_upload_store: Dict[str, dict] = {}


# ============================================================================
# ENDPOINTS
# ============================================================================

@router.get("/upload-progress/{file_uuid}")
@observe(name="files.upload_progress")
async def upload_progress_stream(file_uuid: str):
    """
    Server-Sent Events endpoint for real-time upload progress.
    Frontend subscribes to this after starting an upload.
    """
    async def event_generator():
        last_stage = ""
        last_progress = -1
        
        while True:
            progress = get_progress(file_uuid)
            
            if progress:
                # Only send if something changed
                if progress.stage != last_stage or progress.current != last_progress:
                    last_stage = progress.stage
                    last_progress = progress.current
                    
                    data = {
                        "stage": progress.stage,
                        "current": progress.current,
                        "total": progress.total,
                        "message": progress.message
                    }
                    yield f"data: {json.dumps(data)}\n\n"
                    
                    # If complete or error, end the stream
                    if progress.stage in ["complete", "error"]:
                        clear_progress(file_uuid)
                        break
            
            await asyncio.sleep(0.3)  # Poll every 300ms
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@router.post("/upload", response_model=dict)
@observe(name="api.file_upload")
async def upload_excel_file(
    file: UploadFile = File(...),
    project_id: Optional[str] = Form(None),
    subproject_id: Optional[str] = Form(None),
    file_uuid: Optional[str] = Form(None),
    db: DatabaseManager = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Upload an Excel or CSV file for analysis."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="File name is required")

    _trace_user_meta = _get_trace_user_metadata(current_user)
    langfuse_context.update_current_trace(
        user_id=str(current_user.get("id") or current_user.get("email", "")),
        input={"filename": file.filename, "project_id": project_id, "subproject_id": subproject_id},
        metadata=_trace_user_meta,
        tags=["excel-upload"],
    )
    
    allowed_extensions = ['.xlsx', '.csv', '.xls']
    file_ext = os.path.splitext(file.filename)[1].lower()
    if file_ext not in allowed_extensions:
        raise HTTPException(status_code=400, detail=f"Only {allowed_extensions} files are supported")

    if project_id or subproject_id:
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                if project_id:
                    if current_user.get("role") == "admin":
                        cur.execute("SELECT project_id FROM projects WHERE project_id = %s", (project_id,))
                    else:
                        cur.execute(
                            "SELECT project_id FROM projects WHERE project_id = %s AND created_by = %s",
                            (project_id, current_user.get("id"))
                        )
                    if not cur.fetchone():
                        raise HTTPException(status_code=404, detail="Project not found")

                if subproject_id:
                    if current_user.get("role") == "admin":
                        cur.execute("SELECT subproject_id, project_id FROM subprojects WHERE subproject_id = %s", (subproject_id,))
                    else:
                        cur.execute(
                            "SELECT subproject_id, project_id FROM subprojects WHERE subproject_id = %s AND created_by = %s",
                            (subproject_id, current_user.get("id"))
                        )
                    sub_row = cur.fetchone()
                    if not sub_row:
                        raise HTTPException(status_code=404, detail="Subproject not found")
                    if project_id and sub_row[1] != project_id:
                        raise HTTPException(status_code=400, detail="Subproject does not belong to project")
                    if not project_id:
                        project_id = sub_row[1]
    
    if file_uuid:
        try:
            uuid.UUID(file_uuid, version=4)
        except ValueError:
            file_uuid = str(uuid.uuid4())
    else:
        file_uuid = str(uuid.uuid4())
    tmp_path = None
    
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as tmp:
            contents = await file.read()
            tmp.write(contents)
            tmp_path = tmp.name
        
        logger.info(f"🚀 Processing file: {file.filename} | UUID: {file_uuid} | User: {current_user.get('email')}")
        
        progress_callback = create_progress_callback(file_uuid)
        set_progress(file_uuid, "uploading", 2, 100, "File received, starting processing...")
        
        def _create_agent():
            return HybridAgent(
                file_path=tmp_path,
                filename=file.filename,
                file_uuid=file_uuid,
                user_id=current_user.get("id"),
                project_id=project_id,
                subproject_id=subproject_id,
                progress_callback=progress_callback
            )
        
        agent = await asyncio.to_thread(_create_agent)

        log_audit_event(
            db=db, user_id=current_user.get("id"), action="upload_file",
            entity_type="file", entity_id=file_uuid,
            details={"filename": file.filename}
        )

        langfuse_context.update_current_trace(
            output={"file_uuid": file_uuid, "table_name": agent.table_name, "rows": len(agent.df)},
            metadata={
                "file_uuid": file_uuid,
                "filename": file.filename,
                "table_name": agent.table_name,
                **_trace_user_meta,
            },
        )
        
        return {
            "status": "success",
            "message": f"File {file.filename} uploaded and processed successfully",
            "file_uuid": file_uuid,
            "filename": file.filename,
            "table_name": agent.table_name,
            "rows": len(agent.df),
            "columns": agent.columns
        }
    except Exception as e:
        log_full_exception(e, "File upload failed")
        set_progress(file_uuid, "error", 0, 100, "Upload failed due to an internal error", None)
        raise HTTPException(status_code=500, detail=user_facing_error_message(e))
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)


@router.post("/upload-raw", response_model=UploadRawResponse)
@observe(name="files.upload_raw")
async def upload_raw_file(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    """Step 1 of multi-sheet upload: receive raw .xlsx/.xls, return sheet list."""
    allowed = [".xlsx", ".xls"]
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in allowed:
        raise HTTPException(status_code=400, detail="Only .xlsx / .xls files are supported for multi-sheet upload")
    temp_id = str(uuid.uuid4())
    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name
    try:
        sheets = pd.ExcelFile(tmp_path).sheet_names
    except Exception as exc:
        os.remove(tmp_path)
        raise HTTPException(status_code=400, detail=f"Could not read Excel file: {exc}")
    _raw_upload_store[temp_id] = {
        "path": tmp_path,
        "filename": file.filename,
        "user_id": current_user.get("id"),
    }
    return UploadRawResponse(temp_id=temp_id, filename=file.filename, sheets=sheets)


@router.post("/extract-sheet")
@observe(name="files.extract_sheet")
async def extract_sheet(
    request: ExtractSheetRequest,
    db: DatabaseManager = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Step 2 of multi-sheet upload: extract one sheet from previously uploaded raw file."""
    entry = _raw_upload_store.get(request.temp_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Temp file not found – please re-upload the file")

    group_id = request.existing_group_id
    if not group_id:
        group_id = str(uuid.uuid4())
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO file_groups (group_id, original_filename, created_by) VALUES (%s, %s, %s)",
                    (group_id, entry["filename"], current_user.get("id")),
                )
            conn.commit()

    file_uuid = str(uuid.uuid4())
    sheet_display_name = f"{entry['filename']} [{request.sheet_name}]"
    progress_callback = create_progress_callback(file_uuid)

    try:
        agent = HybridAgent(
            file_path=entry["path"],
            filename=sheet_display_name,
            file_uuid=file_uuid,
            user_id=current_user.get("id"),
            project_id=request.project_id,
            subproject_id=request.subproject_id,
            progress_callback=progress_callback,
            sheet_name=request.sheet_name,
            file_group_id=group_id,
        )
    except Exception as exc:
        log_full_exception(exc, "extract-sheet failed")
        raise HTTPException(status_code=500, detail=user_facing_error_message(exc))

    return {
        "status": "success",
        "file_uuid": file_uuid,
        "group_id": group_id,
        "sheet_name": request.sheet_name,
        "filename": sheet_display_name,
        "table_name": agent.table_name,
        "rows": len(agent.df),
        "columns": agent.columns,
    }


@router.get("/groups")
@observe(name="files.list_groups")
async def list_file_groups(
    db: DatabaseManager = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Return all file_groups belonging to the current user."""
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            if current_user.get("role") == "admin":
                cur.execute(
                    "SELECT group_id, original_filename, created_at FROM file_groups ORDER BY created_at DESC"
                )
            else:
                cur.execute(
                    "SELECT group_id, original_filename, created_at FROM file_groups WHERE created_by = %s ORDER BY created_at DESC",
                    (current_user.get("id"),),
                )
            rows = cur.fetchall()
    return {
        "groups": [
            {"group_id": r[0], "original_filename": r[1], "created_at": r[2].isoformat() if r[2] else None}
            for r in rows
        ]
    }


@router.get("", response_model=FileListResponse)
@observe(name="files.list")
async def list_files(
    db: DatabaseManager = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """List ACTIVE uploaded Excel files (Excludes deleted ones)."""
    try:
        files_info = []
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                if current_user.get("role") == "admin":
                    cur.execute("""
                        SELECT file_uuid, filename, table_name, column_stats, created_on,
                               project_id, subproject_id, is_pinned, is_favorite, tags,
                               file_group_id, sheet_name
                        FROM file_registry 
                        WHERE is_deleted = FALSE
                    """)
                else:
                    cur.execute("""
                        SELECT file_uuid, filename, table_name, column_stats, created_on,
                               project_id, subproject_id, is_pinned, is_favorite, tags,
                               file_group_id, sheet_name
                        FROM file_registry 
                        WHERE created_by = %s AND is_deleted = FALSE
                    """, (current_user.get("id"),))
                
                results = cur.fetchall()
        
        for row in results:
            file_uuid, filename, table_name, column_stats, created_on, project_id, subproject_id, is_pinned, is_favorite, tags_raw, file_group_id, sheet_name = row
            try:
                stats = json.loads(column_stats) if isinstance(column_stats, str) else column_stats
                total_rows = stats.get("total_rows", 0)
                columns = list(stats.get("columns", {}).keys())
                tags = json.loads(tags_raw) if isinstance(tags_raw, str) else (tags_raw or [])
                
                files_info.append(FileInfo(
                    file_uuid=file_uuid,
                    filename=filename,
                    table_name=table_name,
                    total_rows=total_rows,
                    columns=columns,
                    column_stats=stats,
                    created_on=created_on.isoformat() if created_on else None,
                    is_deleted=False,
                    project_id=project_id,
                    subproject_id=subproject_id,
                    is_pinned=bool(is_pinned),
                    is_favorite=bool(is_favorite),
                    tags=tags,
                    file_group_id=file_group_id,
                    sheet_name=sheet_name,
                ))
            except Exception as e:
                logger.warning(f"Failed to parse stats for {filename}: {e}")
        
        return FileListResponse(files=files_info)
    except Exception as e:
        log_full_exception(e, "Failed to list files")
        raise HTTPException(status_code=500, detail=user_facing_error_message(e))


@router.get("/trash", response_model=FileListResponse)
@observe(name="files.list_trash")
async def list_trash_files(
    db: DatabaseManager = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """List temporarily deleted files (Recycle Bin)."""
    try:
        files_info = []
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                if current_user.get("role") == "admin":
                    cur.execute("""
                        SELECT file_uuid, filename, table_name, column_stats, created_on, deleted_at,
                               project_id, subproject_id, is_pinned, is_favorite, tags,
                               file_group_id, sheet_name
                        FROM file_registry 
                        WHERE is_deleted = TRUE
                        ORDER BY deleted_at DESC
                    """)
                else:
                    cur.execute("""
                        SELECT file_uuid, filename, table_name, column_stats, created_on, deleted_at,
                               project_id, subproject_id, is_pinned, is_favorite, tags,
                               file_group_id, sheet_name
                        FROM file_registry 
                        WHERE created_by = %s AND is_deleted = TRUE
                        ORDER BY deleted_at DESC
                    """, (current_user.get("id"),))
                
                results = cur.fetchall()
        
        for row in results:
            file_uuid, filename, table_name, column_stats, created_on, deleted_at, project_id, subproject_id, is_pinned, is_favorite, tags_raw, file_group_id, sheet_name = row
            try:
                stats = json.loads(column_stats) if isinstance(column_stats, str) else column_stats
                total_rows = stats.get("total_rows", 0)
                columns = list(stats.get("columns", {}).keys())
                tags = json.loads(tags_raw) if isinstance(tags_raw, str) else (tags_raw or [])
                
                files_info.append(FileInfo(
                    file_uuid=file_uuid,
                    filename=filename,
                    table_name=table_name,
                    total_rows=total_rows,
                    columns=columns,
                    column_stats=stats,
                    created_on=created_on.isoformat() if created_on else None,
                    deleted_at=deleted_at.isoformat() if deleted_at else None,
                    is_deleted=True,
                    project_id=project_id,
                    subproject_id=subproject_id,
                    is_pinned=bool(is_pinned),
                    is_favorite=bool(is_favorite),
                    tags=tags,
                    file_group_id=file_group_id,
                    sheet_name=sheet_name,
                ))
            except Exception as e:
                logger.warning(f"Failed to parse stats for {filename}: {e}")
        
        return FileListResponse(files=files_info)
    except Exception as e:
        log_full_exception(e, "Failed to list trash files")
        raise HTTPException(status_code=500, detail=user_facing_error_message(e))


@router.patch("/{file_uuid}/move")
@observe(name="files.move")
async def move_file(
    file_uuid: str,
    request: FileMoveRequest,
    db: DatabaseManager = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Move a file to a different project/subproject."""
    result = resolve_file_identifier(file_uuid, db)
    if not result:
        raise HTTPException(status_code=404, detail="File not found")
    enforce_file_access(result, current_user)
    
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE file_registry SET project_id = %s, subproject_id = %s WHERE file_uuid = %s",
                (request.target_folder_id, request.target_subfolder_id, file_uuid)
            )
        conn.commit()
    
    return {"status": "success", "file_uuid": file_uuid}


@router.patch("/{file_uuid}/metadata")
@observe(name="files.update_metadata")
async def update_file_metadata(
    file_uuid: str,
    request: FileMetadataUpdateRequest,
    db: DatabaseManager = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Update file metadata (pinned, favorite, tags)."""
    result = resolve_file_identifier(file_uuid, db)
    if not result:
        raise HTTPException(status_code=404, detail="File not found")
    enforce_file_access(result, current_user)
    
    updates = {}
    if request.is_pinned is not None:
        updates["is_pinned"] = request.is_pinned
    if request.is_favorite is not None:
        updates["is_favorite"] = request.is_favorite
    if request.tags is not None:
        updates["tags"] = json.dumps(request.tags)
    
    if updates:
        set_clause = ", ".join([f"{k} = %s" for k in updates.keys()])
        values = list(updates.values()) + [file_uuid]
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(f"UPDATE file_registry SET {set_clause} WHERE file_uuid = %s", values)
            conn.commit()
    
    return {"status": "success", "file_uuid": file_uuid}


@router.post("/bulk-move")
@observe(name="files.bulk_move")
async def bulk_move_files(
    request: BulkMoveRequest,
    db: DatabaseManager = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Move multiple files to a different project/subproject."""
    for file_id in request.file_ids:
        result = resolve_file_identifier(file_id, db)
        if result:
            enforce_file_access(result, current_user)
    
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            placeholders = ",".join(["%s"] * len(request.file_ids))
            cur.execute(
                f"UPDATE file_registry SET project_id = %s, subproject_id = %s WHERE file_uuid IN ({placeholders})",
                [request.target_folder_id, request.target_subfolder_id] + request.file_ids
            )
        conn.commit()
    
    return {"status": "success", "updated_count": len(request.file_ids)}


@router.get("/{file_identifier}")
@observe(name="files.get_info")
async def get_file_info(
    file_identifier: str,
    db: DatabaseManager = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Get details about a single file."""
    result = resolve_file_identifier(file_identifier, db)
    if not result:
        raise HTTPException(status_code=404, detail="File not found")
    enforce_file_access(result, current_user)
    
    file_uuid, filename, table_name, created_by = result
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT column_stats, created_on, is_deleted, file_group_id FROM file_registry WHERE file_uuid = %s",
                (file_uuid,)
            )
            row = cur.fetchone()
            if row:
                column_stats, created_on, is_deleted, file_group_id = row
            else:
                # Fallback to ETL tables
                cur.execute(
                    "SELECT column_stats, created_at FROM etl_system.etl_tables WHERE table_id = %s",
                    (file_uuid,)
                )
                row_etl = cur.fetchone()
                if row_etl:
                    column_stats, created_on = row_etl
                    is_deleted = False
                    file_group_id = None
                else:
                    # Fallback to Board files
                    cur.execute(
                        "SELECT column_stats, created_on FROM board_files WHERE file_uuid = %s",
                        (file_uuid,)
                    )
                    row_board = cur.fetchone()
                    if row_board:
                        column_stats, created_on = row_board
                        is_deleted = False
                        file_group_id = None
                    else:
                        # Fallback to ETL Connections
                        cur.execute(
                            "SELECT created_at FROM etl_system.etl_connections WHERE connection_id = %s",
                            (file_uuid,)
                        )
                        row_conn = cur.fetchone()
                        if row_conn:
                            column_stats = {}
                            created_on = row_conn[0]
                            is_deleted = False
                            file_group_id = None
                        else:
                            raise HTTPException(status_code=404, detail="File not found")
    
    stats = json.loads(column_stats) if isinstance(column_stats, str) else column_stats
    return {
        "file_uuid": file_uuid,
        "filename": filename,
        "table_name": table_name,
        "column_stats": stats,
        "created_on": created_on.isoformat() if created_on else None,
        "is_deleted": is_deleted,
        "file_group_id": file_group_id,
    }


@router.get("/{file_identifier}/chunks")
@observe(name="files.get_chunks")
async def get_file_chunks(
    file_identifier: str,
    db: DatabaseManager = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Get paginated data chunks from a file."""
    result = resolve_file_identifier(file_identifier, db)
    if not result:
        raise HTTPException(status_code=404, detail="File not found")
    enforce_file_access(result, current_user)
    
    file_uuid, filename, table_name, _ = result
    agent = get_agent(file_uuid=file_uuid, filename=filename, load_existing=True, user_id=current_user.get("id"))
    
    return {
        "file_uuid": file_uuid,
        "filename": filename,
        "table_name": table_name,
        "rows": len(agent.df),
        "columns": agent.columns,
        "preview": agent.df.head(50).to_dict(orient="records")
    }


@router.delete("/{file_identifier}")
@observe(name="files.soft_delete")
async def delete_file(
    file_identifier: str,
    db: DatabaseManager = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Soft-delete a file (move to trash)."""
    result = resolve_file_identifier(file_identifier, db)
    if not result:
        raise HTTPException(status_code=404, detail="File not found")
    enforce_file_access(result, current_user)
    
    file_uuid = result[0]
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE file_registry SET is_deleted = TRUE, deleted_at = NOW() WHERE file_uuid = %s",
                (file_uuid,)
            )
        conn.commit()
    
    log_audit_event(db=db, user_id=current_user.get("id"), action="delete_file", entity_type="file", entity_id=file_uuid)
    return {"status": "success", "file_uuid": file_uuid}


@router.post("/{file_identifier}/restore")
@observe(name="files.restore")
async def restore_file(
    file_identifier: str,
    db: DatabaseManager = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Restore a deleted file from trash."""
    result = resolve_file_identifier(file_identifier, db)
    if not result:
        raise HTTPException(status_code=404, detail="File not found")
    enforce_file_access(result, current_user)
    
    file_uuid = result[0]
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE file_registry SET is_deleted = FALSE, deleted_at = NULL WHERE file_uuid = %s",
                (file_uuid,)
            )
        conn.commit()
    
    return {"status": "success", "file_uuid": file_uuid}


@router.delete("/{file_identifier}/permanent")
@observe(name="files.permanent_delete")
async def permanent_delete_file(
    file_identifier: str,
    db: DatabaseManager = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Permanently delete a file and its associated tables."""
    result = resolve_file_identifier(file_identifier, db)
    if not result:
        raise HTTPException(status_code=404, detail="File not found")
    enforce_file_access(result, current_user)
    
    file_uuid, filename, table_name, _ = result
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM file_registry WHERE file_uuid = %s", (file_uuid,))
            try:
                cur.execute(f"DROP TABLE IF EXISTS {table_name} CASCADE", )
            except:
                pass
        conn.commit()
    
    log_audit_event(db=db, user_id=current_user.get("id"), action="permanent_delete_file", entity_type="file", entity_id=file_uuid)
    return {"status": "success", "file_uuid": file_uuid}


@router.delete("/trash/empty")
@observe(name="files.empty_trash")
async def empty_trash(
    db: DatabaseManager = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Permanently delete all files in user's trash."""
    user_id = current_user.get("id")
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT file_uuid, table_name FROM file_registry WHERE created_by = %s AND is_deleted = TRUE",
                (user_id,)
            )
            rows = cur.fetchall()
            for file_uuid, table_name in rows:
                try:
                    cur.execute(f"DROP TABLE IF EXISTS {table_name} CASCADE")
                except:
                    pass
                cur.execute("DELETE FROM file_registry WHERE file_uuid = %s", (file_uuid,))
        conn.commit()
    
    return {"status": "success", "deleted_count": len(rows)}


@router.delete("/{file_identifier}/cache")
@observe(name="files.delete_cache")
async def delete_file_cache(
    file_identifier: str,
    db: DatabaseManager = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Clear semantic cache for a file."""
    result = resolve_file_identifier(file_identifier, db)
    if not result:
        raise HTTPException(status_code=404, detail="File not found")
    enforce_file_access(result, current_user)
    
    file_uuid = result[0]
    try:
        from app.core.cache import _redis_cache
        _redis_cache.clear(file_uuid)
    except:
        pass
    
    return {"status": "success", "file_uuid": file_uuid}
