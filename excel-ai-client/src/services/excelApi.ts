import axios, { type AxiosInstance } from 'axios'

// API Configuration
const API_BASE_URL = import.meta.env.VITE_API_URL || ''

// Create axios instance for Excel API
export const excelApiClient: AxiosInstance = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
  timeout: 300000, // 5 minutes
})

// Request interceptor
excelApiClient.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('user-token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => Promise.reject(error)
)

// Response interceptor for error handling
excelApiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      console.warn('Unauthorized response received')
      // Redirect to login only if not already on the login page
      if (!window.location.hash.includes('/login') && !window.location.hash.includes('/register')) {
        localStorage.removeItem('user-token')
        window.location.hash = '/login'
      }
    }

    if (error.code === 'ERR_NETWORK' || error.message === 'Network Error') {
      console.error('Backend Connection Error:', {
        message: error.message,
        baseURL: API_BASE_URL,
        url: error.config?.url
      })
    }

    return Promise.reject(error)
  }
)

// ============================================================================
// TYPES
// ============================================================================

export interface ETLDatasetTable {
  table_id: string
  table_name: string
  source_name?: string
  row_count?: number
  column_stats?: any
  created_at?: string
}

export interface ETLDatasetJob {
  job_id: string
  status: string
  started_at?: string
  completed_at?: string
  tables: ETLDatasetTable[]
  primary_keys?: string[]
}

export interface ETLDatasetConnection {
  connection_id: string
  name: string
  db_type: string
  database_name?: string
  jobs: ETLDatasetJob[]
}

export interface ETLDatasetListResponse {
  connections: ETLDatasetConnection[]
}

export interface FileInfo {
  file_uuid: string
  filename: string
  table_name: string
  total_rows: number
  columns: string[]
  column_stats: Record<string, any>
  created_on?: string
  deleted_at?: string
  project_id?: string
  subproject_id?: string
  is_pinned?: boolean
  is_favorite?: boolean
  tags?: string[]
  file_group_id?: string
  sheet_name?: string
}

export interface UploadRawResponse {
  temp_id: string
  filename: string
  sheets: string[]
}

export interface ExtractSheetRequest {
  temp_id: string
  sheet_name: string
  existing_group_id?: string
  project_id?: string
  subproject_id?: string
}

export interface SubprojectInfo {
  subproject_id: string
  project_id: string
  name: string
  created_on?: string
  file_count?: number
}

export interface ProjectInfo {
  project_id: string
  name: string
  created_on?: string
  subprojects?: SubprojectInfo[]
  file_count?: number
  color?: string
  is_dashboard?: boolean
  active_file_uuid?: string
  is_shared?: boolean
  share_token?: string
}

/** Minimal project info returned by the project-dashboard endpoint */
export interface ProjectDashboardProject {
  project_id: string
  name: string
  created_on?: string
  color?: string
  is_dashboard?: boolean
  active_file_uuid?: string
  is_shared?: boolean
  share_token?: string
  screen_share_tokens?: Record<string, string>
  published_file_uuid?: string
}

/** Minimal file info returned by the project-dashboard endpoint */
export interface ProjectDashboardFile {
  file_uuid: string
  filename: string
  table_name?: string
  total_rows: number
  created_on?: string
}

/** Insight Board info */
export interface BoardInfo {
  board_id: string
  name: string
  created_on?: string
  active_file_uuid?: string
  is_shared?: boolean
  share_token?: string
  screen_share_tokens?: Record<string, string>
  file_count?: number
}

export interface BoardFileInfo {
  file_uuid: string
  filename: string
  table_name?: string
  total_rows: number
  created_on?: string
  columns?: string[]
  column_stats?: Record<string, any>
}

export interface BoardScreenState {
  id: string
  name: string
}

export interface BoardDashboardSaveRequest {
  widgets: DashboardWidget[]
  [key: string]: any
  thumbnail_version?: number
  screens?: BoardScreenState[]
  active_screen_id?: string
  active_theme?: string
  screen_widgets?: Record<string, DashboardWidget[]>
  file_screen_widgets?: Record<string, Record<string, DashboardWidget[]>>
  file_screen_needs_generation?: Record<string, Record<string, boolean>>
  file_screen_pending_templates?: Record<string, Record<string, DashboardWidget[]>>
  screen_thumbnails?: Record<string, string>
  file_screen_thumbnails?: Record<string, Record<string, string>>
  design?: {
    texture?: 'none' | 'dots' | 'grid' | 'gradient'
    density?: 'compact' | 'cozy' | 'airy'
    cardStyle?: 'flat' | 'soft' | 'glass'
  }
}

export interface UploadResponse {
  status: string
  message: string
  file_uuid: string  // NEW: UUID from backend
  filename: string
  table_name: string
  rows: number
  columns: string[]
}

export interface QueryRequest {
  file_uuid?: string  // NEW: Preferred identifier
  filename?: string   // Legacy fallback
  query: string
  use_cache?: boolean
  session_id?: string
  source_type?: 'file' | 'database'
}

export interface QueryResponse {
  status: string
  data: string
  query_type: string
  cache_hit?: boolean
  trace_id?: string | null
  trace_url?: string | null
  session_id?: string | null
  session_url?: string | null
}

export interface ChunkData {
  chunks: { row_index: number; content: string; data?: Record<string, any> }[]
  columns?: string[]
  total_rows: number
  total_pages: number
  page: number
  limit: number
}

export interface PreviewResponse {
  status: string
  filename: string
  total_rows: number
  preview_rows: number
  columns: string[]
  data: Record<string, any>[]
}

export interface ExportResponse {
  status: string
  format: string
  data: string | Record<string, any>[]
}

export interface WidgetGenerationHints {
  widget_type_hint?: string
  chart_type_hint?: string
  filter_context_hint?: Record<string, any>
}

export interface CacheDeleteResponse {
  status: string
  message: string
  file_uuid: string
  deleted: number
}

export interface ChatHistoryMessage {
  id: number
  file_uuid?: string
  role: string
  content: string
  query_type?: string
  cache_hit?: boolean
  response_time?: number
  metadata?: Record<string, any>
  created_at: string
}

export interface CategoryItem {
  name: string
  question_count: number
  is_default: boolean
}

export interface SavedQuestion {
  id: number
  question_text: string
  question_category: string
  scope_level: 'ROOT' | 'PROJECT' | 'SUBPROJECT'
  scope_id: string | null
  created_at: string
}

export interface BatchQueryResultItem {
  question: string
  status: 'success' | 'error'
  data?: string
  query_type?: string
  error?: string
  trace_id?: string
  trace_url?: string
}

export interface BatchQueryResponse {
  status: string
  file_uuid: string
  results: BatchQueryResultItem[]
  total: number
  successful: number
  failed: number
}

// ============================================================================
// DASHBOARD TYPES
// ============================================================================

export interface DashboardWidgetKpi {
  id: string
  type: 'kpi'
  title: string
  value: string
  subtitle?: string
  trend?: 'positive' | 'negative' | 'neutral'
  icon?: string
  origin_query?: string
  filter_context?: Record<string, any>
  gridW: number
  gridH: number
  gridX?: number
  gridY?: number
}

export interface DashboardWidgetInsight {
  id: string
  type: 'insight'
  title: string
  text: string
  highlight?: string
  icon?: string
  origin_query?: string
  filter_context?: Record<string, any>
  gridW: number
  gridH: number
  gridX?: number
  gridY?: number
}

export interface DashboardWidgetList {
  id: string
  type: 'list'
  title: string
  items: { label: string; value: string }[]
  icon?: string
  origin_query?: string
  filter_context?: Record<string, any>
  gridW: number
  gridH: number
  gridX?: number
  gridY?: number
}

export interface DashboardWidgetChart {
  id: string
  type: 'chart'
  title: string
  chartType: 'bar' | 'pie' | 'line' | 'area' | 'donut' | 'doughnut' | 'scatter' | 'polarArea' | 'combo' | 'bubble' | 'histogram' | 'funnel' | 'gauge' | 'heatmap' | 'treemap' | 'waterfall'
  chartData?: {
    labels: string[]
    series: any[] // Array of {name, data} for bar/line/area OR flat number[] for pie/donut
  }
  horizontal?: boolean
  colorTheme?: 'indigo' | 'violet' | 'emerald' | 'amber' | 'rose' | 'cyan' | 'mokkup1' | 'holidaySpark' | 'mokkup2' | 'rustic'
  icon?: string
  origin_query?: string
  filter_context?: Record<string, any>
  gridW: number
  gridH: number
  gridX?: number
  gridY?: number
}

export interface DashboardWidgetSummary {
  id: string
  type: 'summary'
  title: string
  text: string
  icon?: string
  origin_query?: string
  filter_context?: Record<string, any>
  gridW: number
  gridH: number
  gridX?: number
  gridY?: number
}

export type DashboardWidget = DashboardWidgetKpi | DashboardWidgetInsight | DashboardWidgetList | DashboardWidgetChart | DashboardWidgetSummary

// ── Fingerprint types (semantic data model from backend) ──
export interface FingerprintMeasure {
  col: string
  agg: 'sum' | 'mean' | 'count'
  format_hint: 'currency' | 'percentage' | 'number'
}

export interface FingerprintDimension {
  col: string
  cardinality: number
  dim_type: 'geographic' | 'product' | 'time_dimension' | 'categorical'
  top_values: Record<string, number>
}

export interface FingerprintTimeIntelligence {
  primary_date?: string
  has_yoy?: boolean
  has_mom?: boolean
  has_qoq?: boolean
  has_ytd?: boolean
  suggested_grain?: string
  date_range?: string
  mom_growth?: number
  mom_measure?: string
  yoy_growth?: number
}

export interface DashboardFingerprint {
  measures: FingerprintMeasure[]
  dimensions: FingerprintDimension[]
  time_intelligence: FingerprintTimeIntelligence
  data_quality: {
    completeness: number
    total_nulls: number
    total_cells: number
    duplicate_rows: number
  }
}

export interface DashboardSummary {
  filename: string
  stats?: string
  insight?: string
}

export interface DashboardResponse {
  status: string
  filename: string
  file_uuid: string
  total_rows: number
  total_columns: number
  widgets: DashboardWidget[]
  fingerprint?: DashboardFingerprint
  summary?: DashboardSummary
  cache_hit?: boolean
  trace_id?: string
  trace_url?: string
}

export interface WidgetResponse {
  status: string
  widget: DashboardWidget
  trace_id?: string
  trace_url?: string
}

export interface DualWidgetResponse {
  status: string
  dual: true
  base_widget: DashboardWidget
  compare_widget: DashboardWidget
  trace_id?: string
  trace_url?: string
}

export interface UnifiedCompareResponse {
  status: string
  view: 'unified'
  base_filename: string
  compare_filename: string
  base_file_uuid: string
  compare_file_uuid: string
  total_rows_base: number
  total_rows_compare: number
  widgets: DashboardWidget[]
  fingerprint?: DashboardFingerprint
  trace_id?: string
  trace_url?: string
}

// ============================================================================
// API METHODS
// ============================================================================

const excelFileAPI = {
  getLangfuseToken: async (params?: { session_id?: string; trace_id?: string; target?: string }) => {
    const response = await excelApiClient.get('/api/langfuse-token', { params })
    return response.data
  },

  // --- File Management ---

  /**
   * Upload an Excel or CSV file with real-time embedding progress via SSE
   */
  uploadFileWithProgress: async (
    file: File,
    onProgress: (stage: string, current: number, total: number, message: string) => void,
    projectId?: string | null,
    subprojectId?: string | null
  ): Promise<UploadResponse> => {
    // Generate UUID on the client so we can subscribe to SSE before upload starts
    const fileUuid = crypto.randomUUID()

    const formData = new FormData()
    formData.append('file', file)
    formData.append('file_uuid', fileUuid)
    if (projectId) formData.append('project_id', projectId)
    if (subprojectId) formData.append('subproject_id', subprojectId)

    const token = localStorage.getItem('user-token')
    const baseUrl = API_BASE_URL || ''

    // Show initial uploading state
    onProgress('uploading', 0, 100, 'Uploading file...')

    // Subscribe to real-time SSE progress from backend
    let sseConnected = false
    const sse = new EventSource(`${baseUrl}/api/files/upload-progress/${fileUuid}`)

    const ssePromise = new Promise<void>((resolve) => {
      sse.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)
          sseConnected = true
          onProgress(data.stage, data.current, data.total, data.message)

          // SSE stream ends on complete/error
          if (data.stage === 'complete' || data.stage === 'error') {
            sse.close()
            resolve()
          }
        } catch { /* ignore parse errors */ }
      }

      sse.onerror = () => {
        // SSE may error before backend starts writing progress — that's OK,
        // we'll fall through to using the upload response directly
        sse.close()
        resolve()
      }
    })

    try {
      // Fire the upload — this blocks until backend finishes
      const response = await fetch(`${baseUrl}/api/files/upload`, {
        method: 'POST',
        headers: token ? { 'Authorization': `Bearer ${token}` } : {},
        body: formData
      })

      if (!response.ok) {
        const errorData = await response.json()
        throw new Error(errorData.detail || 'Upload failed')
      }

      const data = await response.json()

      // Wait briefly for the SSE stream to deliver the final "complete" event
      await Promise.race([
        ssePromise,
        new Promise(r => setTimeout(r, 2000))
      ])

      // Ensure UI shows 100% even if SSE missed the final event
      if (!sseConnected) {
        onProgress('complete', 100, 100, 'Upload complete!')
      }

      return data as UploadResponse

    } catch (error: any) {
      sse.close()
      onProgress('error', 0, 100, error.message || 'Upload failed')
      throw error
    }
  },

  /**
   * List all uploaded files
   */
  listETLDatasets: async (): Promise<ETLDatasetConnection[]> => {
    const response = await excelApiClient.get<ETLDatasetListResponse>('/api/etl/datasets')
    return response.data.connections || []
  },

  async getEtlDatasets(): Promise<ETLDatasetListResponse> { return (await excelApiClient.get('/api/etl/datasets')).data },

  listFiles: async () => {
    const response = await excelApiClient.get('/api/files')
    return response.data.files as FileInfo[]
  },
  /**
   * NEW: List DELETED files (Recycle Bin)
   */
  listTrashFiles: async () => {
    const response = await excelApiClient.get('/api/files/trash')
    return response.data.files as FileInfo[]
  },

  /**
   * List projects with subprojects
   */
  listProjects: async () => {
    const response = await excelApiClient.get('/api/projects')
    return response.data.projects as ProjectInfo[]
  },

  /**
   * Create a project (optionally with a color and dashboard flag)
   */
  createProject: async (name: string, color?: string, is_dashboard?: boolean, source_file_uuid?: string) => {
    const payload: any = { name }
    if (color) payload.color = color
    if (is_dashboard !== undefined) payload.is_dashboard = is_dashboard
    if (source_file_uuid) payload.source_file_uuid = source_file_uuid
    const response = await excelApiClient.post<ProjectInfo>('/api/projects', payload)
    return response.data
  },

  /**
   * NEW: Set the active file for a dashboard project
   */
  setActiveFile: async (projectId: string, fileUuid: string) => {
    const response = await excelApiClient.put(`/api/projects/${projectId}/active-file`, { file_uuid: fileUuid })
    return response.data as {
      status: string
      active_file_uuid: string
      dashboard_data: any | null
    }
  },

  /**
   * Stream project active file switch — returns NDJSON stream of individual widgets
   */
  setActiveFileStream: (projectId: string, fileUuid: string): { response: Promise<Response>; abort: () => void } => {
    const controller = new AbortController()
    const token = localStorage.getItem('user-token')
    const baseUrl = API_BASE_URL || ''
    const response = fetch(`${baseUrl}/api/projects/${projectId}/active-file-stream`, {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ file_uuid: fileUuid }),
      signal: controller.signal,
    })
    return { response, abort: () => controller.abort() }
  },

  /**
   * NEW: Toggle public sharing for a dashboard project
   */
  toggleProjectShare: async (projectId: string) => {
    const response = await excelApiClient.post(`/api/projects/${projectId}/share`)
    return response.data as { status: string; is_shared: boolean; share_token: string | null }
  },

  /**
   * NEW: Fetch a shared public dashboard
   */
  getSharedDashboard: async (token: string) => {
    const response = await excelApiClient.get(`/api/share/${token}`)
    return response.data as {
      project_id: string
      project_name: string
      color?: string
      file_uuid?: string
      dashboard_data: any
    }
  },

  /** Cross-filter a shared (public) dashboard — no auth required */
  filterSharedDashboard: async (token: string, column: string, value: string, sessionId?: string): Promise<any> => {
    const response = await excelApiClient.post(`/api/share/${token}/filter`, {
      column,
      value,
      session_id: sessionId || undefined
    }, { timeout: 60000 })
    return response.data
  },

  /**
   * NEW: Load a project's canonical dashboard (project-centric)
   */
  getProjectDashboard: async (projectId: string) => {
    const response = await excelApiClient.get(`/api/projects/${projectId}/dashboard`)
    return response.data as {
      project: ProjectDashboardProject
      files: ProjectDashboardFile[]
      dashboard_data: any
    }
  },

  /**
   * Create a subproject under a project
   */
  createSubproject: async (projectId: string, name: string) => {
    const response = await excelApiClient.post<SubprojectInfo>(`/api/projects/${projectId}/subprojects`, { name })
    return response.data
  },

  /**
   * Delete a project
   */
  deleteProject: async (projectId: string) => {
    const response = await excelApiClient.delete(`/api/projects/${projectId}`)
    return response.data
  },

  /**
   * Delete a subproject
   */
  deleteSubproject: async (projectId: string, subprojectId: string) => {
    const response = await excelApiClient.delete(`/api/projects/${projectId}/subprojects/${subprojectId}`)
    return response.data
  },

  /**
   * Get file information by UUID or filename
   * Endpoint auto-detects UUID vs filename for backward compatibility
   */
  getFileInfo: async (fileUuidOrFilename: string) => {
    const response = await excelApiClient.get(`/api/files/${fileUuidOrFilename}`)
    return response.data
  },
  /**
   * Soft Delete (Move to Trash)
   */
  deleteFile: async (fileUuidOrFilename: string) => {
    const response = await excelApiClient.delete(`/api/files/${fileUuidOrFilename}`)
    return response.data
  },
  /**
   * NEW: Restore file from Trash
   */
  restoreFile: async (fileUuid: string) => {
    const response = await excelApiClient.post(`/api/files/${fileUuid}/restore`)
    return response.data
  },

  /**
   * NEW: Permanently Delete file
   */
  permanentDeleteFile: async (fileUuid: string) => {
    const response = await excelApiClient.delete(`/api/files/${fileUuid}/permanent`)
    return response.data
  },

  /** Permanently delete all files in trash */
  emptyTrash: async (): Promise<{ status: string; message: string; deleted_count: number; errors: string[] }> => {
    const response = await excelApiClient.delete('/api/files/trash/empty')
    return response.data
  },

  /**
   * Get file preview (first N rows) by UUID or filename
   * Endpoint auto-detects UUID vs filename for backward compatibility
   */
  previewFile: async (fileUuidOrFilename: string, rows: number = 10) => {
    const response = await excelApiClient.get<PreviewResponse>(`/api/preview/${fileUuidOrFilename}`, {
      params: { rows }
    })
    return response.data
  },

  /**
   * Get paginated text chunks for a file
   */
  getFileChunks: async (fileUuid: string, page: number = 1, limit: number = 20) => {
    const response = await excelApiClient.get<ChunkData>(`/api/files/${fileUuid}/chunks`, {
      params: { page, limit }
    })
    return response.data
  },

  /**
   * Export file data by UUID or filename
   * Endpoint auto-detects UUID vs filename for backward compatibility
   */
  exportFile: async (fileUuidOrFilename: string, format: 'json' | 'csv' = 'json') => {
    const response = await excelApiClient.post<ExportResponse>(`/api/export/${fileUuidOrFilename}`, {}, {
      params: { format }
    })
    return response.data
  },

  /**
   * Delete semantic cache for a file by UUID or filename
   */
  deleteFileCache: async (fileUuidOrFilename: string) => {
    const response = await excelApiClient.delete<CacheDeleteResponse>(`/api/files/${fileUuidOrFilename}/cache`)
    return response.data
  },

  // --- Analysis ---

  /**
   * Run natural language query on file
   */
  queryFile: async (
    fileUuid: string,
    query: string,
    useCache: boolean = true,
    sessionId?: string,
    sourceType?: 'file' | 'database'
  ) => {
    const payload: any = {
      query,
      use_cache: useCache,
      file_uuid: fileUuid,
      ...(sourceType && { source_type: sourceType }),
      ...(sessionId && { session_id: sessionId })
    }

    const response = await excelApiClient.post<QueryResponse>('/api/query', payload as QueryRequest)
    return response.data
  },

  /**
   * Get one-time SSO URL for Langfuse, optionally targeting a specific session.
   */
  getLangfuseSsoUrl: async (
    sessionId?: string,
    options?: { target?: 'session' | 'traces' | 'project' }
  ): Promise<string> => {
    const params: Record<string, string> = {}
    if (sessionId) params.session_id = sessionId
    if (options?.target) params.target = options.target
    const response = await excelApiClient.get<{ sso_url?: string }>('/api/langfuse-token', {
      params: Object.keys(params).length ? params : undefined
    })
    const fallback = `${import.meta.env.VITE_API_URL || ''}/api/langfuse-sso`
    return response.data?.sso_url ?? fallback
  },

  // --- Chat History ---

  /**
   * Get chat history for a file
   */
  getChatHistory: async (fileUuid: string, limit: number = 10, offset: number = 0): Promise<ChatHistoryMessage[]> => {
    const response = await excelApiClient.get<ChatHistoryMessage[]>(`/api/chat/${fileUuid}`, {
      params: { limit, offset }
    })
    return response.data
  },

  /**
   * Save a chat message
   */
  saveChatMessage: async (fileUuid: string, message: {
    role: string
    content: string
    query_type?: string
    cache_hit?: boolean
    response_time?: number
    metadata?: Record<string, any>
  }): Promise<ChatHistoryMessage> => {
    const response = await excelApiClient.post<ChatHistoryMessage>(`/api/chat/${fileUuid}`, message)
    return response.data
  },

  /**
   * Clear chat history for a file
   */
  clearChatHistory: async (fileUuid: string) => {
    const response = await excelApiClient.delete(`/api/chat/${fileUuid}`)
    return response.data
  },

  /**
   * Soft delete a chat message (and paired question if applicable)
   */
  softDeleteChatMessage: async (fileUuid: string, messageId: number) => {
    const response = await excelApiClient.post(`/api/chat/${fileUuid}/soft_delete`, {
      message_id: messageId
    })
    return response.data
  },

  // --- Categories ---

  /**
   * List all available categories (defaults + user-created derived from saved questions)
   */
  listCategories: async (): Promise<CategoryItem[]> => {
    const response = await excelApiClient.get<CategoryItem[]>('/api/categories')
    return response.data
  },

  /**
   * Rename a category (updates all questions with that category name)
   */
  renameCategory: async (oldName: string, newName: string) => {
    const response = await excelApiClient.put('/api/categories/rename', { old_name: oldName, new_name: newName })
    return response.data
  },

  /**
   * Delete a category (recategorizes questions to Generic)
   */
  deleteCategory: async (categoryName: string) => {
    const response = await excelApiClient.delete(`/api/categories/${encodeURIComponent(categoryName)}`)
    return response.data
  },

  // --- Saved Questions (Question Categories & Auto-Replay) ---

  /**
   * Save/bookmark a question from a chat session
   */
  saveQuestion: async (questionText: string, category: string, fileUuid: string): Promise<SavedQuestion> => {
    const response = await excelApiClient.post<SavedQuestion>('/api/questions/save', {
      question_text: questionText,
      category,
      file_uuid: fileUuid
    })
    return response.data
  },

  /**
   * List all saved questions for the current user
   */
  listSavedQuestions: async (): Promise<SavedQuestion[]> => {
    const response = await excelApiClient.get<SavedQuestion[]>('/api/questions/list')
    return response.data
  },

  /**
   * List saved questions applicable to a specific file's scope
   * (root + project + subproject where relevant).
   */
  listSavedQuestionsForFile: async (fileUuid: string): Promise<SavedQuestion[]> => {
    try {
      const response = await excelApiClient.get<SavedQuestion[]>(`/api/questions/list/${fileUuid}`)
      return response.data
    } catch (error) {
      // Backward-compatible fallback: older backends may not expose scoped endpoint yet.
      if (axios.isAxiosError(error) && error.response?.status === 404) {
        const fallback = await excelApiClient.get<SavedQuestion[]>('/api/questions/list')
        return fallback.data
      }
      throw error
    }
  },

  /**
   * Delete a saved question
   */
  deleteSavedQuestion: async (questionId: number) => {
    const response = await excelApiClient.delete(`/api/questions/${questionId}`)
    return response.data
  },

  /**
   * Update a saved question's text and/or category
   */
  updateSavedQuestion: async (questionId: number, data: { question_text?: string; question_category?: string }) => {
    const response = await excelApiClient.put(`/api/questions/${questionId}`, data)
    return response.data
  },

  /**
   * Execute a batch of questions against a file (auto-replay)
   */
  batchQuery: async (fileUuid: string, questions: string[], sessionId?: string): Promise<BatchQueryResponse> => {
    const response = await excelApiClient.post<BatchQueryResponse>('/api/query/batch', {
      file_uuid: fileUuid,
      questions,
      session_id: sessionId || undefined
    })
    return response.data
  },

  // --- Hierarchical Workspace (Folders, Move, Tags, Pin, Favorite, Bulk) ---

  /** Rename or update color of a folder (project) */
  updateProject: async (projectId: string, data: { name?: string; color?: string }) => {
    const response = await excelApiClient.put(`/api/projects/${projectId}`, data)
    return response.data
  },

  /** Rename a subfolder (subproject) */
  updateSubproject: async (projectId: string, subprojectId: string, data: { name?: string }) => {
    const response = await excelApiClient.put(`/api/projects/${projectId}/subprojects/${subprojectId}`, data)
    return response.data
  },

  /** Move a file to a different folder/subfolder */
  moveFile: async (fileUuid: string, targetFolderId: string | null, targetSubfolderId: string | null = null) => {
    const response = await excelApiClient.patch(`/api/files/${fileUuid}/move`, {
      target_folder_id: targetFolderId,
      target_subfolder_id: targetSubfolderId
    })
    return response.data
  },

  /** Update file metadata (pin, favorite, tags) */
  updateFileMetadata: async (fileUuid: string, data: { is_pinned?: boolean; is_favorite?: boolean; tags?: string[] }) => {
    const response = await excelApiClient.patch(`/api/files/${fileUuid}/metadata`, data)
    return response.data
  },

  /** Bulk soft-delete files */
  bulkDeleteFiles: async (fileIds: string[]) => {
    const response = await excelApiClient.post('/api/files/bulk-delete', { file_ids: fileIds })
    return response.data
  },

  /** Bulk move files to a folder */
  bulkMoveFiles: async (fileIds: string[], targetFolderId: string | null, targetSubfolderId: string | null = null) => {
    const response = await excelApiClient.post('/api/files/bulk-move', {
      file_ids: fileIds,
      target_folder_id: targetFolderId,
      target_subfolder_id: targetSubfolderId
    })
    return response.data
  },

  // --- Smart Insights Dashboard ---

  /** Generate or load full KPI dashboard for a file */
  generateDashboard: async (
    fileUuid: string,
    regenerate: boolean = false,
    sessionId?: string,
    mode?: string,
    sourceType?: 'file' | 'database'
  ): Promise<DashboardResponse> => {
    const response = await excelApiClient.get(`/api/dashboard/${fileUuid}`, {
      params: { regenerate, session_id: sessionId || undefined, mode, source_type: sourceType },
      timeout: 120000 // 2 minutes for LLM generation
    })
    return response.data
  },

  /**
   * Generate (or regenerate) dashboard with user-defined column requirements.
   * Always performs a fresh generation — never uses cache.
   * Example requirements: "consider Salary as key metric, ignore Mobile Number, focus on Region"
   * No extra LLM call is made for parsing — pure string matching on the backend.
   */
  generateDashboardWithRequirements: async (
    fileUuid: string,
    userRequirements: string,
    sessionId?: string,
    mode?: string,
    sourceType?: 'file' | 'database'
  ): Promise<DashboardResponse> => {
    const response = await excelApiClient.post(
      `/api/dashboard/${fileUuid}/generate`,
      { user_requirements: userRequirements || null, session_id: sessionId || undefined, mode, source_type: sourceType },
      { timeout: 120000 }
    )
    return response.data
  },

  /** Update dashboard widgets after user adds/removes widgets */
  updateDashboardWidgets: async (fileUuid: string, widgets: DashboardWidget[], sessionId?: string, studio?: Record<string, any>): Promise<any> => {
    const fileId = fileUuid || ''
    const endpoint = fileId ? `/api/dashboard/${fileId}/update-widgets` : '/api/dashboard/update-widgets'
    const payload: Record<string, any> = {
      widgets,
      session_id: sessionId || undefined,
    }
    if (studio && typeof studio === 'object') {
      payload.studio = studio
    }
    const response = await excelApiClient.post(endpoint, {
      ...payload
    })
    return response.data
  },

  /** Cross-filter dashboard: re-generate widgets on filtered data */
  filterDashboard: async (
    fileUuid: string,
    column: string,
    value: string,
    sessionId?: string,
    mode?: string,
    sourceType?: 'file' | 'database'
  ): Promise<DashboardResponse> => {
    const response = await excelApiClient.post(`/api/dashboard/${fileUuid}/filter`, {
      column,
      value,
      session_id: sessionId || undefined,
      mode,
      source_type: sourceType,
    }, { timeout: 60000 })
    return response.data
  },

  /** Generate a single widget from a natural language query */
  generateWidget: async (
    fileUuid: string,
    query: string,
    compareFileId?: string,
    sessionId?: string,
    hints?: WidgetGenerationHints,
    mode?: string,
    sourceType?: 'file' | 'database'
  ): Promise<WidgetResponse | DualWidgetResponse> => {
    const payload: Record<string, any> = { query }
    if (compareFileId) payload.compare_file_id = compareFileId
    if (sessionId) payload.session_id = sessionId
    if (mode) payload.mode = mode
    if (sourceType) payload.source_type = sourceType
    if (hints?.widget_type_hint) payload.widget_type_hint = hints.widget_type_hint
    if (hints?.chart_type_hint) payload.chart_type_hint = hints.chart_type_hint
    if (hints?.filter_context_hint) {
      payload.filter_context_hint = hints.filter_context_hint as any
    }
    const response = await excelApiClient.post(`/api/dashboard/${fileUuid}/widget`, payload, {
      timeout: 120000
    })
    return response.data
  },

  /** Clone a screen template's widgets onto the selected file using switch-style blueprint regeneration */
  cloneTemplateWidgets: async (
    fileUuid: string,
    templateWidgets: DashboardWidget[],
    sessionId?: string,
    mode?: string
  ): Promise<{ status: string; widgets: DashboardWidget[]; fingerprint?: any; trace_id?: string | null; trace_url?: string | null; session_id?: string | null }> => {
    const response = await excelApiClient.post(
      `/api/dashboard/${fileUuid}/clone-template-widgets`,
      {
        template_widgets: templateWidgets,
        session_id: sessionId || undefined,
        mode
      },
      { timeout: 180000 }
    )
    return response.data
  },

  // ── Chart Builder (Looker Studio style) ──────────────────────────────────

  /** Get column schema (dimensions + measures) for the Chart Builder panel */
  getChartSchema: async (fileUuid: string, sourceType?: 'file' | 'database'): Promise<{
    status: string
    file_uuid: string
    dimensions: { col: string; cardinality: number }[]
    measures: { col: string; agg: string }[]
  }> => {
    const response = await excelApiClient.get(`/api/dashboard/${fileUuid}/schema`, {
      params: { source_type: sourceType },
    })
    return response.data
  },

  /** Generate a single chart widget interactively — no LLM, instant Pandas result */
  generateCustomChart: async (
    fileUuid: string,
    chartType: string,
    dimension: string,
    measure: string | null,
    aggregation: string = 'sum',
    mode?: string,
    sourceType?: 'file' | 'database'
  ): Promise<{ status: string; widget: DashboardWidgetChart }> => {
    const response = await excelApiClient.post(
      `/api/dashboard/${fileUuid}/chart-builder`,
      { chart_type: chartType, dimension, measure: measure || null, aggregation, mode, source_type: sourceType },
      { timeout: 15000 }
    )
    return response.data
  },

  /** Clone base-file widgets onto a target file for compare mode */
  cloneWidgets: async (baseFileId: string, targetFileId: string, sessionId?: string): Promise<DashboardResponse> => {
    const response = await excelApiClient.post('/api/dashboard/clone-widgets', {
      base_file_id: baseFileId,
      target_file_id: targetFileId,
      session_id: sessionId || undefined
    }, { timeout: 300000 })
    return response.data
  },

  /** Unified semantic comparison — merges both files into one widget set */
  generateUnifiedComparison: async (baseFileId: string, compareFileId: string, sessionId?: string): Promise<UnifiedCompareResponse> => {
    const response = await excelApiClient.post('/api/dashboard/compare-unified', {
      base_file_id: baseFileId,
      compare_file_id: compareFileId,
      session_id: sessionId || undefined
    }, { timeout: 180000 })
    return response.data
  },

  /** Save project dashboard layout (widget positions) to backend */
  saveProjectDashboard: async (projectId: string, widgets: DashboardWidget[]): Promise<{ status: string; message: string }> => {
    const response = await excelApiClient.post(`/api/projects/${projectId}/dashboard/save`, { widgets })
    return response.data
  },

  /** Change the current user's password */
  changePassword: async (currentPassword: string, newPassword: string): Promise<{ status: string; message: string }> => {
    const response = await excelApiClient.post('/api/auth/change-password', {
      current_password: currentPassword,
      new_password: newPassword
    })
    return response.data
  },

  // ── Multi-sheet upload ─────────────────────────────────────────────

  /**
   * Step 1: Upload a raw .xlsx/.xls file and receive the list of sheet names.
   * The file is held server-side under `temp_id` until extract-sheet is called.
   */
  uploadRaw: async (file: File): Promise<UploadRawResponse> => {
    const formData = new FormData()
    formData.append('file', file)
    const token = localStorage.getItem('user-token')
    const baseUrl = API_BASE_URL || ''
    const res = await fetch(`${baseUrl}/api/files/upload-raw`, {
      method: 'POST',
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      body: formData,
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Upload failed' }))
      throw new Error(err.detail || 'Upload failed')
    }
    return res.json()
  },

  /**
   * Step 2: Extract one sheet from a previously uploaded raw file.
   * Returns the new file_uuid and group_id to pass for subsequent sheets.
   */
  extractSheet: async (req: ExtractSheetRequest): Promise<{
    status: string
    file_uuid: string
    group_id: string
    sheet_name: string
    filename: string
    table_name: string
    rows: number
    columns: string[]
  }> => {
    const response = await excelApiClient.post('/api/files/extract-sheet', req)
    return response.data
  },

  /** List all file groups (parent Excel files with multiple sheets) */
  getFileGroups: async (): Promise<{ group_id: string; original_filename: string; created_at: string }[]> => {
    const response = await excelApiClient.get('/api/files/groups')
    return response.data.groups
  },

  // ── Insight Boards API ─────────────────────────────────────────

  listBoards: async () => {
    const response = await excelApiClient.get('/api/boards')
    return response.data.boards as BoardInfo[]
  },

  createBoard: async (name: string) => {
    const response = await excelApiClient.post<BoardInfo>('/api/boards', { name })
    return response.data
  },

  deleteBoard: async (boardId: string) => {
    await excelApiClient.delete(`/api/boards/${boardId}`)
  },

  getBoardDashboard: async (boardId: string) => {
    const response = await excelApiClient.get(`/api/boards/${boardId}/dashboard`)
    return response.data as {
      project: ProjectDashboardProject
      files: ProjectDashboardFile[]
      dashboard_data: any
    }
  },

  saveBoardDashboard: async (boardId: string, payload: BoardDashboardSaveRequest) => {
    const response = await excelApiClient.post(`/api/boards/${boardId}/dashboard/save`, payload)
    return response.data
  },

  uploadBoardFile: async (boardId: string, file: File) => {
    const formData = new FormData()
    formData.append('file', file)
    const response = await excelApiClient.post(`/api/boards/${boardId}/upload`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    return response.data as { status: string; file_uuid: string; filename: string; rows: number; columns: string[]; compatible: boolean; is_first_file: boolean; missing_columns: string[]; extra_columns: string[] }
  },

  switchBoardActiveFile: async (boardId: string, fileUuid: string, sessionId?: string) => {
    const response = await excelApiClient.put(`/api/boards/${boardId}/active-file`, { file_uuid: fileUuid, session_id: sessionId })
    return response.data as { status: string; active_file_uuid: string; dashboard_data: any | null }
  },

  /**
   * Stream board active file switch — returns NDJSON stream of individual widgets
   */
  switchBoardActiveFileStream: (boardId: string, fileUuid: string, sessionId?: string): { response: Promise<Response>; abort: () => void } => {
    const controller = new AbortController()
    const token = localStorage.getItem('user-token')
    const baseUrl = API_BASE_URL || ''
    const response = fetch(`${baseUrl}/api/boards/${boardId}/active-file-stream`, {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ file_uuid: fileUuid, session_id: sessionId }),
      signal: controller.signal,
    })
    return { response, abort: () => controller.abort() }
  },

  toggleBoardShare: async (boardId: string, widgets?: any[], activeScreenId?: string) => {
    const payload: Record<string, any> = {}
    if (widgets) payload.widgets = widgets
    if (activeScreenId) payload.active_screen_id = activeScreenId
    const response = await excelApiClient.post(`/api/boards/${boardId}/share`, payload)
    return response.data as {
      status: string
      is_shared: boolean
      share_token: string | null
      share_tokens_by_screen?: Record<string, string>
      active_screen_id?: string | null
      published_file_uuid: string | null
    }
  },

  publishBoard: async (boardId: string, widgets?: any[]) => {
    const response = await excelApiClient.put(`/api/boards/${boardId}/publish`, widgets ? { widgets } : {})
    return response.data as { status: string; message: string }
  },

  unpublishBoard: async (boardId: string) => {
    const response = await excelApiClient.put(`/api/boards/${boardId}/unpublish`)
    return response.data as { status: string; message: string; published_file_uuid?: string }
  },

  // ============================================================================
  // ETL PIPELINE
  etlGenerateTransform: async (prompt: string, tables: any[]) => {
    const response = await excelApiClient.post<{script: string}>('/api/etl/generate-transform', {
      prompt,
      tables
    })
    return response.data
  },
  // ============================================================================

  /**
   * Connect to an external database and get available tables
   */
  etlConnect: async (params: ETLConnectRequest) => {
    const response = await excelApiClient.post<ETLConnectResponse>('/api/etl/connect', params)
    return response.data
  },

  /**
   * Preview rows from an external database table
   */
  etlPreviewTable: async (connectionId: string, tableName: string, limit = 50) => {
    const response = await excelApiClient.post<ETLPreviewResponse>('/api/etl/preview-table', {
      connection_id: connectionId,
      table_name: tableName,
      limit,
    })
    return response.data
  },

  /**
   * Dry-run: Execute full ETL pipeline on 100 rows for preview
   */
  etlDryRun: async (
    connectionId: string,
    tableNames: string[],
    transformScript: string,
    datasets: ETLExtractDataset[] = []
  ) => {
    const response = await excelApiClient.post<ETLDryRunResponse>('/api/etl/dry-run', {
      connection_id: connectionId,
      table_names: tableNames,
      datasets,
      transform_script: transformScript,
    })
    return response.data
  },

  /**
   * Submit a full ETL pipeline job (background)
   */
  etlExecuteJob: async (
    connectionId: string,
    tableNames: string[],
    transformScript: string,
    datasets: ETLExtractDataset[] = [],
    targetTable?: string,
    pipelineName?: string,
    syncMode: string = 'overwrite',
    syncColumn?: string,
    workspaceId?: string,
    primaryKeys?: string[],
    jobId?: string
  ) => {
    const response = await excelApiClient.post<ETLJobResponse>('/api/etl/execute-job', {
      job_id: jobId,
      connection_id: connectionId,
      table_names: tableNames,
      datasets,
      transform_script: transformScript,
      target_table: targetTable,
      pipeline_name: pipelineName,
      sync_mode: syncMode,
      sync_column: syncColumn,
      workspace_id: workspaceId,
      primary_keys: primaryKeys
    })
    return response.data
  },

  etlSyncUpdate: async (
    connectionId: string,
    workspaceId: string,
    targetTableName: string,
    tableNames: string[] = [],
    datasets: ETLExtractDataset[] = [],
    transformScript?: string
  ) => {
    const response = await excelApiClient.post<{ success: boolean; loaded_tables: Record<string, any>[]; message: string }>(
      '/api/etl/sync-update',
      {
        connection_id: connectionId,
        workspace_id: workspaceId,
        target_table_name: targetTableName,
        table_names: tableNames,
        datasets,
        transform_script: transformScript,
      }
    )
    return response.data
  },

  /**
   * Delta Sync (Incremental Pull)
   */
  etlDeltaSync: async (jobId: string, syncColumn?: string, previewOnly?: boolean) => {
    const payload: Record<string, any> = {}
    if (syncColumn) payload.sync_column = syncColumn
    if (previewOnly) payload.preview_only = true
    const response = await excelApiClient.post<{
      success: boolean
      loaded_tables: Record<string, any>[]
      preview_tables?: Record<string, any>[]
      total_new_rows?: number
      requires_confirmation?: boolean
      message: string
    }>(
      `/api/etl/job/${jobId}/sync`,
      payload
    )
    return response.data
  },

  /**
   * Poll the status of an ETL job
   */
  etlJobStatus: async (jobId: string) => {
    const response = await excelApiClient.get<ETLJobStatusResponse>(`/api/etl/job/${jobId}`)
    return response.data
  },

  /**
   * Get all previous pipeline jobs for a specific connection
   */
  etlGetConnectionJobs: async (connectionId: string) => {
    const response = await excelApiClient.get<ETLJobStatusResponse[]>(`/api/etl/connection/${connectionId}/jobs`)
    return response.data
  },

  /**
   * List saved ETL connections
   */
  etlListConnections: async () => {
    const response = await excelApiClient.get<{ connections: ETLConnectionInfo[] }>('/api/etl/connections')
    return response.data.connections
  },

  /**
   * Delete a saved ETL connection
   */
  etlDeleteConnection: async (connectionId: string) => {
    const response = await excelApiClient.delete(`/api/etl/connections/${connectionId}`)
    return response.data
  },

  /**
   * Delete an ETL pipeline and its associated tables
   */
  etlDeleteJob: async (jobId: string) => {
    const response = await excelApiClient.delete(`/api/etl/job/${jobId}`)
    return response.data
  },

  /**
   * Update sync config (sync_column and/or sync_mode_type) on an existing pipeline
   */
  etlUpdateSyncConfig: async (jobId: string, config: { sync_column?: string; sync_mode_type?: string }) => {
    const response = await excelApiClient.patch(`/api/etl/job/${jobId}/sync-config`, config)
    return response.data
  },

  /**
   * Get full pipeline detail for editing
   */
  etlGetJobDetail: async (jobId: string) => {
    const response = await excelApiClient.get(`/api/etl/job/${jobId}/detail`)
    return response.data
  },

  /**
   * Update an existing pipeline job configuration
   */
  etlUpdateJob: async (jobId: string, payload: Record<string, any>) => {
    const response = await excelApiClient.put(`/api/etl/job/${jobId}`, payload)
    return response.data
  },
}

// ============================================================================
// ETL TYPES
// ============================================================================

export interface ETLConnectRequest {
  connection_id?: string
  db_type?: string
  host?: string
  port?: number
  username?: string
  password?: string
  database?: string
  auth_source?: string
  connection_name?: string
}

export interface ETLTableInfo {
  name: string
  row_count?: number
  columns?: Record<string, any>[]
}

export interface ETLExtractDataset {
  table_name?: string
  custom_query?: string
  output_name?: string
  sync_column?: string
}

export interface ETLConnectResponse {
  connection_id: string
  db_type: string
  database: string
  tables: ETLTableInfo[]
  message: string
}

export interface ETLPreviewResponse {
  table_name: string
  rows: Record<string, any>[]
  total_rows: number
  columns: string[]
}

export interface ETLDryRunResponse {
  success: boolean
  duration_seconds: number
  output_tables?: { name: string; row_count: number; columns: string[]; preview: Record<string, any>[] }[]
  error?: string
  stdout?: string
}

export interface ETLJobResponse {
  job_id: string
  status: string
  message: string
}

export interface ETLJobStatusResponse {
  job_id: string
  status: string
  source_tables?: any[]
  output_tables?: Record<string, any>[]
  error_message?: string
  started_at?: string
  completed_at?: string
  created_at?: string
  pipeline_name?: string
  target_table?: string
  sync_mode?: string
  sync_column?: string
  high_water_mark?: string
  sync_mode_type?: string
  primary_keys?: string[]
}

export interface ETLConnectionInfo {
  connection_id: string
  name: string
  db_type: string
  host: string
  port: number
  database_name: string
  created_at?: string
  last_used_at?: string
}

export default excelFileAPI
