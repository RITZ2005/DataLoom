import json

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import enforce_file_access, get_db, get_or_load_agent, resolve_file_identifier
from app.utils.logging import log_full_exception, logger, user_facing_error_message
from app.core.auth import UserManager, get_current_user

try:
    from app.config import observe
except ImportError:
    def observe(_func=None, *, name: str = "", **kwargs):
        def decorator(func):
            return func
        return _func if _func else decorator

router = APIRouter(prefix="/api", tags=["export"])


@router.post("/export/{file_identifier}")
@observe(name="export.file")
async def export_file(
    file_identifier: str,
    format: str = "json",
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_manager = UserManager()
    permissions = user_manager.get_permissions(current_user.get("role", ""))
    if "export_data" not in permissions:
        raise HTTPException(status_code=403, detail="You don't have permission to export data")

    try:
        result = resolve_file_identifier(file_identifier, db)
        if not result:
            raise HTTPException(status_code=404, detail=f"File '{file_identifier}' not found")

        enforce_file_access(result, current_user)
        file_uuid, filename, table_name, _user_id = result

        agent = get_or_load_agent(file_uuid=file_uuid, filename=filename, load_existing=True, db=db)

        if format.lower() == "csv":
            csv_data = agent.df.to_csv(index=False)
            return {"status": "success", "file_uuid": file_uuid, "format": "csv", "data": csv_data}
        if format.lower() == "json":
            try:
                json_data = json.loads(agent.df.to_json(orient="records", date_format="iso"))
            except Exception as ser_err:
                logger.warning("[/api/export] JSON roundtrip fallback for %s: %s", file_uuid, ser_err)
                safe_df = agent.df.copy()
                safe_df = safe_df.replace([float("inf"), float("-inf")], None)
                safe_df = safe_df.where(pd.notnull(safe_df), None)
                raw_records = safe_df.to_dict(orient="records")
                json_data = json.loads(json.dumps(raw_records, default=str))
            return {"status": "success", "file_uuid": file_uuid, "format": "json", "data": json_data}

        raise HTTPException(status_code=400, detail=f"Format {format} not supported")
    except HTTPException:
        raise
    except Exception as e:
        log_full_exception(e, "Export failed")
        raise HTTPException(status_code=500, detail=user_facing_error_message(e))
