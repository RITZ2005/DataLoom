<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, computed, nextTick, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import ChartViewer from '@/components/chart/ChartViewer.vue'
import ChangePasswordModal from '@/components/ChangePasswordModal.vue'
import excelFileAPI, { type FileInfo, type CategoryItem, type ETLDatasetConnection, type ETLDatasetTable } from '@/services/excelApi'
import { marked } from 'marked'
import { Login } from '@/store/login'

interface ChartData {
  chart_type: 'bar' | 'pie' | 'line'
  title?: string
  data: Record<string, number>
}

interface TableData {
  type: 'table'
  columns: string[]
  data: Record<string, any>[]
  full_data?: Record<string, any>[]
  total_rows: number
  displayed_rows: number
  has_more?: boolean
  message: string
}

interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  queryType?: string
  chartData?: ChartData
  tableData?: TableData
  cacheHit?: boolean
  sourceQuery?: string
  timestamp: Date
  responseTime?: number
  traceId?: string
  traceUrl?: string
  sessionUrl?: string
  sessionId?: string
  sessionEvent?: 'join' | 'leave'
}

const route = useRoute()
const props = defineProps<{ fileId?: string }>()
const router = useRouter()
const loginStore = Login()

const langfuseOn = computed(() => {
  return loginStore.userData?.langfuse_enabled ?? false
})

const files = ref<FileInfo[]>([])
const datasets = ref<ETLDatasetConnection[]>([])
const selectedFile = ref<FileInfo | null>(null)
const messages = ref<Message[]>([])
const inputMessage = ref('')
const isLoading = ref(false)
const isSending = ref(false)
const messagesContainer = ref<HTMLElement | null>(null)
const historyRequestId = ref(0)
const queryRequestId = ref(0)
const historyLimit = 10
const historyLoadedCount = ref(0)
const hasMoreHistory = ref(false)
const isLoadingHistory = ref(false)
// In embedded mode (with fileId), always hide sidebar. In Root Directory mode, allow toggle.
const sidebarManuallyHidden = ref(false)
const showChangePasswordModal = ref(false)
// Langfuse session tracking: each file gets a unique chat-thread UUID
const activeSessions = ref<Record<string, string>>({})
const sessionHasActivity = ref<Record<string, boolean>>({})
const openingLangfuseSessionId = ref<string | null>(null)
const _beaconSentForSession = ref<string | null>(null)  // prevent duplicate beacons
const showFileSidebar = computed(() => !props.fileId && !sidebarManuallyHidden.value)
const isDatabaseMode = computed(() => route.query.type === 'db' || selectedFile.value?.tags?.includes('ETL Data'))

// Quick suggestion chips
const quickSuggestions = ref([
  'How many rows are there?',
  'Show column names',
  'Display statistics',
  'Show first 10 rows'
])

// User avatar from profile (localStorage)
const userAvatarUrl = ref(localStorage.getItem('user-avatar') || '')
function _onStorageChange(e: StorageEvent) {
  if (e.key === 'user-avatar') userAvatarUrl.value = e.newValue || ''
}
function _refreshAvatar() {
  userAvatarUrl.value = localStorage.getItem('user-avatar') || ''
}

// Bookmark / Question Category state
const bookmarkingMessageId = ref<string | null>(null)
const isBookmarking = ref(false)
const copiedMessageId = ref<string | null>(null)

// Category state
const availableCategories = ref<CategoryItem[]>([])
const isLoadingCategories = ref(false)
const newCustomCategoryName = ref('')
const showNewCategoryInput = ref(false)

async function loadCategories() {
  if (availableCategories.value.length > 0) return  // cache
  isLoadingCategories.value = true
  try {
    availableCategories.value = await excelFileAPI.listCategories()
  } catch (e) {
    console.error('Failed to load categories:', e)
  } finally {
    isLoadingCategories.value = false
  }
}

async function createCustomCategory() {
  const name = newCustomCategoryName.value.trim()
  if (!name) return
  // Check if already exists
  if (availableCategories.value.some(c => c.name.toLowerCase() === name.toLowerCase())) {
    addSystemMessage(`❌ Category "${name}" already exists`)
    return
  }
  // Add locally — it will persist once a question is bookmarked with it
  availableCategories.value.push({ name, question_count: 0, is_default: false })
  newCustomCategoryName.value = ''
  showNewCategoryInput.value = false
  addSystemMessage(`✅ Category "${name}" created`)
}

async function bookmarkWithCategory(message: Message, categoryName: string) {
  if (!selectedFile.value || isBookmarking.value) return
  isBookmarking.value = true
  try {
    await excelFileAPI.saveQuestion(message.content, categoryName, selectedFile.value.file_uuid)
    bookmarkingMessageId.value = null
    addSystemMessage(`✅ Question saved under "${categoryName}"`)
  } catch (e: any) {
    console.error('Failed to bookmark question:', e)
    addSystemMessage('❌ Failed to bookmark question')
  } finally {
    isBookmarking.value = false
  }
}

async function resolveFileById(fileId: string): Promise<FileInfo | null> {
  if (!fileId) return null
  if (!files.value.length) {
    await loadFiles()
  }

  const forceDatabase = route.query.type === 'db'

  // Prefer database resolution first when explicitly in database mode.
  if (forceDatabase) {
    for (const conn of datasets.value) {
      if (conn.connection_id === fileId) {
        const allTables = conn.jobs.flatMap(job => job.tables)
        const totalRows = allTables.reduce((sum, table) => sum + (table.row_count || 0), 0)
        const uniqueTableNames = Array.from(new Set(allTables.map(table => table.table_name).filter(Boolean)))
        return {
          file_uuid: conn.connection_id,
          filename: `[DB] ${conn.name}`,
          table_name: '__DATABASE_CONNECTION__',
          total_rows: totalRows,
          columns: uniqueTableNames,
          column_stats: {
            mode: 'connection',
            db_type: conn.db_type,
            database_name: conn.database_name,
            table_count: uniqueTableNames.length,
          },
          tags: ['ETL Data']
        } as FileInfo
      }
    }

    for (const conn of datasets.value) {
      for (const job of conn.jobs) {
        for (const table of job.tables) {
          if (table.table_id === fileId || table.table_name === fileId) {
            return {
              file_uuid: table.table_id,
              filename: `[DB] ${table.table_name || table.source_name}`,
              table_name: table.table_name,
              total_rows: table.row_count || 0,
              columns: Object.keys(table.column_stats || {}),
              column_stats: table.column_stats || {},
              tags: ["ETL Data"]
            } as FileInfo
          }
        }
      }
    }
  }

  // 1. Check normal files
  const existing = files.value.find(f => f.file_uuid === fileId || f.filename === fileId)
  if (existing) return existing

  // 2. Check ETL connection-level targets (chat with entire database)
  for (const conn of datasets.value) {
    if (conn.connection_id === fileId) {
      const allTables = conn.jobs.flatMap(job => job.tables)
      const totalRows = allTables.reduce((sum, table) => sum + (table.row_count || 0), 0)
      const uniqueTableNames = Array.from(new Set(allTables.map(table => table.table_name).filter(Boolean)))
      return {
        file_uuid: conn.connection_id,
        filename: `[DB] ${conn.name}`,
        table_name: '__DATABASE_CONNECTION__',
        total_rows: totalRows,
        columns: uniqueTableNames,
        column_stats: {
          mode: 'connection',
          db_type: conn.db_type,
          database_name: conn.database_name,
          table_count: uniqueTableNames.length,
        },
        tags: ['ETL Data']
      } as FileInfo
    }
  }

  // 3. Check ETL table-level datasets
  for (const conn of datasets.value) {
    for (const job of conn.jobs) {
      for (const table of job.tables) {
        if (table.table_id === fileId || table.table_name === fileId) {
          return {
            file_uuid: table.table_id,
            filename: `[DB] ${table.table_name || table.source_name}`,
            table_name: table.table_name,
            total_rows: table.row_count || 0,
            columns: Object.keys(table.column_stats || {}),
            column_stats: table.column_stats || {},
            tags: ["ETL Data"]
          } as FileInfo
        }
      }
    }
  }

  try {
    const info = await excelFileAPI.getFileInfo(fileId)
    const stats = info.stats || {}
    const columns = Object.keys(stats.columns || {})
    return {
      file_uuid: info.file_uuid,
      filename: info.filename,
      table_name: info.table_name || '',
      total_rows: stats.total_rows || 0,
      columns,
      column_stats: stats,
      created_on: undefined,
      deleted_at: undefined
    }
  } catch (e) {
    return null
  }
}

function toSingleQueryValue(value: unknown): string | undefined {
  if (Array.isArray(value)) return value[0]
  return typeof value === 'string' ? value : undefined
}

function generateSessionUuid(): string {
  const webCrypto = globalThis.crypto

  if (webCrypto?.randomUUID) {
    return webCrypto.randomUUID()
  }

  // Fallback for environments where randomUUID is unavailable (common on non-HTTPS LAN URLs).
  if (webCrypto?.getRandomValues) {
    const bytes = new Uint8Array(16)
    webCrypto.getRandomValues(bytes)
    bytes[6] = (bytes[6] & 0x0f) | 0x40
    bytes[8] = (bytes[8] & 0x3f) | 0x80
    const hex = Array.from(bytes, b => b.toString(16).padStart(2, '0')).join('')
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
  }

  // Last-resort fallback to keep session flow functional on very old runtimes.
  const now = Date.now().toString(16)
  const rnd = Math.floor(Math.random() * Number.MAX_SAFE_INTEGER).toString(16)
  return `${now.slice(-8)}-${rnd.slice(0, 4).padEnd(4, '0')}-4${rnd.slice(4, 7).padEnd(3, '0')}-a${rnd.slice(7, 10).padEnd(3, '0')}-${(now + rnd).slice(0, 12).padEnd(12, '0')}`
}

function startSessionId(fileUuid: string, preferredSessionId?: string): string {
  const sanitizedPreferred = preferredSessionId?.trim()
  if (sanitizedPreferred) {
    activeSessions.value[fileUuid] = sanitizedPreferred
    _beaconSentForSession.value = null  // reset guard for new session
    return sanitizedPreferred
  }
  const created = generateSessionUuid()
  activeSessions.value[fileUuid] = created
  _beaconSentForSession.value = null  // reset guard for new session
  return created
}

function buildSessionSystemMessage(type: 'join' | 'leave', file: FileInfo, _sessionId: string): string {
  if (type === 'join') {
    return `👋 Session started for ${file.filename}`
  }
  return `🚪 Session ended for ${file.filename}`
}

function createSessionMessage(type: 'join' | 'leave', file: FileInfo, sessionId: string): Message {
  return {
    id: `sys-${Date.now()}-${Math.random()}`,
    role: 'assistant',
    content: buildSessionSystemMessage(type, file, sessionId),
    timestamp: new Date(),
    sessionId,
    sessionEvent: type,
  }
}

async function persistSessionEvent(file: FileInfo, sessionId: string, type: 'join' | 'leave') {
  const message = createSessionMessage(type, file, sessionId)
  try {
    await excelFileAPI.saveChatMessage(file.file_uuid, {
      role: 'assistant',
      content: message.content,
      metadata: {
        isSessionEvent: true,
        sessionEvent: type,
        langfuseSessionId: sessionId,
      }
    })
  } catch (e) {
    console.error(`Failed to persist session ${type} event:`, e)
  }
}

function getSessionActivityKey(fileUuid: string, sessionId: string): string {
  return `${fileUuid}:${sessionId}`
}

function hasSessionActivity(fileUuid: string, sessionId: string): boolean {
  return !!sessionHasActivity.value[getSessionActivityKey(fileUuid, sessionId)]
}

function markSessionActivity(fileUuid: string, sessionId: string): void {
  sessionHasActivity.value[getSessionActivityKey(fileUuid, sessionId)] = true
}

function clearSessionActivity(fileUuid: string, sessionId: string): void {
  delete sessionHasActivity.value[getSessionActivityKey(fileUuid, sessionId)]
}

function removeTransientSessionMessages(sessionId: string) {
  messages.value = messages.value.filter(m => !(m.sessionEvent && m.sessionId === sessionId && !m.id.startsWith('saved-')))
}

async function ensureSessionActivated(file: FileInfo, sessionId: string) {
  if (hasSessionActivity(file.file_uuid, sessionId)) return
  markSessionActivity(file.file_uuid, sessionId)
  await persistSessionEvent(file, sessionId, 'join')
}

async function closeSession(file: FileInfo, sessionId: string, renderLeaveMessage: boolean) {
  if (!hasSessionActivity(file.file_uuid, sessionId)) {
    removeTransientSessionMessages(sessionId)
    clearSessionActivity(file.file_uuid, sessionId)
    return
  }

  if (renderLeaveMessage) {
    messages.value.push(createSessionMessage('leave', file, sessionId))
  }
  await persistSessionEvent(file, sessionId, 'leave')
  clearSessionActivity(file.file_uuid, sessionId)
}

async function openLangfuseSession(sessionId: string) {
  if (!sessionId || openingLangfuseSessionId.value) return
  openingLangfuseSessionId.value = sessionId
  try {
    const ssoUrl = await excelFileAPI.getLangfuseSsoUrl(sessionId)
    window.open(ssoUrl, '_blank', 'noopener')
  } catch (error: any) {
    const detail = error?.response?.data?.detail || 'Failed to open Langfuse session'
    addSystemMessage(`❌ ${detail}`)
  } finally {
    openingLangfuseSessionId.value = null
  }
}

function buildTraceUrlFromId(traceId?: string): string | undefined {
  if (!traceId) return undefined
  const host = (import.meta.env.VITE_LANGFUSE_HOST || `${window.location.protocol}//${window.location.hostname}:3000`).replace(/\/$/, '')
  const projectId = import.meta.env.VITE_LANGFUSE_PROJECT_ID
  if (!projectId) return undefined
  return `${host}/project/${projectId}/traces/${traceId}`
}

function hasTraceLink(message: Message): boolean {
  return !!(message.traceUrl || message.traceId)
}

async function openTraceForMessage(message: Message) {
  try {
    const params: any = {}
    if (message.traceId) {
      params.trace_id = message.traceId
    } else if (message.sessionId) {
      params.session_id = message.sessionId
      params.target = 'traces'
    } else {
      params.target = 'traces'
    }
    const data = await excelFileAPI.getLangfuseToken(params)
    const url = data?.sso_url
    if (url) {
      window.open(url, '_blank', 'noopener')
      return
    }
  } catch (err: any) {
    if (err?.response?.status === 503) {
      addSystemMessage('Setting up your Traces session... Please try again in a few seconds.')
      return
    }
  }

  // Fallback
  if (message.traceUrl) {
    window.open(message.traceUrl, '_blank', 'noopener')
    return
  }

  const derivedTraceUrl = buildTraceUrlFromId(message.traceId)
  if (derivedTraceUrl) {
    window.open(derivedTraceUrl, '_blank', 'noopener')
    return
  }

  addSystemMessage('Langfuse trace link is not available yet for this response.')
}

function clearSelection() {
  selectedFile.value = null
  messages.value = []
  inputMessage.value = ''
  isSending.value = false
}

// ── sendBeacon-based session close for hard tab/browser close ──
function _getApiBaseUrl(): string {
  return (import.meta.env.VITE_API_URL as string) || ''
}

function _sendSessionCloseBeacon() {
  const file = selectedFile.value
  if (!file) return
  const sessionId = activeSessions.value[file.file_uuid]
  if (!sessionId) return
  // Guard: only send once per session (beforeunload + visibilitychange can both fire)
  if (_beaconSentForSession.value === sessionId) return
  _beaconSentForSession.value = sessionId

  const token = localStorage.getItem('user-token')
  if (!token) return

  const payload = JSON.stringify({
    file_uuid: file.file_uuid,
    session_id: sessionId,
    token,
  })
  const url = `${_getApiBaseUrl()}/api/session/close`
  try {
    navigator.sendBeacon(url, new Blob([payload], { type: 'application/json' }))
  } catch (e) {
    // sendBeacon is best-effort; swallow errors
    console.warn('sendBeacon failed for session close:', e)
  }
}

function _onBeforeUnload() {
  _sendSessionCloseBeacon()
}

function _onPageHide() {
  _sendSessionCloseBeacon()
}

onBeforeUnmount(() => {
  // Clean up global listeners
  window.removeEventListener('beforeunload', _onBeforeUnload)
  window.removeEventListener('pagehide', _onPageHide)
  window.removeEventListener('storage', _onStorageChange)
  window.removeEventListener('avatar-changed', _refreshAvatar)

  // Normal in-app teardown — close session via API
  if (!selectedFile.value) return
  const endingSessionId = activeSessions.value[selectedFile.value.file_uuid]
  if (!endingSessionId) return
  // If beacon already handled this session close (hard tab/browser close), skip
  if (_beaconSentForSession.value === endingSessionId) return
  // If page is being unloaded, beacon will handle it — skip to avoid duplicate
  if (document.visibilityState === 'hidden') return
  // Mark as handled so beacon won't also fire for this session
  _beaconSentForSession.value = endingSessionId
  void closeSession(selectedFile.value, endingSessionId, false)
})

onMounted(async () => {
  // Register global listeners for hard tab/browser close
  window.addEventListener('beforeunload', _onBeforeUnload)
  window.addEventListener('pagehide', _onPageHide)
  window.addEventListener('storage', _onStorageChange)
  window.addEventListener('avatar-changed', _refreshAvatar)

  // If fileId is passed as prop (embedded mode), only load that specific file
  if (props.fileId) {
    const file = await resolveFileById(props.fileId)
    if (file) {
      await selectFile(file, toSingleQueryValue(route.query.sessionId))
    } else {
      clearSelection()
    }
  } else {
    // Root Directory mode: load all files and allow selection
    await loadFiles()
    const initialFileId = route.query.fileId as string | undefined
    const initialSessionId = toSingleQueryValue(route.query.sessionId)
    if (initialFileId) {
      const file = await resolveFileById(initialFileId)
      if (file) {
        await selectFile(file, initialSessionId)
      } else {
        clearSelection()
      }
    }
  }
})

watch(
  () => props.fileId,
  async (newFileId) => {
    if (!newFileId) return
    const file = await resolveFileById(newFileId)
    if (file && file.file_uuid !== selectedFile.value?.file_uuid) {
      await selectFile(file, toSingleQueryValue(route.query.sessionId))
    } else if (!file) {
      clearSelection()
    }
  }
)

watch(
  () => ({
    fileId: toSingleQueryValue(route.query.fileId),
    sessionId: toSingleQueryValue(route.query.sessionId)
  }),
  async ({ fileId, sessionId }) => {
    if (props.fileId) return
    if (!fileId) return
    const file = await resolveFileById(fileId)
    if (file && file.file_uuid !== selectedFile.value?.file_uuid) {
      await selectFile(file, sessionId)
    } else if (file && sessionId) {
      const currentSessionId = activeSessions.value[file.file_uuid]
      if (currentSessionId && currentSessionId !== sessionId) {
        await closeSession(file, currentSessionId, true)
      }
      activeSessions.value[file.file_uuid] = sessionId
      const joinMessage = createSessionMessage('join', file, sessionId)
      messages.value.push(joinMessage)
      clearSessionActivity(file.file_uuid, sessionId)
      scrollToBottom()
    } else if (!file) {
      clearSelection()
    }
  }
)

async function loadFiles() {
  isLoading.value = true
  try {
    const [fetchedFiles, fetchedETL] = await Promise.all([
      excelFileAPI.listFiles(),
      excelFileAPI.listETLDatasets().catch(err => {
        console.error('Error loading ETL datasets:', err)
        return []
      })
    ])
    files.value = fetchedFiles
    datasets.value = fetchedETL
  } catch (error) {
    console.error('Error loading files:', error)
    addSystemMessage('❌ Failed to load files. Please check your connection.')
  } finally {
    isLoading.value = false
  }
}

function selectDataset(table: ETLDatasetTable) {
  selectFile({
    file_uuid: table.table_id,
    filename: `[DB] ${table.table_name || table.source_name}`,
    table_name: table.table_name,
    total_rows: table.row_count || 0,
    columns: Object.keys(table.column_stats?.columns || {}),
    column_stats: table.column_stats || {}
  })
}

async function selectFile(file: FileInfo, preferredSessionId?: string) {
  const previousFile = selectedFile.value
  const previousSessionId = previousFile ? activeSessions.value[previousFile.file_uuid] : undefined

  if (previousFile && previousSessionId && previousFile.file_uuid !== file.file_uuid) {
    await closeSession(previousFile, previousSessionId, false)
  }

  selectedFile.value = file
  messages.value = []
  inputMessage.value = ''
  isSending.value = false
  queryRequestId.value += 1
  historyLoadedCount.value = 0
  hasMoreHistory.value = false
  const currentSessionId = startSessionId(file.file_uuid, preferredSessionId)
  const expectedFileUuid = file.file_uuid
  const requestId = ++historyRequestId.value
  const freshMessages: Message[] = []

  // Add welcome message
  freshMessages.push({
    id: `sys-${Date.now()}-${Math.random()}`,
    role: 'assistant',
    content: `📊 Loaded: ${file.filename} (${file.total_rows} rows, ${file.columns.length} columns)`,
    timestamp: new Date()
  })

  // Load persisted chat history
  try {
    isLoadingHistory.value = true
    const history = await excelFileAPI.getChatHistory(file.file_uuid, historyLimit, 0)
    if (historyRequestId.value !== requestId) return
    if (selectedFile.value?.file_uuid !== expectedFileUuid) return
    const filteredHistory = history.filter(msg => !msg.file_uuid || msg.file_uuid === expectedFileUuid)
    historyLoadedCount.value = filteredHistory.length
    hasMoreHistory.value = filteredHistory.length === historyLimit
    if (filteredHistory.length > 0) {
      for (let idx = 0; idx < filteredHistory.length; idx += 1) {
        const msg = filteredHistory[idx]
        const meta = msg.metadata || {}
        freshMessages.push({
          id: `saved-${msg.id}`,
          role: msg.role as 'user' | 'assistant',
          content: msg.content,
          queryType: msg.query_type || undefined,
          chartData: meta.chartData || undefined,
          tableData: meta.tableData || undefined,
          cacheHit: msg.cache_hit || false,
          sourceQuery: meta.sourceQuery || undefined,
          responseTime: msg.response_time || undefined,
          timestamp: new Date(msg.created_at),
          traceId: meta.traceId || undefined,
          traceUrl: meta.traceUrl || undefined,
          sessionUrl: meta.langfuseSessionUrl || undefined,
          sessionId: meta.langfuseSessionId || undefined,
          sessionEvent: (meta.isSessionEvent ? meta.sessionEvent : undefined) as 'join' | 'leave' | undefined,
        })
      }
    } else {
      freshMessages.push({
        id: `sys-${Date.now()}-${Math.random()}`,
        role: 'assistant',
        content: '💬 Ask questions about your data using natural language...',
        timestamp: new Date()
      })
      freshMessages.push({
        id: `sys-${Date.now()}-${Math.random()}`,
        role: 'assistant',
        content: 'Examples: "How many rows?", "Show me the average of column X", "List all unique values"',
        timestamp: new Date()
      })
    }
    freshMessages.push(createSessionMessage('join', file, currentSessionId))
    clearSessionActivity(file.file_uuid, currentSessionId)
    messages.value = freshMessages
    scrollToBottom()
  } catch (e) {
    if (historyRequestId.value !== requestId) return
    if (selectedFile.value?.file_uuid !== expectedFileUuid) return
    console.error('Failed to load chat history:', e)
    freshMessages.push({
      id: `sys-${Date.now()}-${Math.random()}`,
      role: 'assistant',
      content: '💬 Ask questions about your data using natural language...',
      timestamp: new Date()
    })
    freshMessages.push({
      id: `sys-${Date.now()}-${Math.random()}`,
      role: 'assistant',
      content: 'Examples: "How many rows?", "Show me the average of column X", "List all unique values"',
      timestamp: new Date()
    })
    freshMessages.push(createSessionMessage('join', file, currentSessionId))
    clearSessionActivity(file.file_uuid, currentSessionId)
    messages.value = freshMessages
    scrollToBottom()
  } finally {
    isLoadingHistory.value = false
  }
}

async function loadMoreHistory() {
  if (!selectedFile.value || isLoadingHistory.value || !hasMoreHistory.value) return
  const expectedFileUuid = selectedFile.value.file_uuid
  const requestId = historyRequestId.value
  isLoadingHistory.value = true
  try {
    const history = await excelFileAPI.getChatHistory(
      expectedFileUuid,
      historyLimit,
      historyLoadedCount.value
    )
    if (historyRequestId.value !== requestId) return
    if (selectedFile.value?.file_uuid !== expectedFileUuid) return
    const filteredHistory = history.filter(msg => !msg.file_uuid || msg.file_uuid === expectedFileUuid)
    if (filteredHistory.length === 0) {
      hasMoreHistory.value = false
      return
    }
    const olderMessages: Message[] = filteredHistory.map(msg => {
      const meta = msg.metadata || {}
      return {
        id: `saved-${msg.id}`,
        role: msg.role as 'user' | 'assistant',
        content: msg.content,
        queryType: msg.query_type || undefined,
        chartData: meta.chartData || undefined,
        tableData: meta.tableData || undefined,
        cacheHit: msg.cache_hit || false,
        sourceQuery: meta.sourceQuery || undefined,
        responseTime: msg.response_time || undefined,
        timestamp: new Date(msg.created_at),
        traceId: meta.traceId || undefined,
        traceUrl: meta.traceUrl || undefined,
        sessionUrl: meta.langfuseSessionUrl || undefined,
        sessionId: meta.langfuseSessionId || undefined,
        sessionEvent: (meta.isSessionEvent ? meta.sessionEvent : undefined) as 'join' | 'leave' | undefined,
      }
    })
    const insertIndex = messages.value.findIndex(m => m.id.startsWith('saved-') || m.role === 'user')
    if (insertIndex === -1) {
      messages.value.unshift(...olderMessages)
    } else {
      messages.value.splice(insertIndex, 0, ...olderMessages)
    }
    historyLoadedCount.value += olderMessages.length
    hasMoreHistory.value = olderMessages.length === historyLimit
  } catch (e) {
    console.error('Failed to load more chat history:', e)
  } finally {
    isLoadingHistory.value = false
  }
}

function addSystemMessage(content: string) {
  messages.value.push({
    id: `sys-${Date.now()}-${Math.random()}`,
    role: 'assistant',
    content,
    timestamp: new Date()
  })
  scrollToBottom()
}

async function runQuery(userMessage: string, useCache: boolean, addUserBubble: boolean) {
  if (!selectedFile.value || isSending.value) return
  const activeFileUuid = selectedFile.value.file_uuid
  const requestId = queryRequestId.value

  let userMsgId: string | null = null
  if (addUserBubble) {
    userMsgId = `user-${Date.now()}`
    messages.value.push({
      id: userMsgId,
      role: 'user',
      content: userMessage,
      timestamp: new Date()
    })
    // User message is saved to server AFTER we get the trace ID (see below)
  }

  // Add thinking indicator
  const thinkingId = `thinking-${Date.now()}`
  messages.value.push({
    id: thinkingId,
    role: 'assistant',
    content: 'thinking',
    timestamp: new Date()
  })

  isSending.value = true
  const startTime = performance.now()
  scrollToBottom()

  try {
    // Send query to backend with Langfuse session ID
    let sessionId = activeSessions.value[selectedFile.value.file_uuid]
    if (!sessionId) {
      sessionId = startSessionId(selectedFile.value.file_uuid)
      clearSessionActivity(selectedFile.value.file_uuid, sessionId)
    }
    await ensureSessionActivated(selectedFile.value, sessionId)
    const sourceType = isDatabaseMode.value ? 'database' : 'file'
    const result = await excelFileAPI.queryFile(
      selectedFile.value.file_uuid,
      userMessage,
      useCache,
      sessionId,
      sourceType,
    )
    if (result.session_id) {
      activeSessions.value[selectedFile.value.file_uuid] = result.session_id
      sessionId = result.session_id
      markSessionActivity(selectedFile.value.file_uuid, sessionId)
    }
    if (queryRequestId.value !== requestId || selectedFile.value?.file_uuid !== activeFileUuid) {
      messages.value = messages.value.filter(m => m.id !== thinkingId)
      isSending.value = false
      return
    }

    // Remove thinking indicator
    messages.value = messages.value.filter(m => m.id !== thinkingId)

    // Parse response based on query type
    let chartData: ChartData | undefined = undefined
    let tableData: TableData | undefined = undefined
    let displayContent = result.data

    // Try to parse if it's a table response
    try {
      const parsed = JSON.parse(result.data)
      if (parsed.type === 'table' && parsed.columns && parsed.data) {
        tableData = parsed
        displayContent = parsed.message
      }
    } catch (e) {
      // Not JSON table data, continue normal processing
    }

    if (result.query_type === 'PLOT') {
      // Try to parse JSON response for chart data
      try {
        const cleanJson = result.data
          .replace(/```json/g, '')
          .replace(/```/g, '')
          .trim()
        
        const parsedData = JSON.parse(cleanJson)
        if (parsedData.chart_type && parsedData.data) {
          chartData = parsedData
          displayContent = `Generated ${parsedData.chart_type} chart${parsedData.title ? ': ' + parsedData.title : ''}`
        }
      } catch (e) {
        // If JSON parsing fails, use raw response
        console.warn('Failed to parse chart JSON:', e)
      }
    }

    // Attach trace link to the user message that triggered this query
    const traceId = result.trace_id ?? undefined
    const traceUrl = result.trace_url ?? undefined
    if (userMsgId) {
      const idx = messages.value.findIndex(m => m.id === userMsgId)
      if (idx !== -1) {
        messages.value.splice(idx, 1, {
          ...messages.value[idx],
          traceId,
          traceUrl,
        })
      }
    }
    // Now save user message with trace info in metadata
    if (userMsgId) {
      try {
        await excelFileAPI.saveChatMessage(selectedFile.value.file_uuid, {
          role: 'user',
          content: userMessage,
          metadata: {
            traceId,
            traceUrl,
            langfuseSessionId: sessionId,
            langfuseSessionUrl: result.session_url || undefined,
          }
        })
      } catch (e) { console.error('Failed to save user message:', e) }
    }

    // Add assistant response with optional chart or table
    const elapsedTime = (performance.now() - startTime) / 1000
    messages.value.push({
      id: `assistant-${Date.now()}`,
      role: 'assistant',
      content: displayContent,
      queryType: result.query_type,
      chartData: chartData,
      tableData: tableData,
      cacheHit: result.cache_hit,
      sourceQuery: userMessage,
      timestamp: new Date(),
      responseTime: elapsedTime,
      traceId: result.trace_id ?? undefined,
      traceUrl: result.trace_url ?? undefined,
      sessionUrl: result.session_url ?? undefined,
    })

    // Save assistant response to server
    try {
      const metadata: Record<string, any> = {
        sourceQuery: userMessage,
        traceId,
        traceUrl,
        langfuseSessionId: sessionId,
        langfuseSessionUrl: result.session_url || undefined,
      }
      if (chartData) metadata.chartData = chartData
      if (tableData) metadata.tableData = tableData
      await excelFileAPI.saveChatMessage(selectedFile.value.file_uuid, {
        role: 'assistant',
        content: displayContent,
        query_type: result.query_type,
        cache_hit: result.cache_hit || false,
        response_time: elapsedTime,
        metadata
      })
    } catch (e) { console.error('Failed to save assistant message:', e) }

    scrollToBottom()
  } catch (error: any) {
    if (queryRequestId.value !== requestId || selectedFile.value?.file_uuid !== activeFileUuid) {
      messages.value = messages.value.filter(m => m.id !== thinkingId)
      isSending.value = false
      return
    }
    console.error('Query error:', error)
    // Remove thinking indicator on error
    messages.value = messages.value.filter(m => m.id !== thinkingId)
    
    const errorMessage = error.response?.data?.detail || 'Failed to process query'
    messages.value.push({
      id: `error-${Date.now()}`,
      role: 'assistant',
      content: `❌ Error: ${errorMessage}`,
      timestamp: new Date()
    })
    scrollToBottom()
  } finally {
    isSending.value = false
  }
}

async function sendMessage() {
  if (!inputMessage.value.trim()) return

  const userMessage = inputMessage.value.trim()
  inputMessage.value = ''
  await runQuery(userMessage, true, true)
}

async function bypassCache(message: Message) {
  if (!message.sourceQuery) return
  await runQuery(message.sourceQuery, false, false)
}

function scrollToBottom() {
  nextTick(() => {
    if (messagesContainer.value) {
      messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
    }
  })
}

function getMessageClass(message: Message) {
  return {
    'flex justify-end': message.role === 'user',
    'flex justify-start': message.role === 'assistant'
  }
}

function formatTime(date: Date) {
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

function downloadChat() {
  if (messages.value.length === 0) {
    alert('No chat history to download')
    return
  }

  // Format chat as text
  let chatContent = `Chat History - ${selectedFile.value?.filename || 'Unknown File'}\n`
  chatContent += `Generated: ${new Date().toLocaleString()}\n`
  chatContent += `${'='.repeat(80)}\n\n`

  messages.value.forEach((msg, idx) => {
    chatContent += `${idx + 1}. [${msg.role.toUpperCase()}] ${formatTime(msg.timestamp)}\n`
    if (msg.queryType) {
      chatContent += `Type: ${msg.queryType}\n`
    }
    chatContent += `${msg.content}\n`
    chatContent += `-${'-'.repeat(78)}\n\n`
  })

  // Create and download file
  const dataBlob = new Blob([chatContent], { type: 'text/plain' })
  const url = URL.createObjectURL(dataBlob)
  const link = document.createElement('a')
  link.href = url
  link.download = `chat_${selectedFile.value?.filename.replace(/\.[^.]+$/, '')}_${Date.now()}.txt`
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}

function downloadChartAsImage(message: Message) {
  if (!message.chartData) return
  
  // Find the canvas element for this chart
  // Chart.js renders charts on canvas elements
  const chartElements = document.querySelectorAll('.chart-wrapper canvas')
  
  if (chartElements.length === 0) {
    console.error('No chart canvas found')
    return
  }
  
  // Get the last canvas (most recent chart)
  const canvas = chartElements[chartElements.length - 1] as HTMLCanvasElement
  
  // Convert canvas to image
  canvas.toBlob((blob) => {
    if (!blob) {
      console.error('Failed to create image blob')
      return
    }
    
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `chart_${message.chartData?.title || 'data'}_${Date.now()}.png`
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    URL.revokeObjectURL(url)
  }, 'image/png')
}

function exportTableToCSV(tableData: TableData) {
  if (!tableData) return
  
  // Use full_data if available, otherwise use displayed data
  const dataToExport = tableData.full_data || tableData.data
  
  if (!dataToExport.length) return
  
  // Create CSV header
  const headers = tableData.columns.join(',')
  
  // Create CSV rows - use full_data for complete export
  const rows = dataToExport.map(row => {
    return tableData.columns.map(col => {
      const value = row[col]
      // Escape values containing commas or quotes
      if (typeof value === 'string' && (value.includes(',') || value.includes('"'))) {
        return `"${value.replace(/"/g, '""')}"`
      }
      return value
    }).join(',')
  })
  
  // Combine header and rows
  const csvContent = [headers, ...rows].join('\n')
  
  // Create and download file
  const blob = new Blob([csvContent], { type: 'text/csv' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  const rowCount = dataToExport.length
  link.download = `table_data_${rowCount}_rows_${Date.now()}.csv`
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}

function copyToClipboard(text: string, messageId?: string) {
  navigator.clipboard.writeText(text).then(() => {
    if (messageId) {
      copiedMessageId.value = messageId
      setTimeout(() => { copiedMessageId.value = null }, 2000)
    }
  }).catch(err => {
    console.error('Failed to copy text:', err)
  })
}

async function removeMessageFromView(message: Message) {
  const idsToRemove = new Set<string>([message.id])
  if (message.role === 'assistant') {
    const index = messages.value.findIndex(m => m.id === message.id)
    if (index > 0) {
      for (let i = index - 1; i >= 0; i -= 1) {
        if (messages.value[i].role === 'user') {
          idsToRemove.add(messages.value[i].id)
          break
        }
      }
    }
  }

  const savedId = message.id.startsWith('saved-')
    ? Number(message.id.replace('saved-', ''))
    : null

  messages.value = messages.value.filter(m => !idsToRemove.has(m.id))

  if (savedId && selectedFile.value) {
    try {
      await excelFileAPI.softDeleteChatMessage(selectedFile.value.file_uuid, savedId)
    } catch (e) {
      console.error('Failed to soft delete message:', e)
    }
  }
}

function exportChatAsJSON() {
  if (messages.value.length === 0) {
    alert('No chat history to export')
    return
  }

  const chatData = {
    file: selectedFile.value?.filename,
    timestamp: new Date().toISOString(),
    totalMessages: messages.value.length,
    messages: messages.value.map(msg => ({
      id: msg.id,
      role: msg.role,
      content: msg.content,
      queryType: msg.queryType,
      chartData: msg.chartData || null,
      timestamp: msg.timestamp.toISOString()
    }))
  }

  const dataBlob = new Blob([JSON.stringify(chatData, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(dataBlob)
  const link = document.createElement('a')
  link.href = url
  link.download = `chat_export_${selectedFile.value?.filename.replace(/\.[^.]+$/, '')}_${Date.now()}.json`
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}

function clearChat() {
  if (confirm('Are you sure you want to clear the chat history?')) {
    // Clear server-side history
    if (selectedFile.value) {
      excelFileAPI.clearChatHistory(selectedFile.value.file_uuid).catch(e =>
        console.error('Failed to clear server chat history:', e)
      )
      // Reset Langfuse session — new thread after clearing
      activeSessions.value[selectedFile.value.file_uuid] = startSessionId(selectedFile.value.file_uuid)
      clearSessionActivity(selectedFile.value.file_uuid, activeSessions.value[selectedFile.value.file_uuid])
    }
    messages.value = []
    if (selectedFile.value) {
      addSystemMessage(`📊 Loaded: ${selectedFile.value.filename}`)
      addSystemMessage('💬 Ask questions about your data...')
      const joinMessage = createSessionMessage('join', selectedFile.value, activeSessions.value[selectedFile.value.file_uuid])
      messages.value.push(joinMessage)
      scrollToBottom()
    }
  }
}

// Render markdown to HTML
function renderMarkdown(content: string): string {
  try {
    return marked.parse(content) as string
  } catch (e) {
    console.error('Markdown parsing error:', e)
    return content
  }
}

// Expose functions for parent component to use
defineExpose({
  clearChat,
  downloadChat,
  exportChatAsJSON,
  messages
})
</script>

<template>
  <div class="flex" :class="props.fileId ? 'h-full' : 'h-screen'">
    <!-- Files Sidebar -->
    <div v-if="showFileSidebar" class="w-64 border-r flex flex-col bg-gradient-to-b from-muted/60 to-background overflow-hidden">
      
      <template v-if="!isDatabaseMode">
        <div class="p-4 border-b bg-card">
          <div class="flex items-center gap-2 mb-1">
            <iconify-icon icon="lucide:files" class="h-4 w-4 text-primary" />
            <h2 class="font-semibold text-sm">Uploaded Files</h2>
          </div>
          <p class="text-xs text-muted-foreground">{{ files.length }} file(s) available</p>
        </div>

        <div class="flex-1 overflow-y-auto p-3 space-y-2">
          <div v-if="isLoading" class="text-center py-8">
            <iconify-icon icon="eos-icons:loading" class="h-8 w-8 text-primary animate-spin mx-auto mb-2" />
            <p class="text-sm text-muted-foreground">Loading files...</p>
          </div>

          <button
            v-for="file in files"
            :key="file.file_uuid"
            @click="selectFile(file)"
            :class="[
              'w-full text-left p-3 rounded-lg transition-all text-sm shadow-sm',
              selectedFile?.file_uuid === file.file_uuid
                ? 'bg-primary text-primary-foreground border border-primary/40 shadow-md'
                : 'hover:bg-muted border border-border hover:border-primary/30 hover:shadow-md bg-card'
            ]"
          >
            <div class="flex items-center gap-2 mb-1">
              <iconify-icon
                icon="lucide:file-spreadsheet"
                :class="[
                  'h-5 w-5 shrink-0',
                  selectedFile?.file_uuid === file.file_uuid ? 'text-primary-foreground' : 'text-primary'
                ]"
              />
              <div class="font-medium truncate flex-1">{{ file.filename }}</div>
            </div>
            <div :class="['text-xs flex items-center gap-1', selectedFile?.file_uuid === file.file_uuid ? 'text-primary-foreground/80' : 'text-muted-foreground']">
              <iconify-icon icon="lucide:table" class="h-3 w-3" />
              {{ file.total_rows }} rows • {{ file.columns.length }} cols
            </div>
          </button>

          <div v-if="files.length === 0 && !isLoading" class="text-center py-12">
            <iconify-icon icon="lucide:inbox" class="h-12 w-12 text-muted-foreground/40 mx-auto mb-3" />
            <p class="text-sm text-muted-foreground font-medium mb-1">No files uploaded</p>
            <p class="text-xs text-muted-foreground/60 mb-3">Upload an Excel file to get started</p>
            <Button
              variant="outline"
              size="sm"
              class="shadow-sm"
              @click="router.push('/app')"
            >
              <iconify-icon icon="lucide:upload" class="h-3 w-3 mr-1" />
              Upload File
            </Button>
          </div>
        </div>
      </template>

      <!-- ETL Databases Section -->
      <template v-else>
        <div class="p-4 border-b bg-card">
          <div class="flex items-center gap-2 mb-1">
            <iconify-icon icon="lucide:database" class="h-4 w-4 text-primary" />
            <h2 class="font-semibold text-sm">ETL Databases</h2>
          </div>
          <p class="text-xs text-muted-foreground">Select a database table</p>
        </div>
        <div class="flex-1 overflow-y-auto px-3 pb-3 space-y-3 pt-3">
          <div v-for="conn in datasets" :key="conn.connection_id" class="space-y-1">
            <details class="group border rounded-lg bg-card shadow-sm mt-2 open:shadow-md cursor-pointer overflow-hidden transition-all">
              <summary class="flex items-center gap-2 p-3 font-semibold text-sm text-foreground hover:bg-muted/50 outline-none select-none">
                <iconify-icon icon="lucide:database" class="text-primary h-4 w-4" />
                <span class="truncate">{{ conn.name }}</span>
                <iconify-icon icon="lucide:chevron-down" class="h-4 w-4 ml-auto transition-transform group-open:-rotate-180 text-muted-foreground" />
              </summary>
              <div class="px-2 pb-2 space-y-1 border-t border-border/40 bg-muted/20">
                <template v-for="job in conn.jobs" :key="job.job_id">
                  <button
                    v-for="table in job.tables"
                    :key="table.table_id"
                    @click="selectDataset(table)"
                    :class="[
                      'w-full text-left p-3 mt-1 rounded-lg transition-all text-sm shadow-sm',
                      selectedFile?.file_uuid === table.table_id
                        ? 'bg-primary text-primary-foreground border border-primary/40 shadow-md'
                        : 'hover:bg-muted border border-border hover:border-primary/30 hover:shadow-md bg-card'
                    ]"
                  >
                    <div class="flex items-center gap-2 mb-1">
                      <iconify-icon
                        icon="lucide:table"
                        :class="[
                          'h-5 w-5 shrink-0',
                          selectedFile?.file_uuid === table.table_id ? 'text-primary-foreground' : 'text-primary'
                        ]"
                      />
                      <div class="font-medium truncate flex-1">{{ table.table_name || table.source_name }}</div>
                    </div>
                    <div :class="['text-xs flex items-center gap-1', selectedFile?.file_uuid === table.table_id ? 'text-primary-foreground/80' : 'text-muted-foreground']">
                      {{ table.row_count || 0 }} rows
                    </div>
                  </button>
                </template>
              </div>
            </details>
          </div>
        </div>
      </template>

      <div class="p-4 border-t space-y-2 bg-card">
        <Button
          variant="outline"
          size="sm"
          class="w-full"
          @click="() => sidebarManuallyHidden = true"
        >
          Hide Panel
        </Button>
        <Button
          variant="outline"
          size="sm"
          class="w-full"
          @click="router.push('/app')"
        >
          <iconify-icon icon="lucide:plus" class="h-4 w-4 mr-1" />
          Upload
        </Button>
      </div>
    </div>

    <!-- Chat Area -->
    <div class="flex-1 flex flex-col" :class="props.fileId ? 'h-full' : 'bg-background chat-area-bg'">
      <!-- Header - Only show in Root Directory mode (embedded mode uses documents page header) -->
      <div v-if="!props.fileId" class="border-b border-border/30 flex items-center justify-between bg-background/70 backdrop-blur-2xl p-4">
        <div class="flex items-center gap-3">
          <Button
            v-if="!showFileSidebar && !props.fileId"
            variant="ghost"
            size="sm"
            @click="() => sidebarManuallyHidden = false"
          >
            <iconify-icon icon="lucide:menu" class="h-4 w-4" />
          </Button>
          <div v-if="!props.fileId">
            <div class="flex items-center gap-2">
              <iconify-icon v-if="selectedFile" icon="lucide:file-text" class="h-4 w-4 text-primary" />
              <h1 class="font-semibold" :class="props.fileId ? 'text-base' : 'text-lg'">
                <span v-if="selectedFile">{{ selectedFile.filename }}</span>
                <span v-else class="text-muted-foreground">Select a file to chat</span>
              </h1>
            </div>
            <p v-if="selectedFile" class="text-xs text-muted-foreground mt-0.5">
              {{ selectedFile.total_rows }} rows • {{ selectedFile.columns.length }} columns
            </p>
          </div>
        </div>
        <div v-if="selectedFile && messages.length > 0" class="flex gap-2">
          <Button
            variant="outline"
            size="sm"
            @click="clearChat"
            title="Clear chat history"
            class="rounded-lg hover:bg-destructive/5 hover:text-destructive hover:border-destructive/30"
          >
            <iconify-icon icon="lucide:trash-2" class="h-4 w-4 mr-1" />
            Clear
          </Button>
          <Button
            variant="outline"
            size="sm"
            @click="downloadChat"
            title="Download chat as text"
            class="rounded-lg hover:bg-muted hover:text-primary hover:border-primary/30"
          >
            <iconify-icon icon="lucide:download" class="h-4 w-4" :class="props.fileId ? '' : 'mr-1'" />
            <span v-if="!props.fileId">Download Chat</span>
          </Button>
          <Button
            variant="outline"
            size="sm"
            @click="exportChatAsJSON"
            title="Export chat as JSON"
            class="rounded-lg hover:bg-muted hover:text-primary hover:border-primary/30"
          >
            <iconify-icon icon="lucide:file-json" class="h-4 w-4" :class="props.fileId ? '' : 'mr-1'" />
            <span v-if="!props.fileId">JSON</span>
          </Button>
        </div>
      </div>

      <!-- Messages -->
      <div ref="messagesContainer" class="flex-1 overflow-y-auto" :class="props.fileId ? 'p-2 space-y-2' : 'p-4 sm:p-6 space-y-3'">
        <div v-if="!selectedFile" class="h-full flex items-center justify-center">
          <div class="text-center space-y-4">
            <div class="w-16 h-16 rounded-2xl bg-gradient-to-br from-primary/10 to-primary/5 flex items-center justify-center mx-auto ring-1 ring-primary/10">
              <iconify-icon icon="lucide:message-square-text" class="h-8 w-8 text-primary/40" />
            </div>
            <div>
              <p class="font-semibold text-lg text-foreground">Start a conversation</p>
              <p class="text-sm text-muted-foreground">Select a file from the sidebar to begin</p>
            </div>
          </div>
        </div>

        <div v-else class="space-y-2">
          <div v-if="hasMoreHistory" class="flex justify-center">
            <Button
              variant="ghost"
              size="sm"
              :disabled="isLoadingHistory"
              @click="loadMoreHistory"
              class="text-xs text-muted-foreground transition-all duration-200 ease-out hover:text-foreground"
            >
              <span v-if="isLoadingHistory" class="flex items-center gap-2">
                <iconify-icon icon="eos-icons:loading" class="h-3.5 w-3.5 animate-spin" />
                Loading...
              </span>
              <span v-else>Load more messages</span>
            </Button>
          </div>
          <transition-group name="message" tag="div" class="space-y-2">
            <div
              v-for="message in messages"
              :key="message.id"
              :class="getMessageClass(message)"
              class="message-item"
            >
            <!-- Thinking Indicator -->
            <div v-if="message.content === 'thinking'" class="flex items-start gap-3 max-w-xl">
              <div class="flex-shrink-0 w-7 h-7 rounded-full bg-gradient-to-br from-primary/20 to-primary/5 flex items-center justify-center ring-1 ring-primary/10">
                <iconify-icon icon="lucide:sparkles" class="h-3.5 w-3.5 text-primary/70" />
              </div>
              <div class="flex-1 bg-card/60 backdrop-blur-sm rounded-2xl rounded-tl-sm px-4 py-3 border border-border/20">
                <div class="flex items-center gap-2">
                  <div class="thinking-dots">
                    <span></span>
                    <span></span>
                    <span></span>
                  </div>
                  <span class="text-sm text-muted-foreground animate-pulse">Analyzing your question...</span>
                </div>
              </div>
            </div>

            <!-- Chart Display for PLOT queries -->
            <div v-else-if="message.chartData && message.queryType === 'PLOT'" class="w-full max-w-full">
              <div class="bg-card/60 backdrop-blur-sm rounded-2xl border border-border/20 overflow-hidden shadow-sm shadow-black/[0.02] dark:shadow-white/[0.02]">
                <div class="px-4 py-3 border-b border-border/20 flex items-center justify-between">
                  <div class="flex items-center gap-2">
                    <iconify-icon icon="lucide:bar-chart-3" class="h-4 w-4 text-primary/70" />
                    <span class="text-sm font-medium text-foreground">{{ message.chartData.title || 'Visualization' }}</span>
                    <span v-if="message.cacheHit" class="text-emerald-600 text-[10px] font-medium bg-emerald-500/10 px-1.5 py-0.5 rounded-md">CACHE</span>
                  </div>
                  <div class="flex items-center gap-1.5">
                    <Button
                      variant="ghost"
                      size="sm"
                      @click="downloadChartAsImage(message)"
                      class="h-7 rounded-lg text-muted-foreground hover:text-foreground"
                    >
                      <iconify-icon icon="lucide:download" class="h-4 w-4 mr-1" />
                      Download PNG
                    </Button>
                    <Button
                      v-if="message.cacheHit"
                      variant="ghost"
                      size="sm"
                      @click="bypassCache(message)"
                      class="h-7 rounded-lg text-muted-foreground hover:text-foreground"
                    >
                      <iconify-icon icon="lucide:rotate-ccw" class="h-3.5 w-3.5 mr-1" />
                      Regenerate
                    </Button>
                    <Button
                      v-if="!message.id.startsWith('sys-') && message.role !== 'user'"
                      variant="ghost"
                      size="icon"
                      @click="removeMessageFromView(message)"
                      class="h-7 w-7 text-muted-foreground hover:text-destructive transition-colors"
                      title="Remove from Chat"
                      aria-label="Remove"
                    >
                      <iconify-icon icon="lucide:x" class="h-3.5 w-3.5" />
                    </Button>
                    <button
                      v-if="langfuseOn && hasTraceLink(message)"
                      @click="openTraceForMessage(message)"
                      class="h-7 w-7 flex items-center justify-center text-muted-foreground hover:text-primary transition-colors rounded-lg"
                      title="View Langfuse trace"
                      aria-label="View trace"
                    >
                      <iconify-icon icon="lucide:activity" class="h-3.5 w-3.5" />
                    </button>
                  </div>
                </div>
                <div class="p-4">
                  <ChartViewer :chart-data="message.chartData" />
                </div>
              </div>
            </div>

            <!-- Table Display for structured data -->
            <div v-else-if="message.tableData" class="w-full max-w-4xl">
              <div class="bg-card/60 backdrop-blur-sm rounded-2xl border border-border/20 overflow-hidden shadow-sm shadow-black/[0.02] dark:shadow-white/[0.02]">
                <div class="px-4 py-3 border-b border-border/20 flex items-center justify-between">
                  <div class="flex items-center gap-2">
                    <iconify-icon icon="lucide:table" class="h-4 w-4 text-primary/70" />
                    <span class="text-sm font-medium text-foreground">{{ message.content }}</span>
                    <span v-if="message.cacheHit" class="text-emerald-600 text-[10px] font-medium bg-emerald-500/10 px-1.5 py-0.5 rounded-md">CACHE</span>
                  </div>
                  <div class="flex items-center gap-1.5">
                    <Button
                      variant="ghost"
                      size="sm"
                      @click="exportTableToCSV(message.tableData)"
                      class="h-7 rounded-lg text-muted-foreground hover:text-foreground"
                    >
                      <iconify-icon icon="lucide:download" class="h-3.5 w-3.5 mr-1" />
                      Export CSV
                    </Button>
                    <Button
                      v-if="!message.id.startsWith('sys-') && message.role !== 'user'"
                      variant="ghost"
                      size="icon"
                      @click="removeMessageFromView(message)"
                      class="h-7 w-7 text-muted-foreground hover:text-destructive transition-colors"
                      title="Remove from Chat"
                      aria-label="Remove"
                    >
                      <iconify-icon icon="lucide:x" class="h-3.5 w-3.5" />
                    </Button>
                    <button
                      v-if="langfuseOn && hasTraceLink(message)"
                      @click="openTraceForMessage(message)"
                      class="h-7 w-7 flex items-center justify-center text-muted-foreground hover:text-primary transition-colors rounded-lg"
                      title="View Langfuse trace"
                      aria-label="View trace"
                    >
                      <iconify-icon icon="lucide:activity" class="h-3.5 w-3.5" />
                    </button>
                  </div>
                </div>
                <div class="overflow-x-auto max-h-96">
                  <table class="w-full text-sm">
                    <thead class="bg-muted/40 sticky top-0">
                      <tr>
                        <th class="px-3 py-2 text-left font-medium text-[11px] uppercase tracking-wider border-b border-border/30 text-muted-foreground">#</th>
                        <th 
                          v-for="col in message.tableData.columns" 
                          :key="col"
                          class="px-3 py-2 text-left font-medium text-[11px] uppercase tracking-wider border-b border-border/30 text-muted-foreground"
                        >
                          {{ col }}
                        </th>
                      </tr>
                    </thead>
                    <tbody class="divide-y divide-border">
                      <tr 
                        v-for="(row, idx) in message.tableData.data" 
                        :key="idx"
                        class="hover:bg-muted/60 transition-colors"
                      >
                        <td class="px-3 py-2 text-xs text-muted-foreground border-r font-medium">{{ idx + 1 }}</td>
                        <td 
                          v-for="col in message.tableData.columns" 
                          :key="col"
                          class="px-3 py-2 text-foreground"
                        >
                          {{ row[col] }}
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </div>
                <div class="px-4 py-2 border-t border-border/20 text-xs flex items-center justify-between">
                  <span class="text-muted-foreground">{{ message.tableData.message }}</span>
                  <div class="flex items-center gap-2">
                    <Button
                      v-if="message.cacheHit"
                      variant="ghost"
                      size="sm"
                      @click="bypassCache(message)"
                      class="h-6 px-2 text-xs rounded-lg"
                    >
                      <iconify-icon icon="lucide:rotate-ccw" class="h-3 w-3 mr-1" />
                      Regenerate
                    </Button>
                    <span class="text-muted-foreground/70">
                      <iconify-icon icon="lucide:info" class="h-3 w-3 inline mr-1" />
                      Export CSV to save
                    </span>
                  </div>
                </div>
              </div>
            </div>

            <!-- Session Lifecycle Event -->
            <div v-else-if="message.sessionEvent" class="w-full flex justify-center px-4 py-1">
              <button
                v-if="langfuseOn && message.sessionId"
                @click="openLangfuseSession(message.sessionId)"
                :disabled="openingLangfuseSessionId === message.sessionId"
                class="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-muted/30 border border-border/20 hover:bg-muted/50 hover:border-border/40 transition-all cursor-pointer group"
              >
                <iconify-icon
                  v-if="openingLangfuseSessionId === message.sessionId"
                  icon="eos-icons:loading"
                  class="h-3 w-3 text-muted-foreground/60 animate-spin"
                />
                <iconify-icon
                  v-else
                  :icon="message.sessionEvent === 'join' ? 'lucide:play-circle' : 'lucide:stop-circle'"
                  :class="message.sessionEvent === 'join' ? 'h-3 w-3 text-emerald-500/70' : 'h-3 w-3 text-muted-foreground/50'"
                />
                <span class="text-[11px] text-muted-foreground/70 group-hover:text-foreground/70 transition-colors">
                  {{ message.sessionEvent === 'join' ? 'Session started' : 'Session ended' }}
                </span>
                <span class="text-[10px] text-muted-foreground/40">{{ formatTime(message.timestamp) }}</span>
              </button>
              <div
                v-else
                class="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-muted/30 border border-border/20"
              >
                <iconify-icon
                  :icon="message.sessionEvent === 'join' ? 'lucide:play-circle' : 'lucide:stop-circle'"
                  :class="message.sessionEvent === 'join' ? 'h-3 w-3 text-emerald-500/70' : 'h-3 w-3 text-muted-foreground/50'"
                />
                <span class="text-[11px] text-muted-foreground/70">
                  {{ message.sessionEvent === 'join' ? 'Session started' : 'Session ended' }}
                </span>
                <span class="text-[10px] text-muted-foreground/40">{{ formatTime(message.timestamp) }}</span>
              </div>
            </div>

            <!-- Regular Message Display -->
            <template v-else>
              <!-- Assistant message with avatar -->
              <div v-if="message.role === 'assistant'" class="flex items-start gap-2.5 max-w-xs lg:max-w-2xl">
                <div class="flex-shrink-0 w-7 h-7 rounded-full bg-gradient-to-br from-primary/20 to-primary/5 flex items-center justify-center mt-1 ring-1 ring-primary/10">
                  <iconify-icon icon="lucide:sparkles" class="h-3.5 w-3.5 text-primary/70" />
                </div>
                <div class="flex-1 min-w-0 bg-card/60 backdrop-blur-sm rounded-2xl rounded-tl-sm px-4 py-2.5 border border-border/20 group relative shadow-sm shadow-black/[0.02] dark:shadow-white/[0.02]">
                  <div class="text-sm break-words prose prose-sm max-w-none" v-html="renderMarkdown(message.content)" />
                  <div class="flex items-center justify-between mt-2">
                    <div class="flex items-center gap-2 text-xs opacity-60">
                      <span v-if="message.queryType">[{{ message.queryType }}]</span>
                      <span v-if="message.cacheHit" class="text-emerald-600 text-[10px] font-medium bg-emerald-500/10 px-1.5 py-0.5 rounded-md">CACHE</span>
                      <span v-if="message.responseTime" class="text-primary font-medium">⏱ {{ message.responseTime.toFixed(2) }}s</span>
                      <span>{{ formatTime(message.timestamp) }}</span>
                    </div>
                    <div class="flex items-center gap-1">
                      <Button
                        v-if="langfuseOn && message.sessionEvent && message.sessionId"
                        variant="outline"
                        size="sm"
                        @click="openLangfuseSession(message.sessionId)"
                        :disabled="openingLangfuseSessionId === message.sessionId"
                        class="h-6 px-2 text-xs"
                      >
                        <iconify-icon
                          :icon="openingLangfuseSessionId === message.sessionId ? 'eos-icons:loading' : 'lucide:external-link'"
                          :class="openingLangfuseSessionId === message.sessionId ? 'h-3 w-3 mr-1 animate-spin' : 'h-3 w-3 mr-1'"
                        />
                        Open Langfuse Session
                      </Button>
                      <Button
                        v-if="message.cacheHit"
                        variant="outline"
                        size="sm"
                        @click="bypassCache(message)"
                        class="h-6 px-2 text-xs"
                      >
                        <iconify-icon icon="lucide:rotate-ccw" class="h-3 w-3 mr-1" />
                        Regenerate
                      </Button>
                      <Button
                        v-if="message.content !== 'thinking' && !message.id.startsWith('sys-') && !message.sessionEvent"
                        variant="ghost"
                        size="icon"
                        class="h-6 w-6 opacity-0 group-hover:opacity-80 hover:!opacity-100 hover:text-destructive transition-all"
                        @click="removeMessageFromView(message)"
                        title="Remove from Chat"
                        aria-label="Remove"
                      >
                        <iconify-icon icon="lucide:x" class="h-3.5 w-3.5" />
                      </Button>
                      <Button
                        v-if="message.content !== 'File uploaded successfully' && message.content !== 'thinking' && !message.chartData && !message.tableData"
                        variant="ghost"
                        size="icon"
                        class="h-6 w-6 opacity-0 group-hover:opacity-80 hover:!opacity-100 transition-all"
                        @click="copyToClipboard(message.content, message.id)"
                        :title="copiedMessageId === message.id ? 'Copied!' : 'Copy to clipboard'"
                        aria-label="Copy to clipboard"
                      >
                        <iconify-icon :icon="copiedMessageId === message.id ? 'lucide:check' : 'lucide:copy'" :class="copiedMessageId === message.id ? 'h-3 w-3 text-emerald-500' : 'h-3 w-3'" />
                      </Button>
                      <button
                        v-if="langfuseOn && hasTraceLink(message)"
                        @click="openTraceForMessage(message)"
                        class="h-6 w-6 flex items-center justify-center opacity-0 group-hover:opacity-80 hover:!opacity-100 text-muted-foreground hover:text-primary transition-all rounded-lg"
                        title="View Langfuse trace"
                        aria-label="View trace"
                      >
                        <iconify-icon icon="lucide:activity" class="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </div>
                </div>
              </div>
              <!-- User message -->
              <div v-else class="flex items-end gap-2">
              <div class="bg-gradient-to-br from-primary/95 to-primary/80 text-primary-foreground rounded-2xl rounded-tr-sm px-4 py-2.5 max-w-xs lg:max-w-md shadow-sm shadow-primary/10 group relative">
                <div class="text-sm whitespace-pre-wrap break-words">{{ message.content }}</div>
                <div class="flex items-center justify-between mt-2">
                  <div class="flex items-center gap-2 text-xs text-primary-foreground/70">
                    <span>{{ formatTime(message.timestamp) }}</span>
                  </div>
                  <div class="flex items-center gap-1">
                    <Popover v-if="!message.id.startsWith('sys-')" @update:open="(v: boolean) => { if (v) loadCategories() }">
                      <PopoverTrigger as-child>
                        <Button
                          variant="ghost"
                          size="icon"
                          class="h-6 w-6 opacity-0 group-hover:opacity-80 hover:!opacity-100 text-primary-foreground hover:text-primary-foreground/80 transition-all"
                          title="Bookmark question"
                          aria-label="Bookmark question"
                        >
                          <iconify-icon icon="lucide:bookmark" class="h-3.5 w-3.5" />
                        </Button>
                      </PopoverTrigger>
                      <PopoverContent class="w-60 p-3" side="left">
                        <div class="space-y-2">
                          <p class="text-xs font-semibold text-foreground">Save question under:</p>

                          <div v-if="isLoadingCategories" class="text-center py-3">
                            <iconify-icon icon="svg-spinners:180-ring-with-bg" class="h-4 w-4 text-muted-foreground" />
                          </div>

                          <div v-else class="max-h-48 overflow-y-auto space-y-1">
                            <!-- All categories: default first, then custom -->
                            <button
                              v-for="cat in availableCategories"
                              :key="cat.name"
                              class="w-full text-left text-xs px-2.5 py-2 rounded-md border hover:bg-muted/50 transition-colors flex items-center gap-2"
                              :disabled="isBookmarking"
                              @click="bookmarkWithCategory(message, cat.name)"
                            >
                              <iconify-icon
                                :icon="cat.is_default
                                  ? (cat.name === 'Generic' ? 'lucide:globe' : 'lucide:target')
                                  : 'lucide:tag'"
                                :class="cat.is_default
                                  ? (cat.name === 'Generic' ? 'h-3.5 w-3.5 text-primary' : 'h-3.5 w-3.5 text-primary')
                                  : 'h-3.5 w-3.5 text-amber-500'"
                              />
                              <span class="flex-1 truncate">{{ cat.name }}</span>
                              <span v-if="!cat.is_default" class="text-[10px] text-muted-foreground/60 flex-shrink-0">Custom</span>
                            </button>
                          </div>

                          <!-- Divider -->
                          <div class="border-t border-border/50"></div>

                          <!-- Create custom category -->
                          <div v-if="showNewCategoryInput" class="flex items-center gap-1.5">
                            <Input
                              v-model="newCustomCategoryName"
                              placeholder="Category name"
                              class="h-7 text-xs flex-1"
                              @keyup.enter="createCustomCategory"
                              autofocus
                            />
                            <Button variant="default" size="sm" class="h-7 px-2 text-[10px]" @click="createCustomCategory" :disabled="!newCustomCategoryName.trim()">
                              <iconify-icon icon="lucide:check" class="h-3 w-3" />
                            </Button>
                            <Button variant="ghost" size="sm" class="h-7 w-7 px-0" @click="showNewCategoryInput = false; newCustomCategoryName = ''">
                              <iconify-icon icon="lucide:x" class="h-3 w-3" />
                            </Button>
                          </div>
                          <button
                            v-else
                            class="w-full text-left text-xs px-2.5 py-1.5 rounded-md border border-dashed hover:bg-muted/30 transition-colors flex items-center gap-2 text-muted-foreground hover:text-foreground"
                            @click="showNewCategoryInput = true; newCustomCategoryName = ''"
                          >
                            <iconify-icon icon="lucide:plus" class="h-3 w-3" /> Create custom category
                          </button>
                        </div>
                      </PopoverContent>
                    </Popover>
                  </div>
                </div>
              </div>
              <!-- User avatar (Bitmoji style) -->
              <div class="flex-shrink-0 w-7 h-7 rounded-full mb-1 shrink-0 overflow-hidden">
                <img v-if="userAvatarUrl" :src="userAvatarUrl" alt="You" class="w-full h-full object-cover rounded-full" />
                <svg v-else viewBox="0 0 128 128" class="w-full h-full" aria-label="You">
                  <!-- Gradient bg -->
                  <defs><linearGradient id="abg" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stop-color="#60a5fa"/><stop offset="100%" stop-color="#818cf8"/></linearGradient></defs>
                  <circle cx="64" cy="64" r="64" fill="url(#abg)"/>
                  <!-- Neck -->
                  <rect x="52" y="80" width="24" height="22" rx="4" fill="#FDDCB1"/>
                  <!-- Face -->
                  <ellipse cx="64" cy="60" rx="28" ry="33" fill="#FDDCB1"/>
                  <!-- Hair -->
                  <ellipse cx="64" cy="32" rx="30" ry="20" fill="#3B2314"/>
                  <!-- Eyes -->
                  <ellipse cx="52" cy="57" rx="4.5" ry="4" fill="#fff"/><ellipse cx="76" cy="57" rx="4.5" ry="4" fill="#fff"/>
                  <circle cx="53" cy="57" r="2.5" fill="#2C1810"/><circle cx="77" cy="57" r="2.5" fill="#2C1810"/>
                  <circle cx="51.5" cy="55.5" r="1" fill="#fff"/><circle cx="75.5" cy="55.5" r="1" fill="#fff"/>
                  <!-- Smile -->
                  <path d="M55 73 Q64 82 73 73" stroke="#C48A5C" stroke-width="2" fill="none" stroke-linecap="round"/>
                  <!-- Blush -->
                  <ellipse cx="44" cy="70" rx="5" ry="3" fill="rgba(255,130,130,0.2)"/>
                  <ellipse cx="84" cy="70" rx="5" ry="3" fill="rgba(255,130,130,0.2)"/>
                </svg>
              </div>
              </div>
            </template>
            </div>
          </transition-group>
        </div>
      </div>

      <!-- Input Area -->
      <div v-if="selectedFile" class="border-t border-border/30 bg-background/70 backdrop-blur-2xl" :class="props.fileId ? 'px-2 py-1.5' : 'px-4 py-3'">
        <!-- Quick Suggestions (shown when no messages) -->
        <div v-if="messages.length === 0" class="mb-3">
          <p class="text-xs font-medium text-muted-foreground mb-2">Try asking:</p>
          <div class="flex flex-wrap gap-2">
            <button
              v-for="suggestion in quickSuggestions"
              :key="suggestion"
              @click="inputMessage = suggestion"
              class="px-3 py-1.5 text-xs bg-card/60 border border-border/20 rounded-full hover:bg-primary/5 hover:border-primary/20 hover:text-primary transition-all backdrop-blur-sm"
            >
              {{ suggestion }}
            </button>
          </div>
        </div>
        
        <div class="flex gap-2">
          <div class="flex-1 relative">
            <Input
              v-model="inputMessage"
              placeholder="Ask a question about your data..."
              @keyup.enter="sendMessage"
              :disabled="isSending"
              class="pr-10 rounded-xl bg-card/50 border-border/30 focus:border-primary/40 shadow-none"
            />
            <button
              v-if="inputMessage"
              @click="inputMessage = ''"
              class="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground/60 hover:text-muted-foreground transition-colors"
              title="Clear input"
            >
              <iconify-icon icon="lucide:x" class="h-4 w-4" />
            </button>
          </div>
          <Button
            @click="sendMessage"
            :disabled="!inputMessage.trim() || isSending"
            class="min-w-[100px] rounded-xl shadow-none"
          >
            <iconify-icon v-if="isSending" icon="eos-icons:loading" class="h-4 w-4 mr-2 animate-spin" />
            <iconify-icon v-else icon="lucide:send" class="h-4 w-4 mr-2" />
            {{ isSending ? 'Processing...' : 'Send' }}
          </Button>
        </div>
      </div>

      <!-- No File Selected State -->
      <div v-else class="border-t border-border/30 p-6 bg-background/70 backdrop-blur-2xl text-center">
        <div class="w-12 h-12 rounded-2xl bg-gradient-to-br from-primary/10 to-primary/5 flex items-center justify-center mx-auto mb-3 ring-1 ring-primary/10">
          <iconify-icon icon="lucide:message-square-text" class="h-6 w-6 text-primary/40" />
        </div>
        <p class="text-sm text-muted-foreground font-medium">Select a file to start chatting</p>
        <p class="text-xs text-muted-foreground/60 mt-1">Upload an Excel file to begin analyzing your data</p>
      </div>
    </div>
  </div>

  <!-- Change Password Modal -->
  <ChangePasswordModal
    v-if="showChangePasswordModal"
    @close="showChangePasswordModal = false"
  />
</template>

<style scoped>
/* Subtle chat area background */
.chat-area-bg {
  background-image:
    radial-gradient(ellipse at 20% 80%, oklch(0.85 0.03 160 / 0.08) 0%, transparent 50%),
    radial-gradient(ellipse at 80% 20%, oklch(0.85 0.04 280 / 0.06) 0%, transparent 50%);
}

:is(.dark) .chat-area-bg {
  background-image:
    radial-gradient(ellipse at 20% 80%, oklch(0.25 0.02 160 / 0.12) 0%, transparent 50%),
    radial-gradient(ellipse at 80% 20%, oklch(0.25 0.03 280 / 0.08) 0%, transparent 50%);
}

/* Chat container scroll behavior */
:deep(.overflow-y-auto) {
  scroll-behavior: smooth;
}

/* Message entrance animation */
.message-enter-active,
.message-enter-to {
  transition: all 0.4s ease-out;
}

.message-enter-from {
  opacity: 0;
  transform: translateY(20px);
}

.message-leave-active {
  transition: all 0.3s ease-in;
}

.message-leave-to {
  opacity: 0;
  transform: translateX(-10px);
}

.message-item {
  transition: all 0.3s ease;
}

/* Thinking indicator animation */
.thinking-dots {
  display: inline-flex;
  gap: 4px;
  align-items: center;
}

.thinking-dots span {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background-color: var(--primary);
  opacity: 0.6;
  animation: bounce 1.4s infinite ease-in-out both;
}

.thinking-dots span:nth-child(1) {
  animation-delay: -0.32s;
}

.thinking-dots span:nth-child(2) {
  animation-delay: -0.16s;
}

@keyframes bounce {
  0%, 80%, 100% {
    transform: scale(0);
    opacity: 0.5;
  }
  40% {
    transform: scale(1);
    opacity: 1;
  }
}
</style>
