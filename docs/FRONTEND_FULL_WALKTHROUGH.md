# Frontend Full Walkthrough

## Purpose

This document explains the frontend as a feature-driven system instead of a folder listing.

It is designed to answer:

- which pages make up the product
- which stores and services each page uses
- how navigation works
- how state flows from page to API
- which components are structural versus feature-specific
- where to start reading for any major frontend feature

This complements:

- [CODEBASE_FULL_WALKTHROUGH.md](/F:/MKCL%20Training/pandas%20triagent%20system/docs/CODEBASE_FULL_WALKTHROUGH.md:1)
- [FRONTEND_ARCHITECTURE_REPORT.md](/F:/MKCL%20Training/pandas%20triagent%20system/docs/FRONTEND_ARCHITECTURE_REPORT.md:1)
- [FRONTEND_STATE_API_FLOW_REPORT.md](/F:/MKCL%20Training/pandas%20triagent%20system/docs/FRONTEND_STATE_API_FLOW_REPORT.md:1)

---

## Frontend Technology Role

The frontend is a Vue 3 SPA that acts as the user-facing orchestration layer for:

- authentication
- file management
- ETL pipeline setup
- workspace analytics
- dashboard building
- sharing and reporting

Main frontend stack:

- Vue 3
- TypeScript
- Vue Router
- Pinia
- Axios and fetch
- GridStack for dashboard layout
- ECharts for chart rendering
- shadcn-vue style UI primitives

---

## Top-Level Frontend Structure

Main folder:

- `excel-ai-client/src/`

Key subfolders:

- `pages/`
  Route-level screens and product modules.
- `services/`
  API integration layer.
- `store/`
  Shared state and persistence.
- `components/`
  Reusable UI and feature components.
- `router/`
  Route definitions and auth guard.
- `utils/`
  Support helpers such as file tree generation and Langfuse bridge.
- `plugins/`
  Custom helper classes and app-level plugin-like utilities.
- `assets/`
  Global styles and supporting assets.
- `lang/`
  Localization JSON files.

---

## Frontend Bootstrap Module

This is the first layer of the UI and sets up the application shell, routing, and global state.

### Files involved

- `excel-ai-client/src/main.ts`
- `excel-ai-client/src/App.vue`
- `excel-ai-client/src/router/router.ts`

### What each file does

#### `src/main.ts`

Responsibilities:

- loads global CSS and icon support
- initializes theme
- creates Pinia
- enables persisted Pinia state
- mounts the app
- sets custom global MQL configuration

Important function:

- `initializeTheme()`
  Reads theme preference and applies root-level classes.

App bootstrap sequence:

1. imports global styles
2. initializes theme
3. creates Pinia
4. attaches persistence plugin
5. creates Vue app
6. attaches router
7. mounts `App.vue`

#### `src/App.vue`

Responsibilities:

- mounts global toast system
- exposes `RouterView`

This file is intentionally very thin. The product is route-driven, not shell-driven.

#### `src/router/router.ts`

Responsibilities:

- defines all routes
- separates public and authenticated flows
- applies route guard for authentication

Important logic:

- redirects `/` to `/login`
- protects `/app/*`
- exposes shared/public routes without auth

Main route groups:

- auth routes
  - `/login`
  - `/register`
- authenticated app routes
  - `/app`
  - `/app/upload`
  - `/app/chat`
  - `/app/dashboard`
  - `/app/etl`
  - `/app/workspaces/*`
- public share routes
  - `/share/:token`
  - `/shared/workspace/:token`
  - `/shared/report/:token`

### Why this module matters

This layer determines the full product shape. Every major experience is a route-mounted screen, and understanding `router.ts` is the fastest way to understand the frontend surface area.

---

## API Integration Module

The service layer is the frontend’s contract with the backend.

### Files involved

- `excel-ai-client/src/services/excelApi.ts`
- `excel-ai-client/src/services/workspaceApi.ts`

### `src/services/excelApi.ts`

This is the large API wrapper for the legacy and mixed-mode product surface.

It handles:

- auth-adjacent helpers
- file upload and file management
- file query
- legacy dashboard generation
- project and board operations
- categories and saved questions
- ETL flow
- exports and previews
- shared dashboard operations

It also exports many shared TypeScript interfaces such as:

- `FileInfo`
- `ProjectInfo`
- `BoardInfo`
- `QueryResponse`
- `DashboardWidget`
- `DashboardResponse`
- ETL-related response types

Infrastructure responsibilities:

- creates the Axios client
- injects the auth token from `localStorage`
- handles `401` redirects
- logs network failures

Main usage pattern:

Pages call `excelFileAPI.someMethod()`, get typed data, update local or store state, and then render.

### `src/services/workspaceApi.ts`

This is the cleaner, workspace-focused service layer for the newer system.

It handles:

- workspace CRUD
- table and column metadata
- semantic layer CRUD
- workspace relationships
- workspace chat
- report SQL execution
- report summarization
- workspace dashboard retrieval and save
- widget generation
- chart builder
- history and sharing

Important distinction:

- `excelApi.ts` is broader and older, serving many mixed/legacy flows.
- `workspaceApi.ts` is more product-specific and models the newer workspace system directly.

### Why this module matters

If you want to know how a frontend screen talks to the backend, the answer is almost always in these two files.

---

## Global State Module

The store layer centralizes user state, explorer state, and board state.

### Files involved

- `excel-ai-client/src/store/login.ts`
- `excel-ai-client/src/store/documents.ts`
- `excel-ai-client/src/store/boards.ts`
- `excel-ai-client/src/store/index.ts`

### `src/store/login.ts`

Responsibilities:

- store token
- store authentication status
- store current user info
- perform login/register/logout
- fetch current user profile
- expose permission checks

Key actions:

- `login()`
- `register()`
- `fetchUserInfo()`
- `logout()`
- `hasPermission()`

How it is used:

- auth pages call `login()` or `register()`
- protected pages rely on router auth guard and persisted token
- app features can check `hasPermission()`

### `src/store/documents.ts`

This is one of the most important stores because it powers the explorer and file-centered dashboard experience.

Responsibilities:

- maintain active files and trash files
- maintain projects and subprojects
- maintain file filters, sorting, tags, pinned/favorites
- maintain dashboard layout persistence
- maintain compare mode state

Key state areas:

- file collections
- project collections
- search/filter/sort state
- expanded folder state
- dashboard layout cache
- compare mode

Important functions:

- `fetchFiles()`
- `fetchProjects()`
- `fetchAll()`
- `createProject()`
- `renameProject()`
- `updateProjectColor()`
- `deleteProject()`
- `createSubproject()`
- `renameSubproject()`
- `deleteSubproject()`
- `moveFile()`
- `togglePin()`
- `toggleFavorite()`
- `updateTags()`
- dashboard layout and theme persistence helpers

How it is used:

- `pages/documents/index.vue` uses it heavily
- `SmartDashboard.vue` uses it for file tree and compare-related flows

### `src/store/boards.ts`

Responsibilities:

- maintain list of boards
- maintain active board widget selection
- maintain screen list and active screen

Important functions:

- `fetchBoards()`
- `createBoard()`
- `deleteBoard()`
- `setActiveWidget()`
- `addScreen()`
- `setActiveScreen()`

Used mainly by:

- `pages/documents/index.vue`
- `pages/dashboard/SmartDashboard.vue`

### `src/store/index.ts`

This is a small general-purpose store layer entry, less central than the three feature stores above.

### Why this module matters

These stores prevent the app from becoming a purely local-state UI and make explorer, auth, and board behavior persistent and reusable across routes.

---

## Utility And Integration Helpers Module

These files are small, but they connect major behaviors.

### Files involved

- `excel-ai-client/src/utils/fileTree.ts`
- `excel-ai-client/src/utils/langfuseBridge.ts`

### `src/utils/fileTree.ts`

Responsibilities:

- convert flat files and projects into a VS Code-style nested explorer tree
- support grouped multi-sheet files
- order pinned items consistently

Important exports:

- `FolderNode`
- `FileNode`
- `GroupNode`
- `TreeNode`
- `buildFileTree()`

Supporting helpers:

- `isPinnedNode()`
- `sortNodesByPinned()`
- `fileToNode()`

Used by:

- `pages/documents/index.vue`
- `pages/dashboard/SmartDashboard.vue`

### `src/utils/langfuseBridge.ts`

Responsibilities:

- silently sync application auth into Langfuse by creating an iframe to a Langfuse signin endpoint

Important function:

- `syncAuthToLangfuse()`

Used by:

- `store/login.ts`

### Why this module matters

These helpers solve two important cross-cutting concerns:

- how files appear as a structured explorer
- how observability is connected to the user session

---

## Authentication UI Module

This module is the user-entry layer for the app.

### Files involved

- `excel-ai-client/src/pages/login/index.vue`
- `excel-ai-client/src/pages/register/index.vue`
- `excel-ai-client/src/pages/layout/AuthLayout.vue`
- `excel-ai-client/src/components/login/UserAuthForm.vue`
- `excel-ai-client/src/components/auth/AuthForm.vue`
- `excel-ai-client/src/components/ChangePasswordModal.vue`

### Responsibilities

- capture credentials
- dispatch login/register actions
- show validation and loading states
- support password changes

### Flow

1. user opens `/login`
2. auth form collects credentials
3. form calls store action `Login.login()`
4. login store calls backend through Axios client
5. token is stored
6. router redirects into authenticated routes

### Supporting layout

`pages/layout/AuthLayout.vue` provides the stripped-down layout for auth pages so users are not inside the full app shell before login.

### Why this module matters

It is the first screen every authenticated user touches and is the gateway into all other product modules.

---

## File Explorer And Document Workspace Module

This is the main legacy landing area for file-based analytics.

### Files involved

- `excel-ai-client/src/pages/documents/index.vue`
- `excel-ai-client/src/pages/documents/FileSystemNode.vue`
- `excel-ai-client/src/pages/documents/FilterPopover.vue`
- `excel-ai-client/src/store/documents.ts`
- `excel-ai-client/src/store/boards.ts`
- `excel-ai-client/src/services/excelApi.ts`
- `excel-ai-client/src/utils/fileTree.ts`
- `excel-ai-client/src/pages/chat/index.vue`

### What this screen is responsible for

This page is not just a file list. It is a multi-function operating surface for the legacy system:

- file explorer
- project/subproject organization
- dashboard folder creation
- file upload
- multi-sheet extraction
- preview
- chunk viewer
- saved question replay
- quick transition into chat and dashboard flows

### Key state and functions in `documents/index.vue`

Important local areas:

- explorer accordion state
- upload modal state
- multi-sheet picker state
- replay dialog state
- preview state
- chunk pagination state
- selected file state
- sidebar state

Important functions:

- `handleCreateRootFolder()`
- `handleCreateDashboard()`
- `toggleSidebar()`
- `toggleExplorerSection()`
- upload flow helpers
- multi-sheet extraction handlers
- replay question selection handlers

### How the file explorer is built

1. store loads files and projects through `fetchAll()`
2. page computes `folderFileTree`
3. `buildFileTree()` creates the nested folder/file/group structure
4. `FileSystemNode.vue` renders it recursively

### How upload is handled in the page

1. user chooses file
2. page starts upload
3. `excelApi.uploadFileWithProgress()` sends multipart request
4. page subscribes to SSE progress
5. after completion, store refreshes files
6. user can optionally trigger replay of saved questions

### How this module connects to other modules

- file upload connects to backend ingestion
- selected file connects to chat page
- selected file connects to SmartDashboard
- dashboard folder creation connects to board/project mode

### Why this module matters

It is the main operating console for users who work with uploaded files rather than workspaces.

---

## Legacy Smart Dashboard And Board Studio Module

This is the most complex single frontend file and one of the most important pieces of the whole client.

### Files involved

- `excel-ai-client/src/pages/dashboard/SmartDashboard.vue`
- `excel-ai-client/src/services/excelApi.ts`
- `excel-ai-client/src/store/documents.ts`
- `excel-ai-client/src/store/boards.ts`
- `excel-ai-client/src/components/dashboard/LeftSidebar.vue`
- `excel-ai-client/src/components/dashboard/RightProperties.vue`
- `excel-ai-client/src/components/dashboard/WidgetFloatingToolbar.vue`
- `excel-ai-client/src/components/dashboard/WidgetStyleChooserModal.vue`
- `excel-ai-client/src/components/dashboard/ERDWidget.vue`

### Why this file is so large

`SmartDashboard.vue` is not one dashboard page. It is a combined studio for multiple modes:

- file dashboard mode
- project dashboard mode
- board dashboard mode
- shared dashboard mode
- compare mode

It also handles:

- GridStack layout
- chart rendering
- screen management
- file source switching
- compare loading
- export to PNG and PDF
- share/publish controls
- board design state
- widget edits
- chart filters
- command palette behavior

### Core mode-resolution logic

The page determines behavior using computed values like:

- `activeProjectId`
- `isDashboardProject`
- `activeBoardId`
- `isBoardMode`
- `shareToken`
- `isSharedMode`

That mode branching is the key to understanding the file.

### Main operational function groups

#### Initialization and data loading

- `loadFileInfo()`
- `loadDashboard()`
- `initProjectDashboard()`
- `initBoardDashboard()`
- `initSharedDashboard()`
- `loadDataSources()`

#### Grid and persistence

- `initGrid()`
- `initGridB()`
- `persistDashboardWidgets()`
- board save payload generation

#### Widget creation and editing

- `addCustomWidget()`
- `removeWidget()`
- `recomputeActiveChart()`
- `recomputeActiveKpi()`
- `handleWidgetStyleUpdate()`
- `setWidgetColor()`
- `clearWidgetColor()`

#### Compare mode

- `loadCompareFiles()`
- `openCompareSelector()`
- `selectCompareFile()`
- `switchCompareView()`
- `exitCompareMode()`

#### Source and board control

- `triggerDataSourceUpload()`
- `handleDataSourceUpload()`
- `switchActiveDataSource()`
- `generatePendingScreenDashboard()`
- `toggleShareStatus()`
- `publishBoard()`

#### Export and sharing

- `exportDashboardPNG()`
- `exportDashboardPDF()`
- `copyShareLink()`
- `openDashboardSession()`
- `openLastDashboardTrace()`

### Supporting components

#### `LeftSidebar.vue`

Used as the structural left control layer for:

- screens
- data sources
- element selection
- board-oriented dashboard navigation

#### `RightProperties.vue`

Used as the widget properties editor:

- style
- display behavior
- chart settings
- design adjustments

#### `WidgetFloatingToolbar.vue`

Used for quick per-widget actions such as edit/duplicate/remove.

#### `WidgetStyleChooserModal.vue`

Used for changing widget style and variant quickly.

#### `ERDWidget.vue`

Special-purpose widget for relationship visualization.

### Why this module matters

This file is the frontend presentation layer for the legacy intelligence system. If someone wants to understand how the UI becomes a dashboard studio, this is the main file to study.

---

## ETL Wizard Module

This module is the frontend control panel for database ingestion and transformation.

### Files involved

- `excel-ai-client/src/pages/etl/index.vue`
- `excel-ai-client/src/services/excelApi.ts`

### Responsibilities

- connect to source databases
- load saved connections
- preview source tables
- define extract datasets
- generate or edit transform script
- dry run the pipeline
- execute ETL jobs
- poll job status
- manage existing pipelines
- trigger delta sync
- configure sync behavior

### Major state groups in the page

- wizard step state
- connection credentials
- available source tables
- selected extract datasets
- transform script and AI prompt
- dry run result
- execution job state
- polling timer
- saved connections
- pipeline rename/sync configuration state
- pending relationships

### Key functions

- `handleConnect()`
- `useSavedConnection()`
- `loadSavedConnections()`
- `deleteSavedConnection()`
- `toggleTable()`
- `selectAllTables()`
- `previewTable()`
- `generateTransformAI()`
- `handleDryRun()`
- `handleExecute()`
- `startPolling()`
- `stopPolling()`
- `buildExtractDatasets()`
- `savePipelineName()`
- `syncPipeline()`
- `continuePreviewSync()`
- `openSyncConfig()`
- `saveSyncConfig()`
- `editPipeline()`
- `handleSaveConfigOnly()`
- `saveAllRelationships()`

### How the page talks to the backend

Connection stage:

- `etlConnect()`

Preview stage:

- `etlPreviewTable()`

Script generation stage:

- `etlGenerateTransform()`

Dry run stage:

- `etlDryRun()`

Execution stage:

- `etlExecuteJob()`
- `etlJobStatus()`

Pipeline management:

- `etlGetConnectionJobs()`
- `etlDeltaSync()`
- `etlUpdateSyncConfig()`
- `etlGetJobDetail()`
- `etlUpdateJob()`

### Why this module matters

This page is the frontend bridge from raw source systems to the newer workspace analytics model.

---

## Workspace Home And Catalog Module

This module introduces and shapes the workspace-centric product.

### Files involved

- `excel-ai-client/src/pages/workspaces/index.vue`
- `excel-ai-client/src/pages/workspaces/catalog/index.vue`
- `excel-ai-client/src/services/workspaceApi.ts`

### `pages/workspaces/index.vue`

Responsibilities:

- list workspaces
- search workspaces
- create workspaces
- update workspace metadata
- delete workspaces
- navigate to ETL using workspace context

Key functions:

- `fetchWorkspaces()`
- `handleCreateWorkspace()`
- `openEditModal()`
- `handleUpdateWorkspace()`
- `handleDeleteWorkspace()`
- `navigateToEtl()`
- `copySchemaName()`

This page is the workspace entry directory.

### `pages/workspaces/catalog/index.vue`

Responsibilities:

- show workspace tables and columns
- show semantic layer
- manage relationships
- trigger profiling
- edit table and column descriptions
- create and delete semantic metrics
- create and delete semantic dimensions
- create and delete synonyms

Key functions:

- `fetchDetails()`
- `fetchSemanticLayer()`
- `toggleTable()`
- `handleProfileWorkspace()`
- `startEdit()`
- `saveTableDescription()`
- `saveColumnDescription()`
- `fetchRelationships()`
- `createRelationship()`
- `deleteRelationship()`
- `createMetric()`
- `deleteMetric()`
- `createDimension()`
- `deleteDimension()`
- `createSynonym()`
- `deleteSynonym()`

### Why this module matters

This is the frontend layer where technical source data becomes business-defined workspace data.

---

## Workspace Chat Module

This module provides the conversational workspace experience.

### Files involved

- `excel-ai-client/src/pages/workspaces/chat/index.vue`
- `excel-ai-client/src/services/workspaceApi.ts`

### Responsibilities

- load workspace info
- load chat history
- send natural language questions
- render markdown explanations
- render returned tables or KPI-style results
- pin useful chat results to dashboard
- clear workspace chat history

### Key functions

- `fetchWorkspace()`
- `scrollToBottom()`
- `renderMarkdown()`
- `copyToClipboard()`
- `adjustTextareaHeight()`
- `sendMessage()`
- `openPinModal()`
- `handlePinToDashboard()`
- `loadChatHistory()`
- `clearChatHistory()`

### How the screen works

1. on mount, load workspace and prior chat history
2. user sends a message
3. page appends optimistic user message
4. `workspaceApi.workspaceChat()` is called
5. response is rendered as assistant explanation plus structured result
6. if result is useful, user can pin it to the dashboard

### Why this module matters

This is the simplest and most approachable UI for the workspace intelligence engine.

---

## Workspace Report Module

This module is the report-generation surface for workspace data.

### Files involved

- `excel-ai-client/src/pages/workspaces/report/index.vue`
- `excel-ai-client/src/services/workspaceApi.ts`

### Responsibilities

- allow AI mode or custom SQL mode
- generate report results
- render tabular output
- generate AI summary over returned data
- load historical report executions
- rerun historical reports
- download CSV
- share report snapshots

### Key functions

- `fetchWorkspace()`
- `fetchHistory()`
- `getTitleForHistory()`
- `cleanQuestionForInput()`
- `loadHistoricalReport()`
- `runHistoricalReport()`
- `generateReport()`
- `downloadCSV()`
- `forwardToAIReport()`
- `deleteHistoricalReport()`
- `clearAllHistory()`
- `resetReport()`
- `openShareModal()`
- `shareThisReport()`
- `copyShareLink()`

### Flow

AI report path:

1. user writes natural language request
2. page calls `workspaceChat()`
3. SQL-backed result is returned
4. page can optionally call `summarizeReport()` for AI narrative

Custom SQL path:

1. user writes SQL
2. page calls `executeCustomSql()`
3. result is rendered and stored in report history

### Why this module matters

It turns workspace analysis into reusable reporting, not just one-off chat answers.

---

## Workspace Dashboard Module

This module is the newer dashboard layer for workspaces.

### Files involved

- `excel-ai-client/src/pages/workspaces/dashboard/index.vue`
- `excel-ai-client/src/services/workspaceApi.ts`
- `excel-ai-client/src/components/dashboard/*`

### Responsibilities

- load or stream workspace dashboard
- render widgets
- support slicers and filter-driven refresh
- create widgets from natural language
- create widgets from custom SQL
- open chart builder
- apply themes and dashboard design adjustments
- refresh existing widgets
- save layout state

### Key functions

- `toggleSidebar()`
- `onSlicerChange()`
- `clearSlicers()`
- `refreshAllWidgets()`
- `changeTheme()`
- `handleWidgetStyleUpdate()`
- `handleDashboardDesignUpdate()`

The page combines:

- GridStack layout behavior
- ECharts rendering
- toolbar and side properties
- schema-driven chart building

### How it talks to the backend

- `getDashboard()`
- `streamDashboard()`
- `saveDashboard()`
- `pinWidget()`
- `unpinWidget()`
- `refreshWidget()`
- `generateWidget()`
- `createCustomWidget()`
- `getChartSchema()`
- `generateCustomChart()`
- history and share helpers where relevant

### Why this module matters

It is the visual persistence layer of the workspace system, just as `SmartDashboard.vue` is for the legacy file system.

---

## Shared Workspace And Shared Report Module

This module exposes public or read-only views for tokenized shared assets.

### Files involved

- `excel-ai-client/src/pages/workspaces/shared/SharedWorkspaceDashboard.vue`
- `excel-ai-client/src/pages/workspaces/shared/SharedWorkspaceChat.vue`
- `excel-ai-client/src/pages/workspaces/shared/SharedWorkspaceReport.vue`
- `excel-ai-client/src/pages/workspaces/shared/SharedReportView.vue`
- `excel-ai-client/src/services/workspaceApi.ts`

### Responsibilities

- render shared dashboards without edit controls
- allow restricted shared chat
- render shared report snapshots
- support public access using share tokens

### Service calls used

- `getSharedWorkspaceDashboard()`
- `sharedWorkspaceChat()`
- `sharedReportChat()`
- `sharedReportSql()`
- `sharedReportSummarize()`
- `getSharedReport()`

### Why this module matters

It creates a safe presentation layer for external or cross-team consumption without exposing full workspace editing.

---

## Layout And Structural UI Module

These components create reusable page structure rather than owning business logic.

### Files involved

- `excel-ai-client/src/components/Layout/Sidebar.vue`
- `excel-ai-client/src/components/Layout/SidebarLinks.vue`
- `excel-ai-client/src/components/Layout/TopNavbar.vue`
- `excel-ai-client/src/pages/layout/AuthLayout.vue`
- `excel-ai-client/src/components/Layout/main/AuthLayout.vue`

### Responsibilities

- sidebar navigation
- top navigation
- authenticated shell
- auth-specific blank layout

These components matter because they make route transitions feel like one coherent product instead of disconnected screens.

---

## Dashboard-Specific Reusable Component Module

These components are feature-aware and are reused across dashboard screens.

### Files involved

- `src/components/dashboard/LeftSidebar.vue`
- `src/components/dashboard/RightProperties.vue`
- `src/components/dashboard/WidgetFloatingToolbar.vue`
- `src/components/dashboard/WidgetStyleChooserModal.vue`
- `src/components/dashboard/DateRangePicker.vue`
- `src/components/dashboard/EditChart.vue`
- `src/components/dashboard/EditInsight.vue`
- `src/components/dashboard/EditKPI.vue`
- `src/components/dashboard/EditList.vue`
- `src/components/dashboard/EditSummary.vue`
- `src/components/chart/ChartViewer.vue`

### Responsibilities

- widget editing
- dashboard-level filters
- rendering charts
- side property panels
- per-widget action controls

These are not generic UI atoms. They are dashboard feature components.

---

## Generic UI Primitive Module

The `src/components/ui/*` directory contains reusable presentational building blocks:

- alerts
- buttons
- dialogs
- dropdowns
- inputs
- tabs
- select controls
- tables
- sheets
- popovers
- calendars
- charts wrappers

These components generally do not contain product workflow logic. They provide styling and consistent behavior for higher-level screens.

Use them as supporting infrastructure, not as the starting point for understanding business features.

---

## Non-Core Or Secondary UI Areas

The repo also includes several UI groups that are less central to the current analytics workflow:

- `components/playground/*`
- `components/music/*`
- `components/mails/*`
- `components/card/*`
- `components/form/*`
- `components/data/*`

These are useful as:

- demos
- design references
- generic UI examples
- supporting settings/account surfaces

But they are not the best place to start when learning the main analytics product.

---

## Best Read Order By Frontend Goal

### If you want to understand the full app structure

1. `src/main.ts`
2. `src/router/router.ts`
3. `src/services/excelApi.ts`
4. `src/services/workspaceApi.ts`
5. `src/store/login.ts`

### If you want to understand the file-centric product

1. `src/store/documents.ts`
2. `src/utils/fileTree.ts`
3. `src/pages/documents/index.vue`
4. `src/pages/dashboard/SmartDashboard.vue`
5. `src/store/boards.ts`

### If you want to understand ETL

1. `src/pages/etl/index.vue`
2. `src/services/excelApi.ts`

### If you want to understand workspace product flow

1. `src/pages/workspaces/index.vue`
2. `src/pages/workspaces/catalog/index.vue`
3. `src/pages/workspaces/chat/index.vue`
4. `src/pages/workspaces/report/index.vue`
5. `src/pages/workspaces/dashboard/index.vue`
6. `src/services/workspaceApi.ts`

### If you want to understand shared/public experiences

1. `src/router/router.ts`
2. `src/pages/workspaces/shared/*`
3. `src/pages/dashboard/SmartDashboard.vue`

---

## Final Mental Model

The frontend is easiest to understand if you group it like this:

- `main.ts` and `router.ts` define the app shell and route map
- `excelApi.ts` powers the older file/project/board/dashboard product
- `workspaceApi.ts` powers the newer workspace/chat/report/dashboard product
- `documents/index.vue` is the operating console for uploaded files
- `SmartDashboard.vue` is the studio for file dashboards, boards, compare mode, and sharing
- `etl/index.vue` is the bridge from source databases into analytical workspaces
- `workspaces/*` pages are the structured analytics product built on top of curated data

That is the real frontend architecture in working terms.

