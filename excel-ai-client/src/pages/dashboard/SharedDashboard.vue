<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { useRoute } from 'vue-router'
import excelFileAPI, { type DashboardWidget } from '@/services/excelApi'
import { GridStack } from 'gridstack'
import 'gridstack/dist/gridstack.min.css'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { BarChart, LineChart, PieChart, ScatterChart } from 'echarts/charts'
import { TitleComponent, TooltipComponent, LegendComponent, GridComponent, DataZoomComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

use([BarChart, LineChart, PieChart, ScatterChart, TitleComponent, TooltipComponent, LegendComponent, GridComponent, DataZoomComponent, CanvasRenderer])

const route = useRoute()
const token = route.params.token as string

const isLoading = ref(true)
const loadError = ref<string | null>(null)
const dashboardName = ref('')
const widgets = ref<DashboardWidget[]>([])
const activeTheme = ref('indigo') // Default theme for shared dashboards
let grid: GridStack | null = null
const gridContainer = ref<HTMLElement | null>(null)
const gridReady = ref(false)
let previousRootDarkState: boolean | null = null

function forceSharedLightMode() {
  const root = document.documentElement
  previousRootDarkState = root.classList.contains('dark')
  root.classList.remove('dark')
}

function restoreRootThemeMode() {
  if (previousRootDarkState === null) return
  const root = document.documentElement
  root.classList.toggle('dark', previousRootDarkState)
}

// ── COLOR THEMES (shared view mirrors board view) ─────────────────
const colorThemes: Record<string, { swatch: string; bg: string; text: string; chart: string[] }> = {
  mix:     { swatch: 'conic',   bg: 'bg-slate-50 dark:bg-slate-800/40',   text: 'text-slate-600 dark:text-slate-400',   chart: ['#6366f1', '#10b981', '#f59e0b', '#f43f5e', '#06b6d4', '#8b5cf6', '#f97316', '#22c55e'] },
  indigo:  { swatch: '#6366f1', bg: 'bg-indigo-50 dark:bg-indigo-950/30',  text: 'text-indigo-600 dark:text-indigo-400',  chart: ['#4338ca', '#4f46e5', '#6366f1', '#818cf8', '#a5b4fc'] },
  violet:  { swatch: '#8b5cf6', bg: 'bg-violet-50 dark:bg-violet-950/30',  text: 'text-violet-600 dark:text-violet-400',  chart: ['#6d28d9', '#7c3aed', '#8b5cf6', '#a78bfa', '#c4b5fd'] },
  emerald: { swatch: '#10b981', bg: 'bg-emerald-50 dark:bg-emerald-950/30', text: 'text-emerald-600 dark:text-emerald-400', chart: ['#047857', '#059669', '#10b981', '#34d399', '#6ee7b7'] },
  amber:   { swatch: '#f59e0b', bg: 'bg-amber-50 dark:bg-amber-950/30',   text: 'text-amber-600 dark:text-amber-400',   chart: ['#b45309', '#d97706', '#f59e0b', '#fbbf24', '#fcd34d'] },
  rose:    { swatch: '#f43f5e', bg: 'bg-rose-50 dark:bg-rose-950/30',     text: 'text-rose-600 dark:text-rose-400',     chart: ['#be123c', '#e11d48', '#f43f5e', '#fb7185', '#fda4af'] },
  cyan:    { swatch: '#06b6d4', bg: 'bg-cyan-50 dark:bg-cyan-950/30',     text: 'text-cyan-600 dark:text-cyan-400',     chart: ['#0e7490', '#0891b2', '#06b6d4', '#22d3ee', '#67e8f9'] },
}

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

function getWidgetTheme(widget: any, index = 0) {
  const base = colorThemes[activeTheme.value] || colorThemes.indigo
  const custom = typeof widget?.chartColor === 'string' ? widget.chartColor.trim() : ''
  if (custom) return { ...base, chart: generateShades(custom) }
  return { ...base, chart: base.chart[index % base.chart.length] ? base.chart : colorThemes.indigo.chart }
}

function getWidgetCardStyle(widget: any): Record<string, string> {
  const custom = typeof widget?.chartColor === 'string' ? widget.chartColor.trim() : ''
  if (!custom || widget?.type === 'chart') return {}
  return {
    backgroundColor: `${custom}55`,
    borderColor: `${custom}aa`,
  }
}

function getEChartOption(widget: any, index: number): Record<string, any> {
  const theme = getWidgetTheme(widget, index)
  const chartType = widget.chartType || 'bar'
  const isPieType = ['pie', 'donut', 'doughnut'].includes(chartType)
  const labels: string[] = widget.chartData?.labels || []
  const seriesData: any[] = widget.chartData?.series || []

  const base: Record<string, any> = {
    color: theme.chart,
    backgroundColor: 'transparent',
    tooltip: { trigger: isPieType ? 'item' : 'axis' },
    legend: {
      show: !isPieType || labels.length <= 8,
      bottom: 4,
      textStyle: { fontSize: 11 }
    },
    animationDuration: 600,
  }

  if (isPieType) {
    base.series = [{
      type: 'pie',
      radius: chartType.includes('donut') ? ['45%', '72%'] : '68%',
      center: ['50%', '44%'],
      data: labels.map((l: string, i: number) => ({
        name: l,
        value: typeof seriesData[0] === 'number' ? seriesData[i] : seriesData[0]?.data?.[i] ?? 0
      }))
    }]
  } else {
    base.xAxis = widget.horizontal ? { type: 'value' } : { type: 'category', data: labels }
    base.yAxis = widget.horizontal ? { type: 'category', data: labels } : { type: 'value' }
    base.series = seriesData.map((s: any) => ({
      name: s.name || 'Value',
      type: chartType,
      data: s.data || s,
      smooth: true,
      itemStyle: { borderRadius: chartType === 'bar' ? [4,4,0,0] : 0 }
    }))
  }

  return base
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
  const sourceValue = widget?.value ?? 'N/A'
  const title = String(widget?.title || '')
  
  const parsed = typeof sourceValue === 'number'
    ? sourceValue
    : Number(String(sourceValue).replace(/[^0-9.-]/g, ''))

  if (!Number.isNaN(parsed) && String(sourceValue).match(/[0-9]/)) {
    const formatted = formatIndianNumber(parsed, 0)
    const currencySymbol = isCurrencyValue(sourceValue, title) ? extractCurrencySymbol(sourceValue) || '₹' : ''
    return `${currencySymbol}${formatted}`
  }

  return String(sourceValue)
}

// ── INIT GRID ──────────────────────────────────────────────────
function initGrid() {
  if (!widgets.value.length) return
  if (!gridContainer.value) { setTimeout(initGrid, 100); return }

  gridReady.value = false
  try { grid?.destroy(false) } catch { /* ignore */ }
  
  grid = GridStack.init({
    column: window.innerWidth < 768 ? 1 : 12,
    cellHeight: 80,
    minRow: 1,
    margin: 16,
    staticGrid: true // Locks the grid completely (no drag, no resize)
  }, gridContainer.value)

  nextTick(() => window.requestAnimationFrame(() => { gridReady.value = true }))
}

// ── LIFECYCLE ──────────────────────────────────────────────────
onMounted(async () => {
  forceSharedLightMode()

  if (!token) {
    loadError.value = "Invalid share link."
    isLoading.value = false
    return
  }

  try {
    const res = await excelFileAPI.getSharedDashboard(token)
    dashboardName.value = res.project_name
    const themeKey = (
      res.dashboard_data?.studio?.active_theme
      || res.dashboard_data?.theme
      || ''
    ).toString().trim()
    if (themeKey && colorThemes[themeKey]) activeTheme.value = themeKey
    // Widgets already include saved grid positions from the dashboards table
    widgets.value = res.dashboard_data?.widgets || []

    if (widgets.value.length > 0) {
      await nextTick()
      initGrid()
    } else {
      loadError.value = "This dashboard is empty."
    }
  } catch (e: any) {
    console.error('Failed to load shared dashboard:', e)
    loadError.value = "This dashboard is unavailable or the link has expired."
  } finally {
    isLoading.value = false
  }
})

onBeforeUnmount(() => {
  try { grid?.destroy(false) } catch {}
  restoreRootThemeMode()
})
</script>

<template>
  <div class="min-h-screen bg-slate-50 dark:bg-slate-950 flex flex-col">
    <!-- Header -->
    <header class="h-14 border-b border-slate-200 bg-white px-6 flex items-center justify-between shadow-sm dark:bg-slate-900 dark:border-slate-800">
      <div class="flex items-center gap-3">
        <div class="h-9 w-9 rounded-lg bg-gradient-to-br from-indigo-500 to-indigo-600 flex items-center justify-center text-white shadow-sm">
          <iconify-icon icon="lucide:layout-dashboard" class="h-4.5 w-4.5" />
        </div>
        <div>
          <h1 class="font-semibold text-lg text-slate-800 dark:text-slate-100 leading-tight">{{ dashboardName || 'Shared Dashboard' }}</h1>
          <p class="text-[10px] text-slate-400 dark:text-slate-500">{{ widgets.length }} widgets &middot; Insight Board</p>
        </div>
      </div>
      <div class="text-xs font-semibold text-indigo-600 bg-indigo-50 px-3 py-1.5 rounded-full dark:bg-indigo-900/30 dark:text-indigo-400 border border-indigo-100 dark:border-indigo-800/40">
        Read-Only View
      </div>
    </header>

    <!-- Main Content -->
    <main class="flex-1 overflow-auto p-6">
      <div v-if="isLoading" class="flex flex-col items-center justify-center h-64 opacity-50">
        <div class="h-10 w-10 animate-spin rounded-full border-4 border-indigo-200 border-t-indigo-600 mb-4" />
        <p class="text-slate-500 font-medium tracking-wide">Loading dashboard...</p>
      </div>

      <div v-else-if="loadError" class="flex flex-col items-center justify-center h-64">
        <div class="h-16 w-16 mb-4 text-slate-300">
          <iconify-icon icon="lucide:file-question" class="h-full w-full" />
        </div>
        <p class="text-lg font-medium text-slate-600 dark:text-slate-300 mb-2">{{ loadError }}</p>
        <p class="text-sm text-slate-400">Please check the link and try again.</p>
      </div>

      <div v-else class="max-w-[1600px] mx-auto">
        <div ref="gridContainer" class="grid-stack static-grid relative pb-32">
          <div
            v-for="(widget, widgetIndex) in widgets"
            :key="widget.id"
            class="grid-stack-item transition-all duration-300"
            :gs-id="widget.id"
            :gs-x="(widget as any).gridX"
            :gs-y="(widget as any).gridY"
            :gs-w="widget.gridW || 3"
            :gs-h="widget.gridH || 2"
          >
            <div class="grid-stack-item-content widget-card relative flex flex-col rounded-xl border border-slate-200/80 bg-white shadow-md backdrop-blur transition-shadow hover:shadow-lg dark:border-slate-700/60 dark:bg-slate-900 overflow-hidden"
              :style="getWidgetCardStyle(widget)">
              <div class="flex items-center justify-between px-4 py-2.5 border-b border-slate-100 dark:border-slate-800 bg-slate-50/60 dark:bg-slate-800/40">
                <h3 class="text-xs font-bold uppercase tracking-wider text-slate-600 dark:text-slate-300 truncate" :title="widget.title">
                  {{ widget.title }}
                </h3>
              </div>

              <div class="flex-1 min-h-0 relative p-4">
                <!-- CHART -->
                <v-chart v-if="widget.type === 'chart' && widget.chartData && gridReady"
                  class="h-full w-full"
                  :option="getEChartOption(widget, widgetIndex)"
                  autoresize
                />

                <!-- KPI -->
                <div v-else-if="widget.type === 'kpi'" class="flex h-full flex-col justify-center items-center text-center rounded-lg p-4"
                  :style="(widget as any).chartColor ? { backgroundColor: (widget as any).chartColor + '4d' } : {}"
                  :class="(widget as any).chartColor ? '' : 'bg-gradient-to-br from-indigo-50/60 to-white dark:from-indigo-950/20 dark:to-slate-900'">
                  <div class="text-4xl font-extrabold tracking-tight mb-2"
                    :style="(widget as any).chartColor ? { color: (widget as any).chartColor } : {}"
                    :class="(widget as any).chartColor ? '' : 'text-indigo-700 dark:text-indigo-300'">
                    {{ getKpiDisplayValue(widget) }}
                  </div>
                  <div class="text-sm font-medium text-slate-500 dark:text-slate-400">
                    {{ (widget as any).subtitle || widget.title }}
                  </div>
                </div>

                <!-- LIST -->
                <div v-else-if="widget.type === 'list'" class="h-full overflow-y-auto scrollbar-thin">
                  <table class="w-full text-left text-[13px]">
                    <tbody>
                      <tr v-for="(item, idx) in (widget as any).items" :key="idx" class="border-b border-slate-100 last:border-0 dark:border-slate-700/60">
                        <td class="py-2.5 font-medium text-slate-700 dark:text-slate-300">{{ item.label }}</td>
                        <td class="py-2.5 text-right font-semibold text-slate-900 dark:text-slate-100">{{ item.value }}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>

                <!-- INSIGHT -->
                <div v-else-if="widget.type === 'insight'" class="h-full overflow-y-auto text-[13px] leading-relaxed text-slate-700 dark:text-slate-200 whitespace-pre-wrap rounded-lg p-3 border"
                  :style="(widget as any).chartColor ? { backgroundColor: (widget as any).chartColor + '2e', borderColor: (widget as any).chartColor + '8a' } : {}"
                  :class="(widget as any).chartColor ? '' : 'bg-amber-50/50 dark:bg-amber-950/10 border-amber-100/60 dark:border-amber-800/20'">
                  {{ (widget as any).text || 'No insights available.' }}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </main>
  </div>
</template>

<style scoped>
.widget-card { transform: translateZ(0); }
.grid-stack { min-height: 400px; }
</style>
