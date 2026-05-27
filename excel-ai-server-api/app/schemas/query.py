from typing import List, Optional

from pydantic import BaseModel


class QueryRequest(BaseModel):
    file_uuid: Optional[str] = None
    filename: Optional[str] = None
    query: str
    use_cache: Optional[bool] = True
    session_id: Optional[str] = None
    source_type: Optional[str] = None


class QueryResponse(BaseModel):
    status: str
    data: str
    query_type: str
    cache_hit: bool = False
    trace_id: Optional[str] = None
    trace_url: Optional[str] = None
    session_id: Optional[str] = None
    session_url: Optional[str] = None


class BatchQueryRequest(BaseModel):
    file_uuid: str
    questions: List[str]
    session_id: Optional[str] = None


class BatchQueryResultItem(BaseModel):
    question: str
    status: str
    data: Optional[str] = None
    query_type: Optional[str] = None
    error: Optional[str] = None
    trace_id: Optional[str] = None
    trace_url: Optional[str] = None


class BatchQueryResponse(BaseModel):
    status: str
    file_uuid: str
    results: List[BatchQueryResultItem]
    total: int
    successful: int
    failed: int
