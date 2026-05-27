<script setup lang="ts">
const props = defineProps<{
  open: boolean
  elementLabel: string
  styles: Array<{ id: string; name: string; description: string }>
  selectedStyleId: string
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'apply'): void
  (e: 'select-style', styleId: string): void
}>()

function getPreviewShell(styleId: string): string {
  if (styleId === 'executive') return 'bg-white'
  if (styleId === 'compact') return 'bg-[#fbfbfd]'
  return 'bg-[#fcfcff]'
}

function getPreviewAccent(styleId: string): string {
  if (styleId === 'executive') return '#4f46e5'
  if (styleId === 'compact') return '#6366f1'
  return '#6d6ae8'
}

function getPreviewPanelWidth(styleId: string): string {
  if (styleId === 'executive') return 'w-[74px]'
  if (styleId === 'compact') return 'w-[58px]'
  return 'w-[52px]'
}
</script>

<template>
  <div v-if="props.open" class="fixed inset-0 z-[70] flex items-center justify-center p-4">
    <div class="absolute inset-0 bg-black/55 backdrop-blur-[2px]" @click="emit('close')" />

    <div class="relative z-10 w-full max-w-4xl rounded-[28px] border border-slate-200 bg-white shadow-2xl dark:border-white/10 dark:bg-slate-900">
      <div class="flex items-center justify-between border-b border-slate-200 px-6 py-4 dark:border-white/10">
        <div>
          <h3 class="text-2xl font-semibold text-slate-900 dark:text-slate-100">Choose style</h3>
          <p class="mt-1 text-sm text-slate-500 dark:text-slate-400">Select a style for {{ props.elementLabel }}</p>
        </div>
        <button
          @click="emit('close')"
          class="inline-flex h-8 w-8 items-center justify-center rounded-md bg-slate-900 text-white transition hover:bg-black dark:bg-white dark:text-slate-900"
          title="Close"
        >
          <iconify-icon icon="lucide:x" class="h-4 w-4" />
        </button>
      </div>

      <div class="px-6 py-4">
        <div class="mb-3 flex items-center justify-between">
          <p class="text-sm font-semibold text-slate-500 dark:text-slate-400">Available styles</p>
          <p class="text-sm font-semibold text-indigo-600 dark:text-indigo-400">{{ props.styles.find(style => style.id === props.selectedStyleId)?.name || 'Default' }}</p>
        </div>

        <div class="max-h-[500px] space-y-5 overflow-y-auto pr-1">
          <button
            v-for="s in props.styles"
            :key="s.id"
            @click="emit('select-style', s.id)"
            :class="[
              'w-full rounded-2xl border p-4 text-left transition',
              props.selectedStyleId === s.id
                ? 'border-indigo-300 bg-indigo-50/70 dark:border-indigo-500/40 dark:bg-indigo-500/10'
                : 'border-slate-200 bg-slate-50 hover:border-slate-300 dark:border-slate-700 dark:bg-slate-800/60 dark:hover:border-slate-600',
            ]"
          >
            <div class="mb-3 flex items-center justify-between gap-4">
              <p class="text-sm font-semibold text-slate-700 dark:text-slate-200">{{ s.name }}</p>
              <span :class="['inline-flex h-5 w-5 items-center justify-center rounded-full border', props.selectedStyleId === s.id ? 'border-indigo-400 bg-indigo-100 text-indigo-700 dark:border-indigo-400 dark:bg-indigo-500/20 dark:text-indigo-300' : 'border-slate-300 bg-white dark:border-slate-600 dark:bg-slate-900']">
                <iconify-icon v-if="props.selectedStyleId === s.id" icon="lucide:check" class="h-3.5 w-3.5" />
              </span>
            </div>
            <div class="overflow-hidden rounded-xl border border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-900/60">
              <div class="flex h-56 w-full">
                <div :class="['border-r border-slate-100 bg-[#f6f7fb] dark:border-slate-800 dark:bg-slate-950', getPreviewPanelWidth(s.id)]" />
                <div :class="['flex-1 p-4', getPreviewShell(s.id)]">
                  <div class="mb-3 flex items-start justify-between gap-4">
                    <div>
                      <div class="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">{{ props.elementLabel }}</div>
                      <div class="mt-1 text-xl font-semibold text-slate-800">Title goes here</div>
                    </div>
                    <div v-if="s.id !== 'default'" class="flex items-center gap-2 text-[11px] text-slate-500">
                      <span>{{ s.id === 'executive' ? 'Title 1' : 'Metric 1' }}</span>
                      <span class="rounded-md border border-slate-200 px-2 py-1">Metric 1</span>
                    </div>
                  </div>

                  <svg viewBox="0 0 520 190" class="h-[170px] w-full">
                    <line x1="34" y1="20" x2="34" y2="162" stroke="#d6dceb" stroke-width="1" />
                    <line x1="34" y1="162" x2="500" y2="162" stroke="#d6dceb" stroke-width="1" />
                    <g fill="#7c879b" font-size="10">
                      <text x="18" y="32">60</text>
                      <text x="18" y="58">50</text>
                      <text x="18" y="84">40</text>
                      <text x="18" y="110">30</text>
                      <text x="18" y="136">20</text>
                      <text x="18" y="162">10</text>
                    </g>
                    <g fill="#7c879b" font-size="10">
                      <text x="54" y="182">Jan 22</text>
                      <text x="136" y="182">Feb 22</text>
                      <text x="218" y="182">Mar 22</text>
                      <text x="300" y="182">Apr 22</text>
                      <text x="382" y="182">May 22</text>
                      <text x="464" y="182">Jun 22</text>
                    </g>
                    <path
                      d="M48 104 C88 88, 114 78, 140 80 S194 142, 220 140 S280 50, 306 48 S388 82, 414 80 S470 112, 492 122"
                      fill="none"
                      :stroke="getPreviewAccent(s.id)"
                      stroke-width="2.2"
                      stroke-linecap="round"
                    />
                    <g :fill="getPreviewAccent(s.id)">
                      <circle cx="48" cy="104" r="2.8" />
                      <circle cx="140" cy="80" r="2.8" />
                      <circle cx="220" cy="140" r="2.8" />
                      <circle cx="306" cy="48" r="2.8" />
                      <circle cx="392" cy="80" r="2.8" />
                      <circle cx="492" cy="122" r="2.8" />
                    </g>
                  </svg>
                </div>
              </div>
            </div>
            <p class="mt-3 text-sm text-slate-500 dark:text-slate-400">{{ s.description }}</p>
          </button>
        </div>
      </div>

      <div class="border-t border-slate-200 px-6 py-4 dark:border-white/10">
        <button
          @click="emit('apply')"
          class="w-full rounded-lg bg-indigo-600 px-4 py-3 text-xl font-semibold text-white transition hover:bg-indigo-700"
        >
          Apply style
        </button>
      </div>
    </div>
  </div>
</template>
