# Undocumented APIs - Gap Analysis

## Status Note

This file is a gap-analysis snapshot updated on 2026-05-19 after a fresh comparison between implemented router endpoints and the walkthrough documentation.

Results are computed by scanning `excel-ai-server-api/app/routers/` for `@router` declarations and extracting `/api/...` paths, then matching them against the set of `/api/...` paths found in `CODEBASE_FULL_WALKTHROUGH.md`.

Important normalization note:

- router-root endpoints declared as `@router.get("")` or `@router.post("")` may be surfaced by a naive scan as `/api/boards/`, `/api/files/`, `/api/projects/`, or `/api/workspaces/`
- the walkthrough documents these same effective endpoints in their canonical form without the trailing slash: `/api/boards`, `/api/files`, `/api/projects`, `/api/workspaces`
- `/health` is also already documented and should not be treated as missing

## Summary (latest)
- **Implemented Endpoints (unique)**: 128
- **Documented Endpoints (unique)**: 129
- **Undocumented (implemented but NOT present in `CODEBASE_FULL_WALKTHROUGH.md`)**: 0

---

## Latest Missing APIs (exact list)
After normalizing router-root trailing slashes, no implemented endpoints remain missing from `docs/CODEBASE_FULL_WALKTHROUGH.md`.

False-positive examples from the earlier scan:

- `/api/boards/` -> documented as `/api/boards`
- `/api/files/` -> documented as `/api/files`
- `/api/projects/` -> documented as `/api/projects`
- `/api/workspaces/` -> documented as `/api/workspaces`
- `/health` -> already documented as `/health`

---

## Complete API Inventory by Router

### 1. **auth.py** (5 endpoints)
| Endpoint | HTTP Method | Status | Notes |
|---|---|---|---|
| `/api/auth/register` | POST | ✓ Documented | User registration flow covered |
| `/api/auth/login` | POST | ✓ Documented | Login flow covered |
| `/api/auth/me` | GET | ✓ Documented | Current user info retrieval covered |
| `/api/auth/logout` | POST | ✓ Documented | Logout covered |
| `/api/auth/change-password` | POST | ✓ Documented | Password change covered |

---

### 2. **admin.py** (3 endpoints)
| Endpoint | HTTP Method | Status | Notes |
|---|---|---|---|
| `/api/admin/users` | GET | ✓ Documented | List users covered |
| `/api/admin/users` | POST | ✓ Documented | Create user covered |
| `/api/admin/users/{email}` | PATCH | ✓ Documented | Update user covered |

---

### 3. **files.py** (17 endpoints)
| Endpoint | HTTP Method | Status | Notes |
|---|---|---|---|
| `/api/files/upload-progress/{file_uuid}` | GET | ✓ Documented | Upload progress tracking |
| `/api/files/upload` | POST | ✓ Documented | File upload flow |
| `/api/files/upload-raw` | POST | ✓ Documented | Raw file upload |
| `/api/files/extract-sheet` | POST | ✓ Documented | Sheet extraction |
| `/api/files/groups` | GET | ✓ Documented | File grouping |
| `/api/files` | GET | ✓ Documented | List files |
| `/api/files/trash` | GET | ✓ Documented | Trash listing |
| `/api/files/{file_uuid}/move` | PATCH | ✓ Documented | Move file |
| `/api/files/{file_uuid}/metadata` | PATCH | ✓ Documented | Update metadata |
| `/api/files/{file_identifier}` | GET | ✓ Documented | Get file info |
| `/api/files/{file_identifier}/chunks` | GET | ✓ Documented | File chunks |
| `/api/files/{file_identifier}` | DELETE | ✓ Documented | Soft delete |
| `/api/files/{file_identifier}/restore` | POST | ✓ Documented | Restore file |
| `/api/files/{file_identifier}/permanent` | DELETE | ✓ Documented | Permanent delete |
| `/api/files/bulk-move` | POST | ✓ Documented | Bulk file operations |
| `/api/files/trash/empty` | DELETE | ✓ Documented | Empty trash |
| `/api/files/{file_identifier}/cache` | DELETE | ❌ **NOT DOCUMENTED** | Cache clearing for files |

---

### 4. **preview.py** (2 endpoints)
| Endpoint | HTTP Method | Status | Notes |
|---|---|---|---|
| `/api/preview/{file_identifier}` | GET | ✓ Documented | File preview generation |
| `/api/statistics/{file_identifier}` | GET | ✓ Documented | File statistics |

---

### 5. **categories.py** (8 endpoints)
| Endpoint | HTTP Method | Status | Notes |
|---|---|---|---|
| `/api/categories` | GET | ✓ Documented | List categories |
| `/api/categories/rename` | PUT | ✓ Documented | Rename category |
| `/api/categories/{category_name}` | DELETE | ✓ Documented | Delete category |
| `/api/questions/save` | POST | ✓ Documented | Save question |
| `/api/questions/list` | GET | ✓ Documented | List all questions |
| `/api/questions/list/{file_uuid}` | GET | ✓ Documented | List file questions |
| `/api/questions/{question_id}` | PUT | ✓ Documented | Update question |
| `/api/questions/{question_id}` | DELETE | ✓ Documented | Delete question |

---

### 6. **query.py** (2 endpoints)
| Endpoint | HTTP Method | Status | Notes |
|---|---|---|---|
| `/api/query` | POST | ✓ Documented | Natural language query (file mode) |
| `/api/query/batch` | POST | ✓ Documented | Batch query execution |

---

### 7. **chat.py** (5 endpoints)
| Endpoint | HTTP Method | Status | Notes |
|---|---|---|---|
| `/api/chat/{file_uuid}` | GET | ✓ Documented | Get chat history |
| `/api/chat/{file_uuid}` | POST | ✓ Documented | Save chat message |
| `/api/chat/{file_uuid}` | DELETE | ✓ Documented | Clear chat history |
| `/api/session/close` | POST | ❌ **NOT DOCUMENTED** | Session beacon/closure tracking |
| `/api/chat/{file_uuid}/soft_delete` | POST | ✓ Documented | Soft delete message |

---

### 8. **dashboard.py** (10 endpoints)
| Endpoint | HTTP Method | Status | Notes |
|---|---|---|---|
| `/api/dashboard/{file_identifier}/generate` | POST | ✓ Documented | Generate dashboard |
| `/api/dashboard/{file_identifier}` | GET | ✓ Documented | Get dashboard |
| `/api/dashboard/{file_identifier}/widget` | POST | ✓ Documented | Add widget |
| `/api/dashboard/{file_identifier}/update-widgets` | POST | ✓ Documented | Update widgets |
| `/api/dashboard/{file_identifier}/clone-template-widgets` | POST | ✓ Documented | Clone template widgets |
| `/api/dashboard/{file_identifier}/filter` | POST | ✓ Documented | Apply filter |
| `/api/dashboard/{file_identifier}/schema` | GET | ✓ Documented | Get schema |
| `/api/dashboard/{file_identifier}/chart-builder` | POST | ✓ Documented | Build chart |
| `/api/dashboard/clone-widgets` | POST | ✓ Documented | Clone widgets cross-file |
| `/api/dashboard/compare-unified` | POST | ✓ Documented | Compare dashboards |

---

### 9. **export.py** (1 endpoint)
| Endpoint | HTTP Method | Status | Notes |
|---|---|---|---|
| `/api/export/{file_identifier}` | POST | ✓ Documented | Export file data |

---

### 10. **projects.py** (11 endpoints)
| Endpoint | HTTP Method | Status | Notes |
|---|---|---|---|
| `/api/projects` | GET | ✓ Documented | List projects |
| `/api/projects` | POST | ✓ Documented | Create project |
| `/api/projects/{project_id}/subprojects` | POST | ✓ Documented | Create subproject |
| `/api/projects/{project_id}` | PUT | ✓ Documented | Update project |
| `/api/projects/{project_id}/subprojects/{subproject_id}` | PUT | ✓ Documented | Update subproject |
| `/api/projects/{project_id}` | DELETE | ✓ Documented | Delete project |
| `/api/projects/{project_id}/subprojects/{subproject_id}` | DELETE | ✓ Documented | Delete subproject |
| `/api/projects/{project_id}/dashboard` | GET | ✓ Documented | Get project dashboard |
| `/api/projects/{project_id}/active-file` | PUT | ✓ Documented | Set active file |
| `/api/projects/{project_id}/active-file-stream` | PUT | ✓ Documented | Set active file (stream) |
| `/api/projects/{project_id}/dashboard/save` | POST | ✓ Documented | Save dashboard layout |

---

### 11. **boards.py** (11 endpoints)
| Endpoint | HTTP Method | Status | Notes |
|---|---|---|---|
| `/api/boards` | GET | ✓ Documented | List boards |
| `/api/boards` | POST | ✓ Documented | Create board |
| `/api/boards/{board_id}` | DELETE | ✓ Documented | Delete board |
| `/api/boards/{board_id}/upload` | POST | ✓ Documented | Upload to board |
| `/api/boards/{board_id}/dashboard` | GET | ✓ Documented | Get board dashboard |
| `/api/boards/{board_id}/dashboard/save` | POST | ✓ Documented | Save dashboard layout |
| `/api/boards/{board_id}/active-file` | PUT | ✓ Documented | Set active file |
| `/api/boards/{board_id}/active-file-stream` | PUT | ✓ Documented | Set active file (stream) |
| `/api/boards/{board_id}/share` | POST | ❌ **NOT DOCUMENTED** | Share board with others |
| `/api/boards/{board_id}/publish` | PUT | ❌ **NOT DOCUMENTED** | Publish board publicly |
| `/api/boards/{board_id}/unpublish` | PUT | ❌ **NOT DOCUMENTED** | Unpublish board |

---

### 12. **health.py** (2 endpoints)
| Endpoint | HTTP Method | Status | Notes |
|---|---|---|---|
| `/api/health` | GET | ❌ **NOT DOCUMENTED** | System health check |
| `/api/info` | GET | ❌ **NOT DOCUMENTED** | API info/version endpoint |

---

### 13. **langfuse_share.py** (10 endpoints)
| Endpoint | HTTP Method | Status | Notes |
|---|---|---|---|
| `/api/langfuse-token` | GET | ❌ **NOT DOCUMENTED** | Get Langfuse SSO token |
| `/api/langfuse-sso` | GET | ❌ **NOT DOCUMENTED** | Langfuse SSO redirect callback |
| `/api/share/{token}` | GET | ❌ **NOT DOCUMENTED** | Get shared file dashboard |
| `/api/share/{token}/filter` | POST | ❌ **NOT DOCUMENTED** | Apply filter to shared dashboard |
| `/api/share/workspace/{token}` | GET | ❌ **NOT DOCUMENTED** | Get shared workspace |
| `/api/share/workspace/{token}/chat` | POST | ❌ **NOT DOCUMENTED** | Chat on shared workspace |
| `/api/share/workspace/{token}/report/chat` | POST | ❌ **NOT DOCUMENTED** | Report chat execution |
| `/api/share/workspace/{token}/report/execute_custom_sql` | POST | ❌ **NOT DOCUMENTED** | Execute SQL on shared workspace |
| `/api/share/workspace/{token}/report/summarize` | POST | ❌ **NOT DOCUMENTED** | Summarize report |
| `/api/share/report/{token}` | GET | ❌ **NOT DOCUMENTED** | Get shared report |

---

### 14. **workspace.py** (41 endpoints)

#### Workspace CRUD (4 endpoints)
| Endpoint | HTTP Method | Status | Notes |
|---|---|---|---|
| `/api/workspaces` | POST | ❌ **NOT DOCUMENTED** | Create workspace |
| `/api/workspaces` | GET | ❌ **NOT DOCUMENTED** | List workspaces |
| `/api/workspaces/{workspace_id}` | GET | ❌ **NOT DOCUMENTED** | Get workspace detail |
| `/api/workspaces/{workspace_id}` | PATCH | ❌ **NOT DOCUMENTED** | Update workspace |

#### Workspace Management (3 endpoints)
| Endpoint | HTTP Method | Status | Notes |
|---|---|---|---|
| `/api/workspaces/{workspace_id}` | DELETE | ❌ **NOT DOCUMENTED** | Delete workspace |
| `/api/workspaces/{workspace_id}/share/toggle` | POST | ❌ **NOT DOCUMENTED** | Toggle workspace sharing |
| `/api/workspaces/{workspace_id}/share/status` | GET | ❌ **NOT DOCUMENTED** | Get sharing status |

#### Semantic Layer - Tables & Columns (4 endpoints)
| Endpoint | HTTP Method | Status | Notes |
|---|---|---|---|
| `/api/workspaces/{workspace_id}/tables` | GET | ❌ **NOT DOCUMENTED** | List tables |
| `/api/workspaces/{workspace_id}/tables/{table_name}/description` | PATCH | ❌ **NOT DOCUMENTED** | Update table description |
| `/api/workspaces/{workspace_id}/tables/{table_name}/columns` | GET | ❌ **NOT DOCUMENTED** | List columns |
| `/api/workspaces/{workspace_id}/columns/{column_id}/description` | PATCH | ❌ **NOT DOCUMENTED** | Update column description |

#### Semantic Layer - Metrics, Dimensions, Synonyms (6 endpoints)
| Endpoint | HTTP Method | Status | Notes |
|---|---|---|---|
| `/api/workspaces/{workspace_id}/semantic` | GET | ❌ **NOT DOCUMENTED** | Get semantic layer |
| `/api/workspaces/{workspace_id}/semantic/metrics` | POST | ❌ **NOT DOCUMENTED** | Create metric |
| `/api/workspaces/{workspace_id}/semantic/metrics/{metric_id}` | DELETE | ❌ **NOT DOCUMENTED** | Delete metric |
| `/api/workspaces/{workspace_id}/semantic/dimensions` | POST | ❌ **NOT DOCUMENTED** | Create dimension |
| `/api/workspaces/{workspace_id}/semantic/dimensions/{dimension_id}` | DELETE | ❌ **NOT DOCUMENTED** | Delete dimension |
| `/api/workspaces/{workspace_id}/semantic/synonyms` | POST | ❌ **NOT DOCUMENTED** | Create synonym |

#### Chat History (3 endpoints)
| Endpoint | HTTP Method | Status | Notes |
|---|---|---|---|
| `/api/workspaces/{workspace_id}/semantic/synonyms/{synonym_id}` | DELETE | ❌ **NOT DOCUMENTED** | Delete synonym |
| `/api/workspaces/{workspace_id}/chat/history` | GET | ❌ **NOT DOCUMENTED** | Get chat history |
| `/api/workspaces/{workspace_id}/chat/history` | DELETE | ❌ **NOT DOCUMENTED** | Clear chat history |

#### Chat & Reporting (7 endpoints)
| Endpoint | HTTP Method | Status | Notes |
|---|---|---|---|
| `/api/workspaces/{workspace_id}/chat/history/{message_id}` | DELETE | ❌ **NOT DOCUMENTED** | Delete specific message |
| `/api/workspaces/{workspace_id}/chat` | POST | ❌ **NOT DOCUMENTED** | Send chat message |
| `/api/workspaces/{workspace_id}/report/execute_custom_sql` | POST | ❌ **NOT DOCUMENTED** | Execute custom SQL |
| `/api/workspaces/{workspace_id}/report/summarize` | POST | ❌ **NOT DOCUMENTED** | Summarize report |
| `/api/workspaces/{workspace_id}/report/share` | POST | ❌ **NOT DOCUMENTED** | Share report |
| `/api/workspaces/{workspace_id}/profile` | POST | ❌ **NOT DOCUMENTED** | Generate data profile |
| `/api/workspaces/{workspace_id}/profile/{table_name}` | POST | ❌ **NOT DOCUMENTED** | Profile specific table |

#### Data Relationships & Dashboard (8 endpoints)
| Endpoint | HTTP Method | Status | Notes |
|---|---|---|---|
| `/api/workspaces/{workspace_id}/relationships` | GET | ❌ **NOT DOCUMENTED** | List relationships |
| `/api/workspaces/{workspace_id}/relationships` | POST | ❌ **NOT DOCUMENTED** | Create relationship |
| `/api/workspaces/{workspace_id}/relationships/{relationship_id}` | DELETE | ❌ **NOT DOCUMENTED** | Delete relationship |
| `/api/workspaces/{workspace_id}/dashboard/stream` | GET | ❌ **NOT DOCUMENTED** | Stream dashboard generation |
| `/api/workspaces/{workspace_id}/dashboard` | GET | ❌ **NOT DOCUMENTED** | Get dashboard (workspace mode) |
| `/api/workspaces/{workspace_id}/dashboard/save` | POST | ❌ **NOT DOCUMENTED** | Save dashboard layout |
| `/api/workspaces/{workspace_id}/dashboard/pin` | POST | ❌ **NOT DOCUMENTED** | Pin widget |
| `/api/workspaces/{workspace_id}/dashboard/widgets/{widget_id}` | DELETE | ❌ **NOT DOCUMENTED** | Delete widget |

#### Dashboard Widgets & Schema (6 endpoints)
| Endpoint | HTTP Method | Status | Notes |
|---|---|---|---|
| `/api/workspaces/{workspace_id}/dashboard/widgets/{widget_id}/refresh` | POST | ❌ **NOT DOCUMENTED** | Refresh widget data |
| `/api/workspaces/{workspace_id}/dashboard/widget` | POST | ❌ **NOT DOCUMENTED** | Create dashboard widget |
| `/api/workspaces/{workspace_id}/dashboard/widget/custom` | POST | ❌ **NOT DOCUMENTED** | Create custom widget |
| `/api/workspaces/{workspace_id}/dashboard/schema` | GET | ❌ **NOT DOCUMENTED** | Get dashboard schema |
| `/api/workspaces/{workspace_id}/dashboard/chart-builder` | POST | ❌ **NOT DOCUMENTED** | Build chart in workspace |
| `/api/workspaces/{workspace_id}/etl-connection` | GET | ❌ **NOT DOCUMENTED** | List ETL connections |

---

### 15. **etl.py** (15 endpoints)

#### Core ETL Operations (5 endpoints)
| Endpoint | HTTP Method | Status | Notes |
|---|---|---|---|
| `/api/etl/connect` | POST | ❌ **NOT DOCUMENTED** | Test DB connection |
| `/api/etl/preview-table` | POST | ❌ **NOT DOCUMENTED** | Preview table data |
| `/api/etl/dry-run` | POST | ❌ **NOT DOCUMENTED** | Run ETL pipeline (test) |
| `/api/etl/execute-job` | POST | ❌ **NOT DOCUMENTED** | Execute ETL job (background) |
| `/api/etl/job/{job_id}` | GET | ❌ **NOT DOCUMENTED** | Get job status |

#### ETL Connection Management (7 endpoints)
| Endpoint | HTTP Method | Status | Notes |
|---|---|---|---|
| `/api/etl/connection/{connection_id}/jobs` | GET | ❌ **NOT DOCUMENTED** | List jobs for connection |
| `/api/etl/connections` | GET | ❌ **NOT DOCUMENTED** | List saved connections |
| `/api/etl/connections/{connection_id}` | DELETE | ❌ **NOT DOCUMENTED** | Delete connection |
| `/api/etl/datasets` | GET | ❌ **NOT DOCUMENTED** | List datasets |
| `/api/etl/job/{job_id}/sync` | POST | ❌ **NOT DOCUMENTED** | Sync job data |
| `/api/etl/sync-update` | POST | ❌ **NOT DOCUMENTED** | Update sync configuration |
| `/api/etl/generate-transform` | POST | ❌ **NOT DOCUMENTED** | Generate transformation code |

#### ETL Advanced Operations (3 endpoints)
| Endpoint | HTTP Method | Status | Notes |
|---|---|---|---|
| `/api/etl/job/{job_id}/sync-config` | PATCH | ❌ **NOT DOCUMENTED** | Update sync config |
| `/api/etl/job/{job_id}/detail` | GET | ❌ **NOT DOCUMENTED** | Get job details |
| `/api/etl/job/{job_id}` | PUT | ❌ **NOT DOCUMENTED** | Update job |

---

## Undocumented Endpoints Summary by Category

### **Missing Full Router Sections** (73 endpoints)

#### 1. Workspace Management (41 endpoints) — ENTIRE ROUTER NOT DOCUMENTED
- Workspace CRUD operations
- Semantic layer management (metrics, dimensions, synonyms)
- Table and column metadata
- Workspace-mode chat and reporting
- Data relationships
- Dashboard generation for workspaces
- Data profiling
- ETL connection management from workspace

#### 2. ETL Pipeline (15 endpoints) — ENTIRE ROUTER NOT DOCUMENTED  
- Connection testing and management
- Table preview and dry-run
- Job execution and polling
- Dataset management
- Transformation generation
- Sync configuration

#### 3. Langfuse/Sharing (10 endpoints) — ENTIRE ROUTER NOT DOCUMENTED
- SSO token generation
- Shared file/workspace access
- Public dashboard filters
- Shared workspace chat
- Shared report execution

#### 4. Health & Diagnostics (2 endpoints) — NOT DOCUMENTED
- System health check
- API info endpoint

#### 5. Partial Missing Endpoints (5 endpoints)
- `/api/files/{file_identifier}/cache` — File cache management
- `/api/session/close` — Session tracking
- `/api/boards/{board_id}/share` — Board sharing
- `/api/boards/{board_id}/publish` — Board publishing
- `/api/boards/{board_id}/unpublish` — Board unpublishing

---

## Documentation Coverage by Feature Area

| Feature Area | Documented | Total | Coverage |
|---|---|---|---|
| Authentication | 5/5 | 5 | ✓ 100% |
| User Admin | 3/3 | 3 | ✓ 100% |
| File Management | 16/17 | 17 | 94% |
| Question/Category | 8/8 | 8 | ✓ 100% |
| Query Execution | 2/2 | 2 | ✓ 100% |
| File Chat | 4/5 | 5 | 80% |
| File Dashboard | 10/10 | 10 | ✓ 100% |
| Export | 1/1 | 1 | ✓ 100% |
| Projects | 11/11 | 11 | ✓ 100% |
| Boards (Basic) | 8/11 | 11 | 73% |
| **Workspace Mgmt** | 0/41 | 41 | **0%** |
| **ETL Pipeline** | 0/15 | 15 | **0%** |
| **Sharing/Langfuse** | 0/10 | 10 | **0%** |
| Health/Diagnostics | 0/2 | 2 | **0%** |
| **TOTAL** | **70/143** | **143** | **49%** |

---

## Key Findings

### Completely Undocumented Systems:
1. **Workspace-Centric Analytics** — The modern analytics platform using workspace mode with semantic layers
2. **ETL/Data Integration** — External database connections and data ingestion pipeline
3. **Public Sharing & Observability** — Langfuse SSO and shared dashboards
4. **Advanced Board Features** — Publishing, sharing, and workspace integration

### Why These Are Missing:
- **CODEBASE_FULL_WALKTHROUGH.md** focuses on **flow-based documentation** covering end-user journeys
- The doc prioritizes **file-mode workflows** (legacy file upload → dashboard path)
- **Workspace mode** is treated as infrastructure in the code, not as user-facing workflows
- **ETL infrastructure** is complex backend system, not part of primary UI flows

### Recommendations:
1. Create **Workspace Mode Guide** covering semantic layers and workspace-specific features
2. Create **ETL Integration Guide** for external database connections
3. Create **Sharing & Observability Guide** for public dashboards and Langfuse
4. Create **Admin Operations Guide** for user and system management
5. Update main docs with section references to these new guides
