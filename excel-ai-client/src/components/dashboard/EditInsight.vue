<script setup lang="ts">
import { ref, watch } from 'vue'

const props = defineProps<{
  widget: any
  isLoading?: boolean
}>()

const draftTitle = ref('')
const draftText = ref('')
const draftHighlight = ref('')

watch(
  () => props.widget,
  (widget) => {
    draftTitle.value = String(widget?.title || '')
    draftText.value = String(widget?.text || '')
    draftHighlight.value = String(widget?.highlight || '')
  },
  { immediate: true, deep: true }
)

function applyInsightChanges() {
  props.widget.title = draftTitle.value.trim() || props.widget.title
  props.widget.text = draftText.value
  props.widget.highlight = draftHighlight.value
  if (!props.widget.ui) props.widget.ui = {}
  props.widget.ui.titleText = props.widget.title
  props.widget.ui.titleLocked = true
}
</script>

<template>
  <div class="space-y-3">
    <details class="rounded-lg border border-slate-200 p-3 dark:border-slate-700" open>
      <summary class="cursor-pointer text-sm font-semibold text-slate-700 dark:text-slate-200">Data</summary>
      <div class="mt-2 space-y-2">
        <input
          v-model="draftTitle"
          placeholder="Insight title"
          class="w-full rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-sm outline-none focus:border-indigo-400 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
        />
        <textarea
          v-model="draftText"
          rows="4"
          placeholder="Insight content"
          class="w-full rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-sm outline-none focus:border-indigo-400 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
        />
        <input
          v-model="draftHighlight"
          placeholder="Highlight badge"
          class="w-full rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-sm outline-none focus:border-indigo-400 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
        />
        <button
          type="button"
          @click="applyInsightChanges"
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
    </details>
  </div>
</template>
