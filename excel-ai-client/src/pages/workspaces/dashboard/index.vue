<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import workspaceApi from '@/services/workspaceApi'
import { toast } from 'vue-sonner'
import { GridStack } from 'gridstack'
import 'gridstack/dist/gridstack.min.css'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { BarChart, LineChart, PieChart, ScatterChart, FunnelChart, GaugeChart, HeatmapChart, TreemapChart } from 'echarts/charts'
import { TitleComponent, TooltipComponent, LegendComponent, GridComponent, DataZoomComponent, VisualMapComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import LeftSidebar from '@/components/dashboard/LeftSidebar.vue'
import WidgetStyleChooserModal from '@/components/dashboard/WidgetStyleChooserModal.vue'
import WidgetFloatingToolbar from '@/components/dashboard/WidgetFloatingToolbar.vue'

// Dummy values for screens (required by LeftSidebar)
const boardScreens = ref([{ id: 'default', name: 'Dashboard' }])
const activeScreenId = ref('default')

const sidebarOpen = ref(true)
const isPreviewMode = ref(false)

function toggleSidebar() {
  sidebarOpen.value = !sidebarOpen.value
}

use([BarChart,LineChart,PieChart,ScatterChart,FunnelChart,GaugeChart,HeatmapChart,TreemapChart,TitleComponent,TooltipComponent,LegendComponent,GridComponent,DataZoomComponent,VisualMapComponent,CanvasRenderer])

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type AnyData = any;

const COLOR_THEMES: Record<string, { swatch: string; bg: string; text: string; chart: string[] }> = {
  mokkup1: { swatch: '#4338ca', bg: 'bg-indigo-50 dark:bg-indigo-950/30', text: 'text-indigo-700 dark:text-indigo-300', chart: ['#20156f', '#3f34b8', '#6a60d9', '#8f89e6', '#547bc7'] },
  holidaySpark: { swatch: '#d4645e', bg: 'bg-rose-50 dark:bg-rose-950/20', text: 'text-rose-600 dark:text-rose-300', chart: ['#d0605a', '#e07b76', '#98c97e', '#ee9992', '#86b96d'] },
  mokkup2: { swatch: '#4b3fb6', bg: 'bg-violet-50 dark:bg-violet-950/30', text: 'text-violet-700 dark:text-violet-300', chart: ['#4f44b9', '#746bdb', '#948fde', '#e69488', '#d57665'] },
  rustic: { swatch: '#8b4e25', bg: 'bg-amber-50 dark:bg-amber-950/20', text: 'text-amber-700 dark:text-amber-300', chart: ['#884e24', '#d78d59', '#f3ba90', '#f8dc98', '#efbd47'] },
  indigo: { swatch: '#6366f1', bg: 'bg-indigo-50 dark:bg-indigo-950/30', text: 'text-indigo-600 dark:text-indigo-400', chart: ['#4338ca', '#4f46e5', '#6366f1', '#818cf8', '#a5b4fc'] },
  violet: { swatch: '#8b5cf6', bg: 'bg-violet-50 dark:bg-violet-950/30', text: 'text-violet-600 dark:text-violet-400', chart: ['#6d28d9', '#7c3aed', '#8b5cf6', '#a78bfa', '#c4b5fd'] },
  emerald: { swatch: '#10b981', bg: 'bg-emerald-50 dark:bg-emerald-950/30', text: 'text-emerald-600 dark:text-emerald-400', chart: ['#047857', '#059669', '#10b981', '#34d399', '#6ee7b7'] },
  amber: { swatch: '#f59e0b', bg: 'bg-amber-50 dark:bg-amber-950/30', text: 'text-amber-600 dark:text-amber-400', chart: ['#b45309', '#d97706', '#f59e0b', '#fbbf24', '#fcd34d'] },
  rose: { swatch: '#f43f5e', bg: 'bg-rose-50 dark:bg-rose-950/30', text: 'text-rose-600 dark:text-rose-400', chart: ['#be123c', '#e11d48', '#f43f5e', '#fb7185', '#fda4af'] },
  cyan: { swatch: '#06b6d4', bg: 'bg-cyan-50 dark:bg-cyan-950/30', text: 'text-cyan-600 dark:text-cyan-400', chart: ['#0e7490', '#0891b2', '#06b6d4', '#22d3ee', '#67e8f9'] },
}

const THEMES: Record<string, { shades: string[]; swatch: string }> = Object.entries(COLOR_THEMES).reduce((acc, [key, val]) => {
  acc[key] = { shades: val.chart, swatch: val.swatch }
  return acc
}, {} as any)

const themeKeysList = computed(() => Object.keys(COLOR_THEMES)) 
const themeKeys = themeKeysList // Alias for child components or debugging

function getSwatchStyle(tk: string): Record<string, string> { 
  const theme = COLOR_THEMES[tk];
  if (!theme) return { backgroundColor: '#6366f1' };
  return { 
    background: `linear-gradient(135deg, ${theme.swatch} 0%, ${theme.chart[1] || theme.swatch} 100%)`,
    boxShadow: `0 2px 8px ${theme.swatch}44`,
    backgroundColor: theme.swatch // Fallback
  };
}

const CB_TYPES = [
  {id:'bar',label:'Bar',icon:'lucide:bar-chart-2'},{id:'line',label:'Line',icon:'lucide:trending-up'},{id:'area',label:'Area',icon:'lucide:mountain'},
  {id:'combo',label:'Combo',icon:'lucide:chart-column-increasing'},{id:'pie',label:'Pie',icon:'lucide:pie-chart'},{id:'donut',label:'Donut',icon:'lucide:circle-dashed'},
  {id:'scatter',label:'Scatter',icon:'lucide:scatter-chart'},{id:'bubble',label:'Bubble',icon:'lucide:circle-dot'},{id:'histogram',label:'Histogram',icon:'lucide:chart-bar-big'},
  {id:'funnel',label:'Funnel',icon:'lucide:funnel'},{id:'gauge',label:'Gauge',icon:'lucide:gauge'},{id:'heatmap',label:'Heatmap',icon:'lucide:grid-2x2'},
  {id:'treemap',label:'Treemap',icon:'lucide:layout-grid'},{id:'waterfall',label:'Waterfall',icon:'lucide:chart-column-stacked'},
]

const route = useRoute(), router = useRouter()
const workspaceId = route.params.workspaceId as string
const boardFiles = ref<any[]>([])
const widgets = ref<AnyData[]>([])
const sortedWidgets = computed(() => {
  const order: Record<string, number> = { summary: -1, kpi: 0, insight: 1, list: 2, chart: 3 }
  return [...widgets.value].sort((a, b) => {
    const aOrder = order[a.type] ?? 3
    const bOrder = order[b.type] ?? 3
    return aOrder - bOrder
  })
})
const isLoading = ref(false)
const isAddingWidget = ref(false)
const newWidgetQuery = ref('')
const showAddPopover = ref(false)

const showCustomWidgetModal = ref(false)
const isAddingCustomWidget = ref(false)
const customWidgetForm = ref({
  title: '',
  sqlQuery: '',
  widgetType: 'kpi',
  chartType: 'bar'
})

const isDashboardLocked = ref(false)
const zoomLevel = ref(100)
function zoomIn() { if (zoomLevel.value < 150) zoomLevel.value += 10 }
function zoomOut() { if (zoomLevel.value > 50) zoomLevel.value -= 10 }
const activeWidgetId = ref<string|null>(null)
const toolbarPos = ref({top:0,left:0,visible:false})
const chartBuilderOpen = ref(false)
const chartBuilderLoading = ref(false)
const chartSchema = ref<AnyData | null>(null)
const refreshingWidgets = ref<Set<string>>(new Set())
const cbForm = ref({chartType:'bar',dimension:'',measure:'',aggregation:'sum'})
const selectedMeasureAggs = computed(() => {
  if (!chartSchema.value?.measures?.length) return ['sum','avg','count','min','max']
  const m = chartSchema.value.measures.find((m: any) => m.col === cbForm.value.measure)
  return m?.available_aggs || ['sum','avg','count','min','max']
})
const activeTheme = ref('indigo')
let grid: any = null
const gridEl = ref<HTMLElement|null>(null)
let saveTimer: ReturnType<typeof setTimeout> | null = null

// ── STUDIO STATE (SmartDashboard Parity) ──
const studioTab = ref<'elements' | 'screens' | 'design'>('elements')
const boardDesign = ref({
  texture: 'none' as 'none' | 'dots' | 'grid' | 'gradient',
  density: 'cozy' as 'compact' | 'cozy' | 'airy',
  cardStyle: 'flat' as 'flat' | 'soft' | 'glass'
})
// ── SLICER STATE ──
const slicerValues = ref<Record<string, string>>({})
const slicerDimensions = computed(() => {
  if (!chartSchema.value?.dimensions) return []
  // Filter for high-quality slicer dimensions (reasonable cardinality)
  return chartSchema.value.dimensions.filter((d: any) => d.cardinality > 1 && d.cardinality < 50)
})

async function onSlicerChange(col: string, val: string) {
  if (val === '__all__') delete slicerValues.value[col]
  else slicerValues.value[col] = val
  
  // Refresh all widgets with new filters
  await refreshAllWidgets()
}

async function clearSlicers() {
  slicerValues.value = {}
  await refreshAllWidgets()
}

async function refreshAllWidgets() {
  const promises = widgets.value.map(w => refreshSingleWidget(w.id))
  await Promise.all(promises)
}

const showStyleChooser = ref(false)
const activeWidget = computed(() => widgets.value.find(w => w.id === activeWidgetId.value))

// ── COMMAND PALETTE STATE ──
const showCommandPalette = ref(false)
const commandQuery = ref('')
const commandInputRef = ref<HTMLInputElement|null>(null)
const commands = [
  { id: 'regen', label: 'Regenerate Dashboard', icon: '🔄', action: () => load(true) },
  { id: 'add', label: 'Add New Widget', icon: '➕', action: () => { showAddPopover.value = true; nextTick(() => { const el = document.querySelector('textarea'); el?.focus() }) } },
  { id: 'preview', label: 'Toggle Preview Mode', icon: '👁️', action: togglePreview },
  { id: 'lock', label: 'Toggle Grid Lock', icon: '🔒', action: () => { isDashboardLocked.value = !isDashboardLocked.value; grid?.setStatic(isDashboardLocked.value) } },
  { id: 'png', label: 'Export as PNG', icon: '🖼️', action: exportPNG },
  { id: 'pdf', label: 'Export as PDF', icon: '📄', action: exportPDF },
]
const filteredCommands = computed(() => commands.filter(c => c.label.toLowerCase().includes(commandQuery.value.toLowerCase())))

function executeCommand(cmd: any) {
  cmd.action()
  showCommandPalette.value = false
  commandQuery.value = ''
}

const canvasClass = computed(() => [
  `design-texture-${boardDesign.value.texture}`,
  `design-density-${boardDesign.value.density}`,
  `design-card-${boardDesign.value.cardStyle}`,
  isPreviewMode.value ? 'is-preview' : ''
])

// ── THEME ANIMATION STATE ──
const isThemeChanging = ref(false)

async function changeTheme(tk: string) {
  if (activeTheme.value === tk) return
  isThemeChanging.value = true
  activeTheme.value = tk
  // Allow CSS variables to propagate before ending transition
  setTimeout(() => {
    isThemeChanging.value = false
  }, 400)
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

function truncateAxisLabel(val: string, len: number): string {
  if (!val) return ''
  return val.length > len ? val.slice(0, len) + '…' : val
}

function handleWidgetStyleUpdate(update: any) {
  if (!activeWidget.value) return
  Object.assign(activeWidget.value, update)
  persist()
}

function handleDashboardDesignUpdate(key: string, value: any) {
  (boardDesign.value as any)[key] = value
  
  // Re-init grid if density changes to update margins
  if (key === 'density') {
    const marginMap = { compact: 4, cozy: 12, airy: 24 }
    grid?.margin((marginMap as any)[value])
  }
}

// ── FORMATTING HELPERS (SmartDashboard Parity) ──
function ensureWidgetUiDefaults(w: any) {
  if (!w.ui) w.ui = {}
  if (typeof w.ui.showTitle !== 'boolean') w.ui.showTitle = true
  if (typeof w.ui.titleText !== 'string') w.ui.titleText = w.title || ''
  if (typeof w.ui.align !== 'string') w.ui.align = 'left'
  if (!w.ui.variation) w.ui.variation = 'default'
}

function getWidgetTitle(w: any): string {
  ensureWidgetUiDefaults(w)
  if (!w.ui.showTitle) return ''
  return w.ui.titleText || w.title || ''
}

function formatIndianNumber(num: number, decimals: number = 0): string {
  return num.toLocaleString('en-IN', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })
}

function getKpiDisplayValue(w: any): string {
  ensureWidgetUiDefaults(w)
  const val = w.value ?? 'N/A'
  if (val === 'N/A') return 'N/A'
  
  const num = typeof val === 'number' ? val : parseFloat(String(val).replace(/[^0-9.-]/g, ''))
  if (isNaN(num)) return String(val)

  const formatted = formatIndianNumber(num, w.ui.decimals || 0)
  const prefix = w.ui.prefix || ''
  const suffix = w.ui.suffix || ''
  
  // Auto-detect currency if it looks like a large financial number
  const isCurrency = /salary|revenue|cost|price|amount|budget/i.test(w.title)
  const symbol = isCurrency ? (w.ui.currency || '₹') : ''
  
  return `${prefix}${symbol}${formatted}${suffix}`
}

const themePalette = ()=>THEMES[activeTheme.value]?.shades||THEMES.indigo.shades
const themeCssVars = ()=>{
  const accent = THEMES[activeTheme.value]?.swatch || '#6366f1'
  const accentStrong = darkenHex(accent, 0.12)
  const shades = themePalette()
  return {
    '--ts1': shades[0], '--ts2': shades[1], '--ts3': shades[2], '--ts4': shades[3], '--ts5': shades[4],
    '--theme-accent': accent,
    '--theme-accent-rgb': hexToRgbString(accent),
    '--theme-accent-strong': accentStrong,
    '--theme-soft': hexToRgba(accent, 0.14),
    '--theme-text': darkenHex(accent, 0.32),
  }
}
function badgeStyle(w: AnyData){const s=themePalette();const ct=w.chartType||'bar';const m:Record<string,[string,string]>={bar:[s[2]+'33',s[2]],pie:[s[3]+'33',s[3]],donut:[s[3]+'33',s[3]],line:[s[1]+'33',s[1]],area:[s[1]+'33',s[1]],scatter:[s[4]+'33',s[4]],list:[s[3]+'33',s[3]],insight:[s[0]+'33',s[0]]};const c=m[w.type==='chart'?ct:w.type]||[s[0]+'33',s[0]];return{backgroundColor:c[0],color:c[1]}}
function listBarColor(idx:number){const s=themePalette();return idx<3?s[0]:s[2]}
function widgetBorderStyle(w: AnyData){
  const s=themePalette();
  const ui = w.ui || {}
  
  if (ui.canvasColor) return { backgroundColor: ui.canvasColor }
  
  // Design card styles should override these default borders if soft/glass are used
  const isSpecialStyle = ['soft', 'glass'].includes(boardDesign.value.cardStyle)
  
  if(w.type==='kpi')return{borderLeft: isSpecialStyle ? `0` : `4px solid ${s[0]}`};
  if(w.type==='insight')return{borderLeft: isSpecialStyle ? `0` : `4px solid ${s[2]}`};
  if(w.type==='list')return{borderLeft: isSpecialStyle ? `0` : `4px solid ${s[3]}`};
  if(w.type==='chart'){
    const ct=w.chartType||'bar';
    if(['line','area'].includes(ct))return{borderTop: isSpecialStyle ? `0` : `3px solid ${s[1]}`};
    if(['bar','histogram','waterfall'].includes(ct))return{borderTop: isSpecialStyle ? `0` : `3px solid ${s[2]}`};
    if(['pie','donut','treemap'].includes(ct))return{borderTop: isSpecialStyle ? `0` : `3px solid ${s[3]}`};
    return{borderTop: isSpecialStyle ? `0` : `3px solid ${s[4]}`};
  }
  return {}
}

function getWidgetCardClass(w: AnyData) {
  const ui = w.ui || {}
  const variation = ui.variation || 'default'
  
  return [
    'widget-card group relative flex flex-col h-full overflow-hidden transition-all duration-300',
    // Background and Shadow based on variant
    w.type === 'summary' 
      ? 'border border-indigo-100/80 dark:border-indigo-500/15 bg-gradient-to-br from-indigo-50/50 via-white to-white dark:from-indigo-950/20 dark:via-slate-900 shadow-[0_8px_30px_rgb(0,0,0,0.04)]' 
      : 'border border-slate-200/60 dark:border-white/[0.05] bg-white dark:bg-slate-900 shadow-[0_4px_20px_rgb(0,0,0,0.03)]',
    
    // Active/Hover States
    activeWidgetId.value === w.id 
      ? 'ring-2 ring-indigo-500 ring-offset-4 z-10 scale-[1.02] shadow-2xl' 
      : 'hover:shadow-[0_20px_50px_rgba(0,0,0,0.1)] hover:scale-[1.01] hover:z-[5]',
    
    // Corner Rounding
    ui.roundedCorners !== false ? 'rounded-[1.25rem]' : 'rounded-none',
    
    // Variants from SmartDashboard
    variation === 'executive' ? 'border-t-[6px] border-t-indigo-500 pt-1' : '',
    variation === 'glass' ? 'backdrop-blur-xl bg-white/60 dark:bg-slate-900/60 border-white/20' : '',
    variation === 'compact' ? 'px-1 py-1' : ''
  ]
}

function echartOpts(w: AnyData){
  const cd=w.chartData; if(!cd) return undefined
  const p=themePalette()
  const ct=w.chartType||'bar'
  const isHorizontal = w.horizontal === true
  const axisTickColor = '#64748b'
  const labels = cd.labels || []
  const series = cd.series || []

  const base: any = {
    color: p,
    backgroundColor: 'transparent',
    tooltip: {
      trigger: ct === 'pie' || ct === 'donut' ? 'item' : 'axis',
      backgroundColor: '#fff',
      borderColor: '#e2e8f0',
      borderWidth: 1,
      textStyle: { color: '#334155', fontSize: 12 },
      extraCssText: 'box-shadow: 0 4px 16px rgba(0,0,0,0.08); border-radius: 8px;'
    },
    legend: {
      show: ct === 'pie' || ct === 'donut' ? labels.length <= 8 : series.length > 1,
      bottom: 0,
      textStyle: { color: '#64748b', fontSize: 10 }
    },
    grid: { left: 48, right: 16, top: 24, bottom: series.length > 1 ? 40 : 32, containLabel: true }
  }

  // Helper: extract numeric value from series at index `i`
  // Handles both flat [42, 30, ...] and structured [{name, data: [...]}] formats
  const getSeriesVal = (i: number): number => {
    const s0 = series?.[0]
    if (s0 == null) return 0
    // Structured format: {name, data: [...]}
    if (typeof s0 === 'object' && !Array.isArray(s0) && s0.data) {
      const v = Number(s0.data[i]); return isNaN(v) ? 0 : v
    }
    // Flat format: series is [42, 30, ...]
    if (typeof s0 === 'number' || typeof s0 === 'string') {
      const v = Number(series[i]); return isNaN(v) ? 0 : v
    }
    return 0
  }

  if(ct==='pie'||ct==='donut'){
    return {
      ...base,
      series:[{
        type:'pie',
        radius:ct==='donut'?['45%','70%']:'65%',
        center: ['50%', '45%'],
        data:labels.map((l:string,i:number)=>({name:l,value:getSeriesVal(i)})),
        label:{fontSize:10, show: labels.length <= 6},
        emphasis:{itemStyle:{shadowBlur:10,shadowColor:'rgba(0,0,0,0.2)'}},
        itemStyle: { borderRadius: ct==='donut' ? 4 : 0, borderColor: '#fff', borderWidth: 2 }
      }]
    }
  }

  const categoryAxis = {
    type: 'category',
    data: labels,
    axisLabel: {
      fontSize: 9,
      color: axisTickColor,
      rotate: labels.length > 8 ? 30 : 0,
      formatter: (v: string) => truncateAxisLabel(v, labels.length > 12 ? 8 : 12)
    },
    axisLine: { lineStyle: { color: '#cbd5e1' } }
  }

  const valueAxis = {
    type: 'value',
    axisLabel: { fontSize: 9, color: axisTickColor },
    splitLine: { lineStyle: { color: 'rgba(148, 163, 184, 0.2)', type: 'dashed' } }
  }

  base.xAxis = isHorizontal ? valueAxis : categoryAxis
  base.yAxis = isHorizontal ? categoryAxis : valueAxis

  if(ct==='area'){
    base.series = series.map((s: AnyData,i:number)=>({
      name:s.name||'Value',
      type:'line',
      data:s.data||[],
      smooth:true,
      areaStyle:{opacity:0.2},
      itemStyle:{color:p[i%p.length]}
    }))
    return base
  }

  if(ct==='funnel'){
    return {
      ...base,
      series:[{
        type:'funnel',
        left:'10%', width:'80%',
        data:labels.map((l:string,i:number)=>({name:l,value:getSeriesVal(i)}))
      }]
    }
  }

  if(ct==='treemap'){
    return {
      ...base,
      series:[{
        type:'treemap',
        roam:false,
        breadcrumb:{show:false},
        data:labels.map((l:string,i:number)=>({name:l,value:getSeriesVal(i)}))
      }]
    }
  }

  const seriesType=ct==='line'?'line':ct==='scatter'?'scatter':'bar'
  base.series = series.map((s: AnyData,i:number)=>({
    name:s.name||'Value',
    type:seriesType,
    data:s.data||[],
    smooth:ct==='line',
    itemStyle:{
      color:p[i%p.length],
      borderRadius: seriesType === 'bar' ? (isHorizontal ? [0, 4, 4, 0] : [4, 4, 0, 0]) : undefined
    },
    barMaxWidth: 32
  }))
  return base
}

function initGrid(){
  if(!widgets.value.length||!gridEl.value) return
  try{grid?.destroy(false)}catch{}

  const marginMap = { compact: 4, cozy: 12, airy: 24 }
  const currentMargin = (marginMap as any)[boardDesign.value.density] || 12

  grid=GridStack.init({
    column:12,
    cellHeight: 80,
    minRow:1,
    margin: currentMargin,
    animate:true,
    float:false,
    staticGrid:isDashboardLocked.value,
    draggable:{handle:'.ws-drag'},
    resizable:{
      handles:'e,se,s',
      autoHide: true 
    }
  },gridEl.value)
  
  // Internal force refresh of handles
  grid.on('enable', () => nextTick(() => {}));
  grid.on('change',(_e: AnyData,items: AnyData)=>{
    items?.forEach((it: AnyData)=>{const w=widgets.value.find(x=>x.id===String(it.id));if(w){w.gridX=it.x;w.gridY=it.y;w.gridW=it.w;w.gridH=it.h}})
    if(saveTimer)clearTimeout(saveTimer);saveTimer=setTimeout(()=>persist(),1500)
  })
}

function autoPos() {
  const COLS = 12
  const colHeights = new Array(COLS).fill(0)
  
  for (const w of sortedWidgets.value) {
    const ww = Math.min(w.gridW || (w.type === 'summary' ? 12 : w.type === 'kpi' ? 3 : 4), COLS)
    const hh = w.gridH || (w.type === 'kpi' ? 2 : 3)

    let bestX = 0
    let bestY = Infinity
    for (let x = 0; x <= COLS - ww; x++) {
      let maxH = 0
      for (let c = x; c < x + ww; c++) maxH = Math.max(maxH, colHeights[c])
      if (maxH < bestY) { bestY = maxH; bestX = x }
    }

    w.gridX = bestX
    w.gridY = bestY
    w.gridW = ww
    w.gridH = hh
    for (let c = bestX; c < bestX + ww; c++) colHeights[c] = bestY + hh
  }
}

async function streamLoad() {
  isLoading.value = true
  widgets.value = []
  try {
    await workspaceApi.streamDashboard(workspaceId, (w: AnyData) => {
      if (w.event === 'complete') {
        toast.success(`Dashboard complete! ${w.widget_count || widgets.value.length} widgets generated`)
        return
      }
      if (!w.chartType && w.chart_type) w.chartType = w.chart_type
      widgets.value.push(w)
      // Show grid as widgets arrive
      if (widgets.value.length === 1) {
        isLoading.value = false
        nextTick(() => initGrid())
      } else {
        nextTick(() => {
          try { grid?.destroy(false) } catch {}
          grid = null
          initGrid()
        })
      }
    })
    isLoading.value = false
    await nextTick()
    initGrid()
    await persist()
  } catch (e: unknown) {
    const err = e as { response?: { data?: { detail?: string } } }
    toast.error(err?.response?.data?.detail || 'Stream failed')
    isLoading.value = false
  }
}

async function load(regen=false){
  isLoading.value=true
  try{
    // Load workspace files to populate the sidebar
    workspaceApi.getWorkspaceDetail(workspaceId).then(detail => {
      boardFiles.value = detail.tables.map(t => ({
        file_uuid: t.metadata_id,
        filename: t.table_name,
        total_rows: t.row_count
      }))
    })

    const r=await workspaceApi.getDashboard(workspaceId,regen)
    const ws=(r.widgets||[]).map((w: AnyData)=>{
      if(!w.chartType&&w.chart_type) w.chartType=w.chart_type

      // ── Chat-pinned widget data transform ─────────────────────────
      // Chat-pinned widgets store raw row data in `chartData` (array of objects)
      // and `columns` (array of strings). The dashboard renderers expect:
      //   - chart: { labels: [...], series: [{ name, data: [...] }] }
      //   - kpi: w.value
      //   - list: w.items = [{ label, value }, ...]
      //   - table: w.data + w.columns (already correct)
      if (w.source_table === '_chat' && Array.isArray(w.chartData) && w.columns?.length) {
        const rawRows = w.chartData as any[]
        const cols = w.columns as string[]

        if (w.type === 'kpi' && rawRows.length >= 1) {
          // Use first numeric column value, or first column
          const numCol = cols.find(c => typeof rawRows[0][c] === 'number') || cols[0]
          w.value = rawRows[0][numCol]
          w.subtitle = numCol

        } else if (w.type === 'list') {
          // First col = label, second col (or first numeric) = value
          const labelCol = cols[0]
          const valueCol = cols.find((c, i) => i > 0 && typeof rawRows[0]?.[c] === 'number') || cols[1] || cols[0]
          w.items = rawRows.slice(0, 10).map((row: any) => ({
            label: String(row[labelCol] ?? ''),
            value: row[valueCol] ?? ''
          }))

        } else if (w.type === 'chart') {
          // Convert raw rows to ECharts format: first col = categories, rest = series
          const catCol = cols[0]
          const numCols = cols.filter((c, i) => i > 0 && rawRows.some(r => typeof r[c] === 'number'))
          const seriesCols = numCols.length > 0 ? numCols : cols.slice(1)
          w.chartData = {
            labels: rawRows.map((r: any) => String(r[catCol] ?? '')),
            series: seriesCols.map(sc => ({
              name: sc,
              data: rawRows.map((r: any) => Number(r[sc]) || 0)
            }))
          }

        } else if (w.type === 'table') {
          // Table uses w.data + w.columns — move chartData to data
          w.data = rawRows
          // columns already set
        }
      }

      return w
    })
    widgets.value=ws
    
    // Crucial fix: Show grid DOM before initGrid
    isLoading.value = false
    await nextTick()
    initGrid()
    
    // Auto-fetch data for incremental SQL widgets (have sql_query but no pre-computed data)
    ws.forEach((w: AnyData) => {
      if (w.sql_query && !w.chartData && !w.items && !w.value && !w.data) {
        refreshSingleWidget(w.id)
      }
    })
    
    if (regen) {
      toast.success(`🎉 Dashboard regenerated with ${widgets.value.length} widgets`)
    } else {
      toast.success(`Loaded ${widgets.value.length} widgets`)
    }
  }catch(e: unknown){
    const err = e as {response?: {data?: {detail?: string}}};
    toast.error(err?.response?.data?.detail||'Failed to load dashboard')
    isLoading.value = false
  }
}

async function persist(){try{await workspaceApi.updateDashboardWidgets(workspaceId,widgets.value)}catch{}}

async function refreshSingleWidget(id:string){
  refreshingWidgets.value.add(id)
  try{
    // Pack slicer filters into the refresh request
    const r=await workspaceApi.refreshWidget(workspaceId,id, { filters: slicerValues.value })
    if(r.status==='success'&&r.widget){
      const idx=widgets.value.findIndex(w=>w.id===id)
      if(idx>=0){const old=widgets.value[idx];Object.assign(old,r.widget);old.id=id}
      toast.success('Widget refreshed')
    }else{toast.error(r.message||'Refresh failed')}
  }catch{toast.error('Refresh failed')}
  finally{refreshingWidgets.value.delete(id)}
}

async function addWidget(){
  const q=newWidgetQuery.value.trim();if(!q)return;isAddingWidget.value=true
  try{
    const r=await workspaceApi.generateWidget(workspaceId,q)
    if(r.status==='success'&&r.widget){delete r.widget.gridX;delete r.widget.gridY;widgets.value.push(r.widget);autoPos();try{grid?.destroy(false)}catch{};grid=null;await nextTick();initGrid();await persist();newWidgetQuery.value='';showAddPopover.value=false;toast.success('Widget added')}
  }catch{toast.error('Failed')}finally{isAddingWidget.value=false}
}

async function addCustomWidget() {
  const { title, sqlQuery, widgetType, chartType } = customWidgetForm.value
  if (!title.trim() || !sqlQuery.trim()) return
  isAddingCustomWidget.value = true
  try {
    const r = await workspaceApi.createCustomWidget(workspaceId, title, sqlQuery, widgetType, chartType)
    if (r.status === 'success' && r.widget) {
      delete r.widget.gridX
      delete r.widget.gridY
      widgets.value.push(r.widget)
      autoPos()
      try { grid?.destroy(false) } catch {}
      grid = null
      await nextTick()
      initGrid()
      await persist()
      customWidgetForm.value = { title: '', sqlQuery: '', widgetType: 'kpi', chartType: 'bar' }
      showCustomWidgetModal.value = false
      toast.success('Custom widget added')
    } else {
      toast.error(r.message || 'Failed')
    }
  } catch (e: any) {
    const err = e as {response?: {data?: {detail?: string}}};
    toast.error(err?.response?.data?.detail || e?.message || 'Failed')
  } finally {
    isAddingCustomWidget.value = false
  }
}

async function removeWidget(id:string){
  try {
    await workspaceApi.removeWidget(workspaceId, id)
    widgets.value=widgets.value.filter(w=>w.id!==id);
    activeWidgetId.value=null;
    toolbarPos.value.visible=false;
    try{grid?.destroy(false)}catch{};
    grid=null;
    if(widgets.value.length){await nextTick();initGrid()};
    await persist();
    toast.success('Removed')
  } catch (err) {
    toast.error('Failed to remove widget permanently')
  }
}

async function cloneWidget(id:string){
  const src=widgets.value.find(w=>w.id===id);if(!src)return
  const clone={...JSON.parse(JSON.stringify(src)),id:`ws-clone-${Date.now()}`};delete clone.gridX;delete clone.gridY
  widgets.value.push(clone);autoPos();try{grid?.destroy(false)}catch{};grid=null;await nextTick();initGrid();await persist();toast.success('Widget cloned')
}

function selectWidget(id:string,ev:MouseEvent){
  if(isDashboardLocked.value){activeWidgetId.value=null;toolbarPos.value.visible=false;return}
  activeWidgetId.value=id
  const el=(ev.currentTarget as HTMLElement).closest('.grid-stack-item') as HTMLElement
  if(el){const r=el.getBoundingClientRect();toolbarPos.value={top:r.top-44,left:r.left+r.width/2,visible:true}}
}
function clearSelection(){activeWidgetId.value=null;toolbarPos.value.visible=false}

async function ensureSchema(){if(chartSchema.value)return;try{const r=await workspaceApi.getChartSchema(workspaceId);chartSchema.value=r;if(!cbForm.value.dimension&&r.dimensions?.length)cbForm.value.dimension=r.dimensions[0].col;if(!cbForm.value.measure&&r.measures?.length)cbForm.value.measure=r.measures[0].col}catch{}}

async function buildChart(){
  if(!cbForm.value.dimension)return;chartBuilderLoading.value=true
  try{const r=await workspaceApi.generateCustomChart(workspaceId,cbForm.value.chartType,cbForm.value.dimension,cbForm.value.aggregation==='count'?null:cbForm.value.measure,cbForm.value.aggregation);if(r.status==='success'&&r.widget){delete r.widget.gridX;delete r.widget.gridY;widgets.value.push(r.widget);autoPos();try{grid?.destroy(false)}catch{};grid=null;await nextTick();initGrid();await persist();toast.success('Chart added!')}}catch{toast.error('Failed')}finally{chartBuilderLoading.value=false}
}

function trendClass(w: AnyData){return w.trend==='positive'?'bg-emerald-50 text-emerald-600 dark:bg-emerald-500/10 dark:text-emerald-400':w.trend==='negative'?'bg-rose-50 text-rose-600 dark:bg-rose-500/10 dark:text-rose-400':'text-slate-400'}
function trendIcon(w: AnyData){return w.trend==='positive'?'↗':w.trend==='negative'?'↘':'—'}
// ── Preview & Export ──
// ── SHARE STATE ──
const isSharing = ref(false)
const shareToken = ref<string|null>(null)
const showShareModal = ref(false)

async function loadShareStatus() {
  try {
    const r = await workspaceApi.getShareStatus(workspaceId)
    isSharing.value = r.is_shared
    shareToken.value = r.share_token
  } catch { /* columns may not exist yet, ignore */ }
}

async function toggleShare() {
  try {
    const r = await workspaceApi.toggleShare(workspaceId)
    isSharing.value = r.is_shared
    shareToken.value = r.share_token
    if (r.is_shared) {
      showShareModal.value = true
      toast.success('Dashboard sharing enabled!')
    } else {
      showShareModal.value = false
      toast.info('Dashboard sharing disabled')
    }
  } catch { toast.error('Failed to toggle sharing') }
}

function getShareDashboardUrl() {
  return `${window.location.origin}${window.location.pathname}#/shared/workspace/${shareToken.value}`
}

function getShareChatUrl() {
  return `${window.location.origin}${window.location.pathname}#/shared/workspace/${shareToken.value}/chat`
}

function getShareReportUrl() {
  return `${window.location.origin}${window.location.pathname}#/shared/workspace/${shareToken.value}/report`
}

function copyShareLink(url: string) {
  navigator.clipboard.writeText(url)
  toast.success('Share link copied to clipboard!')
}

function getEmbedSnippet() {
  const baseUrl = window.location.origin
  // Build without literal closing-script to prevent Vue SFC parser from breaking
  const openTag = '<' + 'script'
  const closeTag = '</' + 'script' + '>'
  return `${openTag} src="${baseUrl}/chatbot-widget.js" data-share-token="${shareToken.value}" data-base-url="${baseUrl}">${closeTag}`
}

const embedSnippetDisplay = computed(() => getEmbedSnippet())

function copyEmbedSnippet() {
  navigator.clipboard.writeText(getEmbedSnippet())
  toast.success('Embed code copied!')
}

const showExportMenu = ref(false)

function togglePreview(){
  isPreviewMode.value=!isPreviewMode.value
  if(isPreviewMode.value){
    clearSelection();
    isDashboardLocked.value=true;
    grid?.setStatic(true);
    sidebarOpen.value = false;
  } else {
    sidebarOpen.value = true;
  }
}

async function exportPNG(){
  showExportMenu.value=false
  const el=gridEl.value
  if(!el){toast.error('Nothing to export');return}
  toast.info('Generating PNG...')
  
  const originalZoom = zoomLevel.value
  zoomLevel.value = 100
  await nextTick()
  
  try{
    const {default:html2canvas}=await import('html2canvas-pro')
    const canvas=await html2canvas(el,{
      backgroundColor: activeTheme.value === 'none' ? '#ffffff' : (document.documentElement.classList.contains('dark') ? '#09090b' : '#ffffff'),
      scale: 2,
      useCORS: true,
      logging: false,
      scrollX: 0,
      scrollY: 0,
      windowWidth: el.scrollWidth,
      windowHeight: el.scrollHeight
    })
    const link=document.createElement('a')
    link.download=`workspace-dashboard-${workspaceId.slice(0,8)}.png`
    link.href=canvas.toDataURL('image/png')
    link.click()
    toast.success('PNG exported')
  }catch(e: unknown){const err = e as Error;toast.error('Export failed: '+err.message)}
  finally {
    zoomLevel.value = originalZoom
  }
}

async function exportPDF(){
  showExportMenu.value=false
  const el=gridEl.value
  if(!el){toast.error('Nothing to export');return}
  toast.info('Generating PDF...')
  
  const originalZoom = zoomLevel.value
  zoomLevel.value = 100
  await nextTick()
  
  try{
    const {default:html2canvas}=await import('html2canvas-pro')
    const {default:jsPDF}=await import('jspdf')
    const canvas=await html2canvas(el,{
      backgroundColor: activeTheme.value === 'none' ? '#ffffff' : (document.documentElement.classList.contains('dark') ? '#09090b' : '#ffffff'),
      scale: 2,
      useCORS: true,
      logging: false,
      scrollX: 0,
      scrollY: 0,
      windowWidth: el.scrollWidth,
      windowHeight: el.scrollHeight
    })
    // Use highly optimized, compressed JPEG instead of heavy raw PNG
    const imgData=canvas.toDataURL('image/jpeg', 0.75)
    const pdf=new jsPDF({
      orientation: canvas.width > canvas.height ? 'landscape' : 'portrait',
      unit: 'px',
      format: [canvas.width, canvas.height]
    })
    pdf.addImage(imgData, 'JPEG', 0, 0, canvas.width, canvas.height, undefined, 'FAST')
    pdf.save(`workspace-dashboard-${workspaceId.slice(0,8)}.pdf`)
    toast.success('PDF exported')
  }catch(e: unknown){const err = e as Error;toast.error('Export failed: '+err.message)}
  finally {
    zoomLevel.value = originalZoom
  }
}

function handleKeydown(e:KeyboardEvent){
  if(e.key==='Escape'){
    if(showCommandPalette.value){ showCommandPalette.value = false; return }
    if(isPreviewMode.value){isPreviewMode.value=false;return}
  }
  if((e.ctrlKey || e.metaKey) && e.key === 'k'){
    e.preventDefault()
    showCommandPalette.value = !showCommandPalette.value
    if(showCommandPalette.value) nextTick(() => commandInputRef.value?.focus())
    return
  }
  if(e.key==='p'&&!e.ctrlKey&&!e.metaKey&&!(e.target instanceof HTMLInputElement||e.target instanceof HTMLTextAreaElement)){togglePreview()}
}

onMounted(()=>{load();loadShareStatus();window.addEventListener('keydown',handleKeydown)})
onBeforeUnmount(()=>{try{grid?.destroy(false)}catch{};if(saveTimer)clearTimeout(saveTimer);window.removeEventListener('keydown',handleKeydown)})
</script>

<template>
<div :class="['dashboard-root relative flex gap-3 p-3 h-[calc(100vh-3.5rem)] bg-slate-50/50 dark:bg-zinc-950', ...canvasClass]" @click="clearSelection">
  <!-- Command Palette -->
  <div v-if="showCommandPalette" class="fixed inset-0 z-[100] flex items-start justify-center pt-[15vh]">
    <div class="fixed inset-0 bg-slate-900/40 backdrop-blur-sm" @click="showCommandPalette = false" />
    <div class="relative w-full max-w-lg rounded-2xl border border-slate-200 dark:border-white/10 bg-white dark:bg-slate-900 shadow-2xl overflow-hidden">
      <div class="flex items-center gap-3 border-b border-slate-100 dark:border-white/5 px-4 py-3">
        <iconify-icon icon="lucide:search" class="text-slate-400"/>
        <input ref="commandInputRef" v-model="commandQuery" placeholder="Search commands..." class="flex-1 bg-transparent text-sm outline-none" @keydown.enter="filteredCommands[0] && executeCommand(filteredCommands[0])" />
        <kbd class="rounded bg-slate-100 dark:bg-slate-800 px-1.5 py-0.5 text-[10px] text-slate-500">ESC</kbd>
      </div>
      <div class="max-h-72 overflow-y-auto p-2">
        <button v-for="cmd in filteredCommands" :key="cmd.id" @click="executeCommand(cmd)" class="flex w-full items-center gap-3 px-3 py-2 text-left text-sm rounded-xl transition hover:bg-slate-50 dark:hover:bg-white/5">
          <span class="w-6 text-center">{{ cmd.icon }}</span>
          <span class="flex-1 font-medium">{{ cmd.label }}</span>
        </button>
      </div>
    </div>
  </div>

    <LeftSidebar
    :visible="!isPreviewMode"
    :sidebar-open="sidebarOpen"
    :studio-tab="studioTab"
    :active-theme="activeTheme"
    :theme-keys="themeKeysList"
    :get-swatch-style="getSwatchStyle"
    :dashboard-design="boardDesign"
    :active-widget="activeWidget"
    :board-screens="boardScreens"
    :board-files="boardFiles"
    :active-screen-id="activeScreenId"
    @update:studio-tab="studioTab = $event"
    @set-theme="changeTheme"
    @update-widget-style="handleWidgetStyleUpdate"
    @update-dashboard-design="handleDashboardDesignUpdate"
  />

  <div class="flex-1 flex flex-col overflow-hidden rounded-2xl border border-slate-200/80 bg-white/70 shadow-sm dark:border-white/10 dark:bg-slate-900/50 backdrop-blur-md transition-all duration-500" :class="{'opacity-80 scale-[0.99] grayscale-[0.2]': isThemeChanging}">
    <!-- Header -->
    <header class="sticky top-0 z-30 flex items-center justify-between gap-4 border-b border-slate-200/80 dark:border-zinc-800 bg-white/80 dark:bg-zinc-900/80 backdrop-blur-xl px-6 py-2">
      <div class="flex items-center gap-4 min-w-0">
        <button v-if="!isPreviewMode" @click="toggleSidebar" class="shrink-0 p-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-zinc-800 transition" :title="sidebarOpen ? 'Collapse Sidebar' : 'Expand Sidebar'">
          <iconify-icon :icon="sidebarOpen ? 'lucide:panel-left-close' : 'lucide:panel-left-open'" class="text-lg text-slate-500"/>
        </button>
        <button @click="router.push(`/app/workspaces/${workspaceId}`)" class="shrink-0 p-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-zinc-800 transition"><iconify-icon icon="lucide:arrow-left" class="text-lg"/></button>
        <div class="flex items-center gap-2.5 min-w-0 bg-slate-50/50 dark:bg-white/5 px-3 py-1.5 rounded-xl border border-slate-200/50 dark:border-white/5">
          <div class="h-8 w-8 shrink-0 rounded-lg bg-indigo-100 dark:bg-indigo-500/20 flex items-center justify-center text-indigo-600 dark:text-indigo-400 border border-indigo-200/50 dark:border-indigo-500/20 shadow-sm">
            <iconify-icon icon="lucide:layout-dashboard" class="text-lg"/>
          </div>
          <div class="min-w-0">
            <h1 class="text-sm font-bold tracking-tight truncate text-slate-800 dark:text-white">Workspace Analytics</h1>
            <p class="text-[10px] text-slate-400 font-medium tabular-nums">{{ widgets.length }} active widgets</p>
          </div>
        </div>

        <!-- Zoom Controls -->
        <div class="hidden md:flex items-center gap-1 bg-slate-50/50 dark:bg-white/5 px-2 py-1 rounded-lg border border-slate-200/50 dark:border-white/5">
          <button @click="zoomOut" class="p-1 hover:bg-white dark:hover:bg-white/10 rounded text-slate-400 transition-colors" title="Zoom Out"><iconify-icon icon="lucide:minus" class="text-[10px]"/></button>
          <span class="text-[10px] font-bold text-slate-500 w-10 text-center uppercase tracking-tighter tabular-nums">{{ zoomLevel }}%</span>
          <button @click="zoomIn" class="p-1 hover:bg-white dark:hover:bg-white/10 rounded text-slate-400 transition-colors" title="Zoom In"><iconify-icon icon="lucide:plus" class="text-[10px]"/></button>
        </div>
      </div>
      <div class="flex items-center gap-1.5">
        <button v-if="!isPreviewMode" @click="isDashboardLocked=!isDashboardLocked;grid?.setStatic(isDashboardLocked)" class="p-2 rounded-lg hover:bg-slate-100 dark:hover:bg-zinc-800 transition" :title="isDashboardLocked?'Unlock':'Lock'"><iconify-icon :icon="isDashboardLocked?'lucide:lock':'lucide:unlock'" class="text-sm"/></button>
        <!-- Theme Swatches -->
        <div v-if="!isPreviewMode" class="flex items-center gap-0.5 border border-slate-200 dark:border-zinc-700 rounded-lg px-1.5 py-1">
          <button v-for="(th,tk) in THEMES" :key="tk" @click="changeTheme(tk)" :title="tk" :class="['h-4 w-4 rounded-full border-2 transition-transform hover:scale-125',activeTheme===tk?'border-slate-900 dark:border-white scale-110':'border-transparent']" :style="{backgroundColor:th.swatch}"/>
        </div>
        <!-- Preview Toggle -->
        <button @click="togglePreview" :class="['px-3 py-1.5 text-[11px] font-medium rounded-lg border transition',isPreviewMode?'border-amber-500 bg-amber-50 text-amber-700 dark:bg-amber-900/20 dark:text-amber-300':'border-slate-200 dark:border-zinc-700 hover:bg-slate-50 dark:hover:bg-zinc-800']" :title="isPreviewMode?'Exit Preview (Esc)':'Preview Mode (P)'"><iconify-icon :icon="isPreviewMode?'lucide:eye-off':'lucide:eye'" class="mr-1"/>{{ isPreviewMode?'Exit Preview':'Preview' }}</button>
        <!-- Export Menu -->
        <div class="relative">
          <button @click="showExportMenu=!showExportMenu" class="px-3 py-1.5 text-[11px] font-medium rounded-lg border border-slate-200 dark:border-zinc-700 hover:bg-slate-50 dark:hover:bg-zinc-800 transition"><iconify-icon icon="lucide:download" class="mr-1"/>Export</button>
          <div v-if="showExportMenu" class="absolute right-0 top-full mt-1 w-40 bg-white dark:bg-zinc-900 rounded-xl shadow-2xl border border-slate-200 dark:border-zinc-700 py-1 z-50">
            <button @click="exportPNG" class="w-full px-4 py-2 text-left text-xs hover:bg-slate-50 dark:hover:bg-zinc-800 flex items-center gap-2"><iconify-icon icon="lucide:image" class="text-sm"/>Export as PNG</button>
            <button @click="exportPDF" class="w-full px-4 py-2 text-left text-xs hover:bg-slate-50 dark:hover:bg-zinc-800 flex items-center gap-2"><iconify-icon icon="lucide:file-text" class="text-sm"/>Export as PDF</button>
          </div>
        </div>
        <button v-if="!isPreviewMode" @click="load(true)" class="px-3 py-1.5 text-[11px] font-medium rounded-lg border border-slate-200 dark:border-zinc-700 hover:bg-slate-50 dark:hover:bg-zinc-800 transition"><iconify-icon icon="lucide:refresh-cw" class="mr-1"/>Regenerate</button>
        <button v-if="!isPreviewMode" @click="chartBuilderOpen=true;ensureSchema()" class="px-3 py-1.5 text-[11px] font-medium rounded-lg border border-violet-200 dark:border-violet-700 text-violet-700 dark:text-violet-300 hover:bg-violet-50 dark:hover:bg-violet-900/30 transition"><iconify-icon icon="lucide:bar-chart-2" class="mr-1"/>Chart Builder</button>
        <button v-if="!isPreviewMode" @click="showCustomWidgetModal=true" class="px-3 py-1.5 text-[11px] font-medium rounded-lg border border-slate-200 dark:border-zinc-700 hover:bg-slate-50 dark:hover:bg-zinc-800 transition"><iconify-icon icon="lucide:code" class="mr-1"/>Custom SQL</button>
        <button v-if="!isPreviewMode" @click="router.push(`/app/workspaces/${workspaceId}/report`)" class="px-3 py-1.5 text-[11px] font-medium rounded-lg border border-slate-200 dark:border-zinc-700 hover:bg-slate-50 dark:hover:bg-zinc-800 transition"><iconify-icon icon="lucide:file-text" class="mr-1"/>Reports</button>
        <button v-if="!isPreviewMode" @click="showShareModal=true;loadShareStatus()" :class="['px-3 py-1.5 text-[11px] font-medium rounded-lg border transition',isSharing?'border-emerald-300 bg-emerald-50 text-emerald-700 dark:bg-emerald-900/20 dark:text-emerald-300 dark:border-emerald-700':'border-slate-200 dark:border-zinc-700 hover:bg-slate-50 dark:hover:bg-zinc-800']" :title="isSharing?'Sharing Active':'Share Dashboard'"><iconify-icon :icon="isSharing?'lucide:globe':'lucide:share-2'" class="mr-1"/>{{ isSharing?'Shared':'Share' }}</button>
        <div v-if="!isPreviewMode" class="relative">
          <button @click="showAddPopover=!showAddPopover" class="px-3 py-1.5 text-[11px] font-semibold rounded-lg bg-gradient-to-r from-indigo-600 to-violet-600 text-white hover:from-indigo-700 hover:to-violet-700 shadow-md shadow-indigo-500/20 transition"><iconify-icon icon="lucide:plus" class="mr-1"/>Add Widget</button>
          <div v-if="showAddPopover" class="absolute right-0 top-full mt-2 w-80 bg-white dark:bg-zinc-900 rounded-xl shadow-2xl border border-slate-200 dark:border-zinc-700 p-4 z-50">
            <p class="text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-2">Ask about your data</p>
            <textarea v-model="newWidgetQuery" rows="3" placeholder="e.g. Show total revenue by region" class="w-full text-xs rounded-lg border border-slate-200 dark:border-zinc-700 bg-slate-50 dark:bg-zinc-800 p-2.5 resize-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent" @keydown.enter.ctrl="addWidget"/>
            <div class="flex justify-end gap-2 mt-2">
              <button @click="showAddPopover=false" class="px-3 py-1.5 text-[10px] rounded-lg hover:bg-slate-100">Cancel</button>
              <button @click="addWidget" :disabled="isAddingWidget||!newWidgetQuery.trim()" class="px-3 py-1.5 text-[10px] font-semibold rounded-lg bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50"><iconify-icon v-if="isAddingWidget" icon="lucide:loader-2" class="mr-1 animate-spin"/>Generate</button>
            </div>
          </div>
        </div>
      </div>
    </header>

    <!-- Slicer Ribbon -->
    <div v-if="slicerDimensions.length && !isLoading" class="flex shrink-0 flex-wrap items-center gap-2 border-b border-slate-200/70 bg-white/55 px-4 py-1.5 backdrop-blur-sm dark:border-white/10 dark:bg-slate-900/25">
      <span class="mr-1 text-[9px] font-bold uppercase tracking-widest text-slate-500 dark:text-slate-400">
        <iconify-icon icon="lucide:filter" class="inline h-3 w-3 -mt-0.5 mr-0.5" />
        Slicers
      </span>
      <div v-for="dim in slicerDimensions" :key="dim.col" class="flex items-center gap-2">
        <label class="whitespace-nowrap text-[10px] font-medium text-slate-500 dark:text-slate-400 capitalize">{{ dim.label || dim.col.replace(/_/g, ' ') }}</label>
        <select
          :value="slicerValues[dim.col] || '__all__'"
          @change="onSlicerChange(dim.col, ($event.target as HTMLSelectElement).value)"
          class="h-7 max-w-[150px] rounded-lg border border-slate-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-2 text-[10px] font-medium outline-none focus:ring-2 focus:ring-indigo-500/20 transition"
        >
          <option value="__all__">All</option>
          <option v-for="val in (dim.sample_values || [])" :key="val" :value="val">{{ val }}</option>
        </select>
      </div>
      <button v-if="Object.keys(slicerValues).length" @click="clearSlicers" class="ml-auto text-[10px] font-bold text-indigo-600 dark:text-indigo-400 hover:underline">Clear Filters</button>
    </div>

    <!-- Loading -->
    <div v-if="isLoading" class="flex-1 flex items-center justify-center">
      <div class="text-center">
        <div class="relative mx-auto mb-5 h-16 w-16">
          <div class="absolute inset-0 animate-spin rounded-full border-[3px] border-indigo-100 border-t-indigo-500 dark:border-indigo-900 dark:border-t-indigo-400"/>
          <div class="absolute inset-2 animate-spin rounded-full border-[3px] border-violet-100 border-b-violet-500 dark:border-violet-900 dark:border-b-violet-400" style="animation-direction:reverse;animation-duration:1.2s"/>
        </div>
        <p class="text-sm font-semibold text-slate-700 dark:text-slate-300">Generating dashboard…</p>
        <p class="mt-1.5 text-xs text-slate-400">AI is analyzing your workspace schema</p>
      </div>
    </div>

    <!-- Empty -->
    <div v-else-if="!widgets.length" class="flex-1 flex items-center justify-center p-12">
      <div class="text-center max-w-sm">
        <div class="mx-auto mb-6 flex h-24 w-24 items-center justify-center rounded-3xl bg-gradient-to-br from-indigo-50 to-violet-50 dark:from-indigo-900/30 dark:to-violet-900/20">
          <iconify-icon icon="lucide:layout-dashboard" class="text-4xl text-indigo-300 dark:text-indigo-600"/>
        </div>
        <h3 class="text-xl font-semibold mb-2">No widgets yet</h3>
        <p class="text-sm text-slate-500 mb-6">Click "Regenerate" to auto-create your dashboard.</p>
        <button @click="load(true)" class="rounded-2xl bg-gradient-to-r from-indigo-600 to-violet-600 px-8 py-3 text-sm font-medium text-white shadow-lg shadow-indigo-500/20 hover:shadow-xl transition">Generate Dashboard</button>
      </div>
    </div>

    <!-- Grid -->
    <div v-else class="flex-1 overflow-auto relative custom-scrollbar canvas-container">
      <div ref="gridEl" class="grid-stack" :style="[themeCssVars(), { zoom: zoomLevel / 100 }]" :class="canvasClass">
        <div v-for="w in sortedWidgets" :key="w.id" :id="`widget-${w.id}`" class="grid-stack-item" :gs-id="w.id" :gs-x="w.gridX" :gs-y="w.gridY" :gs-w="w.gridW??3" :gs-h="w.gridH??2" :gs-min-w="2" :gs-min-h="2">
          <div class="grid-stack-item-content">
            <div :class="getWidgetCardClass(w)" :style="widgetBorderStyle(w)" @click.stop="selectWidget(w.id,$event)">

            <!-- Glow Effect for Chart Builders or Important metrics -->
            <div v-if="w.type === 'kpi' || w.type === 'summary'" class="absolute -inset-px bg-gradient-to-br from-indigo-500/10 to-transparent opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none" />

            <!-- Header (Full Drag Handle) -->
            <div :class="['flex items-center gap-2 border-b', !isDashboardLocked ? 'ws-drag cursor-grab active:cursor-grabbing' : '', w.type==='summary'?'px-5 py-2 border-indigo-100/80 dark:border-indigo-500/15':w.type==='kpi'?'px-4 py-1.5 border-slate-200/60 dark:border-white/[0.06]':'px-4 py-2 border-slate-200/60 dark:border-white/[0.06]']">
              <span v-if="w.type!=='kpi'&&w.type!=='summary'" class="inline-flex shrink-0 items-center rounded-md px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider" :style="badgeStyle(w)">{{ w.type==='chart'?(w.chartType||'chart'):w.type }}</span>
              <svg v-if="w.type==='summary'" class="h-4 w-4 shrink-0 text-indigo-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"/></svg>
              <h3 class="flex-1 min-w-0 uppercase leading-snug break-words truncate" 
                :class="[
                  w.type==='summary'?'text-[11px] font-bold tracking-wider text-indigo-700 dark:text-indigo-300':w.type==='kpi'?'text-[10px] font-bold tracking-wider text-slate-400 dark:text-slate-500':'text-[11px] font-semibold tracking-wide text-slate-500 dark:text-slate-400',
                  w.ui?.align === 'center' ? 'text-center' : w.ui?.align === 'right' ? 'text-right' : ''
                ]"
              >
                {{ getWidgetTitle(w) }}
              </h3>
              <span v-if="w.is_newly_added" class="shrink-0 rounded bg-emerald-500 px-1.5 py-0.5 text-[9px] font-bold text-white shadow-sm ring-1 ring-inset ring-emerald-600/20 mr-1 animate-pulse" title="Newly Generated via Incremental Pipeline">NEW!</span>
              <span v-if="w.source_table" class="shrink-0 max-w-[100px] truncate rounded px-1.5 py-0.5 text-[9px] font-mono border" :class="w.source_table==='_chat'?'bg-blue-50 dark:bg-blue-500/10 text-blue-600 dark:text-blue-400 border-blue-200 dark:border-blue-800':'bg-slate-100 dark:bg-zinc-800 text-slate-500 dark:text-slate-400 border-slate-200 dark:border-zinc-700'" :title="`Source: ${w.source_table}`">{{ w.source_table==='_cross_table'?'Cross-Table':w.source_table==='_incremental'?'Incremental':w.source_table==='_multi_table'?'Multi-Table':w.source_table==='_chat'?'Chat':w.source_table }}</span>
              <button v-if="w.sql_query&&!isDashboardLocked" @click.stop="refreshSingleWidget(w.id)" class="rounded p-1 text-slate-300 opacity-0 transition hover:bg-indigo-50 hover:text-indigo-500 group-hover:opacity-100" title="Refresh data"><iconify-icon :icon="refreshingWidgets.has(w.id)?'lucide:loader-2':'lucide:refresh-cw'" :class="{'animate-spin':refreshingWidgets.has(w.id)}" class="text-xs"/></button>
              <button v-if="!isDashboardLocked" @click.stop="removeWidget(w.id)" class="rounded p-1 text-slate-300 opacity-0 transition hover:bg-red-50 hover:text-red-500 group-hover:opacity-100"><svg class="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg></button>
            </div>

            <!-- Body -->
            <div class="flex flex-1 flex-col overflow-hidden min-h-0 relative" :class="w.type==='summary'?'px-5 py-3':w.type==='kpi'?'px-4 py-3':w.type==='list'?'pt-1 pb-3 px-3':'p-2 pt-1'">

              <!-- Summary -->
              <div v-if="w.type==='summary'" class="flex items-center gap-4">
                <div class="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-indigo-100 dark:bg-indigo-500/15"><svg class="h-5 w-5 text-indigo-600 dark:text-indigo-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"/></svg></div>
                <p class="text-sm leading-relaxed text-slate-600 dark:text-slate-300">{{ w.text }}</p>
              </div>

              <!-- KPI -->
              <div v-else-if="w.type==='kpi'" class="flex flex-1 flex-col justify-center gap-1 overflow-hidden" :class="w.ui?.align === 'center' ? 'items-center' : w.ui?.align === 'right' ? 'items-end' : ''">
                <p class="font-extrabold tracking-tight text-slate-900 dark:text-white truncate w-full" :class="[
                  String(w.value||'').length>12?'text-lg':String(w.value||'').length>8?'text-2xl':'text-3xl',
                  w.ui?.align === 'center' ? 'text-center' : w.ui?.align === 'right' ? 'text-right' : ''
                ]">{{ getKpiDisplayValue(w) }}</p>
                <div class="mt-1 flex items-center gap-2 overflow-hidden">
                  <span v-if="w.trend&&w.trend!=='neutral'" :class="['inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[11px] font-medium whitespace-nowrap',trendClass(w)]">{{ trendIcon(w) }} {{ w.subtitle||'' }}</span>
                  <span v-else-if="w.subtitle" class="text-[11px] font-medium text-slate-400 dark:text-slate-500 truncate">{{ w.subtitle }}</span>
                </div>
              </div>

              <!-- Chart -->
              <div v-else-if="w.type==='chart'" class="relative flex min-h-[140px] flex-1 flex-col overflow-hidden">
                <p v-if="w.description" class="px-2 pb-1 text-[11px] leading-snug text-slate-400 dark:text-slate-500 line-clamp-2">{{ w.description }}</p>
                <div v-if="!w.chartData || !w.chartData.series || w.chartData.series.length === 0" class="h-full flex items-center justify-center text-xs text-slate-400">
                  No data available
                </div>
                <div v-else class="min-h-0 flex-1"><v-chart v-if="echartOpts(w)" :option="echartOpts(w)" autoresize class="h-full w-full"/></div>
              </div>

              <!-- List -->
              <div v-else-if="w.type==='list'" class="h-full overflow-y-auto scrollbar-thin">
                <div v-if="!w.items || w.items.length === 0" class="h-full flex items-center justify-center text-xs text-slate-400">
                  No data available
                </div>
                <ul v-else class="space-y-1 pt-1">
                  <li v-for="(item,idx) in (((w.items||[]) as any[]).slice(0,10))" :key="idx" class="group/item flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition hover:bg-slate-50 dark:hover:bg-white/[0.04]">
                    <span class="flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-[11px] font-bold" :style="{backgroundColor:(idx<3?themePalette()[0]:themePalette()[2])+'22',color:idx<3?themePalette()[0]:themePalette()[2]}">{{ idx+1 }}</span>
                    <div class="flex flex-1 items-center gap-2 overflow-hidden">
                      <span class="truncate text-slate-700 dark:text-slate-300">{{ item.label }}</span>
                      <div class="ml-auto h-1.5 w-16 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
                        <div class="h-full rounded-full" :style="{width:`${Math.max(20,100-idx*12)}%`,backgroundColor:listBarColor(idx)}"/>
                      </div>
                    </div>
                    <span class="text-xs font-semibold text-slate-600 dark:text-slate-300 tabular-nums">{{ item.value }}</span>
                  </li>
                </ul>
              </div>

              <!-- Table -->
              <div v-else-if="w.type==='table'" class="h-full overflow-auto scrollbar-thin">
                <table class="w-full text-xs"><thead class="sticky top-0 bg-slate-50 dark:bg-zinc-800"><tr><th v-for="col in (w.columns||[])" :key="col" class="text-left px-2 py-1 font-semibold text-slate-500 uppercase text-[10px] tracking-wider">{{ col }}</th></tr></thead>
                <tbody><tr v-for="(row,ri) in (((w.data||[]) as any[]).slice(0,20))" :key="ri" class="border-t border-slate-100 dark:border-zinc-800"><td v-for="col in (w.columns||[])" :key="col" class="px-2 py-1 text-slate-600 dark:text-slate-300">{{ row[col] }}</td></tr></tbody></table>
              </div>

              <!-- Insight -->
              <div v-else-if="w.type==='insight'" class="flex flex-1 flex-col overflow-y-auto scrollbar-thin">
                <div class="flex gap-3">
                  <div class="w-1 shrink-0 rounded-full" :style="`background: linear-gradient(180deg, ${themePalette()[0]} 0%, ${themePalette()[2]} 100%); opacity: 0.6;`"/>
                  <div class="flex flex-col justify-center gap-2">
                    <p class="text-[13px] leading-relaxed text-slate-600 dark:text-slate-300">{{ w.text || 'No insight available' }}</p>
                    <span v-if="w.highlight" class="inline-flex items-center rounded-md px-2 py-0.5 text-[11px] font-semibold bg-indigo-50 text-indigo-700 dark:bg-indigo-500/10 dark:text-indigo-300">{{ w.highlight }}</span>
                  </div>
                </div>
              </div>

              <div v-else class="h-full flex items-center justify-center text-xs text-slate-400">{{ w.type }}</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>


    <!-- Screens Footer -->
    <footer v-if="!isPreviewMode" class="h-10 shrink-0 border-t border-slate-200/60 dark:border-white/[0.06] bg-white/50 dark:bg-slate-900/50 backdrop-blur-md flex items-center px-4 gap-1">
      <div class="flex items-center gap-1 bg-slate-100 dark:bg-white/5 p-1 rounded-lg">
        <button class="px-3 py-1 text-[11px] font-bold bg-white dark:bg-slate-800 text-indigo-600 dark:text-indigo-400 rounded shadow-sm border border-slate-200 dark:border-white/5">Dashboard</button>
        <button class="px-3 py-1 text-[11px] font-medium text-slate-500 hover:text-slate-700 dark:hover:text-slate-300 transition">Metrics</button>
      </div>
      <button class="h-6 w-6 flex items-center justify-center rounded-md hover:bg-slate-200 dark:hover:bg-white/10 text-slate-400 transition ml-1" title="Add screen"><iconify-icon icon="lucide:plus" class="text-xs"/></button>
    </footer>
  </div>

  <!-- Floating Toolbar -->
  <WidgetFloatingToolbar :visible="toolbarPos.visible" :top="toolbarPos.top" :left="toolbarPos.left" @duplicate="cloneWidget(activeWidgetId!)" @delete="removeWidget(activeWidgetId!)"/>

  <!-- Widget Style Chooser Modal -->
  <WidgetStyleChooserModal
    :open="showStyleChooser"
    :element-label="activeWidget?.title || 'Widget'"
    :selected-style-id="activeWidget?.ui?.variation || 'default'"
    :styles="[
      { id: 'default', name: 'Default', description: 'Standard balanced style' },
      { id: 'executive', name: 'Executive', description: 'Premium clean look with subtle accents' },
      { id: 'compact', name: 'Compact', description: 'Maximum information density' },
      { id: 'contrast', name: 'Contrast', description: 'High visibility for critical metrics' }
    ]"
    @close="showStyleChooser = false"
    @select-style="handleWidgetStyleUpdate({ variation: $event })"
    @apply="showStyleChooser = false"
  />

  <!-- Chart Builder Sidebar -->
  <Transition name="slide">
    <aside v-if="chartBuilderOpen" class="w-72 shrink-0 border-l border-slate-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 overflow-y-auto">
      <div class="p-4 space-y-5">
        <div class="flex items-center justify-between"><h3 class="text-sm font-bold">Chart Builder</h3><button @click="chartBuilderOpen=false" class="p-1 rounded hover:bg-slate-100 dark:hover:bg-zinc-800"><iconify-icon icon="lucide:x" class="text-sm"/></button></div>
        <div><label class="text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-2 block">◧ CHART TYPE</label><div class="grid grid-cols-3 gap-1.5"><button v-for="ct in CB_TYPES" :key="ct.id" @click="cbForm.chartType=ct.id" :class="['flex flex-col items-center gap-1.5 p-2.5 rounded-lg border text-[10px] transition',cbForm.chartType===ct.id?'border-violet-500 bg-violet-50 dark:bg-violet-900/20 text-violet-700 font-bold shadow-sm':'border-slate-200 dark:border-zinc-700 hover:border-slate-300']"><iconify-icon :icon="ct.icon" class="text-base"/>{{ ct.label }}</button></div></div>
        <div><label class="text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-1.5 block">◇ DIMENSION <span class="normal-case font-normal text-slate-400">(Qualitative)</span></label><select v-model="cbForm.dimension" class="w-full h-10 text-xs rounded-lg border border-slate-200 dark:border-zinc-700 bg-slate-50 dark:bg-zinc-800 px-3 py-2"><optgroup v-if="((chartSchema?.dimensions||[]) as any[]).filter((d:any)=>d.dim_type==='temporal').length" label="⏱ Temporal"><option v-for="d in ((chartSchema?.dimensions||[]) as any[]).filter((d:any)=>d.dim_type==='temporal')" :key="d.col" :value="d.col">{{ d.label || d.col }}</option></optgroup><optgroup label="◇ Categorical"><option v-for="d in ((chartSchema?.dimensions||[]) as any[]).filter((d:any)=>d.dim_type!=='temporal')" :key="d.col" :value="d.col">{{ d.label || d.col }}{{ d.cardinality ? ` (${d.cardinality})` : '' }}</option></optgroup></select><p class="mt-1 text-[9px] text-slate-400">X-axis / category grouping</p></div>
        <div><label class="text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-1.5 block">Σ AGGREGATION</label><div class="flex gap-1.5 flex-wrap"><button v-for="a in (selectedMeasureAggs || ['sum','avg','count','min','max'])" :key="a" @click="cbForm.aggregation=a" :class="['px-3 py-1.5 text-[10px] rounded-lg border transition',cbForm.aggregation===a?'border-violet-500 bg-violet-50 dark:bg-violet-900/20 font-bold':'border-slate-200 dark:border-zinc-700 hover:border-slate-300']">{{ a.charAt(0).toUpperCase()+a.slice(1) }}</button></div></div>
        <div v-if="cbForm.aggregation!=='count'"><label class="text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-1.5 block"># MEASURE <span class="normal-case font-normal text-slate-400">(Quantitative)</span></label><select v-model="cbForm.measure" class="w-full h-10 text-xs rounded-lg border border-slate-200 dark:border-zinc-700 bg-slate-50 dark:bg-zinc-800 px-3 py-2"><option v-for="m in ((chartSchema?.measures||[]) as any[])" :key="m.col" :value="m.col">{{ m.label || m.col }} ({{ m.data_type || 'numeric' }})</option></select><p class="mt-1 text-[9px] text-slate-400">Y-axis / numeric value</p></div>
        <div v-if="cbForm.dimension" class="rounded-xl border border-violet-100 dark:border-violet-800 bg-violet-50/50 dark:bg-violet-900/10 p-2.5 text-[10px] text-slate-600 dark:text-slate-300"><strong class="capitalize">{{ cbForm.chartType }}</strong> of <template v-if="cbForm.aggregation==='count'">count</template><template v-else>{{ cbForm.aggregation }} of {{ cbForm.measure||'...' }}</template> by <strong>{{ cbForm.dimension }}</strong></div>
        <button @click="buildChart" :disabled="!cbForm.dimension||chartBuilderLoading" class="w-full py-2.5 text-xs font-semibold rounded-xl bg-gradient-to-r from-violet-600 to-indigo-600 text-white hover:from-violet-700 hover:to-indigo-700 disabled:opacity-50 shadow-md shadow-violet-500/20 transition"><iconify-icon v-if="chartBuilderLoading" icon="lucide:loader-2" class="mr-1.5 animate-spin"/>Add Chart</button>
      </div>
    </aside>
  </Transition>

    <!-- Custom Widget Modal -->
    <div v-if="showCustomWidgetModal" class="fixed inset-0 z-[100] flex items-center justify-center bg-slate-900/50 backdrop-blur-sm">
      <div class="w-full max-w-xl rounded-2xl bg-white dark:bg-zinc-900 border border-slate-200 dark:border-zinc-800 shadow-2xl p-6 flex flex-col gap-4 relative">
        <button @click="showCustomWidgetModal=false" class="absolute top-4 right-4 p-1 hover:bg-slate-100 rounded-lg text-slate-500"><iconify-icon icon="lucide:x"/></button>
        <h2 class="text-lg font-bold text-slate-800 dark:text-white">Add Custom Widget (SQL)</h2>
        
        <div class="grid grid-cols-2 gap-4">
          <div class="col-span-2">
            <label class="text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-1.5 block">Widget Title</label>
            <input v-model="customWidgetForm.title" type="text" placeholder="e.g. Daily Revenue" class="w-full text-xs rounded-lg border border-slate-200 bg-slate-50 p-2.5 outline-none focus:border-indigo-500"/>
          </div>
          <div>
            <label class="text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-1.5 block">Widget Type</label>
            <select v-model="customWidgetForm.widgetType" class="w-full h-10 text-xs rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 outline-none">
              <option value="kpi">KPI Indicator</option>
              <option value="chart">Chart</option>
              <option value="list">Top / Bottom List</option>
            </select>
          </div>
          <div v-if="customWidgetForm.widgetType==='chart'">
            <label class="text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-1.5 block">Chart Type</label>
            <select v-model="customWidgetForm.chartType" class="w-full h-10 text-xs rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 outline-none">
              <option value="bar">Bar Chart</option>
              <option value="line">Line Chart</option>
              <option value="pie">Pie Chart</option>
              <option value="donut">Donut Chart</option>
              <option value="area">Area Chart</option>
            </select>
          </div>
          <div class="col-span-2">
            <label class="text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-1.5 block">Raw SQL Query</label>
            <textarea v-model="customWidgetForm.sqlQuery" rows="5" placeholder="SELECT column, SUM(value) FROM target_table GROUP BY column" class="w-full text-xs font-mono rounded-lg border border-slate-200 bg-slate-50 p-2.5 resize-none outline-none focus:border-indigo-500"/>
          </div>
        </div>

        <div class="flex justify-end gap-3 mt-2">
          <button @click="showCustomWidgetModal=false" class="px-4 py-2 text-xs font-medium text-slate-600 hover:bg-slate-100 rounded-xl">Cancel</button>
          <button @click="addCustomWidget" :disabled="isAddingCustomWidget || !customWidgetForm.title || !customWidgetForm.sqlQuery" class="px-4 py-2 text-xs font-semibold bg-indigo-600 text-white rounded-xl hover:bg-indigo-700 disabled:opacity-50 flex items-center">
            <iconify-icon v-if="isAddingCustomWidget" icon="lucide:loader-2" class="mr-2 animate-spin"/> Add Widget
          </button>
        </div>
      </div>
    </div>

    <!-- Share Dashboard Modal -->
    <Teleport to="body">
    <div v-if="showShareModal" class="fixed inset-0 z-[200] flex items-center justify-center bg-slate-900/60 backdrop-blur-sm" @click.self="showShareModal=false">
      <div class="w-full max-w-lg rounded-2xl bg-white dark:bg-zinc-900 border border-slate-200 dark:border-zinc-800 shadow-2xl overflow-hidden">
        <!-- Header -->
        <div class="flex items-center justify-between px-6 py-4 bg-gradient-to-r from-emerald-500/10 to-teal-500/10 dark:from-emerald-900/30 dark:to-teal-900/20 border-b border-slate-200 dark:border-zinc-800">
          <div class="flex items-center gap-3">
            <div class="h-10 w-10 flex items-center justify-center rounded-xl bg-emerald-100 dark:bg-emerald-900/40 text-emerald-600 dark:text-emerald-400">
              <iconify-icon icon="lucide:share-2" class="text-lg"/>
            </div>
            <div>
              <h2 class="text-base font-bold text-slate-800 dark:text-white">Share Workspace</h2>
              <p class="text-[11px] text-slate-500">Allow anyone with the link to view this workspace</p>
            </div>
          </div>
          <button @click="showShareModal=false" class="p-2 hover:bg-slate-100 dark:hover:bg-zinc-800 rounded-lg transition"><iconify-icon icon="lucide:x" class="text-sm text-slate-500"/></button>
        </div>

        <div class="p-6 space-y-5">
          <!-- Share Toggle -->
          <div class="flex items-center justify-between p-4 rounded-xl bg-slate-50 dark:bg-zinc-800/50 border border-slate-200 dark:border-zinc-700">
            <div>
              <p class="text-sm font-semibold text-slate-700 dark:text-slate-200">Public Sharing</p>
              <p class="text-[11px] text-slate-500">{{ isSharing ? 'Anyone with the link can view' : 'Dashboard is private' }}</p>
            </div>
            <button @click="toggleShare" :class="['relative inline-flex h-7 w-12 flex-shrink-0 rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out cursor-pointer focus:outline-none', isSharing ? 'bg-emerald-500' : 'bg-slate-300 dark:bg-zinc-600']">
              <span :class="['inline-block h-6 w-6 transform rounded-full bg-white shadow ring-0 transition-transform duration-200 ease-in-out', isSharing ? 'translate-x-5' : 'translate-x-0']"/>
            </button>
          </div>

          <template v-if="isSharing && shareToken">
            <!-- Dashboard Link -->
            <div class="space-y-2">
              <label class="text-[10px] font-bold text-slate-500 uppercase tracking-wider flex items-center gap-1.5">
                <iconify-icon icon="lucide:layout-dashboard" class="text-xs"/>Dashboard Link
              </label>
              <div class="flex gap-2">
                <input :value="getShareDashboardUrl()" readonly class="flex-1 text-xs font-mono rounded-lg border border-slate-200 dark:border-zinc-700 bg-slate-50 dark:bg-zinc-800 px-3 py-2.5 select-all"/>
                <button @click="copyShareLink(getShareDashboardUrl())" class="px-4 py-2.5 text-xs font-semibold rounded-lg bg-emerald-600 text-white hover:bg-emerald-700 transition flex items-center gap-1.5 shrink-0"><iconify-icon icon="lucide:copy"/>Copy</button>
              </div>
            </div>

            <!-- Chat Link -->
            <div class="space-y-2">
              <label class="text-[10px] font-bold text-slate-500 uppercase tracking-wider flex items-center gap-1.5">
                <iconify-icon icon="lucide:message-circle" class="text-xs"/>Chat Link
              </label>
              <div class="flex gap-2">
                <input :value="getShareChatUrl()" readonly class="flex-1 text-xs font-mono rounded-lg border border-slate-200 dark:border-zinc-700 bg-slate-50 dark:bg-zinc-800 px-3 py-2.5 select-all"/>
                <button @click="copyShareLink(getShareChatUrl())" class="px-4 py-2.5 text-xs font-semibold rounded-lg bg-indigo-600 text-white hover:bg-indigo-700 transition flex items-center gap-1.5 shrink-0"><iconify-icon icon="lucide:copy"/>Copy</button>
              </div>
            </div>

            <!-- Report Link -->
            <div class="space-y-2">
              <label class="text-[10px] font-bold text-slate-500 uppercase tracking-wider flex items-center gap-1.5">
                <iconify-icon icon="lucide:file-text" class="text-xs"/>Report Link
              </label>
              <div class="flex gap-2">
                <input :value="getShareReportUrl()" readonly class="flex-1 text-xs font-mono rounded-lg border border-slate-200 dark:border-zinc-700 bg-slate-50 dark:bg-zinc-800 px-3 py-2.5 select-all"/>
                <button @click="copyShareLink(getShareReportUrl())" class="px-4 py-2.5 text-xs font-semibold rounded-lg bg-purple-600 text-white hover:bg-purple-700 transition flex items-center gap-1.5 shrink-0"><iconify-icon icon="lucide:copy"/>Copy</button>
              </div>
            </div>

            <!-- Embed Code -->
            <div class="space-y-2">
              <label class="text-[10px] font-bold text-slate-500 uppercase tracking-wider flex items-center gap-1.5">
                <iconify-icon icon="lucide:code" class="text-xs"/>Embed Chatbot Widget
              </label>
              <div class="relative">
                <pre class="text-[10px] font-mono rounded-lg border border-slate-200 dark:border-zinc-700 bg-slate-50 dark:bg-zinc-800 p-3 overflow-x-auto whitespace-pre-wrap break-all text-slate-600 dark:text-slate-300">{{ embedSnippetDisplay }}</pre>
                <button @click="copyEmbedSnippet" class="absolute top-2 right-2 p-1.5 rounded-md bg-white dark:bg-zinc-700 border border-slate-200 dark:border-zinc-600 hover:bg-slate-100 dark:hover:bg-zinc-600 transition" title="Copy embed code"><iconify-icon icon="lucide:copy" class="text-xs"/></button>
              </div>
            </div>
          </template>

          <!-- Info -->
          <div v-if="!isSharing" class="flex items-start gap-3 p-4 rounded-xl bg-amber-50 dark:bg-amber-900/10 border border-amber-200 dark:border-amber-800/30">
            <iconify-icon icon="lucide:shield" class="text-amber-500 mt-0.5"/>
            <p class="text-xs text-amber-700 dark:text-amber-300">Enable sharing to generate public links. Shared dashboards are read-only and do not require login.</p>
          </div>
        </div>
      </div>
    </div>
    </Teleport>
  </div>
</template>

<style scoped>
/* KPI widgets should not scroll */
.grid-stack-item[gs-w="3"][gs-h="2"] .widget-card,
.grid-stack-item[gs-h="2"] .widget-card {
  overflow: hidden !important;
}

.grid-stack {
  margin-top: -12px !important;
  margin-left: -12px !important;
  margin-right: -12px !important;
  min-height: 100%;
}

.grid-stack-item-content {
  padding: 0 !important; /* Let GridStack margin handle the spacing */
  background-clip: padding-box;
  overflow: visible !important; /* Prevent scrollbars when widget translates on hover */
}

.grid-stack.design-card-soft .widget-card {
  border-radius: 20px;
  box-shadow: 0 10px 30px -5px rgba(0,0,0,0.08); /* More depth */
}

.grid-stack.design-card-flat .widget-card {
  border-radius: 4px; /* Slightly sharper but still modern */
}

.grid-stack.design-texture-gradient {
  background: linear-gradient(135deg, rgba(var(--theme-accent-rgb), 0.03) 0%, transparent 100%);
}

/* 3D and Effect Styles */
.widget-card {
  transform: perspective(1000px) rotateX(0deg) rotateY(0deg);
  transition: 
    transform 0.5s cubic-bezier(0.175, 0.885, 0.32, 1.275), 
    box-shadow 0.4s ease, 
    border-color 0.4s ease, 
    background-color 0.4s ease;
  backface-visibility: hidden;
}

.widget-card:hover {
  transform: perspective(1000px) rotateX(1.5deg) translateY(-6px);
  box-shadow: 
    0 20px 40px -10px rgba(0, 0, 0, 0.12),
    0 0 15px 0 var(--theme-soft);
}

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

.widget-card:hover {
  transform: perspective(1000px) rotateX(2deg) rotateY(-1deg) translateY(-8px);
  box-shadow: 
    0 25px 50px -12px rgba(0, 0, 0, 0.15),
    0 0 20px 0 var(--theme-soft);
}

.widget-card::after {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(135deg, rgba(255,255,255,0.1) 0%, rgba(255,255,255,0) 100%);
  pointer-events: none;
  opacity: 0;
  transition: opacity 0.3s ease;
}

.widget-card:hover::after {
  opacity: 1;
}

.widget-card::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 2px;
  background: linear-gradient(90deg, transparent, var(--theme-accent, #6366f1), transparent);
  opacity: 0;
  transition: opacity 0.3s ease;
}

.widget-card:hover::before {
  opacity: 1;
}

.grid-stack.design-card-glass .widget-card {
  backdrop-filter: blur(12px);
  background: rgba(255, 255, 255, 0.65);
  border-color: rgba(255, 255, 255, 0.4);
  box-shadow: 0 8px 32px 0 rgba(31, 38, 135, 0.07);
}

.dark .grid-stack.design-card-glass .widget-card {
  background: rgba(15, 23, 42, 0.65);
  border-color: rgba(255, 255, 255, 0.1);
}

.grid-stack.design-texture-dots {
  background-image: radial-gradient(var(--theme-accent) 1px, transparent 1px) !important;
  background-size: 24px 24px !important;
  background-position: center;
  background-attachment: local;
}

.grid-stack.design-texture-grid {
  background-image: 
    linear-gradient(to right, rgba(var(--theme-accent-rgb), 0.1) 1px, transparent 1px),
    linear-gradient(to bottom, rgba(var(--theme-accent-rgb), 0.1) 1px, transparent 1px) !important;
  background-size: 50px 50px !important;
  background-attachment: local;
}

.grid-stack.design-texture-gradient {
  background: linear-gradient(135deg, rgba(var(--theme-accent-rgb), 0.05) 0%, transparent 100%) !important;
  background-attachment: local;
}

/* ── DENSITY SYSTEM ── */
.grid-stack.design-density-compact {
  gap: 4px !important;
}
.grid-stack.design-density-compact .grid-stack-item-content {
  padding: 4px !important;
}

.grid-stack.design-density-airy {
  gap: 24px !important;
}
.grid-stack.design-density-airy .grid-stack-item-content {
  padding: 24px !important;
}

.canvas-container {
  padding: 0 32px 100px 32px;
}

.custom-scrollbar::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}
.custom-scrollbar::-webkit-scrollbar-track {
  background: transparent;
}
.custom-scrollbar::-webkit-scrollbar-thumb {
  background: #e2e8f0;
  border-radius: 10px;
}
.dark .custom-scrollbar::-webkit-scrollbar-thumb {
  background: #334155;
}

.slide-enter-active,.slide-leave-active{transition:transform .25s ease,opacity .25s ease}
.slide-enter-from,.slide-leave-to{transform:translateX(100%);opacity:0}
/* Background pattern */
.bg-dots{background-image:radial-gradient(rgba(0,0,0,0.06) 1px,transparent 1px);background-size:20px 20px}
.dark .bg-dots{background-image:radial-gradient(rgba(255,255,255,0.04) 1px,transparent 1px)}

/* ── DESIGN SYSTEM TEXTURES ────────────────────────────────────── */
.design-texture-dots .bg-dots { background-image: radial-gradient(rgba(0,0,0,0.08) 1px, transparent 1px); background-size: 16px 16px; }
.dark .design-texture-dots .bg-dots { background-image: radial-gradient(rgba(255,255,255,0.06) 1px, transparent 1px); }
.design-texture-grid .bg-dots { background-image: linear-gradient(rgba(0,0,0,0.04) 1px, transparent 1px), linear-gradient(90deg, rgba(0,0,0,0.04) 1px, transparent 1px); background-size: 20px 20px; }
.dark .design-texture-grid .bg-dots { background-image: linear-gradient(rgba(255,255,255,0.03) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.03) 1px, transparent 1px); }
.design-texture-gradient .bg-dots { background: radial-gradient(circle at 0% 0%, rgba(var(--ts1), 0.05) 0%, transparent 50%), radial-gradient(circle at 100% 100%, rgba(var(--ts5), 0.05) 0%, transparent 50%); }

/* ── CARD STYLES ──────────────────────────────────────────────── */
.design-card-soft .widget-card { border-radius: 20px; box-shadow: 0 10px 30px -10px rgba(0,0,0,0.1); }
.design-card-glass .widget-card { background: rgba(255, 255, 255, 0.7); backdrop-filter: blur(12px); border: 1px solid rgba(255, 255, 255, 0.3); }
.dark .design-card-glass .widget-card { background: rgba(15, 23, 42, 0.6); border: 1px solid rgba(255, 255, 255, 0.05); }

/* ── DENSITY ─────────────────────────────────────────────────── */
.grid-stack-item {
  padding: 18px !important; /* Increased default breathing space from all sides */
  transition: padding 0.3s ease;
}
.design-density-compact .grid-stack-item { padding: 8px !important; }
.design-density-airy .grid-stack-item { padding: 32px !important; }

/* ── PREVIEW MODE ────────────────────────────────────────────── */
.is-preview .bg-dots { background: none !important; }
.is-preview .dashboard-root { padding: 0 !important; }
</style>
