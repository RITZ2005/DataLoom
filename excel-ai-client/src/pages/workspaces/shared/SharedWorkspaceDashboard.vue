<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { useRoute } from 'vue-router'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { PieChart, BarChart, LineChart, FunnelChart, TreemapChart, ScatterChart } from 'echarts/charts'
import { TitleComponent, TooltipComponent, LegendComponent, GridComponent, DataZoomComponent } from 'echarts/components'
import VChart from 'vue-echarts'
import { GridStack } from 'gridstack'
import 'gridstack/dist/gridstack.min.css'
import workspaceApi from '@/services/workspaceApi'

use([CanvasRenderer, PieChart, BarChart, LineChart, FunnelChart, TreemapChart, ScatterChart,
     TitleComponent, TooltipComponent, LegendComponent, GridComponent, DataZoomComponent])

const route = useRoute()
const token = computed(() => route.params.token as string)

const isLoading = ref(true)
const errorMsg = ref('')
const workspaceName = ref('')
const dashboardName = ref('')
const widgets = ref<any[]>([])
const layoutJson = ref<any>(null)
const gridReady = ref(false)

type AnyData = Record<string, any>
let grid: any = null
const gridEl = ref<HTMLElement|null>(null)

// ── THEME ──
const isDark = ref(false)
function initTheme() {
  const saved = localStorage.getItem('shared-theme')
  isDark.value = saved ? saved === 'dark' : window.matchMedia('(prefers-color-scheme: dark)').matches
  document.documentElement.classList.toggle('dark', isDark.value)
}
function toggleTheme() {
  isDark.value = !isDark.value
  localStorage.setItem('shared-theme', isDark.value ? 'dark' : 'light')
  document.documentElement.classList.toggle('dark', isDark.value)
}

// ── COLORS & THEMES ──
const COLOR_THEMES: Record<string, { swatch: string; bg: string; text: string; chart: string[] }> = {
  indigo: { swatch: '#6366f1', bg: 'bg-indigo-50 dark:bg-indigo-950/30', text: 'text-indigo-600 dark:text-indigo-400', chart: ['#4338ca', '#4f46e5', '#6366f1', '#818cf8', '#a5b4fc'] },
  violet: { swatch: '#8b5cf6', bg: 'bg-violet-50 dark:bg-violet-950/30', text: 'text-violet-600 dark:text-violet-400', chart: ['#6d28d9', '#7c3aed', '#8b5cf6', '#a78bfa', '#c4b5fd'] },
  emerald: { swatch: '#10b981', bg: 'bg-emerald-50 dark:bg-emerald-950/30', text: 'text-emerald-600 dark:text-emerald-400', chart: ['#047857', '#059669', '#10b981', '#34d399', '#6ee7b7'] },
  amber: { swatch: '#f59e0b', bg: 'bg-amber-50 dark:bg-amber-950/30', text: 'text-amber-600 dark:text-amber-400', chart: ['#b45309', '#d97706', '#f59e0b', '#fbbf24', '#fcd34d'] },
  rose: { swatch: '#f43f5e', bg: 'bg-rose-50 dark:bg-rose-950/30', text: 'text-rose-600 dark:text-rose-400', chart: ['#be123c', '#e11d48', '#f43f5e', '#fb7185', '#fda4af'] },
  cyan: { swatch: '#06b6d4', bg: 'bg-cyan-50 dark:bg-cyan-950/30', text: 'text-cyan-600 dark:text-cyan-400', chart: ['#0e7490', '#0891b2', '#06b6d4', '#22d3ee', '#67e8f9'] },
  mokkup1: { swatch: '#4338ca', bg: 'bg-indigo-50 dark:bg-indigo-950/30', text: 'text-indigo-700 dark:text-indigo-300', chart: ['#20156f', '#3f34b8', '#6a60d9', '#8f89e6', '#547bc7'] },
  holidaySpark: { swatch: '#d4645e', bg: 'bg-rose-50 dark:bg-rose-950/20', text: 'text-rose-600 dark:text-rose-300', chart: ['#d0605a', '#e07b76', '#98c97e', '#ee9992', '#86b96d'] },
  mokkup2: { swatch: '#4b3fb6', bg: 'bg-violet-50 dark:bg-violet-950/30', text: 'text-violet-700 dark:text-violet-300', chart: ['#4f44b9', '#746bdb', '#948fde', '#e69488', '#d57665'] },
  rustic: { swatch: '#8b4e25', bg: 'bg-amber-50 dark:bg-amber-950/20', text: 'text-amber-700 dark:text-amber-300', chart: ['#884e24', '#d78d59', '#f3ba90', '#f8dc98', '#efbd47'] }
}

const activeTheme = ref(localStorage.getItem('shared-active-theme') || 'indigo')
const themePalette = computed(() => COLOR_THEMES[activeTheme.value]?.chart || COLOR_THEMES.indigo.chart)

function changeTheme(tk: string) {
  activeTheme.value = tk
  localStorage.setItem('shared-active-theme', tk)
}

// ── AUTO POSITION ──
function autoPos() {
  const COLS = 12
  const colH = new Array(COLS).fill(0)
  const order: Record<string, number> = { summary: -1, kpi: 0, insight: 1, list: 2, chart: 3 }
  const sorted = [...widgets.value].sort((a, b) => (order[a.type] ?? 3) - (order[b.type] ?? 3))
  for (const w of sorted) {
    const ww = Math.min(w.gridW || (w.type === 'summary' ? 12 : w.type === 'kpi' ? 3 : w.type === 'insight' ? 4 : 6), COLS)
    const hh = w.gridH || (w.type === 'kpi' ? 2 : w.type === 'insight' ? 2 : 3)
    let bestX = 0, bestY = Infinity
    for (let x = 0; x <= COLS - ww; x++) {
      let maxH = 0
      for (let c = x; c < x + ww; c++) maxH = Math.max(maxH, colH[c])
      if (maxH < bestY) { bestY = maxH; bestX = x }
    }
    w.gridX = bestX; w.gridY = bestY; w.gridW = ww; w.gridH = hh
    for (let c = bestX; c < bestX + ww; c++) colH[c] = bestY + hh
  }
}

function initGrid() {
  if (!widgets.value.length || !gridEl.value) return
  try { grid?.destroy(false) } catch {}

  grid = GridStack.init({
    column: 12, cellHeight: 80, minRow: 1, margin: 8,
    animate: true, float: false,
    draggable: { handle: '.shared-drag-handle' },
    resizable: { handles: 'e,se,s', autoHide: true }
  }, gridEl.value)

  grid.opts.marginTop = 0
  grid.opts.marginBottom = 0
  grid.opts.marginLeft = 0
  grid.opts.marginRight = 0

  grid.on('change', (_e: AnyData, items: AnyData) => {
    items?.forEach((it: AnyData) => {
      const w = widgets.value.find(x => x.id === String(it.id))
      if (w) { w.gridX = it.x; w.gridY = it.y; w.gridW = it.w; w.gridH = it.h }
    })
  })
}

// ── CHART OPTS ──
function getSeriesVal(series: any[], i: number): number {
  const s0 = series?.[0]
  if (s0 == null) return 0
  if (typeof s0 === 'object' && !Array.isArray(s0) && s0.data) { const v = Number(s0.data[i]); return isNaN(v) ? 0 : v }
  if (typeof s0 === 'number' || typeof s0 === 'string') { const v = Number(series[i]); return isNaN(v) ? 0 : v }
  return 0
}

function echartOpts(w: AnyData) {
  const cd = w.chartData || {}
  const labels: string[] = cd.labels || []
  const series: any[] = cd.series || []
  const ct = (w.chartType || w.chart_type || 'bar').toLowerCase()
  const tc = isDark.value ? '#94a3b8' : '#475569'
  const gl = isDark.value ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)'

  const base: any = {
    color: themePalette.value, backgroundColor: 'transparent',
    tooltip: { trigger: ct === 'pie' || ct === 'donut' ? 'item' : 'axis', confine: true },
    legend: { show: ct === 'pie' || ct === 'donut' ? labels.length <= 8 : series.length > 1, bottom: 0, textStyle: { color: tc, fontSize: 10 } },
    grid: { left: 48, right: 16, top: 24, bottom: 32 }
  }

  if (['pie','donut'].includes(ct)) {
    return { ...base, series: [{ type: 'pie', radius: ct === 'donut' ? ['45%','70%'] : '65%', center: ['50%','45%'],
      data: labels.map((l,i) => ({ name: l, value: getSeriesVal(series, i) })),
      label: { fontSize: 10, show: labels.length <= 6, color: tc },
      itemStyle: { borderRadius: ct === 'donut' ? 4 : 0, borderColor: isDark.value ? '#18181b' : '#fff', borderWidth: 2 }
    }]}
  }
  if (ct === 'funnel') {
    return { ...base, series: [{ type: 'funnel', left: '10%', width: '80%',
      data: labels.map((l,i) => ({ name: l, value: getSeriesVal(series, i) })), label: { color: tc }
    }]}
  }
  if (ct === 'treemap') {
    return { ...base, series: [{ type: 'treemap', roam: false, breadcrumb: { show: false },
      data: labels.map((l,i) => ({ name: l, value: getSeriesVal(series, i) }))
    }]}
  }

  const catAxis = { type: 'category', data: labels, axisLabel: { fontSize: 9, color: tc, rotate: labels.length > 8 ? 30 : 0 }, axisLine: { lineStyle: { color: gl } } }
  const valAxis = { type: 'value', axisLabel: { fontSize: 9, color: tc }, splitLine: { lineStyle: { color: gl, type: 'dashed' } } }
  const isH = w.horizontal === true
  base.xAxis = isH ? valAxis : catAxis
  base.yAxis = isH ? catAxis : valAxis

  if (ct === 'area') {
    base.series = series.map((s: any, i: number) => ({ name: s.name || 'Value', type: 'line', data: s.data || [], smooth: true, areaStyle: { opacity: 0.15 }, itemStyle: { color: themePalette.value[i % themePalette.value.length] } }))
    return base
  }
  const sType = ct === 'line' ? 'line' : ct === 'scatter' ? 'scatter' : 'bar'
  base.series = series.map((s: any, i: number) => ({ name: s.name || 'Value', type: sType, data: (s.data || []).map((v: any) => { const n = Number(v); return isNaN(n) ? 0 : n }), smooth: ct === 'line', barMaxWidth: 40, itemStyle: { color: themePalette.value[i % themePalette.value.length], borderRadius: sType === 'bar' ? [4,4,0,0] : undefined } }))
  return base
}

function formatKpi(w: AnyData) {
  const v = w.value
  if (v == null || v === '') return '—'
  const n = Number(String(v).replace(/[₹$€,\s]/g, ''))
  if (isNaN(n)) return v
  const fmt = w.format_hint || ''
  if (fmt === 'currency' || String(v).includes('₹')) return '₹' + n.toLocaleString('en-IN', { maximumFractionDigits: 2 })
  if (fmt === 'percentage') return n.toFixed(1) + '%'
  return n.toLocaleString('en-IN', { maximumFractionDigits: 2 })
}

// ── LOAD ──
async function loadDashboard() {
  isLoading.value = true
  gridReady.value = false
  errorMsg.value = ''
  try {
    const data = await workspaceApi.getSharedWorkspaceDashboard(token.value)
    workspaceName.value = data.workspace_name || 'Workspace'
    dashboardName.value = data.dashboard_name || 'Dashboard'
    layoutJson.value = data.layout_json || null
    const ws = (data.widgets || []).map((w: AnyData) => {
      if (!w.chartType && w.chart_type) w.chartType = w.chart_type
      return w
    })

    // Assign grid positions BEFORE rendering so Vue template has correct gs-x/gs-y
    const hasLayout = ws.some((w: AnyData) => typeof w.gridX === 'number' && typeof w.gridY === 'number')
    if (!hasLayout) {
      // Temporarily assign to ref so autoPos can work on it
      widgets.value = ws
      autoPos()
    } else {
      widgets.value = ws
    }

    // Now show the grid — Vue renders with correct positions
    isLoading.value = false
    await nextTick()
    await nextTick()
    initGrid()
    // Give GridStack time to compute layout before rendering charts
    setTimeout(() => { gridReady.value = true }, 200)
  } catch (e: any) {
    errorMsg.value = e?.response?.data?.detail || 'This shared dashboard is not available.'
    isLoading.value = false
  }
}

onMounted(() => { initTheme(); loadDashboard() })
onBeforeUnmount(() => { try { grid?.destroy(false) } catch {} })
</script>

<template>
  <div :class="['min-h-screen transition-colors duration-300', isDark ? 'bg-zinc-950 text-white' : 'bg-gradient-to-br from-slate-50 via-white to-indigo-50/30 text-slate-900']">
    <!-- Header -->
    <header :class="['sticky top-0 z-50 backdrop-blur-xl border-b transition-colors', isDark ? 'bg-zinc-900/80 border-white/[0.06]' : 'bg-white/80 border-slate-200/60']">
      <div class="max-w-[1440px] mx-auto px-6 py-3 flex items-center justify-between">
        <div class="flex items-center gap-3">
          <div class="h-9 w-9 flex items-center justify-center rounded-xl bg-gradient-to-br from-indigo-500 to-violet-600 text-white text-sm font-bold shadow-md shadow-indigo-500/20">W</div>
          <div>
            <h1 :class="['text-sm font-bold', isDark ? 'text-white' : 'text-slate-800']">{{ workspaceName }}</h1>
            <p class="text-[10px] text-slate-400">{{ dashboardName }} · Shared Dashboard</p>
          </div>
        </div>
        <div class="flex items-center gap-3">
          <!-- Color Theme Selection -->
          <div class="flex items-center gap-1 bg-slate-100/60 dark:bg-zinc-800/60 rounded-xl px-2.5 py-1 border border-slate-200/50 dark:border-white/[0.05]">
            <span class="text-[9px] font-bold uppercase tracking-wider text-slate-400 dark:text-zinc-500 mr-1.5 hidden sm:inline">Theme:</span>
            <div class="flex items-center gap-1">
              <button
                v-for="(th, tk) in COLOR_THEMES"
                :key="tk"
                @click="changeTheme(tk)"
                :title="tk.charAt(0).toUpperCase() + tk.slice(1)"
                :class="['h-4.5 w-4.5 rounded-full border-2 transition-all hover:scale-125 shrink-0', activeTheme === tk ? 'border-slate-800 dark:border-white scale-110 shadow-sm' : 'border-transparent']"
                :style="{ backgroundColor: th.swatch }"
              />
            </div>
          </div>

          <!-- Light/Dark Toggle -->
          <button @click="toggleTheme" :class="['relative h-8 w-16 rounded-full border-2 transition-all flex items-center', isDark ? 'bg-zinc-800 border-zinc-600' : 'bg-amber-50 border-amber-200']">
            <span :class="['absolute h-6 w-6 rounded-full flex items-center justify-center text-xs transition-all shadow-md', isDark ? 'translate-x-[30px] bg-indigo-500 text-white' : 'translate-x-[2px] bg-amber-400 text-amber-900']">
              <svg v-if="isDark" xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>
              <svg v-else xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>
            </span>
          </button>
          <span :class="['inline-flex items-center gap-1.5 px-3 py-1 text-[10px] font-semibold rounded-full border', isDark ? 'bg-emerald-900/20 text-emerald-300 border-emerald-800' : 'bg-emerald-50 text-emerald-700 border-emerald-200']">
            <span class="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse"/>Read Only
          </span>
        </div>
      </div>
    </header>

    <!-- Loading -->
    <div v-if="isLoading" class="flex items-center justify-center" style="min-height:60vh">
      <div class="text-center">
        <div class="relative mx-auto mb-5 h-16 w-16">
          <div class="absolute inset-0 animate-spin rounded-full border-[3px] border-indigo-100 border-t-indigo-500"/>
          <div class="absolute inset-2 animate-spin rounded-full border-[3px] border-violet-100 border-b-violet-500" style="animation-direction:reverse;animation-duration:1.2s"/>
        </div>
        <p :class="['text-sm font-semibold', isDark ? 'text-slate-300' : 'text-slate-700']">Loading shared dashboard…</p>
      </div>
    </div>

    <!-- Error -->
    <div v-else-if="errorMsg" class="flex items-center justify-center" style="min-height:60vh">
      <div class="text-center max-w-md">
        <div :class="['mx-auto mb-6 flex h-24 w-24 items-center justify-center rounded-3xl', isDark ? 'bg-red-900/20' : 'bg-red-50']">
          <iconify-icon icon="lucide:shield-off" class="text-4xl text-red-400"/>
        </div>
        <h2 :class="['text-xl font-bold mb-2', isDark ? 'text-white' : 'text-slate-800']">Dashboard Unavailable</h2>
        <p class="text-sm text-slate-500">{{ errorMsg }}</p>
      </div>
    </div>

    <!-- Dashboard -->
    <div v-else class="max-w-[1440px] mx-auto px-4 py-4">
      <div v-if="!widgets.length" class="flex items-center justify-center" style="min-height:40vh">
        <p class="text-sm text-slate-500">This dashboard has no widgets yet.</p>
      </div>

      <div v-else ref="gridEl" class="grid-stack">
        <div v-for="w in widgets" :key="w.id" class="grid-stack-item"
          :gs-id="w.id" :gs-x="w.gridX||0" :gs-y="w.gridY||0"
          :gs-w="w.gridW||(w.type==='summary'?12:w.type==='kpi'?3:6)"
          :gs-h="w.gridH||(w.type==='kpi'?2:3)"
          :gs-min-w="2" :gs-min-h="2">
          <div :class="['grid-stack-item-content rounded-2xl border shadow-sm overflow-hidden flex flex-col group transition-colors', isDark ? 'bg-zinc-900/90 border-white/[0.06]' : 'bg-white border-slate-200/60']">

            <!-- Header -->
            <div v-if="w.type !== 'kpi'" :class="['shrink-0 flex items-center gap-2 px-4 py-2.5 border-b', isDark ? 'border-white/[0.06]' : 'border-slate-100']">
              <p :class="['text-xs font-bold truncate flex-1', isDark ? 'text-slate-200' : 'text-slate-700']">{{ w.title }}</p>
              <span v-if="w.source_table" :class="['text-[9px] px-1.5 py-0.5 rounded font-mono', isDark ? 'bg-zinc-800 text-zinc-400' : 'bg-slate-100 text-slate-400']">{{ w.source_table === '_cross_table' ? 'Multi-Table' : w.source_table }}</span>
            </div>

            <!-- Body -->
            <div class="flex-1 min-h-0 overflow-hidden" :class="w.type === 'kpi' ? 'px-4 py-3' : w.type === 'summary' ? 'px-5 py-3' : 'p-2'">

              <!-- Summary -->
              <div v-if="w.type === 'summary'" class="flex items-center gap-4">
                <div :class="['flex h-10 w-10 shrink-0 items-center justify-center rounded-xl', isDark ? 'bg-indigo-500/15' : 'bg-indigo-100']">
                  <svg class="h-5 w-5 text-indigo-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"/></svg>
                </div>
                <p :class="['text-sm leading-relaxed', isDark ? 'text-slate-300' : 'text-slate-600']">{{ w.text || w.content || '—' }}</p>
              </div>

              <!-- KPI -->
              <div v-else-if="w.type === 'kpi'" class="flex flex-col justify-center h-full gap-1">
                <p :class="['text-[10px] font-bold uppercase tracking-wider truncate', isDark ? 'text-slate-500' : 'text-slate-400']">{{ w.title }}</p>
                <p :class="['font-extrabold tabular-nums tracking-tight', isDark ? 'text-white' : 'text-slate-800', String(w.value||'').length > 12 ? 'text-lg' : String(w.value||'').length > 8 ? 'text-2xl' : 'text-3xl']">{{ formatKpi(w) }}</p>
                <p v-if="w.subtitle" :class="['text-[11px]', isDark ? 'text-slate-500' : 'text-slate-400']">{{ w.subtitle }}</p>
              </div>

              <!-- Chart -->
              <div v-else-if="w.type === 'chart'" class="flex flex-col h-full">
                <p v-if="w.description" :class="['text-[11px] leading-snug px-1 pb-1 line-clamp-2', isDark ? 'text-slate-500' : 'text-slate-400']">{{ w.description }}</p>
                <div class="flex-1 min-h-0">
                  <VChart v-if="gridReady && w.chartData && (w.chartData.series || w.chartData.labels)" :option="echartOpts(w)" autoresize class="h-full w-full" :key="isDark ? 'd' : 'l'"/>
                  <div v-else-if="!gridReady" class="h-full flex items-center justify-center text-xs text-slate-400">Loading chart…</div>
                  <div v-else class="h-full flex items-center justify-center text-xs text-slate-400">No data</div>
                </div>
              </div>

              <!-- List -->
              <div v-else-if="w.type === 'list'" class="h-full overflow-y-auto">
                <div v-if="w.items && w.items.length" class="space-y-0.5 px-1">
                  <div v-for="(item, idx) in (w.items as any[]).slice(0, 15)" :key="idx" :class="['flex items-center gap-3 rounded-lg px-2 py-1.5 text-sm', isDark ? 'hover:bg-white/[0.04]' : 'hover:bg-slate-50']">
                    <span class="flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-[11px] font-bold" :style="{ backgroundColor: themePalette[idx % themePalette.length] + '22', color: themePalette[idx % themePalette.length] }">{{ idx + 1 }}</span>
                    <span :class="['flex-1 truncate', isDark ? 'text-slate-300' : 'text-slate-700']">{{ item.label || item.name }}</span>
                    <span :class="['text-xs font-semibold tabular-nums', isDark ? 'text-slate-400' : 'text-slate-600']">{{ item.value }}</span>
                  </div>
                </div>
                <div v-else class="h-full flex items-center justify-center text-xs text-slate-400">No data</div>
              </div>

              <!-- Insight -->
              <div v-else-if="w.type === 'insight'" class="flex h-full overflow-y-auto">
                <div :class="['w-1 shrink-0 rounded-full mr-3', isDark ? 'bg-gradient-to-b from-indigo-500/60 to-violet-500/30' : 'bg-gradient-to-b from-indigo-400 to-violet-400 opacity-60']"/>
                <div class="flex flex-col justify-center gap-2 flex-1">
                  <p :class="['text-[13px] leading-relaxed', isDark ? 'text-slate-300' : 'text-slate-600']">{{ w.text || w.content || 'No insight available' }}</p>
                  <span v-if="w.highlight" :class="['inline-flex self-start items-center rounded-md px-2 py-0.5 text-[11px] font-semibold', isDark ? 'bg-indigo-500/10 text-indigo-300' : 'bg-indigo-50 text-indigo-700']">{{ w.highlight }}</span>
                </div>
              </div>

              <!-- Table -->
              <div v-else-if="w.type === 'table' && w.columns" class="h-full overflow-auto">
                <table class="w-full text-xs">
                  <thead :class="['sticky top-0', isDark ? 'bg-zinc-900' : 'bg-slate-50']">
                    <tr><th v-for="col in w.columns" :key="col" :class="['text-left px-2 py-1.5 font-semibold text-[10px] uppercase tracking-wider', isDark ? 'text-indigo-300/80' : 'text-indigo-600/70']">{{ col }}</th></tr>
                  </thead>
                  <tbody>
                    <tr v-for="(row, ri) in ((w.data || []) as any[]).slice(0, 20)" :key="ri" :class="['border-t', isDark ? 'border-white/[0.04]' : 'border-slate-100']">
                      <td v-for="col in w.columns" :key="col" :class="['px-2 py-1', isDark ? 'text-slate-300' : 'text-slate-600']">{{ row[col] }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>

              <!-- Fallback -->
              <div v-else class="h-full flex items-center justify-center text-xs text-slate-400">{{ w.type }}</div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <footer :class="['border-t py-4 mt-8 text-center', isDark ? 'border-white/[0.06]' : 'border-slate-200/60']">
      <p class="text-[10px] text-slate-400">Powered by Workspace Analytics</p>
    </footer>
  </div>
</template>

<style>
.grid-stack { min-height: 100%; }
.grid-stack-item-content { padding: 0 !important; background-clip: padding-box; overflow: visible !important; }
/* Resize handle: subtle on hover */
:deep(.grid-stack-item:not(.static):hover .ui-resizable-handle) {
  opacity: 0.5 !important;
}
.grid-stack-item > .ui-resizable-handle {
  opacity: 0;
  transition: opacity 0.2s;
}
</style>
