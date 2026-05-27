<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { marked } from 'marked'
import workspaceApi from '@/services/workspaceApi'

const route = useRoute()
const token = computed(() => route.params.token as string)

// Theme
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

const report = ref<any>(null)
const isLoading = ref(true)
const errorMsg = ref('')

const parsedSummary = computed(() => {
  if (!report.value?.ai_summary) return ''
  try { return marked.parse(report.value.ai_summary) as string }
  catch { return report.value.ai_summary }
})

async function loadReport() {
  isLoading.value = true
  try {
    report.value = await workspaceApi.getSharedReport(token.value)
  } catch (err: any) {
    errorMsg.value = err?.response?.data?.detail || 'Report not found or has been removed.'
  } finally {
    isLoading.value = false
  }
}

function downloadCSV() {
  if (!report.value?.data?.length) return
  const cols = report.value.columns
  const rows = report.value.data
  const header = cols.join(',')
  const csvRows = rows.map((r: any) => cols.map((c: string) => `"${String(r[c] || '').replace(/"/g, '""')}"`).join(','))
  const blob = new Blob([header + '\n' + csvRows.join('\n')], { type: 'text/csv' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${report.value.title || 'report'}.csv`
  a.click()
  URL.revokeObjectURL(url)
}

onMounted(() => {
  initTheme()
  loadReport()
})
</script>

<template>
  <div :class="['min-h-screen transition-colors duration-300', isDark ? 'bg-zinc-950 text-white' : 'bg-gradient-to-br from-slate-50 via-white to-purple-50/30 text-slate-900']">
    <!-- Top Bar -->
    <div :class="['sticky top-0 z-50 backdrop-blur-xl border-b', isDark ? 'bg-zinc-900/80 border-white/[0.06]' : 'bg-white/80 border-slate-200/60']">
      <div class="max-w-6xl mx-auto px-6 h-14 flex items-center justify-between">
        <div class="flex items-center gap-3">
          <div class="h-8 w-8 rounded-lg bg-gradient-to-br from-purple-500 to-indigo-600 flex items-center justify-center text-white text-xs font-bold shadow-lg shadow-purple-500/25">R</div>
          <div>
            <h1 :class="['text-sm font-bold', isDark ? 'text-white' : 'text-slate-800']">Shared Report</h1>
            <p v-if="report" class="text-[10px] text-slate-500">{{ report.workspace_name }}</p>
          </div>
        </div>
        <button @click="toggleTheme" :class="['p-2 rounded-lg transition', isDark ? 'hover:bg-zinc-800 text-zinc-400' : 'hover:bg-slate-100 text-slate-500']">
          <svg v-if="isDark" xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="5"/><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/></svg>
          <svg v-else xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>
        </button>
      </div>
    </div>

    <div class="max-w-6xl mx-auto px-6 py-8 space-y-6">
      <!-- Loading -->
      <div v-if="isLoading" class="flex items-center justify-center py-20">
        <div class="text-center space-y-3">
          <svg class="animate-spin h-8 w-8 mx-auto text-purple-500" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>
          <p :class="['text-sm', isDark ? 'text-zinc-500' : 'text-slate-400']">Loading report...</p>
        </div>
      </div>

      <!-- Error -->
      <div v-else-if="errorMsg" class="flex flex-col items-center justify-center py-20">
        <div :class="['p-8 rounded-2xl border text-center max-w-md', isDark ? 'bg-red-900/10 border-red-800/30' : 'bg-red-50 border-red-200']">
          <svg xmlns="http://www.w3.org/2000/svg" width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" :class="['mx-auto mb-4', isDark ? 'text-red-400' : 'text-red-500']"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>
          <p :class="['text-sm font-semibold', isDark ? 'text-red-300' : 'text-red-700']">{{ errorMsg }}</p>
        </div>
      </div>

      <!-- Report Content -->
      <template v-else-if="report">
        <!-- Report Header -->
        <div :class="['p-6 rounded-2xl border', isDark ? 'bg-gradient-to-r from-purple-900/20 to-indigo-900/10 border-purple-800/30' : 'bg-gradient-to-r from-purple-50 to-indigo-50 border-purple-200/50']">
          <h2 :class="['text-xl font-bold mb-1', isDark ? 'text-white' : 'text-slate-800']">{{ report.title || 'Report' }}</h2>
          <p v-if="report.question" :class="['text-sm', isDark ? 'text-purple-300/70' : 'text-purple-600/70']">
            <span class="font-medium">Query:</span> {{ report.question }}
          </p>
          <div class="flex items-center gap-4 mt-3">
            <span :class="['text-[11px] px-2 py-0.5 rounded-md font-medium', isDark ? 'bg-emerald-500/20 text-emerald-300' : 'bg-emerald-100 text-emerald-700']">{{ report.row_count }} rows</span>
            <span :class="['text-[11px] px-2 py-0.5 rounded-md font-medium', isDark ? 'bg-blue-500/20 text-blue-300' : 'bg-blue-100 text-blue-700']">{{ report.columns?.length || 0 }} columns</span>
            <span v-if="report.created_at" :class="['text-[10px]', isDark ? 'text-zinc-500' : 'text-slate-400']">Shared {{ new Date(report.created_at).toLocaleDateString() }}</span>
          </div>
        </div>

        <!-- Data Table -->
        <div v-if="report.data?.length" :class="['rounded-2xl border shadow-sm overflow-hidden flex flex-col', isDark ? 'bg-zinc-900/90 border-white/[0.06]' : 'bg-white border-slate-200/60']" style="max-height: 500px">
          <div :class="['flex items-center justify-between p-4 border-b shrink-0', isDark ? 'border-white/[0.06] bg-white/[0.02]' : 'border-slate-100 bg-slate-50/50']">
            <div class="flex items-center gap-2">
              <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" :class="isDark ? 'text-emerald-400' : 'text-emerald-600'"><path d="M12 3v18"/><rect width="18" height="18" x="3" y="3" rx="2"/><path d="M3 9h18"/><path d="M3 15h18"/></svg>
              <span :class="['text-sm font-bold', isDark ? 'text-white' : 'text-slate-800']">Data</span>
              <span :class="['text-[10px]', isDark ? 'text-zinc-500' : 'text-slate-400']">{{ report.row_count }} rows</span>
            </div>
            <button @click="downloadCSV" :class="['px-3 py-1.5 text-xs font-medium rounded-lg border transition flex items-center gap-1.5', isDark ? 'border-zinc-700 text-slate-300 hover:bg-zinc-800' : 'border-slate-200 text-slate-600 hover:bg-slate-50']">
              <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
              CSV
            </button>
          </div>
          <div class="flex-1 overflow-auto">
            <table class="w-full text-sm">
              <thead :class="['sticky top-0 z-10 backdrop-blur-sm', isDark ? 'bg-zinc-900/90' : 'bg-slate-50']">
                <tr>
                  <th v-for="col in report.columns" :key="col" :class="['text-left px-4 py-2.5 font-semibold text-xs whitespace-nowrap border-b', isDark ? 'text-purple-300/80 border-white/[0.06]' : 'text-purple-600/70 border-slate-200']">{{ col }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(row, ri) in report.data" :key="ri" :class="['border-b transition', isDark ? 'border-white/[0.04] hover:bg-white/[0.02]' : 'border-slate-100 hover:bg-slate-50']">
                  <td v-for="col in report.columns" :key="col" :class="['px-4 py-2 whitespace-nowrap', isDark ? 'text-white/60' : 'text-slate-600']">{{ row[col] ?? '—' }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <!-- SQL Query (collapsible) -->
        <div v-if="report.sql_query" :class="['rounded-2xl border overflow-hidden', isDark ? 'bg-zinc-900/60 border-white/[0.06]' : 'bg-white border-slate-200/60']">
          <details class="group">
            <summary :class="['px-5 py-3 cursor-pointer select-none text-xs font-semibold uppercase tracking-wider flex items-center gap-2', isDark ? 'text-zinc-400 hover:text-zinc-300' : 'text-slate-500 hover:text-slate-700']">
              <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>
              SQL Query
            </summary>
            <div :class="['px-5 pb-4', isDark ? 'border-t border-white/[0.04]' : 'border-t border-slate-100']">
              <pre :class="['mt-3 text-[11px] font-mono p-4 rounded-xl overflow-x-auto whitespace-pre-wrap', isDark ? 'bg-black/40 text-emerald-300/80' : 'bg-slate-50 text-slate-600']">{{ report.sql_query }}</pre>
            </div>
          </details>
        </div>

        <!-- AI Analysis -->
        <div v-if="report.ai_summary" :class="['rounded-2xl border overflow-hidden', isDark ? 'bg-zinc-900/60 border-white/[0.06]' : 'bg-white border-slate-200/60']">
          <div :class="['flex items-center gap-2 px-5 py-3 border-b', isDark ? 'border-white/[0.06] bg-purple-500/5' : 'border-slate-100 bg-purple-50/50']">
            <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="text-purple-500"><path d="m12 3-1.912 5.813a2 2 0 0 1-1.275 1.275L3 12l5.813 1.912a2 2 0 0 1 1.275 1.275L12 21l1.912-5.813a2 2 0 0 1 1.275-1.275L21 12l-5.813-1.912a2 2 0 0 1-1.275-1.275L12 3Z"/></svg>
            <span :class="['text-sm font-bold', isDark ? 'text-purple-300' : 'text-purple-700']">AI Analysis</span>
          </div>
          <div class="p-6">
            <div :class="['prose prose-sm max-w-none', isDark ? 'prose-invert prose-headings:text-slate-200' : 'prose-headings:text-slate-800']" v-html="parsedSummary"></div>
          </div>
        </div>

        <!-- No data message -->
        <div v-if="!report.data?.length && !report.ai_summary" :class="['text-center py-12 rounded-2xl border-2 border-dashed', isDark ? 'border-zinc-800 text-zinc-600' : 'border-slate-200 text-slate-400']">
          <p class="text-sm">This report contains no data rows.</p>
        </div>
      </template>
    </div>
  </div>
</template>
