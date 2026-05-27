from fastapi import HTTPException, Depends, APIRouter
from fastapi.responses import StreamingResponse
from typing import List, Optional, Dict, Any
import logging
import json
import uuid
import secrets
from psycopg2.extras import RealDictCursor

from app.core import DatabaseManager
from app.utils.logging import log_full_exception, user_facing_error_message
from app.core.auth import get_current_user
from app.dependencies import get_db, get_agent, get_or_load_agent, resolve_file_identifier
from app.utils.audit import log_audit_event
from app.config import logger
from app.schemas import (
    SubprojectInfo, ProjectInfo, ProjectListResponse, ProjectCreateRequest,
    ProjectUpdateRequest, ActiveFileRequest, ShareProjectResponse,
    SubprojectCreateRequest, SubprojectUpdateRequest, ProjectDeleteResponse,
    SubprojectDeleteResponse
)

try:
    from app.config import observe
except ImportError:
    def observe(_func=None, *, name: str = "", **kwargs):
        def decorator(func):
            return func
        return _func if _func else decorator

# ============================================================================
# ROUTER
# ============================================================================
router = APIRouter(prefix="/api/projects", tags=["projects"])

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def load_project_dashboard(project_id: str, db) -> dict | None:
    """Load a project-level dashboard from the dashboards table (keyed by project_id)."""
    try:
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT widgets_json, file_uuid FROM dashboards WHERE dashboard_id = %s LIMIT 1;",
                    (f"proj-{project_id}",)
                )
                result = cur.fetchone()
                if result:
                    data = result[0] if isinstance(result[0], dict) else json.loads(result[0])
                    return data
        return None
    except Exception as e:
        logger.error(f"Failed to load project dashboard: {e}")
        return None

# ============================================================================
# ENDPOINTS
# ============================================================================

@router.get("", response_model=ProjectListResponse)
@observe(name="project.list")
async def list_projects(
    db: DatabaseManager = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    List projects with their subprojects for the current user.
    """
    try:
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                if current_user.get("role") == "admin":
                    cur.execute(
                        "SELECT project_id, name, created_on, color, is_dashboard, active_file_uuid, is_shared, share_token FROM projects ORDER BY created_on DESC"
                    )
                    projects = cur.fetchall()
                    cur.execute(
                        "SELECT subproject_id, project_id, name, created_on FROM subprojects ORDER BY created_on DESC"
                    )
                    subprojects = cur.fetchall()
                else:
                    cur.execute(
                        "SELECT project_id, name, created_on, color, is_dashboard, active_file_uuid, is_shared, share_token FROM projects WHERE created_by = %s ORDER BY created_on DESC",
                        (current_user.get("id"),)
                    )
                    projects = cur.fetchall()
                    cur.execute(
                        "SELECT subproject_id, project_id, name, created_on FROM subprojects WHERE created_by = %s ORDER BY created_on DESC",
                        (current_user.get("id"),)
                    )
                    subprojects = cur.fetchall()

        # Get file counts for projects and subprojects
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT project_id, COUNT(*) as cnt 
                    FROM file_registry 
                    WHERE is_deleted = FALSE AND project_id IS NOT NULL AND subproject_id IS NULL
                    GROUP BY project_id
                """)
                project_file_counts = {row[0]: row[1] for row in cur.fetchall()}
                
                cur.execute("""
                    SELECT subproject_id, COUNT(*) as cnt 
                    FROM file_registry 
                    WHERE is_deleted = FALSE AND subproject_id IS NOT NULL 
                    GROUP BY subproject_id
                """)
                subproject_file_counts = {row[0]: row[1] for row in cur.fetchall()}

        project_map: Dict[str, ProjectInfo] = {}
        for project_id, name, created_on, color, is_dashboard, active_file_uuid, is_shared, share_token in projects:
            project_map[project_id] = ProjectInfo(
                project_id=project_id,
                name=name,
                created_on=created_on.isoformat() if created_on else None,
                subprojects=[],
                file_count=project_file_counts.get(project_id, 0),
                color=color,
                is_dashboard=bool(is_dashboard),
                active_file_uuid=active_file_uuid,
                is_shared=bool(is_shared),
                share_token=share_token
            )

        for subproject_id, project_id, name, created_on in subprojects:
            if project_id not in project_map:
                continue
            project_map[project_id].subprojects.append(
                SubprojectInfo(
                    subproject_id=subproject_id,
                    project_id=project_id,
                    name=name,
                    created_on=created_on.isoformat() if created_on else None,
                    file_count=subproject_file_counts.get(subproject_id, 0)
                )
            )

        return ProjectListResponse(projects=list(project_map.values()))
    except Exception as e:
        logger.error(f"Failed to list projects: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("", response_model=ProjectInfo)
@observe(name="project.create")
async def create_project(
    request: ProjectCreateRequest,
    db: DatabaseManager = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    name = request.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Project name is required")

    project_id = str(uuid.uuid4())
    color = request.color
    user_id = current_user.get("id")
    try:
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO projects (project_id, name, created_by, color, is_dashboard, active_file_uuid) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    (project_id, name, user_id, color, request.is_dashboard,
                     request.source_file_uuid if request.is_dashboard else None)
                )
                # If creating a dashboard with a source file, move that file into this project
                if request.is_dashboard and request.source_file_uuid:
                    cur.execute(
                        "UPDATE file_registry SET project_id = %s WHERE file_uuid = %s AND created_by = %s",
                        (project_id, request.source_file_uuid, user_id)
                    )
            conn.commit()

        return ProjectInfo(
            project_id=project_id,
            name=name,
            subprojects=[],
            color=color,
            is_dashboard=request.is_dashboard,
            active_file_uuid=request.source_file_uuid if request.is_dashboard else None,
        )
    except Exception as e:
        logger.error(f"Failed to create project: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{project_id}/subprojects", response_model=SubprojectInfo)
@observe(name="project.create_subproject")
async def create_subproject(
    project_id: str,
    request: SubprojectCreateRequest,
    db: DatabaseManager = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    name = request.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Subproject name is required")

    try:
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                if current_user.get("role") == "admin":
                    cur.execute(
                        "SELECT project_id FROM projects WHERE project_id = %s",
                        (project_id,)
                    )
                else:
                    cur.execute(
                        "SELECT project_id FROM projects WHERE project_id = %s AND created_by = %s",
                        (project_id, current_user.get("id"))
                    )
                if not cur.fetchone():
                    raise HTTPException(status_code=404, detail="Project not found")

                subproject_id = str(uuid.uuid4())
                cur.execute(
                    "INSERT INTO subprojects (subproject_id, project_id, name, created_by) VALUES (%s, %s, %s, %s)",
                    (subproject_id, project_id, name, current_user.get("id"))
                )
            conn.commit()

        return SubprojectInfo(subproject_id=subproject_id, project_id=project_id, name=name)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create subproject: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{project_id}/dashboard/save")
@observe(name="project.save_dashboard")
async def save_project_dashboard_layout(
    project_id: str,
    request: dict,
    db: DatabaseManager = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Save widget positions/layout for the project dashboard (dashboard-first persistence)."""
    widgets = request.get("widgets", [])
    if not widgets:
        raise HTTPException(status_code=400, detail="widgets array is required")
    try:
        saved = load_project_dashboard(project_id, db)
        fingerprint = saved.get("fingerprint", {}) if saved else {}

        with db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT active_file_uuid FROM projects WHERE project_id = %s", (project_id,))
                proj_row = cur.fetchone()
                if not proj_row:
                    raise HTTPException(status_code=404, detail="Project not found")
                active_file_uuid = proj_row[0]

                dashboard_data = {
                    "status": "success",
                    "filename": saved.get("filename", "") if saved else "",
                    "file_uuid": active_file_uuid or "",
                    "total_rows": saved.get("total_rows", 0) if saved else 0,
                    "total_columns": saved.get("total_columns", 0) if saved else 0,
                    "widgets": widgets,
                    "fingerprint": fingerprint,
                }
                cur.execute("""
                    INSERT INTO dashboards (dashboard_id, project_id, file_uuid, widgets_json, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    ON CONFLICT (dashboard_id) DO UPDATE
                    SET widgets_json = EXCLUDED.widgets_json, updated_at = CURRENT_TIMESTAMP;
                """, (
                    f"proj-{project_id}",
                    project_id,
                    active_file_uuid,
                    json.dumps(dashboard_data, default=str)
                ))
            conn.commit()
        return {"status": "success", "message": "Dashboard layout saved"}
    except HTTPException:
        raise
    except Exception as e:
        log_full_exception(e, "Failed to save project dashboard layout")
        raise HTTPException(status_code=500, detail="Error saving dashboard layout")

@router.put("/{project_id}/active-file")
@observe(name="project.update_active_file")
async def update_active_file(
    project_id: str,
    request: ActiveFileRequest,
    db: DatabaseManager = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Switch the active data source for a dashboard project.
    Dashboard-first: loads the saved project dashboard template and clones
    it onto the new file's data via clone_widgets_from_blueprints.
    """
    try:
        with db.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Verify file belongs to this project
                cur.execute(
                    "SELECT 1 FROM file_registry WHERE file_uuid = %s AND project_id = %s",
                    (request.file_uuid, project_id)
                )
                if not cur.fetchone():
                    raise HTTPException(status_code=400, detail="File does not belong to this project")
                cur.execute(
                    "UPDATE projects SET active_file_uuid = %s WHERE project_id = %s AND created_by = %s RETURNING project_id",
                    (request.file_uuid, project_id, current_user.get("id"))
                )
                if not cur.fetchone():
                    raise HTTPException(status_code=404, detail="Project not found or unauthorized")
            conn.commit()

        # Load the saved project dashboard (the template/blueprint)
        saved_dashboard = load_project_dashboard(project_id, db)

        # Resolve the new active file
        result = resolve_file_identifier(request.file_uuid, db)
        if not result:
            return {"status": "success", "active_file_uuid": request.file_uuid, "dashboard_data": None}

        f_uuid, f_name, _table, _uid = result
        agent = get_agent(file_uuid=f_uuid, filename=f_name, load_existing=True)

        if saved_dashboard:
            # Clone saved template onto new file's data
            base_widgets = saved_dashboard.get("widgets", [])
            cloned_widgets = agent.clone_widgets_from_blueprints(base_widgets)
            fingerprint = agent._build_file_fingerprint()
            dashboard_data = agent._build_response_envelope(cloned_widgets, fingerprint)
            # Update project dashboard with cloned result
            agent.save_project_dashboard(project_id, cloned_widgets, fingerprint)
        else:
            # No project dashboard yet — generate fresh
            dashboard_data = agent.generate_kpi_dashboard()
            widgets = dashboard_data.get("widgets", []) if dashboard_data else []
            fp = dashboard_data.get("fingerprint") if dashboard_data else None
            agent.save_project_dashboard(project_id, widgets, fp)

        return {
            "status": "success",
            "active_file_uuid": request.file_uuid,
            "dashboard_data": dashboard_data,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update active file: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{project_id}/dashboard")
@observe(name="project.get_dashboard")
async def get_project_dashboard(
    project_id: str,
    db: DatabaseManager = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Canonical project-centric dashboard load.
    Dashboard-first approach: one dashboard per project stored in `dashboards` table.
    When the active file differs from what was last rendered, the saved widget
    template is cloned onto the new file's data via clone_widgets_from_blueprints.
    """
    try:
        with db.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT project_id, name, color, is_dashboard, active_file_uuid, "
                    "is_shared, share_token, created_on "
                    "FROM projects WHERE project_id = %s",
                    (project_id,)
                )
                proj = cur.fetchone()
                if not proj:
                    raise HTTPException(status_code=404, detail="Project not found")

                # Ownership check (admins see all)
                if current_user.get("role") != "admin":
                    cur.execute(
                        "SELECT 1 FROM projects WHERE project_id = %s AND created_by = %s",
                        (project_id, current_user.get("id"))
                    )
                    if not cur.fetchone():
                        raise HTTPException(status_code=403, detail="Access denied")

                # Gather all files that belong to this project
                cur.execute(
                    "SELECT file_uuid, filename, table_name, column_stats, created_on "
                    "FROM file_registry WHERE project_id = %s AND is_deleted = FALSE ORDER BY created_on DESC",
                    (project_id,)
                )
                files = []
                for r in cur.fetchall():
                    row = dict(r)
                    stats = row.pop("column_stats", None)
                    if isinstance(stats, str):
                        try: stats = json.loads(stats)
                        except: stats = {}
                    elif stats is None:
                        stats = {}
                    row["total_rows"] = stats.get("total_rows", 0)
                    files.append(row)

        active_file_uuid = proj.get("active_file_uuid")

        # No active file → empty dashboard (upload CTA)
        if not active_file_uuid or not files:
            return {
                "project": {
                    "project_id": proj["project_id"],
                    "name": proj["name"],
                    "created_on": str(proj["created_on"]) if proj.get("created_on") else None,
                    "color": proj.get("color"),
                    "is_dashboard": proj.get("is_dashboard"),
                    "active_file_uuid": active_file_uuid,
                    "is_shared": proj.get("is_shared", False),
                    "share_token": proj.get("share_token"),
                },
                "files": files,
                "dashboard_data": None,
            }

        # Load saved project dashboard from `dashboards` table
        saved_dashboard = load_project_dashboard(project_id, db)
        saved_file_uuid = saved_dashboard.get("file_uuid") if saved_dashboard else None

        # Resolve active file for agent
        result = resolve_file_identifier(active_file_uuid, db)
        if not result:
            return {
                "project": {
                    "project_id": proj["project_id"],
                    "name": proj["name"],
                    "created_on": str(proj["created_on"]) if proj.get("created_on") else None,
                    "color": proj.get("color"),
                    "is_dashboard": proj.get("is_dashboard"),
                    "active_file_uuid": active_file_uuid,
                    "is_shared": proj.get("is_shared", False),
                    "share_token": proj.get("share_token"),
                },
                "files": files,
                "dashboard_data": None,
            }

        f_uuid, f_name, _table, _uid = result
        agent = get_agent(file_uuid=f_uuid, filename=f_name, load_existing=True)

        if saved_dashboard and saved_file_uuid == active_file_uuid:
            # Same file as last time — return saved dashboard as-is
            dashboard_data = saved_dashboard
        elif saved_dashboard:
            # Different file — clone saved template onto new file's data
            base_widgets = saved_dashboard.get("widgets", [])
            cloned_widgets = agent.clone_widgets_from_blueprints(base_widgets)
            fingerprint = agent._build_file_fingerprint()
            dashboard_data = agent._build_response_envelope(cloned_widgets, fingerprint)
            # Save the cloned result as the project dashboard (updates file_uuid)
            agent.save_project_dashboard(project_id, cloned_widgets, fingerprint)
        else:
            # No saved dashboard yet — generate fresh and save as project dashboard
            dashboard_data = agent.generate_kpi_dashboard()
            widgets = dashboard_data.get("widgets", []) if dashboard_data else []
            fp = dashboard_data.get("fingerprint") if dashboard_data else None
            agent.save_project_dashboard(project_id, widgets, fp)

        return {
            "project": {
                "project_id": proj["project_id"],
                "name": proj["name"],
                "created_on": str(proj["created_on"]) if proj.get("created_on") else None,
                "color": proj.get("color"),
                "is_dashboard": proj.get("is_dashboard"),
                "active_file_uuid": active_file_uuid,
                "is_shared": proj.get("is_shared", False),
                "share_token": proj.get("share_token"),
            },
            "files": files,
            "dashboard_data": dashboard_data,
        }
    except HTTPException:
        raise
    except Exception as e:
        log_full_exception(e, "Failed to get project dashboard")
        raise HTTPException(status_code=500, detail="Error loading project dashboard")

@router.put("/{project_id}/active-file-stream")
@observe(name="project.update_active_file_stream")
async def update_project_active_file_stream(
    project_id: str,
    request: ActiveFileRequest,
    db: DatabaseManager = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Stream widgets one-by-one as NDJSON for project dashboards."""
    with db.get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT 1 FROM file_registry WHERE file_uuid = %s AND project_id = %s",
                (request.file_uuid, project_id)
            )
            if not cur.fetchone():
                raise HTTPException(status_code=400, detail="File does not belong to this project")
            cur.execute(
                "UPDATE projects SET active_file_uuid = %s WHERE project_id = %s AND created_by = %s RETURNING project_id",
                (request.file_uuid, project_id, current_user.get("id"))
            )
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Project not found or unauthorized")
        conn.commit()

    saved_dashboard = load_project_dashboard(project_id, db)
    result = resolve_file_identifier(request.file_uuid, db)
    if not result:
        raise HTTPException(status_code=404, detail="File not found")

    f_uuid, f_name, _table, _uid = result
    agent = get_or_load_agent(file_uuid=f_uuid, filename=f_name, load_existing=True, db=db)

    base_widgets = saved_dashboard.get("widgets", []) if saved_dashboard else []

    def _stream_widgets():
        all_cloned = []
        if base_widgets:
            for widget in agent.clone_widgets_from_blueprints_iter(base_widgets):
                all_cloned.append(widget)
                yield json.dumps({"type": "widget", "widget": widget}, default=str) + "\n"
        else:
            dashboard_data = agent.generate_kpi_dashboard()
            widgets = dashboard_data.get("widgets", []) if dashboard_data else []
            for w in widgets:
                all_cloned.append(w)
                yield json.dumps({"type": "widget", "widget": w}, default=str) + "\n"

        fp = agent._build_file_fingerprint()
        dashboard_data = agent._build_response_envelope(all_cloned, fp)
        agent.save_project_dashboard(project_id, all_cloned, fp)
        yield json.dumps({
            "type": "done",
            "active_file_uuid": request.file_uuid,
            "fingerprint": fp,
            "total_widgets": len(all_cloned)
        }, default=str) + "\n"

    return StreamingResponse(_stream_widgets(), media_type="application/x-ndjson")

@router.delete("/{project_id}/subprojects/{subproject_id}", response_model=SubprojectDeleteResponse)
@observe(name="project.delete_subproject")
async def delete_subproject(
    project_id: str,
    subproject_id: str,
    db: DatabaseManager = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Delete a subproject and all its files (CASCADE DELETE).
    """
    try:
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                # Check ownership
                if current_user.get("role") == "admin":
                    cur.execute(
                        "SELECT subproject_id FROM subprojects WHERE subproject_id = %s AND project_id = %s",
                        (subproject_id, project_id)
                    )
                else:
                    cur.execute(
                        "SELECT subproject_id FROM subprojects WHERE subproject_id = %s AND project_id = %s AND created_by = %s",
                        (subproject_id, project_id, current_user.get("id"))
                    )
                if not cur.fetchone():
                    raise HTTPException(status_code=404, detail="Subproject not found")
                
                # Get all files in this subproject
                cur.execute(
                    "SELECT file_uuid, filename, table_name FROM file_registry WHERE subproject_id = %s",
                    (subproject_id,)
                )
                files_to_delete = cur.fetchall()
                
                # Delete each file properly (drop tables, delete from registry)
                for file_uuid, filename, table_name in files_to_delete:
                    try:
                        # Drop the data table
                        cur.execute(f"DROP TABLE IF EXISTS {table_name}")
                        
                        # Delete from file registry
                        cur.execute(
                            "DELETE FROM file_registry WHERE file_uuid = %s",
                            (file_uuid,)
                        )
                        
                        # Delete chat history
                        cur.execute(
                            "DELETE FROM chat_history WHERE file_uuid = %s",
                            (file_uuid,)
                        )
                        
                        # Delete semantic cache for this file
                        try:
                            agent = get_agent(file_uuid=file_uuid, filename=filename, load_existing=True)
                            agent.delete_file_cache(file_uuid)
                        except Exception as cache_error:
                            logger.warning(f"Failed to delete cache for {file_uuid}: {cache_error}")
                            
                    except Exception as file_error:
                        logger.error(f"Error deleting file {file_uuid}: {file_error}")
                        # Continue with other files
                
                # Delete the subproject
                cur.execute(
                    "DELETE FROM subprojects WHERE subproject_id = %s",
                    (subproject_id,)
                )
            conn.commit()

        log_audit_event(
            db=db,
            user_id=current_user.get("id"),
            action="delete_subproject_cascade",
            entity_type="subproject",
            entity_id=subproject_id,
            details={"files_deleted": len(files_to_delete)}
        )

        return SubprojectDeleteResponse(status="success", subproject_id=subproject_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete subproject: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/{project_id}")
@observe(name="project.update")
async def update_project(
    project_id: str,
    request: ProjectUpdateRequest,
    db: DatabaseManager = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Rename or update color of a folder (project)."""
    try:
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                if current_user.get("role") == "admin":
                    cur.execute("SELECT project_id FROM projects WHERE project_id = %s", (project_id,))
                else:
                    cur.execute("SELECT project_id FROM projects WHERE project_id = %s AND created_by = %s",
                                (project_id, current_user.get("id")))
                if not cur.fetchone():
                    raise HTTPException(status_code=404, detail="Folder not found")

                updates, params = [], []
                if request.name is not None:
                    updates.append("name = %s")
                    params.append(request.name.strip())
                if request.color is not None:
                    updates.append("color = %s")
                    params.append(request.color)
                if not updates:
                    raise HTTPException(status_code=400, detail="Nothing to update")

                params.append(project_id)
                cur.execute(f"UPDATE projects SET {', '.join(updates)} WHERE project_id = %s", params)
            conn.commit()
        return {"status": "success", "project_id": project_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update project: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/{project_id}/subprojects/{subproject_id}")
@observe(name="project.update_subproject")
async def update_subproject(
    project_id: str,
    subproject_id: str,
    request: SubprojectUpdateRequest,
    db: DatabaseManager = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Rename a subfolder (subproject)."""
    try:
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                if current_user.get("role") == "admin":
                    cur.execute("SELECT subproject_id FROM subprojects WHERE subproject_id = %s AND project_id = %s",
                                (subproject_id, project_id))
                else:
                    cur.execute("SELECT subproject_id FROM subprojects WHERE subproject_id = %s AND project_id = %s AND created_by = %s",
                                (subproject_id, project_id, current_user.get("id")))
                if not cur.fetchone():
                    raise HTTPException(status_code=404, detail="Subfolder not found")

                if not request.name or not request.name.strip():
                    raise HTTPException(status_code=400, detail="Name is required")

                cur.execute("UPDATE subprojects SET name = %s WHERE subproject_id = %s",
                            (request.name.strip(), subproject_id))
            conn.commit()
        return {"status": "success", "subproject_id": subproject_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update subproject: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/{project_id}", response_model=ProjectDeleteResponse)
@observe(name="project.delete")
async def delete_project(
    project_id: str,
    db: DatabaseManager = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Delete a project, all its subprojects, and all files (CASCADE DELETE).
    """
    try:
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                # Check ownership
                if current_user.get("role") == "admin":
                    cur.execute(
                        "SELECT project_id FROM projects WHERE project_id = %s",
                        (project_id,)
                    )
                else:
                    cur.execute(
                        "SELECT project_id FROM projects WHERE project_id = %s AND created_by = %s",
                        (project_id, current_user.get("id"))
                    )
                if not cur.fetchone():
                    raise HTTPException(status_code=404, detail="Project not found")
                
                # Get all files in this project (including those in subprojects)
                cur.execute(
                    "SELECT file_uuid, filename, table_name FROM file_registry WHERE project_id = %s",
                    (project_id,)
                )
                files_to_delete = cur.fetchall()
                
                # Delete each file properly (drop tables, delete from registry)
                for file_uuid, filename, table_name in files_to_delete:
                    try:
                        # Drop the data table
                        cur.execute(f"DROP TABLE IF EXISTS {table_name}")
                        
                        # Delete from file registry
                        cur.execute(
                            "DELETE FROM file_registry WHERE file_uuid = %s",
                            (file_uuid,)
                        )
                        
                        # Delete chat history
                        cur.execute(
                            "DELETE FROM chat_history WHERE file_uuid = %s",
                            (file_uuid,)
                        )
                        
                        # Delete semantic cache for this file
                        try:
                            agent = get_agent(file_uuid=file_uuid, filename=filename, load_existing=True)
                            agent.delete_file_cache(file_uuid)
                        except Exception as cache_error:
                            logger.warning(f"Failed to delete cache for {file_uuid}: {cache_error}")
                            
                    except Exception as file_error:
                        logger.error(f"Error deleting file {file_uuid}: {file_error}")
                        # Continue with other files
                
                # Delete all subprojects
                cur.execute(
                    "DELETE FROM subprojects WHERE project_id = %s",
                    (project_id,)
                )
                
                # Delete the project
                cur.execute(
                    "DELETE FROM projects WHERE project_id = %s",
                    (project_id,)
                )
            conn.commit()

        log_audit_event(
            db=db,
            user_id=current_user.get("id"),
            action="delete_project_cascade",
            entity_type="project",
            entity_id=project_id,
            details={"files_deleted": len(files_to_delete)}
        )

        return ProjectDeleteResponse(status="success", project_id=project_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete project: {e}")
        raise HTTPException(status_code=500, detail=str(e))
