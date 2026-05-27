# Frontend State Management & API Flow Architecture

## Overview
This document outlines how the Vue 3 (`excel-ai-client`) application manages data, maintains synchronized state with the FastAPI backend, and handles complex asynchronous flows like conversational streams and file uploads.

---

## 1. Global State Management (Pinia)
The application relies on **Pinia** stores (located in `src/store/`) for cross-component reactivity and persistent state.

### Key Stores
1. **`authStore`:**
   - **State:** Holds the current user's `JWT Token`, `Profile Info` (name, email, role), and `langfuse_enabled` flag.
   - **Persistence:** Syncs the JWT token to `localStorage`/cookies to persist sessions across page reloads.
   - **Flow:** Dispatches actions to `/api/auth/login`. On success, updates the state and redirects to the dashboard via Vue Router.
   
2. **`workspaceStore`:**
   - **State:** Maintains the `active_workspace_id`, the list of available workspaces, and the current catalog state (dimensions/metrics).
   - **Responsibility:** Ensures that when a user switches workspaces in the `LeftSidebar`, all dashboard widgets and chat interfaces reactively fetch the context for the new workspace.

3. **`dashboardStore`:**
   - **State:** Holds the structural schema of the current dashboard (layout grid positions, widget definitions, chart types).
   - **Flow:** When a widget is resized or modified in `EditChart.vue`, this store updates immediately (optimistic UI update) and debounces a `POST /api/projects/{id}/dashboard/save` call to the backend.

---

## 2. API Communication Layer
All API interactions go through a centralized Axios/Fetch wrapper service (`src/services/`).

### A. HTTP Interceptors
- **Request Interceptor:** Automatically attaches the `Authorization: Bearer <token>` header to all outgoing requests.
- **Response Interceptor:** Catches `401 Unauthorized` responses globally to trigger a logout flow and redirect the user back to the `/login` page.

### B. Server-Sent Events (SSE) & Streaming
To provide a fast, conversational UX, the application handles real-time data streams.
- **Chat Streaming:** When querying `/api/workspaces/{id}/chat`, the backend streams chunks of markdown. The frontend accumulates these chunks into a reactive string, updating the chat UI byte-by-byte for a "typing" effect.
- **Progress Tracking:** For large ETL jobs or file uploads, the client listens to `/api/files/upload-progress` using the browser's `EventSource` API, updating a reactive progress bar (0-100%).

---

## 3. Component Data Flow (The Vue lifecycle)

### Example: Loading the Workspace Dashboard
1. **Routing (`vue-router`):** User navigates to `/workspaces/dashboard`.
2. **Setup/Mounted (`onMounted`):** The `dashboard/index.vue` page component triggers an action in the `workspaceStore` to fetch the workspace details.
3. **API Call:** Service layer calls `GET /api/workspaces/{id}`.
4. **State Update:** `workspaceStore` updates, triggering a re-render.
5. **Prop Drilling:** The page component iterates over the dashboard layout array and passes individual widget configurations as `props` to instances of `ChartViewer.vue`.
6. **Local State:** `ChartViewer.vue` handles its own local reactivity (e.g., hovering over a bar chart shows a tooltip) without polluting the global Pinia store.

---

## 4. Shared Public State (Langfuse & Public Dashboards)
When accessing a shared dashboard (`src/pages/workspaces/shared/`), the state flow is slightly modified to ensure security:
- **No JWT Required:** The `authStore` is bypassed.
- **Token-Based Auth:** The URL contains a specific `{token}`. The API service injects this token into requests directed at `/api/share/...`.
- **Read-Only Mode:** Pinia stores lock down mutation actions (like saving layouts or editing metrics) based on the presence of the share token.
