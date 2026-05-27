from fastapi import APIRouter

from app.core.database import DatabaseManager
from app.utils.logging import log_full_exception

try:
    from app.config import observe
except ImportError:
    def observe(_func=None, *, name: str = "", **kwargs):
        def decorator(func):
            return func
        return _func if _func else decorator

router = APIRouter(tags=["health"])


@router.get("/health")
@observe(name="health.check")
async def health_check():
    """Health check endpoint."""
    try:
        db = DatabaseManager()
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        log_full_exception(e, "Health check failed")
        return {"status": "unhealthy", "database": "disconnected", "error": "internal error"}, 500


@router.get("/api/info")
@observe(name="health.api_info")
async def api_info():
    """API information and available endpoints."""
    return {
        "status": "ok",
        "api": "Excel Analysis API",
        "version": "1.0.0",
        "endpoints": {
            "files": {
                "upload": "POST /api/files/upload - Upload Excel/CSV file",
                "list": "GET /api/files - List all uploaded files",
                "info": "GET /api/files/{file_identifier} - Get file details (UUID or filename)",
                "delete": "DELETE /api/files/{file_identifier} - Delete file (UUID or filename)",
                "preview": "GET /api/preview/{file_identifier} - Preview file data (UUID or filename)",
                "statistics": "GET /api/statistics/{file_identifier} - Get statistics (UUID or filename)",
                "export": "POST /api/export/{file_identifier} - Export file data (UUID or filename)",
            },
            "analysis": {
                "query": "POST /api/query - Run analysis query (supports file_uuid or filename)",
            },
            "dashboard": {
                "generate": "GET /api/dashboard/{file_identifier} - Generate KPI dashboard",
                "widget": "POST /api/dashboard/{file_identifier}/widget - Create widget from query",
                "update_widgets": "POST /api/dashboard/{file_identifier}/update-widgets - Update dashboard widgets",
            },
        },
    }
