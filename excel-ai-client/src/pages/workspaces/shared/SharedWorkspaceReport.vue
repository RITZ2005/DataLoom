<script setup lang="ts">
/**
 * SharedWorkspaceReport.vue
 * Public report generation interface for shared workspaces — no auth required.
 * Supports AI queries, custom SQL, data table, CSV download, and AI summarization.
 */
import { ref, computed, onMounted, nextTick } from 'vue'
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

// UI State
const queryMode = ref<'ai' | 'custom_sql'>('ai')
const inputQuery = ref('')
const customSql = ref('')
const reportTitle = ref('')
const isGenerating = ref(false)
const currentReport = ref<any>(null)
const aiReportContent = ref('')
const isGeneratingAI = ref(false)
const workspaceName = ref('')
const errorMessage = ref('')

const parsedAiReport = computed(() => {
  if (!aiReportContent.value) return ''
  try { return marked.parse(aiReportContent.value) as string }
  catch { return aiReportContent.value }
})

// Load workspace name from dashboard endpoint
async function loadMeta() {
  try {
    const data = await workspaceApi.getSharedWorkspaceDashboard(token.value)
    workspaceName.value = data.workspace_name || 'Workspace'
  } catch {}
}

async function generateReport() {
  if (isGenerating.value) return
  isGenerating.value = true
  currentReport.value = null
  aiReportContent.value = ''

  try {
    let response: any
    const title = reportTitle.value.trim()
    errorMessage.value = ''

    if (queryMode.value === 'ai') {
      const query = inputQuery.value.trim()
      if (!query) { isGenerating.value = false; return }
      response = await workspaceApi.sharedReportChat(token.value, query, title || undefined)
    } else {
      const sql = customSql.value.trim()
      if (!sql) { isGenerating.value = false; return }
      response = await workspaceApi.sharedReportSql(token.value, { title: title || 'Custom SQL Report', sql_query: sql })
    }

    if (response.status === 'error') {
      errorMessage.value = response.message || 'Query failed. Please try a different question.'
      currentReport.value = null
      return
    }
    currentReport.value = response
  } catch (err: any) {
    errorMessage.value = err?.response?.data?.detail || 'Report generation failed. Please try again.'
    console.error('Report generation failed', err)
  } finally {
    isGenerating.value = false
  }
}

function downloadCSV() {
  if (!currentReport.value?.data?.length) return
  const cols = currentReport.value.columns
  const rows = currentReport.value.data
  const header = cols.join(',')
  const csvRows = rows.map((r: any) => cols.map((c: string) => `"${String(r[c] || '').replace(/"/g, '""')}"`).join(','))
  const csv = [header, ...csvRows].join('\n')
  const blob = new Blob([csv], { type: 'text/csv' })
  const url = window.URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${(reportTitle.value || 'report').replace(/[^a-z0-9]/gi, '_').toLowerCase()}.csv`
  a.click()
}

async function forwardToAIReport() {
  if (!currentReport.value) return
  isGeneratingAI.value = true
  aiReportContent.value = ''

  try {
    const response = await workspaceApi.sharedReportSummarize(token.value, {
      question: reportTitle.value || inputQuery.value || 'Custom Query',
      sql_query: currentReport.value.sql || '',
      columns: currentReport.value.columns || [],
      data: currentReport.value.data || [],
    })
    if (response.status === 'success') {
      aiReportContent.value = response.summary
      nextTick(() => {
        document.getElementById('ai-summary-section')?.scrollIntoView({ behavior: 'smooth', block: 'end' })
      })
    }
  } catch (err: any) {
    console.error('AI summarization failed', err)
  } finally {
    isGeneratingAI.value = false
  }
}

function resetReport() {
  reportTitle.value = ''
  inputQuery.value = ''
  customSql.value = ''
  currentReport.value = null
  aiReportContent.value = ''
  queryMode.value = 'ai'
}

onMounted(() => { initTheme(); loadMeta() })
</script>

<template>
  <div :class="['min-h-screen transition-colors duration-300', isDark ? 'bg-zinc-950 text-white' : 'bg-gradient-to-br from-slate-50 via-white to-purple-50/30 text-slate-900']">
    <!-- Header -->
    <header :class="['sticky top-0 z-50 backdrop-blur-xl border-b transition-colors', isDark ? 'bg-zinc-950/80 border-white/[0.06]' : 'bg-white/80 border-slate-200/60']">
      <div class="max-w-7xl mx-auto flex items-center justify-between px-6 py-3">
        <div class="flex items-center gap-3">
          <div class="h-9 w-9 rounded-xl bg-gradient-to-br from-purple-500 to-indigo-600 flex items-center justify-center text-white font-bold text-sm shadow-lg shadow-purple-500/25">R</div>
          <div>
            <h1 :class="['text-sm font-bold', isDark ? 'text-white' : 'text-slate-800']">{{ workspaceName }} Reports</h1>
            <p class="text-[10px] text-slate-400">Shared Report Generator</p>
          </div>
        </div>
        <div class="flex items-center gap-3">
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

    <!-- Content -->
    <div class="max-w-5xl mx-auto px-6 py-8 space-y-6">

      <!-- Query Configuration -->
      <div :class="['rounded-2xl p-6 border shadow-sm', isDark ? 'bg-zinc-900/90 border-white/[0.06]' : 'bg-white border-slate-200/60']">
        <div class="flex items-center justify-between mb-4">
          <div :class="['flex items-center p-1 rounded-lg', isDark ? 'bg-zinc-800' : 'bg-slate-100']">
            <button @click="queryMode = 'ai'" :class="['px-4 py-1.5 text-xs font-medium rounded-md transition-all flex items-center gap-1.5', queryMode === 'ai' ? isDark ? 'bg-zinc-700 text-white shadow-sm' : 'bg-white text-slate-900 shadow-sm' : isDark ? 'text-slate-400' : 'text-slate-500']">
              <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m12 3-1.912 5.813a2 2 0 0 1-1.275 1.275L3 12l5.813 1.912a2 2 0 0 1 1.275 1.275L12 21l1.912-5.813a2 2 0 0 1 1.275-1.275L21 12l-5.813-1.912a2 2 0 0 1-1.275-1.275L12 3Z"/></svg>
              AI Query
            </button>
            <button @click="queryMode = 'custom_sql'" :class="['px-4 py-1.5 text-xs font-medium rounded-md transition-all flex items-center gap-1.5', queryMode === 'custom_sql' ? isDark ? 'bg-zinc-700 text-white shadow-sm' : 'bg-white text-slate-900 shadow-sm' : isDark ? 'text-slate-400' : 'text-slate-500']">
              <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>
              Custom SQL
            </button>
          </div>
          <button @click="resetReport" :class="['px-3 py-1.5 text-xs font-medium rounded-lg border transition flex items-center gap-1.5', isDark ? 'border-zinc-700 text-slate-300 hover:bg-zinc-800' : 'border-slate-200 text-slate-600 hover:bg-slate-50']">
            <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
            New Report
          </button>
        </div>

        <div class="space-y-4">
          <div>
            <label :class="['text-xs font-medium mb-1.5 block', isDark ? 'text-slate-400' : 'text-slate-500']">Report Title (Optional)</label>
            <input v-model="reportTitle" placeholder="e.g. Q3 Regional Sales Summary" :class="['w-full h-10 rounded-xl border px-4 text-sm outline-none transition', isDark ? 'bg-zinc-800 border-zinc-700 text-white placeholder-zinc-500 focus:border-purple-500' : 'bg-slate-50 border-slate-200 text-slate-800 placeholder-slate-400 focus:border-purple-400']" />
          </div>

          <div v-if="queryMode === 'ai'">
            <label :class="['text-xs font-medium mb-1.5 block', isDark ? 'text-slate-400' : 'text-slate-500']">What report do you need?</label>
            <input v-model="inputQuery" placeholder="e.g. Get total sales grouped by region" @keyup.enter="generateReport" :class="['w-full h-12 rounded-xl border px-4 text-sm outline-none transition', isDark ? 'bg-zinc-800 border-zinc-700 text-white placeholder-zinc-500 focus:border-purple-500' : 'bg-slate-50 border-slate-200 text-slate-800 placeholder-slate-400 focus:border-purple-400']" />
          </div>

          <div v-if="queryMode === 'custom_sql'">
            <label :class="['text-xs font-medium mb-1.5 block', isDark ? 'text-slate-400' : 'text-slate-500']">PostgreSQL Query</label>
            <textarea v-model="customSql" placeholder="SELECT * FROM table_name WHERE..." @keydown.ctrl.enter="generateReport" :class="['w-full h-24 p-3 text-sm font-mono rounded-xl border resize-none outline-none transition', isDark ? 'bg-zinc-800 border-zinc-700 text-white placeholder-zinc-500 focus:border-purple-500' : 'bg-slate-50 border-slate-200 text-slate-800 placeholder-slate-400 focus:border-purple-400']"></textarea>
          </div>

          <div class="flex justify-end pt-2">
            <button @click="generateReport" :disabled="isGenerating || (queryMode === 'ai' ? !inputQuery.trim() : !customSql.trim())" class="h-10 px-6 bg-gradient-to-r from-purple-600 to-indigo-600 hover:from-purple-500 hover:to-indigo-500 text-white text-sm font-semibold rounded-xl shadow-lg shadow-purple-500/20 disabled:opacity-40 transition flex items-center gap-2">
              <svg v-if="isGenerating" class="animate-spin h-4 w-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"/></svg>
              <svg v-else xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg>
              {{ isGenerating ? 'Running...' : 'Run Report' }}
            </button>
          </div>
        </div>
      </div>

      <!-- Results Table -->
      <div v-if="currentReport" :class="['rounded-2xl border shadow-sm overflow-hidden flex flex-col', isDark ? 'bg-zinc-900/90 border-white/[0.06]' : 'bg-white border-slate-200/60']" style="max-height: 500px">
        <div :class="['flex items-center justify-between p-4 border-b shrink-0', isDark ? 'border-white/[0.06] bg-white/[0.02]' : 'border-slate-100 bg-slate-50/50']">
          <div class="flex items-center gap-3">
            <div :class="['h-8 w-8 rounded-lg flex items-center justify-center', isDark ? 'bg-emerald-500/20 text-emerald-400' : 'bg-emerald-100 text-emerald-600']">
              <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 3v18"/><rect width="18" height="18" x="3" y="3" rx="2"/><path d="M3 9h18"/><path d="M3 15h18"/></svg>
            </div>
            <div>
              <h3 :class="['text-sm font-bold', isDark ? 'text-white' : 'text-slate-800']">{{ reportTitle || 'Report Results' }}</h3>
              <p class="text-[10px] text-slate-500">{{ currentReport.row_count }} rows retrieved</p>
            </div>
          </div>
          <div class="flex gap-2">
            <button @click="downloadCSV" :class="['px-3 py-2 text-xs font-medium rounded-lg border transition flex items-center gap-1.5', isDark ? 'border-zinc-700 text-slate-300 hover:bg-zinc-800' : 'border-slate-200 text-slate-600 hover:bg-slate-50']">
              <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
              Export CSV
            </button>
            <button @click="forwardToAIReport" :disabled="isGeneratingAI" class="px-3 py-2 text-xs font-semibold rounded-lg bg-purple-600 hover:bg-purple-700 text-white shadow-md shadow-purple-500/20 disabled:opacity-40 transition flex items-center gap-1.5">
              <svg v-if="isGeneratingAI" class="animate-spin h-3 w-3" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>
              <svg v-else xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m12 3-1.912 5.813a2 2 0 0 1-1.275 1.275L3 12l5.813 1.912a2 2 0 0 1 1.275 1.275L12 21l1.912-5.813a2 2 0 0 1 1.275-1.275L21 12l-5.813-1.912a2 2 0 0 1-1.275-1.275L12 3Z"/></svg>
              Analyze with AI
            </button>
          </div>
        </div>

        <div class="flex-1 overflow-auto">
          <table class="w-full text-sm">
            <thead :class="['sticky top-0 z-10 backdrop-blur-sm', isDark ? 'bg-zinc-900/90' : 'bg-slate-50']">
              <tr>
                <th v-for="col in currentReport.columns" :key="col" :class="['text-left px-4 py-2.5 font-semibold text-xs whitespace-nowrap border-b', isDark ? 'text-purple-300/80 border-white/[0.06]' : 'text-purple-600/70 border-slate-200']">{{ col }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(row, ri) in currentReport.data" :key="ri" :class="['border-b transition', isDark ? 'border-white/[0.04] hover:bg-white/[0.02]' : 'border-slate-100 hover:bg-slate-50']">
                <td v-for="col in currentReport.columns" :key="col" :class="['px-4 py-2 whitespace-nowrap', isDark ? 'text-white/60' : 'text-slate-600']">{{ row[col] ?? '—' }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- Zero rows hint -->
        <div v-if="currentReport.data?.length === 0" :class="['px-4 py-3 text-xs flex items-center gap-2 border-t', isDark ? 'bg-amber-900/10 border-white/[0.04] text-amber-300' : 'bg-amber-50 border-amber-100 text-amber-700']">
          <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
          No matching rows found. Try broadening your query or check column value casing.
        </div>

        <!-- Generated SQL (collapsible) -->
        <div v-if="currentReport.sql" :class="['px-4 py-2 border-t', isDark ? 'border-white/[0.04]' : 'border-slate-100']">
          <details>
            <summary :class="['text-[10px] font-semibold uppercase tracking-wider cursor-pointer select-none', isDark ? 'text-white/30 hover:text-white/50' : 'text-slate-400 hover:text-slate-600']">Generated SQL</summary>
            <pre :class="['mt-2 text-[11px] font-mono p-3 rounded-lg overflow-x-auto whitespace-pre-wrap', isDark ? 'bg-black/30 text-emerald-300/80' : 'bg-slate-50 text-slate-600']">{{ currentReport.sql }}</pre>
          </details>
        </div>
      </div>

      <!-- Error message -->
      <div v-else-if="errorMessage" :class="['flex items-start gap-3 p-4 rounded-2xl border', isDark ? 'bg-red-900/10 border-red-800/30 text-red-300' : 'bg-red-50 border-red-200 text-red-700']">
        <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="shrink-0 mt-0.5"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>
        <div>
          <p class="text-sm font-semibold">Query Error</p>
          <p class="text-xs mt-1 opacity-80">{{ errorMessage }}</p>
        </div>
      </div>

      <!-- Loading state -->
      <div v-else-if="isGenerating" class="flex items-center justify-center py-16">
        <div class="text-center">
          <div class="relative mx-auto mb-5 h-16 w-16">
            <div class="absolute inset-0 animate-spin rounded-full border-[3px] border-purple-100 border-t-purple-500"/>
            <div class="absolute inset-2 animate-spin rounded-full border-[3px] border-indigo-100 border-b-indigo-500" style="animation-direction:reverse;animation-duration:1.2s"/>
          </div>
          <p :class="['text-sm font-semibold', isDark ? 'text-slate-300' : 'text-slate-700']">Generating report…</p>
        </div>
      </div>

      <!-- Empty state -->
      <div v-else :class="['flex flex-col items-center justify-center py-16 rounded-2xl border-2 border-dashed', isDark ? 'border-zinc-800 text-zinc-600' : 'border-slate-200 text-slate-300']">
        <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" class="mb-4 opacity-50"><path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>
        <p :class="['text-sm', isDark ? 'text-zinc-500' : 'text-slate-400']">Run an AI query or Custom SQL to view report results.</p>
      </div>

      <!-- AI Summary -->
      <div id="ai-summary-section" v-if="aiReportContent || isGeneratingAI" :class="['rounded-2xl border shadow-sm overflow-hidden', isDark ? 'bg-zinc-900/90 border-purple-500/20 ring-1 ring-purple-500/10' : 'bg-white border-purple-200/60 ring-1 ring-purple-500/10']">
        <div :class="['flex items-center p-4 border-b', isDark ? 'bg-purple-900/10 border-purple-500/10' : 'bg-purple-50/50 border-purple-100']">
          <div class="flex items-center gap-3">
            <div :class="['h-8 w-8 rounded-lg flex items-center justify-center', isDark ? 'bg-purple-500/20 text-purple-400' : 'bg-purple-100 text-purple-600']">
              <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 8V4H8"/><rect width="16" height="12" x="4" y="8" rx="2"/><path d="M2 14h2"/><path d="M20 14h2"/><path d="M15 13v2"/><path d="M9 13v2"/></svg>
            </div>
            <div>
              <h3 :class="['text-sm font-bold', isDark ? 'text-white' : 'text-slate-800']">AI Generated Insight</h3>
              <p class="text-[10px] text-slate-500">Automated analysis of the retrieved data</p>
            </div>
          </div>
        </div>
        <div class="p-8">
          <div v-if="isGeneratingAI" class="flex flex-col items-center justify-center py-12 text-purple-500 gap-4">
            <svg class="animate-spin h-10 w-10" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"/></svg>
            <p class="text-sm font-medium animate-pulse">Analyzing data and generating insights...</p>
          </div>
          <div v-else-if="aiReportContent" class="prose prose-sm dark:prose-invert max-w-none" v-html="parsedAiReport"></div>
        </div>
      </div>
    </div>

    <!-- Footer -->
    <footer :class="['border-t py-4 mt-8 text-center', isDark ? 'border-white/[0.06]' : 'border-slate-200/60']">
      <p class="text-[10px] text-slate-400">Powered by Workspace Analytics</p>
    </footer>
  </div>
</template>
