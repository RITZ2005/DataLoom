<script setup lang="ts">
import { computed, watchEffect } from 'vue'

const props = defineProps<{
  widget: any
  activeTab?: 'data' | 'customize'
  dimensions?: string[]
  measures?: string[]
}>()

const emit = defineEmits<{
  (e: 'recompute-chart', payload: { chartType: string; dimension: string; measure: string; aggregation: string; suggestedTitle?: string }): void
}>()

const chartTypeOptions = [
  'bar', 'line', 'area', 'combo',
  'pie', 'donut',
  'scatter', 'bubble',
  'funnel', 'gauge', 'heatmap', 'treemap', 'waterfall',
  'histogram'
]

const dimensionOptions = computed(() => props.dimensions || [])
const measureOptions = computed(() => props.measures || [])

const ui = computed(() => {
  const w = props.widget
  if (!w.ui) w.ui = {}
  if (typeof w.ui.showLegend !== 'boolean') w.ui.showLegend = true
  if (typeof w.ui.smoothLines !== 'boolean') w.ui.smoothLines = false
  if (typeof w.ui.showGrid !== 'boolean') w.ui.showGrid = true
  if (typeof w.ui.xAxisLabel !== 'string') w.ui.xAxisLabel = ''
  if (typeof w.ui.yAxisLabel !== 'string') w.ui.yAxisLabel = ''
  if (typeof w.ui.xAxisColumn !== 'string') w.ui.xAxisColumn = ''
  if (typeof w.ui.yAxisColumn !== 'string') w.ui.yAxisColumn = ''
  if (typeof w.ui.colorTheme !== 'string') w.ui.colorTheme = 'default'
  if (typeof w.ui.aggregation !== 'string') w.ui.aggregation = 'sum'
  if (typeof w.ui.barWidth !== 'number') w.ui.barWidth = 36
  if (typeof w.ui.dataLabels !== 'boolean') w.ui.dataLabels = false
  if (typeof w.ui.showLegend !== 'boolean') w.ui.showLegend = true
  if (typeof w.ui.chartVariant !== 'string') w.ui.chartVariant = 'default'
  if (typeof w.ui.addButtons !== 'boolean') w.ui.addButtons = false
  if (typeof w.ui.addDropdowns !== 'boolean') w.ui.addDropdowns = false
  if (typeof w.ui.addKpis !== 'boolean') w.ui.addKpis = false
  if (typeof w.ui.addText !== 'boolean') w.ui.addText = false
  return w.ui
})

function syncAxisLabel(axis: 'x' | 'y') {
  if (axis === 'x') {
    ui.value.xAxisLabel = ui.value.xAxisColumn || ''
    props.widget.filter_context = { ...(props.widget.filter_context || {}), column: ui.value.xAxisColumn || '' }
    return
  }
  ui.value.yAxisLabel = ui.value.yAxisColumn || ''
  props.widget.filter_context = { ...(props.widget.filter_context || {}), measure: ui.value.yAxisColumn || '' }
}

function requestRecompute() {
  if (!ui.value.xAxisColumn || !ui.value.yAxisColumn) return
  const chartTypeLabel = String(props.widget.chartType || 'chart').toUpperCase()
  const suggestedTitle = `${ui.value.yAxisColumn} by ${ui.value.xAxisColumn} (${chartTypeLabel})`
  emit('recompute-chart', {
    chartType: props.widget.chartType || 'bar',
    dimension: ui.value.xAxisColumn,
    measure: ui.value.yAxisColumn,
    aggregation: ui.value.aggregation || 'sum',
    suggestedTitle,
  })
}

watchEffect(() => {
  if (!ui.value.xAxisColumn && dimensionOptions.value.length) {
    ui.value.xAxisColumn = dimensionOptions.value[0]
  }
  if (!ui.value.yAxisColumn && measureOptions.value.length) {
    ui.value.yAxisColumn = measureOptions.value[0]
  }
  if (!ui.value.xAxisLabel && ui.value.xAxisColumn) {
    ui.value.xAxisLabel = ui.value.xAxisColumn
  }
  if (!ui.value.yAxisLabel && ui.value.yAxisColumn) {
    ui.value.yAxisLabel = ui.value.yAxisColumn
  }
})
</script>

<template>
  <div class="space-y-3">
    <template v-if="props.activeTab !== 'customize'">
      <details class="rounded-lg border border-slate-200 p-3 dark:border-slate-700" open>
        <summary class="cursor-pointer text-sm font-semibold text-slate-700 dark:text-slate-200">Variation</summary>
        <div class="mt-2 space-y-2">
          <select
            v-model="ui.chartVariant"
            class="w-full rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-sm outline-none focus:border-indigo-400 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
          >
            <option value="default">Default</option>
            <option value="executive">Executive</option>
            <option value="compact">Compact</option>
            <option value="contrast">High Contrast</option>
          </select>
          <button
            class="w-full rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300"
            type="button"
          >
            Theme &amp; Customizations
          </button>
        </div>
      </details>

      <div class="rounded-lg border border-slate-200 p-3 dark:border-slate-700">
        <p class="mb-2 text-sm font-semibold text-slate-700 dark:text-slate-200">Chart Type</p>
        <select
          v-model="widget.chartType"
          @change="requestRecompute"
          class="w-full rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-sm outline-none focus:border-indigo-400 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
        >
          <option v-for="t in chartTypeOptions" :key="t" :value="t">{{ t.toUpperCase() }}</option>
        </select>
      </div>

      <details class="rounded-lg border border-slate-200 p-3 dark:border-slate-700" open>
        <summary class="cursor-pointer text-sm font-semibold text-slate-700 dark:text-slate-200">Aggregation</summary>
        <div class="mt-2 grid grid-cols-3 gap-1 rounded-md bg-slate-100 p-1 dark:bg-slate-800">
          <button @click="ui.aggregation = 'sum'; requestRecompute()" :class="['rounded px-2 py-1 text-xs', ui.aggregation === 'sum' ? 'bg-white dark:bg-slate-700' : 'text-slate-500']">Sum</button>
          <button @click="ui.aggregation = 'mean'; requestRecompute()" :class="['rounded px-2 py-1 text-xs', ui.aggregation === 'mean' ? 'bg-white dark:bg-slate-700' : 'text-slate-500']">Avg</button>
          <button @click="ui.aggregation = 'count'; requestRecompute()" :class="['rounded px-2 py-1 text-xs', ui.aggregation === 'count' ? 'bg-white dark:bg-slate-700' : 'text-slate-500']">Count</button>
        </div>
      </details>

      <details class="rounded-lg border border-slate-200 p-3 dark:border-slate-700" open>
        <summary class="cursor-pointer text-sm font-semibold text-slate-700 dark:text-slate-200">X Axis</summary>
        <div class="mt-2 space-y-2">
          <select
            v-model="ui.xAxisColumn"
            @change="syncAxisLabel('x'); requestRecompute()"
            class="w-full rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-sm outline-none focus:border-indigo-400 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
          >
            <option disabled value="">Select column</option>
            <option v-for="column in dimensionOptions" :key="column" :value="column">{{ column }}</option>
          </select>
          <p class="text-xs text-slate-500 dark:text-slate-400">Columns are loaded from the active Insight Board source file.</p>
        </div>
      </details>

      <details class="rounded-lg border border-slate-200 p-3 dark:border-slate-700" open>
        <summary class="cursor-pointer text-sm font-semibold text-slate-700 dark:text-slate-200">Y Axis</summary>
        <div class="mt-2 space-y-2">
          <select
            v-model="ui.yAxisColumn"
            @change="syncAxisLabel('y'); requestRecompute()"
            class="w-full rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-sm outline-none focus:border-indigo-400 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
          >
            <option disabled value="">Select column</option>
            <option v-for="column in measureOptions" :key="column" :value="column">{{ column }}</option>
          </select>
          <p class="text-xs text-slate-500 dark:text-slate-400">Numeric columns are suggested automatically for the selected file.</p>
        </div>
      </details>
    </template>

    <details class="rounded-lg border border-slate-200 p-3 dark:border-slate-700" :open="props.activeTab === 'customize'">
      <summary class="cursor-pointer text-sm font-semibold text-slate-700 dark:text-slate-200">Properties</summary>
      <div class="mt-2 space-y-2">
        <div>
          <p class="mb-1 text-xs text-slate-500 dark:text-slate-400">Bar Width</p>
          <input v-model.number="ui.barWidth" type="range" min="10" max="70" class="w-full accent-indigo-600" />
        </div>
        <label class="flex items-center justify-between text-sm text-slate-600 dark:text-slate-300">
          <span>Data Labels</span>
          <input type="checkbox" v-model="ui.dataLabels" class="accent-indigo-600" />
        </label>
        <label class="flex items-center justify-between text-sm text-slate-600 dark:text-slate-300">
          <span>Show Legend</span>
          <input type="checkbox" v-model="ui.showLegend" class="accent-indigo-600" />
        </label>
        <label class="flex items-center justify-between text-sm text-slate-600 dark:text-slate-300">
          <span>Show Grid</span>
          <input type="checkbox" v-model="ui.showGrid" class="accent-indigo-600" />
        </label>
        <label class="flex items-center justify-between text-sm text-slate-600 dark:text-slate-300">
          <span>Smooth Lines</span>
          <input type="checkbox" v-model="ui.smoothLines" class="accent-indigo-600" />
        </label>
      </div>
    </details>

    <details class="rounded-lg border border-slate-200 p-3 dark:border-slate-700" :open="props.activeTab === 'customize'">
      <summary class="cursor-pointer text-sm font-semibold text-slate-700 dark:text-slate-200">Add Ons</summary>
      <div class="mt-2 space-y-2">
        <label class="flex items-center justify-between text-sm text-slate-600 dark:text-slate-300">
          <span>Buttons</span>
          <input type="checkbox" v-model="ui.addButtons" class="accent-indigo-600" />
        </label>
        <label class="flex items-center justify-between text-sm text-slate-600 dark:text-slate-300">
          <span>Dropdowns</span>
          <input type="checkbox" v-model="ui.addDropdowns" class="accent-indigo-600" />
        </label>
        <label class="flex items-center justify-between text-sm text-slate-600 dark:text-slate-300">
          <span>KPIs</span>
          <input type="checkbox" v-model="ui.addKpis" class="accent-indigo-600" />
        </label>
        <label class="flex items-center justify-between text-sm text-slate-600 dark:text-slate-300">
          <span>Text</span>
          <input type="checkbox" v-model="ui.addText" class="accent-indigo-600" />
        </label>
      </div>
    </details>
  </div>
</template>
