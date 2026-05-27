"""
Pydantic schemas for ETL pipeline endpoints.

Covers: connection setup, table preview, dry-run, full execution, and job status.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator


# ── Connection ────────────────────────────────────────────────────────────

class ETLConnectRequest(BaseModel):
    """Request to connect to an external database."""
    connection_id: Optional[str] = Field(default=None, description="Provide an existing connection_id to auto-connect")
    db_type: Optional[str] = Field(default=None, description="Database type: mysql, postgresql, or mongodb")
    host: str = Field(default="localhost")
    port: int = Field(default=3306)
    username: str = Field(default="")
    password: str = Field(default="")
    database: str = Field(default="", description="Database name to connect to")
    # MongoDB-specific
    auth_source: str = Field(default="admin")
    # Optional display name for saving connection
    connection_name: Optional[str] = Field(default=None, description="Friendly name for this connection")

    @model_validator(mode="after")
    def validate_request(self) -> ETLConnectRequest:
        if not self.connection_id and not (self.db_type and self.database):
            raise ValueError("Must provide either a connection_id OR db_type, database, and credentials")
        return self


class TableInfo(BaseModel):
    """Information about a single table/collection."""
    name: str
    row_count: Optional[int] = None
    columns: Optional[List[Dict[str, Any]]] = None


class ETLConnectResponse(BaseModel):
    """Response from connection — includes connection ID and available tables."""
    connection_id: str
    db_type: str
    database: str
    tables: List[TableInfo]
    message: str = "Connected successfully"


# ── Preview ───────────────────────────────────────────────────────────────

class ETLPreviewRequest(BaseModel):
    """Request to preview rows from a specific table."""
    connection_id: str
    table_name: str
    limit: int = Field(default=50, le=200)


class ETLPreviewResponse(BaseModel):
    """Preview response with sample rows."""
    table_name: str
    rows: List[Dict[str, Any]]
    total_rows: int
    columns: List[str]

# ── Generate Script ──────────────────────────────────────────────────────────

class ETLGenerateTransformRequest(BaseModel):
    """Request to generate an ETL transform script via AI."""
    prompt: str
    tables: List[TableInfo]

class ETLGenerateTransformResponse(BaseModel):
    """Response containing the AI generated code."""
    script: str


class ETLDatasetInput(BaseModel):
    """Extract definition for one logical output dataset."""
    table_name: Optional[str] = None
    custom_query: Optional[str] = None
    output_name: Optional[str] = None
    sync_column: Optional[str] = None

    @model_validator(mode="after")
    def validate_source(self) -> "ETLDatasetInput":
        if not self.table_name and not self.custom_query:
            raise ValueError("Each dataset must include either table_name or custom_query")
        if self.custom_query and not self.output_name:
            raise ValueError("output_name is required when custom_query is provided")
        return self

# ── Dry Run ───────────────────────────────────────────────────────────────

class ETLDryRunRequest(BaseModel):
    """Request to test-run the pipeline on a small sample (100 rows)."""
    connection_id: str
    table_names: List[str] = Field(default_factory=list)
    datasets: List[ETLDatasetInput] = Field(default_factory=list)
    transform_script: str = Field(..., description="Python script content with transform() function")

    @model_validator(mode="after")
    def validate_extract_inputs(self) -> "ETLDryRunRequest":
        if not self.table_names and not self.datasets:
            raise ValueError("Provide at least one table_name or dataset")
        return self


class ETLDryRunResponse(BaseModel):
    """Dry-run response with preview of transformed output."""
    success: bool
    duration_seconds: float = 0.0
    output_tables: Optional[List[Dict[str, Any]]] = None
    error: Optional[str] = None
    stdout: Optional[str] = None


class ETLDeltaSyncRequest(BaseModel):
    sync_column: Optional[str] = None
    preview_only: bool = False
    primary_keys: Optional[List[str]] = None

# ── Full Execution ────────────────────────────────────────────────────────────

class ETLExecuteRequest(BaseModel):
    """Request to execute the full ETL pipeline."""
    job_id: Optional[str] = Field(default=None, description="If provided, updates and re-executes an existing pipeline job")
    connection_id: str
    table_names: List[str] = Field(default_factory=list)
    datasets: List[ETLDatasetInput] = Field(default_factory=list)
    transform_script: str = Field(..., description="Python script content with transform() function")
    
    # Phase 2 details
    target_table: Optional[str] = Field(default=None, description="Provide a clean specific table name, else it falls back to generation")
    pipeline_name: Optional[str] = Field(default=None, description="Friendly pipeline name shown in the UI")
    sync_mode: str = Field(default="overwrite", description="Can be 'overwrite' or 'append'")
    sync_column: Optional[str] = Field(default=None, description="The column to track high-water mark for incremental sync")
    primary_keys: Optional[List[str]] = Field(default=None, description="Primary keys to use for UPSERT during incremental sync")

    # Workspace targeting (required — ETL data lands in ws_{workspace_id} schema)
    workspace_id: str = Field(..., description="Target workspace ID for schema routing.")

    @model_validator(mode="after")
    def validate_extract_inputs(self) -> "ETLExecuteRequest":
        if not self.table_names and not self.datasets:
            raise ValueError("Provide at least one table_name or dataset")
        if self.sync_mode not in ["overwrite", "append"]:
            raise ValueError("Sync mode must be 'overwrite' or 'append'")
        return self


class ETLSyncUpdateRequest(BaseModel):
    """Append/update an existing loaded table using delta extract query/table."""
    connection_id: str
    workspace_id: str
    target_table_name: str
    table_names: List[str] = Field(default_factory=list)
    datasets: List[ETLDatasetInput] = Field(default_factory=list)
    transform_script: Optional[str] = None

    @model_validator(mode="after")
    def validate_extract_inputs(self) -> "ETLSyncUpdateRequest":
        if not self.table_names and not self.datasets:
            raise ValueError("Provide at least one table_name or dataset")
        return self


class ETLSyncUpdateResponse(BaseModel):
    success: bool
    loaded_tables: List[Dict[str, Any]] = Field(default_factory=list)
    preview_tables: List[Dict[str, Any]] = Field(default_factory=list)
    total_new_rows: int = 0
    requires_confirmation: bool = False
    message: str


class ETLJobResponse(BaseModel):
    """Response when an ETL job is submitted."""
    job_id: str
    status: str = "pending"
    message: str = "Job submitted successfully"


# ── Job Status ────────────────────────────────────────────────────────────

class ETLJobStatusResponse(BaseModel):
    """Full status of an ETL job."""
    job_id: str
    status: str  # pending | extracting | transforming | loading | complete | failed
    source_tables: Optional[List[Any]] = None
    output_tables: Optional[List[Dict[str, Any]]] = None
    error_message: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    created_at: Optional[str] = None
    target_table: Optional[str] = None
    sync_mode: Optional[str] = None
    high_water_mark: Optional[str] = None
    sync_column: Optional[str] = None
    sync_mode_type: Optional[str] = None
    pipeline_name: Optional[str] = None
    primary_keys: Optional[List[str]] = None


# ── Connections List ──────────────────────────────────────────────────────

class ETLConnectionInfo(BaseModel):
    """Summary of a saved ETL connection."""
    connection_id: str
    name: str
    db_type: str
    host: str
    port: int
    database_name: str
    created_at: Optional[str] = None
    last_used_at: Optional[str] = None


class ETLConnectionListResponse(BaseModel):
    """List of saved ETL connections for a user."""
    connections: List[ETLConnectionInfo]


# ── Datasets List ────────────────────────────────────────────────────────

class ETLDatasetTable(BaseModel):
    table_id: str
    table_name: str
    source_name: Optional[str] = None
    row_count: Optional[int] = None
    column_stats: Optional[Dict[str, Any]] = None
    created_at: Optional[str] = None

class ETLDatasetJob(BaseModel):
    job_id: str
    status: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    tables: List[ETLDatasetTable]

class ETLDatasetConnection(BaseModel):
    connection_id: str
    name: str
    db_type: str
    database_name: Optional[str] = None
    jobs: List[ETLDatasetJob]

class ETLDatasetListResponse(BaseModel):
    connections: List[ETLDatasetConnection]
