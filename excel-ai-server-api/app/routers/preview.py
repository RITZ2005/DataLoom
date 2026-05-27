from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import enforce_file_access, get_agent, get_db, resolve_file_identifier
from app.utils.logging import log_full_exception, user_facing_error_message
from app.core.auth import get_current_user

try:
    from app.config import observe
except ImportError:
    def observe(_func=None, *, name: str = "", **kwargs):
        def decorator(func):
            return func
        return _func if _func else decorator

router = APIRouter(prefix="/api", tags=["preview"])


@router.get("/preview/{file_identifier}")
@observe(name="preview.file")
async def preview_file(
    file_identifier: str,
    rows: int = 10,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        result = resolve_file_identifier(file_identifier, db)
        if not result:
            raise HTTPException(status_code=404, detail=f"File '{file_identifier}' not found")

        enforce_file_access(result, current_user)
        file_uuid, filename, table_name, _user_id = result

        agent = get_agent(file_uuid=file_uuid, filename=filename, load_existing=True)
        preview_df = agent.df.head(rows)

        preview_df = preview_df.astype(object)
        preview_df = preview_df.where(preview_df.notna(), "None")
        null_strings = {"NaT", "nan", "NaN", "null", "NAT"}
        preview_df = preview_df.replace(null_strings, "None")

        return {
            "status": "success",
            "file_uuid": file_uuid,
            "filename": filename,
            "total_rows": len(agent.df),
            "preview_rows": len(preview_df),
            "columns": agent.columns,
            "data": preview_df.to_dict(orient="records"),
        }
    except HTTPException:
        raise
    except Exception as e:
        log_full_exception(e, "Preview failed")
        raise HTTPException(status_code=500, detail=user_facing_error_message(e))


@router.get("/statistics/{file_identifier}")
@observe(name="preview.statistics")
async def get_statistics(
    file_identifier: str,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        result = resolve_file_identifier(file_identifier, db)
        if not result:
            raise HTTPException(status_code=404, detail=f"File '{file_identifier}' not found")

        enforce_file_access(result, current_user)
        file_uuid, filename, table_name, _user_id = result

        agent = get_agent(file_uuid=file_uuid, filename=filename, load_existing=True)
        stats = agent.column_stats

        return {
            "status": "success",
            "file_uuid": file_uuid,
            "filename": filename,
            "statistics": stats,
        }
    except HTTPException:
        raise
    except Exception as e:
        log_full_exception(e, "Statistics retrieval failed")
        raise HTTPException(status_code=500, detail=user_facing_error_message(e))
