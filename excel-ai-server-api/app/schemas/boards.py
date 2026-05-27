from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class BoardInfo(BaseModel):
    board_id: str
    name: str
    created_on: Optional[str] = None
    active_file_uuid: Optional[str] = None
    is_shared: bool = False
    share_token: Optional[str] = None
    screen_share_tokens: Dict[str, str] = Field(default_factory=dict)
    file_count: int = 0


class BoardListResponse(BaseModel):
    boards: List[BoardInfo]


class BoardPublishRequest(BaseModel):
    widgets: Optional[List[Dict]] = None
    active_screen_id: Optional[str] = None


class BoardCreateRequest(BaseModel):
    name: str


class BoardFileInfo(BaseModel):
    file_uuid: str
    filename: str
    table_name: str
    total_rows: int = 0
    created_on: Optional[str] = None


class BoardScreenState(BaseModel):
    id: str
    name: str


class BoardDashboardSaveRequest(BaseModel):
    widgets: List[Dict[str, Any]] = Field(default_factory=list)
    screens: List[BoardScreenState] = Field(default_factory=list)
    active_screen_id: Optional[str] = None
    active_theme: Optional[str] = None
    thumbnail_version: Optional[int] = None
    screen_widgets: Dict[str, List[Dict[str, Any]]] = Field(default_factory=dict)
    file_screen_widgets: Dict[str, Dict[str, List[Dict[str, Any]]]] = Field(default_factory=dict)
    file_screen_needs_generation: Dict[str, Dict[str, bool]] = Field(default_factory=dict)
    file_screen_pending_templates: Dict[str, Dict[str, List[Dict[str, Any]]]] = Field(default_factory=dict)
    screen_thumbnails: Dict[str, str] = Field(default_factory=dict)
    file_screen_thumbnails: Dict[str, Dict[str, str]] = Field(default_factory=dict)
    design: Dict[str, Any] = Field(default_factory=dict)


class SharedDashboardFilterRequest(BaseModel):
    column: str | None = None
    value: str | None = None
    filters: dict | None = None
    session_id: str | None = None
