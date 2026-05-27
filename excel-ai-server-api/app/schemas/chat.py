from typing import Optional

from pydantic import BaseModel


class ChatMessageSave(BaseModel):
    role: str
    content: str
    query_type: Optional[str] = None
    cache_hit: bool = False
    response_time: Optional[float] = None
    metadata: Optional[dict] = None


class ChatMessageSoftDelete(BaseModel):
    message_id: int


class ChatMessageResponse(BaseModel):
    id: int
    file_uuid: str
    role: str
    content: str
    query_type: Optional[str] = None
    cache_hit: bool = False
    response_time: Optional[float] = None
    metadata: Optional[dict] = None
    created_at: str


class SessionCloseRequest(BaseModel):
    file_uuid: str
    session_id: str
    token: str
