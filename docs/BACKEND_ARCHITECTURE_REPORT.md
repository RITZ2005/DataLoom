# Backend Architecture Report — `excel-ai-server-api`

## Tech Stack & Libraries

| Area | Stack / Libraries |
|---|---|
| Runtime | Python, FastAPI, Uvicorn |
| HTTP / API | FastAPI routers, Pydantic request/response models, `python-multipart` (file uploads), `httpx`, `requests` |
| Data Processing | `pandas`, `openpyxl`, `pyarrow`, `tabulate` |
| Databases | PostgreSQL (`psycopg2-binary`, `sqlalchemy`), MySQL (`pymysql`), MongoDB (`pymongo`) |
| AI / LLM | `langchain`, `langchain-core`, `langchain-openai`, `langchain-ollama`, `langchain-community`, `langchain-experimental` |
| Embeddings / Vector | Custom `OpenWebUIEmbeddings`, pgvector (`CREATE EXTENSION vector`) |
| Auth / Security | JWT (`PyJWT`), password hashing (`bcrypt`, `passlib`), `cryptography` |
| Cache / Session | Redis (`redis`), RediSearch-based semantic cache |
| Config | `.env` via `python-dotenv` |
| Observability | Langfuse decorators/client (`observe`, trace/session metadata), startup auth check + flush on shutdown |
| Logging | Central `HybridSystem` logger, ANSI console logs, rotating file logs (`production_system.log`) |

## Project Structure

```text
excel-ai-server-api/
├── .env
├── .gitignore
├── QUICK_START_GUIDE.md
├── README.md
├── SETUP_INSTRUCTIONS.md
├── database.db
├── docker-compose-langfuse.yml
├── main.py
├── requirements.txt
├── setup_pg_role.py
├── start-langfuse.bat
├── users.json
├── exports/
├── venv/
└── app/
    ├── __init__.py
    ├── config.py
    ├── dependencies.py
    ├── core/
    │   ├── __init__.py
    │   ├── agent.py
    │   ├── auth.py
    │   ├── cache.py
    │   ├── callbacks.py
    │   ├── database.py
    │   ├── embeddings.py
    │   ├── file_ops.py
    │   ├── formatters.py
    │   ├── ingestion.py
    │   ├── llm.py
    │   ├── routing.py
    │   ├── schema_utils.py
    │   ├── agents/
    │   │   ├── __init__.py
    │   │   ├── profiler.py
    │   │   ├── workspace_sql.py
    │   ├── dashboard/
    │   │   ├── __init__.py
    │   │   ├── kpi_builder.py
    │   │   └── workspace_builder.py
    │   ├── etl/
    │   │   ├── __init__.py
    │   │   ├── loader.py
    │   │   ├── connectors/
    │   │   │   ├── __init__.py
    │   │   │   ├── base_connector.py
    │   │   │   ├── factory.py
    │   │   │   ├── mongo_connector.py
    │   │   │   └── sql_connector.py
    │   │   └── sandbox/
    │   │       ├── __init__.py
    │   │       ├── executor.py
    │   │       └── sandbox_runner.py
    │   └── paths/
    │       ├── __init__.py
    │       ├── analytical.py
    │       ├── metadata.py
    │       ├── plot.py
    │       ├── semantic.py
    │       └── sql_agent.py
    ├── routers/
    │   ├── __init__.py
    │   ├── admin.py
    │   ├── auth.py
    │   ├── boards.py
    │   ├── categories.py
    │   ├── chat.py
    │   ├── dashboard.py
    │   ├── etl.py
    │   ├── export.py
    │   ├── files.py
    │   ├── health.py
    │   ├── langfuse_share.py
    │   ├── preview.py
    │   ├── projects.py
    │   ├── query.py
    │   └── workspace.py
    ├── schemas/
    │   ├── __init__.py
    │   ├── auth.py
    │   ├── boards.py
    │   ├── categories.py
    │   ├── chat.py
    │   ├── dashboard.py
    │   ├── etl.py
    │   ├── files.py
    │   ├── projects.py
    │   ├── query.py
    │   └── workspace.py
    ├── services/
    │   ├── __init__.py
    │   ├── langfuse_sso.py
    │   └── progress_manager.py
    └── utils/
        ├── __init__.py
        ├── audit.py
        └── logging.py
```

## Complete API Reference (Hierarchical)

> **Directory Structure:** `app/routers/` -> `filename.py` -> `Endpoints`


### Folder: `app/routers/`

#### File: `auth.py`
**Description:** Handles user registration, login, profile management, and authentication flows.

##### 1. `POST /api/auth/register`
- **What it does:** Register user
- **Expected Payload:** `RegisterRequest` `{email, username, password, name?, role?}`
- **Response:** `AuthResponse` `{status, token, email, name, role, message, langfuse_enabled}`

##### 2. `POST /api/auth/login`
- **What it does:** Login user
- **Expected Payload:** `LoginRequest` `{email?, loginId?, companyId?, password}`
- **Response:** `AuthResponse`

##### 3. `GET /api/auth/me`
- **What it does:** Current user profile
- **Expected Payload:** Bearer auth
- **Response:** `UserInfo` `{email, name, role, permissions[], langfuse_enabled}`

##### 4. `POST /api/auth/logout`
- **What it does:** Logout
- **Expected Payload:** Bearer auth
- **Response:** JSON `{status, ...}`

##### 5. `POST /api/auth/change-password`
- **What it does:** Change password
- **Expected Payload:** `ChangePasswordRequest` `{current_password, new_password}`
- **Response:** JSON `{status, message}`

#### File: `admin.py`
**Description:** Administrative endpoints for user management and system administration.

##### 1. `GET /api/admin/users`
- **What it does:** List users (admin)
- **Expected Payload:** Bearer admin auth
- **Response:** `AdminUserResponse[]`

##### 2. `POST /api/admin/users`
- **What it does:** Create user (admin)
- **Expected Payload:** `AdminCreateUserRequest` `{email, username, password, name?, role?}`
- **Response:** `AdminUserResponse`

##### 3. `PATCH /api/admin/users/{email}`
- **What it does:** Update user (admin)
- **Expected Payload:** Path `email`; `AdminUpdateUserRequest`
- **Response:** `AdminUserResponse`

#### File: `files.py`
**Description:** Manages file uploads, metadata updates, folder organization, and the recycle bin.

##### 1. `GET /api/files/upload-progress/{file_uuid}`
- **What it does:** Upload progress stream
- **Expected Payload:** Path `file_uuid`
- **Response:** `StreamingResponse` (SSE progress events)

##### 2. `POST /api/files/upload`
- **What it does:** Upload file
- **Expected Payload:** `multipart/form-data`: `file`, `project_id?`, `subproject_id?`, `file_uuid?`
- **Response:** JSON `{status, file_uuid, filename, table_name, ...}`

##### 3. `POST /api/files/upload-raw`
- **What it does:** Upload raw multi-sheet file
- **Expected Payload:** `multipart/form-data`: `file`
- **Response:** `UploadRawResponse` `{temp_id, filename, sheets[]}`

##### 4. `POST /api/files/extract-sheet`
- **What it does:** Extract and ingest selected sheet
- **Expected Payload:** `ExtractSheetRequest` `{temp_id, sheet_name, existing_group_id?, project_id?, subproject_id?}`
- **Response:** JSON `{status, file_uuid?, file_group_id?, ...}`

##### 5. `GET /api/files/groups`
- **What it does:** List file groups
- **Expected Payload:** Bearer auth
- **Response:** JSON `{groups:[...]}`

##### 6. `GET /api/files`
- **What it does:** List files
- **Expected Payload:** Bearer auth; filters via query params
- **Response:** `FileListResponse` `{files:[FileInfo...]}`

##### 7. `GET /api/files/trash`
- **What it does:** List deleted files
- **Expected Payload:** Bearer auth
- **Response:** `FileListResponse`

##### 8. `PATCH /api/files/{file_uuid}/move`
- **What it does:** Move file to folder/subfolder
- **Expected Payload:** Path `file_uuid`; `FileMoveRequest` `{target_folder_id?, target_subfolder_id?}`
- **Response:** JSON `{status, ...}`

##### 9. `PATCH /api/files/{file_uuid}/metadata`
- **What it does:** Update file metadata
- **Expected Payload:** Path `file_uuid`; `FileMetadataUpdateRequest` `{is_pinned?, is_favorite?, tags?}`
- **Response:** JSON `{status, ...}`

##### 10. `POST /api/files/bulk-move`
- **What it does:** Move files in bulk
- **Expected Payload:** `BulkMoveRequest` `{file_ids[], target_folder_id?, target_subfolder_id?}`
- **Response:** JSON `{status, moved_count?}`

##### 11. `GET /api/files/{file_identifier}`
- **What it does:** File details by id/name
- **Expected Payload:** Path `file_identifier`
- **Response:** JSON with file metadata/profile

##### 12. `GET /api/files/{file_identifier}/chunks`
- **What it does:** Fetch cached/embedded chunks
- **Expected Payload:** Path `file_identifier`
- **Response:** JSON `{chunks:[...], ...}`

##### 13. `DELETE /api/files/{file_identifier}`
- **What it does:** Soft-delete file
- **Expected Payload:** Path `file_identifier`
- **Response:** JSON `{status, ...}`

##### 14. `POST /api/files/{file_identifier}/restore`
- **What it does:** Restore soft-deleted file
- **Expected Payload:** Path `file_identifier`
- **Response:** JSON `{status, ...}`

##### 15. `DELETE /api/files/{file_identifier}/permanent`
- **What it does:** Hard-delete file
- **Expected Payload:** Path `file_identifier`
- **Response:** JSON `{status, ...}`

##### 16. `DELETE /api/files/trash/empty`
- **What it does:** Empty trash
- **Expected Payload:** Bearer auth
- **Response:** JSON `{status, deleted_count?}`

##### 17. `DELETE /api/files/{file_identifier}/cache`
- **What it does:** Clear semantic cache for file
- **Expected Payload:** Path `file_identifier`
- **Response:** JSON `{status, removed_cache_keys?}`

#### File: `preview.py`
**Description:** Endpoints for data previewing and statistical profiling.

##### 1. `GET /api/preview/{file_identifier}`
- **What it does:** Preview rows
- **Expected Payload:** Path `file_identifier`; query `rows?`
- **Response:** JSON `{status, data:[...], columns:[...], ...}`

##### 2. `GET /api/statistics/{file_identifier}`
- **What it does:** Dataset statistics/profile
- **Expected Payload:** Path `file_identifier`
- **Response:** JSON `{status, stats:{...}}`

#### File: `query.py`
**Description:** Provides the primary natural language to data pipeline interface, routing queries across metadata, plot, and SQL agents.

##### 1. `POST /api/query`
- **What it does:** Single query execution
- **Expected Payload:** `QueryRequest` `{file_uuid?, filename?, query, use_cache?, session_id?, source_type?}`
- **Response:** `QueryResponse` `{status, data, query_type, cache_hit, trace_id?, trace_url?, session_id?, session_url?}`

##### 2. `POST /api/query/batch`
- **What it does:** Batch query execution
- **Expected Payload:** `BatchQueryRequest` `{file_uuid, questions[], session_id?}`
- **Response:** `BatchQueryResponse`

#### File: `dashboard.py`
**Description:** Comprehensive endpoints for AI-powered KPI dashboard generation, widget cloning, and custom chart building.

##### 1. `POST /api/dashboard/{file_identifier}/generate`
- **What it does:** Generate dashboard from requirements
- **Expected Payload:** Path `file_identifier`; `DashboardGenerateRequest`
- **Response:** JSON `{status, widgets:[...], ...}`

##### 2. `GET /api/dashboard/{file_identifier}`
- **What it does:** Get/generate dashboard
- **Expected Payload:** Path `file_identifier`; query `regenerate?`, `session_id?`, `source_type?`, `mode?`
- **Response:** JSON dashboard payload

##### 3. `POST /api/dashboard/{file_identifier}/widget`
- **What it does:** Generate one widget
- **Expected Payload:** Path `file_identifier`; `DashboardWidgetRequest`
- **Response:** JSON `{status, widget:{...}}`

##### 4. `POST /api/dashboard/clone-widgets`
- **What it does:** Clone widgets between files
- **Expected Payload:** `CloneWidgetsRequest` `{base_file_id, target_file_id, session_id?}`
- **Response:** JSON `{status, cloned_widgets?}`

##### 5. `POST /api/dashboard/compare-unified`
- **What it does:** Unified comparison dashboard
- **Expected Payload:** `UnifiedCompareRequest`
- **Response:** JSON compare payload

##### 6. `POST /api/dashboard/{file_identifier}/filter`
- **What it does:** Filter dashboard output
- **Expected Payload:** Path `file_identifier`; `DashboardFilterRequest`
- **Response:** JSON filtered payload

##### 7. `POST /api/dashboard/{file_identifier}/update-widgets`
- **What it does:** Update widget configs
- **Expected Payload:** Path `file_identifier`; body `dict`
- **Response:** JSON `{status, ...}`

##### 8. `GET /api/dashboard/{file_identifier}/schema`
- **What it does:** Dashboard schema metadata
- **Expected Payload:** Path `file_identifier`; query `source_type?`, `mode?`
- **Response:** JSON schema payload

##### 9. `POST /api/dashboard/{file_identifier}/clone-template-widgets`
- **What it does:** Clone template widget set
- **Expected Payload:** Path `file_identifier`; `TemplateCloneRequest`
- **Response:** JSON `{status, widgets:[...]}`

##### 10. `POST /api/dashboard/{file_identifier}/chart-builder`
- **What it does:** Chart builder API
- **Expected Payload:** Path `file_identifier`; `ChartBuilderRequest` `{chart_type, dimension, measure?, aggregation?, source_type?, mode?}`
- **Response:** JSON chart config/data

#### File: `projects.py`
**Description:** Manages projects, subprojects, and layout persistence for specific datasets.

##### 1. `GET /api/projects`
- **What it does:** List projects
- **Expected Payload:** Bearer auth
- **Response:** `ProjectListResponse`

##### 2. `POST /api/projects`
- **What it does:** Create project
- **Expected Payload:** `ProjectCreateRequest` `{name, color?, is_dashboard?, source_file_uuid?}`
- **Response:** `ProjectInfo`

##### 3. `POST /api/projects/{project_id}/subprojects`
- **What it does:** Create subproject
- **Expected Payload:** Path `project_id`; `SubprojectCreateRequest` `{name}`
- **Response:** `SubprojectInfo`

##### 4. `POST /api/projects/{project_id}/dashboard/save`
- **What it does:** Save project dashboard layout
- **Expected Payload:** Path `project_id`; body `dict`
- **Response:** JSON `{status, ...}`

##### 5. `PUT /api/projects/{project_id}/active-file`
- **What it does:** Set project active file
- **Expected Payload:** Path `project_id`; `ActiveFileRequest` `{file_uuid, session_id?}`
- **Response:** JSON `{status, ...}`

##### 6. `GET /api/projects/{project_id}/dashboard`
- **What it does:** Get project dashboard
- **Expected Payload:** Path `project_id`
- **Response:** JSON dashboard payload

##### 7. `PUT /api/projects/{project_id}/active-file-stream`
- **What it does:** Stream active-file update
- **Expected Payload:** Path `project_id`; `ActiveFileRequest`
- **Response:** `StreamingResponse` (NDJSON)

##### 8. `DELETE /api/projects/{project_id}/subprojects/{subproject_id}`
- **What it does:** Delete subproject
- **Expected Payload:** Path params
- **Response:** `SubprojectDeleteResponse`

##### 9. `PUT /api/projects/{project_id}`
- **What it does:** Update project
- **Expected Payload:** Path `project_id`; `ProjectUpdateRequest` `{name?, color?}`
- **Response:** `ProjectInfo`/JSON

##### 10. `PUT /api/projects/{project_id}/subprojects/{subproject_id}`
- **What it does:** Update subproject
- **Expected Payload:** Path params; `SubprojectUpdateRequest` `{name?}`
- **Response:** `SubprojectInfo`/JSON

##### 11. `DELETE /api/projects/{project_id}`
- **What it does:** Delete project
- **Expected Payload:** Path `project_id`
- **Response:** `ProjectDeleteResponse`

#### File: `boards.py`
**Description:** Provides insight board creation, widget state management, and file handling for boards.

##### 1. `GET /api/boards`
- **What it does:** List boards
- **Expected Payload:** Bearer auth
- **Response:** `BoardListResponse`

##### 2. `POST /api/boards`
- **What it does:** Create board
- **Expected Payload:** `BoardCreateRequest` `{name}`
- **Response:** `BoardInfo`

##### 3. `DELETE /api/boards/{board_id}`
- **What it does:** Delete board
- **Expected Payload:** Path `board_id`
- **Response:** JSON `{status, ...}`

##### 4. `POST /api/boards/{board_id}/upload`
- **What it does:** Upload board file
- **Expected Payload:** Path `board_id`; `multipart/form-data` file
- **Response:** JSON `{status, file_uuid, ...}`

##### 5. `GET /api/boards/{board_id}/dashboard`
- **What it does:** Get board dashboard state
- **Expected Payload:** Path `board_id`
- **Response:** JSON dashboard/studio state

##### 6. `POST /api/boards/{board_id}/dashboard/save`
- **What it does:** Save board dashboard/studio state
- **Expected Payload:** Path `board_id`; `BoardDashboardSaveRequest`
- **Response:** JSON `{status, ...}`

##### 7. `PUT /api/boards/{board_id}/active-file`
- **What it does:** Set active board file
- **Expected Payload:** Path `board_id`; `ActiveFileRequest`
- **Response:** JSON `{status, ...}`

##### 8. `PUT /api/boards/{board_id}/active-file-stream`
- **What it does:** Stream active-file update
- **Expected Payload:** Path `board_id`; `ActiveFileRequest`
- **Response:** `StreamingResponse` (NDJSON)

##### 9. `POST /api/boards/{board_id}/share`
- **What it does:** Toggle share/config share payload
- **Expected Payload:** Path `board_id`; `BoardPublishRequest`
- **Response:** JSON with share info

##### 10. `PUT /api/boards/{board_id}/publish`
- **What it does:** Publish board
- **Expected Payload:** Path `board_id`; body `dict`
- **Response:** JSON `{status, share_token?, ...}`

##### 11. `PUT /api/boards/{board_id}/unpublish`
- **What it does:** Unpublish board
- **Expected Payload:** Path `board_id`
- **Response:** JSON `{status, ...}`

#### File: `categories.py`
**Description:** Handles question categorization, saving questions, and bookmark management.

##### 1. `GET /api/categories`
- **What it does:** List categories
- **Expected Payload:** Bearer auth
- **Response:** `CategoryItem[]`

##### 2. `PUT /api/categories/rename`
- **What it does:** Rename category
- **Expected Payload:** `CategoryRenameRequest` `{old_name, new_name}`
- **Response:** JSON `{status, ...}`

##### 3. `DELETE /api/categories/{category_name}`
- **What it does:** Delete category
- **Expected Payload:** Path `category_name`
- **Response:** JSON `{status, ...}`

##### 4. `POST /api/questions/save`
- **What it does:** Save question
- **Expected Payload:** `SaveQuestionRequest` `{question_text, category?, file_uuid}`
- **Response:** `SavedQuestionResponse`

##### 5. `GET /api/questions/list`
- **What it does:** List saved questions
- **Expected Payload:** Bearer auth
- **Response:** `SavedQuestionResponse[]`

##### 6. `GET /api/questions/list/{file_uuid}`
- **What it does:** List saved questions for file
- **Expected Payload:** Path `file_uuid`
- **Response:** `SavedQuestionResponse[]`

##### 7. `PUT /api/questions/{question_id}`
- **What it does:** Update saved question
- **Expected Payload:** Path `question_id`; body `dict`
- **Response:** JSON `{status, ...}`

##### 8. `DELETE /api/questions/{question_id}`
- **What it does:** Delete saved question
- **Expected Payload:** Path `question_id`
- **Response:** JSON `{status, ...}`

#### File: `chat.py`
**Description:** Manages chat history and session closing for interactions.

##### 1. `GET /api/chat/{file_uuid}`
- **What it does:** Get chat history
- **Expected Payload:** Path `file_uuid`; query `limit?`, `offset?`
- **Response:** `ChatMessageResponse[]`

##### 2. `POST /api/chat/{file_uuid}`
- **What it does:** Save chat message
- **Expected Payload:** Path `file_uuid`; `ChatMessageSave`
- **Response:** `ChatMessageResponse`

##### 3. `DELETE /api/chat/{file_uuid}`
- **What it does:** Clear chat history
- **Expected Payload:** Path `file_uuid`
- **Response:** JSON `{status, ...}`

##### 4. `POST /api/session/close`
- **What it does:** Session close beacon
- **Expected Payload:** `SessionCloseRequest` `{file_uuid, session_id, token}`
- **Response:** JSON `{status, ...}`

##### 5. `POST /api/chat/{file_uuid}/soft_delete`
- **What it does:** Soft-delete one chat message
- **Expected Payload:** Path `file_uuid`; `ChatMessageSoftDelete` `{message_id}`
- **Response:** JSON `{status, ...}`

#### File: `etl.py`
**Description:** Manages external database connections, pipeline job orchestration, delta syncs, and data transformations.

##### 1. `POST /api/etl/connect`
- **What it does:** Create/test ETL connection
- **Expected Payload:** `ETLConnectRequest`
- **Response:** `ETLConnectResponse`

##### 2. `POST /api/etl/preview-table`
- **What it does:** Preview source table
- **Expected Payload:** `ETLPreviewRequest` `{connection_id, table_name, limit?}`
- **Response:** `ETLPreviewResponse`

##### 3. `POST /api/etl/dry-run`
- **What it does:** Dry-run transform
- **Expected Payload:** `ETLDryRunRequest`
- **Response:** `ETLDryRunResponse`

##### 4. `POST /api/etl/execute-job`
- **What it does:** Execute ETL job
- **Expected Payload:** `ETLExecuteRequest`
- **Response:** `ETLJobResponse`

##### 5. `GET /api/etl/job/{job_id}`
- **What it does:** Get ETL job status
- **Expected Payload:** Path `job_id`
- **Response:** `ETLJobStatusResponse`

##### 6. `GET /api/etl/connection/{connection_id}/jobs`
- **What it does:** List jobs for connection
- **Expected Payload:** Path `connection_id`
- **Response:** JSON `{jobs:[...]}`

##### 7. `POST /api/etl/job/{job_id}/sync`
- **What it does:** Delta sync by job
- **Expected Payload:** Path `job_id`; `ETLDeltaSyncRequest`
- **Response:** `ETLSyncUpdateResponse`

##### 8. `GET /api/etl/connections`
- **What it does:** List ETL connections
- **Expected Payload:** Bearer auth
- **Response:** `ETLConnectionListResponse`

##### 9. `DELETE /api/etl/connections/{connection_id}`
- **What it does:** Delete ETL connection
- **Expected Payload:** Path `connection_id`
- **Response:** JSON `{status, ...}`

##### 10. `GET /api/etl/datasets`
- **What it does:** List ETL datasets/job outputs
- **Expected Payload:** Bearer auth
- **Response:** `ETLDatasetListResponse`

##### 11. `POST /api/etl/sync-update`
- **What it does:** Sync update endpoint
- **Expected Payload:** `ETLSyncUpdateRequest`
- **Response:** `ETLSyncUpdateResponse`

##### 12. `POST /api/etl/generate-transform`
- **What it does:** AI transform script generation
- **Expected Payload:** `ETLGenerateTransformRequest` `{prompt, tables[]}`
- **Response:** `ETLGenerateTransformResponse` `{script}`

##### 13. `PATCH /api/etl/job/{job_id}/sync-config`
- **What it does:** Update ETL sync config
- **Expected Payload:** Path `job_id`; body `dict`
- **Response:** JSON `{status, ...}`

##### 14. `GET /api/etl/job/{job_id}/detail`
- **What it does:** ETL job detailed metadata
- **Expected Payload:** Path `job_id`
- **Response:** JSON job detail

##### 15. `PUT /api/etl/job/{job_id}`
- **What it does:** Update/re-run ETL job config
- **Expected Payload:** Path `job_id`; `ETLExecuteRequest`-like body
- **Response:** JSON `{status, ...}`

#### File: `export.py`
**Description:** Handles dataset exporting in various formats (JSON, CSV).

##### 1. `POST /api/export/{file_identifier}`
- **What it does:** Export dataset
- **Expected Payload:** Path `file_identifier`; query `format?`
- **Response:** JSON/CSV payload

#### File: `health.py`
**Description:** Provides service status, health checks, and API metadata.

##### 1. `GET /health`
- **What it does:** Service health
- **Expected Payload:** None
- **Response:** JSON `{status, database, ...}`

##### 2. `GET /api/info`
- **What it does:** API metadata info
- **Expected Payload:** None
- **Response:** JSON `{api, version, endpoints, ...}`

#### File: `langfuse_share.py`
**Description:** Manages SSO, Langfuse token management, and public shared-dashboard access.

##### 1. `GET /api/langfuse-token`
- **What it does:** Generate Langfuse access token/URL
- **Expected Payload:** Query params for session/trace context
- **Response:** JSON token/url payload

##### 2. `GET /api/langfuse-sso`
- **What it does:** SSO redirect endpoint
- **Expected Payload:** Query `key`
- **Response:** Redirect/HTML response

##### 3. `GET /api/share/{token}`
- **What it does:** Shared board/report fetch by token
- **Expected Payload:** Path `token`
- **Response:** JSON shared payload

##### 4. `POST /api/share/{token}/filter`
- **What it does:** Filter shared data
- **Expected Payload:** Path `token`; `SharedDashboardFilterRequest`
- **Response:** JSON filtered shared payload

##### 5. `GET /api/share/workspace/{token}`
- **What it does:** Public workspace share fetch
- **Expected Payload:** Path `token`
- **Response:** JSON workspace/report payload

##### 6. `POST /api/share/workspace/{token}/chat`
- **What it does:** Chat in shared workspace context
- **Expected Payload:** Path `token`; body `dict`
- **Response:** JSON chat result

##### 7. `POST /api/share/workspace/{token}/report/chat`
- **What it does:** Report chat in shared workspace
- **Expected Payload:** Path `token`; body `dict`
- **Response:** JSON chat/report result

##### 8. `POST /api/share/workspace/{token}/report/execute_custom_sql`
- **What it does:** Execute custom SQL on shared report
- **Expected Payload:** Path `token`; body `{sql,...}`
- **Response:** JSON SQL result

##### 9. `POST /api/share/workspace/{token}/report/summarize`
- **What it does:** Summarize shared report
- **Expected Payload:** Path `token`; body `dict`
- **Response:** JSON summary

##### 10. `GET /api/share/report/{token}`
- **What it does:** Public shared report fetch
- **Expected Payload:** Path `token`
- **Response:** JSON report payload

#### File: `workspace.py`
**Description:** Extensive Workspace CRUD, semantic layer management, and workspace-scoped chat and reporting.

##### 1. `POST /api/workspaces`
- **What it does:** Create workspace
- **Expected Payload:** `WorkspaceCreateRequest` `{name, description?}`
- **Response:** `WorkspaceResponse`

##### 2. `GET /api/workspaces`
- **What it does:** List workspaces
- **Expected Payload:** Bearer auth
- **Response:** `WorkspaceListResponse`

##### 3. `GET /api/workspaces/{workspace_id}`
- **What it does:** Workspace detail
- **Expected Payload:** Path `workspace_id`
- **Response:** `WorkspaceDetailResponse`

##### 4. `PATCH /api/workspaces/{workspace_id}`
- **What it does:** Update workspace
- **Expected Payload:** Path `workspace_id`; `WorkspaceUpdateRequest`
- **Response:** `WorkspaceResponse`

##### 5. `DELETE /api/workspaces/{workspace_id}`
- **What it does:** Delete workspace
- **Expected Payload:** Path `workspace_id`
- **Response:** JSON `{status, ...}`

##### 6. `POST /api/workspaces/{workspace_id}/share/toggle`
- **What it does:** Toggle workspace sharing
- **Expected Payload:** Path `workspace_id`; body `dict`
- **Response:** JSON share status

##### 7. `GET /api/workspaces/{workspace_id}/share/status`
- **What it does:** Get workspace share status
- **Expected Payload:** Path `workspace_id`
- **Response:** JSON share status

##### 8. `GET /api/workspaces/{workspace_id}/tables`
- **What it does:** List workspace tables
- **Expected Payload:** Path `workspace_id`
- **Response:** `TableMetadataResponse[]`/JSON

##### 9. `PATCH /api/workspaces/{workspace_id}/tables/{table_name}/description`
- **What it does:** Update table description
- **Expected Payload:** Path params; `UpdateTableDescriptionRequest`
- **Response:** `TableMetadataResponse`/JSON

##### 10. `GET /api/workspaces/{workspace_id}/tables/{table_name}/columns`
- **What it does:** List table columns
- **Expected Payload:** Path params
- **Response:** `ColumnMetadataResponse[]`

##### 11. `PATCH /api/workspaces/{workspace_id}/columns/{column_id}/description`
- **What it does:** Update column description
- **Expected Payload:** Path params; `UpdateColumnDescriptionRequest`
- **Response:** `ColumnMetadataResponse`/JSON

##### 12. `GET /api/workspaces/{workspace_id}/semantic`
- **What it does:** Semantic layer snapshot
- **Expected Payload:** Path `workspace_id`
- **Response:** `SemanticLayerResponse`

##### 13. `POST /api/workspaces/{workspace_id}/semantic/metrics`
- **What it does:** Create semantic metric
- **Expected Payload:** `SemanticMetricRequest` `{name, formula, description?, related_tables?}`
- **Response:** `SemanticMetricResponse`

##### 14. `DELETE /api/workspaces/{workspace_id}/semantic/metrics/{metric_id}`
- **What it does:** Delete semantic metric
- **Expected Payload:** Path params
- **Response:** JSON `{status, ...}`

##### 15. `POST /api/workspaces/{workspace_id}/semantic/dimensions`
- **What it does:** Create semantic dimension
- **Expected Payload:** `SemanticDimensionRequest` `{name, table_name, column_name, description?, dim_type?}`
- **Response:** `SemanticDimensionResponse`

##### 16. `DELETE /api/workspaces/{workspace_id}/semantic/dimensions/{dimension_id}`
- **What it does:** Delete semantic dimension
- **Expected Payload:** Path params
- **Response:** JSON `{status, ...}`

##### 17. `POST /api/workspaces/{workspace_id}/semantic/synonyms`
- **What it does:** Create semantic synonym
- **Expected Payload:** `SemanticSynonymRequest` `{keyword, mapped_to, mapped_type?}`
- **Response:** `SemanticSynonymResponse`

##### 18. `DELETE /api/workspaces/{workspace_id}/semantic/synonyms/{synonym_id}`
- **What it does:** Delete semantic synonym
- **Expected Payload:** Path params
- **Response:** JSON `{status, ...}`

##### 19. `GET /api/workspaces/{workspace_id}/chat/history`
- **What it does:** Workspace chat history
- **Expected Payload:** Path `workspace_id`; query filters
- **Response:** JSON `{messages:[...], ...}`

##### 20. `DELETE /api/workspaces/{workspace_id}/chat/history`
- **What it does:** Clear workspace chat history
- **Expected Payload:** Path `workspace_id`
- **Response:** JSON `{status, ...}`

##### 21. `DELETE /api/workspaces/{workspace_id}/chat/history/{message_id}`
- **What it does:** Delete one workspace chat message
- **Expected Payload:** Path params
- **Response:** JSON `{status, ...}`

##### 22. `POST /api/workspaces/{workspace_id}/chat`
- **What it does:** Workspace chat query
- **Expected Payload:** Path `workspace_id`; body `dict`
- **Response:** JSON query/chat result

##### 23. `POST /api/workspaces/{workspace_id}/report/execute_custom_sql`
- **What it does:** Execute SQL for workspace report
- **Expected Payload:** Path `workspace_id`; body `{sql,...}`
- **Response:** JSON SQL result

##### 24. `POST /api/workspaces/{workspace_id}/report/summarize`
- **What it does:** Summarize workspace report
- **Expected Payload:** Path `workspace_id`; body `dict`
- **Response:** JSON summary

##### 25. `POST /api/workspaces/{workspace_id}/report/share`
- **What it does:** Share workspace report
- **Expected Payload:** Path `workspace_id`; body `dict`
- **Response:** JSON `{share_token, share_url, ...}`

##### 26. `POST /api/workspaces/{workspace_id}/profile`
- **What it does:** Profile workspace dataset(s)
- **Expected Payload:** Path `workspace_id`; body `dict`
- **Response:** JSON profiling output

##### 27. `POST /api/workspaces/{workspace_id}/profile/{table_name}`
- **What it does:** Profile specific workspace table
- **Expected Payload:** Path params; body `dict?`
- **Response:** JSON profiling output

##### 28. `GET /api/workspaces/{workspace_id}/relationships`
- **What it does:** List inferred/defined relationships
- **Expected Payload:** Path `workspace_id`
- **Response:** JSON `{relationships:[...]}`

##### 29. `POST /api/workspaces/{workspace_id}/relationships`
- **What it does:** Create relationship
- **Expected Payload:** Path `workspace_id`; body `dict`
- **Response:** JSON `{status, relationship_id, ...}`

##### 30. `DELETE /api/workspaces/{workspace_id}/relationships/{relationship_id}`
- **What it does:** Delete relationship
- **Expected Payload:** Path params
- **Response:** JSON `{status, ...}`

##### 31. `GET /api/workspaces/{workspace_id}/dashboard/stream`
- **What it does:** Stream dashboard build/progress
- **Expected Payload:** Path `workspace_id`; query params
- **Response:** `StreamingResponse`

##### 32. `GET /api/workspaces/{workspace_id}/dashboard`
- **What it does:** Workspace dashboard
- **Expected Payload:** Path `workspace_id`; query params
- **Response:** JSON dashboard payload

##### 33. `POST /api/workspaces/{workspace_id}/dashboard/save`
- **What it does:** Save workspace dashboard
- **Expected Payload:** Path `workspace_id`; body `dict`
- **Response:** JSON `{status, dashboard_id, ...}`

##### 34. `POST /api/workspaces/{workspace_id}/dashboard/pin`
- **What it does:** Pin dashboard widget/state
- **Expected Payload:** Path `workspace_id`; body `dict`
- **Response:** JSON `{status, ...}`

##### 35. `DELETE /api/workspaces/{workspace_id}/dashboard/widgets/{widget_id}`
- **What it does:** Delete workspace widget
- **Expected Payload:** Path params
- **Response:** JSON `{status, ...}`

##### 36. `POST /api/workspaces/{workspace_id}/dashboard/widgets/{widget_id}/refresh`
- **What it does:** Refresh widget data
- **Expected Payload:** Path params; body `dict?`
- **Response:** JSON refreshed widget

##### 37. `POST /api/workspaces/{workspace_id}/dashboard/widget`
- **What it does:** Generate workspace widget
- **Expected Payload:** Path `workspace_id`; `DashboardWidgetRequest`-style body
- **Response:** JSON widget payload

##### 38. `POST /api/workspaces/{workspace_id}/dashboard/widget/custom`
- **What it does:** Create custom workspace widget
- **Expected Payload:** Path `workspace_id`; body `dict`
- **Response:** JSON custom widget

##### 39. `GET /api/workspaces/{workspace_id}/dashboard/schema`
- **What it does:** Workspace dashboard schema
- **Expected Payload:** Path `workspace_id`
- **Response:** JSON schema payload

##### 40. `POST /api/workspaces/{workspace_id}/dashboard/chart-builder`
- **What it does:** Workspace chart builder
- **Expected Payload:** Path `workspace_id`; `ChartBuilderRequest`-style body
- **Response:** JSON chart payload

##### 41. `GET /api/workspaces/{workspace_id}/etl-connection`
- **What it does:** Workspace ETL connection metadata
- **Expected Payload:** Path `workspace_id`
- **Response:** JSON connection/status payload

---

*Note: Exact JSON request bodies are available in the code schemas and legacy documentation format. Refer to `app/schemas/` for complete Pydantic models.*

