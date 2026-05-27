"""
Database Manager (Singleton) — extracted from hybrid_chat_system.py.

Manages PostgreSQL connection pool and schema initialization.
"""
from __future__ import annotations

import os
import logging
import threading
from contextlib import contextmanager

import psycopg2
import psycopg2.pool

from app.utils.logging import log_full_exception

logger = logging.getLogger("HybridSystem")


class DatabaseManager:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(DatabaseManager, cls).__new__(cls)
                cls._instance._initialize_pool()
        return cls._instance

    def _initialize_pool(self):
        try:
            self.config = {
                "host": os.getenv("PG_HOST", "localhost"),
                "port": os.getenv("PG_PORT", "5432"),
                "database": os.getenv("PG_DATABASE", "hybrid"),
                "user": os.getenv("PG_USER", "postgres"),
                "password": os.getenv("PG_PASSWORD", "postgres")
            }
            self.pool = psycopg2.pool.ThreadedConnectionPool(minconn=1, maxconn=20, **self.config)
            logger.info("✅ Database Connection Pool Initialized (Max: 20)")
            self._init_schema()
        except Exception as e:
            log_full_exception(e, "Failed to initialize Database Pool")
            raise

    def _init_schema(self):
        with self.get_connection() as conn:
          with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            cur.execute("CREATE SCHEMA IF NOT EXISTS etl_system;")
            # ── file_groups table (multi-sheet parent) ──
            cur.execute("""
                CREATE TABLE IF NOT EXISTS file_groups (
                    group_id   VARCHAR(255) PRIMARY KEY,
                    original_filename VARCHAR(512) NOT NULL,
                    created_by VARCHAR(255),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            conn.commit()

            cur.execute("""
                CREATE TABLE IF NOT EXISTS file_registry (
                    file_uuid VARCHAR(255) PRIMARY KEY,
                    filename VARCHAR(255),
                    table_name VARCHAR(255) NOT NULL,
                    column_stats JSONB,
                    created_on TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    created_by VARCHAR(255),
                    project_id VARCHAR(255),
                    subproject_id VARCHAR(255),
                    is_deleted BOOLEAN DEFAULT FALSE,
                    deleted_at TIMESTAMP,
                    file_group_id VARCHAR(255) REFERENCES file_groups(group_id) ON DELETE SET NULL,
                    sheet_name VARCHAR(255),
                    is_pinned BOOLEAN DEFAULT FALSE,
                    is_favorite BOOLEAN DEFAULT FALSE,
                    tags JSONB DEFAULT '[]'::jsonb
                );
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS projects (
                    project_id VARCHAR(255) PRIMARY KEY,
                    name VARCHAR(255) NOT NULL,
                    created_by VARCHAR(255),
                    created_on TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    template_widgets_json JSONB,
                    is_dashboard BOOLEAN DEFAULT FALSE,
                    active_file_uuid VARCHAR(255),
                    is_shared BOOLEAN DEFAULT FALSE,
                    share_token VARCHAR(255) UNIQUE,
                    color VARCHAR(30)
                );
            """)


            cur.execute("""
                CREATE TABLE IF NOT EXISTS subprojects (
                    subproject_id VARCHAR(255) PRIMARY KEY,
                    project_id VARCHAR(255) NOT NULL,
                    name VARCHAR(255) NOT NULL,
                    created_by VARCHAR(255),
                    created_on TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)


            # Dashboard persistence table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS dashboards (
                    dashboard_id VARCHAR(255) PRIMARY KEY,
                    file_uuid VARCHAR(255),
                    widgets_json JSONB NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    project_id VARCHAR(255),
                    FOREIGN KEY (file_uuid) REFERENCES file_registry(file_uuid) ON DELETE CASCADE
                );
            """)

            conn.commit()
            logger.info("✅ Dashboard table created/exists")

            cur.execute("""
                CREATE TABLE IF NOT EXISTS audit_log (
                    id SERIAL PRIMARY KEY,
                    user_id VARCHAR(255),
                    action VARCHAR(50) NOT NULL,
                    entity_type VARCHAR(50) NOT NULL,
                    entity_id VARCHAR(255),
                    details JSONB,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            # Create indexes for lookups
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_file_registry_filename 
                ON file_registry(filename);
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_file_registry_table_name 
                ON file_registry(table_name);
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_file_registry_created_by 
                ON file_registry(created_by);
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_file_registry_project_id
                ON file_registry(project_id);
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_file_registry_subproject_id
                ON file_registry(subproject_id);
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_projects_created_by
                ON projects(created_by);
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_subprojects_project_id
                ON subprojects(project_id);
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_audit_log_user_id 
                ON audit_log(user_id);
            """)

            # ── Insight Boards (standalone, decoupled from projects) ─────
            cur.execute("""
                CREATE TABLE IF NOT EXISTS insight_boards (
                    board_id VARCHAR(255) PRIMARY KEY,
                    name VARCHAR(255) NOT NULL,
                    created_by VARCHAR(255),
                    created_on TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    active_file_uuid VARCHAR(255),
                    widgets_json JSONB,
                    studio_state_json JSONB,
                    is_shared BOOLEAN DEFAULT FALSE,
                    share_token VARCHAR(255) UNIQUE,
                    template_columns JSONB,
                    published_file_uuid VARCHAR(255),
                    published_widgets_json JSONB
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS board_files (
                    file_uuid VARCHAR(255) PRIMARY KEY,
                    board_id VARCHAR(255) NOT NULL REFERENCES insight_boards(board_id) ON DELETE CASCADE,
                    filename VARCHAR(255),
                    table_name VARCHAR(255) NOT NULL,
                    column_stats JSONB,
                    created_on TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_insight_boards_created_by ON insight_boards(created_by);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_board_files_board_id ON board_files(board_id);")
            conn.commit()
            logger.info("✅ Insight Boards tables created/exist")

            # Chat history table for persistent conversations
            cur.execute("""
                CREATE TABLE IF NOT EXISTS chat_history (
                    id SERIAL PRIMARY KEY,
                    user_id VARCHAR(255) NOT NULL,
                    file_uuid VARCHAR(255) NOT NULL,
                    role VARCHAR(20) NOT NULL,
                    content TEXT NOT NULL,
                    query_type VARCHAR(50),
                    cache_hit BOOLEAN DEFAULT FALSE,
                    response_time FLOAT,
                    metadata JSONB,
                    is_deleted BOOLEAN DEFAULT FALSE,
                    deleted_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_chat_history_user_file 
                ON chat_history(user_id, file_uuid);
            """)

            # Saved questions table for Question Categories & Auto-Replay
            cur.execute("""
                CREATE TABLE IF NOT EXISTS saved_questions (
                    id SERIAL PRIMARY KEY,
                    question_text TEXT NOT NULL,
                    question_category VARCHAR(100) NOT NULL DEFAULT 'Generic',
                    scope_level VARCHAR(20) NOT NULL DEFAULT 'ROOT',
                    scope_id VARCHAR(255),
                    created_by VARCHAR(255),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_saved_questions_scope
                ON saved_questions(scope_level, scope_id);
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_saved_questions_created_by
                ON saved_questions(created_by);
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_saved_questions_category
                ON saved_questions(question_category);
            """)



            # ── pgvector Extension (for Semantic Catalog RAG) ────────────
            try:
                # Explicitly create in the public schema to avoid InvalidSchemaName
                cur.execute("CREATE EXTENSION IF NOT EXISTS vector SCHEMA public;")
                conn.commit()
                logger.info("✅ pgvector extension enabled")
            except Exception as pgv_err:
                conn.rollback()
                logger.warning(
                    "⚠️  pgvector extension not available — semantic vector search will be disabled. "
                    "Install pgvector to enable RAG-to-SQL. Error: %s", pgv_err
                )

            # ── ETL Pipeline Tables ──────────────────────────────────────
            # etl_connections: saved external DB connections
            cur.execute("""
                CREATE TABLE IF NOT EXISTS etl_system.etl_connections (
                    connection_id VARCHAR(255) PRIMARY KEY,
                    name VARCHAR(255) NOT NULL,
                    db_type VARCHAR(50) NOT NULL,
                    host VARCHAR(255),
                    port INTEGER,
                    database_name VARCHAR(255),
                    username VARCHAR(255),
                    created_by VARCHAR(255),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_used_at TIMESTAMP,
                    password VARCHAR(255),
                    workspace_id VARCHAR(255)
                );
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_etl_connections_created_by ON etl_system.etl_connections(created_by);")


            # etl_jobs: tracks ETL pipeline executions
            cur.execute("""
                CREATE TABLE IF NOT EXISTS etl_system.etl_jobs (
                    job_id VARCHAR(255) PRIMARY KEY,
                    connection_id VARCHAR(255) REFERENCES etl_system.etl_connections(connection_id) ON DELETE SET NULL,
                    status VARCHAR(50) DEFAULT 'pending',
                    source_tables JSONB,
                    transform_script TEXT,
                    output_tables JSONB,
                    error_message TEXT,
                    created_by VARCHAR(255),
                    started_at TIMESTAMP,
                    completed_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    target_table VARCHAR(255),
                    sync_mode VARCHAR(50) DEFAULT 'overwrite',
                    high_water_mark VARCHAR(255),
                    sync_column VARCHAR(255),
                    pipeline_name VARCHAR(255),
                    sync_mode_type VARCHAR(50),
                    primary_keys JSONB,
                    workspace_id VARCHAR(255)
                );
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_etl_jobs_created_by ON etl_system.etl_jobs(created_by);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_etl_jobs_connection_id ON etl_system.etl_jobs(connection_id);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_etl_jobs_status ON etl_system.etl_jobs(status);")


            # etl_tables: maps ETL output tables to jobs
            cur.execute("""
                CREATE TABLE IF NOT EXISTS etl_system.etl_tables (
                    table_id VARCHAR(255) PRIMARY KEY,
                    job_id VARCHAR(255) REFERENCES etl_system.etl_jobs(job_id) ON DELETE CASCADE,
                    table_name VARCHAR(255) NOT NULL,
                    source_name VARCHAR(255),
                    row_count INTEGER,
                    column_stats JSONB,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_etl_tables_job_id ON etl_system.etl_tables(job_id);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_etl_tables_table_name ON etl_system.etl_tables(table_name);")
            conn.commit()
            logger.info("✅ ETL tables created/exist")

            # ── Workspace Management ─────────────────────────────────────
            # workspaces: each workspace = one PostgreSQL schema (ws_{id})
            cur.execute("""
                CREATE TABLE IF NOT EXISTS etl_system.workspaces (
                    workspace_id VARCHAR(255) PRIMARY KEY,
                    name VARCHAR(255) NOT NULL,
                    schema_name VARCHAR(255) UNIQUE NOT NULL,
                    description TEXT,
                    created_by VARCHAR(255),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_shared BOOLEAN DEFAULT FALSE,
                    share_token VARCHAR(255) UNIQUE
                );
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_workspaces_created_by ON etl_system.workspaces(created_by);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_workspaces_schema_name ON etl_system.workspaces(schema_name);")



            conn.commit()
            logger.info("✅ Workspace management tables created/exist")

            # ── Semantic Catalog (Metadata + Business Logic) ──────────────
            # tables_metadata: stores business descriptions for loaded tables
            cur.execute("""
                CREATE TABLE IF NOT EXISTS etl_system.tables_metadata (
                    metadata_id VARCHAR(255) PRIMARY KEY,
                    workspace_id VARCHAR(255) NOT NULL,
                    table_name VARCHAR(255) NOT NULL,
                    schema_name VARCHAR(255),
                    description TEXT,
                    schema_info TEXT,
                    row_count INTEGER,
                    auto_profile JSONB,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_tables_metadata_workspace ON etl_system.tables_metadata(workspace_id);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_tables_metadata_table ON etl_system.tables_metadata(table_name);")

            # columns_metadata: stores column-level descriptions and types
            cur.execute("""
                CREATE TABLE IF NOT EXISTS etl_system.columns_metadata (
                    column_id VARCHAR(255) PRIMARY KEY,
                    metadata_id VARCHAR(255) REFERENCES etl_system.tables_metadata(metadata_id) ON DELETE CASCADE,
                    workspace_id VARCHAR(255) NOT NULL,
                    table_name VARCHAR(255) NOT NULL,
                    column_name VARCHAR(255) NOT NULL,
                    data_type VARCHAR(100),
                    description TEXT,
                    sample_values JSONB,
                    stats JSONB,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_columns_metadata_workspace ON etl_system.columns_metadata(workspace_id);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_columns_metadata_table ON etl_system.columns_metadata(table_name);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_columns_metadata_parent ON etl_system.columns_metadata(metadata_id);")

            # semantic_metrics: user-defined formulas (e.g., Net Revenue = Gross - Tax)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS etl_system.semantic_metrics (
                    metric_id VARCHAR(255) PRIMARY KEY,
                    workspace_id VARCHAR(255) NOT NULL,
                    name VARCHAR(255) NOT NULL,
                    formula TEXT NOT NULL,
                    description TEXT,
                    related_tables TEXT[],
                    created_by VARCHAR(255),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_semantic_metrics_workspace ON etl_system.semantic_metrics(workspace_id);")

            # semantic_dimensions: defines analytical dimensions (e.g., date = orders.created_at)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS etl_system.semantic_dimensions (
                    dimension_id VARCHAR(255) PRIMARY KEY,
                    workspace_id VARCHAR(255) NOT NULL,
                    name VARCHAR(255) NOT NULL,
                    table_name VARCHAR(255) NOT NULL,
                    column_name VARCHAR(255) NOT NULL,
                    description TEXT,
                    dim_type VARCHAR(50) DEFAULT 'categorical',
                    created_by VARCHAR(255),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_semantic_dimensions_workspace ON etl_system.semantic_dimensions(workspace_id);")

            # semantic_synonyms: maps business terms to technical names (e.g., sales → revenue)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS etl_system.semantic_synonyms (
                    synonym_id VARCHAR(255) PRIMARY KEY,
                    workspace_id VARCHAR(255) NOT NULL,
                    keyword VARCHAR(255) NOT NULL,
                    mapped_to VARCHAR(255) NOT NULL,
                    mapped_type VARCHAR(50) DEFAULT 'column',
                    created_by VARCHAR(255),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_semantic_synonyms_workspace ON etl_system.semantic_synonyms(workspace_id);")

            # semantic_vectors: pgvector embeddings for RAG-to-SQL retrieval
            cur.execute("""
                CREATE TABLE IF NOT EXISTS etl_system.semantic_vectors (
                    vector_id VARCHAR(255) PRIMARY KEY,
                    workspace_id VARCHAR(255) NOT NULL,
                    content_type VARCHAR(50) NOT NULL,
                    source_id VARCHAR(255),
                    content_text TEXT NOT NULL,
                    embedding vector(1024),
                    metadata JSONB,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_semantic_vectors_workspace ON etl_system.semantic_vectors(workspace_id);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_semantic_vectors_type ON etl_system.semantic_vectors(content_type);")

            conn.commit()
            logger.info("✅ Semantic catalog tables created/exist")

            # ── Workspace Relationships (PK/FK between tables) ───────────
            cur.execute("""
                CREATE TABLE IF NOT EXISTS etl_system.workspace_relationships (
                    relationship_id VARCHAR(255) PRIMARY KEY,
                    workspace_id VARCHAR(255) NOT NULL,
                    source_table VARCHAR(255) NOT NULL,
                    source_column VARCHAR(255) NOT NULL,
                    target_table VARCHAR(255) NOT NULL,
                    target_column VARCHAR(255) NOT NULL,
                    relationship_type VARCHAR(50) DEFAULT 'foreign_key',
                    inferred_by VARCHAR(50) DEFAULT 'user',
                    created_by VARCHAR(255),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_ws_relationships_workspace ON etl_system.workspace_relationships(workspace_id);")
            conn.commit()
            logger.info("✅ Workspace relationships table created/exist")

            # ── Workspace Dashboards (Chat-to-Widget) ────────────────────
            # workspace_dashboards: dashboard layout per workspace
            cur.execute("""
                CREATE TABLE IF NOT EXISTS etl_system.workspace_dashboards (
                    dashboard_id VARCHAR(255) PRIMARY KEY,
                    workspace_id VARCHAR(255) NOT NULL,
                    name VARCHAR(255) NOT NULL DEFAULT 'Default Dashboard',
                    layout_json JSONB,
                    created_by VARCHAR(255),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_ws_dashboards_workspace ON etl_system.workspace_dashboards(workspace_id);")

            # dashboard_widgets: individual pinned widgets (Chat-to-Widget)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS etl_system.dashboard_widgets (
                    widget_id VARCHAR(255) PRIMARY KEY,
                    dashboard_id VARCHAR(255) REFERENCES etl_system.workspace_dashboards(dashboard_id) ON DELETE CASCADE,
                    workspace_id VARCHAR(255) NOT NULL,
                    title VARCHAR(255),
                    widget_type VARCHAR(50) NOT NULL,
                    chart_type VARCHAR(50),
                    sql_query TEXT,
                    config JSONB,
                    origin_question TEXT,
                    pinned_by VARCHAR(255),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_ws_widgets_dashboard ON etl_system.dashboard_widgets(dashboard_id);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_ws_widgets_workspace ON etl_system.dashboard_widgets(workspace_id);")

            # workspace_chat_messages: persistent chat history per workspace
            cur.execute("""
                CREATE TABLE IF NOT EXISTS etl_system.workspace_chat_messages (
                    id SERIAL PRIMARY KEY,
                    workspace_id VARCHAR(255) NOT NULL,
                    user_id VARCHAR(255),
                    role VARCHAR(20) NOT NULL,
                    content TEXT,
                    sql_query TEXT,
                    columns JSONB,
                    data JSONB,
                    row_count INTEGER,
                    ai_summary TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_ws_chat_workspace ON etl_system.workspace_chat_messages(workspace_id);")


            conn.commit()
            logger.info("✅ Workspace dashboard + chat tables created/exist")

            # ── Shared Reports (snapshot sharing) ────────────────────────
            cur.execute("""
                CREATE TABLE IF NOT EXISTS etl_system.shared_reports (
                    report_id VARCHAR(255) PRIMARY KEY,
                    workspace_id VARCHAR(255) NOT NULL,
                    share_token VARCHAR(255) UNIQUE NOT NULL,
                    title VARCHAR(500),
                    question TEXT,
                    sql_query TEXT,
                    columns JSONB,
                    data JSONB,
                    row_count INTEGER DEFAULT 0,
                    ai_summary TEXT,
                    created_by VARCHAR(255),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_shared_reports_token ON etl_system.shared_reports(share_token);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_shared_reports_workspace ON etl_system.shared_reports(workspace_id);")
            conn.commit()
            logger.info("✅ Shared reports table created/exists")

            conn.commit()
            logger.info("✅ Database schema initialized successfully")

    @contextmanager
    def get_connection(self):
        conn = self.pool.getconn()
        try:
            yield conn
        finally:
            self.pool.putconn(conn)
