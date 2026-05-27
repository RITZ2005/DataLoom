# Frontend Architecture Report — `excel-ai-client`

## Tech Stack & Libraries

| Area | Stack / Libraries |
|---|---|
| Core Framework | Vue 3, Vite, TypeScript |
| UI Component Library | `shadcn-vue`, Tailwind CSS |
| State Management | Pinia (implied via standard Vue 3 stack) |
| Routing | Vue Router |
| Charts & Visualization | Recharts / ECharts / Highcharts (Wrapped in `ChartViewer.vue`) |
| Icons | Lucide Vue |
| Styling | Tailwind CSS, PostCSS, SCSS |

## Project Structure

```text
excel-ai-client/
├── public/                 # Static assets
├── src/                    # Main application source code
│   ├── assets/             # Images, global stylesheets, fonts
│   ├── components/         # Reusable Vue components (Atoms, Molecules, Organisms)
│   │   ├── auth/           # Authentication related components
│   │   ├── card/           # Generic data display cards
│   │   ├── chart/          # Chart rendering engines and wrappers
│   │   ├── dashboard/      # Specific dashboard UI widgets and sidebars
│   │   ├── form/           # Reusable form components
│   │   ├── Layout/         # Global layouts (Sidebar, Navbars)
│   │   ├── ui/             # Core shadcn-vue base components (buttons, dialogs, inputs)
│   │   └── ...             # Other feature modules (projects, playground, etc.)
│   ├── lang/               # Internationalization / Locales
│   ├── lib/                # Utility scripts, external library configurations
│   ├── pages/              # Vue Router view components (Page level)
│   │   ├── dashboard/      # Primary analytical dashboards
│   │   ├── documents/      # File system and file management views
│   │   ├── etl/            # ETL pipeline configuration views
│   │   ├── workspaces/     # Multi-tenant workspace suite (chat, report, dashboard, catalog)
│   │   └── ...             # Core pages (login, register, index)
│   ├── plugins/            # Vue plugins initialization
│   ├── router/             # Vue Router configuration
│   ├── services/           # API integration and HTTP clients (Axios/Fetch wrappers)
│   ├── store/              # Pinia state management modules
│   └── utils/              # Helper functions and formatters
├── vite.config.ts          # Vite build configuration
├── tailwind.config.js      # Tailwind utility class definitions
└── components.json         # UI component generator config
```

---

## Complete Component Reference (Hierarchical)

> **Directory Structure:** `src/components/` -> `Folder` -> `Component.vue`

### Folder: `dashboard/`
**Description:** Contains all complex organisms and widgets used to construct the interactive analytical dashboards.

1. **`ChartViewer.vue`** (Located in `chart/`)
   - **Role:** The core rendering engine for all data visualizations. Takes high-level chart configurations (e.g., bar, line, pie) and renders them using the underlying charting library.
   - **Key Responsibilities:** Handling responsiveness, tooltip generation, color mapping, and dataset binding.

2. **`DateRangePicker.vue`**
   - **Role:** Allows users to filter dashboard data globally based on start and end dates.

3. **`EditChart.vue`** / **`EditInsight.vue`** / **`EditKPI.vue`** / **`EditList.vue`** / **`EditSummary.vue`**
   - **Role:** Configuration modals or side-panels for editing specific widget types.
   - **Key Responsibilities:** Updating title, changing chart dimensions/measures, adjusting aggregations, and saving the updated widget schema back to the backend.

4. **`LeftSidebar.vue`** & **`RightProperties.vue`**
   - **Role:** Structural dashboard components. `LeftSidebar` handles navigation between different dashboards or datasets, while `RightProperties` shows context-sensitive settings for the currently selected widget.

5. **`WidgetFloatingToolbar.vue`**
   - **Role:** A hovering action bar that appears when a user focuses on a specific widget, providing quick access to actions like Edit, Duplicate, Delete, or Fullscreen.

6. **`WidgetStyleChooserModal.vue`**
   - **Role:** Allows users to quickly change the aesthetic style of a widget (e.g., from a Pie Chart to a Donut Chart, or modifying color palettes).

7. **`ERDWidget.vue`**
   - **Role:** Specialized widget for rendering Entity-Relationship Diagrams, likely used to visualize the database schema or ETL pipeline relationships.

### Folder: `Layout/`
**Description:** Defines the global structural skeletons of the application.

1. **`Sidebar.vue` & `SidebarLinks.vue`**
   - **Role:** The main vertical navigation menu, persistent across authenticated routes. Contains routing links to Workspaces, Documents, ETL, etc.

2. **`TopNavbar.vue`**
   - **Role:** The horizontal top bar containing global search, user profile dropdown (`UserNav.vue`), notifications, and environment toggles.

3. **`AuthLayout.vue`**
   - **Role:** A specialized blank-canvas layout used exclusively for authentication pages (Login/Register), removing the sidebar and top navigation.

### Folder: `auth/` & `login/`
**Description:** Components specific to handling authentication flows, user authorization, and registration logic.

1. **`AuthForm.vue`**
   - **Role:** Handles the core business logic and UI for generic authentication steps (often shared between login and registration).

2. **`UserAuthForm.vue`** (Located in `login/`)
   - **Role:** The primary form used on the `/login` route. Handles credential inputs, validation, and dispatches the login action to the API via Pinia stores.
   - **Key Responsibilities:** Managing loading states, displaying field-level validation errors, and handling OAuth or third-party sign-ins if applicable.

3. **`ChangePasswordModal.vue`** (Root components dir)
   - **Role:** A global modal that can be triggered from anywhere (usually the profile dropdown) to allow the user to change their current password. Uses `POST /api/auth/change-password`.

### Folder: `card/`
**Description:** A collection of highly reusable, styled card components used across different dashboards and settings pages to display encapsulated data.

1. **`Container.vue`**
   - **Role:** A generic wrapper component providing consistent padding, borders, and shadowing for block content.
2. **`CookieSettings.vue` / `PaymentMethod.vue` / `Notifications.vue`**
   - **Role:** Presentation-level cards for specific user account settings, often nested inside `FormsLayout.vue`.
3. **`CreateAccount.vue` / `GitHubCard.vue`**
   - **Role:** Specific card instances used within the authentication or integrations view.
4. **`DatePicker.vue`**
   - **Role:** A card-based inline date selector, wrapping the core UI calendar component.
5. **`ReportAnIssue.vue` / `ShareDocument.vue` / `TeamMembers.vue`**
   - **Role:** Specific action cards used in workspaces or document views to handle reporting bugs, modifying file sharing permissions, and managing team access.

### Folder: `form/` & `formLayout/`
**Description:** Centralized location for structured data-entry forms.

1. **`ProfileForm.vue` / `AccountForm.vue` / `AppearanceForm.vue`**
   - **Role:** Settings panels for user management. Maps directly to the `/api/auth/me` and `/api/auth/change-password` backend routes.

2. **`DateRangeForm.vue` / `DisplayForm.vue` / `NotificationsForm.vue`**
   - **Role:** Handlers for workspace-level or global preferences, managing the data binding between the UI and local storage / API.

3. **`SidebarNav.vue`** & **`FormsLayout.vue`**
   - **Role:** A wrapper component that provides a consistent layout with a sidebar (`SidebarNav.vue`) for complex multi-page settings interfaces.

### Folder: `playground/` & `music/` & `mails/`
**Description:** Example or sandbox components often used for testing new UI paradigms, demonstrating component libraries, or acting as template bases for new features.

1. **`ModelSelector.vue` / `TemperatureSelector.vue` / `TopPSelector.vue`** (Located in `playground/`)
   - **Role:** Controls for adjusting LLM generation parameters, used if the application provides a raw prompt playground.
2. **`CodeViewer.vue` / `PresetSelector.vue`**
   - **Role:** Components for displaying raw API requests/responses or SQL queries, and selecting saved prompt templates.

### Folder: `projects/`
**Description:** Components specific to project and dataset collaboration.

1. **`CollaboratorsCell.vue`**
   - **Role:** Renders a list of user avatars or a management interface for users who have access to a specific shared project/workspace.
2. **`BugIcon.vue`**
   - **Role:** Specialized SVG/icon wrapper for indicating tracking or bug statuses within project tables.

### Folder: `ui/`
**Description:** Shadcn-vue base components. These are dumb, presentational components with no business logic.
- **Components:** `Accordion`, `Alert`, `Button`, `Dialog`, `DropdownMenu`, `Input`, `Select`, `Table`, `Tabs`, `Tooltip`, etc.
- **Key Responsibilities:** Maintaining visual consistency across the app utilizing Tailwind classes.

---

## Pages & Routing Reference

> **Directory Structure:** `src/pages/` -> `ViewComponent.vue`

### Core Workspaces Module (`src/pages/workspaces/`)
**Description:** The heart of the Tri-Agent system, where users interact with their data workspaces.

1. **`index.vue`**
   - **Role:** Lists all available workspaces for the user. Interacts with `GET /api/workspaces`.

2. **`dashboard/index.vue`**
   - **Role:** The interactive workspace dashboard view. Fetches the saved layout and renders the `ChartViewer.vue` widgets based on the `WorkspaceSqlAgent` output.

3. **`chat/index.vue`**
   - **Role:** Conversational interface for natural language querying. Integrates streaming text output and data table rendering. Interacts with `POST /api/workspaces/{id}/chat`.

4. **`report/index.vue`**
   - **Role:** Detailed reporting view, likely showing generated AI summaries alongside complex data tables and charts.

5. **`catalog/index.vue`**
   - **Role:** Semantic layer management. Allows users to view, define, and modify Dimensions, Metrics, and Synonyms for the workspace. Interacts with `GET /api/workspaces/{id}/semantic`.

### Shared Workspaces (`src/pages/workspaces/shared/`)
**Description:** Public-facing, read-only views for workspaces shared via the `langfuse_share.py` backend endpoints.

1. **`SharedWorkspaceDashboard.vue` / `SharedWorkspaceReport.vue`**
   - **Role:** Renders the dashboard/report but strips out all editing capabilities (no floating toolbars, no property sidebars). Uses `GET /api/share/workspace/{token}`.

2. **`SharedWorkspaceChat.vue`**
   - **Role:** A restricted conversational interface allowing external users to query the shared workspace context without modifying the core dataset.

### Documents & File Management (`src/pages/documents/`)
**Description:** File browser interface mapping to the `/api/files` backend router.

1. **`index.vue`**
   - **Role:** The main file explorer grid/list view. Handles file uploads, drag-and-drop movement, and folder navigation.

2. **`FileSystemNode.vue`**
   - **Role:** A recursive component representing a single folder or file in the document tree hierarchy.

3. **`FilterPopover.vue`**
   - **Role:** Advanced filtering UI (by date, type, tags, favorites) for large document repositories.

### ETL Pipeline Module (`src/pages/etl/`)
**Description:** Interface for configuring data extraction and transformation jobs.

1. **`index.vue`**
   - **Role:** Dashboard for monitoring ETL job status, configuring new database connections, and triggering manual syncs. Interacts heavily with `app/routers/etl.py`.

### Authentication (`src/pages/login/` & `src/pages/register/`)
**Description:** User onboarding flows.

1. **`login/index.vue` & `register/index.vue`**
   - **Role:** Integrates `UserAuthForm.vue` to capture credentials, dispatch login actions to Pinia, store JWT tokens in `localStorage`/cookies, and redirect to the dashboard.
