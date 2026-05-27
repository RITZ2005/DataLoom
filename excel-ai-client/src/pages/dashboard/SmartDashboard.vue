<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, nextTick, computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useDocumentsStore } from '@/store/documents'
import excelFileAPI, { type DashboardWidget, type DashboardResponse, type DashboardFingerprint, type FileInfo, type DualWidgetResponse, type UnifiedCompareResponse, type BoardDashboardSaveRequest } from '@/services/excelApi'
import FileSystemNode from '@/pages/documents/FileSystemNode.vue'
import { buildFileTree, type TreeNode } from '@/utils/fileTree'
import LeftSidebar from '@/components/dashboard/LeftSidebar.vue'
import WidgetFloatingToolbar from '@/components/dashboard/WidgetFloatingToolbar.vue'
import RightProperties from '@/components/dashboard/RightProperties.vue'
import ERDWidget from '@/components/dashboard/ERDWidget.vue'
import { toast } from 'vue-sonner'
import { GridStack } from 'gridstack'
import 'gridstack/dist/gridstack.min.css'
import html2canvas from 'html2canvas-pro'
import jsPDF from 'jspdf'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { BarChart, FunnelChart, GaugeChart, HeatmapChart, LineChart, PieChart, ScatterChart, TreemapChart } from 'echarts/charts'
import { TitleComponent, TooltipComponent, LegendComponent, GridComponent, DataZoomComponent, VisualMapComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
use([BarChart, FunnelChart, GaugeChart, HeatmapChart, LineChart, PieChart, ScatterChart, TreemapChart, TitleComponent, TooltipComponent, LegendComponent, GridComponent, DataZoomComponent, VisualMapComponent, CanvasRenderer])

const route = useRoute()
const router = useRouter()
const store = useDocumentsStore()

// ── STATE ──────────────────────────────────────────────────────
const fileInfo = ref<FileInfo | null>(null)
const widgets = ref<DashboardWidget[]>([])
const isLoading = ref(false)
const isGeneratingPendingScreen = ref(false)
const isAddingWidget = ref(false)
const newWidgetQuery = ref('')
const dashboardData = ref<DashboardResponse | null>(null)
const isDashboardLocked = ref(false)

let grid: GridStack | null = null
const gridContainer = ref<HTMLElement | null>(null)
const exportContainer = ref<HTMLElement | null>(null)
let persistTimer: ReturnType<typeof setTimeout> | null = null
// Debounced timer for backend dashboard auto-save (dashboard projects only)
let backendPersistTimer: ReturnType<typeof setTimeout> | null = null

const showCommandPalette = ref(false)
const commandQuery = ref('')
const commandInputRef = ref<HTMLInputElement | null>(null)
const crossFilter = ref<{ key: string; value: string } | null>(null)
const fingerprint = ref<DashboardFingerprint | null>(null)
const originalFingerprint = ref<DashboardFingerprint | null>(null)  // Stable fingerprint for slicers
const slicerValues = ref<Record<string, string>>({})
const originalWidgets = ref<DashboardWidget[]>([])
const isFiltering = ref(false)
const showAddPopover = ref(false)
const addPopoverRef = ref<HTMLElement | null>(null)
const activeTheme = ref('indigo')
const showThemePicker = ref(false)
const themeTriggerRef = ref<HTMLElement | null>(null)
const themePickerRef = ref<HTMLElement | null>(null)
const themeMenuPosition = ref({ top: 0, left: 0 })
const showExportMenu = ref(false)
const exportTriggerRef = ref<HTMLElement | null>(null)
const exportMenuRef = ref<HTMLElement | null>(null)
const exportMenuPosition = ref({ top: 0, left: 0 })

// ── CUSTOM REQUIREMENTS (column hints for regeneration) ──────────────────────────────────────────
const userRequirements = ref('')
const showRequirementsPanel = ref(false)

// ── COMPARE MODE STATE ─────────────────────────────────────────
const showCompareSelector = ref(false)
const compareTriggerRef = ref<HTMLElement | null>(null)
const compareSelectorRef = ref<HTMLElement | null>(null)
const compareMenuPosition = ref({ top: 0, left: 0 })
const compareWidgets = ref<DashboardWidget[]>([])
const originalCompareWidgets = ref<DashboardWidget[]>([])
const compareFileInfo = ref<FileInfo | null>(null)
const compareFileId = ref<string | null>(null)
const isCompareMode = ref(false)
const isCompareLoading = ref(false)
const compareFingerprint = ref<DashboardFingerprint | null>(null)
let gridB: GridStack | null = null
const gridContainerB = ref<HTMLElement | null>(null)
const availableCompareFiles = ref<FileInfo[]>([])
const compareViewMode = ref<'split' | 'unified'>('split')
const unifiedWidgets = ref<DashboardWidget[]>([])
const isUnifiedLoading = ref(false)
const compareLoadError = ref<string | null>(null)
const isFileScreensMode = computed(() => !isBoardMode.value && !isDashboardProject.value && !isSharedMode.value)
const shouldPersistStudioState = computed(() => isBoardMode.value || isFileScreensMode.value)

// ── FILE SIDEBAR STATE ────────────────────────────────────────
const sidebarOpen = ref(true)
const studioTab = ref<'elements' | 'screens' | 'design'>('elements')

type BoardScreen = { id: string; name: string }
const boardScreens = ref<BoardScreen[]>([
  { id: 'screen-1', name: 'Dashboard' },
])
const activeScreenId = ref('screen-1')
const boardScreenWidgets = ref<Record<string, DashboardWidget[]>>({
  'screen-1': [],
})
const boardFileScreenWidgets = ref<Record<string, Record<string, DashboardWidget[]>>>({})
const boardFileScreenNeedsGeneration = ref<Record<string, Record<string, boolean>>>({})
const boardFileScreenPendingTemplates = ref<Record<string, Record<string, DashboardWidget[]>>>({})
const templateSourceFileId = ref('')
const boardScreenThumbnails = ref<Record<string, string>>({})
const boardScreenShareTokens = ref<Record<string, string>>({})
const boardDesign = ref<{ texture: 'none' | 'dots' | 'grid' | 'gradient'; density: 'compact' | 'cozy' | 'airy'; cardStyle: 'flat' | 'soft' | 'glass' }>({
  texture: 'none',
  density: 'cozy',
  cardStyle: 'flat',
})

const canvasDesignClass = computed(() => [
  `design-texture-${boardDesign.value.texture}`,
  `design-density-${boardDesign.value.density}`,
  `design-card-${boardDesign.value.cardStyle}`,
])

const boardScreenPreviews = computed(() => {
  const previews: Record<string, { total: number; chart: number; kpi: number; insight: number; list: number; summary: number }> = {}
  for (const screen of boardScreens.value) {
    const items = screen.id === activeScreenId.value
      ? widgets.value
      : (Array.isArray(boardScreenWidgets.value[screen.id]) ? boardScreenWidgets.value[screen.id] : [])
    previews[screen.id] = {
      total: items.length,
      chart: items.filter((w: any) => w?.type === 'chart').length,
      kpi: items.filter((w: any) => w?.type === 'kpi').length,
      insight: items.filter((w: any) => w?.type === 'insight').length,
      list: items.filter((w: any) => w?.type === 'list').length,
      summary: items.filter((w: any) => w?.type === 'summary').length,
    }
  }
  return previews
})

const activeWidgetId = ref<string | null>(null)
const widgetToolbarPos = ref<{ top: number; left: number; visible: boolean }>({
  top: 0,
  left: 0,
  visible: false,
})
const isPreviewMode = ref(false)
const canvasZoom = ref(100)

// ── WIDGET UI CHANGE TRACKING (Force chart re-renders when UI changes) ──
const widgetRenderVersions = ref<Record<string, number>>({})

// ── CHART BUILDER (Looker Studio right sidebar) ───────────────
type ChartSchema = { dimensions: { col: string; cardinality: number }[]; measures: { col: string; agg: string }[] }

const chartBuilderOpen = ref(false)
const chartBuilderLoading = ref(false)
const chartSchema = ref<ChartSchema | null>(null)
const chartSchemaFileId = ref('')
const chartBuilderForm = ref({
  chartType: 'bar',
  dimension: '',
  measure: '',
  aggregation: 'sum',
})
const chartBuilderChartTypes = [
  { id: 'bar', label: 'Bar', icon: 'lucide:bar-chart-2' },
  { id: 'line', label: 'Line', icon: 'lucide:trending-up' },
  { id: 'area', label: 'Area', icon: 'lucide:mountain' },
  { id: 'combo', label: 'Combo', icon: 'lucide:chart-column-increasing' },
  { id: 'pie', label: 'Pie', icon: 'lucide:pie-chart' },
  { id: 'donut', label: 'Donut', icon: 'lucide:circle-dashed' },
  { id: 'scatter', label: 'Scatter', icon: 'lucide:scatter-chart' },
  { id: 'bubble', label: 'Bubble', icon: 'lucide:bubbles' },
  { id: 'histogram', label: 'Histogram', icon: 'lucide:chart-bar-big' },
  { id: 'funnel', label: 'Funnel', icon: 'lucide:funnel' },
  { id: 'gauge', label: 'Gauge', icon: 'lucide:gauge' },
  { id: 'heatmap', label: 'Heatmap', icon: 'lucide:grid-2x2' },
  { id: 'treemap', label: 'Treemap', icon: 'lucide:layout-grid' },
  { id: 'waterfall', label: 'Waterfall', icon: 'lucide:chart-column-stacked' },
]

const chartDimensionColumns = computed(() => (chartSchema.value?.dimensions || []).map(item => item.col))
const chartMeasureColumns = computed(() => (chartSchema.value?.measures || []).map(item => item.col))

const activeWidget = computed(() =>
  widgets.value.find(w => w.id === activeWidgetId.value) as any | undefined
)

const isHeaderCompact = computed(() => {
  // Prioritize title space when either side panel is expanded.
  return sidebarOpen.value || chartBuilderOpen.value || (!!activeWidgetId.value && !isPreviewMode.value)
})

const activeWidgetTypeLabel = computed(() => {
  const t = activeWidget.value?.type
  if (!t) return 'Widget'
  if (t === 'kpi') return 'KPI'
  if (t === 'chart') return 'Chart'
  if (t === 'list') return 'List'
  if (t === 'summary') return 'Header'
  if (t === 'erd') return 'ERD'
  return String(t).charAt(0).toUpperCase() + String(t).slice(1)
})

function ensureWidgetUiDefaults(widget: any) {
  if (!widget) return
  if (!widget.ui) widget.ui = {}
  if (typeof widget.ui.showTitle !== 'boolean') widget.ui.showTitle = true
  if (typeof widget.ui.titleText !== 'string') widget.ui.titleText = widget.title || ''
  if (typeof widget.ui.align !== 'string') widget.ui.align = 'left'
  if (typeof widget.ui.banding !== 'boolean') widget.ui.banding = false
  if (typeof widget.ui.widgetVariant !== 'string') widget.ui.widgetVariant = 'default'
  if (typeof widget.ui.titleLocked !== 'boolean') widget.ui.titleLocked = false
}

function getWidgetTitle(widget: any): string {
  ensureWidgetUiDefaults(widget)
  if (!widget.ui.showTitle) return ''
  const raw = String(widget.ui.titleText || widget.title || '').trim()
  if (!raw) return ''
  const deduped = raw.split(/\s+/).reduce((acc: string[], word: string) => {
    if (!acc.length || acc[acc.length - 1].toLowerCase() !== word.toLowerCase()) acc.push(word)
    return acc
  }, []).join(' ')
  return deduped
}

function getWidgetAlignClass(widget: any): string {
  ensureWidgetUiDefaults(widget)
  if (widget.ui.align === 'center') return 'text-center'
  if (widget.ui.align === 'right') return 'text-right'
  return 'text-left'
}

function getWidgetHeaderClass(widget: any): string[] {
  const type = (widget as any)?.type
  const toneClass = type === 'summary'
    ? 'text-[11px] font-bold tracking-wider text-indigo-600 dark:text-indigo-400'
    : type === 'kpi' || type === 'insight'
      ? 'text-[10px] font-semibold tracking-wide text-slate-500 dark:text-slate-400'
      : 'text-[10px] font-bold tracking-widest text-slate-400 dark:text-slate-500'

  return [toneClass, getWidgetAlignClass(widget)]
}

function isLikelyGarbageKpiValue(value: any): boolean {
  if (value === null || value === undefined) return true
  if (typeof value === 'number') return !Number.isFinite(value)

  const raw = String(value).trim()
  if (!raw) return true

  const lower = raw.toLowerCase()
  if (
    lower.includes('undefined') ||
    lower.includes('null') ||
    lower.includes('nan') ||
    lower.includes('inf') ||
    lower.includes('[object object]')
  ) {
    return true
  }

  if (/[{}\[\]<>]/.test(raw)) return true

  const alphaNumChars = (raw.match(/[a-z0-9]/gi) || []).length
  const symbolRatio = raw.length ? 1 - (alphaNumChars / raw.length) : 1
  if (symbolRatio > 0.55) return true

  if (raw.length > 48 && !/[0-9]/.test(raw)) return true

  return false
}

function sanitizeKpiWidgetPayload(widget: any, templateWidget?: any): any {
  if (!widget || widget.type !== 'kpi') return widget

  const templateValue = templateWidget?.value
  const fallbackValue = !isLikelyGarbageKpiValue(templateValue) ? templateValue : 'N/A'
  if (isLikelyGarbageKpiValue(widget.value)) {
    widget.value = fallbackValue
    if (!widget.subtitle) {
      widget.subtitle = 'Value unavailable for selected file'
    }
  }

  if (typeof widget.change === 'string' && widget.change.trim().length > 24) {
    widget.change = '0%'
  }

  if (!widget.trend || !['up', 'down', 'neutral'].includes(String(widget.trend))) {
    widget.trend = 'neutral'
  }

  return widget
}

function extractCurrencySymbol(value: any): string {
  const str = String(value || '')
  const match = str.match(/[$€£¥₹₽₩]/)
  return match ? match[0] : ''
}

function isCurrencyValue(value: any, title: string = ''): boolean {
  const str = String(value || '').toLowerCase()
  const titleStr = String(title || '').toLowerCase()
  return /[$€£¥₹₽₩]/.test(str) || /salary|fee|price|cost|revenue|income|expense/.test(titleStr)
}

function formatIndianNumber(num: number, decimals: number = 0): string {
  return num.toLocaleString('en-IN', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })
}

function getKpiDisplayValue(widget: any): string {
  ensureWidgetUiDefaults(widget)
  const sourceValue = widget?.ui?.overrideValue ? widget.ui.overrideValue : (widget?.value ?? 'N/A')
  const rawValue = isLikelyGarbageKpiValue(sourceValue) ? 'N/A' : sourceValue
  const prefix = String(widget?.ui?.prefix || '')
  const suffix = String(widget?.ui?.suffix || '')
  const decimals = Number.isFinite(widget?.ui?.decimals) ? Number(widget.ui.decimals) : 0
  const title = String(widget?.title || '')
  
  const parsed = typeof rawValue === 'number'
    ? rawValue
    : Number(String(rawValue).replace(/[^0-9.-]/g, ''))

  if (!Number.isNaN(parsed) && String(rawValue).match(/[0-9]/)) {
    const formatted = formatIndianNumber(parsed, decimals)
    const currencySymbol = isCurrencyValue(rawValue, title) ? extractCurrencySymbol(rawValue) || '₹' : ''
    return `${prefix}${currencySymbol}${formatted}${suffix}`
  }

  return `${prefix}${rawValue}${suffix}`
}

function getVisibleListItems(widget: any): any[] {
  ensureWidgetUiDefaults(widget)
  const items = Array.isArray(widget?.items) ? [...widget.items] : []
  const sortOrder = widget?.ui?.sortOrder === 'asc' ? 'asc' : 'desc'
  const maxItems = Math.max(1, Number(widget?.ui?.maxItems || items.length || 1))

  items.sort((left: any, right: any) => {
    const leftValue = Number(String(left?.value ?? '').replace(/[^0-9.-]/g, ''))
    const rightValue = Number(String(right?.value ?? '').replace(/[^0-9.-]/g, ''))
    if (Number.isNaN(leftValue) || Number.isNaN(rightValue)) return 0
    return sortOrder === 'asc' ? leftValue - rightValue : rightValue - leftValue
  })

  return items.slice(0, maxItems)
}

function getSummarySubtitle(widget: any): string {
  ensureWidgetUiDefaults(widget)
  return String(widget?.ui?.subtitle || '')
}

function getSummaryBadgeText(widget: any): string {
  ensureWidgetUiDefaults(widget)
  return String(widget?.ui?.badgeText || '')
}

function shouldShowSummaryDate(widget: any): boolean {
  ensureWidgetUiDefaults(widget)
  return widget?.ui?.showDate !== false
}

function scheduleWidgetConfigPersist() {
  if (isSharedMode.value || isLoading.value || isFiltering.value || !activeWidgetId.value) return
  if (backendPersistTimer) clearTimeout(backendPersistTimer)
  backendPersistTimer = setTimeout(async () => {
    try {
      await persistDashboardWidgets()
    } catch (error) {
      console.warn('[Dashboard] Widget config auto-save failed:', error)
    }
  }, 450)
}

function updateSelectedWidgetTitle() {
  if (!activeWidget.value) return
  ensureWidgetUiDefaults(activeWidget.value)
  const txt = String(activeWidget.value.ui.titleText || '').trim()
  if (txt) {
    activeWidget.value.title = txt
    activeWidget.value.ui.titleLocked = true
  }
}

function selectWidget(widgetId: string, event?: MouseEvent) {
  if (isSharedMode.value || isDashboardLocked.value) return
  activeWidgetId.value = widgetId
  const w = widgets.value.find(x => x.id === widgetId) as any
  ensureWidgetUiDefaults(w)
  nextTick(() => updateWidgetToolbarPosition(event))
  
  if (w && w.type === 'chart') {
    ensureChartSchema(resolvedFileId.value || activeDataSourceId.value)
  }
}

function clearWidgetSelection() {
  activeWidgetId.value = null
  widgetToolbarPos.value.visible = false
}

function updateWidgetToolbarPosition(_event?: MouseEvent) {
  if (!activeWidgetId.value || !gridContainer.value) {
    widgetToolbarPos.value.visible = false
    return
  }
  const item = gridContainer.value.querySelector(`[gs-id="${activeWidgetId.value}"]`) as HTMLElement | null
  if (!item) {
    widgetToolbarPos.value.visible = false
    return
  }
  const rect = item.getBoundingClientRect()
  widgetToolbarPos.value = {
    top: Math.max(12, rect.top - 52),
    left: rect.left + rect.width / 2,
    visible: true,
  }
}

function duplicateActiveWidget() {
  if (!guardTemplateMutation()) return
  if (!activeWidget.value) return
  const source: any = activeWidget.value
  const cloned = JSON.parse(JSON.stringify(source))
  cloned.id = `w-${Date.now()}`
  cloned.gridX = ((source.gridX ?? 0) + 1) % 12
  cloned.gridY = (source.gridY ?? 0) + 1
  widgets.value.push(cloned)
  nextTick(() => {
    try { grid?.destroy(false) } catch {}
    grid = null
    initGrid()
    selectWidget(cloned.id)
  })
}

function addBoardScreen() {
  if (!guardTemplateMutation()) return
  snapshotActiveScreenWidgets()
  const id = `screen-${Date.now()}`
  const index = boardScreens.value.length + 1
  boardScreens.value.push({ id, name: `Screen ${index}` })
  boardScreenWidgets.value[id] = []
  boardScreenThumbnails.value[id] = ''
  activeScreenId.value = id
  widgets.value = []
  if (isBoardMode.value) {
    const generationMap = getBoardFileGenerationMap()
    generationMap[id] = true
  }
  clearWidgetSelection()
  nextTick(() => {
    try { grid?.destroy(false) } catch {}
    grid = null
    initGrid()
  })
  if (shouldPersistStudioState.value) persistDashboardWidgets().catch(() => {})
}

function getActiveBoardFileKey(explicitFileId?: string): string {
  return String(explicitFileId || resolvedFileId.value || activeDataSourceId.value || '__default__')
}

function getTemplateSourceFileKey(): string {
  const key = String(templateSourceFileId.value || '').trim()
  if (key) return key
  if (isBoardMode.value && boardFiles.value.length > 0) {
    const originalSource = String(boardFiles.value[boardFiles.value.length - 1]?.file_uuid || '').trim()
    if (originalSource) return originalSource
  }
  return getActiveBoardFileKey()
}

function getBoardFileScreens(fileId?: string): Record<string, DashboardWidget[]> {
  const key = getActiveBoardFileKey(fileId)
  if (!boardFileScreenWidgets.value[key]) {
    boardFileScreenWidgets.value[key] = {}
  }
  return boardFileScreenWidgets.value[key]
}

function getSourceTemplateScreens(): Record<string, DashboardWidget[]> {
  const key = getTemplateSourceFileKey()
  return getBoardFileScreens(key)
}

function peekBoardFileScreens(fileId?: string): Record<string, DashboardWidget[]> {
  const key = getActiveBoardFileKey(fileId)
  return boardFileScreenWidgets.value[key] || {}
}

function getBoardFileGenerationMap(fileId?: string): Record<string, boolean> {
  const key = getActiveBoardFileKey(fileId)
  if (!boardFileScreenNeedsGeneration.value[key]) {
    boardFileScreenNeedsGeneration.value[key] = {}
  }
  return boardFileScreenNeedsGeneration.value[key]
}

function getBoardFilePendingTemplates(fileId?: string): Record<string, DashboardWidget[]> {
  const key = getActiveBoardFileKey(fileId)
  if (!boardFileScreenPendingTemplates.value[key]) {
    boardFileScreenPendingTemplates.value[key] = {}
  }
  return boardFileScreenPendingTemplates.value[key]
}

function peekBoardFilePendingTemplates(fileId?: string): Record<string, DashboardWidget[]> {
  const key = getActiveBoardFileKey(fileId)
  return boardFileScreenPendingTemplates.value[key] || {}
}

const isCurrentScreenPendingGeneration = computed(() => {
  if (!isBoardMode.value || !activeScreenId.value) return false
  const generationMap = getBoardFileGenerationMap()
  return !!generationMap[activeScreenId.value]
})

const hasCurrentScreenGeneratedWidgetsForFile = computed(() => {
  if (!isBoardMode.value || !activeScreenId.value) return false
  const fileScreens = peekBoardFileScreens()
  const directWidgets = fileScreens[activeScreenId.value]
  return Array.isArray(directWidgets) && directWidgets.length > 0
})

function resolveScreenWidgetsForRender(screenId: string, fileId?: string): DashboardWidget[] {
  const screens = getBoardFileScreens(fileId)
  const directWidgets = cloneWidgetList((screens[screenId] || []) as DashboardWidget[])
  if (directWidgets.length) return directWidgets

  const generationMap = getBoardFileGenerationMap(fileId)
  if (!generationMap[screenId]) return directWidgets

  const pendingTemplates = getBoardFilePendingTemplates(fileId)
  return cloneWidgetList((pendingTemplates[screenId] || []) as DashboardWidget[])
}

const hasPendingTemplatePreview = computed(() => {
  if (!isBoardMode.value || !activeScreenId.value) return false
  if (!isCurrentScreenPendingGeneration.value || isGeneratingPendingScreen.value) return false
  if (hasCurrentScreenGeneratedWidgetsForFile.value) return false
  const pendingTemplates = peekBoardFilePendingTemplates()
  return Array.isArray(pendingTemplates[activeScreenId.value]) && pendingTemplates[activeScreenId.value].length > 0
})

function ensureBoardFileScreens(fileId?: string) {
  const fileScreens = getBoardFileScreens(fileId)
  const generationMap = getBoardFileGenerationMap(fileId)
  for (const screen of boardScreens.value) {
    if (!fileScreens[screen.id]) fileScreens[screen.id] = []
    if (generationMap[screen.id] === undefined) {
      generationMap[screen.id] = false
    }
  }
  boardScreenWidgets.value = fileScreens
}

function activateScreen(screenId: string) {
  if (activeScreenId.value === screenId) return
  snapshotActiveScreenWidgets()
  ensureBoardFileScreens()
  activeScreenId.value = screenId
  widgets.value = resolveScreenWidgetsForRender(screenId)

  clearWidgetSelection()
  nextTick(() => {
    try { grid?.destroy(false) } catch {}
    grid = null
    initGrid()
  })
  if (isCurrentScreenPendingGeneration.value && !isGeneratingPendingScreen.value) {
    // Screen templates should auto-generate on switch with widget-wise loading.
    void generatePendingScreenDashboard()
  }
  if (shouldPersistStudioState.value) persistDashboardWidgets().catch(() => {})
}

function renameScreen(screenId: string, newName: string) {
  if (!guardTemplateMutation()) return
  const screen = boardScreens.value.find(s => s.id === screenId)
  if (screen && newName.trim()) {
    screen.name = newName.trim()
    if (shouldPersistStudioState.value) persistDashboardWidgets().catch(() => {})
  }
}

function deleteScreen(screenId: string) {
  if (!guardTemplateMutation()) return
  if (boardScreens.value.length <= 1) {
    toast.error('Must have at least one screen')
    return
  }
  const index = boardScreens.value.findIndex(s => s.id === screenId)
  if (index === -1) return
  boardScreens.value.splice(index, 1)
  
  // If deleted screen was active, switch to another
  if (activeScreenId.value === screenId) {
    activeScreenId.value = boardScreens.value[0]?.id || ''
    widgets.value = cloneWidgetList(boardScreenWidgets.value[activeScreenId.value] || [])
    clearWidgetSelection()
    nextTick(() => {
      try { grid?.destroy(false) } catch {}
      grid = null
      initGrid()
    })
  }

  delete boardScreenWidgets.value[screenId]
  delete boardScreenThumbnails.value[screenId]
  for (const fileKey of Object.keys(boardFileScreenWidgets.value)) {
    if (boardFileScreenWidgets.value[fileKey]?.[screenId]) {
      delete boardFileScreenWidgets.value[fileKey][screenId]
    }
  }
  for (const fileKey of Object.keys(boardFileScreenNeedsGeneration.value)) {
    if (boardFileScreenNeedsGeneration.value[fileKey]?.[screenId] !== undefined) {
      delete boardFileScreenNeedsGeneration.value[fileKey][screenId]
    }
  }
  
  if (shouldPersistStudioState.value) persistDashboardWidgets().catch(() => {})
}

function cloneWidgetList(source: DashboardWidget[]): DashboardWidget[] {
  return JSON.parse(JSON.stringify(source || []))
}

function snapshotActiveScreenWidgets() {
  if (!activeScreenId.value) return
  ensureBoardFileScreens()
  const fileScreens = getBoardFileScreens()
  const generationMap = getBoardFileGenerationMap()
  const pendingTemplates = getBoardFilePendingTemplates()
  boardScreenWidgets.value[activeScreenId.value] = cloneWidgetList(widgets.value)
  fileScreens[activeScreenId.value] = cloneWidgetList(widgets.value)
  generationMap[activeScreenId.value] = false
  pendingTemplates[activeScreenId.value] = []
  const key = getActiveBoardFileKey()
  boardFileScreenWidgets.value[key] = Object.fromEntries(
    Object.entries(boardScreenWidgets.value).map(([screenId, items]) => [screenId, cloneWidgetList(items || [])])
  )
}

function syncActiveScreenWidgetsToCurrentFile(fileId?: string) {
  if (!activeScreenId.value) return
  const key = getActiveBoardFileKey(fileId)
  const fileScreens = getBoardFileScreens(fileId)
  const generationMap = getBoardFileGenerationMap(fileId)
  for (const screen of boardScreens.value) {
    if (!fileScreens[screen.id]) fileScreens[screen.id] = []
    if (generationMap[screen.id] === undefined) generationMap[screen.id] = false
  }
  fileScreens[activeScreenId.value] = cloneWidgetList(widgets.value)
  generationMap[activeScreenId.value] = false
  boardFileScreenWidgets.value[key] = fileScreens
  boardScreenWidgets.value = fileScreens
}

function buildFileDashboardStudioState(fileId?: string) {
  const targetFileId = fileId || resolvedFileId.value
  const screens = boardScreens.value.map(s => ({ id: s.id, name: s.name }))
  const fileScreens = getBoardFileScreens(targetFileId)
  const screenWidgets: Record<string, DashboardWidget[]> = {}
  for (const screen of screens) {
    screenWidgets[screen.id] = cloneWidgetList(fileScreens[screen.id] || [])
  }
  return {
    screens,
    active_screen_id: activeScreenId.value || screens[0]?.id || 'screen-1',
    active_theme: activeTheme.value,
    screen_widgets: screenWidgets,
  }
}

function hydrateFileDashboardStudio(studio: any, fallbackWidgets: DashboardWidget[]) {
  const targetFileId = resolvedFileId.value
  const safeFallback = cloneWidgetList(fallbackWidgets || [])
  const screens = Array.isArray(studio?.screens) && studio.screens.length
    ? studio.screens.filter((screen: any) => typeof screen?.id === 'string' && typeof screen?.name === 'string')
    : [{ id: 'screen-1', name: 'Dashboard' }]

  const active = screens.some((screen: any) => screen.id === studio?.active_screen_id)
    ? studio.active_screen_id
    : screens[0].id

  const incomingScreenWidgets = (studio && typeof studio.screen_widgets === 'object' && studio.screen_widgets)
    ? studio.screen_widgets
    : {}

  const normalized: Record<string, DashboardWidget[]> = {}
  for (const screen of screens) {
    const value = (incomingScreenWidgets as Record<string, unknown>)[screen.id]
    normalized[screen.id] = Array.isArray(value)
      ? cloneWidgetList(value as DashboardWidget[])
      : []
  }
  if (!normalized[active].length && safeFallback.length) {
    normalized[active] = safeFallback
  }

  boardScreens.value = screens
  activeScreenId.value = active
  boardScreenWidgets.value = normalized
  boardFileScreenWidgets.value[getActiveBoardFileKey(targetFileId)] = normalized
  widgets.value = cloneWidgetList(normalized[active] || [])
}

async function generatePendingScreenDashboard() {
  if (!isBoardMode.value || !activeScreenId.value || isGeneratingPendingScreen.value) return

  const fileId = resolvedFileId.value || activeDataSourceId.value
  if (!fileId) {
    toast.error('No active file selected')
    return
  }

  const pendingTemplates = getBoardFilePendingTemplates(fileId)
  const templateWidgets = cloneWidgetList(pendingTemplates[activeScreenId.value] || [])

  if (!templateWidgets.length) {
    await loadDashboard(true)
    return
  }

  isGeneratingPendingScreen.value = true
  toast.loading('Generating this screen from template...', { id: 'pending-screen-generate' })
  try {
    const loadingTemplate: DashboardWidget[] = cloneWidgetList(templateWidgets).map((widget) => ({
      ...(widget as any),
      isLoadingData: true,
    })) as DashboardWidget[]

    widgets.value = loadingTemplate
    syncActiveScreenWidgetsToCurrentFile(fileId)
    await nextTick()
    try { grid?.destroy(false) } catch {}
    grid = null
    initGrid()

    const cloneResponse = await excelFileAPI.cloneTemplateWidgets(fileId, templateWidgets, dashboardSessionId.value)
    captureTrace(cloneResponse as any)

    const regenerated: DashboardWidget[] = cloneWidgetList((cloneResponse?.widgets || []) as DashboardWidget[])
    for (let index = 0; index < regenerated.length; index++) {
      const templateWidget = templateWidgets[index]
      const nextWidget = {
        ...(regenerated[index] as any),
        id: (templateWidget as any)?.id || (regenerated[index] as any).id,
        gridX: (templateWidget as any)?.gridX,
        gridY: (templateWidget as any)?.gridY,
        gridW: (templateWidget as any)?.gridW ?? regenerated[index].gridW,
        gridH: (templateWidget as any)?.gridH ?? regenerated[index].gridH,
        isLoadingData: false,
      } as DashboardWidget
      sanitizeKpiWidgetPayload(nextWidget as any, templateWidget as any)
      regenerated[index] = nextWidget
    }

    widgets.value = regenerated
    originalWidgets.value = JSON.parse(JSON.stringify(regenerated))
    syncActiveScreenWidgetsToCurrentFile(fileId)

    const generationMap = getBoardFileGenerationMap(fileId)
    generationMap[activeScreenId.value] = false
    delete pendingTemplates[activeScreenId.value]

    await persistDashboardWidgets()

    if (widgets.value.length > 0) {
      const hasPositions = widgets.value.some(w => (w as any).gridX !== undefined || (w as any).gridY !== undefined)
      if (!hasPositions) autoPositionWidgets()
      await nextTick()
      initGrid()
    }

    toast.success('Screen dashboard generated from this screen template', { id: 'pending-screen-generate' })
  } catch (e: any) {
    toast.error(e?.message || 'Failed to generate this screen for selected file', { id: 'pending-screen-generate' })
  } finally {
    widgets.value.forEach((w: any) => { w.isLoadingData = false })
    isGeneratingPendingScreen.value = false
  }
}

function handleWidgetStyleUpdate(key: string, value: any) {
  if (!activeWidget.value) return
  
  if (!activeWidget.value.ui) {
    activeWidget.value.ui = {}
  }
  
  activeWidget.value.ui[key] = value
  
  // Trigger deep watch to persist changes
  scheduleWidgetConfigPersist()
  
  // Bump render version to force chart re-render if needed
  if (activeWidgetId.value) {
    widgetRenderVersions.value[activeWidgetId.value] = (widgetRenderVersions.value[activeWidgetId.value] || 0) + 1
  }
}

function handleDashboardDesignUpdate(key: string, value: any) {
  if (key === 'texture' && ['none', 'dots', 'grid', 'gradient'].includes(String(value))) {
    boardDesign.value.texture = value
  }
  if (key === 'density' && ['compact', 'cozy', 'airy'].includes(String(value))) {
    boardDesign.value.density = value
  }
  if (key === 'cardStyle' && ['flat', 'soft', 'glass'].includes(String(value))) {
    boardDesign.value.cardStyle = value
  }
  if (isBoardMode.value) persistDashboardWidgets().catch(() => {})
}

async function recomputeActiveKpi(payload: { title: string; overrideValue: string }) {
  if (!activeWidget.value || activeWidget.value.type !== 'kpi') return
  const widget = activeWidget.value as any
  ensureWidgetUiDefaults(widget)

  const nextTitle = String(payload.title || widget.title || '').trim()
  if (nextTitle) {
    widget.title = nextTitle
    widget.ui.titleText = nextTitle
    widget.ui.titleLocked = true
  }

  const overrideValue = String(payload.overrideValue || '').trim()
  if (overrideValue) {
    widget.ui.overrideValue = overrideValue
    scheduleWidgetConfigPersist()
    return
  }

  widget.ui.overrideValue = ''

  const fileId = resolvedFileId.value || activeDataSourceId.value
  if (!fileId || !nextTitle) {
    scheduleWidgetConfigPersist()
    return
  }

  widget.isLoadingData = true
  const mode = route.query.mode ? String(route.query.mode) : undefined
  try {
    const query = `Create one KPI widget for: ${nextTitle}. Use available data and return concise metric output.`
    const compareId = isCompareMode.value && compareFileId.value ? compareFileId.value : undefined
    const response = await excelFileAPI.generateWidget(fileId, query, compareId, dashboardSessionId.value, undefined, mode, dashboardSourceType.value)
    captureTrace(response as any)

    const generated = ('dual' in response && (response as any).dual)
      ? (response as any).base_widget
      : (response as any).widget

    if (generated && generated.type === 'kpi') {
      widget.value = generated.value ?? widget.value
      widget.subtitle = generated.subtitle ?? widget.subtitle
      widget.trend = generated.trend ?? widget.trend
      widget.highlight = generated.highlight ?? widget.highlight
      widget.origin_query = query
      toast.success('KPI recalculated from data')
    } else {
      toast.info('Applied title, but no KPI metric response was returned')
    }
  } catch (error) {
    console.error('[Dashboard] KPI recompute failed', error)
    toast.error('Failed to recompute KPI from title')
  } finally {
    widget.isLoadingData = false
  }

  scheduleWidgetConfigPersist()
}

function getWidgetVisualClasses(widget: any): string[] {
  const kind = String(widget?.type || 'unknown').toLowerCase()
  const classes = [`widget-type-${kind}`]
  const variant = String(widget?.ui?.widgetVariant || '').toLowerCase()
  if (variant) classes.push(`widget-variant-${variant}`)
  if (kind === 'chart') {
    const chartType = String(widget?.chartType || 'bar').toLowerCase().replace(/[^a-z0-9]+/g, '-')
    classes.push(`chart-type-${chartType}`)
  }
  return classes
}

function zoomOutCanvas() {
  canvasZoom.value = Math.max(50, canvasZoom.value - 10)
}

function zoomInCanvas() {
  canvasZoom.value = Math.min(150, canvasZoom.value + 10)
}

function resetCanvasZoom() {
  canvasZoom.value = 100
}

function togglePreviewMode() {
  isPreviewMode.value = !isPreviewMode.value
  if (isPreviewMode.value) {
    clearWidgetSelection()
  }
}

async function openChartBuilder() {
  if (!guardTemplateMutation()) return
  chartBuilderOpen.value = true
  await ensureChartSchema(resolvedFileId.value || activeDataSourceId.value)
}

async function recomputeActiveChart(payload: { chartType: string; dimension: string; measure: string; aggregation: string; suggestedTitle?: string }) {
  if (!activeWidget.value || activeWidget.value.type !== 'chart') return
  const fileId = resolvedFileId.value || activeDataSourceId.value
  if (!fileId) {
    toast.error('No active data source available for chart computation')
    return
  }

  const current = activeWidget.value as any
  const preserve = {
    id: current.id,
    title: current.title,
    description: current.description,
    ui: JSON.parse(JSON.stringify(current.ui || {})),
    gridX: current.gridX,
    gridY: current.gridY,
    gridW: current.gridW,
    gridH: current.gridH,
    chartColor: current.chartColor,
  }

  current.isLoadingData = true
  const mode = route.query.mode ? String(route.query.mode) : undefined
  try {
    const result = await excelFileAPI.generateCustomChart(
      fileId,
      payload.chartType,
      payload.dimension,
      payload.aggregation === 'count' ? null : payload.measure,
      payload.aggregation,
      mode,
      dashboardSourceType.value
    )

    if (result?.status === 'success' && result.widget) {
      const i = widgets.value.findIndex(w => w.id === preserve.id)
      if (i >= 0) {
        const titleLocked = Boolean(preserve.ui?.titleLocked)
        const computedTitle = String(result.widget.title || payload.suggestedTitle || preserve.title || '').trim()
        const finalTitle = titleLocked ? preserve.title : (computedTitle || preserve.title)
        const rebuilt: any = {
          ...result.widget,
          id: preserve.id,
          title: finalTitle,
          description: preserve.description || (result.widget as any).description,
          ui: {
            ...(result.widget as any).ui,
            ...preserve.ui,
            xAxisColumn: payload.dimension,
            yAxisColumn: payload.measure,
            aggregation: payload.aggregation,
            titleText: finalTitle,
          },
          gridX: preserve.gridX,
          gridY: preserve.gridY,
          gridW: preserve.gridW,
          gridH: preserve.gridH,
          chartColor: preserve.chartColor,
        }
        widgets.value[i] = rebuilt
        snapshotActiveScreenWidgets()
        scheduleWidgetConfigPersist()
        chartRenderEpoch.value++
      }
    }
  } catch (e: any) {
    const detail = e?.response?.data?.detail || 'Failed to recompute chart with selected columns'
    toast.error(detail)
  } finally {
    current.isLoadingData = false
  }
}

async function ensureChartSchema(fileId?: string) {
  const effectiveFileId = String(fileId || '').trim()
  if (!effectiveFileId) {
    chartSchema.value = null
    chartSchemaFileId.value = ''
    return
  }
  if (chartSchema.value && chartSchemaFileId.value === effectiveFileId) {
    return
  }
  try {
    const res = await excelFileAPI.getChartSchema(effectiveFileId, dashboardSourceType.value)
    chartSchema.value = res
    chartSchemaFileId.value = effectiveFileId
    if (!chartBuilderForm.value.dimension && res.dimensions.length) {
      chartBuilderForm.value.dimension = res.dimensions[0].col
    }
    if (!chartBuilderForm.value.measure && res.measures.length) {
      chartBuilderForm.value.measure = res.measures[0].col
    }
  } catch {
    chartSchema.value = null
    chartSchemaFileId.value = ''
  }
}

async function buildCustomChart() {
  if (!guardTemplateMutation()) return
  if (!chartBuilderForm.value.dimension) {
    toast.error('Please select a dimension (qualitative column)')
    return
  }
  chartBuilderLoading.value = true
  const mode = route.query.mode ? String(route.query.mode) : undefined
  try {
    const fileId = resolvedFileId.value || activeDataSourceId.value
    const res = await excelFileAPI.generateCustomChart(
      fileId,
      chartBuilderForm.value.chartType,
      chartBuilderForm.value.dimension,
      chartBuilderForm.value.aggregation === 'count' ? null : (chartBuilderForm.value.measure || null),
      chartBuilderForm.value.aggregation,
      mode,
      dashboardSourceType.value
    )
    if (res.status === 'success' && res.widget) {
      const w = res.widget as any
      delete w.gridX
      delete w.gridY
      widgets.value.push(w)
      widgets.value.forEach(x => { delete (x as any).gridX; delete (x as any).gridY })
      autoPositionWidgets()
      try { grid?.destroy(false) } catch {}
      grid = null; await nextTick(); initGrid()
      await persistDashboardWidgets()
      store.saveDashboardLayout(resolvedFileId.value, widgets.value)
      toast.success(`${chartBuilderForm.value.chartType} chart added!`)
    }
  } catch (e: any) {
    const msg = e?.response?.data?.detail || 'Failed to build chart'
    toast.error(typeof msg === 'string' ? msg : 'Failed to build chart')
  } finally {
    chartBuilderLoading.value = false
  }
}

// File tree built from the documents store (same data as the files page)
const dashboardFileTree = computed<TreeNode[]>(() =>
  buildFileTree(store.sortedFiles, store.projects)
)

// ── PER-CHART VALUE FILTER ────────────────────────────────────
// Maps widgetId → selected label values (null = no manual filter, use Top-N default)
const chartFilters = ref<Record<string, string[] | null>>({})
// Which chart's filter popover is currently open
const openChartFilterId = ref<string | null>(null)
// Temporary selection state while the popover is open
const chartFilterDraft = ref<string[]>([])
// Search query inside the filter popover
const chartFilterSearch = ref('')
const chartFilterPos = ref<{ top?: number; bottom?: number; right: number }>({ top: 0, right: 0 })

const TOP_N_THRESHOLD = 12   // charts with more labels than this show Top-10 by default
const TOP_N_DEFAULT   = 10   // how many bars to show by default

/** Return the active label-set for a chart widget (Top-N if no manual filter set). */
function getActiveChartLabels(widgetId: string, allLabels: string[], allSeries: any[]): string[] {
  const entry = chartFilters.value[widgetId]
  // null  = key exists but user explicitly chose "All" → show everything
  // array = manual selection → use it
  // undefined = never opened → apply auto Top-N default
  if (entry === null) return allLabels          // explicit "show all"
  if (Array.isArray(entry) && entry.length > 0) return entry
  if (allLabels.length > TOP_N_THRESHOLD) {
    // Auto Top-N: pick top TOP_N_DEFAULT by first-series value
    const firstSeries = allSeries.length > 0 ? allSeries[0] : null
    const firstData: number[] = firstSeries
      ? (typeof firstSeries === 'object' && Array.isArray(firstSeries.data) ? firstSeries.data : (Array.isArray(firstSeries) ? firstSeries : []))
      : []
    const scored = allLabels.map((l, i) => ({ l, v: Number(firstData[i] ?? 0) }))
    scored.sort((a, b) => b.v - a.v)
    return scored.slice(0, TOP_N_DEFAULT).map(x => x.l)
  }
  return allLabels  // ≤ threshold: show everything
}

/** Slice chartData to only the selected labels (preserves order of allLabels). */
function getFilteredChartData(widgetId: string, chartData: any, rawSeries: any[]): { labels: string[], series: any[] } {
  const allLabels: string[] = chartData?.labels || []
  const active = getActiveChartLabels(widgetId, allLabels, rawSeries)
  // If active is the full set, skip slicing
  if (active.length === allLabels.length) return { labels: allLabels, series: rawSeries }

  const activeSet = new Set(active)
  const idxMap: number[] = []
  allLabels.forEach((l, i) => { if (activeSet.has(l)) idxMap.push(i) })
  const filteredLabels = idxMap.map(i => allLabels[i])

  const filteredSeries = rawSeries.map(s => {
    if (typeof s === 'object' && Array.isArray(s.data)) {
      return { ...s, data: idxMap.map(i => s.data[i] ?? 0) }
    }
    if (typeof s === 'number' || typeof s === 'string') return s  // flat — can't slice
    return s
  })
  return { labels: filteredLabels, series: filteredSeries }
}

/** Sort all labels by descending value (first series) and return top n. */
function getTopNSortedLabels(allLabels: string[], allSeries: any[], n: number): string[] {
  const firstSeries = allSeries.length > 0 ? allSeries[0] : null
  const firstData: number[] = firstSeries
    ? (typeof firstSeries === 'object' && Array.isArray(firstSeries.data) ? firstSeries.data : (Array.isArray(firstSeries) ? firstSeries : []))
    : []
  const scored = allLabels.map((l, i) => ({ l, v: Number(firstData[i] ?? 0) }))
  scored.sort((a, b) => b.v - a.v)
  return scored.slice(0, n).map(x => x.l)
}

/** Open the filter popover for a chart widget. */
function openChartFilter(widgetId: string, allLabels: string[], event?: MouseEvent) {
  if (event) {
    const rect = (event.currentTarget as HTMLElement).getBoundingClientRect()
    const popoverHeight = 380  // approx max height of the popover in px
    const rightPos = window.innerWidth - rect.right
    if (rect.bottom + popoverHeight > window.innerHeight) {
      // Not enough space below — flip upward
      chartFilterPos.value = { bottom: window.innerHeight - rect.top + 4, right: rightPos }
    } else {
      chartFilterPos.value = { top: rect.bottom + 4, right: rightPos }
    }
  }
  const existing = chartFilters.value[widgetId]
  if (existing === null) {
    // was set to explicit "all"
    chartFilterDraft.value = [...allLabels]
  } else if (Array.isArray(existing) && existing.length > 0) {
    chartFilterDraft.value = [...existing]
  } else {
    // Never opened or auto-Top-N: pre-check the current auto selection so user sees what's shown
    chartFilterDraft.value = [...allLabels]
  }
  chartFilterSearch.value = ''
  openChartFilterId.value = widgetId
}

/** Apply the draft selection. Storing null means "show all". */
function applyChartFilter(widgetId: string) {
  const all = chartFilterDraft.value
  // If user selected every label, treat as null = "show all" (no filter indicator)
  chartFilters.value = { ...chartFilters.value, [widgetId]: [...all] }
  openChartFilterId.value = null
}

/** Reset a chart — store null to mean "explicitly show all labels" and keep popover open so user can see the full list. */
function clearChartFilter(widgetId: string, allLabels?: string[]) {
  // null sentinel = "show all labels" (bypasses auto-Top-N)
  chartFilters.value = { ...chartFilters.value, [widgetId]: null }
  if (allLabels) chartFilterDraft.value = [...allLabels]
  // keep popover open so user can see the full list and make a selection
}

/** True if any chart has an active filter (array selection, NOT null/all). */
const hasAnyChartFilter = computed(() =>
  Object.values(chartFilters.value).some(v => Array.isArray(v) && v.length > 0)
)

// ── COMPARE MODE MEMORY CACHE ─────────────────────────────────
// Snapshot of primary widgets BEFORE entering compare mode — used to restore
// when exiting or switching back from unified.
const primaryWidgetsSnapshot = ref<DashboardWidget[]>([])
// Cached unified API response — toggling between split/unified reuses this.
const unifiedWidgetsCache = ref<DashboardWidget[]>([])
// Epoch counter included in VChart :key — incrementing forces ECharts to fully
// remount and clear any stale merged series from unified comparison mode.
const chartRenderEpoch = ref(0)
// Gates VChart rendering until GridStack has sized the primary / compare cells.
// Prevents the ECharts 'Can't get DOM width or height' console warning on mount.
const gridReady = ref(false)
const gridBReady = ref(false)

// Compare sorted widgets (mirrors primary sort order)
const sortedCompareWidgets = computed(() => {
  const order: Record<string, number> = { summary: -1, kpi: 0, insight: 1, list: 2, chart: 3 }
  return [...compareWidgets.value].sort((a, b) => {
    const aOrder = order[(a as any).type] ?? 3
    const bOrder = order[(b as any).type] ?? 3
    return aOrder - bOrder
  })
})

// ── SORTED WIDGETS: text widgets (kpi/insight/list) first, charts after ──
const sortedWidgets = computed(() => {
  const order: Record<string, number> = { summary: -1, kpi: 0, insight: 1, list: 2, chart: 3 }
  const source = (isCompareMode.value && compareViewMode.value === 'unified' && unifiedWidgets.value.length)
    ? unifiedWidgets.value
    : widgets.value
  return [...source].sort((a, b) => {
    const aOrder = order[(a as any).type] ?? 3
    const bOrder = order[(b as any).type] ?? 3
    return aOrder - bOrder
  })
})

// ── SLICER DIMENSIONS (from original fingerprint — stable across filter/refresh) ──
const slicerDimensions = computed(() => {
  const fp = originalFingerprint.value || fingerprint.value
  if (!fp?.dimensions) return []
  return fp.dimensions.filter(d => d.cardinality >= 2 && d.cardinality <= 200).slice(0, 8)
})

// ── AUTO-POSITION: Bin-pack widgets into a 12-col grid ─────────────
function autoPositionWidgets() {
  const COLS = 12
  const colHeights = new Array(COLS).fill(0)
  const sorted = sortedWidgets.value

  for (const w of sorted) {
    const ww = Math.min(w.gridW || 3, COLS)
    const hh = w.gridH || 1

    // Find leftmost position with the lowest y where this widget fits
    let bestX = 0
    let bestY = Infinity
    for (let x = 0; x <= COLS - ww; x++) {
      let maxH = 0
      for (let c = x; c < x + ww; c++) maxH = Math.max(maxH, colHeights[c])
      if (maxH < bestY) { bestY = maxH; bestX = x }
    }

    ;(w as any).gridX = bestX
    ;(w as any).gridY = bestY
    for (let c = bestX; c < bestX + ww; c++) colHeights[c] = bestY + hh
  }
}

// ── COLOR THEMES ───────────────────────────────────────────────
// Each theme has a swatch color for the picker + muted chart palette
const colorThemes: Record<string, { swatch: string; bg: string; text: string; chart: string[] }> = {
  mokkup1: { swatch: '#4338ca', bg: 'bg-indigo-50 dark:bg-indigo-950/30', text: 'text-indigo-700 dark:text-indigo-300', chart: ['#20156f', '#3f34b8', '#6a60d9', '#8f89e6', '#547bc7'] },
  holidaySpark: { swatch: '#d4645e', bg: 'bg-rose-50 dark:bg-rose-950/20', text: 'text-rose-600 dark:text-rose-300', chart: ['#d0605a', '#e07b76', '#98c97e', '#ee9992', '#86b96d'] },
  mokkup2: { swatch: '#4b3fb6', bg: 'bg-violet-50 dark:bg-violet-950/30', text: 'text-violet-700 dark:text-violet-300', chart: ['#4f44b9', '#746bdb', '#948fde', '#e69488', '#d57665'] },
  rustic: { swatch: '#8b4e25', bg: 'bg-amber-50 dark:bg-amber-950/20', text: 'text-amber-700 dark:text-amber-300', chart: ['#884e24', '#d78d59', '#f3ba90', '#f8dc98', '#efbd47'] },
  mix: { swatch: 'conic', bg: 'bg-slate-50 dark:bg-slate-800/40', text: 'text-slate-600 dark:text-slate-400', chart: ['#6366f1', '#10b981', '#f59e0b', '#f43f5e', '#06b6d4', '#8b5cf6', '#f97316', '#22c55e'] },
  indigo: { swatch: '#6366f1', bg: 'bg-indigo-50 dark:bg-indigo-950/30', text: 'text-indigo-600 dark:text-indigo-400', chart: ['#4338ca', '#4f46e5', '#6366f1', '#818cf8', '#a5b4fc'] },
  violet: { swatch: '#8b5cf6', bg: 'bg-violet-50 dark:bg-violet-950/30', text: 'text-violet-600 dark:text-violet-400', chart: ['#6d28d9', '#7c3aed', '#8b5cf6', '#a78bfa', '#c4b5fd'] },
  emerald: { swatch: '#10b981', bg: 'bg-emerald-50 dark:bg-emerald-950/30', text: 'text-emerald-600 dark:text-emerald-400', chart: ['#047857', '#059669', '#10b981', '#34d399', '#6ee7b7'] },
  amber: { swatch: '#f59e0b', bg: 'bg-amber-50 dark:bg-amber-950/30', text: 'text-amber-600 dark:text-amber-400', chart: ['#b45309', '#d97706', '#f59e0b', '#fbbf24', '#fcd34d'] },
  rose: { swatch: '#f43f5e', bg: 'bg-rose-50 dark:bg-rose-950/30', text: 'text-rose-600 dark:text-rose-400', chart: ['#be123c', '#e11d48', '#f43f5e', '#fb7185', '#fda4af'] },
  cyan: { swatch: '#06b6d4', bg: 'bg-cyan-50 dark:bg-cyan-950/30', text: 'text-cyan-600 dark:text-cyan-400', chart: ['#0e7490', '#0891b2', '#06b6d4', '#22d3ee', '#67e8f9'] },
}

const CONIC_GRADIENT = 'conic-gradient(#6366f1, #8b5cf6, #f43f5e, #f59e0b, #10b981, #06b6d4, #6366f1)'

function getSwatchStyle(key: string): Record<string, string> {
  const s = colorThemes[key]?.swatch
  return s === 'conic' ? { background: CONIC_GRADIENT } : { background: s || '#6366f1' }
}

function hexToRgba(hex: string, alpha: number): string {
  const safe = /^#[0-9a-f]{6}$/i.test(hex) ? hex : '#6366f1'
  const r = parseInt(safe.slice(1, 3), 16)
  const g = parseInt(safe.slice(3, 5), 16)
  const b = parseInt(safe.slice(5, 7), 16)
  return `rgba(${r}, ${g}, ${b}, ${alpha})`
}

function darkenHex(hex: string, weight: number): string {
  const safe = /^#[0-9a-f]{6}$/i.test(hex) ? hex : '#6366f1'
  const r = parseInt(safe.slice(1, 3), 16)
  const g = parseInt(safe.slice(3, 5), 16)
  const b = parseInt(safe.slice(5, 7), 16)
  const w = Math.min(0.9, Math.max(0, weight))
  const dr = Math.round(r * (1 - w))
  const dg = Math.round(g * (1 - w))
  const db = Math.round(b * (1 - w))
  return `#${[dr, dg, db].map(v => v.toString(16).padStart(2, '0')).join('')}`
}

function hexToRgbString(hex: string): string {
  const safe = /^#[0-9a-f]{6}$/i.test(hex) ? hex : '#6366f1'
  const r = parseInt(safe.slice(1, 3), 16)
  const g = parseInt(safe.slice(3, 5), 16)
  const b = parseInt(safe.slice(5, 7), 16)
  return `${r}, ${g}, ${b}`
}

const themeCssVars = computed(() => {
  const swatch = colorThemes[activeTheme.value]?.swatch
  const accent = swatch && swatch !== 'conic' ? swatch : '#6366f1'
  const accentStrong = darkenHex(accent, 0.12)
  const palette = (colorThemes[activeTheme.value]?.chart || []).slice(0, 5)
  const fallbackPalette = ['#4338ca', '#4f46e5', '#6366f1', '#818cf8', '#a5b4fc']
  const shades = [...palette, ...fallbackPalette].slice(0, 5)
  return {
    '--theme-accent': accent,
    '--theme-accent-rgb': hexToRgbString(accent),
    '--theme-accent-strong': accentStrong,
    '--theme-accent-contrast': darkenHex(accent, 0.24),
    '--theme-soft': hexToRgba(accent, 0.14),
    '--theme-soft-2': hexToRgba(accent, 0.22),
    '--theme-border': hexToRgba(accent, 0.36),
    '--theme-text': darkenHex(accent, 0.32),
    '--theme-shade-1': shades[0],
    '--theme-shade-2': shades[1],
    '--theme-shade-3': shades[2],
    '--theme-shade-4': shades[3],
    '--theme-shade-5': shades[4],
  } as Record<string, string>
})

function getWidgetPalette(widget: any): string[] {
  const fromWidget = getWidgetTheme(widget, 0)?.chart || []
  if (Array.isArray(fromWidget) && fromWidget.length) return fromWidget
  const fromTheme = colorThemes[activeTheme.value]?.chart || []
  if (Array.isArray(fromTheme) && fromTheme.length) return fromTheme
  return ['#4338ca', '#4f46e5', '#6366f1', '#818cf8', '#a5b4fc']
}

function getListBarColor(widget: any, rowIndex: number): string {
  const palette = getWidgetPalette(widget)
  const idx = Math.min(rowIndex, Math.max(0, palette.length - 1))
  return palette[idx] || palette[0]
}

function getListRankStyle(widget: any, rowIndex: number): Record<string, string> {
  const palette = getWidgetPalette(widget)
  const color = palette[Math.min(rowIndex, Math.max(0, palette.length - 1))] || palette[0]
  return {
    backgroundColor: hexToRgba(color, 0.16),
    color,
  }
}

function resolveWidgetColor(widget: any): string | undefined {
  const own = typeof widget?.chartColor === 'string' ? widget.chartColor.trim() : ''
  if (own) return own
  const fromPrimary = widgets.value.find(w => w.id === widget?.id) as any
  const inherited = typeof fromPrimary?.chartColor === 'string' ? fromPrimary.chartColor.trim() : ''
  return inherited || undefined
}

function getWidgetCardStyle(widget: any): Record<string, string> {
  ensureWidgetUiDefaults(widget)
  const ui = widget?.ui || {}
  const color = resolveWidgetColor(widget)
  const styles: Record<string, string> = {}

  if (color && widget?.type !== 'chart') {
    styles.backgroundColor = `${color}55`
    styles.borderColor = `${color}aa`
  }

  if (ui.canvasColor) styles.backgroundColor = ui.canvasColor

  if (ui.roundedCorners) {
    const radius = ui.cornerRadius === 'lg' ? '18px' : ui.cornerRadius === 'sm' ? '8px' : '12px'
    styles.borderRadius = radius
  }

  if (ui.dropShadow) {
    const shadow = ui.shadowSize === 'lg'
      ? '0 12px 28px rgba(15, 23, 42, 0.2)'
      : ui.shadowSize === 'sm'
        ? '0 4px 10px rgba(15, 23, 42, 0.12)'
        : '0 8px 18px rgba(15, 23, 42, 0.16)'
    styles.boxShadow = shadow
  }

  if (ui.stroke) {
    const width = Number.isFinite(Number(ui.strokeWidth)) ? Math.max(1, Number(ui.strokeWidth)) : 1
    styles.borderStyle = 'solid'
    styles.borderWidth = `${width}px`
    styles.borderColor = ui.strokeColor || styles.borderColor || '#0f172a22'
  }

  if (ui.banding) {
    styles.backgroundImage = 'linear-gradient(180deg, rgba(99, 102, 241, 0.16) 0%, rgba(99, 102, 241, 0.06) 100%)'
  }

  if (widget?.type === 'chart' && (ui.addButtons || ui.addDropdowns || ui.addKpis || ui.addText)) {
    const insetGlow = 'inset 0 0 0 2px rgba(59, 130, 246, 0.18)'
    styles.boxShadow = styles.boxShadow ? `${styles.boxShadow}, ${insetGlow}` : insetGlow
  }

  return styles
}

const themeKeys = Object.keys(colorThemes)

const defaultChartColors = computed(() => {
  const t = colorThemes[activeTheme.value]
  return t ? t.chart : ['#4f6d9b', '#5c9a8a', '#c4975a', '#a87585', '#5b97a5']
})

function getWidgetTheme(_widget: any, _index: number) {
  // Per-widget color override (Insight Boards)
  const widgetColor = resolveWidgetColor(_widget)
  if (widgetColor) {
    const base = colorThemes[activeTheme.value] || colorThemes.indigo
    return { ...base, chart: generateShades(widgetColor) }
  }
  // All widgets use the user-selected dashboard theme
  return colorThemes[activeTheme.value] || colorThemes.indigo
}

/** Generate a 5-shade palette from a single hex color (light→dark variations) */
function generateShades(hex: string): string[] {
  const r = parseInt(hex.slice(1, 3), 16)
  const g = parseInt(hex.slice(3, 5), 16)
  const b = parseInt(hex.slice(5, 7), 16)
  const mix = (c: number, t: number, w: number) => Math.round(c + (t - c) * w)
  return [
    `#${[r, g, b].map(c => mix(c, 255, 0.08).toString(16).padStart(2, '0')).join('')}`,
    hex,
    `#${[r, g, b].map(c => mix(c, 0, 0.12).toString(16).padStart(2, '0')).join('')}`,
    `#${[r, g, b].map(c => mix(c, 0, 0.24).toString(16).padStart(2, '0')).join('')}`,
    `#${[r, g, b].map(c => mix(c, 0, 0.36).toString(16).padStart(2, '0')).join('')}`,
  ]
}

// ── COMPARE THEME (auto-contrasting) ───────────────────────────
// Maps each primary theme to a visually distinct compare theme
const compareThemeMap: Record<string, string> = {
  mokkup1: 'holidaySpark',
  holidaySpark: 'mokkup2',
  mokkup2: 'rustic',
  rustic: 'mokkup1',
  mix: 'rose',
  indigo: 'emerald',
  violet: 'cyan',
  emerald: 'violet',
  amber: 'indigo',
  rose: 'cyan',
  cyan: 'rose',
}

const compareThemeKey = computed(() => {
  return compareThemeMap[activeTheme.value] || 'emerald'
})

const compareChartColors = computed(() => {
  const t = colorThemes[compareThemeKey.value]
  return t ? t.chart : colorThemes.emerald.chart
})

function getCompareWidgetTheme() {
  return colorThemes[compareThemeKey.value] || colorThemes.emerald
}

function getCompareEChartOption(widget: any, index: number = 0): Record<string, any> {
  // Use a synthetic id so the compare‑panel filter key (widget.id + '-cmp') is looked up correctly
  const opts = getEChartOption({ ...widget, id: widget.id + '-cmp' }, index)
  opts.color = compareChartColors.value
  return opts
}

function wrapAxisLabel(value: string, chunkSize = 12): string {
  const text = String(value ?? '')
  if (!text || text.length <= chunkSize) return text

  const words = text.split(/\s+/).filter(Boolean)
  if (words.length <= 1) {
    const lines: string[] = []
    for (let i = 0; i < text.length; i += chunkSize) {
      lines.push(text.slice(i, i + chunkSize))
    }
    return lines.join('\n')
  }

  const lines: string[] = []
  let current = ''
  for (const word of words) {
    if (!current.length) {
      current = word
      continue
    }
    if ((current + ' ' + word).length <= chunkSize) {
      current += ' ' + word
    } else {
      lines.push(current)
      current = word
    }
  }
  if (current.length) lines.push(current)
  return lines.join('\n')
}

function truncateAxisLabel(value: string, maxLen = 12): string {
  const text = String(value ?? '').trim()
  if (!text) return ''
  return text.length > maxLen ? `${text.slice(0, Math.max(1, maxLen - 1))}…` : text
}

function prettifyAxisName(value: string): string {
  const text = String(value ?? '').replace(/[_-]+/g, ' ').trim()
  if (!text) return ''
  return text.split(/\s+/).map(word => word.charAt(0).toUpperCase() + word.slice(1)).join(' ')
}

function setTheme(key: string) {
  activeTheme.value = key
  showThemePicker.value = false
  if (resolvedFileId.value) store.setDashboardTheme(resolvedFileId.value, key)
  if (shouldPersistStudioState.value) persistDashboardWidgets().catch(() => {})
}

function updateThemeMenuPosition() {
  const trigger = themeTriggerRef.value
  if (!trigger) return
  const rect = trigger.getBoundingClientRect()
  const menuWidth = 250
  const margin = 8
  themeMenuPosition.value = {
    top: Math.round(rect.bottom + 6),
    left: Math.max(margin, Math.min(window.innerWidth - menuWidth - margin, Math.round(rect.right - menuWidth))),
  }
}

function toggleThemePicker() {
  if (showThemePicker.value) {
    showThemePicker.value = false
    return
  }
  updateThemeMenuPosition()
  showThemePicker.value = true
}

function hydrateBoardStudioState(studio: any) {
  const screens = Array.isArray(studio?.screens) && studio.screens.length
    ? studio.screens.filter((screen: any) => typeof screen?.id === 'string' && typeof screen?.name === 'string')
    : [{ id: 'screen-1', name: 'Dashboard' }]

  boardScreens.value = screens
  activeScreenId.value = screens.some((screen: any) => screen.id === studio?.active_screen_id)
    ? studio.active_screen_id
    : screens[0].id

  const incomingShareTokens = typeof studio?.screen_share_tokens === 'object' && studio?.screen_share_tokens
    ? studio.screen_share_tokens
    : {}
  const normalizedShareTokens: Record<string, string> = {}
  for (const screen of screens) {
    const token = (incomingShareTokens as Record<string, unknown>)[screen.id]
    if (typeof token === 'string' && token.trim()) {
      normalizedShareTokens[screen.id] = token
    }
  }

  // Prefer incoming tokens, then keep known local/project tokens for missing entries.
  const mergedSource = {
    ...(dashboardProject.value?.screen_share_tokens || {}),
    ...(boardScreenShareTokens.value || {}),
    ...normalizedShareTokens,
  } as Record<string, string>
  const mergedShareTokens: Record<string, string> = Object.fromEntries(
    screens
      .map((screen: any) => [screen.id, mergedSource[screen.id]])
      .filter((entry: any) => typeof entry?.[1] === 'string' && !!String(entry[1]).trim())
  ) as Record<string, string>
  boardScreenShareTokens.value = mergedShareTokens
  if (dashboardProject.value) {
    dashboardProject.value.screen_share_tokens = { ...mergedShareTokens }
  }

  if (typeof studio?.active_theme === 'string' && studio.active_theme) {
    activeTheme.value = studio.active_theme
  }

  const persistedTemplateSource = String(studio?.template_source_file_uuid || '').trim()
  const originalSource = String(boardFiles.value[boardFiles.value.length - 1]?.file_uuid || '').trim()
  templateSourceFileId.value = originalSource || persistedTemplateSource || String(internalFileId.value || dashboardProject.value?.active_file_uuid || '')

  if (studio?.design && typeof studio.design === 'object') {
    const nextTexture = String(studio.design.texture || 'none')
    const nextDensity = String(studio.design.density || 'cozy')
    const nextCardStyle = String(studio.design.cardStyle || 'flat')
    boardDesign.value = {
      texture: (['none', 'dots', 'grid', 'gradient'].includes(nextTexture) ? nextTexture : 'none') as any,
      density: (['compact', 'cozy', 'airy'].includes(nextDensity) ? nextDensity : 'cozy') as any,
      cardStyle: (['flat', 'soft', 'glass'].includes(nextCardStyle) ? nextCardStyle : 'flat') as any,
    }
  }

  const screenWidgetsMap = typeof studio?.screen_widgets === 'object' && studio?.screen_widgets
    ? Object.fromEntries(
        Object.entries(studio.screen_widgets)
          .filter(([key, value]) => typeof key === 'string' && Array.isArray(value))
          .map(([key, value]) => [key, cloneWidgetList(value as DashboardWidget[])])
      )
    : {}

  for (const screen of screens) {
    if (!screenWidgetsMap[screen.id]) {
      screenWidgetsMap[screen.id] = []
    }
  }

  // Backward compatibility: if old payload has only widgets, assign them to active screen
  if (!Object.values(screenWidgetsMap).some((items: any) => Array.isArray(items) && items.length)) {
    screenWidgetsMap[activeScreenId.value] = cloneWidgetList(widgets.value)
  }

  const incomingFileMap = typeof studio?.file_screen_widgets === 'object' && studio?.file_screen_widgets
    ? studio.file_screen_widgets
    : null

  if (incomingFileMap) {
    const normalizedFileMap: Record<string, Record<string, DashboardWidget[]>> = {}
    for (const [fileId, screensMap] of Object.entries(incomingFileMap)) {
      if (typeof fileId !== 'string' || !screensMap || typeof screensMap !== 'object') continue
      normalizedFileMap[fileId] = {}
      for (const screen of screens) {
        const value = (screensMap as any)[screen.id]
        normalizedFileMap[fileId][screen.id] = Array.isArray(value) ? cloneWidgetList(value as DashboardWidget[]) : []
      }
    }
    boardFileScreenWidgets.value = normalizedFileMap
  }

  const currentFileKey = getActiveBoardFileKey()
  if (!boardFileScreenWidgets.value[currentFileKey]) {
    boardFileScreenWidgets.value[currentFileKey] = {}
  }
  if (!Object.keys(boardFileScreenWidgets.value[currentFileKey]).length) {
    boardFileScreenWidgets.value[currentFileKey] = screenWidgetsMap
  }

  const sourceKey = getTemplateSourceFileKey()
  if (!boardFileScreenWidgets.value[sourceKey]) {
    boardFileScreenWidgets.value[sourceKey] = JSON.parse(JSON.stringify(boardFileScreenWidgets.value[currentFileKey] || {}))
  }

  const incomingNeedsGeneration = typeof studio?.file_screen_needs_generation === 'object' && studio?.file_screen_needs_generation
    ? studio.file_screen_needs_generation
    : null
  if (incomingNeedsGeneration) {
    const normalizedNeedsMap: Record<string, Record<string, boolean>> = {}
    for (const [fileId, screensMap] of Object.entries(incomingNeedsGeneration)) {
      if (typeof fileId !== 'string' || !screensMap || typeof screensMap !== 'object') continue
      normalizedNeedsMap[fileId] = {}
      for (const screen of screens) {
        normalizedNeedsMap[fileId][screen.id] = Boolean((screensMap as any)[screen.id])
      }
    }
    boardFileScreenNeedsGeneration.value = normalizedNeedsMap
  }

  const incomingPendingTemplates = typeof studio?.file_screen_pending_templates === 'object' && studio?.file_screen_pending_templates
    ? studio.file_screen_pending_templates
    : null
  if (incomingPendingTemplates) {
    const normalizedPendingMap: Record<string, Record<string, DashboardWidget[]>> = {}
    for (const [fileId, screensMap] of Object.entries(incomingPendingTemplates)) {
      if (typeof fileId !== 'string' || !screensMap || typeof screensMap !== 'object') continue
      normalizedPendingMap[fileId] = {}
      for (const screen of screens) {
        const value = (screensMap as any)[screen.id]
        normalizedPendingMap[fileId][screen.id] = Array.isArray(value) ? cloneWidgetList(value as DashboardWidget[]) : []
      }
    }
    boardFileScreenPendingTemplates.value = normalizedPendingMap
  }

  // Ensure current file has complete generation/template maps for all screens.
  const currentNeedsMap = getBoardFileGenerationMap(currentFileKey)
  const currentPendingMap = getBoardFilePendingTemplates(currentFileKey)
  for (const screen of screens) {
    if (currentNeedsMap[screen.id] === undefined) currentNeedsMap[screen.id] = false
    if (!Array.isArray(currentPendingMap[screen.id])) currentPendingMap[screen.id] = []
  }

  boardScreenWidgets.value = boardFileScreenWidgets.value[currentFileKey]
  boardScreenThumbnails.value = Object.fromEntries(screens.map((screen: any) => [screen.id, '']))
  ensureBoardFileScreens()
  widgets.value = resolveScreenWidgetsForRender(activeScreenId.value)
}

function getBoardSavePayload(): BoardDashboardSaveRequest {
  snapshotActiveScreenWidgets()
  const payload = {
    widgets: widgets.value,
    screens: boardScreens.value,
    active_screen_id: activeScreenId.value,
    active_theme: activeTheme.value,
    screen_widgets: boardScreenWidgets.value,
    file_screen_widgets: boardFileScreenWidgets.value,
    file_screen_needs_generation: boardFileScreenNeedsGeneration.value,
    file_screen_pending_templates: boardFileScreenPendingTemplates.value,
    template_source_file_uuid: getTemplateSourceFileKey(),
    design: boardDesign.value,
  }
  return payload as BoardDashboardSaveRequest
}

// ── PROPS & COMPUTED ───────────────────────────────────────────
const props = defineProps<{ fileUuid?: string }>()

// Internal file ID set by project-first init (writable source for project mode)
const internalFileId = ref<string>('')
// Block the resolvedFileId watcher from re-loading during project-first init
let skipNextFileIdWatch = false
// True when project has no files — shows upload CTA instead of editor
const noFileState = ref(false)

const resolvedFileId = computed(() =>
  internalFileId.value ||
  props.fileUuid ||
  (route.query.fileId as string) ||
  ''
)

const dashboardSourceType = computed<'file' | 'database'>(() => (
  route.query.type === 'db' ? 'database' : 'file'
))

// ── DASHBOARD-FIRST STATE ──────────────────────────────────────
// Support both /app/dashboard/:projectId (new) and ?project_id= query (legacy)
const activeProjectId = computed(() => (route.params.projectId as string) || (route.query.project_id as string) || '')
const isDashboardProject = computed(() => !!activeProjectId.value || isBoardMode.value)

// ── BOARD MODE (standalone Insight Boards) ─────────────────────
const activeBoardId = computed(() => (route.params.boardId as string) || '')
const isBoardMode = computed(() => !!activeBoardId.value)

// ── SHARED MODE (read-only public view) ────────────────────────
const shareToken = computed(() => (route.params.token as string) || '')
const isSharedMode = computed(() => !!shareToken.value)

let rootDarkBeforeShared: boolean | null = null

function enterSharedLightMode() {
  const root = document.documentElement
  if (rootDarkBeforeShared === null) {
    rootDarkBeforeShared = root.classList.contains('dark')
  }
  root.classList.remove('dark')
}

function exitSharedLightMode() {
  if (rootDarkBeforeShared === null) return
  const root = document.documentElement
  root.classList.toggle('dark', rootDarkBeforeShared)
  rootDarkBeforeShared = null
}

watch(isSharedMode, (shared) => {
  if (shared) enterSharedLightMode()
  else exitSharedLightMode()
}, { immediate: true })

// The Dashboard Project object (if viewing a Dashboard-first project)
const dashboardProject = computed(() => {
  if (isBoardMode.value) return boardProjectProxy.value
  return store.dashboardFolders.find(p => p.project_id === activeProjectId.value) || null
})

// Board-mode proxy: shaped like a project so the rest of the component works unchanged
const boardProjectProxy = ref<any>(null)
// Board files list (separate from store.sortedFiles)
const boardFiles = ref<FileInfo[]>([])

// Data sources available for this dashboard
const dataSources = computed<FileInfo[]>(() => {
  if (isBoardMode.value) return boardFiles.value
  if (!activeProjectId.value) return []
  return store.sortedFiles.filter(f => String(f.project_id) === activeProjectId.value)
})

// Current active active data source ID
const activeDataSourceId = computed(() => {
  return dashboardProject.value?.active_file_uuid || ''
})

const isTemplateSourceActive = computed(() => {
  if (!isBoardMode.value) return true
  return getActiveBoardFileKey() === getTemplateSourceFileKey()
})

const canMutateWidgets = computed(() => {
  if (isSharedMode.value) return false
  if (!isBoardMode.value) return true
  return isTemplateSourceActive.value
})

function guardTemplateMutation(): boolean {
  if (!isBoardMode.value) return true
  if (isTemplateSourceActive.value) return true
  toast.error('Only the source file can change screen templates.')
  return false
}

function toggleAddWidgetPopover() {
  if (!guardTemplateMutation()) return
  showAddPopover.value = !showAddPopover.value
}

const dashboardDisplayTitle = computed(() => {
  const projectName = String(dashboardProject.value?.name || '').trim()
  if (isDashboardProject.value && projectName) return projectName
  const fileName = String(fileInfo.value?.filename || '').trim()
  if (fileName) return fileName
  return 'Insight Dashboard'
})

async function loadDataSources() {
  if (!activeProjectId.value) return
  try {
    // Refresh files list just in case
    await store.fetchAll()
  } catch (e) {
    console.error('[Dashboard] Failed to load data sources:', e)
  }
}

// ── PROJECT-FIRST INIT ────────────────────────────────────────

async function initProjectDashboard() {
  if (!activeProjectId.value) return
  isLoading.value = true
  noFileState.value = false
  try {
    const data = await excelFileAPI.getProjectDashboard(activeProjectId.value)

    // Sync project info into store so header dropdown etc. stays current
    await store.fetchAll()

    if (!data.project.active_file_uuid || !data.files.length) {
      noFileState.value = true
      return
    }

    // Set the canonical active file WITHOUT triggering the watcher reload
    skipNextFileIdWatch = true
    internalFileId.value = data.project.active_file_uuid
    if (!templateSourceFileId.value) {
      templateSourceFileId.value = data.project.active_file_uuid
    }
    await ensureChartSchema(data.project.active_file_uuid)

    if (data.dashboard_data) {
      widgets.value = data.dashboard_data.widgets || []
      originalWidgets.value = JSON.parse(JSON.stringify(widgets.value))
      dashboardData.value = data.dashboard_data
      fingerprint.value = data.dashboard_data.fingerprint || null
      originalFingerprint.value = data.dashboard_data.fingerprint
        ? JSON.parse(JSON.stringify(data.dashboard_data.fingerprint))
        : null
      slicerValues.value = {}
      dashboardLoadedAt.value = new Date().toLocaleDateString('en-US', {
        month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
      })

      // Positions are already stored in dashboard_data from the dashboards table.
      // Only fall back to auto-position if widgets lack grid coords.
      const hasPositions = widgets.value.some(w => (w as any).gridX !== undefined || (w as any).gridY !== undefined)
      if (!hasPositions) {
        autoPositionWidgets()
      }

      isDashboardLocked.value = store.getDashboardLockState(internalFileId.value)
      activeTheme.value = store.getDashboardTheme(internalFileId.value)

      // Populate fileInfo from the files list (avoids an extra /api/files call)
      const activeFileMeta = data.files.find((f: any) => f.file_uuid === internalFileId.value)
      if (activeFileMeta) {
        fileInfo.value = {
          file_uuid: activeFileMeta.file_uuid,
          filename: activeFileMeta.filename,
          table_name: activeFileMeta.table_name || '',
          total_rows: activeFileMeta.total_rows || 0,
          columns: [],
          column_stats: {},
        } as FileInfo
      }

      if (widgets.value.length > 0) { await nextTick(); initGrid() }
      if (isCurrentScreenPendingGeneration.value && !isGeneratingPendingScreen.value) {
        void generatePendingScreenDashboard()
      }
    }
  } catch (e: any) {
    if (e.response?.status === 401) {
      router.push('/login')
    } else if (e.response?.status === 403) {
      toast.error('Access denied to this dashboard')
      router.push('/app')
    } else {
      toast.error('Failed to load dashboard: ' + (e.response?.data?.detail || e.message))
    }
  } finally {
    isLoading.value = false
  }
}

// ── BOARD-FIRST INIT ──────────────────────────────────────────

async function initBoardDashboard() {
  if (!activeBoardId.value) return
  // Set session ID before API call so trace buttons appear immediately after load
  dashboardSessionId.value = `board-${activeBoardId.value}`
  isLoading.value = true
  noFileState.value = false
  try {
    const data = await excelFileAPI.getBoardDashboard(activeBoardId.value)
    captureTrace(data)

    // Build board proxy so template references work
    boardProjectProxy.value = {
      project_id: data.project.project_id,
      name: data.project.name,
      created_on: data.project.created_on,
      color: data.project.color,
      is_dashboard: true,
      active_file_uuid: data.project.active_file_uuid,
      is_shared: data.project.is_shared,
      share_token: data.project.share_token,
      screen_share_tokens: data.project.screen_share_tokens || {},
      published_file_uuid: data.project.published_file_uuid,
    }
    boardScreenShareTokens.value = data.project.screen_share_tokens || {}

    // Populate board files
    boardFiles.value = (data.files || []).map((f: any) => ({
      file_uuid: f.file_uuid,
      filename: f.filename,
      table_name: f.table_name || '',
      total_rows: f.total_rows || 0,
      columns: [],
      column_stats: {},
      created_on: f.created_on,
      project_id: activeBoardId.value,
    })) as FileInfo[]

    if (!data.project.active_file_uuid || !data.files.length) {
      noFileState.value = true
      return
    }

    skipNextFileIdWatch = true
    internalFileId.value = data.project.active_file_uuid
    await ensureChartSchema(data.project.active_file_uuid)

    if (data.dashboard_data) {
      widgets.value = data.dashboard_data.widgets || []
      originalWidgets.value = JSON.parse(JSON.stringify(widgets.value))
      dashboardData.value = data.dashboard_data
      fingerprint.value = data.dashboard_data.fingerprint || null
      originalFingerprint.value = data.dashboard_data.fingerprint
        ? JSON.parse(JSON.stringify(data.dashboard_data.fingerprint))
        : null
      slicerValues.value = {}
      dashboardLoadedAt.value = new Date().toLocaleDateString('en-US', {
        month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
      })

      const hasPositions = widgets.value.some(w => (w as any).gridX !== undefined || (w as any).gridY !== undefined)
      if (!hasPositions) autoPositionWidgets()

      isDashboardLocked.value = store.getDashboardLockState(internalFileId.value)
      activeTheme.value = store.getDashboardTheme(internalFileId.value)
      hydrateBoardStudioState(data.dashboard_data.studio)

      const activeFileMeta = data.files.find((f: any) => f.file_uuid === internalFileId.value)
      if (activeFileMeta) {
        fileInfo.value = {
          file_uuid: activeFileMeta.file_uuid,
          filename: activeFileMeta.filename,
          table_name: activeFileMeta.table_name || '',
          total_rows: activeFileMeta.total_rows || 0,
          columns: [],
          column_stats: {},
        } as FileInfo
      }

      if (widgets.value.length > 0) { await nextTick(); initGrid() }
    }
  } catch (e: any) {
    if (e.response?.status === 401) {
      router.push('/login')
    } else if (e.response?.status === 403) {
      toast.error('Access denied to this board')
      router.push('/app')
    } else {
      toast.error('Failed to load board: ' + (e.response?.data?.detail || e.message))
    }
  } finally {
    isLoading.value = false
  }
}

// ── SHARED MODE INIT (read-only public view) ──────────────────

async function initSharedDashboard() {
  if (!shareToken.value) return
  isLoading.value = true
  noFileState.value = false
  try {
    const data = await excelFileAPI.getSharedDashboard(shareToken.value)

    // Build a proxy so template references work
    boardProjectProxy.value = {
      project_id: data.project_id || '',
      name: data.project_name || 'Shared Dashboard',
      created_on: null,
      color: data.color || null,
      is_dashboard: true,
      active_file_uuid: null,
      is_shared: true,
      share_token: shareToken.value,
    }

    if (!data.dashboard_data?.widgets?.length) {
      noFileState.value = true
      return
    }

    widgets.value = data.dashboard_data.widgets || []
    originalWidgets.value = JSON.parse(JSON.stringify(widgets.value))
    dashboardData.value = data.dashboard_data

    const sharedThemeKey = String(
      data.dashboard_data?.studio?.active_theme
      || data.dashboard_data?.theme
      || ''
    ).trim()
    if (sharedThemeKey && colorThemes[sharedThemeKey]) {
      activeTheme.value = sharedThemeKey
    }

    fingerprint.value = data.dashboard_data.fingerprint || null
    originalFingerprint.value = data.dashboard_data.fingerprint
      ? JSON.parse(JSON.stringify(data.dashboard_data.fingerprint))
      : null
    slicerValues.value = {}
    dashboardLoadedAt.value = new Date().toLocaleDateString('en-US', {
      month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
    })

    const hasPositions = widgets.value.some(w => (w as any).gridX !== undefined || (w as any).gridY !== undefined)
    if (!hasPositions) autoPositionWidgets()

    isDashboardLocked.value = false  // shared mode starts unlocked — drag/resize enabled
    dashboardSessionId.value = `share-${shareToken.value}`
    chartSchema.value = null
    chartSchemaFileId.value = ''

    if (widgets.value.length > 0) { await nextTick(); initGrid() }
  } catch (e: any) {
    toast.error('This dashboard is unavailable or the link has expired.')
    noFileState.value = true
  } finally {
    isLoading.value = false
  }
}

// ── ADD DATA SOURCE UPLOAD ─────────────────────────────────────
const dataSourceFileInput = ref<HTMLInputElement | null>(null)

function triggerDataSourceUpload() {
  dataSourceFileInput.value?.click()
}

async function handleDataSourceUpload(event: Event) {
  const input = event.target as HTMLInputElement
  if (!input.files?.length) return
  if (!isBoardMode.value && !activeProjectId.value) return
  
  const file = input.files[0]
  toast.info('Uploading new data source...')
  
  try {
    let resultFileUuid: string

    if (isBoardMode.value) {
      // Board mode: lightweight upload (no embeddings)
      const result = await excelFileAPI.uploadBoardFile(activeBoardId.value, file)
      resultFileUuid = result.file_uuid

      if (!result.is_first_file && result.extra_columns?.length) {
        toast.info(`File has extra columns (${result.extra_columns.join(', ')}) — template still compatible.`)
      }

      // Add to local board files list
      boardFiles.value.unshift({
        file_uuid: result.file_uuid,
        filename: result.filename,
        table_name: '',
        total_rows: result.rows || 0,
        columns: result.columns || [],
        column_stats: {},
      } as FileInfo)
    } else {
      // Project mode: full upload pipeline
      const result = await excelFileAPI.uploadFileWithProgress(
        file,
        (stage, progress) => {
          if (progress > 0) toast.loading(`Uploading... ${progress}%`, { id: 'datasource-upload' })
        },
        activeProjectId.value,
        null
      )
      resultFileUuid = result.file_uuid
      await store.fetchAll()
    }
    
    toast.success('Upload complete!', { id: 'datasource-upload' })
    input.value = ''
    
    await switchActiveDataSource(resultFileUuid)
    
  } catch (e: any) {
    console.error('Data source upload failed:', e)
    const detail = e.response?.data?.detail || e.message
    if (e.response?.status === 400) {
      toast.warning('Template mismatch: ' + detail, { id: 'datasource-upload' })
    } else {
      toast.error('Failed to upload file: ' + detail, { id: 'datasource-upload' })
    }
    isLoading.value = false
    return
  }
}

async function switchActiveDataSource(fileUuid: string) {
  if (!fileUuid) return
  if (!isBoardMode.value && !activeProjectId.value) return
  if (fileUuid === internalFileId.value) return  // no-op if already active

  if (isBoardMode.value) {
    snapshotActiveScreenWidgets()
    ensureBoardFileScreens(fileUuid)
  }

  const sourceTemplateScreensForSwitch = isBoardMode.value ? getSourceTemplateScreens() : {}

  if (isBoardMode.value && activeScreenId.value) {
    const activeTemplate = cloneWidgetList((sourceTemplateScreensForSwitch?.[activeScreenId.value] || []) as DashboardWidget[])
    if (activeTemplate.length > 0) {
      widgets.value = activeTemplate.map((widget) => ({ ...(widget as any), isLoadingData: true })) as DashboardWidget[]
      await nextTick()
      try { grid?.destroy(false) } catch {}
      grid = null
      initGrid()
    }
  }

  // Phase 6: Per-widget streaming — keep existing grid visible, pop in widgets one-by-one
  const hasExistingWidgets = widgets.value.length > 0
  if (hasExistingWidgets) {
    widgets.value.forEach(w => { (w as any).isLoadingData = true })
    toast.info('Loading new data into widgets...')
  } else {
    isLoading.value = true
    toast.info('Switching data source...')
  }

  // Update local project store reference eagerly
  if (dashboardProject.value) {
    dashboardProject.value.active_file_uuid = fileUuid
  }
  skipNextFileIdWatch = true
  internalFileId.value = fileUuid

  try {
    // Use streaming endpoint for side-by-side widget loading
    const streamCtx = isBoardMode.value
      ? excelFileAPI.switchBoardActiveFileStream(activeBoardId.value, fileUuid, dashboardSessionId.value)
      : excelFileAPI.setActiveFileStream(activeProjectId.value, fileUuid)

    const response = await streamCtx.response
    if (!response.ok) {
      const errText = await response.text()
      throw new Error(errText || `HTTP ${response.status}`)
    }

    const reader = response.body?.getReader()
    if (!reader) throw new Error('No readable stream')
    const decoder = new TextDecoder()
    let buffer = ''
    const oldMap = hasExistingWidgets ? new Map(widgets.value.map(w => [w.id, w])) : null

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })

      // Process complete NDJSON lines
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''  // keep incomplete line in buffer

      for (const line of lines) {
        if (!line.trim()) continue
        let msg: any
        try { msg = JSON.parse(line) } catch { continue }

        if (msg.type === 'widget' && msg.widget) {
          const nw = msg.widget
          if (oldMap) {
            const existing = oldMap.get(nw.id) as any
            if (existing) {
              const savedX = existing.gridX
              const savedY = existing.gridY
              const savedW = existing.gridW
              const savedH = existing.gridH
              const savedColor = existing.chartColor
              Object.assign(existing, nw)
              if (savedX !== undefined) existing.gridX = savedX
              if (savedY !== undefined) existing.gridY = savedY
              if (savedW !== undefined) existing.gridW = savedW
              if (savedH !== undefined) existing.gridH = savedH
              if (savedColor) existing.chartColor = savedColor
              sanitizeKpiWidgetPayload(existing)
              existing.isLoadingData = false
            } else {
              // If target file had no cached widget with this id, stream it in instead of dropping it.
              const streamed = nw as any
              if (streamed.gridW === undefined || streamed.gridW === null) {
                streamed.gridW = (streamed.type === 'summary') ? 12 : 3
              }
              if (streamed.gridH === undefined || streamed.gridH === null) {
                streamed.gridH = (streamed.type === 'kpi') ? 2 : 2
              }
              if (streamed.gridX === undefined || streamed.gridX === null || streamed.gridY === undefined || streamed.gridY === null) {
                const nextBottomY = widgets.value.reduce((maxY, item) => {
                  const y = Number((item as any).gridY ?? 0)
                  const h = Number((item as any).gridH ?? 2)
                  return Math.max(maxY, y + h)
                }, 0)
                if (streamed.gridX === undefined || streamed.gridX === null) streamed.gridX = 0
                if (streamed.gridY === undefined || streamed.gridY === null) streamed.gridY = nextBottomY
              }
              sanitizeKpiWidgetPayload(streamed)
              widgets.value.push(streamed)
              oldMap.set(streamed.id, streamed)
            }
          } else {
            // No existing widgets — append as they arrive
            const streamed = nw as any
            sanitizeKpiWidgetPayload(streamed)
            widgets.value.push(streamed)
          }
          chartRenderEpoch.value++
        } else if (msg.type === 'done') {
          fingerprint.value = msg.fingerprint || null
          if (msg.trace_id) lastTraceId.value = msg.trace_id
          if (msg.trace_url) lastTraceUrl.value = msg.trace_url
          originalFingerprint.value = msg.fingerprint
            ? JSON.parse(JSON.stringify(msg.fingerprint))
            : null
        }
      }
    }

    // Ensure all loading flags are cleared
    widgets.value.forEach(w => { (w as any).isLoadingData = false })

    if (isBoardMode.value) {
      const targetScreens = getBoardFileScreens(fileUuid)
      const generationMap = getBoardFileGenerationMap(fileUuid)
      const pendingTemplates = getBoardFilePendingTemplates(fileUuid)

      for (const screen of boardScreens.value) {
        const sourceTemplateWidgets = cloneWidgetList((sourceTemplateScreensForSwitch?.[screen.id] || []) as DashboardWidget[])
        if (screen.id === activeScreenId.value) {
          targetScreens[screen.id] = cloneWidgetList(widgets.value)
          generationMap[screen.id] = false
          pendingTemplates[screen.id] = []
          continue
        }

        // Non-active screens always follow source file template and auto-generate on first open.
        targetScreens[screen.id] = []
        generationMap[screen.id] = sourceTemplateWidgets.length > 0
        pendingTemplates[screen.id] = sourceTemplateWidgets
      }

      const key = getActiveBoardFileKey(fileUuid)
      boardFileScreenWidgets.value[key] = targetScreens
      boardFileScreenNeedsGeneration.value[key] = generationMap
      boardFileScreenPendingTemplates.value[key] = pendingTemplates
      boardScreenWidgets.value = targetScreens
      await persistDashboardWidgets()
    }

    if (!hasExistingWidgets && widgets.value.length) {
      const hasPositions = widgets.value.some(w => (w as any).gridX !== undefined || (w as any).gridY !== undefined)
      if (!hasPositions) autoPositionWidgets()
      await nextTick(); initGrid()
    }

    originalWidgets.value = JSON.parse(JSON.stringify(widgets.value))
    slicerValues.value = {}
    noFileState.value = false
    await ensureChartSchema(fileUuid)
    toast.success('Data source switched!')
  } catch (e: any) {
    toast.error('Failed to switch data source: ' + (e.message || e))
    widgets.value.forEach(w => { (w as any).isLoadingData = false })
  } finally {
    isLoading.value = false
  }
}

// ── SHARE DASHBOARD ────────────────────────────────────────────
async function toggleShareStatus() {
  if (!isBoardMode.value && !activeProjectId.value) return
  try {
    const res = isBoardMode.value
      ? await excelFileAPI.toggleBoardShare(activeBoardId.value, widgets.value, activeScreenId.value)
      : await excelFileAPI.toggleProjectShare(activeProjectId.value)
    if (dashboardProject.value) {
        dashboardProject.value.is_shared = res.is_shared
        dashboardProject.value.share_token = res.share_token ?? undefined
        if (isBoardMode.value && (res as any).share_tokens_by_screen) {
          const screenMap = (res as any).share_tokens_by_screen as Record<string, string>
          boardScreenShareTokens.value = { ...screenMap }
          dashboardProject.value.screen_share_tokens = { ...screenMap }
          const activeToken = screenMap[activeScreenId.value]
          if (activeToken) {
            dashboardProject.value.share_token = activeToken
          }
        }
        dashboardProject.value.published_file_uuid = res.is_shared
          ? ((res as any).published_file_uuid ?? activeDataSourceId.value)
          : undefined
      }
    const msg = res.is_shared ? 'Dashboard is now public' : 'Dashboard is now private'
    toast.success(msg)
  } catch (e: any) {
    toast.error('Failed to change share status: ' + (e.response?.data?.detail || e.message))
  }
}

const currentShareLink = computed(() => {
  if (!dashboardProject.value?.is_shared) return ''

  const token = isBoardMode.value
    ? (boardScreenShareTokens.value[activeScreenId.value] || dashboardProject.value?.share_token)
    : dashboardProject.value?.share_token
  if (!token) return ''

  const configuredShareBaseRaw = String(
    (import.meta.env.VITE_SHARE_BASE_URL as string)
    || (import.meta.env.VITE_PUBLIC_BASE_URL as string)
    || ''
  ).trim()

  const normalizeBaseUrl = (raw: string): string => {
    let out = raw.trim()
    while (out.endsWith('/')) out = out.slice(0, -1)
    return out
  }

  const base = configuredShareBaseRaw
    ? normalizeBaseUrl(configuredShareBaseRaw)
    : normalizeBaseUrl(window.location.origin)

  return `${base}/#/share/${token}`
})

watch(currentShareLink, (link) => {
  window.dispatchEvent(new CustomEvent('topbar-share-link-updated', { detail: link }))
}, { immediate: true })

function copyShareLink() {
  const url = currentShareLink.value
  if (!url) return

  navigator.clipboard.writeText(url)
    .then(() => {
      toast.success('Share link copied to clipboard!')
    })
    .catch(() => {
      toast.error('Copy failed. Use hover link to copy manually.')
    })
}

async function publishBoard() {
  if (!isBoardMode.value) return
  try {
    await excelFileAPI.publishBoard(activeBoardId.value, widgets.value)
    if (dashboardProject.value) {
      dashboardProject.value.published_file_uuid = activeDataSourceId.value
    }
    toast.success('Shared view updated with current layout')
  } catch (e: any) {
    toast.error('Failed to publish: ' + (e.response?.data?.detail || e.message))
  }
}

async function togglePublishFreeze() {
  if (!isBoardMode.value) return
  const isCurrentlyFrozen = !!dashboardProject.value?.published_file_uuid
  try {
    if (isCurrentlyFrozen) {
      // Unfreeze → back to live mode
      await excelFileAPI.unpublishBoard(activeBoardId.value)
      if (dashboardProject.value) dashboardProject.value.published_file_uuid = undefined
      toast.success('Shared view is now live — showing active file dashboard')
    } else {
      // Freeze current file's dashboard for shared viewers
      const res = await excelFileAPI.publishBoard(activeBoardId.value, widgets.value)
      if (dashboardProject.value) {
        dashboardProject.value.published_file_uuid = (res as any).published_file_uuid ?? activeDataSourceId.value
      }
      toast.success(`Frozen: shared viewers will see ${dataSources.value.find((f: FileInfo) => f.file_uuid === activeDataSourceId.value)?.filename || 'this'} dashboard`)
    }
  } catch (e: any) {
    toast.error('Failed to toggle: ' + (e.response?.data?.detail || e.message))
  }
}

// forceApplyTemplate removed — auto-apply is handled directly in loadDashboard
// ── LANGFUSE SESSION & TRACE ──────────────────────────────────
const dashboardSessionId = ref('')
const lastTraceId = ref('')
const lastTraceUrl = ref('')

function initDashboardSession() {
  dashboardSessionId.value = `dashboard-${resolvedFileId.value}`
}

function captureTrace(response: any) {
  if (response?.trace_id) lastTraceId.value = response.trace_id
  if (response?.trace_url) lastTraceUrl.value = response.trace_url
}

const isOpeningSession = ref(false)

async function openDashboardSession() {
  if (!dashboardSessionId.value || isOpeningSession.value) return
  isOpeningSession.value = true
  try {
    const ssoUrl = await excelFileAPI.getLangfuseSsoUrl(dashboardSessionId.value, { target: 'session' })
    window.open(ssoUrl, '_blank', 'noopener')
  } catch (error: any) {
    toast.error(error?.response?.data?.detail || 'Failed to open Langfuse session')
  } finally {
    isOpeningSession.value = false
  }
}

function openLastDashboardTrace() {
  const url = (lastTraceUrl.value || '').trim()
  if (url) {
    window.open(url, '_blank', 'noopener')
    return
  }
  if (lastTraceId.value) {
    toast.info(`Latest trace id: ${lastTraceId.value}`)
    return
  }
  toast.info('No dashboard trace found yet. Run Regenerate or any dashboard action first.')
}


const dashboardLoadedAt = ref('')
const dashboardCacheHit = ref<boolean | null>(null)

const lastUpdated = computed(() => {
  if (dashboardLoadedAt.value) return dashboardLoadedAt.value
  if (!fileInfo.value?.created_on) return '—'
  return new Date(fileInfo.value.created_on).toLocaleDateString('en-US', {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
  })
})

const filteredCommands = computed(() => {
  const cmds = [
    { id: 'regen', label: 'Regenerate Dashboard', icon: '⟳', action: () => loadDashboard(true) },
    { id: 'lock', label: isDashboardLocked.value ? 'Unlock Layout' : 'Lock Layout', icon: isDashboardLocked.value ? '🔓' : '🔒', action: toggleLock },
    { id: 'files', label: 'Go to Files', icon: '→', action: () => router.push('/app') },
    { id: 'kpi', label: 'Add KPI Widget', icon: '▦', action: () => promptWidget('e.g. Total revenue, avg salary…') },
    { id: 'chart', label: 'Add Chart Widget', icon: '◑', action: () => promptWidget('e.g. Bar chart of sales by region…') },
    { id: 'list', label: 'Add Top-N List', icon: '≡', action: () => promptWidget('e.g. Top 5 cities by employee count…') },
    { id: 'insight', label: 'Add Insight', icon: '💡', action: () => promptWidget('e.g. Key patterns in the data…') },
    { id: 'export-png', label: 'Export as PNG', icon: '📷', action: exportDashboardPNG },
    { id: 'export-pdf', label: 'Export as PDF', icon: '📄', action: exportDashboardPDF },
  ]
  const q = commandQuery.value.toLowerCase()
  return q ? cmds.filter(c => c.label.toLowerCase().includes(q)) : cmds
})

// ── WATCHERS ───────────────────────────────────────────────────
watch(() => isDashboardLocked.value, (v) => {
  if (resolvedFileId.value) store.setDashboardLockState(resolvedFileId.value, v)
})

watch(showCommandPalette, async (show) => {
  if (show) { await nextTick(); commandInputRef.value?.focus() }
})

// ── CHART HELPERS (ECharts) ────────────────────────────────────
function getEChartOption(widget: any, index: number = 0): Record<string, any> {
  ensureWidgetUiDefaults(widget)
  const widgetUi = widget?.ui || {}
  const theme = getWidgetTheme(widget, index)
  const colors = theme.chart.length ? theme.chart : defaultChartColors.value

  // For unified comparison charts, interleave base+compare theme colors
  const isComparison = widget.is_comparison === true
  const comparisonColors = isComparison
    ? (() => {
        const cmpTheme = getCompareWidgetTheme()
        const cmpC = cmpTheme.chart.length ? cmpTheme.chart : ['#e11d48', '#f43f5e', '#fb7185']
        // Interleave: base1, cmp1, base2, cmp2, ...
        const interleaved: string[] = []
        const maxLen = Math.max(colors.length, cmpC.length)
        for (let i = 0; i < maxLen; i++) {
          if (i < colors.length) interleaved.push(colors[i])
          if (i < cmpC.length) interleaved.push(cmpC[i])
        }
        return interleaved
      })()
    : colors

  const chartType = widget.chartType || 'bar'
  const isPieType = ['pie', 'donut', 'doughnut', 'polarArea'].includes(chartType)
  const isHorizontal = widget.horizontal === true
  const axisNameColor = '#475569'
  const axisTickColor = '#64748b'
  const splitLineColor = 'rgba(148, 163, 184, 0.35)'

  // Apply per-chart value filter (client-side, non-destructive)
  const rawLabels: string[] = widget.chartData?.labels || []
  const rawSeriesAll: any[] = widget.chartData?.series || widget.series || []
  const { labels, series: rawSeries } = isPieType
    ? { labels: rawLabels, series: rawSeriesAll }  // pie slices handled differently below
    : getFilteredChartData(widget.id, widget.chartData, rawSeriesAll)

  const seriesCount = (Array.isArray(rawSeries) && rawSeries.length > 0 && typeof rawSeries[0] === 'object' && rawSeries[0]?.data)
    ? rawSeries.length
    : 1

  const firstSeriesName = Array.isArray(rawSeries) && rawSeries.length > 0
    ? (typeof rawSeries[0] === 'object' ? String(rawSeries[0]?.name || '') : '')
    : ''

  const inferredCategoryAxisName = prettifyAxisName(
    widget?.filter_context?.column
    || widget?.chartData?.x_axis_label
    || widget?.chartData?.xAxisLabel
    || widget?.chartData?.dimension
    || ''
  )

  const inferredValueAxisName = prettifyAxisName(
    widget?.chartData?.y_axis_label
    || widget?.chartData?.yAxisLabel
    || widget?.chartData?.measure
    || firstSeriesName
    || 'Value'
  )

  const showLegend = typeof widgetUi.showLegend === 'boolean'
    ? (widgetUi.showLegend && (isPieType || isComparison || seriesCount > 1))
    : (isComparison || (isPieType ? labels.length <= 8 : seriesCount > 1))

  const base: Record<string, any> = {
    color: comparisonColors,
    backgroundColor: 'transparent',
    tooltip: {
      trigger: isPieType ? 'item' : 'axis',
      backgroundColor: '#fff',
      borderColor: '#e2e8f0',
      borderWidth: 1,
      textStyle: { color: '#334155', fontSize: 12 },
      confine: true,
      extraCssText: 'box-shadow: 0 4px 16px rgba(0,0,0,0.08); border-radius: 8px; padding: 8px 12px;'
    },
    legend: {
      show: showLegend,
      top: isPieType ? undefined : 6,
      bottom: isPieType ? 4 : undefined,
      left: 10,
      right: 10,
      type: 'scroll',
      textStyle: { color: axisTickColor, fontSize: 11 },
      formatter: (name: string) => String(name || '').replace(/_/g, ' ').trim(),
      icon: 'circle',
      itemWidth: 8,
      itemHeight: 8,
      itemGap: 10
    },
    animationDuration: 600,
    animationEasing: 'cubicInOut',
  }

  const barWidth = Number(widgetUi.barWidth)
  const computedBarWidth = Number.isFinite(barWidth) && barWidth > 0 ? Math.min(72, Math.max(10, barWidth)) : 36

  // ── SPECIAL CHART TYPES (funnel, gauge, heatmap, treemap, waterfall, etc) ──
  if (['funnel', 'gauge', 'heatmap', 'treemap', 'waterfall'].includes(chartType)) {
    if (chartType === 'funnel') {
      base.series = [{
        type: 'funnel',
        data: rawLabels.map((l: string, i: number) => ({
          name: l,
          value: typeof rawSeries[0] === 'number' ? rawSeries[i] : (rawSeries[i]?.data?.[0] ?? rawSeries[0]?.data?.[i] ?? 0)
        })),
        label: { show: true, formatter: '{b}: {d}%' }
      }]
      base.tooltip = { trigger: 'item', formatter: (p: any) => `${p.name}: ${p.value}` }
    } else if (chartType === 'gauge') {
      const val = typeof rawSeries[0] === 'number' ? rawSeries[0] : (rawSeries[0]?.data?.[0] ?? 0)
      base.series = [{
        type: 'gauge',
        data: [{ value: val, name: rawLabels[0] || 'Value' }],
        detail: { formatter: '{value}' },
        axisLine: { lineStyle: { color: [[1, colors[0]]] } }
      }]
      base.tooltip = { trigger: 'item' }
    } else if (chartType === 'heatmap') {
      // Heatmap: labels are X, rawSeries[i].name are Y, rawSeries[i].data are values
      const heatmapData: any[] = []
      rawSeries.forEach((s: any, si: number) => {
        (s.data || []).forEach((v: number, xi: number) => {
          heatmapData.push([xi, si, v])
        })
      })
      base.xAxis = { type: 'category', data: rawLabels }
      base.yAxis = { type: 'category', data: rawSeries.map((s: any) => s.name || 'Series') }
      base.visualMap = { min: 0, max: Math.max(...heatmapData.map((d: any) => d[2] ?? 0)) }
      base.series = [{ type: 'heatmap', data: heatmapData }]
      base.tooltip = { trigger: 'item' }
    } else if (chartType === 'treemap') {
      const treeData = rawLabels.map((l: string, i: number) => ({
        name: l,
        value: typeof rawSeries[0] === 'number' ? rawSeries[i] : (rawSeries[i]?.data?.[0] ?? rawSeries[0]?.data?.[i] ?? 0)
      }))
      base.series = [{
        type: 'treemap',
        data: treeData,
        label: { show: true }
      }]
      base.tooltip = { trigger: 'item', formatter: (p: any) => `${p.name}: ${p.value}` }
    } else if (chartType === 'waterfall') {
      const waterfallData: any[] = []
      const values = typeof rawSeries[0] === 'number' ? rawSeries : (rawSeries[0]?.data || [])
      rawLabels.forEach((l: string, i: number) => {
        waterfallData.push({ name: l, value: values[i] ?? 0 })
      })
      base.series = [{
        type: 'bar',  // Waterfall is a styled bar chart
        data: waterfallData.map(d => d.value),
        stack: 'waterfall',
        itemStyle: { color: colors[0] }
      }]
      base.tooltip = { trigger: 'axis', axisPointer: { type: 'shadow' } }
    }
    return base
  }

  if (isPieType) {
    // ── Side-by-side donuts for unified comparison ──
    if (isComparison && widget.base_chartData && widget.cmp_chartData) {
      const baseLabels: string[]  = widget.base_chartData.labels || []
      const baseSeries: any[]     = widget.base_chartData.series || []
      const cmpLabels: string[]   = widget.cmp_chartData.labels  || []
      const cmpSeries: any[]      = widget.cmp_chartData.series  || []

      // Apply per-chart filter — use same filter key for both sides
      const baseFiltered = getFilteredChartData(widget.id, widget.base_chartData, baseSeries)
      const cmpFiltered = getFilteredChartData(widget.id, widget.cmp_chartData, cmpSeries)

      const toSlices = (lbls: string[], ser: any[]) =>
        lbls.map((l: string, i: number) => ({
          name: l,
          value: Array.isArray(ser) && ser.length > 0
            ? (typeof ser[0] === 'number' ? ser[i] : ser[0]?.data?.[i] ?? 0)
            : 0
        }))

      // Distinct palettes: warm blues for base, warm reds/roses for compare
      const baseColors = ['#4f46e5','#6366f1','#818cf8','#a5b4fc','#c7d2fe','#4338ca','#3730a3','#312e81','#e0e7ff','#5b5bd6']
      const cmpColors  = ['#e11d48','#f43f5e','#fb7185','#fda4af','#fecdd3','#be123c','#9f1239','#881337','#ffe4e6','#e8556d']

      const baseLabel = (widget.base_label || 'File A').replace(/\.[^.]+$/, '').slice(0, 18)
      const cmpLabel = (widget.compare_label || 'File B').replace(/\.[^.]+$/, '').slice(0, 18)

      base.legend = { show: false }
      base.title = [
        { text: baseLabel, left: '25%', top: '82%', textAlign: 'center', textStyle: { fontSize: 12, fontWeight: 'bold', color: '#4f46e5' } },
        { text: cmpLabel, left: '75%', top: '82%', textAlign: 'center', textStyle: { fontSize: 12, fontWeight: 'bold', color: '#e11d48' } },
      ]
      base.tooltip = {
        trigger: 'item',
        backgroundColor: '#fff',
        borderColor: '#e2e8f0',
        borderWidth: 1,
        textStyle: { color: '#334155', fontSize: 12 },
        confine: true,
        extraCssText: 'box-shadow:0 4px 16px rgba(0,0,0,.08);border-radius:8px;padding:8px 12px;',
        formatter: (p: any) => `<b>${p.name}</b><br/>${p.seriesName}: <b>${(p.value ?? 0).toLocaleString()}</b> (${p.percent}%)`
      }
      base.series = [
        {
          name: baseLabel,
          type: 'pie',
          radius: ['28%', '58%'],
          center: ['25%', '44%'],
          color: baseColors,
          data: toSlices(baseFiltered.labels, baseFiltered.series),
          label: { show: false },
          labelLine: { show: false },
          emphasis: { scaleSize: 5, itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0,0,0,.12)' } },
          itemStyle: { borderRadius: 4, borderColor: '#fff', borderWidth: 2 }
        },
        {
          name: cmpLabel,
          type: 'pie',
          radius: ['28%', '58%'],
          center: ['75%', '44%'],
          color: cmpColors,
          data: toSlices(cmpFiltered.labels, cmpFiltered.series),
          label: { show: false },
          labelLine: { show: false },
          emphasis: { scaleSize: 5, itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0,0,0,.12)' } },
          itemStyle: { borderRadius: 4, borderColor: '#fff', borderWidth: 2 }
        }
      ]
      return base
    }

    // ── Standard single-file pie/donut ──
    const seriesData = labels.map((l: string, i: number) => ({
      name: l,
      value: Array.isArray(rawSeries) && rawSeries.length > 0
        ? (typeof rawSeries[0] === 'number' ? rawSeries[i] : rawSeries[0]?.data?.[i] ?? 0)
        : 0
    }))
    const isDonut = chartType === 'donut' || chartType === 'doughnut'
    base.legend.bottom = 8
    base.series = [{
      type: 'pie',
      radius: isDonut ? ['45%', '72%'] : '68%',
      center: ['50%', '44%'],
      data: seriesData,
      label: {
        show: labels.length <= 6,
        formatter: labels.length <= 4 ? '{b}\n{d}%' : '{d}%',
        fontSize: 11,
        color: axisNameColor,
        lineHeight: 16
      },
      labelLine: { length: 12, length2: 8 },
      emphasis: {
        scaleSize: 6,
        itemStyle: { shadowBlur: 12, shadowColor: 'rgba(0,0,0,0.12)' }
      },
      itemStyle: { borderRadius: isDonut ? 4 : 0, borderColor: '#fff', borderWidth: 2 }
    }]
  } else {
    // Bar, Line, Area, Scatter
    base.grid = { left: 52, right: 16, top: showLegend ? 32 : 14, bottom: 46, containLabel: true }
    const categoryAxis: Record<string, any> = {
      type: 'category',
      data: labels,
      name: isHorizontal
        ? (widgetUi.yAxisLabel || inferredCategoryAxisName)
        : (widgetUi.xAxisLabel || inferredCategoryAxisName),
      nameTextStyle: { color: axisNameColor, fontSize: 11, padding: [12, 0, 0, 0] },
      axisLine: { show: true, lineStyle: { color: '#cbd5e1' } },
      axisTick: { show: false },
      axisLabel: {
        color: axisTickColor, fontSize: 11,
        rotate: 0,
        formatter: (v: string) => truncateAxisLabel(v, labels.length > 18 ? 7 : labels.length > 12 ? 9 : 12),
        overflow: 'truncate',
        ellipsis: '...',
        width: labels.length > 18 ? 54 : labels.length > 12 ? 64 : 88,
        lineHeight: 12,
        margin: 10,
        hideOverlap: true,
        interval: labels.length > 14 ? 'auto' : 0
      }
    }
    const valueAxis: Record<string, any> = {
      type: 'value',
      name: isHorizontal
        ? (widgetUi.xAxisLabel || inferredValueAxisName)
        : (widgetUi.yAxisLabel || inferredValueAxisName),
      nameTextStyle: { color: axisNameColor, fontSize: 11, padding: [0, 0, 8, 0] },
      axisLine: { show: true, lineStyle: { color: '#cbd5e1' } },
      axisTick: { show: false },
      splitLine: { show: widgetUi.showGrid !== false, lineStyle: { color: splitLineColor, type: 'dashed' } },
      axisLabel: {
        color: axisTickColor, fontSize: 11,
        formatter: (v: number) => v >= 1e6 ? (v / 1e6).toFixed(1) + 'M'
          : v >= 1000 ? (v / 1000).toFixed(1) + 'k' : String(v)
      }
    }

    if (widgetUi.chartVariant === 'compact') {
      base.grid = { left: 44, right: 10, top: showLegend ? 26 : 10, bottom: 42, containLabel: true }
    } else if (widgetUi.chartVariant === 'executive') {
      valueAxis.splitLine = { show: true, lineStyle: { color: '#cbd5e1', type: 'solid' } }
    } else if (widgetUi.chartVariant === 'contrast') {
      categoryAxis.axisLabel.color = '#475569'
      valueAxis.axisLabel.color = '#475569'
      valueAxis.splitLine = { show: true, lineStyle: { color: '#94a3b8', type: 'solid' } }
    }

    base.xAxis = isHorizontal ? valueAxis : categoryAxis
    base.yAxis = isHorizontal ? categoryAxis : valueAxis

    // DataZoom for non-pie
    if (labels.length > 12) {
      base.dataZoom = [{ type: 'inside', start: 0, end: 100 }]
    }

    const echartsType = chartType === 'area' ? 'line' : (chartType === 'scatter' ? 'scatter' : chartType === 'bubble' ? 'scatter' : chartType === 'line' ? 'line' : chartType === 'histogram' ? 'bar' : 'bar')
    const isArea = chartType === 'area'
    const isBubble = chartType === 'bubble'
    const isCombo = chartType === 'combo'

    // Handle combo chart (bar + line mix)
    if (isCombo) {
      if (rawSeries.length > 0 && typeof rawSeries[0] === 'object' && rawSeries[0]?.data) {
        base.series = rawSeries.map((s: any, si: number) => ({
          name: s.name || `Series ${si + 1}`,
          type: si === 0 ? 'bar' : 'line',
          data: s.data,
          smooth: si > 0 ? widgetUi.smoothLines !== false : undefined,
          lineStyle: si > 0 ? { width: 2.5 } : undefined,
          barMaxWidth: computedBarWidth,
          itemStyle: si === 0 ? { borderRadius: [4, 4, 0, 0] } : undefined,
          label: { show: widgetUi.dataLabels === true, position: 'top', fontSize: 10, color: '#64748b' },
          emphasis: { focus: 'series' }
        }))
      } else {
        base.series = [{
          type: 'bar',
          data: rawSeries,
          barMaxWidth: computedBarWidth,
          label: { show: widgetUi.dataLabels === true, position: 'top', fontSize: 10, color: '#64748b' },
          itemStyle: { borderRadius: [4, 4, 0, 0] }
        }]
      }
    } else if (rawSeries.length > 0 && typeof rawSeries[0] === 'object' && rawSeries[0]?.data) {
      base.series = rawSeries.map((s: any, si: number) => ({
        name: s.name || `Series ${si + 1}`,
        type: echartsType,
        data: s.data,
        smooth: echartsType === 'line' ? widgetUi.smoothLines !== false : undefined,
        areaStyle: isArea ? { opacity: 0.2 } : undefined,
        barMaxWidth: computedBarWidth,
        barGap: '30%',
        itemStyle: {
          borderRadius: echartsType === 'bar' ? (isHorizontal ? [0, 4, 4, 0] : [4, 4, 0, 0]) : undefined
        },
        label: { show: widgetUi.dataLabels === true, position: 'top', fontSize: 10, color: '#64748b' },
        lineStyle: echartsType === 'line' ? { width: 2.5 } : undefined,
        symbolSize: isBubble ? 12 : (echartsType === 'scatter' ? 8 : (echartsType === 'line' ? 4 : undefined)),
        showSymbol: echartsType === 'line' ? labels.length <= 15 : undefined,
        emphasis: { focus: 'series' }
      }))
    } else {
      // Flat number array
      base.series = [{
        type: echartsType,
        data: rawSeries,
        smooth: echartsType === 'line' ? widgetUi.smoothLines !== false : undefined,
        areaStyle: isArea ? { opacity: 0.2 } : undefined,
        barMaxWidth: computedBarWidth,
        barGap: '30%',
        itemStyle: {
          borderRadius: echartsType === 'bar' ? (isHorizontal ? [0, 4, 4, 0] : [4, 4, 0, 0]) : undefined
        },
        label: { show: widgetUi.dataLabels === true, position: 'top', fontSize: 10, color: '#64748b' },
        lineStyle: echartsType === 'line' ? { width: 2.5 } : undefined,
        symbolSize: isBubble ? 12 : (echartsType === 'scatter' ? 8 : (echartsType === 'line' ? 4 : undefined)),
        showSymbol: echartsType === 'line' ? labels.length <= 15 : undefined,
        emphasis: { focus: 'series' }
      }]
    }
  }

  return base
}

// ── API (uses excelApi.ts exclusively) ─────────────────────────
async function loadFileInfo() {
  try { fileInfo.value = await excelFileAPI.getFileInfo(resolvedFileId.value) }
  catch (e: any) {
    console.warn('[Dashboard] FileInfo failed:', e.message)
    if (e.response?.status === 401) {
      router.push('/login')
    } else if (e.response?.status === 404 || e.response?.status === 500) {
      toast.error('File not found. It may have been deleted. Redirecting to files…')
      setTimeout(() => router.push('/app'), 2000)
    }
  }
}

async function loadDashboard(regenerate = false) {
  if (!resolvedFileId.value || isLoading.value) return
  initDashboardSession()
  isLoading.value = true
  const mode = route.query.mode ? String(route.query.mode) : undefined
  try {
    let res: DashboardResponse
    // Force project/board dashboard to reload via per-file generation
    if (isDashboardProject.value && (activeProjectId.value || isBoardMode.value) && !regenerate) {
      // Just load whatever the API gives for this file
      res = await excelFileAPI.generateDashboard(resolvedFileId.value, false, dashboardSessionId.value, mode, dashboardSourceType.value)
    } else if (regenerate && userRequirements.value.trim()) {
      res = await excelFileAPI.generateDashboardWithRequirements(resolvedFileId.value, userRequirements.value.trim(), dashboardSessionId.value, mode, dashboardSourceType.value)
    } else {
      res = await excelFileAPI.generateDashboard(resolvedFileId.value, regenerate, dashboardSessionId.value, mode, dashboardSourceType.value)
    }
    captureTrace(res)
    const incomingWidgets = cloneWidgetList((res.widgets || []) as DashboardWidget[])
    if (isFileScreensMode.value) {
      hydrateFileDashboardStudio((res as any).studio, incomingWidgets)
    } else {
      widgets.value = incomingWidgets
    }
    originalWidgets.value = JSON.parse(JSON.stringify(widgets.value || []))
    dashboardData.value = res
    fingerprint.value = res.fingerprint || null
    originalFingerprint.value = res.fingerprint ? JSON.parse(JSON.stringify(res.fingerprint)) : null
    slicerValues.value = {}  // Reset slicers on load
    dashboardCacheHit.value = res.cache_hit ?? null
    dashboardLoadedAt.value = new Date().toLocaleDateString('en-US', {
      month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
    })

    const saved = (!regenerate && !isFileScreensMode.value) ? store.loadDashboardLayout(resolvedFileId.value) : null
    let layoutApplied = false
    if (saved) {
      // Check that at least some widget IDs actually match the saved layout
      const matchCount = widgets.value.filter(w => saved[w.id]).length
      if (matchCount > 0) {
        widgets.value.forEach(w => {
          const p = saved[w.id]
          if (p) { (w as any).gridX = p.x; (w as any).gridY = p.y; w.gridW = p.w; w.gridH = p.h }
        })
        layoutApplied = true
      }
    }
    if (!layoutApplied) {
      // No saved layout, regenerating, or stale layout — auto-position using bin-packing
      widgets.value.forEach(w => { delete (w as any).gridX; delete (w as any).gridY })
      autoPositionWidgets()
      // Persist the auto-positioned layout so it's available on next visit
      if (!isFileScreensMode.value) {
        store.saveDashboardLayout(resolvedFileId.value, widgets.value)
      }
    }
    isDashboardLocked.value = store.getDashboardLockState(resolvedFileId.value)
    activeTheme.value = store.getDashboardTheme(resolvedFileId.value)

    if (widgets.value.length > 0) { await nextTick(); initGrid() }

    // In board mode, generation is screen-scoped.
    // Update only the active screen for the active file; keep other screens unchanged
    // until user explicitly regenerates those screens.
    if (isBoardMode.value) {
      syncActiveScreenWidgetsToCurrentFile(resolvedFileId.value)
      await persistDashboardWidgets()
    } else if (isFileScreensMode.value) {
      syncActiveScreenWidgetsToCurrentFile(resolvedFileId.value)
    }

    toast.success(`${regenerate ? 'Regenerated' : 'Loaded'} ${widgets.value.length} widgets`)
  } catch (e: any) {
    console.error('[Dashboard] Load failed:', e)
      if (e.response?.status === 404 || e.response?.status === 500) {
        // Only if it's the generate endpoint that failed
        if (e.response?.config?.url?.includes('/api/dashboard/')) {
          toast.error('Dashboard could not be loaded — file may no longer exist.')
        } else {
          toast.error(e.response?.data?.detail || 'Failed to load dashboard')
        }
      } else {
        toast.error(e.response?.data?.detail || 'Failed to load dashboard')
      }
  } finally { isLoading.value = false }
}

// ── GRIDSTACK ──────────────────────────────────────────────────
function initGrid() {
  if (!widgets.value.length) return
  if (!gridContainer.value) { setTimeout(() => gridContainer.value && initGrid(), 100); return }

  gridReady.value = false  // hide charts until grid cell sizes are set
  try { grid?.destroy(false) } catch { /* safe */ }
  grid = null

  grid = GridStack.init({
    column: window.innerWidth < 768 ? 1 : 12,
    cellHeight: 80,
    minRow: 1,
    margin: 16,
    animate: true,
    float: false,
    staticGrid: isDashboardLocked.value,
    draggable: { handle: '.widget-drag-handle' },
    resizable: { handles: 'e, se, s' }
  }, gridContainer.value)
  if (!grid) return

  // Wait one animation frame after GridStack init so cells have dimensions
  nextTick(() => window.requestAnimationFrame(() => {
    gridReady.value = true
  }))

  grid.on('change', (_e, items) => {
    // In unified mode: don't update widget positions — unified items share IDs with
    // primary widgets and would corrupt the primary layout when switching back to split.
    if (isCompareMode.value && compareViewMode.value === 'unified') return

    items?.forEach((item: any) => {
      const w = widgets.value.find(w => w.id === String(item.id))
      if (w) { (w as any).gridX = item.x; (w as any).gridY = item.y; w.gridW = item.w; w.gridH = item.h }
    })
    if (persistTimer) clearTimeout(persistTimer)
    persistTimer = setTimeout(() => store.saveDashboardLayout(resolvedFileId.value, widgets.value), 300)

    // Auto-save layout to project/board dashboard
    if (isDashboardProject.value && (activeProjectId.value || isBoardMode.value)) {
      if (backendPersistTimer) clearTimeout(backendPersistTimer)
      backendPersistTimer = setTimeout(async () => {
        try {
          if (isBoardMode.value) {
            await excelFileAPI.saveBoardDashboard(activeBoardId.value, getBoardSavePayload())
          } else {
            await excelFileAPI.saveProjectDashboard(activeProjectId.value, widgets.value)
          }
        } catch (err) {
          console.warn('[Dashboard] Auto-save layout failed:', err)
        }
      }, 1500)
    }

    // Mirror primary layout changes to compare side by widget ID (split mode only — data only, no grid reinit)
    if (isCompareMode.value && compareViewMode.value === 'split' && compareWidgets.value.length) {
      items?.forEach((item: any) => {
        const cw = compareWidgets.value.find(w => w.id === String(item.id))
        if (cw) {
          ;(cw as any).gridX = item.x
          ;(cw as any).gridY = item.y
          cw.gridW = item.w
          cw.gridH = item.h
        }
      })
    }
  })
}

// ── WIDGET CRUD ────────────────────────────────────────────────
async function persistDashboardWidgets(): Promise<void> {
  if (isBoardMode.value && activeBoardId.value) {
    await excelFileAPI.saveBoardDashboard(activeBoardId.value, getBoardSavePayload())
    return
  }
  if (activeProjectId.value && isDashboardProject.value) {
    await excelFileAPI.saveProjectDashboard(activeProjectId.value, widgets.value)
    return
  }
  if (isFileScreensMode.value) {
    snapshotActiveScreenWidgets()
    await (excelFileAPI as any).updateDashboardWidgets(
      resolvedFileId.value,
      widgets.value,
      dashboardSessionId.value,
      buildFileDashboardStudioState(resolvedFileId.value),
    )
    return
  }
  await excelFileAPI.updateDashboardWidgets(resolvedFileId.value, widgets.value, dashboardSessionId.value)
}

// Merge a base + compare widget pair into a single unified widget (client-side)
function mergeWidgetPair(base: any, compare: any, baseLabel: string, compareLabel: string): any {
  const wtype = base.type || ''

  if (wtype === 'kpi') {
    const bv = base.value ?? 'N/A'
    const cv = compare?.value ?? 'N/A'
    // Try to compute delta from raw numeric values
    const bNum = typeof bv === 'number' ? bv : parseFloat(String(bv).replace(/[^0-9.\-]/g, ''))
    const cNum = typeof cv === 'number' ? cv : parseFloat(String(cv).replace(/[^0-9.\-]/g, ''))
    let delta: number | null = null
    if (!isNaN(bNum) && !isNaN(cNum) && cNum !== 0) {
      delta = Math.round(((bNum - cNum) / Math.abs(cNum)) * 1000) / 10
    }
    return {
      ...base,
      compare_value: cv,
      delta_percentage: delta,
      subtitle: `${baseLabel} vs ${compareLabel}`,
      trend: delta !== null ? (delta > 0 ? 'positive' : delta < 0 ? 'negative' : 'neutral') : 'neutral',
      base_label: baseLabel, compare_label: compareLabel,
      gridW: Math.max(base.gridW || 3, 4),
    }
  }

  if (wtype === 'list') {
    const baseItems: any[] = base.items || []
    const cmpItems: any[] = compare?.items || []
    const cmpMap = new Map(cmpItems.map((it: any) => [it.label || it.name, it.value]))
    const mergedItems = baseItems.map((it: any) => ({
      ...it,
      compare_value: cmpMap.get(it.label || it.name) ?? '—',
    }))
    return {
      ...base,
      items: mergedItems,
      base_label: baseLabel, compare_label: compareLabel,
      gridW: Math.max(base.gridW || 3, 4),
    }
  }

  if (wtype === 'chart') {
    const baseLabels: string[] = base.chartData?.labels || []
    const baseSeries: any[] = base.chartData?.series || []
    const cmpSeries: any[] = compare?.chartData?.series || []

    // Normalize series (could be flat numbers)
    const normBase = baseSeries.length && typeof baseSeries[0] === 'object' && baseSeries[0]?.data
      ? baseSeries : [{ name: base.title || 'Value', data: baseSeries }]
    const normCmp = cmpSeries.length && typeof cmpSeries[0] === 'object' && cmpSeries[0]?.data
      ? cmpSeries : [{ name: compare?.title || 'Value', data: cmpSeries }]

    const dedup = (s: string) => s.split(' ').reduce((a: string[], w: string) => {
      if (!a.length || w.toLowerCase() !== a[a.length - 1].toLowerCase()) a.push(w); return a
    }, []).join(' ')

    const merged = [
      ...normBase.map((s: any) => ({ name: `${baseLabel}: ${dedup(s.name || 'Value')}`, data: s.data || [], source: 'base' })),
      ...normCmp.map((s: any) => ({ name: `${compareLabel}: ${dedup(s.name || 'Value')}`, data: s.data || [], source: 'compare' })),
    ]

    let chartType = base.chartType || 'bar'
    const isPieMerge = chartType === 'pie' || chartType === 'donut' || chartType === 'doughnut'

    if (isPieMerge) {
      // Keep as donut; store both datasets for dual-ring rendering
      return {
        ...base,
        chartType: 'donut',
        chartData: base.chartData,   // primary (base) data kept on chartData for filter compat
        base_chartData: base.chartData,
        cmp_chartData: compare?.chartData,
        is_comparison: true,
        base_label: baseLabel, compare_label: compareLabel,
        gridW: Math.max(base.gridW || 3, 6), gridH: Math.max(base.gridH || 2, 3),
      }
    }

    if (chartType === 'pie' && cmpSeries.length) chartType = 'bar'

    return {
      ...base,
      chartType,
      chartData: { labels: baseLabels, series: merged },
      is_comparison: true,
      base_label: baseLabel, compare_label: compareLabel,
      gridW: Math.max(base.gridW || 3, 6), gridH: Math.max(base.gridH || 2, 3),
    }
  }

  if (wtype === 'insight') {
    return {
      ...base,
      is_comparison: true,
      base_label: baseLabel, compare_label: compareLabel,
    }
  }

  // Default pass-through
  return { ...base, base_label: baseLabel, compare_label: compareLabel }
}

async function addCustomWidget() {
  if (!guardTemplateMutation()) return
  const q = newWidgetQuery.value.trim()
  if (!q) return
  isAddingWidget.value = true
  const mode = route.query.mode ? String(route.query.mode) : undefined
  try {
    // In compare mode, use dual execution to add widget to both sides
    const cmpId = isCompareMode.value && compareFileId.value ? compareFileId.value : undefined
    const res = await excelFileAPI.generateWidget(resolvedFileId.value, q, cmpId, dashboardSessionId.value, undefined, mode, dashboardSourceType.value)
    captureTrace(res)

    if (res.status === 'success') {
      const isDual = 'dual' in res && (res as DualWidgetResponse).dual
      const baseWidget = isDual ? (res as DualWidgetResponse).base_widget : (res as any).widget
      const compareWidget = isDual ? (res as DualWidgetResponse).compare_widget : null

      if (baseWidget) {
        delete (baseWidget as any).gridX
        delete (baseWidget as any).gridY

        // Always add to base widgets array (persistent source)
        widgets.value.push(baseWidget)
        widgets.value.forEach(w => { delete (w as any).gridX; delete (w as any).gridY })
        autoPositionWidgets()

        // ── Unified mode: merge and push to unifiedWidgets ──
        if (isCompareMode.value && compareViewMode.value === 'unified' && compareWidget) {
          const baseLabel = (fileInfo.value?.filename || 'File A').replace(/\.[^.]+$/, '')
          const cmpLabel = (compareFileInfo.value?.filename || 'File B').replace(/\.[^.]+$/, '')
          const merged = mergeWidgetPair(baseWidget, compareWidget, baseLabel, cmpLabel)
          delete (merged as any).gridX
          delete (merged as any).gridY
          unifiedWidgets.value.push(merged)
          // Also keep compare widget stored for switch-back
          if (compareWidget) compareWidgets.value.push(compareWidget)
        }
        // ── Split mode: add compare widget to B-side ──
        else if (compareWidget && isCompareMode.value) {
          const pw = widgets.value.find(w => w.id === baseWidget.id)
          if (pw) {
            ;(compareWidget as any).gridX = (pw as any).gridX ?? 0
            ;(compareWidget as any).gridY = (pw as any).gridY ?? 0
            compareWidget.gridW = pw.gridW
            compareWidget.gridH = pw.gridH
          }
          compareWidgets.value.push(compareWidget)
        }

        newWidgetQuery.value = ''
        showAddPopover.value = false
        try { grid?.destroy(false) } catch {}
        grid = null; await nextTick(); initGrid()

        // Re-init compare grid too (split mode only)
        if (compareWidget && isCompareMode.value && compareViewMode.value === 'split') {
          try { gridB?.destroy(false) } catch {}
          gridB = null; await nextTick(); initGridB()
        }

        await persistDashboardWidgets()
        store.saveDashboardLayout(resolvedFileId.value, widgets.value)
        toast.success(isDual ? 'Widget added to both dashboards' : 'Widget added')
      }
    }
  } catch (e: any) { console.error('[Dashboard] Widget failed:', e); toast.error('Failed to create widget') }
  finally {
    isAddingWidget.value = false
  }
}

async function removeWidget(id: string) {
  if (!guardTemplateMutation()) return
  if (activeWidgetId.value === id) clearWidgetSelection()
  const idx = widgets.value.findIndex(w => w.id === id)
  if (idx < 0) return
  widgets.value.splice(idx, 1)
  store.saveDashboardLayout(resolvedFileId.value, widgets.value)
  try { grid?.destroy(false) } catch {}
  grid = null
  if (widgets.value.length) {
    await nextTick()
    initGrid()
  }

  // Mirror removal on compare side
  if (isCompareMode.value) {
    const cIdx = compareWidgets.value.findIndex(w => w.id === id)
    if (cIdx >= 0) {
      compareWidgets.value.splice(cIdx, 1)
      if (compareViewMode.value === 'split') {
        try { gridB?.destroy(false) } catch {}
        gridB = null
        if (compareWidgets.value.length) { await nextTick(); initGridB() }
      }
    }
    // Also remove from unified widgets
    if (compareViewMode.value === 'unified') {
      const uIdx = unifiedWidgets.value.findIndex(w => w.id === id)
      if (uIdx >= 0) {
        unifiedWidgets.value.splice(uIdx, 1)
        try { (grid as GridStack | null)?.destroy(false) } catch {}
        grid = null
        if (unifiedWidgets.value.length) { await nextTick(); initGrid() }
      }
    }
  }

  try { await persistDashboardWidgets(); toast.success('Removed') }
  catch { toast.error('Failed to save') }
}

function setWidgetColor(widgetId: string, color: string) {
  const w = widgets.value.find(w => w.id === widgetId) as any
  if (!w) return
  w.chartColor = color
  store.saveDashboardLayout(resolvedFileId.value, widgets.value)
  persistDashboardWidgets().catch(() => {})
}

function clearWidgetColor(widgetId: string) {
  const w = widgets.value.find(w => w.id === widgetId) as any
  if (!w || !w.chartColor) return
  delete w.chartColor
  store.saveDashboardLayout(resolvedFileId.value, widgets.value)
  persistDashboardWidgets().catch(() => {})
}

const hasWidgetColorOverrides = computed(() =>
  widgets.value.some(w => {
    const c = (w as any).chartColor
    return typeof c === 'string' && c.trim().length > 0
  })
)

function clearAllWidgetColors() {
  if (!hasWidgetColorOverrides.value) return
  let changed = false
  for (const w of widgets.value as any[]) {
    if (w.chartColor) {
      delete w.chartColor
      changed = true
    }
  }
  if (!changed) return
  store.saveDashboardLayout(resolvedFileId.value, widgets.value)
  persistDashboardWidgets().catch(() => {})
  toast.success('Cleared widget colors')
}

function promptWidget(placeholder: string) {
  newWidgetQuery.value = ''
  showAddPopover.value = true
  // Use placeholder as hint — user types their own query
  nextTick(() => {
    const ta = addPopoverRef.value?.querySelector('textarea')
    if (ta) { ta.placeholder = placeholder; ta.focus() }
  })
}

function toggleLock() {
  isDashboardLocked.value = !isDashboardLocked.value
  if (grid && gridContainer.value) initGrid()
  if (isCompareMode.value && gridB && gridContainerB.value) initGridB()
  toast.success(isDashboardLocked.value ? 'Locked' : 'Unlocked')
}

function clearCrossFilter() {
  crossFilter.value = null
  slicerValues.value = {}
  // Restore original fingerprint so slicers are stable
  if (originalFingerprint.value) {
    fingerprint.value = JSON.parse(JSON.stringify(originalFingerprint.value))
  }
  // Restore original unfiltered widgets WITH their saved positions
  if (originalWidgets.value.length) {
    widgets.value = JSON.parse(JSON.stringify(originalWidgets.value))
    // Re-apply saved layout positions so alignment is preserved
    const saved = store.loadDashboardLayout(resolvedFileId.value)
    if (saved) {
      widgets.value.forEach(w => {
        const p = saved[w.id]
        if (p) { (w as any).gridX = p.x; (w as any).gridY = p.y; w.gridW = p.w; w.gridH = p.h }
      })
    } else {
      autoPositionWidgets()
    }
    nextTick(() => {
      try { grid?.destroy(false) } catch {}
      grid = null
      initGrid()
    })
  }
  // Restore original compare widgets
  if (isCompareMode.value && originalCompareWidgets.value.length) {
    compareWidgets.value = JSON.parse(JSON.stringify(originalCompareWidgets.value))
    // Re-sync positions from primary side
    const primaryMap = new Map(widgets.value.map(w => [w.id, w]))
    compareWidgets.value.forEach(cw => {
      const pw = primaryMap.get(cw.id)
      if (pw) {
        ;(cw as any).gridX = (pw as any).gridX ?? 0
        ;(cw as any).gridY = (pw as any).gridY ?? 0
        cw.gridW = pw.gridW
        cw.gridH = pw.gridH
      }
    })
    nextTick(() => {
      try { gridB?.destroy(false) } catch {}
      gridB = null
      initGridB()
    })
  }
  toast.info('Filter cleared')
}

// ── CROSS-FILTERING: Apply filter via backend API ──────────────
let filterDebounce: ReturnType<typeof setTimeout> | null = null

async function applyFilter(column: string, value: string) {
  if ((!resolvedFileId.value && !isSharedMode.value) || isFiltering.value) return
  isFiltering.value = true
  const mode = route.query.mode ? String(route.query.mode) : undefined
  try {
    const res = isSharedMode.value
      ? await excelFileAPI.filterSharedDashboard(shareToken.value, column, value, dashboardSessionId.value)
      : await excelFileAPI.filterDashboard(resolvedFileId.value, column, value, dashboardSessionId.value, mode, dashboardSourceType.value)
    captureTrace(res)
    widgets.value = res.widgets || []
    // Backend now returns original dims in filtered response — update fingerprint
    fingerprint.value = res.fingerprint || null
    // Also update originalFingerprint if it was somehow null (safety net)
    if (!originalFingerprint.value && res.fingerprint) {
      originalFingerprint.value = JSON.parse(JSON.stringify(res.fingerprint))
    }
    // Re-apply saved layout positions so alignment stays consistent
    const saved = store.loadDashboardLayout(resolvedFileId.value)
    if (saved) {
      widgets.value.forEach(w => {
        const p = saved[w.id]
        if (p) { (w as any).gridX = p.x; (w as any).gridY = p.y; w.gridW = p.w; w.gridH = p.h }
      })
    } else {
      autoPositionWidgets()
    }
    await nextTick()
    try { grid?.destroy(false) } catch {}
    grid = null
    initGrid()

    // Also filter compare dashboard if in compare mode
    if (isCompareMode.value && compareFileId.value) {
      try {
        const cRes = await excelFileAPI.filterDashboard(compareFileId.value, column, value, dashboardSessionId.value, mode, dashboardSourceType.value)
        compareWidgets.value = cRes.widgets || []
        compareFingerprint.value = cRes.fingerprint || null
        // Sync positions from primary
        const primaryMap = new Map(widgets.value.map(w => [w.id, w]))
        compareWidgets.value.forEach(cw => {
          const pw = primaryMap.get(cw.id)
          if (pw) {
            ;(cw as any).gridX = (pw as any).gridX ?? 0
            ;(cw as any).gridY = (pw as any).gridY ?? 0
            cw.gridW = pw.gridW
            cw.gridH = pw.gridH
          }
        })
        await nextTick()
        try { gridB?.destroy(false) } catch {}
        gridB = null
        initGridB()
      } catch (ce: any) {
        console.warn('[Compare] Filter failed on compare file:', ce.message)
        toast.warning('Compare side could not be filtered — column may not exist')
      }
    }
    toast.success(`Filtered by ${column}: ${value} (${(res as any).filtered_rows ?? '?'} rows)`)
  } catch (e: any) {
    console.error('[Dashboard] Filter failed:', e)
    const detail = e?.response?.data?.detail
    const errMsg = Array.isArray(detail)
      ? detail.map((d: any) => d?.msg || String(d)).join('; ')
      : (typeof detail === 'string' ? detail : 'Filter returned no data — try a different value')
    toast.error(errMsg)
    // Revert to unfiltered
    clearCrossFilter()
  } finally {
    isFiltering.value = false
  }
}

function handleChartClick(widget: any, params: any) {
  if (!params?.name) return
  const filterCol = widget.filter_context?.column || ''
  if (!filterCol) return
  const filterVal = String(params.name)
  if (crossFilter.value?.key === filterCol && crossFilter.value?.value === filterVal) {
    clearCrossFilter()
  } else {
    crossFilter.value = { key: filterCol, value: filterVal }
    // Debounce the API call
    if (filterDebounce) clearTimeout(filterDebounce)
    filterDebounce = setTimeout(() => applyFilter(filterCol, filterVal), 200)
  }
}

// ── SLICER CHANGE: Dropdown value changed ─────────────────────
function onSlicerChange(dimCol: string, value: string) {
  if (value === '' || value === '__all__') {
    delete slicerValues.value[dimCol]
    if (!Object.keys(slicerValues.value).length) {
      clearCrossFilter()
    }
  } else {
    slicerValues.value[dimCol] = value
    crossFilter.value = { key: dimCol, value }
    if (filterDebounce) clearTimeout(filterDebounce)
    filterDebounce = setTimeout(() => applyFilter(dimCol, value), 200)
  }
}

// ── DRILL-THROUGH: Send widget context to chatbot ─────────────
function drillThrough(widget: any) {
  const query = widget.origin_query || widget.title || 'Explain this metric'
  const fileId = resolvedFileId.value
  if (fileId) {
    router.push({ path: '/app/chat', query: { fileId, q: `Explain in detail: ${query}` } })
  }
}

// ── EXPORT HELPERS ────────────────────────────────────────────
const isExporting = ref(false)

/**
 * Pre-process the container for html2canvas:
 * 1. Convert every ECharts <canvas> to a high-res <img> (ECharts' own getDataURL)
 * 2. Remove pointer-events: none from locked grid items so html2canvas reads them
 * Returns a cleanup function that restores everything.
 */
function prepareForCapture(container: HTMLElement, options?: { expandTextWidgets?: boolean }): () => void {
  const restorers: (() => void)[] = []
  const shouldExpandTextWidgets = options?.expandTextWidgets !== false

  // ── 1. ECharts canvas → img snapshot ─────────────────────────
  const echartWrappers = container.querySelectorAll('[_echarts_instance_]') as NodeListOf<HTMLElement>
  echartWrappers.forEach(wrapper => {
    // Snapshot the existing <canvas> elements
    const canvases = wrapper.querySelectorAll('canvas')
    canvases.forEach(cvs => {
      try {
        const dataUrl = cvs.toDataURL('image/png')
        const img = document.createElement('img')
        img.src = dataUrl
        img.style.cssText = `position:absolute;top:0;left:0;width:${cvs.offsetWidth}px;height:${cvs.offsetHeight}px;z-index:9999;pointer-events:none;`
        cvs.parentElement?.appendChild(img)
        cvs.style.visibility = 'hidden'
        restorers.push(() => {
          img.remove()
          cvs.style.visibility = ''
        })
      } catch { /* cross-origin canvas — skip */ }
    })
  })

  // Also handle any standalone <canvas> elements (vue-echarts renders them directly)
  const standaloneCanvases = container.querySelectorAll('canvas:not([data-export-processed])') as NodeListOf<HTMLCanvasElement>
  standaloneCanvases.forEach(cvs => {
    if (cvs.style.visibility === 'hidden') return // already handled above
    try {
      const dataUrl = cvs.toDataURL('image/png')
      const img = document.createElement('img')
      img.src = dataUrl
      img.style.cssText = `position:absolute;top:0;left:0;width:${cvs.offsetWidth}px;height:${cvs.offsetHeight}px;z-index:9999;pointer-events:none;`
      cvs.setAttribute('data-export-processed', '1')
      cvs.parentElement!.style.position = cvs.parentElement!.style.position || 'relative'
      cvs.parentElement?.appendChild(img)
      cvs.style.visibility = 'hidden'
      restorers.push(() => {
        img.remove()
        cvs.style.visibility = ''
        cvs.removeAttribute('data-export-processed')
      })
    } catch { /* skip */ }
  })

  // ── 2. Temporarily enable pointer-events on locked grid items ─
  const lockedItems = container.querySelectorAll('.static-grid .grid-stack-item') as NodeListOf<HTMLElement>
  lockedItems.forEach(el => {
    const prev = el.style.pointerEvents
    el.style.pointerEvents = 'auto'
    restorers.push(() => { el.style.pointerEvents = prev })
  })

  // ── 3. Expand overflow:hidden containers so nothing is clipped ─
  const overflowEls = container.querySelectorAll('.overflow-hidden, .overflow-auto, .overflow-y-auto, .grid-stack-item-content') as NodeListOf<HTMLElement>
  overflowEls.forEach(el => {
    const prevOv = el.style.overflow
    const prevOvY = el.style.overflowY
    const prevH = el.style.height
    const prevBottom = el.style.bottom

    el.style.setProperty('overflow', 'visible', 'important')
    el.style.setProperty('overflow-y', 'visible', 'important')
    if (el.classList.contains('grid-stack-item-content')) {
      el.style.setProperty('height', 'auto', 'important')
      el.style.setProperty('bottom', 'auto', 'important')
    }

    restorers.push(() => { 
      el.style.overflow = prevOv
      el.style.overflowY = prevOvY
      el.style.height = prevH
      el.style.bottom = prevBottom
    })
  })

  if (shouldExpandTextWidgets) {
    // ── 4. Expand text-based widgets whose content overflows & push others down ─
    // Collect all grid items with their positions
    const gridItems = Array.from(container.querySelectorAll('.grid-stack-item') as NodeListOf<HTMLElement>)
    interface ItemInfo { el: HTMLElement; top: number; left: number; height: number; width: number; extraPx: number }
    const items: ItemInfo[] = gridItems.map(el => ({
      el,
      top: el.offsetTop,
      left: el.offsetLeft,
      height: el.offsetHeight,
      width: el.offsetWidth,
      extraPx: 0,
    }))

    // First pass: find which items need expansion
    for (const item of items) {
      const card = item.el.querySelector('.widget-card') as HTMLElement | null
      if (!card) continue
      const scrollable = card.querySelector('.overflow-y-auto, .scrollbar-thin') as HTMLElement | null
      if (!scrollable) continue
      const contentH = scrollable.scrollHeight
      const visibleH = scrollable.clientHeight
      if (contentH <= visibleH + 2) continue
      // Add extra buffer (e.g. 32px instead of 12px) to ensure the last lines of text are not cut off
      item.extraPx = contentH - visibleH + 32
    }

    // Second pass: for each expanded item, push down all items whose top edge
    // is below the expanded item's top edge (i.e. they are in rows below)
    // Sort by top position so we process top-to-bottom
    const expandedItems = items.filter(i => i.extraPx > 0).sort((a, b) => a.top - b.top)
    // Track cumulative shift per widget
    const shifts = new Map<HTMLElement, number>()
    for (const item of items) shifts.set(item.el, 0)

    // We should aggregate the maximum extraPx per "row band" to push everything down evenly
    // But a simple approach is: for every item, its shift is the MAX extraPx of all expanded items
    // that are strictly ABOVE it (their original bottom is <= this item's original top).
    // Wait, if an item is slightly offset? Let's say item is below if `item.top >= expanded.top + 20`.
    for (const item of items) {
      let maxShiftFromAbove = 0;
      for (const exp of expandedItems) {
        // If `item` is on a row below `exp`
        if (item.top >= exp.top + 20) {
          maxShiftFromAbove = Math.max(maxShiftFromAbove, exp.extraPx);
        }
      }
      shifts.set(item.el, maxShiftFromAbove);
    }

    // Apply expansions and shifts
    for (const item of items) {
      const prevH = item.el.style.height
      const prevMinH = item.el.style.minHeight
      const prevTop = item.el.style.top

      if (item.extraPx > 0) {
        // Expand this widget
        const newH = item.height + item.extraPx
        item.el.style.height = `${newH}px`
        item.el.style.minHeight = `${newH}px`
        const card = item.el.querySelector('.widget-card') as HTMLElement
        const prevCardH = card.style.height
        const prevCardOv = card.style.overflow
        card.style.height = 'auto'
        card.style.overflow = 'visible'
        restorers.push(() => {
          card.style.height = prevCardH
          card.style.overflow = prevCardOv
        })
      }

      const shift = shifts.get(item.el) || 0
      if (shift > 0) {
        item.el.style.top = `${item.top + shift}px`
      }

      if (item.extraPx > 0 || shift > 0) {
        restorers.push(() => {
          item.el.style.height = prevH
          item.el.style.minHeight = prevMinH
          item.el.style.top = prevTop
        })
      }
    }

    // Also expand the grid-stack container itself to fit the new total height
    const gridStack = container.querySelector('.grid-stack') as HTMLElement | null
    if (gridStack) {
      // Determine the maximum shift added to any item
      let maxTotalShift = 0;
      for (const shift of shifts.values()) {
         maxTotalShift = Math.max(maxTotalShift, shift);
      }
      // Also consider if the very bottom item was expanded itself
      let maxExpandedBottomExt = 0;
      for (const exp of expandedItems) {
         maxExpandedBottomExt = Math.max(maxExpandedBottomExt, exp.extraPx);
      }

      const totalExtra = maxTotalShift + maxExpandedBottomExt;
      if (totalExtra > 0) {
        const prevGsH = gridStack.style.height
        const prevGsMinH = gridStack.style.minHeight
        const gsHeight = gridStack.offsetHeight
        gridStack.style.height = `${gsHeight + totalExtra}px`
        gridStack.style.minHeight = `${gsHeight + totalExtra}px`
        restorers.push(() => {
          gridStack.style.height = prevGsH
          gridStack.style.minHeight = prevGsMinH
        })
      }
    }
  }

  return () => restorers.forEach(fn => fn())
}

async function captureContainer(): Promise<HTMLCanvasElement> {
  const target = exportContainer.value || gridContainer.value
  if (!target) throw new Error('No export container')

  const restore = prepareForCapture(target)

  const captureWidth = Math.max(1, target.scrollWidth)
  const captureHeight = Math.max(1, target.scrollHeight)
  const maxBitmapDimension = 8192
  const deviceScale = Math.min(window.devicePixelRatio || 1, 2)
  const safeScale = Math.min(deviceScale, maxBitmapDimension / captureWidth, maxBitmapDimension / captureHeight)
  const exportScale = Math.max(0.75, safeScale)

  // Temporarily expand the container to its full scroll height so nothing is clipped
  const savedStyles: { el: HTMLElement; height: string; overflow: string; flex: string; position: string }[] = []
  let el: HTMLElement | null = target
  while (el) {
    savedStyles.push({
      el,
      height: el.style.height,
      overflow: el.style.overflow,
      flex: el.style.flex,
      position: el.style.position,
    })
    el.style.height = `${el.scrollHeight}px`
    el.style.overflow = 'visible'
    el.style.flex = 'none'
    el.style.position = 'relative'
    // Stop at body
    if (el.parentElement === document.body || el.parentElement === document.documentElement) break
    el = el.parentElement
  }

  // Small delay to let browser render the img replacements
  await new Promise(r => setTimeout(r, 100))

  try {
    const canvas = await html2canvas(target, {
      backgroundColor: '#f8fafc',
      scale: exportScale,
      useCORS: true,
      logging: false,
      allowTaint: false,
      width: captureWidth,
      height: captureHeight,
      windowWidth: captureWidth,
      windowHeight: captureHeight,
      onclone: (doc: Document) => {
        // In the cloned DOM, force all grid items visible
        doc.querySelectorAll('.grid-stack-item').forEach((el: any) => {
          el.style.pointerEvents = 'auto'
          el.style.opacity = '1'
          el.style.transform = 'none'
        })
        // Ensure animations don't interfere
        doc.querySelectorAll('.grid-stack-item').forEach((el: any) => {
          el.style.animation = 'none'
        })
        // Avoid browser/compositor effects that can produce artifacted exports.
        doc.querySelectorAll('.widget-card').forEach((el: any) => {
          el.style.backdropFilter = 'none'
          el.style.filter = 'none'
        })
      }
    })
    return canvas
  } finally {
    // Restore all expanded containers
    for (const saved of savedStyles) {
      saved.el.style.height = saved.height
      saved.el.style.overflow = saved.overflow
      saved.el.style.flex = saved.flex
      saved.el.style.position = saved.position
    }
    restore()
  }
}

async function exportDashboardPNG() {
  if (isExporting.value) return
  isExporting.value = true
  toast.info('Preparing export…')
  try {
    const canvas = await captureContainer()
    const link = document.createElement('a')
    link.download = `${fileInfo.value?.filename || 'dashboard'}-${new Date().toISOString().slice(0, 10)}.png`
    link.href = canvas.toDataURL('image/png', 1.0)
    link.click()
    toast.success('Dashboard exported as PNG')
  } catch (e) {
    console.error('[Export] PNG failed:', e)
    toast.error('Export failed')
  } finally {
    isExporting.value = false
  }
}

async function exportDashboardPDF() {
  if (isExporting.value) return
  isExporting.value = true
  toast.info('Generating PDF…')
  try {
    const canvas = await captureContainer()
    const pdf = new jsPDF({
      orientation: 'portrait',
      unit: 'mm',
      format: 'a4',
      compress: true,
    })
    
    // Add metadata
    pdf.setProperties({
      title: fileInfo.value?.filename || 'Dashboard Report',
      author: 'ExcelLoom',
      subject: `Dashboard Export - ${new Date().toLocaleDateString()}`,
      keywords: 'dashboard, export'
    })
    
    const pdfWidth = pdf.internal.pageSize.getWidth()
    const pdfHeight = pdf.internal.pageSize.getHeight()
    const marginX = 10
    const contentTop = 40
    const contentWidthMm = pdfWidth - (marginX * 2)
    const contentHeightMm = pdfHeight - contentTop - 10
    const pxPerMm = canvas.width / contentWidthMm
    const pageSliceHeightPx = Math.max(1, Math.floor(contentHeightMm * pxPerMm))
    
    // Add header
    pdf.setFontSize(14)
    pdf.text(fileInfo.value?.filename || 'Dashboard Report', pdfWidth / 2, 20, { align: 'center' })
    pdf.setFontSize(10)
    pdf.setTextColor(148, 163, 184) // Gray color
    const exportDate = new Date().toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' })
    pdf.text(`Generated on ${exportDate} • ${widgets.value.length} widgets`, pdfWidth / 2, 30, { align: 'center' })
    
    // Add the dashboard image in slices (multi-page safe export).
    let renderedHeightPx = 0
    while (renderedHeightPx < canvas.height) {
      const sliceHeightPx = Math.min(pageSliceHeightPx, canvas.height - renderedHeightPx)
      const pageCanvas = document.createElement('canvas')
      pageCanvas.width = canvas.width
      pageCanvas.height = sliceHeightPx
      const ctx = pageCanvas.getContext('2d')
      if (!ctx) throw new Error('Failed to create PDF page canvas')
      ctx.fillStyle = '#f8fafc'
      ctx.fillRect(0, 0, pageCanvas.width, pageCanvas.height)
      ctx.drawImage(
        canvas,
        0,
        renderedHeightPx,
        canvas.width,
        sliceHeightPx,
        0,
        0,
        pageCanvas.width,
        pageCanvas.height,
      )

      const sliceData = pageCanvas.toDataURL('image/jpeg', 0.92)
      const drawHeightMm = sliceHeightPx / pxPerMm
      pdf.addImage(sliceData, 'JPEG', marginX, contentTop, contentWidthMm, drawHeightMm, undefined, 'FAST')

      renderedHeightPx += sliceHeightPx
      if (renderedHeightPx < canvas.height) {
        pdf.addPage()
      }
    }
    
    // Download the PDF
    const filename = `${fileInfo.value?.filename || 'dashboard'}-${new Date().toISOString().slice(0, 10)}.pdf`
    pdf.save(filename)
    
    toast.success('Dashboard exported as PDF')
  } catch (e) {
    console.error('[Export] PDF failed:', e)
    toast.error('PDF export failed')
  } finally {
    isExporting.value = false
  }
}

function executeCommand(cmd: { action: () => void }) {
  showCommandPalette.value = false; commandQuery.value = ''; cmd.action()
}

// ── COMPARE MODE LOGIC ────────────────────────────────────────
async function loadCompareFiles() {
  try {
    const allFiles = await excelFileAPI.listFiles()
    // Normalize: treat null, undefined, empty string all as null
    const norm = (v: any) => (v == null || v === '' || v === 'null') ? null : String(v)
    // Get current file's directory — prefer fileInfo, fallback to finding self in the list
    let curProject = norm(fileInfo.value?.project_id)
    let curSubproject = norm(fileInfo.value?.subproject_id)
    if (curProject == null && curSubproject == null) {
      const self = allFiles.find(f => f.file_uuid === resolvedFileId.value)
      if (self) {
        curProject = norm(self.project_id)
        curSubproject = norm(self.subproject_id)
      }
    }
    availableCompareFiles.value = allFiles.filter(f => {
      if (f.file_uuid === resolvedFileId.value) return false
      return norm(f.project_id) === curProject && norm(f.subproject_id) === curSubproject
    })
  } catch (e) {
    console.error('[Compare] Failed to load files:', e)
    availableCompareFiles.value = []
  }
}

async function openCompareSelector() {
  if (!fileInfo.value) await loadFileInfo()
  await loadCompareFiles()
  showExportMenu.value = false
  showThemePicker.value = false
  updateCompareMenuPosition()
  showCompareSelector.value = true
}

function updateCompareMenuPosition() {
  const trigger = compareTriggerRef.value
  if (!trigger) return
  const rect = trigger.getBoundingClientRect()
  const menuWidth = 320
  const margin = 8
  compareMenuPosition.value = {
    top: Math.round(rect.bottom + 6),
    left: Math.max(margin, Math.min(window.innerWidth - menuWidth - margin, Math.round(rect.right - menuWidth))),
  }
}

function toggleExportMenu() {
  if (isExporting.value || !widgets.value.length) return
  if (showExportMenu.value) {
    showExportMenu.value = false
    return
  }
  showCompareSelector.value = false
  showThemePicker.value = false
  updateExportMenuPosition()
  showExportMenu.value = true
}

function updateExportMenuPosition() {
  const trigger = exportTriggerRef.value
  if (!trigger) return
  const rect = trigger.getBoundingClientRect()
  const menuWidth = 160
  const margin = 8
  exportMenuPosition.value = {
    top: Math.round(rect.bottom + 6),
    left: Math.max(margin, Math.min(window.innerWidth - menuWidth - margin, Math.round(rect.right - menuWidth))),
  }
}

async function runExportAction(kind: 'png' | 'pdf') {
  showExportMenu.value = false
  if (kind === 'png') {
    await exportDashboardPNG()
    return
  }
  await exportDashboardPDF()
}

async function selectCompareFile(file: FileInfo) {
  showCompareSelector.value = false
  compareFileId.value = file.file_uuid
  compareFileInfo.value = file
  isCompareMode.value = true
  isCompareLoading.value = true
  compareLoadError.value = null

  // Snapshot the current primary widgets so we can restore them on exit
  primaryWidgetsSnapshot.value = JSON.parse(JSON.stringify(widgets.value))
  // Clear the unified cache — new compare pair needs a fresh API call
  unifiedWidgetsCache.value = []

  try {
    // Clone base widgets onto the target file for symmetric comparison
    const res = await excelFileAPI.cloneWidgets(resolvedFileId.value, file.file_uuid, dashboardSessionId.value)
    captureTrace(res)
    compareWidgets.value = res.widgets || []
    originalCompareWidgets.value = JSON.parse(JSON.stringify(res.widgets || []))
    compareFingerprint.value = res.fingerprint || null

    // Copy positions from primary widgets so layouts match exactly
    const primaryMap = new Map(widgets.value.map(w => [w.id, w]))
    compareWidgets.value.forEach(cw => {
      const pw = primaryMap.get(cw.id)
      if (pw) {
        ;(cw as any).gridX = (pw as any).gridX ?? 0
        ;(cw as any).gridY = (pw as any).gridY ?? 0
        cw.gridW = pw.gridW
        cw.gridH = pw.gridH
      }
    })

    isCompareLoading.value = false
    await nextTick()
    try { initGridB() } catch (gridErr) {
      console.warn('[Compare] GridB init error (non-fatal):', gridErr)
    }
    toast.success(`Comparing with ${file.filename}`)
  } catch (e: any) {
    console.error('[Compare] Failed to clone widgets:', e)
    // NEVER auto-exit compare mode — keep the panel open so the user can retry.
    // Exiting compare mode without user consent is confusing UX.
    isCompareLoading.value = false
    compareLoadError.value = e.response?.data?.detail || e.message || 'Failed to load comparison'
    toast.error(compareLoadError.value ?? 'Failed to load comparison')
  }
}

async function retryCompareLoad() {
  if (!compareFileInfo.value) return
  compareLoadError.value = null
  await selectCompareFile(compareFileInfo.value)
}

async function exitCompareMode() {
  // 1. Destroy B-side grid while DOM is still intact (isCompareMode still true)
  try { gridB?.destroy(false) } catch { /* safe */ }
  gridB = null

  // 2. Restore primary widgets from the snapshot taken when compare was activated.
  //    This is critical: unified mode replaces sortedWidgets with merged/comparison
  //    widgets; without this restore the dashboard still shows comparison charts.
  if (primaryWidgetsSnapshot.value.length) {
    widgets.value = JSON.parse(JSON.stringify(primaryWidgetsSnapshot.value))
    // Re-apply saved layout positions so the grid looks the same as before compare
    const savedLayout = store.loadDashboardLayout(resolvedFileId.value)
    if (savedLayout) {
      widgets.value.forEach(w => {
        const pos = savedLayout[w.id]
        if (pos) { ;(w as any).gridX = pos.x; ;(w as any).gridY = pos.y; w.gridW = pos.w; w.gridH = pos.h }
      })
    }
  }

  // 3. Tear down all compare state
  isCompareMode.value = false
  compareFileId.value = null
  compareFileInfo.value = null
  compareWidgets.value = []
  originalCompareWidgets.value = []
  compareFingerprint.value = null
  showCompareSelector.value = false
  compareViewMode.value = 'split'
  unifiedWidgets.value = []
  unifiedWidgetsCache.value = []
  primaryWidgetsSnapshot.value = []
  isUnifiedLoading.value = false
  compareLoadError.value = null

  // Bump epoch so every VChart :key changes → ECharts fully remounts and discards
  // the stale merged series that were rendered in unified comparison mode.
  chartRenderEpoch.value++

  store.setCompareMode(false)

  // 4. Wait for Vue to flush the restored widgets.value into the DOM
  //    (two ticks: first renders the restored widget data, second unmounts old VCharts)
  await nextTick()
  await nextTick()

  // 5. Re-init primary grid at full width
  initGrid()
  toast.info('Compare mode closed')
}

async function switchCompareView(mode: 'split' | 'unified') {
  // Guard: skip if already in this mode or another transition is running
  if (mode === compareViewMode.value || isUnifiedLoading.value || isCompareLoading.value) return

  if (mode === 'unified') {
    if (!compareFileId.value || !resolvedFileId.value) return

    // Use cached response if available (avoids redundant API calls for toggling)
    if (unifiedWidgetsCache.value.length) {
      // Set unified widgets from cache
      unifiedWidgets.value = JSON.parse(JSON.stringify(unifiedWidgetsCache.value))

      // Destroy B-side grid while B-panel still in DOM
      try { gridB?.destroy(false) } catch { /* safe */ }
      gridB = null

      compareViewMode.value = 'unified'
      await nextTick()
      await nextTick()

      autoPositionWidgets()
      await nextTick()
      initGrid()
      toast.success('Switched to Unified View')
      return
    }

    isUnifiedLoading.value = true
    // Stay in split mode during the API call so user sees B-panel with loading state
    try {
      const res = await excelFileAPI.generateUnifiedComparison(resolvedFileId.value, compareFileId.value, dashboardSessionId.value)
      captureTrace(res)
      const fetchedWidgets = res.widgets as DashboardWidget[]

      // Cache for subsequent toggles
      unifiedWidgetsCache.value = JSON.parse(JSON.stringify(fetchedWidgets))
      unifiedWidgets.value = fetchedWidgets

      // 1. Destroy B-side grid WHILE the B-panel is still in the DOM (split mode)
      try { gridB?.destroy(false) } catch { /* safe */ }
      gridB = null

      // 2. Switch view mode → B-panel v-if becomes false, primary panel shows unified items
      compareViewMode.value = 'unified'

      // 3. Wait for Vue to render unified items into the grid container
      await nextTick()
      await nextTick()

      // 4. Auto-position unified items (gridX/gridY unset → without this all stack at x=0)
      autoPositionWidgets()
      await nextTick()

      // 5. Init grid with positioned unified items
      initGrid()
      toast.success('Switched to Unified View')
    } catch (e: any) {
      toast.error('Failed to load unified view: ' + (e?.response?.data?.detail || e.message))
      unifiedWidgets.value = []
    } finally {
      isUnifiedLoading.value = false
    }

  } else {
    // ── Back to split ──
    // 1. Clear unified widgets so sortedWidgets reverts back to primary widgets
    unifiedWidgets.value = []

    // 2. Restore primary widgets from snapshot (ensures charts are NOT unified versions)
    if (primaryWidgetsSnapshot.value.length) {
      widgets.value = JSON.parse(JSON.stringify(primaryWidgetsSnapshot.value))
    }

    // 3. Re-apply saved layout positions
    const savedLayout = store.loadDashboardLayout(resolvedFileId.value)
    if (savedLayout) {
      widgets.value.forEach(w => {
        const pos = savedLayout[w.id]
        if (pos) { ;(w as any).gridX = pos.x; ;(w as any).gridY = pos.y; w.gridW = pos.w; w.gridH = pos.h }
      })
    }

    // 4. Switch to split — B-panel v-if becomes true
    compareViewMode.value = 'split'

    // Bump epoch so VCharts remount cleanly (removes unified merged series)
    chartRenderEpoch.value++

    initGrid()

    // 6. Extra tick for B-panel ref to bind, then init B grid
    await nextTick()
    initGridB()
    toast.success('Switched to Split View')
  }
}

// Initialize the B-side GridStack (interactive, mirrors changes back to primary)
function initGridB() {
  if (!compareWidgets.value.length) return
  if (!gridContainerB.value) { setTimeout(() => gridContainerB.value && initGridB(), 100); return }

  gridBReady.value = false  // hide compare charts until grid cell sizes are set
  try { gridB?.destroy(false) } catch { /* safe */ }
  gridB = null

  gridB = GridStack.init({
    column: window.innerWidth < 768 ? 1 : 12,
    cellHeight: 80,
    minRow: 1,
    margin: 16,
    animate: true,
    float: false,
    draggable: { handle: '.widget-drag-handle' },
    resizable: { handles: 'e, se, s' }
  }, gridContainerB.value)

  // Wait one animation frame after GridStack init so cells have dimensions
  nextTick(() => window.requestAnimationFrame(() => {
    gridBReady.value = true
  }))

  // Mirror compare-side changes back to primary
  if (gridB) {
    gridB.on('change', (_e, items) => {
      items?.forEach((item: any) => {
        const cw = compareWidgets.value.find(w => w.id === String(item.id))
        if (cw) {
          ;(cw as any).gridX = item.x
          ;(cw as any).gridY = item.y
          cw.gridW = item.w
          cw.gridH = item.h
        }
        // Mirror positions to primary side (data-only, no grid re-init to avoid cycles)
        const pw = widgets.value.find(w => w.id === String(item.id))
        if (pw) {
          ;(pw as any).gridX = item.x
          ;(pw as any).gridY = item.y
          pw.gridW = item.w
          pw.gridH = item.h
        }
      })
    })
  }
}

// Handle chart click on compare side — enable cross-filtering
function handleCompareChartClick(widget: any, params: any) {
  if (!params?.name) return
  const filterCol = widget.filter_context?.column || ''
  if (!filterCol) return
  toast.info(`Compare chart clicked: ${filterCol} = ${params.name}`)
}

// ── ADD POPOVER / THEME PICKER OUTSIDE CLICK ──────────────────
function handleOutsideClick(e: MouseEvent) {
  if (showAddPopover.value && addPopoverRef.value && !addPopoverRef.value.contains(e.target as Node)) {
    showAddPopover.value = false
  }
  if (
    showThemePicker.value
    && themePickerRef.value
    && !themePickerRef.value.contains(e.target as Node)
    && (!themeTriggerRef.value || !themeTriggerRef.value.contains(e.target as Node))
  ) {
    showThemePicker.value = false
  }
  if (
    showCompareSelector.value
    && compareSelectorRef.value
    && !compareSelectorRef.value.contains(e.target as Node)
    && (!compareTriggerRef.value || !compareTriggerRef.value.contains(e.target as Node))
  ) {
    showCompareSelector.value = false
  }
  if (
    showExportMenu.value
    && exportMenuRef.value
    && !exportMenuRef.value.contains(e.target as Node)
    && (!exportTriggerRef.value || !exportTriggerRef.value.contains(e.target as Node))
  ) {
    showExportMenu.value = false
  }
  if (openChartFilterId.value) {
    openChartFilterId.value = null
  }
}

// ── KPI HELPERS ────────────────────────────────────────────────
function getTrendIcon(trend: string) {
  if (trend === 'positive') return '↑'
  if (trend === 'negative') return '↓'
  return ''
}

// ── LIFECYCLE ──────────────────────────────────────────────────
function handleKeydown(e: KeyboardEvent) {
  if ((e.ctrlKey || e.metaKey) && e.key === 'k') { e.preventDefault(); showCommandPalette.value = !showCommandPalette.value; commandQuery.value = '' }
  if (e.key === 'Escape' && showCommandPalette.value) showCommandPalette.value = false
  if (e.key === 'Escape' && openChartFilterId.value) openChartFilterId.value = null
  if (e.key === 'Escape' && activeWidgetId.value) clearWidgetSelection()
}

function handleResize() {
  if (widgets.value.length && grid) initGrid()
  if (isCompareMode.value && compareWidgets.value.length && gridB) {
    try { gridB.destroy(false) } catch {}
    gridB = null
    initGridB()
  }
  updateWidgetToolbarPosition()
  if (showThemePicker.value) updateThemeMenuPosition()
  if (showCompareSelector.value) updateCompareMenuPosition()
  if (showExportMenu.value) updateExportMenuPosition()
}

function handleWindowScroll() {
  if (!activeWidgetId.value) return
  updateWidgetToolbarPosition()
}

function toggleSidebar() {
  sidebarOpen.value = !sidebarOpen.value
  nextTick(() => {
    if (grid && gridContainer.value) initGrid()
  })
}

watch(activeWidget, (w) => {
  if (!w) return
  ensureWidgetUiDefaults(w)
})

watch(activeWidget, () => {
  scheduleWidgetConfigPersist()
  // Bump render version to force VChart remount when widget.ui or widget.chartType changes
  if (activeWidgetId.value) {
    widgetRenderVersions.value[activeWidgetId.value] = (widgetRenderVersions.value[activeWidgetId.value] || 0) + 1
  }
}, { deep: true })

watch(widgets, () => {
  if (!activeWidgetId.value) return
  const exists = widgets.value.some(w => w.id === activeWidgetId.value)
  if (!exists) clearWidgetSelection()
  else nextTick(() => updateWidgetToolbarPosition())
}, { deep: true })

watch(widgets, () => {
}, { deep: true })

watch(activeScreenId, () => {
  if (!isBoardMode.value) return
})

watch(canMutateWidgets, (canMutate) => {
  if (canMutate) return
  showAddPopover.value = false
  chartBuilderOpen.value = false
})

watch(activeTheme, () => {
})

watch(boardDesign, () => {
}, { deep: true })

// ── RELOAD WHEN SIDEBAR NAVIGATES TO A DIFFERENT FILE ─────────
watch(resolvedFileId, async (newId, oldId) => {
  if (skipNextFileIdWatch) { skipNextFileIdWatch = false; return }
  if (!newId || newId === oldId) return
  // Tear down existing grids
  try { grid?.destroy(false) } catch {}
  grid = null
  try { gridB?.destroy(false) } catch {}
  gridB = null
  gridReady.value = false
  // Reset all state
  widgets.value = []
  originalWidgets.value = []
  dashboardData.value = null
  fileInfo.value = null
  fingerprint.value = null
  originalFingerprint.value = null
  slicerValues.value = {}
  crossFilter.value = null
  isCompareMode.value = false
  compareWidgets.value = []
  compareFileInfo.value = null
  compareFileId.value = null
  compareViewMode.value = 'split'
  unifiedWidgets.value = []
  unifiedWidgetsCache.value = []
  primaryWidgetsSnapshot.value = []
  chartFilters.value = {}
  userRequirements.value = ''
  showRequirementsPanel.value = false
  showCompareSelector.value = false
  showExportMenu.value = false
  showThemePicker.value = false
  boardScreens.value = [{ id: 'screen-1', name: 'Dashboard' }]
  activeScreenId.value = 'screen-1'
  boardScreenWidgets.value = { 'screen-1': [] }
  boardFileScreenWidgets.value = {}
  boardFileScreenNeedsGeneration.value = {}
  boardFileScreenPendingTemplates.value = {}
  templateSourceFileId.value = ''
  // Load new file
  await loadFileInfo()
  await loadDashboard()
})

onMounted(async () => {
  window.addEventListener('keydown', handleKeydown)
  window.addEventListener('resize', handleResize)
  window.addEventListener('scroll', handleWindowScroll, true)
  document.addEventListener('mousedown', handleOutsideClick)

  if (isSharedMode.value) {
    await initSharedDashboard()
    return
  }

  if (isBoardMode.value) {
    await initBoardDashboard()
    return
  }

  if (isDashboardProject.value) {
    // Project-first init: single canonical endpoint, no file-first branching
    await initProjectDashboard()
    return
  }

  // Legacy file-first path (non-dashboard mode)
  const id = resolvedFileId.value
  if (!id) return

  await loadFileInfo()
  if (!store.sortedFiles.length || !store.projects.length) store.fetchAll()
  await loadDashboard()
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', handleKeydown)
  window.removeEventListener('resize', handleResize)
  window.removeEventListener('scroll', handleWindowScroll, true)
  document.removeEventListener('mousedown', handleOutsideClick)
  if (persistTimer) clearTimeout(persistTimer)
  if (backendPersistTimer) clearTimeout(backendPersistTimer)
  window.dispatchEvent(new CustomEvent('topbar-share-link-updated', { detail: '' }))
  try { grid?.destroy(false) } catch {}
  grid = null
  try { gridB?.destroy(false) } catch {}
  gridB = null
  exitSharedLightMode()
})
</script>

<template>
  <div :class="['dashboard-root relative flex gap-3 p-3', isSharedMode ? 'h-screen' : 'h-[calc(100vh-3.5rem)]']">
    <!-- ── COMMAND PALETTE (Ctrl+K) ─────────────────────────────── -->
    <div v-if="showCommandPalette && !isSharedMode" class="fixed inset-0 z-50 flex items-start justify-center pt-[18vh]">
      <div class="fixed inset-0 bg-black/60 backdrop-blur-sm" @click="showCommandPalette = false" />
      <div class="relative w-full max-w-lg rounded-2xl border border-white/10 bg-slate-800/95 shadow-2xl backdrop-blur-2xl overflow-hidden">
        <div class="flex items-center gap-3 border-b border-white/10 px-4 py-3">
          <svg class="h-5 w-5 text-slate-400 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" /></svg>
          <input ref="commandInputRef" v-model="commandQuery" placeholder="Type a command…"
            class="flex-1 bg-transparent text-sm text-white placeholder-slate-500 outline-none" />
          <kbd class="rounded bg-slate-700 px-1.5 py-0.5 text-[10px] text-slate-500">ESC</kbd>
        </div>
        <div class="max-h-72 overflow-y-auto py-1">
          <button v-for="cmd in filteredCommands" :key="cmd.id" @click="executeCommand(cmd)"
            class="flex w-full items-center gap-3 px-4 py-2.5 text-left text-sm text-slate-300 transition hover:bg-white/5">
            <span class="w-5 text-center text-base opacity-60">{{ cmd.icon }}</span>
            <span>{{ cmd.label }}</span>
          </button>
          <p v-if="!filteredCommands.length" class="px-4 py-6 text-center text-sm text-slate-500">No matching commands</p>
        </div>
      </div>
    </div>

    <!-- ── LEFT DASHBOARD SIDEBAR ──────────────────────────────── -->
    <LeftSidebar
      :visible="!isSharedMode && !isPreviewMode"
      :sidebar-open="sidebarOpen"
      :studio-tab="studioTab"
      :board-screens="boardScreens"
      :board-screen-previews="boardScreenPreviews"
      :board-screen-thumbnails="boardScreenThumbnails"
      :active-screen-id="activeScreenId"
      :theme-keys="themeKeys"
      :active-theme="activeTheme"
      :get-swatch-style="getSwatchStyle"
      :board-files="boardFiles"
      :active-widget="activeWidget"
      :dashboard-design="boardDesign"
      @update:studio-tab="studioTab = $event"
      @activate-screen="activateScreen"
      @rename-screen="renameScreen"
      @delete-screen="deleteScreen"
      @add-screen="addBoardScreen"
      @set-theme="setTheme"
      @update-widget-style="handleWidgetStyleUpdate"
      @update-dashboard-design="handleDashboardDesignUpdate"
    >
      <template #elements-footer>
        <template v-if="isDashboardProject">
          <div class="flex-1 px-2 py-2 overflow-hidden">
            <div class="flex h-full flex-col overflow-hidden rounded-2xl border border-slate-200/80 bg-white/70 shadow-sm dark:border-white/10 dark:bg-slate-900/50">
              <div class="border-b border-slate-100 px-3 py-2 dark:border-white/5">
                <p class="text-[11px] font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Source Files</p>
              </div>
              <div class="flex-1 overflow-y-auto py-2 px-2 space-y-1">
                <div
                  v-for="f in dataSources" :key="f.file_uuid"
                  @click="switchActiveDataSource(f.file_uuid)"
                  :class="[
                    'rounded-xl cursor-pointer transition text-sm border px-3 py-2.5',
                    f.file_uuid === activeDataSourceId
                      ? 'bg-emerald-50/70 text-emerald-700 font-medium border-emerald-200 dark:bg-emerald-500/15 dark:text-emerald-300 dark:border-emerald-500/30'
                      : 'text-slate-600 border-transparent hover:bg-slate-100 hover:border-slate-200 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:border-slate-700'
                  ]"
                >
                  <div class="flex items-start gap-2.5">
                    <iconify-icon
                      icon="lucide:file-spreadsheet"
                      :class="['mt-0.5 h-4 w-4 shrink-0', f.file_uuid === activeDataSourceId ? 'text-emerald-500' : 'text-slate-400']"
                    />
                    <div class="min-w-0 flex-1">
                      <div class="flex items-start gap-2">
                        <p class="truncate text-[15px] leading-tight font-medium flex-1">{{ f.filename }}</p>
                        <div v-if="f.file_uuid === getTemplateSourceFileKey() || f.file_uuid === dashboardProject?.published_file_uuid || f.file_uuid === activeDataSourceId"
                          class="flex items-center gap-1 shrink-0">
                          <span v-if="f.file_uuid === getTemplateSourceFileKey()"
                            class="inline-flex h-5 w-5 items-center justify-center rounded-full bg-amber-50 text-amber-600 dark:bg-amber-500/10 dark:text-amber-400"
                            title="Original source file">
                            <iconify-icon icon="lucide:anchor" class="h-3 w-3" />
                          </span>
                          <span v-if="f.file_uuid === dashboardProject?.published_file_uuid"
                            class="inline-flex h-5 w-5 items-center justify-center rounded-full bg-violet-50 text-violet-600 dark:bg-violet-500/10 dark:text-violet-400"
                            title="This file's dashboard is shared publicly">
                            <iconify-icon icon="lucide:globe" class="h-3 w-3" />
                          </span>
                          <span v-if="f.file_uuid === activeDataSourceId"
                            class="inline-flex h-5 w-5 items-center justify-center rounded-full bg-emerald-50 text-emerald-600 dark:bg-emerald-500/10 dark:text-emerald-400"
                            title="Active data source">
                            <iconify-icon icon="lucide:circle-check" class="h-3 w-3" />
                          </span>
                        </div>
                      </div>
                      <p v-if="f.created_on" class="mt-1 text-[10px] text-slate-400 dark:text-slate-500 tabular-nums">
                        {{ new Date(f.created_on).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit' }) }}
                      </p>
                    </div>
                  </div>
                </div>
                <div v-if="dataSources.length === 0" class="text-center py-12 px-4">
                  <iconify-icon icon="lucide:database" class="h-8 w-8 text-muted-foreground/40 mx-auto mb-2" />
                  <p class="text-xs text-muted-foreground">No data sources yet</p>
                </div>
              </div>
              <div class="px-3 py-2 border-t border-slate-100 dark:border-white/5">
                <button @click="triggerDataSourceUpload"
                  class="w-full flex items-center justify-center gap-1.5 rounded-lg bg-emerald-50 px-3 py-2 text-xs font-medium text-emerald-700 transition hover:bg-emerald-100 dark:bg-emerald-500/10 dark:text-emerald-400 dark:hover:bg-emerald-500/20">
                  <iconify-icon icon="lucide:plus" class="h-3.5 w-3.5" /> Add Data Source
                </button>
                <input type="file" ref="dataSourceFileInput" class="hidden" accept=".csv,.xlsx,.xls" @change="handleDataSourceUpload" />
              </div>
            </div>
          </div>
          <div class="px-3 py-1.5 border-t border-slate-100 dark:border-white/5 text-[11px] text-muted-foreground">
            {{ dataSources.length }} file{{ dataSources.length !== 1 ? 's' : '' }}
          </div>
        </template>

        <template v-else-if="route.query.mode === 'connection' || route.query.mode === 'table'">
          <div class="flex-1 overflow-y-auto py-1 px-1 scroll-smooth scrollbar-thin">
            <div class="px-3 py-2 border-b border-slate-100 dark:border-white/5 bg-slate-50/50 dark:bg-slate-900/20">
              <p class="text-[11px] font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400 flex items-center gap-1.5"><iconify-icon icon="lucide:database" class="w-3.5 h-3.5" /> Database Insight</p>
            </div>
            <div class="px-4 py-8 text-center text-slate-400 dark:text-slate-500 text-xs">
              <iconify-icon icon="lucide:server" class="w-8 h-8 opacity-40 mx-auto mb-3" />
              <p class="font-medium text-slate-600 dark:text-slate-300">Live Database Source</p>
              <p class="mt-2 opacity-80 leading-relaxed max-w-[20ch] mx-auto">Dashboards and widgets generated here use direct database queries.</p>
            </div>
          </div>
        </template>
        <template v-else>
          <div class="flex-1 overflow-y-auto py-1 px-1 scroll-smooth scrollbar-thin">
            <div class="px-3 py-2">
              <p class="text-[11px] font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Workspace Files</p>
            </div>
            <FileSystemNode
              v-for="node in dashboardFileTree"
              :key="node.id"
              :node="node"
              :depth="0"
              :selectedFileId="resolvedFileId"
              :isTrash="false"
              @selectFile="f => router.push({ path: '/app', query: { fileId: f.file_uuid } })"
              @deleteFile="() => {}"
              @restoreFile="() => {}"
              @chatFile="() => {}"
              @uploadToFolder="() => {}"
              @addSheet="() => {}"
            />
            <div v-if="dashboardFileTree.length === 0" class="text-center py-12 px-4">
              <iconify-icon icon="lucide:folder-open" class="h-8 w-8 text-muted-foreground/40 mx-auto mb-2" />
              <p class="text-xs text-muted-foreground">No documents yet</p>
            </div>
          </div>
          <div class="px-3 py-1.5 border-t border-slate-100 dark:border-white/5 flex items-center justify-between text-[11px] text-muted-foreground">
            <span>{{ store.sortedFiles.length }} file{{ store.sortedFiles.length !== 1 ? 's' : '' }}</span>
            <span>{{ store.projects.length }} folder{{ store.projects.length !== 1 ? 's' : '' }}</span>
          </div>
        </template>
      </template>
    </LeftSidebar>

    <!-- ── MAIN CONTENT ─────────────────────────────────────────── -->
    <div ref="exportContainer" class="flex min-w-0 flex-1 flex-col overflow-hidden glass-panel rounded-2xl transition-all duration-300">

      <!-- Top Bar -->
      <header class="relative z-30 flex shrink-0 items-start justify-between gap-2 border-b border-slate-200/70 bg-gradient-to-r from-white/95 via-white/90 to-slate-50/85 px-3 py-2 backdrop-blur-xl dark:border-white/10 dark:from-slate-900/95 dark:via-slate-900/90 dark:to-slate-900/80">
        <!-- ── SHARED-MODE HEADER (read only) ── -->
        <template v-if="isSharedMode">
          <div class="flex items-center gap-3">
            <div class="h-9 w-9 rounded-lg bg-gradient-to-br from-indigo-500 to-indigo-600 flex items-center justify-center text-white shadow-sm">
              <iconify-icon icon="lucide:layout-dashboard" class="h-4.5 w-4.5" />
            </div>
            <div>
              <h1 class="text-base font-semibold text-slate-900 dark:text-slate-100 leading-tight">
                {{ boardProjectProxy?.name || 'Shared Dashboard' }}
              </h1>
              <p class="text-[10px] text-slate-400 dark:text-slate-500">
                {{ widgets.length }} widgets &middot; Insight Board
              </p>
            </div>
          </div>
          <div class="text-xs font-semibold text-indigo-600 bg-indigo-50 px-3 py-1.5 rounded-full dark:bg-indigo-900/30 dark:text-indigo-400 border border-indigo-100 dark:border-indigo-800/40">
            Read-Only View
          </div>
        </template>

        <!-- ── NORMAL HEADER (editing) ── -->
        <template v-else>
        <div class="flex min-w-0 flex-1 items-center gap-2 pr-1">
          <!-- Sidebar toggle (VS Code-style panel icon) -->
          <button @click="toggleSidebar()"
            :title="sidebarOpen ? 'Hide sidebar (Explorer)' : 'Show sidebar (Explorer)'"
            :class="['rounded-lg p-1.5 transition', sidebarOpen ? 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300' : 'text-slate-400 hover:bg-slate-100 hover:text-slate-700 dark:text-slate-500 dark:hover:bg-slate-800 dark:hover:text-slate-300']">
            <iconify-icon :icon="sidebarOpen ? 'lucide:panel-left-close' : 'lucide:panel-left-open'" class="h-4 w-4" />
          </button>
          <!-- Divider -->
          <div :class="['h-5 w-px bg-slate-200 dark:bg-slate-700', isHeaderCompact ? 'hidden xl:block' : 'block']" />
          <div class="min-w-0 flex-1 transition-all duration-300">
            <div class="flex items-center gap-2 min-w-0">
              <h1
                :class="['truncate text-[0.96rem] lg:text-[1.02rem] font-semibold text-slate-900 dark:text-slate-100 leading-tight', isHeaderCompact ? 'max-w-full' : 'max-w-[44ch]']"
                :title="dashboardDisplayTitle"
              >
                {{ dashboardDisplayTitle }}
              </h1>
            </div>
            <p :class="['mt-0.5 flex items-center gap-1.5 text-[10px] text-slate-500 dark:text-slate-400', sidebarOpen ? 'hidden xl:flex' : 'flex']">
              <span class="tabular-nums">{{ widgets.length }}</span>
              <span>widgets</span>
            </p>
          </div>
        </div>
        <div :class="['ml-auto flex max-w-full items-center overflow-x-auto whitespace-nowrap pl-1 no-scrollbar', isHeaderCompact ? 'gap-1' : 'gap-1.5']">
          <!-- Active Data Source indicator (Project Dashboards) — sources list is in the sidebar -->
          <div v-if="isDashboardProject && dataSources.length > 0 && !isSharedMode && !isHeaderCompact" class="hidden 2xl:flex items-center gap-2 border-r border-slate-200/80 dark:border-slate-700 pr-2.5 mr-0.5">
            <div class="flex items-center gap-1.5 rounded-xl border border-slate-200/80 bg-white/80 px-2 py-1 text-[11px] text-slate-600 shadow-sm dark:border-slate-700 dark:bg-slate-800/70 dark:text-slate-300">
              <iconify-icon icon="lucide:file-spreadsheet" class="h-3.5 w-3.5 text-indigo-500" />
              <span class="max-w-[180px] truncate font-medium">{{ dataSources.find(f => f.file_uuid === activeDataSourceId)?.filename || 'No source' }}</span>
            </div>
          </div>

          <!-- Share controls (compact) -->
          <div v-if="isDashboardProject && !isSharedMode" class="flex items-center gap-1 border-r border-slate-200/80 dark:border-slate-700 pr-2.5 mr-0.5">
            <!-- Share / Private pill -->
            <button @click="toggleShareStatus"
                :class="['flex items-center gap-1 rounded-xl border px-2 py-1 text-[11px] font-semibold transition shadow-sm', dashboardProject?.is_shared ? 'border-emerald-200 bg-emerald-50 text-emerald-700 hover:bg-emerald-100 dark:border-emerald-700/40 dark:bg-emerald-500/10 dark:text-emerald-400' : 'border-slate-200 bg-white/70 text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-800/60 dark:text-slate-300 dark:hover:bg-slate-800']"
              :title="dashboardProject?.is_shared ? 'Shared — click to make private' : 'Private — click to share'">
              <iconify-icon :icon="dashboardProject?.is_shared ? 'lucide:globe' : 'lucide:lock'" class="h-3.5 w-3.5" />
              <span>{{ dashboardProject?.is_shared ? 'Shared' : 'Private' }}</span>
            </button>
            <!-- Copy link icon (only when shared) -->
            <button v-if="dashboardProject?.is_shared" @click="copyShareLink"
              class="h-6 w-6 flex items-center justify-center rounded text-emerald-600 hover:bg-emerald-50 dark:hover:bg-emerald-500/10 transition"
              title="Copy share link">
              <iconify-icon icon="lucide:copy" class="h-3.5 w-3.5" />
            </button>
            <!-- Freeze icon-toggle (only when shared + board mode) -->
            <button v-if="dashboardProject?.is_shared && isBoardMode" @click="togglePublishFreeze"
              :class="['h-6 w-6 flex items-center justify-center rounded transition', dashboardProject?.published_file_uuid ? 'text-indigo-600 bg-indigo-50 hover:bg-indigo-100 dark:bg-indigo-500/20 dark:text-indigo-400' : 'text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800']"
              :title="dashboardProject?.published_file_uuid ? 'Frozen — click to go live' : 'Live — click to freeze current file'">
              <iconify-icon :icon="dashboardProject?.published_file_uuid ? 'lucide:snowflake' : 'lucide:radio'" class="h-3.5 w-3.5" />
            </button>
          </div>
          <template v-if="!isSharedMode">
          <div class="flex items-center rounded-xl border border-slate-200 bg-white/75 p-0.5 shadow-sm dark:border-slate-700 dark:bg-slate-800/60">
            <button @click="zoomOutCanvas" class="rounded-lg px-2 py-1 text-xs text-slate-600 transition hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-700" title="Zoom out">
              <iconify-icon icon="lucide:minus" class="h-3.5 w-3.5" />
            </button>
            <button @click="resetCanvasZoom" class="min-w-[48px] rounded-lg px-1.5 py-1 text-[10px] font-semibold text-slate-600 transition hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-700" title="Reset zoom">
              {{ canvasZoom }}%
            </button>
            <button @click="zoomInCanvas" class="rounded-lg px-2 py-1 text-xs text-slate-600 transition hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-700" title="Zoom in">
              <iconify-icon icon="lucide:plus" class="h-3.5 w-3.5" />
            </button>
          </div>
          <button
            @click="togglePreviewMode"
            :class="['rounded-xl border px-2.5 py-1 text-xs font-semibold transition shadow-sm', isPreviewMode ? 'border-emerald-300 bg-emerald-50 text-emerald-700 dark:border-emerald-600/40 dark:bg-emerald-500/10 dark:text-emerald-300' : 'border-slate-200 bg-white/75 text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-800/60 dark:text-slate-300 dark:hover:bg-slate-800']"
            :title="isPreviewMode ? 'Exit preview mode' : 'Preview mode'"
          >
            <span class="inline 2xl:hidden">👁</span>
            <span class="hidden 2xl:inline">{{ isPreviewMode ? 'Exit Preview' : 'Preview' }}</span>
          </button>
          <button @click="showCommandPalette = true"
            class="hidden items-center gap-2 rounded-xl border border-slate-200 bg-white/75 px-2.5 py-1 text-xs text-slate-600 shadow-sm transition hover:border-slate-300 hover:text-slate-800 dark:border-slate-700 dark:bg-slate-800/60 dark:text-slate-300 dark:hover:border-slate-600 xl:flex">
            <svg class="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" /></svg>
            <span>Search</span>
            <kbd class="rounded bg-slate-100 px-1 py-0.5 text-[10px] font-medium dark:bg-slate-800">⌘K</kbd>
          </button>
          <!-- Chart Builder toggle -->
          <button @click="openChartBuilder()"
            :disabled="isBoardMode && !isTemplateSourceActive"
            :class="['flex items-center gap-1.5 rounded-xl border px-2.5 py-1 text-xs font-semibold transition shadow-sm', chartBuilderOpen ? 'border-violet-400 bg-violet-50 text-violet-700 dark:border-violet-600 dark:bg-violet-950 dark:text-violet-300' : 'border-slate-200 bg-white/75 text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-800/60 dark:text-slate-300 dark:hover:bg-slate-800', (isBoardMode && !isTemplateSourceActive) ? 'cursor-not-allowed opacity-50 hover:bg-white/75 dark:hover:bg-slate-800/60' : '']"
            :title="(isBoardMode && !isTemplateSourceActive) ? 'Only source file can add charts' : 'Open interactive Chart Builder'">
            <iconify-icon icon="lucide:layout-template" class="h-3.5 w-3.5" />
            <span class="hidden 2xl:inline">Chart Builder</span>
          </button>
          <button @click="loadDashboard(true)" :disabled="isLoading"
            class="rounded-xl border border-slate-200 bg-white/75 px-2.5 py-1 text-xs font-semibold text-slate-700 shadow-sm transition hover:bg-slate-50 disabled:opacity-50 dark:border-slate-700 dark:bg-slate-800/60 dark:text-slate-200 dark:hover:bg-slate-800">
            <span class="inline 2xl:hidden">⟳</span>
            <span class="hidden 2xl:inline">⟳ Regenerate</span>
          </button>
          <!-- Requirements customisation toggle -->
          <button
            @click="showRequirementsPanel = !showRequirementsPanel"
            :class="['rounded-xl border px-2 py-1 text-xs transition shadow-sm', showRequirementsPanel || userRequirements ? 'border-indigo-400 bg-indigo-50 text-indigo-700 dark:border-indigo-600 dark:bg-indigo-950 dark:text-indigo-300' : 'border-slate-200 bg-white/75 text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-800/60 dark:text-slate-300 dark:hover:bg-slate-800']"
            title="Customize dashboard generation">
            ⚙️
          </button>
          <!-- Export menu -->
          <div>
            <button ref="exportTriggerRef" @click="toggleExportMenu" :disabled="isExporting || !widgets.length"
              class="rounded-xl border border-slate-200 bg-white/75 px-2.5 py-1 text-xs font-semibold text-slate-700 shadow-sm transition hover:bg-slate-50 disabled:opacity-50 dark:border-slate-700 dark:bg-slate-800/60 dark:text-slate-200 dark:hover:bg-slate-800">
              <span class="inline 2xl:hidden">{{ isExporting ? '⏳' : '↓' }}</span>
              <span class="hidden 2xl:inline">{{ isExporting ? '⏳' : '↓' }} Export</span>
            </button>
          </div>
          <button @click="toggleLock"
            class="rounded-xl px-2.5 py-1 text-xs font-semibold transition shadow-sm"
            :class="isDashboardLocked ? 'border border-slate-200 bg-slate-100 text-slate-600 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300' : 'border border-indigo-200 bg-indigo-100 text-indigo-700 dark:border-indigo-500/40 dark:bg-indigo-900/50 dark:text-indigo-300'">
            <span class="inline 2xl:hidden">{{ isDashboardLocked ? '🔒' : '🔓' }}</span>
            <span class="hidden 2xl:inline">{{ isDashboardLocked ? '🔒 Locked' : '🔓 Edit' }}</span>
          </button>
          </template>
          <!-- Langfuse Trace Buttons (chat-style) -->
          <!-- Direct trace for latest response -->
          <button
            v-if="lastTraceUrl || lastTraceId"
            @click="openLastDashboardTrace"
            class="h-7 w-7 flex items-center justify-center rounded-lg text-muted-foreground hover:text-primary transition-colors"
            title="View latest dashboard trace in Langfuse"
            aria-label="View trace"
          >
            <iconify-icon icon="lucide:activity" class="h-3.5 w-3.5" />
          </button>
          <!-- All traces for this dashboard session -->
          <button
            v-if="dashboardSessionId && (lastTraceId || lastTraceUrl)"
            @click="openDashboardSession"
            :disabled="isOpeningSession"
            class="h-7 w-7 flex items-center justify-center rounded-lg text-muted-foreground hover:text-primary transition-colors disabled:opacity-50"
            title="Open this dashboard session in Langfuse"
            aria-label="View all dashboard traces"
          >
            <iconify-icon :icon="isOpeningSession ? 'eos-icons:loading' : 'lucide:list'" :class="isOpeningSession ? 'h-3.5 w-3.5 animate-spin' : 'h-3.5 w-3.5'" />
          </button>
          <!-- Color Theme Picker -->
          <div>
            <button ref="themeTriggerRef" @click="toggleThemePicker"
              class="flex h-8 w-8 items-center justify-center rounded-lg border border-slate-200 transition hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800"
              title="Change color theme">
              <span class="block h-4 w-4 rounded-full" :style="getSwatchStyle(activeTheme)" />
            </button>
          </div>
          <button
            v-if="!isDashboardLocked && hasWidgetColorOverrides"
            @click="clearAllWidgetColors"
            class="h-8 w-8 flex items-center justify-center rounded-lg border border-amber-200 text-amber-600 transition hover:bg-amber-50 dark:border-amber-500/30 dark:text-amber-300 dark:hover:bg-amber-500/10"
            title="Clear all widget colors">
            <iconify-icon icon="lucide:eraser" class="h-3.5 w-3.5" />
          </button>
          <!-- Compare View Mode Toggle (only visible in compare mode) -->
          <div v-if="isCompareMode" class="flex items-center rounded-lg border border-slate-200 p-0.5 dark:border-slate-700">
            <button @click="switchCompareView('split')"
              :disabled="isUnifiedLoading || isCompareLoading"
              :class="[
                'flex items-center gap-1 rounded-md px-2.5 py-1 text-xs font-medium transition disabled:opacity-40 disabled:cursor-not-allowed',
                compareViewMode === 'split'
                  ? 'bg-indigo-100 text-indigo-700 shadow-sm dark:bg-indigo-500/20 dark:text-indigo-300'
                  : 'text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200'
              ]"
              title="Side-by-side split view">
              <svg class="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><rect x="3" y="3" width="7" height="18" rx="1" stroke-width="2"/><rect x="14" y="3" width="7" height="18" rx="1" stroke-width="2"/></svg>
              Split
            </button>
            <button @click="switchCompareView('unified')"
              :disabled="isUnifiedLoading || isCompareLoading"
              :class="[
                'flex items-center gap-1 rounded-md px-2.5 py-1 text-xs font-medium transition disabled:opacity-40 disabled:cursor-not-allowed',
                compareViewMode === 'unified'
                  ? 'bg-violet-100 text-violet-700 shadow-sm dark:bg-violet-500/20 dark:text-violet-300'
                  : 'text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200'
              ]"
              title="Merged unified comparison view">
              <svg class="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/></svg>
              <span v-if="isUnifiedLoading" class="inline-flex items-center gap-1">
                <span class="h-3 w-3 animate-spin rounded-full border-2 border-violet-300 border-t-violet-600" />
                Building…
              </span>
              <span v-else>Unified</span>
            </button>
          </div>
          <!-- Compare Button -->
          <div v-if="!isDashboardProject">
            <button v-if="!isCompareMode" ref="compareTriggerRef" @click="openCompareSelector"
              class="flex items-center gap-1.5 rounded-lg border border-slate-200 px-3 py-1.5 text-sm font-medium transition hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800"
              title="Compare with another file">
              <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 17V7m0 10a2 2 0 01-2 2H5a2 2 0 01-2-2V7a2 2 0 012-2h2a2 2 0 012 2m0 10a2 2 0 002 2h2a2 2 0 002-2M9 7a2 2 0 012-2h2a2 2 0 012 2m0 10V7" /></svg>
              Compare
            </button>
            <button v-else @click="exitCompareMode"
              class="flex items-center gap-1.5 rounded-lg border border-violet-300 bg-violet-50 px-3 py-1.5 text-sm font-medium text-violet-700 transition hover:bg-violet-100 dark:border-violet-500/40 dark:bg-violet-500/10 dark:text-violet-300 dark:hover:bg-violet-500/20">
              <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" /></svg>
              Exit Compare
            </button>
          </div>
        </div>
        </template>
      </header>

      <!-- ── CUSTOM REQUIREMENTS PANEL ──────────────────────────────────────── -->
      <Transition name="slide-down">
        <div v-if="showRequirementsPanel"
          class="flex shrink-0 items-start gap-3 border-b border-indigo-100 bg-indigo-50/60 px-6 py-3 backdrop-blur-sm dark:border-indigo-500/20 dark:bg-indigo-500/5">
          <div class="flex-1">
            <p class="mb-1 text-[10px] font-semibold uppercase tracking-widest text-indigo-500 dark:text-indigo-400">
              Dashboard Requirements
            </p>
            <textarea
              v-model="userRequirements"
              placeholder="e.g. &quot;focus on Salary, treat Region as dimension, ignore Mobile Number, use Total Applications as key metric&quot;"
              rows="2"
              class="w-full resize-none rounded-lg border border-indigo-200 bg-white px-3 py-2 text-xs text-slate-700 outline-none transition placeholder:text-slate-400 focus:border-indigo-400 focus:ring-2 focus:ring-indigo-300/30 dark:border-indigo-500/30 dark:bg-slate-900 dark:text-slate-300"
            />
            <p class="mt-1 text-[10px] text-slate-400 dark:text-slate-500">
              Hints are applied on next <strong>⟳ Regenerate</strong>. No extra AI call — pure column matching.
            </p>
          </div>
          <div class="flex flex-col items-end gap-2 pt-5">
            <button @click="loadDashboard(true)" :disabled="isLoading"
              class="rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-indigo-700 disabled:opacity-50">
              ⟳ Apply &amp; Regenerate
            </button>
            <button v-if="userRequirements" @click="userRequirements = ''"
              class="text-[10px] text-slate-400 hover:text-red-500 transition">
              Clear
            </button>
          </div>
        </div>
      </Transition>

      <!-- Teleported Export Menu -->
      <Teleport to="body">
        <Transition name="fab-pop">
          <div v-if="showExportMenu" ref="exportMenuRef"
            :style="{ position: 'fixed', top: exportMenuPosition.top + 'px', left: exportMenuPosition.left + 'px' }"
            class="z-[10000] w-40 rounded-xl border border-slate-200/80 bg-white p-1 shadow-xl dark:border-white/10 dark:bg-slate-900">
            <button @click="runExportAction('png')" class="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm text-slate-700 transition hover:bg-slate-50 dark:text-slate-300 dark:hover:bg-white/5">
              <svg class="h-4 w-4 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" /></svg>
              Export PNG
            </button>
            <button @click="runExportAction('pdf')" class="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm text-slate-700 transition hover:bg-slate-50 dark:text-slate-300 dark:hover:bg-white/5">
              <svg class="h-4 w-4 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z" /></svg>
              Export PDF
            </button>
          </div>
        </Transition>
      </Teleport>

      <!-- Teleported Compare Selector -->
      <Teleport to="body">
        <Transition name="fab-pop">
          <div v-if="showCompareSelector" ref="compareSelectorRef"
            :style="{ position: 'fixed', top: compareMenuPosition.top + 'px', left: compareMenuPosition.left + 'px' }"
            class="z-[10000] w-80 max-h-72 overflow-y-auto rounded-xl border border-slate-200/80 bg-white p-2 shadow-xl dark:border-white/10 dark:bg-slate-900">
            <p class="px-3 py-2 text-xs font-semibold text-slate-500 dark:text-slate-400">Select a file to compare</p>
            <div v-if="!availableCompareFiles.length" class="px-3 py-4 text-center text-xs text-slate-400">No other files in this directory</div>
            <button v-for="f in availableCompareFiles" :key="f.file_uuid" @click="selectCompareFile(f)"
              class="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left transition hover:bg-slate-50 dark:hover:bg-white/5">
              <div class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-violet-100 dark:bg-violet-500/15">
                <svg class="h-4 w-4 text-violet-600 dark:text-violet-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" /></svg>
              </div>
              <div class="flex-1 min-w-0">
                <p class="truncate text-sm font-medium text-slate-700 dark:text-slate-200">{{ f.filename }}</p>
                <p class="text-[10px] text-slate-400">{{ f.total_rows?.toLocaleString() || '?' }} rows &middot; {{ f.columns?.length || '?' }} cols</p>
              </div>
            </button>
          </div>
        </Transition>
      </Teleport>

      <!-- Teleported Theme Picker -->
      <Teleport to="body">
        <Transition name="fab-pop">
          <div v-if="showThemePicker" ref="themePickerRef"
            :style="{ position: 'fixed', top: themeMenuPosition.top + 'px', left: themeMenuPosition.left + 'px' }"
            class="z-[10000] flex gap-2 rounded-xl border border-slate-200/80 bg-white p-3 shadow-xl dark:border-white/10 dark:bg-slate-900">
            <button v-for="key in themeKeys" :key="key" @click="setTheme(key)"
              class="group/swatch relative flex h-7 w-7 items-center justify-center rounded-full transition hover:scale-110"
              :style="getSwatchStyle(key)"
              :title="key">
              <svg v-if="activeTheme === key" class="h-3.5 w-3.5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7" /></svg>
            </button>
          </div>
        </Transition>
      </Teleport>
      <!-- ── SLICER RIBBON (Power BI-style global dimension filters) — always visible ── -->
      <div v-if="slicerDimensions.length && !isLoading"
        class="flex shrink-0 flex-wrap items-center gap-2 border-b border-slate-200/70 bg-white/55 px-3 py-1 backdrop-blur-sm dark:border-white/10 dark:bg-slate-900/25">
        <span class="mr-1 text-[9px] font-bold uppercase tracking-widest text-slate-500 dark:text-slate-400">
          <svg class="inline h-3 w-3 -mt-0.5 mr-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 4a1 1 0 011-1h16a1 1 0 011 1v2.586a1 1 0 01-.293.707l-6.414 6.414a1 1 0 00-.293.707V17l-4 4v-6.586a1 1 0 00-.293-.707L3.293 7.293A1 1 0 013 6.586V4z" /></svg>
          Slicers
        </span>
        <div v-for="dim in slicerDimensions" :key="dim.col" class="flex items-center gap-1">
          <label class="whitespace-nowrap text-[10px] font-medium text-slate-500 dark:text-slate-300 capitalize">{{ dim.col.replace(/_/g, ' ') }}</label>
          <select
            :value="slicerValues[dim.col] || '__all__'"
            @change="onSlicerChange(dim.col, ($event.target as HTMLSelectElement).value)"
            class="h-6 max-w-[170px] rounded-lg border border-slate-200 bg-white/95 px-2 text-[10px] font-medium text-slate-700 outline-none transition focus:border-indigo-400 focus:ring-2 focus:ring-indigo-400/20 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200">
            <option value="__all__">All ({{ Object.keys(dim.top_values || {}).length }})</option>
            <option v-for="(count, val) in dim.top_values" :key="val" :value="val">{{ val }} ({{ count }})</option>
          </select>
        </div>
        <button v-if="Object.keys(slicerValues).length" @click="clearCrossFilter"
          class="ml-auto rounded-md px-2 py-0.5 text-[10px] font-medium text-indigo-600 transition hover:bg-indigo-50 dark:text-indigo-400 dark:hover:bg-indigo-500/10">
          Clear All
        </button>
        <button v-if="hasAnyChartFilter" @click="chartFilters = {} as Record<string, string[] | null>"
          class="rounded-md px-2 py-0.5 text-[10px] font-medium text-violet-600 transition hover:bg-violet-50 dark:text-violet-400 dark:hover:bg-violet-500/10"
          :class="Object.keys(slicerValues).length ? 'ml-2' : 'ml-auto'">
          Clear Chart Filters ✕
        </button>
      </div>

      <!-- Cross-filter indicator -->
      <div v-if="crossFilter || isFiltering" class="flex shrink-0 items-center justify-between border-b border-indigo-300/30 bg-indigo-50/80 px-6 py-1.5 dark:border-indigo-500/20 dark:bg-indigo-500/10">
        <span class="flex items-center gap-2 text-xs text-indigo-700 dark:text-indigo-300">
          <svg v-if="isFiltering" class="h-3.5 w-3.5 animate-spin" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" /><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" /></svg>
          <template v-if="isFiltering">Applying filter…</template>
          <template v-else>Filtering by <strong>{{ crossFilter?.key }}</strong>: {{ crossFilter?.value }}</template>
        </span>
        <button @click="clearCrossFilter" :disabled="isFiltering" class="text-xs font-medium text-indigo-600 hover:text-indigo-800 disabled:opacity-50 dark:text-indigo-400 dark:hover:text-indigo-200">Clear ✕</button>
      </div>

      <!-- Content -->
      <div
        :class="['dashboard-theme-canvas theme-colored flex-1', isCompareMode && compareViewMode === 'split' && !isUnifiedLoading ? 'flex flex-row overflow-hidden' : 'overflow-auto']"
        :style="themeCssVars"
        @click="clearWidgetSelection"
      >

        <!-- Loading (primary dashboard) -->
        <div v-if="isLoading" class="flex h-full items-center justify-center">
          <div class="text-center">
            <div class="relative mx-auto mb-5 h-16 w-16">
              <div class="absolute inset-0 animate-spin rounded-full border-[3px] border-indigo-100 border-t-indigo-500 dark:border-indigo-900 dark:border-t-indigo-400" />
              <div class="absolute inset-2 animate-spin rounded-full border-[3px] border-violet-100 border-b-violet-500 dark:border-violet-900 dark:border-b-violet-400" style="animation-direction: reverse; animation-duration: 1.2s;" />
            </div>
            <p class="text-sm font-semibold text-slate-700 dark:text-slate-300">Generating dashboard…</p>
            <p class="mt-1.5 text-xs text-slate-400 dark:text-slate-500">Analyzing data & creating charts</p>
          </div>
        </div>

        <!-- Unified comparison loading (shown while API call runs, before mode switches) -->
        <div v-else-if="isUnifiedLoading" class="flex h-full items-center justify-center">
          <div class="text-center">
            <div class="relative mx-auto mb-5 h-16 w-16">
              <div class="absolute inset-0 animate-spin rounded-full border-[3px] border-indigo-100 border-t-indigo-500 dark:border-indigo-900 dark:border-t-indigo-400" />
              <div class="absolute inset-2 animate-spin rounded-full border-[3px] border-violet-100 border-b-violet-500 dark:border-violet-900 dark:border-b-violet-400" style="animation-direction: reverse; animation-duration: 1.5s;" />
            </div>
            <p class="text-sm font-semibold text-violet-700 dark:text-violet-300">Building Unified View…</p>
            <p class="mt-1.5 text-xs text-slate-400 dark:text-slate-500">Merging metrics &amp; charts from both files</p>
            <div class="mt-3 flex items-center justify-center gap-2">
              <span class="rounded-full bg-indigo-50 px-2.5 py-1 text-[10px] font-semibold text-indigo-600 dark:bg-indigo-500/10 dark:text-indigo-400">{{ fileInfo?.filename }}</span>
              <span class="text-[10px] text-slate-400">vs</span>
              <span class="rounded-full bg-rose-50 px-2.5 py-1 text-[10px] font-semibold text-rose-600 dark:bg-rose-500/10 dark:text-rose-400">{{ compareFileInfo?.filename }}</span>
            </div>
          </div>
        </div>

        <!-- No Data Source State (project has no uploaded files yet) -->
        <div v-else-if="isDashboardProject && noFileState" class="flex h-full flex-1 items-center justify-center">
          <div class="max-w-sm text-center">
            <div class="mx-auto mb-6 flex h-24 w-24 items-center justify-center rounded-3xl bg-gradient-to-br from-indigo-50 to-violet-50 dark:from-indigo-900/30 dark:to-violet-900/20">
              <svg class="h-12 w-12 text-indigo-300 dark:text-indigo-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
              </svg>
            </div>
            <h3 class="mb-2 text-xl font-semibold text-slate-800 dark:text-slate-200">Upload a data source</h3>
            <p class="mb-8 text-sm text-slate-500 dark:text-slate-400">This dashboard needs at least one file to generate charts, KPIs, and insights.</p>
            <button @click="triggerDataSourceUpload"
              class="rounded-2xl bg-gradient-to-r from-indigo-600 to-violet-600 px-8 py-3 text-sm font-medium text-white shadow-lg shadow-indigo-500/20 transition hover:shadow-xl hover:shadow-indigo-500/30 active:scale-[0.98]">
              + Upload Data Source
            </button>
            <input type="file" ref="dataSourceFileInput" class="hidden" accept=".csv,.xlsx,.xls" @change="handleDataSourceUpload" />
          </div>
        </div>

        <!-- Empty State -->
        <div v-else-if="!widgets.length && !hasPendingTemplatePreview" class="flex h-full flex-1 items-center justify-center">
          <div class="max-w-md text-center">
            <div class="mx-auto mb-6 flex h-24 w-24 items-center justify-center rounded-3xl bg-gradient-to-br from-indigo-50 to-violet-50 dark:from-indigo-900/30 dark:to-violet-900/20">
              <svg class="h-12 w-12 text-indigo-300 dark:text-indigo-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1" d="M4 5a1 1 0 011-1h4a1 1 0 011 1v5a1 1 0 01-1 1H5a1 1 0 01-1-1V5zM14 5a1 1 0 011-1h4a1 1 0 011 1v3a1 1 0 01-1 1h-4a1 1 0 01-1-1V5zM4 15a1 1 0 011-1h4a1 1 0 011 1v4a1 1 0 01-1 1H5a1 1 0 01-1-1v-4zM14 13a1 1 0 011-1h4a1 1 0 011 1v6a1 1 0 01-1 1h-4a1 1 0 01-1-1v-6z" />
              </svg>
            </div>
            <h3 class="mb-2 text-xl font-semibold text-slate-800 dark:text-slate-200">{{ isCurrentScreenPendingGeneration ? 'Generate This Screen For Selected File' : 'Canvas is empty' }}</h3>
            <p class="mb-1 text-sm text-slate-500 dark:text-slate-400">
              {{ isCurrentScreenPendingGeneration ? 'This screen has a saved template. Generate this file\'s dashboard into the same screen template.' : 'Your dashboard canvas is ready' }}
            </p>
            <p class="mb-8 text-xs text-slate-400 dark:text-slate-500">
              {{ isCurrentScreenPendingGeneration ? 'Only this screen will generate now. Other screens remain unchanged until generated.' : 'Generate AI-powered charts, KPIs, and insights from your data' }}
            </p>
            <button @click="isCurrentScreenPendingGeneration ? generatePendingScreenDashboard() : loadDashboard(true)"
              :disabled="isGeneratingPendingScreen"
              class="rounded-2xl bg-gradient-to-r from-indigo-600 to-violet-600 px-8 py-3 text-sm font-medium text-white shadow-lg shadow-indigo-500/20 transition hover:shadow-xl hover:shadow-indigo-500/30 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-60 dark:from-indigo-500 dark:to-violet-500">
              {{ isCurrentScreenPendingGeneration ? (isGeneratingPendingScreen ? 'Generating Screen…' : 'Generate This Screen') : 'Generate Dashboard' }}
            </button>
          </div>
        </div>

        <!-- ══════════════════════════════════════════════════════════ -->
        <!-- PRIMARY PANEL (always shown)                              -->
        <!-- ══════════════════════════════════════════════════════════ -->
        <div v-else :class="[isCompareMode && compareViewMode === 'split' ? 'flex flex-1 flex-col overflow-hidden border-r-2 border-indigo-200/60 dark:border-indigo-500/20' : '', 'relative']">
          <!-- Primary file badge (compare split mode only) -->
          <div v-if="isCompareMode && compareViewMode === 'split'" class="compare-badge-primary flex shrink-0 items-center gap-2 border-b border-indigo-100/60 bg-indigo-50/50 px-4 py-1.5 dark:border-indigo-500/10 dark:bg-indigo-500/5">
            <span class="h-2 w-2 rounded-full bg-indigo-500" />
            <span class="text-[11px] font-semibold text-indigo-700 dark:text-indigo-300">Base: {{ fileInfo?.filename || 'Primary' }}</span>
            <span class="text-[10px] text-indigo-400 dark:text-indigo-500">{{ (fileInfo?.total_rows || dashboardData?.total_rows || 0).toLocaleString() }} rows</span>
          </div>
          <!-- Unified comparison banner -->
          <div v-if="isCompareMode && compareViewMode === 'unified'" class="flex shrink-0 items-center gap-3 border-b border-violet-200/60 bg-gradient-to-r from-indigo-50/80 to-violet-50/80 px-5 py-2 dark:border-violet-500/15 dark:from-indigo-500/5 dark:to-violet-500/5">
            <svg class="h-4 w-4 text-violet-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/></svg>
            <span class="text-[11px] font-semibold text-violet-700 dark:text-violet-300">Unified Comparison</span>
            <span class="rounded-full bg-indigo-100 px-2 py-0.5 text-[10px] font-medium text-indigo-600 dark:bg-indigo-500/15 dark:text-indigo-300">{{ fileInfo?.filename }}</span>
            <span class="text-[10px] text-slate-400">vs</span>
            <span class="rounded-full bg-rose-100 px-2 py-0.5 text-[10px] font-medium text-rose-600 dark:bg-rose-500/15 dark:text-rose-300">{{ compareFileInfo?.filename }}</span>
          </div>
          <!-- Primary GridStack -->
          <div :class="[isCompareMode ? 'flex-1 overflow-auto' : '', 'relative']">
            <div v-if="hasPendingTemplatePreview"
              class="pointer-events-none absolute inset-0 z-20 flex items-center justify-center bg-white/45 backdrop-blur-[1px] dark:bg-slate-900/45">
              <div class="pointer-events-auto max-w-md rounded-2xl border border-indigo-200/70 bg-white/95 px-6 py-5 text-center shadow-xl dark:border-indigo-500/25 dark:bg-slate-900/95">
                <h3 class="mb-2 text-lg font-semibold text-slate-800 dark:text-slate-200">Generate This Screen For Selected File</h3>
                <p class="mb-1 text-sm text-slate-500 dark:text-slate-400">Using this screen template, KPIs and charts will be regenerated for the selected file.</p>
                <p class="mb-5 text-xs text-slate-400 dark:text-slate-500">Only this screen will generate now. Other screens remain unchanged until generated.</p>
                <button @click="generatePendingScreenDashboard()"
                  :disabled="isGeneratingPendingScreen"
                  class="rounded-2xl bg-gradient-to-r from-indigo-600 to-violet-600 px-6 py-2.5 text-sm font-medium text-white shadow-lg shadow-indigo-500/20 transition hover:shadow-xl hover:shadow-indigo-500/30 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-60 dark:from-indigo-500 dark:to-violet-500">
                  {{ isGeneratingPendingScreen ? 'Generating Screen…' : 'Generate This Screen' }}
                </button>
              </div>
            </div>
            <div ref="gridContainer" :style="{ zoom: canvasZoom / 100 }" :class="['grid-stack px-3 py-4', canvasDesignClass, { 'static-grid': isDashboardLocked }]">
              <div v-for="(widget, widgetIndex) in sortedWidgets" :key="widget.id" class="grid-stack-item"
                :gs-id="widget.id"
                :gs-x="(widget as any).gridX"
                :gs-y="(widget as any).gridY"
                :gs-auto-position="(widget as any).gridX == null ? 'true' : undefined"
                :gs-w="widget.gridW"
                :gs-h="widget.gridH"
                :gs-min-w="(widget as any).type === 'summary' ? 12 : (widget as any).type === 'chart' ? 4 : (widget as any).type === 'list' ? 3 : 3"
                :gs-min-h="(widget as any).type === 'summary' ? 2 : (widget as any).type === 'kpi' ? 2 : (widget as any).type === 'chart' ? 3 : (widget as any).type === 'insight' ? 2 : 2">

                <div class="widget-card group relative flex flex-col h-full min-h-[80px] overflow-hidden rounded-xl border border-slate-200/80 bg-white dark:bg-slate-900 dark:border-white/[0.08] shadow-[0_1px_4px_rgba(0,0,0,0.07)] transition-shadow duration-200 hover:shadow-[0_2px_8px_rgba(0,0,0,0.1)]"
                  @click.stop="selectWidget(widget.id, $event)"
                  :class="[
                    getWidgetVisualClasses(widget),
                    {
                      'bg-gradient-to-r from-indigo-50/80 via-white to-violet-50/60 dark:from-indigo-950/30 dark:via-slate-900 dark:to-violet-950/20': (widget as any).type === 'summary' && !resolveWidgetColor(widget),
                      'widget-selected': activeWidgetId === widget.id,
                    }
                  ]"
                  :style="getWidgetCardStyle(widget)">
                  <div v-if="isLoading || isAddingWidget" class="absolute top-3 right-3 h-2 w-2 rounded-full bg-emerald-400 z-10 animate-pulse-ring" />

                  <!-- Widget Header -->
                  <div class="flex items-center gap-2 border-b"
                    :class="(widget as any).type === 'summary' ? 'px-5 py-2 border-indigo-100/80 dark:border-indigo-500/15'
                      : (widget as any).type === 'kpi' ? 'px-4 py-1.5 border-slate-200/60 dark:border-white/[0.06]'
                      : 'px-4 py-2 border-slate-200/60 dark:border-white/[0.06]'">
                    <span v-if="!isDashboardLocked" class="widget-drag-handle cursor-grab active:cursor-grabbing select-none text-xs text-slate-300 opacity-0 transition group-hover:opacity-100">⋮⋮</span>
                    <span v-if="(widget as any).type !== 'kpi' && (widget as any).type !== 'summary'" :class="['inline-flex shrink-0 items-center rounded-md px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider', getWidgetTheme(widget, widgetIndex).bg, getWidgetTheme(widget, widgetIndex).text]">
                      {{ (widget as any).type === 'chart' ? ((widget as any).chartType || 'chart') : (widget as any).type }}
                    </span>
                    <svg v-if="(widget as any).type === 'summary'" class="h-4 w-4 shrink-0 text-indigo-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" /></svg>
                    <h3 v-if="getWidgetTitle(widget)" class="flex-1 min-w-0 uppercase leading-snug break-words"
                      :class="getWidgetHeaderClass(widget)"
                      :title="widget.title">
                      {{ getWidgetTitle(widget) }}
                    </h3>
                    <button v-if="(widget as any).origin_query && isDashboardLocked" @click="drillThrough(widget)"
                      class="rounded p-1 text-slate-300 opacity-0 transition hover:bg-indigo-50 hover:text-indigo-500 group-hover:opacity-100 dark:hover:bg-indigo-500/10"
                      title="Drill through — ask AI for details">
                      <svg class="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 7l5 5m0 0l-5 5m5-5H6" /></svg>
                    </button>
                    <!-- Per-chart value filter button -->
                    <div v-if="(widget as any).type === 'chart' && (((widget as any).chartData?.labels?.length ?? 0) > 8 || ((widget as any).base_chartData && (widget as any).cmp_chartData))" class="relative">
                      <button @mousedown.stop @click="openChartFilter(widget.id, [...new Set([...((widget as any).base_chartData?.labels || (widget as any).chartData?.labels || []), ...((widget as any).cmp_chartData?.labels || [])])], $event)"
                        :class="['rounded p-1 transition opacity-0 group-hover:opacity-100',
                          chartFilters[widget.id] ? 'text-indigo-500 bg-indigo-50 dark:bg-indigo-500/15 opacity-100' : 'text-slate-300 hover:bg-slate-50 hover:text-slate-500 dark:hover:bg-white/5']"
                        title="Filter chart values">
                        <svg class="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 4a1 1 0 011-1h16a1 1 0 011 1v2.586a1 1 0 01-.293.707l-6.414 6.414a1 1 0 00-.293.707V17l-4 4v-6.586a1 1 0 00-.293-.707L3.293 7.293A1 1 0 013 6.586V4z"/>
                        </svg>
                      </button>
                      <!-- Filter Popover -->
                      <Teleport to="body">
                        <Transition name="fab-pop">
                          <div v-if="openChartFilterId === widget.id" @mousedown.stop
                            :style="{ position: 'fixed', top: chartFilterPos.top != null ? chartFilterPos.top + 'px' : undefined, bottom: chartFilterPos.bottom != null ? chartFilterPos.bottom + 'px' : undefined, right: chartFilterPos.right + 'px' }"
                            class="z-[9999] w-64 rounded-xl border border-slate-200/80 bg-white shadow-xl dark:border-white/10 dark:bg-slate-900">
                          <!-- Header -->
                          <div class="flex items-center justify-between border-b border-slate-100 px-3 py-2 dark:border-white/5">
                            <span class="text-[10px] font-bold uppercase tracking-widest text-slate-500">Filter Values</span>
                            <button @click="clearChartFilter(widget.id, (widget as any).chartData?.labels || [])" class="text-[10px] text-rose-400 transition hover:text-rose-600">Reset (Show All)</button>
                          </div>
                          <div class="flex gap-1.5 border-b border-slate-100 px-3 py-2 dark:border-white/5">
                            <button v-for="n in [10, 20]" :key="n"
                              @click="chartFilterDraft = getTopNSortedLabels((widget as any).chartData?.labels || [], (widget as any).chartData?.series || [], n)"
                              class="rounded-md border border-slate-200 px-2 py-0.5 text-[10px] font-medium text-slate-500 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-400">
                              Top {{ n }}
                            </button>
                            <button @click="chartFilterDraft = [...((widget as any).chartData?.labels || [])]"
                              class="rounded-md border border-slate-200 px-2 py-0.5 text-[10px] font-medium text-slate-500 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-400">
                              All
                            </button>
                          </div>
                          <!-- Search -->
                          <div class="px-3 pt-2">
                            <input v-model="chartFilterSearch" placeholder="Search…"
                              class="w-full rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs outline-none focus:border-indigo-400 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300" />
                          </div>
                          <!-- Checkbox list -->
                          <div class="max-h-44 overflow-y-auto px-3 py-1.5 scrollbar-thin">
                            <label v-for="lbl in ((widget as any).chartData?.labels || []).filter((l: string) => !chartFilterSearch || l.toLowerCase().includes(chartFilterSearch.toLowerCase()))"
                              :key="lbl" class="flex cursor-pointer items-center gap-2 rounded-md px-1 py-1 text-xs text-slate-600 hover:bg-slate-50 dark:text-slate-300 dark:hover:bg-white/5">
                              <input type="checkbox" :value="lbl" v-model="chartFilterDraft" class="rounded accent-indigo-500" />
                              <span class="flex-1 truncate">{{ lbl }}</span>
                            </label>
                          </div>
                          <!-- Apply button -->
                          <div class="border-t border-slate-100 px-3 py-2 dark:border-white/5">
                            <button @click="applyChartFilter(widget.id)"
                              :disabled="!chartFilterDraft.length"
                              class="w-full rounded-lg bg-indigo-600 py-1.5 text-xs font-semibold text-white transition hover:bg-indigo-700 disabled:opacity-40">
                              Apply ({{ chartFilterDraft.length }} selected)
                            </button>
                          </div>
                          </div>
                        </Transition>
                      </Teleport>
                    </div>
                    <!-- Per-widget color picker (board mode, unlocked) -->
                    <label v-if="isBoardMode && !isDashboardLocked"
                      class="relative rounded p-1 text-slate-300 opacity-0 transition hover:bg-indigo-50 hover:text-indigo-500 group-hover:opacity-100 cursor-pointer"
                      title="Widget color theme">
                      <span class="inline-block h-3.5 w-3.5 rounded-full border border-slate-200 dark:border-slate-600"
                        :style="{ backgroundColor: resolveWidgetColor(widget) || getWidgetTheme(widget, widgetIndex).chart[0] }" />
                      <input type="color" class="absolute inset-0 h-full w-full cursor-pointer opacity-0"
                        :value="resolveWidgetColor(widget) || getWidgetTheme(widget, widgetIndex).chart[0]"
                        @input="setWidgetColor(widget.id, ($event.target as HTMLInputElement).value)" />
                    </label>
                    <button v-if="isBoardMode && !isDashboardLocked && resolveWidgetColor(widget)"
                      @click="clearWidgetColor(widget.id)"
                      class="rounded p-1 text-slate-300 opacity-0 transition hover:bg-amber-50 hover:text-amber-600 group-hover:opacity-100"
                      title="Clear widget color">
                      <iconify-icon icon="lucide:eraser" class="h-3.5 w-3.5" />
                    </button>
                    <button v-if="!isDashboardLocked && canMutateWidgets" @click="removeWidget(widget.id)"
                      class="rounded p-1 text-slate-300 opacity-0 transition hover:bg-red-50 hover:text-red-500 group-hover:opacity-100">
                      <svg class="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" /></svg>
                    </button>
                  </div>

                  <!-- Widget Body -->
                  <div class="flex flex-1 flex-col overflow-hidden min-h-0 scrollbar-thin relative"
                    :class="{
                      'px-5 py-3': (widget as any).type === 'summary',
                      'px-4 py-3': (widget as any).type === 'kpi' || (widget as any).type === 'insight',
                      'pt-1 pb-3 px-2': (widget as any).type === 'list',
                      'p-2 pt-1': (widget as any).type === 'chart',
                      'bg-[linear-gradient(180deg,rgba(99,102,241,0.18)_0%,rgba(99,102,241,0.07)_100%)]': (widget as any).ui?.banding,
                    }">

                    <!-- Per-widget loading overlay (Phase 5) -->
                    <div v-if="(widget as any).isLoadingData"
                      class="absolute inset-0 z-20 flex items-center justify-center rounded-b-xl bg-white/80 dark:bg-slate-900/80 backdrop-blur-[2px]">
                      <div class="flex flex-col items-center gap-2">
                        <div class="relative h-8 w-8">
                          <div class="absolute inset-0 animate-spin rounded-full border-2 border-indigo-100 border-t-indigo-500 dark:border-indigo-900 dark:border-t-indigo-400" />
                        </div>
                        <span class="text-[10px] font-medium text-slate-400 dark:text-slate-500">Loading data…</span>
                      </div>
                    </div>

                    <!-- ═══ SUMMARY ═══ -->
                    <div v-if="(widget as any).type === 'summary'" :class="['flex flex-1 flex-col gap-3', getWidgetAlignClass(widget)]">
                      <!-- Unified comparison summary with metric cards -->
                      <div v-if="(widget as any).metric_summaries?.length" class="flex flex-col gap-2.5">
                        <div class="flex items-center gap-3">
                          <div class="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-indigo-500 to-violet-500">
                            <svg class="h-4.5 w-4.5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" /></svg>
                          </div>
                          <div class="flex-1">
                            <p class="text-sm font-medium text-slate-700 dark:text-slate-200">{{ (widget as any).text }}</p>
                          </div>
                          <!-- Row comparison pills -->
                          <div v-if="(widget as any).base_rows" class="hidden items-center gap-2 lg:flex">
                            <span class="rounded-full bg-indigo-50 px-2.5 py-1 text-[10px] font-semibold text-indigo-600 dark:bg-indigo-500/10 dark:text-indigo-400">
                              {{ (widget as any).base_label }}: {{ Number((widget as any).base_rows).toLocaleString() }} rows
                            </span>
                            <span class="rounded-full bg-rose-50 px-2.5 py-1 text-[10px] font-semibold text-rose-600 dark:bg-rose-500/10 dark:text-rose-400">
                              {{ (widget as any).compare_label }}: {{ Number((widget as any).compare_rows).toLocaleString() }} rows
                            </span>
                            <span v-if="(widget as any).row_delta != null"
                              :class="['rounded-full px-2 py-1 text-[10px] font-bold',
                                (widget as any).row_delta > 0 ? 'bg-emerald-50 text-emerald-600 dark:bg-emerald-500/10 dark:text-emerald-400'
                                : (widget as any).row_delta < 0 ? 'bg-rose-50 text-rose-600 dark:bg-rose-500/10 dark:text-rose-400'
                                : 'bg-slate-100 text-slate-500 dark:bg-slate-700 dark:text-slate-400']">
                              {{ (widget as any).row_delta > 0 ? '+' : '' }}{{ Number((widget as any).row_delta).toFixed(1) }}%
                            </span>
                          </div>
                        </div>
                        <!-- Metric delta mini-cards -->
                        <div class="flex flex-wrap gap-2 pl-12">
                          <div v-for="(m, mi) in (widget as any).metric_summaries" :key="mi"
                            class="flex items-center gap-2 rounded-lg border border-slate-100 bg-slate-50/50 px-3 py-1.5 dark:border-slate-700/50 dark:bg-slate-800/30">
                            <span class="text-[11px] font-medium text-slate-500 dark:text-slate-400">{{ m.name }}</span>
                            <span class="text-[11px] font-bold text-indigo-600 dark:text-indigo-400 tabular-nums">{{ m.base }}</span>
                            <span class="text-[10px] text-slate-400">vs</span>
                            <span class="text-[11px] font-bold text-rose-600 dark:text-rose-400 tabular-nums">{{ m.compare }}</span>
                            <span v-if="m.delta != null"
                              :class="['text-[10px] font-bold',
                                m.delta > 0 ? 'text-emerald-500' : m.delta < 0 ? 'text-rose-500' : 'text-slate-400']">
                              {{ m.delta > 0 ? '+' : '' }}{{ Number(m.delta).toFixed(1) }}%
                            </span>
                          </div>
                        </div>
                      </div>
                      <!-- Standard summary (non-compare) -->
                      <div v-else :class="[
                        'flex items-center gap-4',
                        (widget as any).ui?.widgetVariant === 'card' ? 'rounded-xl border border-slate-200/70 p-3 dark:border-slate-700/70' : '',
                        (widget as any).ui?.widgetVariant === 'compact' ? 'gap-2' : '',
                        (widget as any).ui?.widgetVariant === 'minimal' ? 'opacity-90' : ''
                      ]">
                        <div class="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl"
                          :class="resolveWidgetColor(widget) ? '' : 'bg-indigo-100 dark:bg-indigo-500/15'"
                          :style="resolveWidgetColor(widget) ? { backgroundColor: resolveWidgetColor(widget) + '4d' } : {}">
                          <svg class="h-5 w-5" :class="resolveWidgetColor(widget) ? '' : 'text-indigo-600 dark:text-indigo-400'" :style="resolveWidgetColor(widget) ? { color: resolveWidgetColor(widget) } : {}" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" /></svg>
                        </div>
                        <div class="flex-1 space-y-2">
                          <div v-if="getSummaryBadgeText(widget) || shouldShowSummaryDate(widget)" class="flex flex-wrap items-center gap-2">
                            <span v-if="getSummaryBadgeText(widget)" class="inline-flex items-center rounded-full bg-indigo-50 px-2 py-0.5 text-[10px] font-semibold text-indigo-600 dark:bg-indigo-500/10 dark:text-indigo-300">
                              {{ getSummaryBadgeText(widget) }}
                            </span>
                            <span v-if="shouldShowSummaryDate(widget)" class="text-[10px] font-medium text-slate-400 dark:text-slate-500">
                              Updated {{ lastUpdated }}
                            </span>
                          </div>
                          <p class="text-sm leading-relaxed text-slate-600 dark:text-slate-300">{{ (widget as any).text ?? 'No summary available' }}</p>
                          <p v-if="getSummarySubtitle(widget)" class="text-xs text-slate-500 dark:text-slate-400">{{ getSummarySubtitle(widget) }}</p>
                        </div>
                      </div>
                    </div>

                    <!-- ═══ KPI ═══ -->
                    <div v-else-if="(widget as any).type === 'kpi'" :class="[
                      'flex flex-1 flex-col justify-center gap-1',
                      getWidgetAlignClass(widget),
                      (widget as any).ui?.kpiVariant === 'minimal' ? 'gap-0.5' : '',
                      (widget as any).ui?.kpiVariant === 'comparison' ? 'rounded-lg border border-slate-200/70 px-3 py-2 dark:border-slate-700/70' : ''
                    ]">
                      <!-- Primary value -->
                      <p class="font-extrabold tracking-tight text-slate-900 dark:text-white"
                        :class="String((widget as any).value || '').length > 12 ? 'text-lg' : String((widget as any).value || '').length > 8 ? 'text-2xl' : 'text-3xl'">
                        {{ getKpiDisplayValue(widget) }}
                      </p>

                      <!-- Unified compare: side-by-side file comparison -->
                      <template v-if="(widget as any).compare_value">
                        <!-- File labels + values row -->
                        <div class="mt-1 flex items-end gap-3">
                          <!-- Base file side -->
                          <div class="flex flex-col">
                            <span class="text-[9px] font-bold uppercase tracking-widest text-indigo-400 dark:text-indigo-500 truncate max-w-[80px]" :title="(widget as any).base_label">{{ (widget as any).base_label || 'Base' }}</span>
                            <span class="text-base font-bold text-slate-800 dark:text-slate-100 tabular-nums">{{ (widget as any).value ?? 'N/A' }}</span>
                          </div>
                          <!-- VS separator -->
                          <span class="mb-0.5 text-[10px] font-semibold text-slate-300 dark:text-slate-600">vs</span>
                          <!-- Compare file side -->
                          <div class="flex flex-col">
                            <span class="text-[9px] font-bold uppercase tracking-widest text-rose-400 dark:text-rose-500 truncate max-w-[80px]" :title="(widget as any).compare_label">{{ (widget as any).compare_label || 'Compare' }}</span>
                            <span class="text-base font-bold text-slate-600 dark:text-slate-300 tabular-nums">{{ (widget as any).compare_value }}</span>
                          </div>
                        </div>

                      </template>

                      <!-- Standard widget: trend subtitle -->
                      <div v-else class="mt-2 flex items-center gap-2">
                        <span v-if="(widget as any).trend && (widget as any).trend !== 'neutral'"
                          v-show="(widget as any).ui?.showTrend !== false"
                          :class="['inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[11px] font-medium', (widget as any).trend === 'positive' ? 'bg-emerald-50 text-emerald-600 dark:bg-emerald-500/10 dark:text-emerald-400' : 'bg-rose-50 text-rose-600 dark:bg-rose-500/10 dark:text-rose-400']">
                          {{ getTrendIcon((widget as any).trend) }} {{ (widget as any).subtitle || '' }}
                        </span>
                        <span v-else-if="(widget as any).subtitle" class="text-[11px] font-medium text-slate-400 dark:text-slate-500">{{ (widget as any).subtitle }}</span>
                      </div>

                      <div v-if="(widget as any).ui?.kpiVariant === 'sparkline'" class="mt-2 h-10 w-full rounded bg-slate-50 px-2 py-1 dark:bg-slate-800/60">
                        <svg viewBox="0 0 120 30" class="h-full w-full">
                          <polyline fill="none" :stroke="getWidgetPalette(widget)[0]" stroke-width="2" points="0,24 18,18 35,15 55,22 76,20 96,10 120,14" />
                        </svg>
                      </div>



                      <div v-if="(widget as any).ui?.kpiVariant === 'comparison' && !(widget as any).compare_value" class="mt-2 space-y-1">

                        <div class="flex items-center justify-between text-[10px] text-slate-500 dark:text-slate-400"><span>Current</span><span class="font-semibold">{{ getKpiDisplayValue(widget) }}</span></div>

                        <div class="h-1.5 w-full rounded-full bg-slate-100 dark:bg-slate-800"><div class="h-full w-2/3 rounded-full" :style="{ backgroundColor: getWidgetPalette(widget)[0] }" /></div>

                        <div class="flex items-center justify-between text-[10px] text-slate-500 dark:text-slate-400"><span>Previous</span><span class="font-semibold">{{ (widget as any).subtitle || 'N/A' }}</span></div>

                        <div class="h-1.5 w-full rounded-full bg-slate-100 dark:bg-slate-800"><div class="h-full w-1/2 rounded-full" :style="{ backgroundColor: getWidgetPalette(widget)[2] || getWidgetPalette(widget)[0] }" /></div>

                      </div>

                    </div>



                    <!-- ═══ INSIGHT ═══ -->

                    <div v-else-if="(widget as any).type === 'insight'" class="flex flex-1 flex-col overflow-y-auto scrollbar-thin">

                      <!-- Comparison insight badge -->

                      <div v-if="(widget as any).is_comparison" class="mb-2 flex items-center gap-2">

                        <span class="inline-flex items-center gap-1 rounded-full bg-violet-50 px-2 py-0.5 text-[10px] font-semibold text-violet-600 dark:bg-violet-500/10 dark:text-violet-400">

                          <svg class="h-3 w-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" /></svg>

                          Comparative Analysis

                        </span>

                        <span v-if="(widget as any).base_label" class="text-[10px] text-slate-400 dark:text-slate-500">

                          {{ (widget as any).base_label }} vs {{ (widget as any).compare_label }}

                        </span>

                      </div>

                      <div class="flex gap-3">

                        <div class="w-1 shrink-0 rounded-full" :style="resolveWidgetColor(widget)

                          ? `background: ${resolveWidgetColor(widget)}; opacity: 0.92;`

                          : (widget as any).is_comparison ? 'background: linear-gradient(180deg, #7c3aed 0%, #c084fc 100%); opacity: 0.7;' : 'background: linear-gradient(180deg, #6366f1 0%, #a5b4fc 100%); opacity: 0.6;'" />

                        <div class="flex flex-col justify-center gap-2">

                          <p class="text-[13px] leading-relaxed text-slate-600 dark:text-slate-300">{{ (widget as any).text ?? 'No insight available' }}</p>

                          <div v-if="(widget as any).highlight" class="flex items-center gap-2">

                            <span :class="['inline-flex items-center rounded-md px-2 py-0.5 text-[11px] font-semibold',

                              resolveWidgetColor(widget) ? '' :

                              (widget as any).is_comparison

                                ? 'bg-violet-50 text-violet-600 dark:bg-violet-500/10 dark:text-violet-400'

                                : 'bg-indigo-50 text-indigo-600 dark:bg-indigo-500/10 dark:text-indigo-400']"

                              :style="resolveWidgetColor(widget) ? { backgroundColor: resolveWidgetColor(widget) + '38', color: resolveWidgetColor(widget) } : {}">

                              {{ (widget as any).highlight }}

                            </span>

                          </div>

                        </div>

                      </div>

                    </div>



                    <!-- ═══ LIST ═══ -->

                    <div v-else-if="(widget as any).type === 'list'" class="flex-1 overflow-y-auto">

                      <!-- Unified list header (when items have compare_value) -->

                      <div v-if="(widget as any).base_label" class="flex items-center gap-4 px-3 pt-2 text-[10px] font-semibold uppercase tracking-wider text-slate-400 dark:text-slate-500">

                        <span class="flex-1" />

                        <span class="w-20 text-right">{{ (widget as any).base_label }}</span>

                        <span class="w-20 text-right">{{ (widget as any).compare_label }}</span>

                      </div>

                      <ul class="space-y-1 pt-2">

                        <li v-for="(item, i) in getVisibleListItems(widget) as any[]" :key="i"

                          :class="[

                            'group/item flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition hover:bg-slate-50 dark:hover:bg-white/[0.04]',

                            (widget as any).ui?.widgetVariant === 'compact' ? 'px-2 py-1.5 text-xs' : '',

                            (widget as any).ui?.widgetVariant === 'card' ? 'border border-slate-200/70 dark:border-slate-700/70 bg-white/70 dark:bg-slate-800/50' : '',

                            (widget as any).ui?.widgetVariant === 'minimal' ? 'rounded-none border-b border-slate-100 dark:border-slate-800' : ''

                          ]">

                          <span v-if="(widget as any).ui?.showRank !== false" class="flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-[11px] font-bold" :style="getListRankStyle(widget, i as number)">{{ (i as number) + 1 }}</span>

                          <div class="flex flex-1 items-center gap-2 overflow-hidden">

                            <span class="truncate text-slate-700 dark:text-slate-300">{{ item.label || item.name || item }}</span>

                            <div v-if="(widget as any).ui?.showBars !== false" class="ml-auto h-1.5 w-16 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">

                              <div class="h-full rounded-full" :style="{ width: `${Math.max(20, 100 - (i as number) * 12)}%`, backgroundColor: getListBarColor(widget, i as number) }" />

                            </div>

                          </div>

                          <div v-if="item.value" class="flex items-center gap-2">

                            <span class="text-xs font-semibold text-slate-600 dark:text-slate-300 tabular-nums">{{ item.value }}</span>

                            <span v-if="item.compare_value && item.compare_value !== '—'" class="text-[10px] text-slate-400 dark:text-slate-500 tabular-nums">vs {{ item.compare_value }}</span>

                          </div>

                        </li>

                      </ul>

                    </div>


                    <!-- ═══ ERD ═══ -->
                    <div v-else-if="(widget as any).type === 'erd'" class="relative flex min-h-[140px] flex-1 flex-col overflow-hidden">
                      <ERDWidget v-if="(widget as any).mermaid" :mermaidCode="(widget as any).mermaid" :id="widget.id" />
                      <div v-else class="flex flex-1 items-center justify-center p-4">
                        <span class="text-sm italic text-slate-400">ERD code pending...</span>
                      </div>
                    </div>

                    <!-- ═══ DATA CATALOG ═══ -->
                    <div v-else-if="(widget as any).type === 'data_catalog'" class="flex-1 overflow-y-auto scrollbar-thin">
                      <ul class="divide-y divide-slate-100 dark:divide-white/[0.04]">
                        <li v-for="(item, idx) in (widget as any).items || []" :key="idx"
                          class="flex flex-col gap-0.5 px-4 py-2.5 transition-colors hover:bg-slate-50/60 dark:hover:bg-white/[0.03]"
                          :class="{ 'bg-slate-50/30 dark:bg-white/[0.015]': Number(idx) % 2 === 0 }">
                          <div class="flex items-center justify-between gap-3">
                            <div class="flex items-center gap-2 min-w-0">
                              <svg class="h-3.5 w-3.5 shrink-0 text-indigo-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 10h18M3 14h18m-9-4v8m-7 0h14a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
                              </svg>
                              <span class="truncate text-sm font-semibold text-slate-800 dark:text-slate-200">{{ item.label }}</span>
                            </div>
                            <span class="shrink-0 text-xs font-medium tabular-nums text-slate-500 dark:text-slate-400">{{ item.value }}</span>
                          </div>
                          <p v-if="item.sublabel" class="pl-[22px] text-[11px] leading-relaxed text-slate-400 dark:text-slate-500 truncate" :title="item.sublabel">
                            {{ item.sublabel }}
                          </p>
                        </li>
                      </ul>
                    </div>

                    <!-- ═══ CHART ═══ -->
                    <div v-else-if="(widget as any).type === 'chart'" class="relative flex min-h-[140px] flex-1 flex-col overflow-hidden">
                      <div v-if="(widget as any).ui?.addButtons || (widget as any).ui?.addDropdowns || (widget as any).ui?.addKpis || (widget as any).ui?.addText" class="mb-1 flex flex-wrap items-center gap-1 px-1">
                        <span v-if="(widget as any).ui?.addButtons" class="rounded bg-indigo-50 px-1.5 py-0.5 text-[10px] font-semibold text-indigo-600 dark:bg-indigo-500/10 dark:text-indigo-300">Buttons</span>
                        <span v-if="(widget as any).ui?.addDropdowns" class="rounded bg-violet-50 px-1.5 py-0.5 text-[10px] font-semibold text-violet-600 dark:bg-violet-500/10 dark:text-violet-300">Dropdowns</span>
                        <span v-if="(widget as any).ui?.addKpis" class="rounded bg-emerald-50 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-600 dark:bg-emerald-500/10 dark:text-emerald-300">Mini KPI</span>
                        <span v-if="(widget as any).ui?.addText" class="rounded bg-amber-50 px-1.5 py-0.5 text-[10px] font-semibold text-amber-600 dark:bg-amber-500/10 dark:text-amber-300">Narrative</span>
                      </div>
                      <!-- Chart Description/Summary -->
                      <p v-if="(widget as any).description" class="px-2 pb-1 text-[11px] leading-snug text-slate-400 dark:text-slate-500 line-clamp-2">{{ (widget as any).description }}</p>
                      <div class="min-h-0 flex-1">
                        <VChart v-if="gridReady && ((widget as any).chartData || (widget as any).series)"
                          :key="'echart-' + widget.id + '-' + activeTheme + '-' + chartRenderEpoch + '-' + (widgetRenderVersions[widget.id] || 0)"
                          :option="getEChartOption(widget, widgetIndex)"
                          autoresize
                          class="h-full w-full"
                          @click="(params: any) => handleChartClick(widget, params)" />
                        <div v-else class="flex h-full items-center justify-center">
                          <div class="text-center">
                            <svg class="mx-auto h-8 w-8 text-slate-300 dark:text-slate-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 013 19.875v-6.75zM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V8.625zM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V4.125z" /></svg>
                            <p class="mt-2 text-xs text-slate-400">{{ gridReady ? 'No chart data' : 'Preparing chart...' }}</p>
                          </div>
                        </div>
                      </div>
                    </div>

                    <!-- ═══ FALLBACK ═══ -->
                    <div v-else class="flex flex-1 items-center justify-center text-sm text-slate-500">Unknown: {{ (widget as any).type }}</div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- ══════════════════════════════════════════════════════════ -->
        <!-- COMPARE PANEL (right side — only in split compare mode)   -->
        <!-- ══════════════════════════════════════════════════════════ -->
        <div v-if="isCompareMode && compareViewMode === 'split' && widgets.length && !isUnifiedLoading" :class="['flex flex-1 flex-col overflow-hidden', getCompareWidgetTheme().bg.split(' ')[0] + '/20']">
          <!-- Compare file badge -->
          <div :class="['compare-badge-compare flex shrink-0 items-center gap-2 border-b px-4 py-1.5', getCompareWidgetTheme().bg + '/60']">
            <span :class="['h-2 w-2 rounded-full', getCompareWidgetTheme().bg.replace('bg-', 'bg-').split(' ')[0]]" :style="{ backgroundColor: colorThemes[compareThemeKey]?.swatch }" />
            <span :class="['text-[11px] font-semibold', getCompareWidgetTheme().text]">Comparing: {{ compareFileInfo?.filename || 'Select a file' }}</span>
            <span v-if="compareFileInfo" class="text-[10px] text-slate-400 dark:text-slate-500">{{ (compareFileInfo.total_rows || 0).toLocaleString() }} rows</span>
            <button @click="exitCompareMode" class="ml-auto rounded-md p-0.5 text-slate-400 transition hover:bg-slate-100 hover:text-slate-600 dark:hover:bg-slate-700 dark:hover:text-slate-300" title="Close compare">
              <svg class="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" /></svg>
            </button>
          </div>

          <!-- Compare Loading Skeleton -->
          <div v-if="isCompareLoading" class="flex flex-1 items-center justify-center">
            <div class="text-center">
              <div class="mx-auto mb-4 h-10 w-10 animate-spin rounded-full border-4 border-slate-200" :style="{ borderTopColor: colorThemes[compareThemeKey]?.swatch || '#10b981' }" />
              <p :class="['text-sm font-medium', getCompareWidgetTheme().text]">Loading comparison…</p>
              <p class="mt-1 text-xs text-slate-400">Generating widgets for {{ compareFileInfo?.filename }}</p>
            </div>
          </div>

          <!-- Compare Load Error -->
          <div v-else-if="compareLoadError" class="flex flex-1 items-center justify-center">
            <div class="text-center max-w-xs">
              <svg class="mx-auto mb-3 h-10 w-10 text-rose-300" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M12 9v4m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" /></svg>
              <p class="text-sm font-medium text-slate-700 dark:text-slate-300">Compare load failed</p>
              <p class="mt-1 text-xs text-slate-400 break-words">{{ compareLoadError }}</p>
              <button @click="retryCompareLoad" class="mt-3 rounded-lg bg-indigo-600 px-4 py-1.5 text-xs font-medium text-white hover:bg-indigo-700">Retry</button>
            </div>
          </div>

          <!-- Compare Empty -->
          <div v-else-if="!compareWidgets.length" class="flex flex-1 items-center justify-center">
            <div class="text-center">
              <svg class="mx-auto h-12 w-12 text-slate-200 dark:text-slate-700" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1" d="M9 17V7m0 10a2 2 0 01-2 2H5a2 2 0 01-2-2V7a2 2 0 012-2h2a2 2 0 012 2m0 10a2 2 0 002 2h2a2 2 0 002-2M9 7a2 2 0 012-2h2a2 2 0 012 2" /></svg>
              <p :class="['mt-3 text-sm', getCompareWidgetTheme().text]">No comparison data</p>
            </div>
          </div>

          <!-- Compare GridStack -->
          <div v-else class="flex-1 overflow-auto">
            <div ref="gridContainerB" :style="{ zoom: canvasZoom / 100 }" :class="['grid-stack px-4 py-6', canvasDesignClass, { 'static-grid': isDashboardLocked }]">
              <div v-for="(widget, widgetIndex) in sortedCompareWidgets" :key="'cmp-' + widget.id" class="grid-stack-item"
                :gs-x="(widget as any).gridX"
                :gs-y="(widget as any).gridY"
                :gs-auto-position="(widget as any).gridX == null ? 'true' : undefined"
                :gs-w="widget.gridW"
                :gs-h="widget.gridH"
                :gs-min-w="(widget as any).type === 'summary' ? 12 : (widget as any).type === 'chart' ? 4 : 3"
                :gs-min-h="(widget as any).type === 'summary' ? 2 : (widget as any).type === 'kpi' ? 2 : (widget as any).type === 'chart' ? 3 : 2">

                <div class="widget-card group relative flex flex-col h-full min-h-[80px] overflow-hidden rounded-xl border border-slate-200/80 bg-white dark:bg-slate-900 dark:border-white/[0.08] shadow-[0_1px_4px_rgba(0,0,0,0.07)] transition-shadow duration-200 hover:shadow-[0_2px_8px_rgba(0,0,0,0.1)]"
                  :class="[
                    getWidgetVisualClasses(widget),
                    getCompareWidgetTheme().bg.replace(/bg-/g, 'border-').split(' ')[0] + '/60',
                    { 'bg-gradient-to-r from-slate-50/60 via-white to-slate-50/40 dark:from-slate-900 dark:via-slate-900 dark:to-slate-800/30': (widget as any).type === 'summary' }
                  ]">

                  <!-- Widget Header (compare side — dynamic compare theme accent) -->
                  <div class="flex items-center gap-2 border-b"
                    :class="(widget as any).type === 'summary' ? 'px-5 py-2 border-slate-200/70 dark:border-slate-700/40'
                      : (widget as any).type === 'kpi' ? 'px-4 py-1.5 border-slate-200/60 dark:border-white/[0.06]'
                      : 'px-4 py-2 border-slate-200/60 dark:border-white/[0.06]'">
                    <span v-if="(widget as any).type !== 'kpi' && (widget as any).type !== 'summary'"
                      :class="['inline-flex shrink-0 items-center rounded-md px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider', getCompareWidgetTheme().bg, getCompareWidgetTheme().text]">
                      {{ (widget as any).type === 'chart' ? ((widget as any).chartType || 'chart') : (widget as any).type }}
                    </span>
                    <svg v-if="(widget as any).type === 'summary'" :class="['h-4 w-4 shrink-0', getCompareWidgetTheme().text]" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" /></svg>
                    <h3 class="flex-1 min-w-0 uppercase leading-snug break-words"
                      :class="(widget as any).type === 'summary'
                        ? ['text-[11px] font-bold tracking-wider', getCompareWidgetTheme().text]
                        : (widget as any).type === 'kpi'
                          ? 'text-[10px] font-semibold tracking-wide text-slate-500 dark:text-slate-400'
                          : (widget as any).type === 'insight'
                            ? 'text-[10px] font-semibold tracking-wide text-slate-500 dark:text-slate-400'
                            : 'text-[10px] font-bold tracking-widest text-slate-400 dark:text-slate-500'"
                      :title="widget.title">
                      {{ widget.title }}
                    </h3>
                    <!-- Per-chart value filter button (compare panel) -->
                    <div v-if="(widget as any).type === 'chart' && ((widget as any).chartData?.labels?.length ?? 0) > 8" class="relative">
                      <button @mousedown.stop @click="openChartFilter(widget.id + '-cmp', (widget as any).chartData?.labels || [], $event)"
                        :class="['rounded p-1 transition opacity-0 group-hover:opacity-100',
                          chartFilters[widget.id + '-cmp'] ? 'text-violet-500 bg-violet-50 dark:bg-violet-500/15 opacity-100' : 'text-slate-300 hover:bg-slate-50 hover:text-slate-500 dark:hover:bg-white/5']"
                        title="Filter chart values">
                        <svg class="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 4a1 1 0 011-1h16a1 1 0 011 1v2.586a1 1 0 01-.293.707l-6.414 6.414a1 1 0 00-.293.707V17l-4 4v-6.586a1 1 0 00-.293-.707L3.293 7.293A1 1 0 013 6.586V4z"/>
                        </svg>
                      </button>
                      <!-- Filter Popover -->
                      <Teleport to="body">
                        <Transition name="fab-pop">
                          <div v-if="openChartFilterId === widget.id + '-cmp'" @mousedown.stop
                            :style="{ position: 'fixed', top: chartFilterPos.top != null ? chartFilterPos.top + 'px' : undefined, bottom: chartFilterPos.bottom != null ? chartFilterPos.bottom + 'px' : undefined, right: chartFilterPos.right + 'px' }"
                            class="z-[9999] w-64 rounded-xl border border-slate-200/80 bg-white shadow-xl dark:border-white/10 dark:bg-slate-900">
                          <div class="flex items-center justify-between border-b border-slate-100 px-3 py-2 dark:border-white/5">
                            <span class="text-[10px] font-bold uppercase tracking-widest text-slate-500">Filter Values</span>
                            <button @click="clearChartFilter(widget.id + '-cmp', (widget as any).chartData?.labels || [])" class="text-[10px] text-rose-400 transition hover:text-rose-600">Reset (Show All)</button>
                          </div>
                          <div class="flex gap-1.5 border-b border-slate-100 px-3 py-2 dark:border-white/5">
                            <button v-for="n in [10, 20]" :key="n"
                              @click="chartFilterDraft = getTopNSortedLabels((widget as any).chartData?.labels || [], (widget as any).chartData?.series || [], n)"
                              class="rounded-md border border-slate-200 px-2 py-0.5 text-[10px] font-medium text-slate-500 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-400">
                              Top {{ n }}
                            </button>
                            <button @click="chartFilterDraft = [...((widget as any).chartData?.labels || [])]"
                              class="rounded-md border border-slate-200 px-2 py-0.5 text-[10px] font-medium text-slate-500 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-400">
                              All
                            </button>
                          </div>
                          <div class="px-3 pt-2">
                            <input v-model="chartFilterSearch" placeholder="Search…"
                              class="w-full rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs outline-none focus:border-indigo-400 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300" />
                          </div>
                          <div class="max-h-44 overflow-y-auto px-3 py-1.5 scrollbar-thin">
                            <label v-for="lbl in ((widget as any).chartData?.labels || []).filter((l: string) => !chartFilterSearch || l.toLowerCase().includes(chartFilterSearch.toLowerCase()))"
                              :key="lbl" class="flex cursor-pointer items-center gap-2 rounded-md px-1 py-1 text-xs text-slate-600 hover:bg-slate-50 dark:text-slate-300 dark:hover:bg-white/5">
                              <input type="checkbox" :value="lbl" v-model="chartFilterDraft" class="rounded accent-violet-500" />
                              <span class="flex-1 truncate">{{ lbl }}</span>
                            </label>
                          </div>
                          <div class="border-t border-slate-100 px-3 py-2 dark:border-white/5">
                            <button @click="applyChartFilter(widget.id + '-cmp')"
                              :disabled="!chartFilterDraft.length"
                              class="w-full rounded-lg bg-violet-600 py-1.5 text-xs font-semibold text-white transition hover:bg-violet-700 disabled:opacity-40">
                              Apply ({{ chartFilterDraft.length }} selected)
                            </button>
                          </div>
                          </div>
                        </Transition>
                      </Teleport>
                    </div>
                    <span v-if="!isDashboardLocked" class="widget-drag-handle cursor-grab active:cursor-grabbing select-none text-xs text-violet-300 opacity-0 transition group-hover:opacity-100">⋮⋮</span>
                  </div>

                  <!-- Widget Body (compare side — reuses same body rendering) -->
                  <div class="flex flex-1 flex-col overflow-hidden min-h-0 scrollbar-thin"
                    :class="{
                      'px-5 py-3': (widget as any).type === 'summary',
                      'px-4 py-3': (widget as any).type === 'kpi' || (widget as any).type === 'insight',
                      'pt-1 pb-3 px-2': (widget as any).type === 'list',
                      'p-2 pt-1': (widget as any).type === 'chart',
                    }">

                    <div v-if="(widget as any).type === 'summary'" class="flex flex-1 items-center gap-4">
                      <div :class="['flex h-10 w-10 shrink-0 items-center justify-center rounded-xl', getCompareWidgetTheme().bg]">
                        <svg :class="['h-5 w-5', getCompareWidgetTheme().text]" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" /></svg>
                      </div>
                      <p class="flex-1 text-sm leading-relaxed text-slate-600 dark:text-slate-300">{{ (widget as any).text ?? 'No summary available' }}</p>
                    </div>

                    <div v-else-if="(widget as any).type === 'kpi'" class="flex flex-1 flex-col justify-center">
                      <p class="font-extrabold tracking-tight text-slate-900 dark:text-white"
                        :class="String((widget as any).value || '').length > 12 ? 'text-lg' : String((widget as any).value || '').length > 8 ? 'text-2xl' : 'text-3xl'">
                        {{ (widget as any).value ?? 'N/A' }}
                      </p>
                      <div class="mt-2 flex items-center gap-2">
                        <span v-if="(widget as any).trend && (widget as any).trend !== 'neutral'"
                          :class="['inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[11px] font-medium', (widget as any).trend === 'positive' ? 'bg-emerald-50 text-emerald-600 dark:bg-emerald-500/10 dark:text-emerald-400' : 'bg-rose-50 text-rose-600 dark:bg-rose-500/10 dark:text-rose-400']">
                          {{ getTrendIcon((widget as any).trend) }} {{ (widget as any).subtitle || '' }}
                        </span>
                        <span v-else-if="(widget as any).subtitle" class="text-[11px] font-medium text-slate-400 dark:text-slate-500">{{ (widget as any).subtitle }}</span>
                      </div>
                    </div>

                    <div v-else-if="(widget as any).type === 'insight'" class="flex flex-1 flex-col overflow-y-auto scrollbar-thin">
                      <div class="flex gap-3">
                        <div class="w-1 shrink-0 rounded-full" :style="{ background: `linear-gradient(180deg, ${compareChartColors[0]} 0%, ${compareChartColors[1] || compareChartColors[0]} 100%)`, opacity: 0.6 }" />
                        <div class="flex flex-col justify-center gap-2">
                          <p class="text-[13px] leading-relaxed text-slate-600 dark:text-slate-300">{{ (widget as any).text ?? 'No insight available' }}</p>
                          <div v-if="(widget as any).highlight" class="flex items-center gap-2">
                            <span :class="['inline-flex items-center rounded-md px-2 py-0.5 text-[11px] font-semibold', getCompareWidgetTheme().bg, getCompareWidgetTheme().text]">{{ (widget as any).highlight }}</span>
                          </div>
                        </div>
                      </div>
                    </div>

                    <div v-else-if="(widget as any).type === 'list'" class="flex-1 overflow-y-auto">
                      <ul class="space-y-1 pt-2">
                        <li v-for="(item, i) in ((widget as any).items || []) as any[]" :key="i"
                          class="group/item flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition hover:bg-violet-50/50 dark:hover:bg-white/[0.04]">
                          <span :class="['flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-[11px] font-bold',
                            (i as number) === 0 ? 'bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-400'
                            : (i as number) === 1 ? 'bg-slate-100 text-slate-500 dark:bg-slate-700 dark:text-slate-400'
                            : (i as number) === 2 ? 'bg-orange-50 text-orange-500 dark:bg-orange-500/10 dark:text-orange-400'
                            : 'bg-slate-50 text-slate-400 dark:bg-slate-800 dark:text-slate-500']">{{ (i as number) + 1 }}</span>
                          <span class="flex-1 truncate text-slate-700 dark:text-slate-300">{{ item.label || item.name || item }}</span>
                          <div v-if="item.value" class="flex items-center gap-2">
                            <span class="text-xs font-semibold text-slate-600 dark:text-slate-300 tabular-nums">{{ item.value }}</span>
                          </div>
                        </li>
                      </ul>
                    </div>

                    <div v-else-if="(widget as any).type === 'erd'" class="relative flex min-h-[140px] flex-1 flex-col overflow-hidden">
                      <ERDWidget v-if="(widget as any).mermaid" :mermaidCode="(widget as any).mermaid" :id="widget.id" />
                      <div v-else class="flex flex-1 items-center justify-center p-4">
                        <span class="text-sm italic text-slate-400">ERD code pending...</span>
                      </div>
                    </div>

                    <div v-else-if="(widget as any).type === 'chart'" class="relative flex min-h-[140px] flex-1 flex-col overflow-hidden">
                      <!-- Chart Description/Summary (compare side) -->
                      <p v-if="(widget as any).description" class="px-2 pb-1 text-[11px] leading-snug text-slate-400 dark:text-slate-500 line-clamp-2">{{ (widget as any).description }}</p>
                      <div class="min-h-0 flex-1">
                        <VChart v-if="gridBReady && ((widget as any).chartData || (widget as any).series)"
                          :key="'cmp-echart-' + widget.id + '-' + activeTheme + '-' + compareThemeKey + '-' + (widgetRenderVersions[widget.id] || 0)"
                          :option="getCompareEChartOption(widget, widgetIndex)"
                          autoresize
                          class="h-full w-full"
                          @click="(params: any) => handleCompareChartClick(widget, params)" />
                        <div v-else class="flex h-full items-center justify-center">
                          <div class="text-center">
                            <svg class="mx-auto h-8 w-8 text-slate-300 dark:text-slate-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 013 19.875v-6.75zM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V8.625zM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V4.125z" /></svg>
                            <p class="mt-2 text-xs text-slate-400">{{ gridBReady ? 'No chart data' : 'Preparing chart...' }}</p>
                          </div>
                        </div>
                      </div>
                    </div>

                    <div v-else class="flex flex-1 items-center justify-center text-sm text-slate-500">Unknown: {{ (widget as any).type }}</div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

      </div>

      <!-- Bottom Screens Tabs -->
      <div v-if="!isSharedMode" class="flex shrink-0 items-center gap-1 overflow-x-auto border-t border-slate-200/70 bg-white px-2 py-1 no-scrollbar dark:border-white/10 dark:bg-slate-900">
        <button v-for="screen in boardScreens" :key="screen.id"
          @click="activateScreen(screen.id)"
          :class="['inline-flex shrink-0 items-center gap-2 rounded-md border px-2.5 py-0.5 text-[11px] font-semibold transition', activeScreenId === screen.id ? 'border-emerald-500 bg-emerald-600 text-white' : 'border-slate-200 bg-slate-50 text-slate-600 hover:bg-slate-100 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700']">
          <span class="max-w-[180px] truncate">{{ screen.name }}</span>
        </button>
        <button @click="addBoardScreen"
          :disabled="!canMutateWidgets"
          :title="canMutateWidgets ? 'Add screen' : 'Only source file can create screens'"
          :class="['ml-1 inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md border transition', canMutateWidgets ? 'border-emerald-200 text-emerald-700 hover:bg-emerald-50 dark:border-emerald-500/30 dark:text-emerald-300 dark:hover:bg-emerald-500/10' : 'cursor-not-allowed border-slate-200 text-slate-400 dark:border-slate-700 dark:text-slate-500']">
          +
        </button>
      </div>
    </div>

    <WidgetFloatingToolbar
      :visible="widgetToolbarPos.visible && !!activeWidgetId && canMutateWidgets && !isPreviewMode"
      :top="widgetToolbarPos.top"
      :left="widgetToolbarPos.left"
      @duplicate="duplicateActiveWidget"
      @delete="activeWidgetId && removeWidget(activeWidgetId)"
    />

    <RightProperties
      :widget="isPreviewMode ? null : (activeWidget || null)"
      :widget-type-label="activeWidgetTypeLabel"
      :chart-dimensions="chartDimensionColumns"
      :chart-measures="chartMeasureColumns"
      @close="clearWidgetSelection"
      @update-title="updateSelectedWidgetTitle"
      @recompute-chart="recomputeActiveChart"
      @recompute-kpi="recomputeActiveKpi"
    />

    <!-- ── CHART BUILDER RIGHT SIDEBAR (Looker Studio style) ──────── -->
    <Transition name="chart-builder-slide">
      <aside v-if="chartBuilderOpen && canMutateWidgets"
        class="shrink-0 rounded-2xl border border-slate-200/70 dark:border-white/[0.08] bg-white/95 dark:bg-slate-900/90 backdrop-blur-sm flex flex-col h-full w-72 xl:w-80 overflow-hidden shadow-lg z-20">
        <!-- Header -->
        <div class="flex items-center justify-between px-3 pt-3 pb-2 border-b border-slate-100 dark:border-white/5">
          <div class="flex items-center gap-1.5">
            <iconify-icon icon="lucide:layout-template" class="h-4 w-4 text-violet-500 shrink-0" />
            <h2 class="font-semibold text-xs uppercase tracking-wide text-slate-600 dark:text-slate-400">Chart Builder</h2>
          </div>
          <button @click="chartBuilderOpen = false"
            class="h-6 w-6 flex items-center justify-center rounded text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 transition">
            <iconify-icon icon="lucide:x" class="h-3.5 w-3.5" />
          </button>
        </div>

        <!-- Loading schema -->
        <div v-if="!chartSchema" class="flex flex-1 items-center justify-center py-6">
          <div class="text-center">
            <div class="mx-auto mb-2 h-6 w-6 animate-spin rounded-full border-2 border-violet-200 border-t-violet-500" />
            <p class="text-xs text-slate-400">Loading columns…</p>
          </div>
        </div>

        <!-- Builder form -->
        <div v-else class="flex flex-1 flex-col gap-4 overflow-y-auto px-3 py-3">

          <!-- 1. Chart Type -->
          <div>
            <p class="mb-2 text-[10px] font-semibold uppercase tracking-widest text-slate-400 dark:text-slate-500">Chart Type</p>
            <div class="grid grid-cols-3 gap-1.5">
              <button v-for="ct in chartBuilderChartTypes" :key="ct.id"
                @click="chartBuilderForm.chartType = ct.id"
                :class="[
                  'flex flex-col items-center gap-1 rounded-lg border p-2 text-center transition',
                  chartBuilderForm.chartType === ct.id
                    ? 'border-violet-400 bg-violet-50 text-violet-700 dark:border-violet-500/60 dark:bg-violet-500/10 dark:text-violet-300'
                    : 'border-slate-200 text-slate-500 hover:border-slate-300 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-400 dark:hover:bg-slate-800',
                ]">
                <iconify-icon :icon="ct.icon" class="h-4 w-4 shrink-0" />
                <span class="text-[10px] font-medium leading-none">{{ ct.label }}</span>
              </button>
            </div>
          </div>

          <!-- Divider -->
          <div class="h-px bg-slate-100 dark:bg-white/5" />

          <!-- 2. Dimension (Qualitative) -->
          <div>
            <p class="mb-1.5 text-[10px] font-semibold uppercase tracking-widest text-slate-400 dark:text-slate-500">
              <span class="inline-flex items-center gap-1">
                <iconify-icon icon="lucide:tag" class="h-3 w-3 text-indigo-400" />
                Dimension <span class="normal-case font-normal text-slate-300 dark:text-slate-600">(Qualitative)</span>
              </span>
            </p>
            <select v-model="chartBuilderForm.dimension"
              class="w-full rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1.5 text-xs text-slate-700 outline-none transition focus:border-indigo-400 focus:ring-2 focus:ring-indigo-300/30 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300">
              <option value="" disabled>Select a column…</option>
              <option v-for="d in chartSchema.dimensions" :key="d.col" :value="d.col">
                {{ d.col }} <template v-if="d.cardinality">({{ d.cardinality }} unique)</template>
              </option>
            </select>
            <p v-if="chartBuilderForm.dimension" class="mt-1 text-[10px] text-slate-400">
              X-axis / category grouping
            </p>
          </div>

          <!-- 3. Aggregation -->
          <div>
            <p class="mb-1.5 text-[10px] font-semibold uppercase tracking-widest text-slate-400 dark:text-slate-500">
              <span class="inline-flex items-center gap-1">
                <iconify-icon icon="lucide:sigma" class="h-3 w-3 text-amber-400" />
                Aggregation
              </span>
            </p>
            <div class="flex gap-1">
              <button v-for="agg in ['sum', 'mean', 'count']" :key="agg"
                @click="chartBuilderForm.aggregation = agg"
                :class="[
                  'flex-1 rounded-md border py-1 text-[11px] font-medium transition capitalize',
                  chartBuilderForm.aggregation === agg
                    ? 'border-amber-400 bg-amber-50 text-amber-700 dark:border-amber-500/50 dark:bg-amber-500/10 dark:text-amber-300'
                    : 'border-slate-200 text-slate-500 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-400 dark:hover:bg-slate-800',
                ]">
                {{ agg === 'mean' ? 'Avg' : agg }}
              </button>
            </div>
          </div>

          <!-- 4. Measure (Quantitative) — hidden for count -->
          <div v-if="chartBuilderForm.aggregation !== 'count'">
            <p class="mb-1.5 text-[10px] font-semibold uppercase tracking-widest text-slate-400 dark:text-slate-500">
              <span class="inline-flex items-center gap-1">
                <iconify-icon icon="lucide:hash" class="h-3 w-3 text-emerald-400" />
                Measure <span class="normal-case font-normal text-slate-300 dark:text-slate-600">(Quantitative)</span>
              </span>
            </p>
            <select v-model="chartBuilderForm.measure"
              class="w-full rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1.5 text-xs text-slate-700 outline-none transition focus:border-emerald-400 focus:ring-2 focus:ring-emerald-300/30 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300">
              <option value="" disabled>Select a column…</option>
              <option v-for="m in chartSchema.measures" :key="m.col" :value="m.col">{{ m.col }}</option>
            </select>
            <p v-if="chartBuilderForm.measure" class="mt-1 text-[10px] text-slate-400">
              Y-axis / numeric value
            </p>
          </div>
          <div v-else class="rounded-lg border border-dashed border-slate-200 dark:border-slate-700 px-3 py-2 text-[10px] text-slate-400 dark:text-slate-500 text-center">
            Counting rows by <strong>{{ chartBuilderForm.dimension || 'dimension' }}</strong>
          </div>

          <!-- Divider -->
          <div class="h-px bg-slate-100 dark:bg-white/5" />

          <!-- Preview summary -->
          <div v-if="chartBuilderForm.dimension" class="rounded-xl border border-violet-100 bg-violet-50/60 dark:border-violet-500/20 dark:bg-violet-500/5 px-3 py-2.5">
            <p class="text-[10px] font-semibold text-violet-600 dark:text-violet-400 mb-1">Preview</p>
            <p class="text-[11px] text-slate-600 dark:text-slate-300 leading-snug">
              <span class="font-medium capitalize">{{ chartBuilderForm.chartType }}</span> chart of
              <span class="font-medium">
                <template v-if="chartBuilderForm.aggregation === 'count'">count</template>
                <template v-else>{{ chartBuilderForm.aggregation }} of {{ chartBuilderForm.measure || '…' }}</template>
              </span>
              by <span class="font-medium">{{ chartBuilderForm.dimension }}</span>
            </p>
          </div>

          <!-- Add Chart button -->
          <button @click="buildCustomChart()"
            :disabled="!chartBuilderForm.dimension || (chartBuilderForm.aggregation !== 'count' && !chartBuilderForm.measure) || chartBuilderLoading || (isBoardMode && !isTemplateSourceActive)"
            class="w-full rounded-xl bg-gradient-to-r from-violet-600 to-indigo-600 px-3 py-2.5 text-xs font-semibold text-white shadow-sm transition hover:from-violet-700 hover:to-indigo-700 active:scale-[0.98] disabled:opacity-40 disabled:cursor-not-allowed">
            <span v-if="chartBuilderLoading" class="flex items-center justify-center gap-2">
              <span class="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white/30 border-t-white" />
              Building…
            </span>
            <span v-else class="flex items-center justify-center gap-1.5">
              <iconify-icon icon="lucide:plus-circle" class="h-3.5 w-3.5" />
              Add to Dashboard
            </span>
          </button>

          <!-- Quick examples -->
          <div>
            <p class="mb-2 text-[10px] font-semibold uppercase tracking-widest text-slate-400 dark:text-slate-500">Quick Examples</p>
            <div class="space-y-1">
              <button
                v-for="ex in [
                  { label: 'Category Distribution', chartType: 'pie', aggr: 'count', icon: '🍩' },
                  { label: 'Revenue by Region', chartType: 'bar', aggr: 'sum', icon: '📊' },
                  { label: 'Average by Group', chartType: 'line', aggr: 'mean', icon: '📈' },
                ]"
                :key="ex.label"
                @click="chartBuilderForm.chartType = ex.chartType; chartBuilderForm.aggregation = ex.aggr"
                class="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-[11px] text-slate-500 transition hover:bg-slate-50 dark:text-slate-400 dark:hover:bg-slate-800">
                <span>{{ ex.icon }}</span>
                <span>{{ ex.label }}</span>
              </button>
            </div>
          </div>
        </div>
      </aside>
    </Transition>

  </div>

  <!-- ── FLOATING AI ASSISTANT BUTTON + POPOVER ─────────────────── -->
  <div v-if="!isDashboardLocked && canMutateWidgets" ref="addPopoverRef" class="fixed bottom-6 right-6 z-50">
    <!-- Compact Popover -->
    <Transition name="fab-pop">
      <div v-if="showAddPopover"
        class="absolute bottom-16 right-0 w-72 rounded-2xl border border-slate-200/80 bg-white/98 p-4 shadow-2xl backdrop-blur-xl dark:border-white/10 dark:bg-slate-900/98">
        <div class="mb-3 flex items-center justify-between">
          <p class="text-xs font-semibold text-slate-700 dark:text-slate-300">Add Widget</p>
          <button @click="showAddPopover = false"
            class="rounded-md p-0.5 text-slate-400 transition hover:text-slate-600 dark:hover:text-slate-200">
            <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none"
              stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>
        <textarea v-model="newWidgetQuery" rows="2"
          placeholder="e.g. Bar chart of top categories…"
          class="w-full resize-none rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-900 placeholder-slate-400 outline-none transition focus:border-emerald-400 focus:ring-2 focus:ring-emerald-500/20 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
          @keydown.enter.ctrl="addCustomWidget" />
        <button @click="addCustomWidget" :disabled="!newWidgetQuery.trim() || isAddingWidget"
          class="mt-2 w-full rounded-xl bg-slate-900 px-3 py-2 text-xs font-semibold text-white shadow-sm transition hover:bg-slate-800 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-slate-200">
          {{ isAddingWidget ? 'Creating…' : '+ Add' }}
        </button>
        <div class="mt-3 flex flex-wrap gap-1.5">
          <button v-for="ex in [
            { q: 'Bar chart of top categories', icon: '📊' },
            { q: 'Distribution pie chart', icon: '🍩' },
            { q: 'Key KPI summary', icon: '💰' },
            { q: 'Top 5 items list', icon: '🏆' },
          ]" :key="ex.q"
            @click="newWidgetQuery = ex.q"
            class="rounded-lg border border-slate-200/60 px-2 py-1 text-[10px] text-slate-500 transition hover:border-emerald-300 hover:text-emerald-600 dark:border-slate-700 dark:text-slate-400 dark:hover:border-emerald-500 dark:hover:text-emerald-400">
            {{ ex.icon }} {{ ex.q }}
          </button>
        </div>
      </div>
    </Transition>

    <!-- FAB Button -->
    <button @click="toggleAddWidgetPopover()"
      class="fab-btn flex h-12 w-12 items-center justify-center rounded-full bg-gradient-to-br from-emerald-600 to-teal-600 text-white shadow-lg shadow-emerald-500/25 transition-all hover:scale-110 hover:shadow-xl hover:shadow-emerald-500/35 active:scale-95 dark:from-emerald-500 dark:to-teal-500 dark:shadow-emerald-500/15"
      title="Add widget">
      <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none"
        stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
        <path d="M12 3v18M3 12h18" v-if="!showAddPopover" />
        <path d="M18 6 6 18M6 6l12 12" v-else />
      </svg>
    </button>
  </div>
</template>

<style scoped>
/* Horizontal utility: keep controls on one line without visible scrollbar chrome. */
.no-scrollbar {
  -ms-overflow-style: none;
  scrollbar-width: none;
}

.no-scrollbar::-webkit-scrollbar {
  display: none;
}

/* ── PULSE ANIMATION (activity indicator) ─────────────────────── */
@keyframes pulse-ring {
  0%, 100% { opacity: 1; box-shadow: 0 0 0 0 rgba(52, 211, 153, 0.6); }
  50% { opacity: 0.6; box-shadow: 0 0 0 6px rgba(52, 211, 153, 0); }
}

.animate-pulse-ring {
  animation: pulse-ring 1.5s ease-in-out infinite;
}

/* ── WIDGET CARD POLISH ───────────────────────────────────────── */
.widget-card {
  border-radius: 12px;
  /* ensure cards sit clearly above the canvas background */
  background-clip: padding-box;
}

/* Widget personality by type + chart type */
.widget-card.widget-type-kpi {
  border-left: 3px solid var(--theme-shade-1);
}

.widget-card.widget-type-insight {
  border-left: 3px solid var(--theme-shade-3);
}

.widget-card.widget-type-list {
  border-left: 3px solid var(--theme-shade-4);
}

.widget-card.widget-type-chart.chart-type-line,
.widget-card.widget-type-chart.chart-type-area {
  border-top: 2px solid var(--theme-shade-2);
}

.widget-card.widget-type-chart.chart-type-bar,
.widget-card.widget-type-chart.chart-type-histogram,
.widget-card.widget-type-chart.chart-type-waterfall {
  border-top: 2px solid var(--theme-shade-3);
}

.widget-card.widget-type-chart.chart-type-pie,
.widget-card.widget-type-chart.chart-type-donut,
.widget-card.widget-type-chart.chart-type-treemap {
  border-top: 2px solid var(--theme-shade-4);
}

.widget-card.widget-type-chart.chart-type-scatter,
.widget-card.widget-type-chart.chart-type-bubble,
.widget-card.widget-type-chart.chart-type-heatmap {
  border-top: 2px solid var(--theme-shade-5);
}

/* Canvas design controls */
.grid-stack.design-texture-dots {
  background-image: radial-gradient(rgba(15, 23, 42, 0.09) 1px, transparent 1px);
  background-size: 18px 18px;
}

.grid-stack.design-texture-grid {
  background-image:
    linear-gradient(rgba(15, 23, 42, 0.08) 1px, transparent 1px),
    linear-gradient(90deg, rgba(15, 23, 42, 0.08) 1px, transparent 1px);
  background-size: 24px 24px;
}

.grid-stack.design-texture-gradient {
  background-image: linear-gradient(135deg, rgba(99, 102, 241, 0.1) 0%, rgba(16, 185, 129, 0.08) 45%, rgba(245, 158, 11, 0.08) 100%);
}

.dark .grid-stack.design-texture-dots {
  background-image: radial-gradient(rgba(148, 163, 184, 0.2) 1px, transparent 1px);
}

.dark .grid-stack.design-texture-grid {
  background-image:
    linear-gradient(rgba(148, 163, 184, 0.18) 1px, transparent 1px),
    linear-gradient(90deg, rgba(148, 163, 184, 0.18) 1px, transparent 1px);
}

.dark .grid-stack.design-texture-gradient {
  background-image: linear-gradient(135deg, rgba(99, 102, 241, 0.14) 0%, rgba(16, 185, 129, 0.12) 45%, rgba(245, 158, 11, 0.1) 100%);
}

:deep(.grid-stack.design-density-compact > .grid-stack-item) {
  padding: 6px;
}

:deep(.grid-stack.design-density-cozy > .grid-stack-item) {
  padding: 8px;
}

:deep(.grid-stack.design-density-airy > .grid-stack-item) {
  padding: 12px;
}

.grid-stack.design-card-soft .widget-card {
  border-radius: 16px;
  box-shadow: 0 10px 30px rgba(15, 23, 42, 0.1);
}

.grid-stack.design-card-glass .widget-card {
  backdrop-filter: blur(8px);
  background-color: rgba(255, 255, 255, 0.72);
  border-color: rgba(148, 163, 184, 0.4);
  box-shadow: 0 14px 34px rgba(15, 23, 42, 0.12);
}

.dark .grid-stack.design-card-glass .widget-card {
  background-color: rgba(15, 23, 42, 0.62);
  border-color: rgba(148, 163, 184, 0.28);
}

.widget-selected {
  box-shadow: 0 0 0 2px rgba(99, 102, 241, 0.45), 0 12px 30px rgba(79, 70, 229, 0.12);
}

.dashboard-theme-canvas.theme-colored :deep(.text-slate-700),
.dashboard-theme-canvas.theme-colored :deep(.text-slate-600),
.dashboard-theme-canvas.theme-colored :deep(.text-slate-500),
.dashboard-theme-canvas.theme-colored :deep(.text-slate-400) {
  color: var(--theme-text) !important;
}

.dashboard-theme-canvas.theme-colored :deep(.text-indigo-700),
.dashboard-theme-canvas.theme-colored :deep(.text-indigo-600),
.dashboard-theme-canvas.theme-colored :deep(.text-indigo-500),
.dashboard-theme-canvas.theme-colored :deep(.text-violet-700),
.dashboard-theme-canvas.theme-colored :deep(.text-violet-600),
.dashboard-theme-canvas.theme-colored :deep(.text-violet-500),
.dashboard-theme-canvas.theme-colored :deep(.text-rose-700),
.dashboard-theme-canvas.theme-colored :deep(.text-rose-600),
.dashboard-theme-canvas.theme-colored :deep(.text-rose-500),
.dashboard-theme-canvas.theme-colored :deep(.text-emerald-700),
.dashboard-theme-canvas.theme-colored :deep(.text-emerald-600),
.dashboard-theme-canvas.theme-colored :deep(.text-emerald-500) {
  color: var(--theme-accent-strong) !important;
}

.dashboard-theme-canvas.theme-colored :deep(.bg-indigo-50),
.dashboard-theme-canvas.theme-colored :deep(.bg-indigo-100),
.dashboard-theme-canvas.theme-colored :deep(.bg-indigo-50\/70),
.dashboard-theme-canvas.theme-colored :deep(.bg-violet-50),
.dashboard-theme-canvas.theme-colored :deep(.bg-violet-100),
.dashboard-theme-canvas.theme-colored :deep(.bg-rose-50),
.dashboard-theme-canvas.theme-colored :deep(.bg-rose-100),
.dashboard-theme-canvas.theme-colored :deep(.bg-emerald-50),
.dashboard-theme-canvas.theme-colored :deep(.bg-emerald-100),
.dashboard-theme-canvas.theme-colored :deep(.from-indigo-50),
.dashboard-theme-canvas.theme-colored :deep(.to-violet-50) {
  background-color: var(--theme-soft) !important;
}

.dashboard-theme-canvas.theme-colored :deep(.bg-indigo-600),
.dashboard-theme-canvas.theme-colored :deep(.bg-violet-600),
.dashboard-theme-canvas.theme-colored :deep(.from-indigo-600),
.dashboard-theme-canvas.theme-colored :deep(.to-violet-600) {
  background-color: var(--theme-accent-strong) !important;
  background-image: none !important;
}

.dashboard-theme-canvas.theme-colored :deep(.border-indigo-100),
.dashboard-theme-canvas.theme-colored :deep(.border-indigo-200),
.dashboard-theme-canvas.theme-colored :deep(.border-indigo-300),
.dashboard-theme-canvas.theme-colored :deep(.border-indigo-400),
.dashboard-theme-canvas.theme-colored :deep(.border-violet-100),
.dashboard-theme-canvas.theme-colored :deep(.border-violet-200),
.dashboard-theme-canvas.theme-colored :deep(.border-violet-300),
.dashboard-theme-canvas.theme-colored :deep(.border-violet-400),
.dashboard-theme-canvas.theme-colored :deep(.border-rose-100),
.dashboard-theme-canvas.theme-colored :deep(.border-rose-200),
.dashboard-theme-canvas.theme-colored :deep(.border-rose-300),
.dashboard-theme-canvas.theme-colored :deep(.border-emerald-100),
.dashboard-theme-canvas.theme-colored :deep(.border-emerald-200),
.dashboard-theme-canvas.theme-colored :deep(.border-emerald-300) {
  border-color: var(--theme-border) !important;
}

.dashboard-theme-canvas.theme-colored :deep(.metric-ribbon) {
  background: linear-gradient(90deg, var(--theme-soft) 0%, rgba(var(--theme-accent-rgb), 0.08) 45%, var(--theme-soft) 100%) !important;
  border-color: var(--theme-border) !important;
}

.dashboard-theme-canvas.theme-colored :deep(.grid-stack) {
  --grid-accent: rgba(var(--theme-accent-rgb), 0.08);
}

.dashboard-theme-canvas.theme-colored :deep(.widget-card) {
  border-color: rgba(var(--theme-accent-rgb), 0.18);
}

.dashboard-theme-canvas.theme-colored :deep(.widget-card .border-b) {
  border-bottom-color: rgba(var(--theme-accent-rgb), 0.2) !important;
}

.dashboard-theme-canvas.theme-colored :deep(.widget-selected) {
  box-shadow: 0 0 0 2px var(--theme-accent), 0 12px 30px rgba(79, 70, 229, 0.16);
}

/* Subtle left-accent for KPI cards */
.widget-card::before {
  content: '';
  position: absolute;
  inset: 0;
  border-radius: inherit;
  pointer-events: none;
  transition: box-shadow 0.2s ease;
}

/* ── GRIDSTACK CELL GAP (breathing space between widgets) ─────── */
:deep(.grid-stack > .grid-stack-item) {
  padding: 8px;
}

/* ── CHART CANVAS (deep override) ─────────────────────────────── */
:deep(canvas) {
  width: 100% !important;
  height: 100% !important;
}

/* ── SCROLLBAR STYLING ────────────────────────────────────────── */
.scrollbar-thin::-webkit-scrollbar { width: 4px; }
.scrollbar-thin::-webkit-scrollbar-track { background: transparent; }
.scrollbar-thin::-webkit-scrollbar-thumb { background: rgba(148, 163, 184, 0.3); border-radius: 4px; }
.scrollbar-thin::-webkit-scrollbar-thumb:hover { background: rgba(148, 163, 184, 0.5); }

/* ── RESIZE HANDLES ───────────────────────────────────────────── */
:deep(.ui-resizable-handle) { display: none !important; }

:deep(.ui-resizable-se) {
  display: block !important;
  width: 20px !important;
  height: 20px !important;
  bottom: 0 !important;
  right: 0 !important;
  background: none !important;
  border: none !important;
  cursor: se-resize !important;
  opacity: 0;
  transition: opacity 0.15s;
}

:deep(.ui-resizable-e) {
  display: block !important;
  width: 8px !important;
  right: 0 !important;
  top: 0 !important;
  height: 100% !important;
  background: none !important;
  border: none !important;
  cursor: e-resize !important;
  opacity: 0;
  transition: opacity 0.15s;
}

:deep(.ui-resizable-s) {
  display: block !important;
  height: 8px !important;
  bottom: 0 !important;
  left: 0 !important;
  width: 100% !important;
  background: none !important;
  border: none !important;
  cursor: s-resize !important;
  opacity: 0;
  transition: opacity 0.15s;
}

:deep(.grid-stack-item:hover .ui-resizable-se),
:deep(.grid-stack-item:hover .ui-resizable-e),
:deep(.grid-stack-item:hover .ui-resizable-s) { opacity: 1; }

:deep(.grid-stack-item:hover .ui-resizable-se::after) {
  content: '';
  position: absolute;
  width: 10px;
  height: 10px;
  bottom: 4px;
  right: 4px;
  background: linear-gradient(135deg, transparent 40%, rgba(99, 102, 241, 0.35) 40%);
  border-radius: 2px;
}

:deep(.ui-resizable-n),
:deep(.ui-resizable-w),
:deep(.ui-resizable-ne),
:deep(.ui-resizable-nw),
:deep(.ui-resizable-sw) {
  display: none !important;
}

/* ── LOCKED STATE ─────────────────────────────────────────────── */
:deep(.grid-stack.static-grid .ui-resizable-handle) {
  display: none !important;
  opacity: 0 !important;
}

:deep(.grid-stack.static-grid .grid-stack-item) { pointer-events: none; }
:deep(.grid-stack.static-grid .grid-stack-item-content) { cursor: default !important; }
:deep(.grid-stack:not(.static-grid) .grid-stack-item) { pointer-events: auto; }

/* ── GRID-STACK OVERRIDES ─────────────────────────────────────── */
:deep(.grid-stack-item-content) {
  border-radius: 12px;
  overflow: visible; /* let card shadow render beyond the gridstack cell clip */
}

:deep(.grid-stack-item) {
  transition: transform 0.15s ease;
  animation: widget-in 0.35s ease-out both;
}

/* ── WIDGET ENTRANCE ANIMATION ─────────────────────────────── */
@keyframes widget-in {
  from { opacity: 0; transform: translateY(8px) scale(0.97); }
  to   { opacity: 1; transform: translateY(0) scale(1); }
}

:deep(.grid-stack-item:nth-child(1)) { animation-delay: 0ms; }
:deep(.grid-stack-item:nth-child(2)) { animation-delay: 40ms; }
:deep(.grid-stack-item:nth-child(3)) { animation-delay: 80ms; }
:deep(.grid-stack-item:nth-child(4)) { animation-delay: 120ms; }
:deep(.grid-stack-item:nth-child(5)) { animation-delay: 160ms; }
:deep(.grid-stack-item:nth-child(6)) { animation-delay: 200ms; }
:deep(.grid-stack-item:nth-child(n+7)) { animation-delay: 240ms; }

/* ── DRAG GLOW (active widget being dragged) ───────────────── */
:deep(.grid-stack-item.ui-draggable-dragging .widget-card),
:deep(.grid-stack-item.ui-resizable-resizing .widget-card) {
  box-shadow: 0 0 0 2px rgba(99, 102, 241, 0.4), 0 20px 60px rgba(99, 102, 241, 0.12), 0 8px 30px rgba(0, 0, 0, 0.06);
  transform: scale(1.01);
}

.dark :deep(.grid-stack-item.ui-draggable-dragging .widget-card),
.dark :deep(.grid-stack-item.ui-resizable-resizing .widget-card) {
  box-shadow: 0 0 0 2px rgba(99, 102, 241, 0.5), 0 20px 60px rgba(99, 102, 241, 0.15), 0 8px 30px rgba(0, 0, 0, 0.2);
}

/* ── SCROLLBAR STYLING ────────────────────────────────────────── */
/* (Handled by .scrollbar-thin in the new Tailwind markup above) */

/* ── FAB POPOVER TRANSITION ───────────────────────────────────── */
.fab-pop-enter-active,
.fab-pop-leave-active {
  transition: opacity 0.2s ease, transform 0.2s ease;
}
.fab-pop-enter-from,
.fab-pop-leave-to {
  opacity: 0;
  transform: translateY(8px) scale(0.95);
}
.slide-down-enter-active,
.slide-down-leave-active {
  transition: max-height 0.25s ease, opacity 0.2s ease;
  max-height: 200px;
  overflow: hidden;
}
.slide-down-enter-from,
.slide-down-leave-to {
  max-height: 0;
  opacity: 0;
}

/* ── CHART BUILDER SIDEBAR SLIDE-IN ──────────────────────────── */
.chart-builder-slide-enter-active,
.chart-builder-slide-leave-active {
  transition: width 0.25s ease, opacity 0.2s ease;
  overflow: hidden;
}
.chart-builder-slide-enter-from,
.chart-builder-slide-leave-to {
  width: 0;
  opacity: 0;
}
.chart-builder-slide-enter-to,
.chart-builder-slide-leave-from {
  width: 18rem; /* w-72 = 288px */
  opacity: 1;
}
</style>

