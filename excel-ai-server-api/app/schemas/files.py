from typing import List, Optional

from pydantic import BaseModel


class FileInfo(BaseModel):
    file_uuid: str
    filename: str
    table_name: str
    total_rows: int
    columns: List[str]
    column_stats: dict
    created_on: Optional[str] = None
    deleted_at: Optional[str] = None
    is_deleted: bool = False
    project_id: Optional[str] = None
    subproject_id: Optional[str] = None
    is_pinned: bool = False
    is_favorite: bool = False
    tags: List[str] = []
    file_group_id: Optional[str] = None
    sheet_name: Optional[str] = None


class UploadRawResponse(BaseModel):
    temp_id: str
    filename: str
    sheets: List[str]


class ExtractSheetRequest(BaseModel):
    temp_id: str
    sheet_name: str
    existing_group_id: Optional[str] = None
    project_id: Optional[str] = None
    subproject_id: Optional[str] = None


class FileListResponse(BaseModel):
    files: List[FileInfo]


class FileMoveRequest(BaseModel):
    target_folder_id: Optional[str] = None
    target_subfolder_id: Optional[str] = None


class FileMetadataUpdateRequest(BaseModel):
    is_pinned: Optional[bool] = None
    is_favorite: Optional[bool] = None
    tags: Optional[List[str]] = None


class BulkFileIdsRequest(BaseModel):
    file_ids: List[str]


class BulkMoveRequest(BaseModel):
    file_ids: List[str]
    target_folder_id: Optional[str] = None
    target_subfolder_id: Optional[str] = None
