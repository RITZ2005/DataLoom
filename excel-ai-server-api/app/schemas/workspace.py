"""
Pydantic schemas for Workspace and Semantic Layer endpoints.

Covers: workspace CRUD, semantic metrics/dimensions/synonyms, and table metadata.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ── Workspace ─────────────────────────────────────────────────────────────

class WorkspaceCreateRequest(BaseModel):
    """Create a new workspace (= a new PostgreSQL schema)."""
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None


class WorkspaceUpdateRequest(BaseModel):
    """Request schema for updating workspace details."""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None


class WorkspaceResponse(BaseModel):
    """Response for a single workspace."""
    workspace_id: str
    name: str
    schema_name: str
    description: Optional[str] = None
    created_by: Optional[str] = None
    created_at: Optional[str] = None
    table_count: int = 0


class WorkspaceListResponse(BaseModel):
    """List of workspaces for a user."""
    workspaces: List[WorkspaceResponse]


class WorkspaceDetailResponse(WorkspaceResponse):
    """Workspace detail with tables and metadata."""
    tables: List[TableMetadataResponse] = Field(default_factory=list)


# ── Table Metadata ────────────────────────────────────────────────────────

class TableMetadataResponse(BaseModel):
    """Metadata about a single table inside a workspace."""
    metadata_id: str
    table_name: str
    schema_name: Optional[str] = None
    description: Optional[str] = None
    row_count: Optional[int] = None
    columns: List[ColumnMetadataResponse] = Field(default_factory=list)


class ColumnMetadataResponse(BaseModel):
    """Metadata about a single column."""
    column_id: str
    column_name: str
    data_type: Optional[str] = None
    description: Optional[str] = None
    sample_values: Optional[List[str]] = None
    stats: Optional[Dict[str, Any]] = None


class UpdateTableDescriptionRequest(BaseModel):
    """Update a table's business description."""
    description: str


class UpdateColumnDescriptionRequest(BaseModel):
    """Update a column's business description."""
    description: str


# ── Semantic Layer ────────────────────────────────────────────────────────

class SemanticMetricRequest(BaseModel):
    """Create or update a semantic metric (e.g., Net Revenue = Gross - Tax)."""
    name: str = Field(..., min_length=1, max_length=255)
    formula: str = Field(..., min_length=1)
    description: Optional[str] = None
    related_tables: Optional[List[str]] = None


class SemanticMetricResponse(BaseModel):
    metric_id: str
    workspace_id: str
    name: str
    formula: str
    description: Optional[str] = None
    related_tables: Optional[List[str]] = None
    created_at: Optional[str] = None


class SemanticDimensionRequest(BaseModel):
    """Create or update a semantic dimension."""
    name: str = Field(..., min_length=1, max_length=255)
    table_name: str
    column_name: str
    description: Optional[str] = None
    dim_type: str = Field(default="categorical")


class SemanticDimensionResponse(BaseModel):
    dimension_id: str
    workspace_id: str
    name: str
    table_name: str
    column_name: str
    description: Optional[str] = None
    dim_type: str = "categorical"
    created_at: Optional[str] = None


class SemanticSynonymRequest(BaseModel):
    """Create a synonym mapping (e.g., sales → revenue)."""
    keyword: str = Field(..., min_length=1, max_length=255)
    mapped_to: str = Field(..., min_length=1, max_length=255)
    mapped_type: str = Field(default="column", description="Type: column, metric, or table")


class SemanticSynonymResponse(BaseModel):
    synonym_id: str
    workspace_id: str
    keyword: str
    mapped_to: str
    mapped_type: str = "column"
    created_at: Optional[str] = None


class SemanticLayerResponse(BaseModel):
    """Full semantic layer for a workspace."""
    workspace_id: str
    metrics: List[SemanticMetricResponse] = Field(default_factory=list)
    dimensions: List[SemanticDimensionResponse] = Field(default_factory=list)
    synonyms: List[SemanticSynonymResponse] = Field(default_factory=list)


# Fix forward reference for WorkspaceDetailResponse
WorkspaceDetailResponse.model_rebuild()
