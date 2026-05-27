<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ widget: any }>()

const ui = computed(() => {
  const w = props.widget
  if (!w.ui) w.ui = {}
  if (typeof w.ui.subtitle !== 'string') w.ui.subtitle = ''
  if (typeof w.ui.showDate !== 'boolean') w.ui.showDate = true
  if (typeof w.ui.badgeText !== 'string') w.ui.badgeText = ''
  return w.ui
})
</script>

<template>
  <div class="space-y-3">
    <details class="rounded-lg border border-slate-200 p-3 dark:border-slate-700" open>
      <summary class="cursor-pointer text-sm font-semibold text-slate-700 dark:text-slate-200">Data</summary>
      <div class="mt-2 space-y-2">
        <input v-model="ui.subtitle" placeholder="Subtitle" class="w-full rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-sm outline-none focus:border-indigo-400 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100" />
        <input v-model="ui.badgeText" placeholder="Badge text" class="w-full rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-sm outline-none focus:border-indigo-400 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100" />
      </div>
    </details>

    <details class="rounded-lg border border-slate-200 p-3 dark:border-slate-700" open>
      <summary class="cursor-pointer text-sm font-semibold text-slate-700 dark:text-slate-200">Customize</summary>
      <div class="mt-2 space-y-2">
        <label class="flex items-center justify-between text-sm text-slate-600 dark:text-slate-300"><span>Show Date</span><input type="checkbox" v-model="ui.showDate" class="accent-indigo-600" /></label>
      </div>
    </details>
  </div>
</template>
