# Database Schema Overview

This document provides a deep, comprehensive breakdown of the core PostgreSQL database schema that powers the application. It outlines all major tables, their purpose, their relationships, and the indexing strategies used.

## 1. High-Level Architecture
The database is structured to separate global physical file metadata from tenant-isolated analytical data. 
It utilizes **PostgreSQL** heavily, relying on custom extensions and separated schemas:
1. **`public` Schema:** Handles global application state (files, projects, boards, generic chat).
2. **`etl_system` Schema:** A dedicated logical grouping for ETL jobs, Semantic Catalogs, and Workspace analytics.
3. **Dynamic Workspaces (`ws_{id}`):** When a workspace is created, the system generates a dedicated, entirely isolated PostgreSQL schema to hold its physical data tables.
4. **`vector` Extension:** `pgvector` is enabled in the public schema to support the RAG-to-SQL architecture.

---

## 2. Global State & File Management (Public Schema)

### `file_groups`
Groups multi-sheet Excel uploads together.
- `group_id` (PK): Unique ID.
- `original_filename`: The raw name of the uploaded `.xlsx`.

### `file_registry`
The central registry bridging physical tables and logical UI representations.
- `file_uuid` (PK): Unique ID.
- `table_name`: The exact physical table name generated in PostgreSQL.
- `column_stats` (JSONB): Statistical profile calculated on upload.
- `file_group_id` (FK): Links to `file_groups` if extracted from a multi-sheet upload.
- `project_id`, `subproject_id`: Links to the organizational hierarchy.
- **Indexes:** `filename`, `table_name`, `created_by`, `project_id`.

---

## 3. Organizational Hierarchy & Dashboards

### `projects` & `subprojects`
Provides the folder-like directory structure.
- `projects.project_id` (PK)
- `projects.active_file_uuid`: Tracks what the user is currently viewing (SSE state).
- `subprojects.subproject_id` (PK), `subprojects.project_id` (FK).

### `dashboards`
Stores project-level dashboard layouts.
- `dashboard_id` (PK)
- `file_uuid` (FK -> `file_registry`)
- `widgets_json` (JSONB): The serialized grid layout and ECharts configurations.

### `insight_boards` & `board_files`
Presentation layers decoupled from standard projects.
- `insight_boards.board_id` (PK)
- `insight_boards.studio_state_json` (JSONB): Complex multi-screen PowerPoint-like state.
- `board_files.file_uuid` (PK): Files explicitly uploaded just for this board.

---

## 4. Chat & Memory (Public Schema)

### `chat_history`
Persists conversational AI interactions.
- `id` (PK, Serial)
- `user_id`, `file_uuid`: Links the chat to the user and the specific dataset.
- `metadata` (JSONB): Stores the generated SQL, JSON previews, and trace IDs.

### `saved_questions`
The bookmarking/prompt library system.
- `id` (PK, Serial)
- `question_text`: The exact natural language prompt.
- `question_category`: User-defined string for folder organization.
- `scope_level` & `scope_id`: Polymorphic relation (can be tied to a file, a project, or a workspace).

---

## 5. ETL Pipeline System (`etl_system` Schema)

### `etl_system.etl_connections`
Stores credentials for external databases (MySQL, PG, Mongo).
- `connection_id` (PK)
- `db_type`, `host`, `port`, `database_name`, `username`, `password`

### `etl_system.etl_jobs`
Tracks the execution of background data pipelines.
- `job_id` (PK)
- `connection_id` (FK)
- `transform_script` (TEXT): The user's sandboxed Python code.
- `sync_mode`: `overwrite` or `append`.
- `high_water_mark`: Tracks the delta for incremental syncs.
- `status`: `pending`, `extracting`, `loading`, `complete`.

### `etl_system.etl_tables`
Maps physical target tables back to the job that created them.
- `table_id` (PK)
- `job_id` (FK)
- `table_name`: The physical workspace table name.

---

## 6. Workspaces & Semantic Layer (`etl_system` Schema)

This is the most complex part of the database. It maps business logic to raw physical data.

### `etl_system.workspaces`
The root tenant record.
- `workspace_id` (PK)
- `schema_name`: e.g., `ws_123456`. All tables for this workspace live in this physical PG schema.

### `etl_system.tables_metadata` & `etl_system.columns_metadata`
Stores descriptions to override poor database naming conventions.
- `metadata_id` (PK)
- `table_name`, `column_name`
- `description`: English explanation fed to the LLM.
- `stats` (JSONB): Min, max, variance, nulls.

### `etl_system.semantic_metrics`
User-defined formulas.
- `metric_id` (PK)
- `formula` (TEXT): e.g., `SUM(revenue) - SUM(cost)`.

### `etl_system.semantic_dimensions` & `etl_system.semantic_synonyms`
Categorical mappings and terminology dictionaries.
- `dimension.column_name`: e.g., `region_id`.
- `synonym.keyword` -> `synonym.mapped_to`: "clients" -> "customers".

### `etl_system.workspace_relationships`
Allows the LLM to perform `JOIN` operations across tables without explicit Foreign Keys in the DB.
- `source_table`, `source_column` -> `target_table`, `target_column`.

### `etl_system.semantic_vectors`
The semantic cache.
- `vector_id` (PK)
- `content_text`: The previously asked question.
- `embedding` (vector(1024)): The pgvector representation used for cosine similarity searches.

---

## 7. Workspace Reporting (`etl_system` Schema)

### `workspace_dashboards` & `dashboard_widgets`
Relational dashboard setup (unlike the JSON blobs used in Projects).
- `dashboard_id` (PK)
- `widget_id` (PK, FK -> `workspace_dashboards`).
- `sql_query`, `config`: The exact code and ECharts JSON needed to render the widget.

### `shared_reports`
Snapshots for public read-only views.
- `report_id` (PK)
- `share_token` (UNIQUE): The cryptographic token.
- `sql_query`, `data`, `ai_summary`: The frozen state of the report at the time of sharing.
