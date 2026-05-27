from typing import List, Optional

from pydantic import BaseModel


class SubprojectInfo(BaseModel):
    subproject_id: str
    project_id: str
    name: str
    created_on: Optional[str] = None
    file_count: int = 0


class ProjectInfo(BaseModel):
    project_id: str
    name: str
    created_on: Optional[str] = None
    subprojects: List[SubprojectInfo] = []
    file_count: int = 0
    color: Optional[str] = None
    is_dashboard: bool = False
    active_file_uuid: Optional[str] = None
    is_shared: bool = False
    share_token: Optional[str] = None


class ProjectListResponse(BaseModel):
    projects: List[ProjectInfo]


class ProjectCreateRequest(BaseModel):
    name: str
    color: Optional[str] = None
    is_dashboard: bool = False
    source_file_uuid: Optional[str] = None


class ProjectUpdateRequest(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None


class ActiveFileRequest(BaseModel):
    file_uuid: str
    session_id: Optional[str] = None


class ShareProjectResponse(BaseModel):
    status: str
    is_shared: bool
    share_token: Optional[str] = None


class SubprojectCreateRequest(BaseModel):
    name: str


class SubprojectUpdateRequest(BaseModel):
    name: Optional[str] = None


class ProjectDeleteResponse(BaseModel):
    status: str
    project_id: str


class SubprojectDeleteResponse(BaseModel):
    status: str
    subproject_id: str
