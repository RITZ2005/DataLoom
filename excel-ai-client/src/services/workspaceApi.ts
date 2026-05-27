import { excelApiClient } from './excelApi'

// ============================================================================
// TYPES
// ============================================================================

export interface WorkspaceResponse {
  workspace_id: string
  name: string
  schema_name: string
  description?: string
  created_by: string
  created_at?: string
  table_count: number
}

export interface WorkspaceDetailResponse extends WorkspaceResponse {
  tables: TableMetadata[]
}

export interface TableMetadata {
  metadata_id: string
  table_name: string
  schema_name: string
  description?: string
  row_count: number
  columns: ColumnMetadata[]
}

export interface ColumnMetadata {
  column_id: string
  column_name: string
  data_type: string
  description?: string
  sample_values?: any[]
  stats?: Record<string, any>
}

export interface SemanticMetric {
  metric_id: string
  workspace_id: string
  name: string
  formula: string
  description?: string
  related_tables?: string[]
}

export interface SemanticDimension {
  dimension_id: string
  workspace_id: string
  name: string
  table_name: string
  column_name: string
  description?: string
  dim_type: string
}

export interface SemanticSynonym {
  synonym_id: string
  workspace_id: string
  keyword: string
  mapped_to: string
  mapped_type: string
}

export interface SemanticMetricRequest {
  name: string
  formula: string
  description?: string
  related_tables?: string[]
}

export interface SemanticDimensionRequest {
  name: string
  table_name: string
  column_name: string
  description?: string
  dim_type: string
}

export interface SemanticSynonymRequest {
  keyword: string
  mapped_to: string
  mapped_type: string
}

export interface SemanticLayerResponse {
  workspace_id: string
  metrics: SemanticMetric[]
  dimensions: SemanticDimension[]
  synonyms: SemanticSynonym[]
}

export interface WorkspaceWidget {
  widget_id: string
  dashboard_id: string
  workspace_id: string
  title: string
  widget_type: string
  chart_type?: string
  sql_query: string
  config?: Record<string, any>
  origin_question?: string
  pinned_by: string
  created_at?: string
}

export interface WorkspaceDashboardResponse {
  status: string
  workspace_id: string
  dashboard_id: string
  dashboard_name: string
  layout_json?: any
  widgets: WorkspaceWidget[]
}

export interface ChatResponse {
  status: string
  question: string
  sql: string
  explanation?: string
  columns: string[]
  data: any[]
  row_count: number
  message?: string
}

// ============================================================================
// API METHODS
// ============================================================================

const workspaceApi = {
  // --- Workspace CRUD ---
  listWorkspaces: async (): Promise<WorkspaceResponse[]> => {
    const { data } = await excelApiClient.get('/api/workspaces')
    return data.workspaces
  },

  createWorkspace: async (req: { name: string; description?: string }): Promise<WorkspaceResponse> => {
    const { data } = await excelApiClient.post('/api/workspaces', req)
    return data
  },

  updateWorkspace: async (workspaceId: string, req: { name?: string; description?: string }): Promise<WorkspaceResponse> => {
    const { data } = await excelApiClient.patch(`/api/workspaces/${workspaceId}`, req)
    return data
  },

  getWorkspaceDetail: async (workspaceId: string): Promise<WorkspaceDetailResponse> => {
    const { data } = await excelApiClient.get(`/api/workspaces/${workspaceId}`)
    return data
  },

  // --- Relationships ---
  getRelationships: async (workspaceId: string) => {
    const { data } = await excelApiClient.get(`/api/workspaces/${workspaceId}/relationships`)
    return data.relationships
  },

  createRelationship: async (workspaceId: string, payload: any) => {
    const { data } = await excelApiClient.post(`/api/workspaces/${workspaceId}/relationships`, payload)
    return data
  },

  deleteRelationship: async (workspaceId: string, relationshipId: string) => {
    const { data } = await excelApiClient.delete(`/api/workspaces/${workspaceId}/relationships/${relationshipId}`)
    return data
  },

  deleteWorkspace: async (workspaceId: string): Promise<any> => {
    const { data } = await excelApiClient.delete(`/api/workspaces/${workspaceId}`)
    return data
  },

  // --- Table/Column Metadata ---
  listTables: async (workspaceId: string): Promise<TableMetadata[]> => {
    const { data } = await excelApiClient.get(`/api/workspaces/${workspaceId}/tables`)
    return data.tables
  },

  updateTableDescription: async (workspaceId: string, tableName: string, description: string): Promise<any> => {
    const { data } = await excelApiClient.patch(`/api/workspaces/${workspaceId}/tables/${tableName}/description`, { description })
    return data
  },

  listColumns: async (workspaceId: string, tableName: string): Promise<ColumnMetadata[]> => {
    const { data } = await excelApiClient.get(`/api/workspaces/${workspaceId}/tables/${tableName}/columns`)
    return data.columns
  },

  updateColumnDescription: async (workspaceId: string, columnId: string, description: string): Promise<any> => {
    const { data } = await excelApiClient.patch(`/api/workspaces/${workspaceId}/columns/${columnId}/description`, { description })
    return data
  },

  // --- Semantic Layer ---
  getSemanticLayer: async (workspaceId: string): Promise<SemanticLayerResponse> => {
    const { data } = await excelApiClient.get(`/api/workspaces/${workspaceId}/semantic`)
    return data
  },

  createMetric: async (workspaceId: string, req: SemanticMetricRequest): Promise<SemanticMetric> => {
    const { data } = await excelApiClient.post(`/api/workspaces/${workspaceId}/semantic/metrics`, req)
    return data
  },

  deleteMetric: async (workspaceId: string, metricId: string): Promise<any> => {
    const { data } = await excelApiClient.delete(`/api/workspaces/${workspaceId}/semantic/metrics/${metricId}`)
    return data
  },

  createDimension: async (workspaceId: string, req: SemanticDimensionRequest): Promise<SemanticDimension> => {
    const { data } = await excelApiClient.post(`/api/workspaces/${workspaceId}/semantic/dimensions`, req)
    return data
  },

  deleteDimension: async (workspaceId: string, dimensionId: string): Promise<any> => {
    const { data } = await excelApiClient.delete(`/api/workspaces/${workspaceId}/semantic/dimensions/${dimensionId}`)
    return data
  },

  createSynonym: async (workspaceId: string, req: SemanticSynonymRequest): Promise<SemanticSynonym> => {
    const { data } = await excelApiClient.post(`/api/workspaces/${workspaceId}/semantic/synonyms`, req)
    return data
  },

  deleteSynonym: async (workspaceId: string, synonymId: string): Promise<any> => {
    const { data } = await excelApiClient.delete(`/api/workspaces/${workspaceId}/semantic/synonyms/${synonymId}`)
    return data
  },

  // --- Chat & Profiling ---
  workspaceChat: async (workspaceId: string, question: string, sessionId?: string, title?: string): Promise<ChatResponse> => {
    const { data } = await excelApiClient.post(`/api/workspaces/${workspaceId}/chat`, { question, session_id: sessionId, title })
    return data
  },

  executeCustomSql: async (workspaceId: string, payload: { title: string, sql_query: string }): Promise<ChatResponse> => {
    const { data } = await excelApiClient.post(`/api/workspaces/${workspaceId}/report/execute_custom_sql`, payload)
    return data
  },

  summarizeReport: async (workspaceId: string, payload: { question: string, sql_query: string, columns: string[], data: any[] }): Promise<{ status: string, summary: string }> => {
    const { data } = await excelApiClient.post(`/api/workspaces/${workspaceId}/report/summarize`, payload)
    return data
  },


  profileWorkspace: async (workspaceId: string): Promise<any> => {
    const { data } = await excelApiClient.post(`/api/workspaces/${workspaceId}/profile`)
    return data
  },

  profileTable: async (workspaceId: string, tableName: string): Promise<any> => {
    const { data } = await excelApiClient.post(`/api/workspaces/${workspaceId}/profile/${tableName}`)
    return data
  },

  // --- Dashboard & Pinning ---
  getDashboard: async (workspaceId: string, regenerate: boolean = false): Promise<WorkspaceDashboardResponse> => {
    const { data } = await excelApiClient.get(`/api/workspaces/${workspaceId}/dashboard`, {
      params: regenerate ? { regenerate: true } : {},
    })
    return data
  },

  streamDashboard: async (workspaceId: string, onWidget: (w: any) => void): Promise<void> => {
    const response = await fetch(`${import.meta.env.VITE_API_BASE_URL}/api/workspaces/${workspaceId}/dashboard/stream`, {
      headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
    })
    const reader = response.body?.getReader()
    if (!reader) return
    const decoder = new TextDecoder()
    let buffer = ''
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''
      for (const line of lines) {
        if (!line.trim()) continue
        try {
          const widget = JSON.parse(line)
          onWidget(widget)
        } catch (e) {
          console.error('[Stream] Failed to parse NDJSON line', e)
        }
      }
    }
  },

  saveDashboard: async (workspaceId: string, req: { name?: string; layout_json?: any; widgets?: any[] }): Promise<any> => {
    const { data } = await excelApiClient.post(`/api/workspaces/${workspaceId}/dashboard/save`, req)
    return data
  },

  pinWidget: async (workspaceId: string, req: {
    title: string
    widget_type: string
    chart_type?: string
    sql_query: string
    config?: Record<string, any>
    origin_question?: string
  }): Promise<any> => {
    const { data } = await excelApiClient.post(`/api/workspaces/${workspaceId}/dashboard/pin`, req)
    return data
  },

  unpinWidget: async (workspaceId: string, widgetId: string): Promise<any> => {
    const { data } = await excelApiClient.delete(`/api/workspaces/${workspaceId}/dashboard/widgets/${widgetId}`)
    return data
  },

  refreshWidget: async (workspaceId: string, widgetId: string, req?: { filters?: Record<string, string> }): Promise<any> => {
    const { data } = await excelApiClient.post(`/api/workspaces/${workspaceId}/dashboard/widgets/${widgetId}/refresh`, req)
    return data
  },

  // --- Dashboard AI Widget Generation ---
  generateWidget: async (workspaceId: string, query: string, widgetTypeHint?: string, chartTypeHint?: string): Promise<any> => {
    const { data } = await excelApiClient.post(`/api/workspaces/${workspaceId}/dashboard/widget`, {
      query,
      widget_type_hint: widgetTypeHint,
      chart_type_hint: chartTypeHint,
    })
    return data
  },

  createCustomWidget: async (workspaceId: string, title: string, sql_query: string, widget_type_hint: string, chart_type_hint?: string): Promise<any> => {
    const { data } = await excelApiClient.post(`/api/workspaces/${workspaceId}/dashboard/widget/custom`, {
      title,
      sql_query,
      widget_type_hint,
      chart_type_hint,
    })
    return data
  },

  getChartSchema: async (workspaceId: string): Promise<{ dimensions: any[]; measures: any[]; tables: any[] }> => {
    const { data } = await excelApiClient.get(`/api/workspaces/${workspaceId}/dashboard/schema`)
    return data
  },

  generateCustomChart: async (
    workspaceId: string,
    chartType: string,
    dimension: string,
    measure: string | null,
    aggregation: string
  ): Promise<any> => {
    const { data } = await excelApiClient.post(`/api/workspaces/${workspaceId}/dashboard/chart-builder`, {
      chart_type: chartType,
      dimension,
      measure,
      aggregation,
    })
    return data
  },

  updateDashboardWidgets: async (workspaceId: string, widgets: any[], layoutJson?: any): Promise<any> => {
    const { data } = await excelApiClient.post(`/api/workspaces/${workspaceId}/dashboard/save`, {
      widgets,
      layout_json: layoutJson,
    })
    return data
  },

  removeWidget: async (workspaceId: string, widgetId: string): Promise<any> => {
    const { data } = await excelApiClient.delete(`/api/workspaces/${workspaceId}/dashboard/widgets/${widgetId}`)
    return data
  },


  // --- Chat History ---
  getChatHistory: async (workspaceId: string): Promise<{ workspace_id: string; messages: any[] }> => {
    const { data } = await excelApiClient.get(`/api/workspaces/${workspaceId}/chat/history`)
    return data
  },

  clearChatHistory: async (workspaceId: string): Promise<{ workspace_id: string; deleted_count: number; message: string }> => {
    const { data } = await excelApiClient.delete(`/api/workspaces/${workspaceId}/chat/history`)
    return data
  },

  deleteChatHistoryItem: async (workspaceId: string, messageId: number) => {
    const { data } = await excelApiClient.delete(`/api/workspaces/${workspaceId}/chat/history/${messageId}`)
    return data
  },

  // --- ETL Navigation ---
  getEtlConnection: async (workspaceId: string): Promise<{ workspace_id: string; connection_id: string | null; job_id: string | null }> => {
    const { data } = await excelApiClient.get(`/api/workspaces/${workspaceId}/etl-connection`)
    return data
  },

  // --- Sharing ---
  toggleShare: async (workspaceId: string): Promise<{ status: string; workspace_id: string; is_shared: boolean; share_token: string | null }> => {
    const { data } = await excelApiClient.post(`/api/workspaces/${workspaceId}/share/toggle`)
    return data
  },

  getShareStatus: async (workspaceId: string): Promise<{ workspace_id: string; is_shared: boolean; share_token: string | null }> => {
    const { data } = await excelApiClient.get(`/api/workspaces/${workspaceId}/share/status`)
    return data
  },

  // --- Shared (Unauthenticated) ---
  getSharedWorkspaceDashboard: async (token: string): Promise<any> => {
    const { data } = await excelApiClient.get(`/api/share/workspace/${token}`)
    return data
  },

  sharedWorkspaceChat: async (token: string, question: string): Promise<ChatResponse> => {
    const { data } = await excelApiClient.post(`/api/share/workspace/${token}/chat`, { question })
    return data
  },

  // --- Shared Report ---
  sharedReportChat: async (token: string, question: string, title?: string): Promise<ChatResponse> => {
    const { data } = await excelApiClient.post(`/api/share/workspace/${token}/report/chat`, { question, title })
    return data
  },

  sharedReportSql: async (token: string, payload: { title: string, sql_query: string }): Promise<ChatResponse> => {
    const { data } = await excelApiClient.post(`/api/share/workspace/${token}/report/execute_custom_sql`, payload)
    return data
  },

  sharedReportSummarize: async (token: string, payload: { question: string, sql_query: string, columns: string[], data: any[] }): Promise<{ status: string, summary: string }> => {
    const { data } = await excelApiClient.post(`/api/share/workspace/${token}/report/summarize`, payload)
    return data
  },

  // --- Share a specific report snapshot ---
  shareReportSnapshot: async (workspaceId: string, payload: {
    title: string, question: string, sql_query: string,
    columns: string[], data: any[], row_count: number, ai_summary: string
  }): Promise<{ status: string, report_id: string, share_token: string }> => {
    const { data } = await excelApiClient.post(`/api/workspaces/${workspaceId}/report/share`, payload)
    return data
  },

  getSharedReport: async (token: string): Promise<any> => {
    const { data } = await excelApiClient.get(`/api/share/report/${token}`)
    return data
  },
}

export default workspaceApi
