<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ widget: any }>()

const ui = computed(() => {
  const w = props.widget
  if (!w.ui) w.ui = {}
  if (typeof w.ui.maxItems !== 'number') w.ui.maxItems = 10
  if (typeof w.ui.showRank !== 'boolean') w.ui.showRank = true
  if (typeof w.ui.showBars !== 'boolean') w.ui.showBars = true
  if (typeof w.ui.sortOrder !== 'string') w.ui.sortOrder = 'desc'
  return w.ui
})
</script>

<template>
  <div class="space-y-3">
    <details class="rounded-lg border border-slate-200 p-3 dark:border-slate-700" open>
      <summary class="cursor-pointer text-sm font-semibold text-slate-700 dark:text-slate-200">Data</summary>
      <div class="mt-2 space-y-2">
        <label class="text-xs text-slate-500 dark:text-slate-400">Max rows</label>
        <input v-model.number="ui.maxItems" type="number" min="1" max="100" class="w-full rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-sm outline-none focus:border-indigo-400 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100" />
      </div>
    </details>

    <details class="rounded-lg border border-slate-200 p-3 dark:border-slate-700" open>
      <summary class="cursor-pointer text-sm font-semibold text-slate-700 dark:text-slate-200">Customize</summary>
      <div class="mt-2 space-y-2">
        <label class="flex items-center justify-between text-sm text-slate-600 dark:text-slate-300"><span>Show Rank</span><input type="checkbox" v-model="ui.showRank" class="accent-indigo-600" /></label>
        <label class="flex items-center justify-between text-sm text-slate-600 dark:text-slate-300"><span>Show Bars</span><input type="checkbox" v-model="ui.showBars" class="accent-indigo-600" /></label>
      </div>
    </details>

    <details class="rounded-lg border border-slate-200 p-3 dark:border-slate-700">
      <summary class="cursor-pointer text-sm font-semibold text-slate-700 dark:text-slate-200">Variation</summary>
      <div class="mt-2">
        <select v-model="ui.sortOrder" class="w-full rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-sm outline-none focus:border-indigo-400 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100">
          <option value="desc">High to Low</option>
          <option value="asc">Low to High</option>
        </select>
      </div>
    </details>
  </div>
</template>
