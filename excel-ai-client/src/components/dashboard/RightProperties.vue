<script setup lang="ts">
import { ref, watch } from 'vue'
import EditChart from '@/components/dashboard/EditChart.vue'
import EditKPI from '@/components/dashboard/EditKPI.vue'
import EditInsight from '@/components/dashboard/EditInsight.vue'
import EditList from '@/components/dashboard/EditList.vue'
import EditSummary from '@/components/dashboard/EditSummary.vue'

const props = defineProps<{
  widget: any | null
  widgetTypeLabel: string
  chartDimensions?: string[]
  chartMeasures?: string[]
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'update-title'): void
  (e: 'recompute-chart', payload: { chartType: string; dimension: string; measure: string; aggregation: string; suggestedTitle?: string }): void
  (e: 'recompute-kpi', payload: { title: string; overrideValue: string }): void
}>()

const activeTab = ref<'data' | 'customize'>('data')

watch(() => props.widget?.id, () => {
  activeTab.value = 'data'
})
</script>

<template>
  <aside
    v-if="props.widget"
    class="sticky top-0 shrink-0 flex h-full max-h-full w-80 flex-col overflow-hidden rounded-2xl border border-slate-200/70 bg-white/95 p-3 dark:border-white/[0.08] dark:bg-slate-900/95"
  >
    <div class="mb-3 flex items-center justify-between border-b border-slate-100 pb-2 dark:border-white/10">
      <h3 class="text-base font-semibold text-slate-800 dark:text-slate-100">Edit {{ props.widgetTypeLabel }}</h3>
      <button
        @click="emit('close')"
        class="rounded p-1 text-slate-400 transition hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-slate-800 dark:hover:text-slate-200"
      >
        <iconify-icon icon="lucide:x" class="h-4 w-4" />
      </button>
    </div>

    <div class="grid grid-cols-2 gap-1 rounded-lg bg-slate-100 p-1 text-xs font-semibold dark:bg-slate-800/70">
      <button
        @click="activeTab = 'data'"
        :class="['rounded-md px-2 py-1.5 transition', activeTab === 'data' ? 'bg-white text-slate-800 shadow-sm dark:bg-slate-700 dark:text-slate-100' : 'text-slate-500 dark:text-slate-400']"
      >
        Data
      </button>
      <button
        @click="activeTab = 'customize'"
        :class="['rounded-md px-2 py-1.5 transition', activeTab === 'customize' ? 'bg-white text-slate-800 shadow-sm dark:bg-slate-700 dark:text-slate-100' : 'text-slate-500 dark:text-slate-400']"
      >
        Customize
      </button>
    </div>

    <div class="mt-3 min-h-0 flex-1 space-y-3 overflow-y-auto pr-1 pb-8">
      <EditChart
        v-if="props.widget.type === 'chart'"
        :widget="props.widget"
        :active-tab="activeTab"
        :dimensions="props.chartDimensions || []"
        :measures="props.chartMeasures || []"
        @recompute-chart="emit('recompute-chart', $event)"
      />
      <EditKPI v-else-if="props.widget.type === 'kpi'" :widget="props.widget" :is-loading="Boolean(props.widget?.isLoadingData)" @apply-kpi="emit('recompute-kpi', $event)" />
      <EditInsight v-else-if="props.widget.type === 'insight'" :widget="props.widget" :is-loading="Boolean(props.widget?.isLoadingData)" />
      <EditList v-else-if="props.widget.type === 'list'" :widget="props.widget" />
      <EditSummary v-else-if="props.widget.type === 'summary'" :widget="props.widget" />

      <div v-if="activeTab === 'customize'" class="rounded-lg border border-slate-200 p-3 dark:border-slate-700">
        <div class="mb-2 flex items-center justify-between">
          <p class="text-sm font-semibold text-slate-700 dark:text-slate-200">Details</p>
        </div>
        <div class="space-y-2">
          <label class="flex items-center justify-between text-sm text-slate-600 dark:text-slate-300">
            <span>Title</span>
            <input type="checkbox" v-model="props.widget.ui.showTitle" class="accent-indigo-600" />
          </label>
          <input
            v-model="props.widget.ui.titleText"
            @blur="emit('update-title')"
            class="w-full rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-sm outline-none focus:border-indigo-400 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
            placeholder="Edit title"
          />
          <div>
            <p class="mb-1 text-xs text-slate-500 dark:text-slate-400">Alignment</p>
            <div class="grid grid-cols-3 gap-1 rounded-md bg-slate-100 p-1 dark:bg-slate-800">
              <button @click="props.widget.ui.align = 'left'" :class="['rounded px-2 py-1 text-xs', props.widget.ui.align === 'left' ? 'bg-white dark:bg-slate-700' : 'text-slate-500']">Left</button>
              <button @click="props.widget.ui.align = 'center'" :class="['rounded px-2 py-1 text-xs', props.widget.ui.align === 'center' ? 'bg-white dark:bg-slate-700' : 'text-slate-500']">Center</button>
              <button @click="props.widget.ui.align = 'right'" :class="['rounded px-2 py-1 text-xs', props.widget.ui.align === 'right' ? 'bg-white dark:bg-slate-700' : 'text-slate-500']">Right</button>
            </div>
          </div>
          <label class="flex items-center justify-between text-sm text-slate-600 dark:text-slate-300">
            <span>Banding</span>
            <input type="checkbox" v-model="props.widget.ui.banding" class="accent-indigo-600" />
          </label>
          <div>
            <p class="mb-1 text-xs text-slate-500 dark:text-slate-400">Variation</p>
            <div class="grid grid-cols-2 gap-1 rounded-md bg-slate-100 p-1 dark:bg-slate-800">
              <template v-if="props.widget.type === 'chart'">
                <button @click="props.widget.ui.chartVariant = 'default'" :class="['rounded px-2 py-1 text-xs', props.widget.ui.chartVariant === 'default' ? 'bg-white dark:bg-slate-700' : 'text-slate-500']">Default</button>
                <button @click="props.widget.ui.chartVariant = 'executive'" :class="['rounded px-2 py-1 text-xs', props.widget.ui.chartVariant === 'executive' ? 'bg-white dark:bg-slate-700' : 'text-slate-500']">Executive</button>
                <button @click="props.widget.ui.chartVariant = 'compact'" :class="['rounded px-2 py-1 text-xs', props.widget.ui.chartVariant === 'compact' ? 'bg-white dark:bg-slate-700' : 'text-slate-500']">Compact</button>
                <button @click="props.widget.ui.chartVariant = 'contrast'" :class="['rounded px-2 py-1 text-xs', props.widget.ui.chartVariant === 'contrast' ? 'bg-white dark:bg-slate-700' : 'text-slate-500']">Contrast</button>
              </template>
              <template v-else-if="props.widget.type === 'kpi'">
                <button @click="props.widget.ui.kpiVariant = 'default'" :class="['rounded px-2 py-1 text-xs', props.widget.ui.kpiVariant === 'default' ? 'bg-white dark:bg-slate-700' : 'text-slate-500']">Default</button>
                <button @click="props.widget.ui.kpiVariant = 'sparkline'" :class="['rounded px-2 py-1 text-xs', props.widget.ui.kpiVariant === 'sparkline' ? 'bg-white dark:bg-slate-700' : 'text-slate-500']">Sparkline</button>
                <button @click="props.widget.ui.kpiVariant = 'comparison'" :class="['rounded px-2 py-1 text-xs', props.widget.ui.kpiVariant === 'comparison' ? 'bg-white dark:bg-slate-700' : 'text-slate-500']">Comparison</button>
                <button @click="props.widget.ui.kpiVariant = 'minimal'" :class="['rounded px-2 py-1 text-xs', props.widget.ui.kpiVariant === 'minimal' ? 'bg-white dark:bg-slate-700' : 'text-slate-500']">Minimal</button>
              </template>
              <template v-else>
                <button @click="props.widget.ui.widgetVariant = 'default'" :class="['rounded px-2 py-1 text-xs', props.widget.ui.widgetVariant === 'default' ? 'bg-white dark:bg-slate-700' : 'text-slate-500']">Default</button>
                <button @click="props.widget.ui.widgetVariant = 'compact'" :class="['rounded px-2 py-1 text-xs', props.widget.ui.widgetVariant === 'compact' ? 'bg-white dark:bg-slate-700' : 'text-slate-500']">Compact</button>
                <button @click="props.widget.ui.widgetVariant = 'card'" :class="['rounded px-2 py-1 text-xs', props.widget.ui.widgetVariant === 'card' ? 'bg-white dark:bg-slate-700' : 'text-slate-500']">Card</button>
                <button @click="props.widget.ui.widgetVariant = 'minimal'" :class="['rounded px-2 py-1 text-xs', props.widget.ui.widgetVariant === 'minimal' ? 'bg-white dark:bg-slate-700' : 'text-slate-500']">Minimal</button>
              </template>
            </div>
          </div>
        </div>
      </div>
    </div>
  </aside>
</template>
