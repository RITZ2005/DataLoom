<script setup lang="ts">
import { ref, onMounted, nextTick, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { marked } from 'marked'
import workspaceApi, { type ChatResponse, type WorkspaceDetailResponse } from '@/services/workspaceApi'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { toast } from 'vue-sonner'

const route = useRoute()
const router = useRouter()
const workspaceId = route.params.workspaceId as string

const workspace = ref<WorkspaceDetailResponse | null>(null)

// UI State
const isSidebarOpen = ref(true)
const queryMode = ref<'ai' | 'custom_sql'>('ai')

// Report State
const inputQuery = ref('')
const customSql = ref('')
const reportTitle = ref('')
const isGenerating = ref(false)
const currentReport = ref<ChatResponse | null>(null)
const aiReportContent = ref<string>('')
const isGeneratingAI = ref(false)

const parsedAiReport = computed(() => {
  if (!aiReportContent.value) return ''
  try {
    return marked.parse(aiReportContent.value) as string
  } catch (e) {
    console.error('Marked parse error:', e)
    return aiReportContent.value
  }
})

const reportHistory = ref<any[]>([])

async function fetchWorkspace() {
  try {
    workspace.value = await workspaceApi.getWorkspaceDetail(workspaceId)
  } catch (err) {
    toast.error('Failed to load workspace')
  }
}

async function fetchHistory() {
  try {
    const history = await workspaceApi.getChatHistory(workspaceId)
    reportHistory.value = history.messages.filter(m => m.role === 'assistant' && m.chatResponse && m.chatResponse.sql).reverse()
  } catch (err) {
    console.error('Failed to load history', err)
  }
}

function getTitleForHistory(msg: any): string {
  // If we stored [Title: My Title] Some question, try to parse it
  const rawQ = msg.chatResponse?.question || ""
  const titleMatch = rawQ.match(/^\[Title: (.*?)\]/)
  if (titleMatch) {
    return titleMatch[1]
  }
  // Otherwise just use the whole question, or 'Custom Query Executed' if that was stored
  return rawQ || "Historical Report"
}

function cleanQuestionForInput(msg: any): string {
  const rawQ = msg.chatResponse?.question || ""
  return rawQ.replace(/^\[Title: .*?\]\s*/, '')
}

function loadHistoricalReport(msg: any) {
  reportTitle.value = getTitleForHistory(msg)
  inputQuery.value = cleanQuestionForInput(msg)
  customSql.value = msg.chatResponse?.sql || ""
  queryMode.value = 'custom_sql' // Switch to custom SQL to show the query
  
  // Just execute the query immediately!
  runHistoricalReport(msg)
}

async function runHistoricalReport(msg: any) {
  const title = getTitleForHistory(msg)
  const sql = msg.chatResponse?.sql
  if (!sql) return
  
  isGenerating.value = true
  currentReport.value = null
  aiReportContent.value = msg.chatResponse?.ai_summary || ''
  
  try {
    const response = await workspaceApi.executeCustomSql(workspaceId, { title, sql_query: sql })
    currentReport.value = response
    toast.success('Report data refreshed')
    await fetchHistory()
  } catch(err) {
    toast.error('Failed to run historical report')
  } finally {
    isGenerating.value = false
  }
}

async function generateReport() {
  if (isGenerating.value) return
  
  isGenerating.value = true
  currentReport.value = null
  aiReportContent.value = ''
  
  try {
    let response;
    const finalTitle = reportTitle.value.trim()

    if (queryMode.value === 'ai') {
      const query = inputQuery.value.trim()
      if (!query) {
        toast.error('Please enter a query')
        isGenerating.value = false
        return
      }
      // Pass title cleanly via the new backend payload property
      response = await workspaceApi.workspaceChat(workspaceId, query, undefined, finalTitle)
    } else {
      const sql = customSql.value.trim()
      if (!sql) {
        toast.error('Please enter SQL query')
        isGenerating.value = false
        return
      }
      response = await workspaceApi.executeCustomSql(workspaceId, { 
        title: finalTitle || 'Custom SQL Report', 
        sql_query: sql 
      })
    }
    
    
    if (response.status === 'error') {
      toast.error(response.message || 'Failed to generate report. SQL error.')
      currentReport.value = null
      return
    }
    
    currentReport.value = response
    if (response.data && response.data.length > 0) {
      toast.success('Report generated successfully')
    } else {
      toast.info('No data found for this query')
    }
    await fetchHistory() // refresh history
  } catch (err: any) {
    toast.error('Failed to generate report')
  } finally {
    isGenerating.value = false
  }
}

function downloadCSV() {
  if (!currentReport.value || !currentReport.value.data.length) return

  const cols = currentReport.value.columns
  const rows = currentReport.value.data

  const header = cols.join(',')
  const csvRows = rows.map(r => cols.map(c => `"${String(r[c] || '').replace(/"/g, '""')}"`).join(','))
  const csv = [header, ...csvRows].join('\n')

  const blob = new Blob([csv], { type: 'text/csv' })
  const url = window.URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.setAttribute('href', url)
  const safeTitle = reportTitle.value ? reportTitle.value.replace(/[^a-z0-9]/gi, '_').toLowerCase() : 'report'
  a.setAttribute('download', `${safeTitle}_${workspaceId.slice(0, 8)}.csv`)
  a.click()
  toast.success('CSV downloaded')
}

async function forwardToAIReport() {
  if (!currentReport.value) return
  
  isGeneratingAI.value = true
  aiReportContent.value = ''
  
  try {
    const payload = {
      question: reportTitle.value || inputQuery.value || 'Custom Query',
      sql_query: currentReport.value.sql,
      columns: currentReport.value.columns,
      data: currentReport.value.data
    }
    const response = await workspaceApi.summarizeReport(workspaceId, payload)
    if (response.status === 'success') {
      aiReportContent.value = response.summary
      toast.success('AI Report Generated')
      // Scroll to bottom to show AI report
      nextTick(() => {
        const aiReportEl = document.getElementById('ai-summary-section')
        if (aiReportEl) {
          aiReportEl.scrollIntoView({ behavior: 'smooth', block: 'end' })
        }
      })
      await fetchHistory()
    } else {
      toast.error('Failed to generate AI report')
    }
  } catch (err: any) {
    toast.error('Failed to generate AI report')
  } finally {
    isGeneratingAI.value = false
  }
}

async function deleteHistoricalReport(msgId: number) {
  try {
    await workspaceApi.deleteChatHistoryItem(workspaceId, msgId)
    toast.success('Report deleted')
    await fetchHistory()
  } catch(err) {
    toast.error('Failed to delete report')
  }
}

async function clearAllHistory() {
  if (!confirm('Are you sure you want to delete all report history?')) return
  try {
    await workspaceApi.clearChatHistory(workspaceId)
    toast.success('All history cleared')
    reportHistory.value = []
    if (currentReport.value) currentReport.value = null
  } catch(err) {
    toast.error('Failed to clear history')
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

// ── Share Report Snapshot ──
const showShareModal = ref(false)
const shareReportUrl = ref('')
const isSharingReport = ref(false)
const shareStep = ref<'options' | 'result'>('options')
const shareOptions = ref({ data: true, ai: true, sql: false })

function openShareModal() {
  shareStep.value = 'options'
  shareReportUrl.value = ''
  showShareModal.value = true
}

async function shareThisReport() {
  if (!currentReport.value) return
  isSharingReport.value = true
  try {
    const payload = {
      title: reportTitle.value || currentReport.value.question || 'Report',
      question: currentReport.value.question || '',
      sql_query: shareOptions.value.sql ? (currentReport.value.sql || '') : '',
      columns: shareOptions.value.data ? (currentReport.value.columns || []) : [],
      data: shareOptions.value.data ? (currentReport.value.data || []) : [],
      row_count: shareOptions.value.data ? (currentReport.value.row_count || 0) : 0,
      ai_summary: shareOptions.value.ai ? (aiReportContent.value || '') : '',
    }
    const r = await workspaceApi.shareReportSnapshot(workspaceId, payload)
    shareReportUrl.value = `${window.location.origin}${window.location.pathname}#/shared/report/${r.share_token}`
    shareStep.value = 'result'
    toast.success('Report shared successfully!')
  } catch {
    toast.error('Failed to share report')
  } finally {
    isSharingReport.value = false
  }
}

function copyShareLink() {
  navigator.clipboard.writeText(shareReportUrl.value)
  toast.success('Report link copied!')
}

onMounted(() => {
  fetchWorkspace()
  fetchHistory()
})
</script>

<template>
  <div class="flex flex-col h-[calc(100vh-3.5rem)] bg-slate-50/50 dark:bg-zinc-950">
    <!-- Header -->
    <header class="h-16 border-b border-slate-200/80 dark:border-zinc-800 flex items-center justify-between px-6 bg-white/80 dark:bg-zinc-900/80 backdrop-blur-xl shrink-0">
      <div class="flex items-center gap-4">
        <Button variant="ghost" size="icon" @click="router.push(`/app/workspaces/${workspaceId}`)">
           <iconify-icon icon="lucide:arrow-left" class="h-5 w-5 text-slate-500" />
        </Button>
        <div class="h-6 w-px bg-slate-200 dark:bg-zinc-800 hidden md:block"></div>
        <div class="flex items-center gap-2.5">
          <div class="h-9 w-9 rounded-xl bg-purple-100 dark:bg-purple-500/20 flex items-center justify-center text-purple-600 dark:text-purple-400 border border-purple-200/50 dark:border-purple-500/20 shadow-sm">
            <iconify-icon icon="lucide:file-text" class="text-lg" />
          </div>
          <div>
            <h1 class="text-sm font-bold tracking-tight text-slate-800 dark:text-white">{{ workspace?.name || 'Workspace' }} Reports</h1>
            <p class="text-[10px] text-slate-400 font-medium uppercase tracking-wider">Custom & AI Reporting</p>
          </div>
        </div>
      </div>
      <div class="flex items-center gap-2">
        <Button variant="outline" size="sm" @click="router.push(`/app/workspaces/${workspaceId}/dashboard`)">
           <iconify-icon icon="lucide:layout-dashboard" class="mr-2 h-4 w-4" />
           Dashboard
        </Button>
      </div>
    </header>

    <div class="flex-1 overflow-hidden flex">
      <!-- History Sidebar -->
      <div 
        class="border-r border-slate-200/80 dark:border-zinc-800 bg-white/50 dark:bg-zinc-900/50 flex-col overflow-hidden flex shrink-0 transition-all duration-300 ease-in-out"
        :class="isSidebarOpen ? 'w-72 p-4 opacity-100' : 'w-0 p-0 opacity-0 border-none'"
      >
        <div class="flex items-center justify-between mb-4 w-[16.5rem]">
          <div class="flex items-center gap-2">
            <h3 class="font-semibold text-sm text-slate-800 dark:text-slate-200 flex items-center gap-2">
              <iconify-icon icon="lucide:history" />
              Report History
            </h3>
            <span class="text-[10px] bg-slate-200 dark:bg-slate-800 px-2 py-0.5 rounded-full font-medium">{{ reportHistory.length }}</span>
          </div>
          <div class="flex items-center gap-1">
            <Button variant="ghost" size="icon" class="h-6 w-6 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800 rounded" @click="isSidebarOpen = false" title="Close Sidebar">
              <iconify-icon icon="lucide:panel-left-close" class="h-3.5 w-3.5" />
            </Button>
            <Button v-if="reportHistory.length > 0" variant="ghost" size="icon" class="h-6 w-6 text-red-500 hover:bg-red-50 dark:hover:bg-red-500/10 rounded" @click="clearAllHistory" title="Clear All History">
              <iconify-icon icon="lucide:trash-2" class="h-3.5 w-3.5" />
            </Button>
          </div>
        </div>
        
        <div class="flex-1 overflow-y-auto pr-2 space-y-2 w-[16.5rem]">
          <div 
            v-for="msg in reportHistory" 
            :key="msg.id" 
            class="p-3 rounded-xl border border-slate-200/60 dark:border-white/5 bg-white dark:bg-zinc-800/50 hover:border-indigo-300 dark:hover:border-indigo-500/50 hover:shadow-sm transition-all group relative"
          >
            <div class="text-[11px] text-slate-400 mb-1 flex items-center justify-between">
              {{ new Date(msg.created_at).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) }}
              <div class="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">

                <button @click.stop="loadHistoricalReport(msg)" class="text-indigo-500 hover:text-indigo-600 bg-indigo-50 dark:bg-indigo-500/10 p-1 rounded" title="Load Query into Editor">
                  <iconify-icon icon="lucide:arrow-right" />
                </button>
                <button @click.stop="deleteHistoricalReport(msg.id)" class="text-red-500 hover:text-red-600 bg-red-50 dark:bg-red-500/10 p-1 rounded" title="Delete Report">
                  <iconify-icon icon="lucide:trash" />
                </button>
              </div>
            </div>
            <!-- Try to extract title, or fallback to SQL -->
            <div class="text-xs font-medium text-slate-700 dark:text-slate-300 line-clamp-2 leading-snug cursor-pointer" @click="loadHistoricalReport(msg)">
              <span v-if="getTitleForHistory(msg) && getTitleForHistory(msg) !== 'Custom Query Executed'" class="font-semibold">{{ getTitleForHistory(msg) }}</span>
              <span v-else class="font-mono text-[10px] text-slate-500">{{ msg.chatResponse?.sql?.slice(0, 60) || 'Query Executed' }}...</span>
            </div>
            <div class="mt-2 flex items-center gap-2">
              <span class="text-[10px] text-emerald-600 bg-emerald-50 dark:bg-emerald-500/10 dark:text-emerald-400 px-1.5 py-0.5 rounded">
                {{ msg.chatResponse?.row_count || 0 }} rows
              </span>
            </div>
          </div>
          <div v-if="reportHistory.length === 0" class="text-center text-slate-400 text-xs py-8">
            No history found. Generate your first report!
          </div>
        </div>
      </div>

      <!-- Main Container Wrapper -->
      <div class="flex-1 overflow-hidden flex flex-col relative bg-slate-50 dark:bg-zinc-950/50 min-w-0 transition-all duration-300">
        
        <!-- Floating Sidebar Open Toggle (only visible when sidebar is closed) -->
        <button 
          v-if="!isSidebarOpen"
          @click="isSidebarOpen = true" 
          class="absolute top-4 left-0 z-10 h-8 w-8 rounded-r-xl border border-l-0 border-slate-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 shadow-sm flex items-center justify-center text-slate-500 hover:text-indigo-600 transition-all duration-300"
        >
          <iconify-icon icon="lucide:panel-left-open" class="h-4 w-4" />
        </button>

        <!-- Scrollable Area -->
        <div class="flex-1 overflow-y-auto w-full">
          <!-- Main Report Content -->
          <div class="flex flex-col p-6 mx-auto w-full max-w-7xl gap-6 relative">
          
          <!-- Query Configuration Area -->
        <div class="bg-white dark:bg-slate-900 rounded-2xl p-6 border border-slate-200/60 dark:border-white/10 shadow-sm shrink-0">
          
          <div class="flex items-center justify-between mb-4">
             <div class="flex items-center bg-slate-100 dark:bg-slate-800 p-1 rounded-lg">
                <button 
                  @click="queryMode = 'ai'" 
                  :class="['px-4 py-1.5 text-xs font-medium rounded-md transition-all', queryMode === 'ai' ? 'bg-white dark:bg-slate-700 shadow-sm text-slate-900 dark:text-white' : 'text-slate-500 hover:text-slate-700 dark:text-slate-400']"
                >
                  <div class="flex items-center gap-1.5">
                    <iconify-icon icon="lucide:sparkles" />
                    AI Query
                  </div>
                </button>
                <button 
                  @click="queryMode = 'custom_sql'" 
                  :class="['px-4 py-1.5 text-xs font-medium rounded-md transition-all', queryMode === 'custom_sql' ? 'bg-white dark:bg-slate-700 shadow-sm text-slate-900 dark:text-white' : 'text-slate-500 hover:text-slate-700 dark:text-slate-400']"
                >
                  <div class="flex items-center gap-1.5">
                    <iconify-icon icon="lucide:code" />
                    Custom SQL
                  </div>
                </button>
             </div>
             
             <Button variant="outline" size="sm" @click="resetReport" class="h-8 rounded-lg text-slate-600 dark:text-slate-300">
                <iconify-icon icon="lucide:plus" class="mr-1.5 h-3.5 w-3.5" />
                New Report
             </Button>
          </div>

          <div class="space-y-4">
            <div>
               <label class="text-xs font-medium text-slate-500 mb-1.5 block">Report Title (Optional)</label>
               <Input 
                 v-model="reportTitle" 
                 placeholder="e.g. Q3 Regional Sales Summary" 
                 class="h-10 bg-slate-50 dark:bg-slate-950 border-slate-200 dark:border-slate-800 rounded-xl"
               />
            </div>

            <div v-if="queryMode === 'ai'">
               <label class="text-xs font-medium text-slate-500 mb-1.5 block">What report do you need?</label>
               <Input 
                 v-model="inputQuery" 
                 placeholder="e.g. Get total sales grouped by region where revenue > 1000" 
                 class="h-12 bg-slate-50 dark:bg-slate-950 border-slate-200 dark:border-slate-800 rounded-xl"
                 @keyup.enter="generateReport"
               />
            </div>

            <div v-if="queryMode === 'custom_sql'">
               <label class="text-xs font-medium text-slate-500 mb-1.5 block">PostgreSQL Query</label>
               <textarea 
                 v-model="customSql" 
                 placeholder="SELECT * FROM table_name WHERE..." 
                 class="w-full h-24 p-3 text-sm font-mono bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-slate-800 rounded-xl resize-none focus:outline-none focus:ring-2 focus:ring-indigo-500/50"
                 @keydown.ctrl.enter="generateReport"
               ></textarea>
            </div>

            <div class="flex justify-end pt-2">
               <Button 
                 @click="generateReport" 
                 :disabled="isGenerating || (queryMode === 'ai' ? !inputQuery.trim() : !customSql.trim())" 
                 class="h-10 px-6 bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl shadow-md shadow-indigo-500/20"
               >
                 <iconify-icon v-if="!isGenerating" icon="lucide:play" class="mr-2" />
                 <iconify-icon v-else icon="lucide:loader-2" class="mr-2 animate-spin" />
                 {{ isGenerating ? 'Running...' : 'Run Report' }}
               </Button>
            </div>
          </div>
        </div>

        <!-- Result Section (Tabular) -->
        <div v-if="currentReport" class="flex flex-col min-h-[300px] max-h-[500px] bg-white dark:bg-slate-900 rounded-2xl border border-slate-200/60 dark:border-white/10 shadow-sm overflow-hidden">
          <div class="flex items-center justify-between p-4 border-b border-slate-100 dark:border-white/5 bg-slate-50/50 dark:bg-white/[0.02]">
            <div class="flex items-center gap-3">
              <div class="h-8 w-8 rounded-lg bg-emerald-100 dark:bg-emerald-500/20 flex items-center justify-center text-emerald-600 dark:text-emerald-400">
                <iconify-icon icon="lucide:table" />
              </div>
              <div>
                <h3 class="text-sm font-bold text-slate-800 dark:text-white">{{ reportTitle || 'Report Results' }}</h3>
                <p class="text-[10px] text-slate-500">{{ currentReport.row_count }} rows retrieved</p>
              </div>
            </div>
            
            <div class="flex gap-2">
              <Button variant="outline" size="sm" @click="openShareModal" class="h-9 rounded-lg">
                <iconify-icon icon="lucide:share-2" class="mr-2 h-4 w-4" />
                Share
              </Button>
              <Button variant="outline" size="sm" @click="downloadCSV" class="h-9 rounded-lg">
                <iconify-icon icon="lucide:download" class="mr-2 h-4 w-4" />
                Export CSV
              </Button>
              <Button size="sm" class="h-9 rounded-lg bg-purple-600 hover:bg-purple-700 text-white shadow-md shadow-purple-500/20" @click="forwardToAIReport" :disabled="isGeneratingAI">
                <iconify-icon v-if="!isGeneratingAI" icon="lucide:sparkles" class="mr-2 h-4 w-4" />
                <iconify-icon v-else icon="lucide:loader-2" class="mr-2 h-4 w-4 animate-spin" />
                Analyze with AI
              </Button>
            </div>
          </div>

          <!-- Tabular Data -->
          <div class="flex-1 overflow-auto p-4 bg-slate-50/30 dark:bg-zinc-950/30">
            <div class="border border-slate-200 dark:border-slate-800 rounded-xl overflow-hidden shadow-sm bg-white dark:bg-zinc-900">
              <Table>
                <TableHeader class="bg-slate-100/50 dark:bg-slate-900/50 sticky top-0 z-10 shadow-sm backdrop-blur-md">
                  <TableRow class="hover:bg-transparent">
                    <TableHead v-for="col in currentReport.columns" :key="col" class="font-semibold text-slate-700 dark:text-slate-300 whitespace-nowrap px-4 py-3 border-b border-slate-200 dark:border-slate-800">
                      {{ col }}
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  <TableRow v-for="(row, ridx) in currentReport.data" :key="ridx" class="hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors border-b border-slate-100 dark:border-slate-800/50 last:border-0">
                    <TableCell v-for="col in currentReport.columns" :key="col" class="px-4 py-3 text-sm text-slate-600 dark:text-slate-400 whitespace-nowrap">
                      {{ row[col] !== null ? row[col] : 'NULL' }}
                    </TableCell>
                  </TableRow>
                  <TableRow v-if="currentReport.data.length === 0">
                    <TableCell :colspan="currentReport.columns.length" class="h-32 text-center text-slate-500">
                      No data available for this query.
                    </TableCell>
                  </TableRow>
                </TableBody>
              </Table>
            </div>
          </div>
        </div>

        <div v-else-if="!isGenerating" class="flex-1 min-h-[300px] flex items-center justify-center text-slate-400 flex-col gap-4 bg-slate-200/20 dark:bg-white/[0.02] rounded-2xl border border-dashed border-slate-300 dark:border-slate-800">
          <iconify-icon icon="lucide:table-properties" class="text-6xl text-slate-200 dark:text-slate-800" />
          <p class="text-sm">Run an AI query or Custom SQL to view report results.</p>
        </div>

        <!-- AI Summary Section (Below Table) -->
        <div id="ai-summary-section" v-if="aiReportContent || isGeneratingAI" class="bg-white dark:bg-slate-900 rounded-2xl border border-purple-200/60 dark:border-purple-500/20 shadow-sm overflow-hidden flex flex-col ring-1 ring-purple-500/10 mb-8 shrink-0 mt-6">
          <div class="flex items-center p-4 border-b border-purple-100 dark:border-purple-500/10 bg-purple-50/50 dark:bg-purple-900/10">
            <div class="flex items-center gap-3">
              <div class="h-8 w-8 rounded-lg bg-purple-100 dark:bg-purple-500/20 flex items-center justify-center text-purple-600 dark:text-purple-400">
                <iconify-icon icon="lucide:bot" />
              </div>
              <div>
                <h3 class="text-sm font-bold text-slate-800 dark:text-white">AI Generated Insight</h3>
                <p class="text-[10px] text-slate-500">Automated analysis of the retrieved data</p>
              </div>
            </div>
          </div>

          <div class="p-8">
            <div v-if="isGeneratingAI" class="flex flex-col items-center justify-center py-12 text-purple-500 gap-4">
              <iconify-icon icon="lucide:loader-2" class="text-4xl animate-spin" />
              <p class="text-sm font-medium animate-pulse">Analyzing mathematical profile and generating insights...</p>
            </div>
            
            <div v-else-if="aiReportContent" class="prose prose-sm dark:prose-invert max-w-none prose-p:leading-relaxed prose-headings:text-slate-800 dark:prose-headings:text-slate-200 prose-a:text-indigo-600 prose-ul:my-2 prose-li:my-0.5" v-html="parsedAiReport">
            </div>
          </div>
        </div>
        </div>
      </div>
    </div>
  </div>
</div>

    <!-- Share Report Modal -->
    <Teleport to="body">
    <div v-if="showShareModal" class="fixed inset-0 z-[200] flex items-center justify-center bg-slate-900/60 backdrop-blur-sm" @click.self="showShareModal=false">
      <div class="w-full max-w-lg rounded-2xl bg-white dark:bg-zinc-900 border border-slate-200 dark:border-zinc-800 shadow-2xl overflow-hidden">
        
        <template v-if="shareStep === 'options'">
          <!-- Options Header -->
          <div class="flex items-center justify-between px-6 py-4 border-b border-slate-100 dark:border-zinc-800">
            <h2 class="text-base font-bold text-slate-800 dark:text-white">Share Report Options</h2>
            <button @click="showShareModal=false" class="p-2 hover:bg-slate-100 dark:hover:bg-zinc-800 rounded-lg transition"><iconify-icon icon="lucide:x" class="text-sm text-slate-500"/></button>
          </div>
          
          <div class="p-6 space-y-4">
            <p class="text-sm text-slate-600 dark:text-slate-400">Choose what information should be included in the shared report link:</p>
            
            <div class="space-y-3">
              <label class="flex items-center gap-3 p-3 rounded-xl border border-slate-200 dark:border-zinc-700 hover:bg-slate-50 dark:hover:bg-zinc-800/50 cursor-pointer transition">
                <input type="checkbox" v-model="shareOptions.data" class="h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-600" />
                <div class="flex flex-col">
                  <span class="text-sm font-semibold text-slate-800 dark:text-slate-200">Full Data Table</span>
                  <span class="text-xs text-slate-500">Include the full extracted rows ({{ currentReport?.row_count || 0 }} rows)</span>
                </div>
              </label>
              
              <label v-if="aiReportContent" class="flex items-center gap-3 p-3 rounded-xl border border-slate-200 dark:border-zinc-700 hover:bg-slate-50 dark:hover:bg-zinc-800/50 cursor-pointer transition">
                <input type="checkbox" v-model="shareOptions.ai" class="h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-600" />
                <div class="flex flex-col">
                  <span class="text-sm font-semibold text-slate-800 dark:text-slate-200">AI Summary</span>
                  <span class="text-xs text-slate-500">Include the generated AI analysis and insights</span>
                </div>
              </label>
              
              <label class="flex items-center gap-3 p-3 rounded-xl border border-slate-200 dark:border-zinc-700 hover:bg-slate-50 dark:hover:bg-zinc-800/50 cursor-pointer transition">
                <input type="checkbox" v-model="shareOptions.sql" class="h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-600" />
                <div class="flex flex-col">
                  <span class="text-sm font-semibold text-slate-800 dark:text-slate-200">SQL Query</span>
                  <span class="text-xs text-slate-500">Show the raw SQL query used to fetch this data</span>
                </div>
              </label>
            </div>
            
            <div class="flex justify-end gap-2 pt-2">
              <Button variant="ghost" @click="showShareModal=false">Cancel</Button>
              <Button @click="shareThisReport" :disabled="isSharingReport" class="bg-indigo-600 hover:bg-indigo-700 text-white">
                <iconify-icon v-if="isSharingReport" icon="lucide:loader-2" class="mr-2 animate-spin" />
                Generate Link
              </Button>
            </div>
          </div>
        </template>
        
        <template v-else>
          <!-- Result Header -->
          <div class="flex items-center justify-between px-6 py-4 bg-gradient-to-r from-emerald-500/10 to-teal-500/10 dark:from-emerald-900/20 dark:to-teal-900/10 border-b border-slate-200 dark:border-zinc-800">
            <div class="flex items-center gap-3">
              <div class="h-10 w-10 flex items-center justify-center rounded-xl bg-emerald-100 dark:bg-emerald-900/40 text-emerald-600 dark:text-emerald-400">
                <iconify-icon icon="lucide:check-circle" class="text-lg"/>
              </div>
              <div>
                <h2 class="text-base font-bold text-slate-800 dark:text-white">Report Shared!</h2>
                <p class="text-[11px] text-slate-500">Anyone with this link can view the report</p>
              </div>
            </div>
            <button @click="showShareModal=false" class="p-2 hover:bg-slate-100 dark:hover:bg-zinc-800 rounded-lg transition"><iconify-icon icon="lucide:x" class="text-sm text-slate-500"/></button>
          </div>

          <div class="p-6 space-y-5">
            <!-- What's included -->
            <div class="flex items-start gap-3 p-4 rounded-xl bg-slate-50 dark:bg-zinc-800/50 border border-slate-200 dark:border-zinc-700">
              <iconify-icon icon="lucide:info" class="text-blue-500 mt-0.5 shrink-0"/>
              <div class="text-xs text-slate-600 dark:text-slate-300">
                <p class="font-semibold mb-1">This shared link includes:</p>
                <ul class="space-y-0.5 text-slate-500 dark:text-slate-400">
                  <li>✓ Report title & query text</li>
                  <li v-if="shareOptions.data">✓ Full data table ({{ currentReport?.row_count || 0 }} rows)</li>
                  <li v-if="aiReportContent && shareOptions.ai">✓ AI Analysis summary</li>
                  <li v-if="shareOptions.sql">✓ SQL query used</li>
                </ul>
              </div>
            </div>

            <!-- Report Link -->
            <div class="space-y-2">
              <label class="text-[10px] font-bold text-slate-500 uppercase tracking-wider flex items-center gap-1.5">
                <iconify-icon icon="lucide:link" class="text-xs"/>Share Link
              </label>
              <div class="flex gap-2">
                <input :value="shareReportUrl" readonly class="flex-1 text-xs font-mono rounded-lg border border-slate-200 dark:border-zinc-700 bg-slate-50 dark:bg-zinc-800 px-3 py-2.5 select-all text-slate-600 dark:text-slate-300"/>
                <button @click="copyShareLink" class="px-4 py-2.5 text-xs font-semibold rounded-lg bg-purple-600 text-white hover:bg-purple-700 transition flex items-center gap-1.5 shrink-0">
                  <iconify-icon icon="lucide:copy"/>Copy
                </button>
              </div>
            </div>
          </div>
        </template>
      </div>
    </div>
    </Teleport>
</template>

<style scoped>
/* Custom thin scrollbar for a modern look */
.overflow-y-auto::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}
.overflow-y-auto::-webkit-scrollbar-track {
  background: transparent;
}
.overflow-y-auto::-webkit-scrollbar-thumb {
  background-color: #cbd5e1;
  border-radius: 10px;
}
.dark .overflow-y-auto::-webkit-scrollbar-thumb {
  background-color: #334155;
}
.overflow-y-auto::-webkit-scrollbar-thumb:hover {
  background-color: #94a3b8;
}
.dark .overflow-y-auto::-webkit-scrollbar-thumb:hover {
  background-color: #475569;
}
</style>
