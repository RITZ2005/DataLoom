<script setup lang="ts">
import { computed, ref, watch } from 'vue'

const props = defineProps<{
  widget: any
  isLoading?: boolean
}>()

const emit = defineEmits<{
  (e: 'apply-kpi', payload: { title: string; overrideValue: string }): void
}>()

const ui = computed(() => {
  const w = props.widget
  if (!w.ui) w.ui = {}
  // KPI display is intentionally fixed to value-only for consistent UI.
  w.ui.displayStyle = 'value-only'
  if (typeof w.ui.prefix !== 'string') w.ui.prefix = ''
  if (typeof w.ui.suffix !== 'string') w.ui.suffix = ''
  if (typeof w.ui.decimals !== 'number') w.ui.decimals = 0
  if (typeof w.ui.showTrend !== 'boolean') w.ui.showTrend = true
  if (typeof w.ui.positiveColor !== 'string') w.ui.positiveColor = '#16a34a'
  if (typeof w.ui.negativeColor !== 'string') w.ui.negativeColor = '#dc2626'
  if (typeof w.ui.kpiVariant !== 'string') w.ui.kpiVariant = 'default'
  if (typeof w.ui.overrideValue !== 'string') w.ui.overrideValue = ''
  return w.ui
})

const draftTitle = ref('')
const draftValue = ref('')

watch(
  () => props.widget,
  (widget) => {
    draftTitle.value = String(widget?.title || '')
    draftValue.value = String(widget?.ui?.overrideValue || '')
  },
  { immediate: true, deep: true }
)

function applyKpiChanges() {
  const nextTitle = draftTitle.value.trim()
  if (nextTitle) {
    props.widget.title = nextTitle
    ui.value.titleText = nextTitle
    ui.value.titleLocked = true
  }
  ui.value.overrideValue = draftValue.value
  emit('apply-kpi', { title: nextTitle, overrideValue: String(draftValue.value || '') })
}
</script>

<template>
  <div class="space-y-3">
    <div class="rounded-lg border border-slate-200 p-3 dark:border-slate-700">
      <p class="mb-2 text-sm font-semibold text-slate-700 dark:text-slate-200">Display</p>
      <div class="grid grid-cols-1 gap-1 rounded-md bg-slate-100 p-1 dark:bg-slate-800">
        <button @click="ui.displayStyle = 'value-only'" :class="['rounded px-2 py-1 text-xs', ui.displayStyle === 'value-only' ? 'bg-white dark:bg-slate-700' : 'text-slate-500']">Value</button>
      </div>
    </div>

    <details class="rounded-lg border border-slate-200 p-3 dark:border-slate-700" open>
      <summary class="cursor-pointer text-sm font-semibold text-slate-700 dark:text-slate-200">Data</summary>
      <div class="mt-2 grid grid-cols-1 gap-2">
        <input
          v-model="draftTitle"
          placeholder="KPI title"
          class="w-full rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-sm outline-none focus:border-indigo-400 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
        />
        <input
          v-model="draftValue"
          placeholder="Override value (optional)"
          class="w-full rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-sm outline-none focus:border-indigo-400 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
        />
        <button
          type="button"
          @click="applyKpiChanges"
          :disabled="props.isLoading"
          class="w-full rounded-md bg-indigo-600 px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-indigo-700"
        >
          <span v-if="props.isLoading" class="inline-flex items-center gap-1.5">
            <span class="h-3 w-3 animate-spin rounded-full border border-white/40 border-t-white" />
            Applying...
          </span>
          <span v-else>Apply</span>
        </button>
      </div>
      <div class="mt-2 grid grid-cols-2 gap-2">
        <input
          v-model="ui.prefix"
          placeholder="Prefix"
          class="w-full rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-sm outline-none focus:border-indigo-400 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
        />
        <input
          v-model="ui.suffix"
          placeholder="Suffix"
          class="w-full rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-sm outline-none focus:border-indigo-400 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
        />
      </div>
    </details>

    <details class="rounded-lg border border-slate-200 p-3 dark:border-slate-700" open>
      <summary class="cursor-pointer text-sm font-semibold text-slate-700 dark:text-slate-200">Customize</summary>
      <div class="mt-2 space-y-2">
        <label class="flex items-center justify-between text-sm text-slate-600 dark:text-slate-300">
          <span>Show Trend</span>
          <input type="checkbox" v-model="ui.showTrend" class="accent-indigo-600" />
        </label>
        <div>
          <p class="mb-1 text-xs text-slate-500 dark:text-slate-400">Decimals</p>
          <input
            v-model.number="ui.decimals"
            type="number"
            min="0"
            max="6"
            class="w-full rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-sm outline-none focus:border-indigo-400 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
          />
        </div>
      </div>
    </details>

    <details class="rounded-lg border border-slate-200 p-3 dark:border-slate-700">
      <summary class="cursor-pointer text-sm font-semibold text-slate-700 dark:text-slate-200">Variation</summary>
      <div class="mt-2 grid grid-cols-2 gap-2">
        <button @click="ui.kpiVariant = 'default'" :class="['rounded px-2 py-1 text-xs border', ui.kpiVariant === 'default' ? 'border-indigo-400 bg-indigo-50 text-indigo-700 dark:bg-indigo-500/10 dark:text-indigo-300' : 'border-slate-200 text-slate-500 dark:border-slate-700']">Default</button>
        <button @click="ui.kpiVariant = 'sparkline'" :class="['rounded px-2 py-1 text-xs border', ui.kpiVariant === 'sparkline' ? 'border-indigo-400 bg-indigo-50 text-indigo-700 dark:bg-indigo-500/10 dark:text-indigo-300' : 'border-slate-200 text-slate-500 dark:border-slate-700']">Sparkline</button>
        <button @click="ui.kpiVariant = 'comparison'" :class="['rounded px-2 py-1 text-xs border', ui.kpiVariant === 'comparison' ? 'border-indigo-400 bg-indigo-50 text-indigo-700 dark:bg-indigo-500/10 dark:text-indigo-300' : 'border-slate-200 text-slate-500 dark:border-slate-700']">Comparison</button>
        <button @click="ui.kpiVariant = 'minimal'" :class="['rounded px-2 py-1 text-xs border', ui.kpiVariant === 'minimal' ? 'border-indigo-400 bg-indigo-50 text-indigo-700 dark:bg-indigo-500/10 dark:text-indigo-300' : 'border-slate-200 text-slate-500 dark:border-slate-700']">Minimal</button>
      </div>
      <div class="mt-2 grid grid-cols-2 gap-2">
        <div>
          <p class="mb-1 text-xs text-slate-500 dark:text-slate-400">Positive</p>
          <input v-model="ui.positiveColor" type="color" class="h-9 w-full rounded-md border border-slate-200 bg-white p-1 dark:border-slate-700 dark:bg-slate-800" />
        </div>
        <div>
          <p class="mb-1 text-xs text-slate-500 dark:text-slate-400">Negative</p>
          <input v-model="ui.negativeColor" type="color" class="h-9 w-full rounded-md border border-slate-200 bg-white p-1 dark:border-slate-700 dark:bg-slate-800" />
        </div>
      </div>
    </details>
  </div>
</template>
