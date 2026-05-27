<script setup lang="ts">
import { ref, onMounted, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { marked } from 'marked'
import workspaceApi, { type ChatResponse, type WorkspaceDetailResponse } from '@/services/workspaceApi'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ScrollArea } from '@/components/ui/scroll-area'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogDescription,
} from '@/components/ui/dialog'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { toast } from 'vue-sonner'

const route = useRoute()
const router = useRouter()
const workspaceId = route.params.workspaceId as string

const workspace = ref<WorkspaceDetailResponse | null>(null)
const messages = ref<any[]>([])
const inputMessage = ref('')
const isSending = ref(false)
const scrollArea = ref<any>(null)

// Pin to Dashboard Modal state
const isPinModalOpen = ref(false)
const pinningData = ref<ChatResponse | null>(null)
const pinConfig = ref({
  title: '',
  widget_type: 'table',
  chart_type: 'bar'
})

async function fetchWorkspace() {
  try {
    workspace.value = await workspaceApi.getWorkspaceDetail(workspaceId)
  } catch (err) {
    toast.error('Failed to load workspace')
  }
}

function scrollToBottom() {
  nextTick(() => {
    if (scrollArea.value?.$el?.querySelector('[data-radix-scroll-area-viewport]')) {
      const viewport = scrollArea.value.$el.querySelector('[data-radix-scroll-area-viewport]')
      viewport.scrollTop = viewport.scrollHeight
    }
  })
}

function renderMarkdown(text: string) {
  if (!text) return ''
  return marked(text)
}

function copyToClipboard(text: string) {
  navigator.clipboard.writeText(text)
  toast.success('Copied to clipboard')
}

function adjustTextareaHeight(e: Event) {
  const el = e.target as HTMLTextAreaElement
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 128) + 'px'
}

async function sendMessage() {
  const text = inputMessage.value.trim()
  if (!text || isSending.value) return

  messages.value.push({ role: 'user', content: text, created_at: new Date() })
  inputMessage.value = ''
  isSending.value = true
  scrollToBottom()

  try {
    const response = await workspaceApi.workspaceChat(workspaceId, text)
    const botMsg: any = {
      role: 'assistant',
      content: response.explanation || 'Here are the results for your query:',
      chatResponse: response,
      created_at: new Date()
    }
    messages.value.push(botMsg)
    scrollToBottom()
    
  } catch (err: any) {
    toast.error('Chat failed')
    messages.value.push({ role: 'assistant', content: '❌ Sorry, I encountered an error processing your request.', created_at: new Date() })
  } finally {
    isSending.value = false
    scrollToBottom()
  }
}

function openPinModal(data: ChatResponse) {
  pinningData.value = data
  pinConfig.value.title = data.question || 'Chat Query Result'
  
  // Auto-detect widget type from data shape
  const rowCount = data.data?.length || 0
  const colCount = data.columns?.length || 0
  if (rowCount === 1 && colCount <= 4) {
    pinConfig.value.widget_type = 'kpi'
  } else if (rowCount <= 5) {
    pinConfig.value.widget_type = 'list'
  } else {
    pinConfig.value.widget_type = 'table'
  }
  isPinModalOpen.value = true
}

async function handlePinToDashboard() {
  if (!pinningData.value) return
  
  try {
    await workspaceApi.pinWidget(workspaceId, {
      title: pinConfig.value.title,
      widget_type: pinConfig.value.widget_type,
      chart_type: pinConfig.value.widget_type === 'chart' ? pinConfig.value.chart_type : undefined,
      sql_query: pinningData.value.sql,
      origin_question: pinningData.value.question,
      config: {
        source_table: '_chat',
        columns: pinningData.value.columns,
        chartData: pinningData.value.data,
        row_count: pinningData.value.row_count || pinningData.value.data?.length || 0,
      }
    })
    toast.success('Widget pinned to workspace dashboard!')
    isPinModalOpen.value = false
  } catch (err) {
    toast.error('Failed to pin widget')
  }
}

async function loadChatHistory() {
  try {
    const history = await workspaceApi.getChatHistory(workspaceId)
    if (history.messages && history.messages.length > 0) {
      messages.value = history.messages
    } else {
      messages.value.push({
        role: 'assistant',
        content: "👋 Ready to analyze your data! Ask me anything like:\n- 'How many tables are in this schema?'\n- 'Show me top 10 rows from [table]'\n- 'What is the sum of [column] grouped by [column]?'",
        created_at: new Date()
      })
    }
  } catch (err) {
    messages.value.push({
      role: 'assistant',
      content: "👋 Ready to analyze your data! Ask me anything like:\n- 'How many tables are in this schema?'\n- 'Show me top 10 rows from [table]'\n- 'What is the sum of [column] grouped by [column]?'",
      created_at: new Date()
    })
  }
  scrollToBottom()
}

async function clearChatHistory() {
  if (!confirm('Are you sure you want to clear this workspace chat history?')) return

  try {
    await workspaceApi.clearChatHistory(workspaceId)
    toast.success('Workspace chat history cleared')
    messages.value = []
    await loadChatHistory()
  } catch (err) {
    toast.error('Failed to clear workspace chat history')
  }
}

onMounted(() => {
  fetchWorkspace()
  loadChatHistory()
})
</script>

<template>
  <div class="flex flex-col h-[calc(100vh-3.5rem)] bg-slate-50/50 dark:bg-zinc-950 relative">
    <!-- Header -->
    <header class="h-16 border-b border-slate-200/80 dark:border-zinc-800 flex items-center justify-between px-6 bg-white/80 dark:bg-zinc-900/80 backdrop-blur-xl shrink-0 z-10">
      <div class="flex items-center gap-4">
        <Button variant="ghost" size="icon" @click="router.push(`/app/workspaces/${workspaceId}`)">
           <iconify-icon icon="lucide:arrow-left" class="h-5 w-5 text-slate-500" />
        </Button>
        <div class="h-9 w-9 rounded-xl bg-indigo-100 dark:bg-indigo-500/20 flex items-center justify-center text-indigo-600 dark:text-indigo-400 border border-indigo-200/50 dark:border-indigo-500/20 shadow-sm">
           <iconify-icon icon="lucide:bot" class="text-lg" />
        </div>
        <div>
          <h1 class="text-sm font-bold tracking-tight text-slate-800 dark:text-white">{{ workspace?.name || 'Workspace' }} AI Assistant</h1>
          <p class="text-[10px] text-slate-400 font-medium tracking-wider uppercase">Interactive SQL Chat</p>
        </div>
      </div>
      <div class="flex items-center gap-2">
        <Button variant="outline" size="sm" @click="clearChatHistory" class="text-rose-500 hover:text-rose-600 hover:bg-rose-50 dark:hover:bg-rose-950/30 border-transparent">
          <iconify-icon icon="lucide:trash-2" class="mr-2 h-4 w-4" />
          Clear Chat
        </Button>
        <Button variant="outline" size="sm" @click="router.push(`/app/workspaces/${workspaceId}/dashboard`)">
           <iconify-icon icon="lucide:layout-dashboard" class="mr-2 h-4 w-4" />
           Dashboard
        </Button>
      </div>
    </header>

    <!-- Chat Area -->
    <ScrollArea ref="scrollArea" class="flex-1 w-full relative bg-slate-50/50 dark:bg-zinc-950/50">
      <div class="max-w-6xl mx-auto space-y-8 p-4 md:p-8 pb-8">
        <div
          v-for="(msg, idx) in messages"
          :key="idx"
          :class="['flex flex-col gap-1 max-w-[95%] md:max-w-[90%]', msg.role === 'user' ? 'ml-auto items-end' : 'mr-auto items-start']"
        >
          <!-- User Bubble -->
          <div v-if="msg.role === 'user'" class="bg-indigo-600 text-white rounded-2xl rounded-tr-sm px-5 py-3.5 shadow-sm text-[15px] leading-relaxed">
             {{ msg.content }}
          </div>

          <!-- Assistant Bubble -->
          <div v-else class="flex gap-4 w-full">
            <div class="w-8 h-8 rounded-full bg-indigo-100 dark:bg-indigo-900/50 flex items-center justify-center shrink-0 border border-indigo-200 dark:border-indigo-800 mt-1">
               <iconify-icon icon="lucide:bot" class="text-indigo-600 dark:text-indigo-400 text-sm" />
            </div>

            <div class="flex-1 flex flex-col gap-3 min-w-0">
               <!-- Content or Typing -->
               <div class="bg-white dark:bg-zinc-900 border border-slate-200 dark:border-zinc-800 rounded-2xl rounded-tl-sm px-5 py-4 shadow-sm">
                  <div v-if="msg.isTyping" class="flex items-center gap-3 text-indigo-500">
                     <iconify-icon icon="lucide:loader-2" class="animate-spin text-lg" />
                     <span class="text-sm font-medium animate-pulse">{{ msg.loadingStage || 'Thinking...' }}</span>
                  </div>
                  <div v-else-if="msg.content" class="prose prose-sm dark:prose-invert max-w-none prose-p:leading-relaxed prose-headings:text-slate-800 dark:prose-headings:text-slate-200 prose-a:text-indigo-600" v-html="renderMarkdown(msg.content)"></div>
               </div>

               <!-- Data Visualizations -->
               <div v-if="msg.chatResponse && msg.chatResponse.data && msg.chatResponse.data.length > 0 && !msg.isTyping" class="flex flex-col gap-2">
                  <!-- 1 Row = KPI Cards -->
                  <div v-if="msg.chatResponse.data.length === 1" class="grid grid-cols-2 md:grid-cols-4 gap-2">
                     <div v-for="col in msg.chatResponse.columns?.slice(0, 4)" :key="col" class="bg-white dark:bg-zinc-900 p-3 rounded-xl border border-slate-200 dark:border-zinc-800 shadow-sm flex flex-col justify-between">
                        <span class="text-[10px] text-slate-400 uppercase tracking-wider font-semibold mb-1 truncate" :title="col">{{ col }}</span>
                        <span class="text-sm font-bold text-slate-800 dark:text-slate-200 truncate" :title="String(msg.chatResponse.data[0][col])">{{ msg.chatResponse.data[0][col] !== null ? msg.chatResponse.data[0][col] : 'NULL' }}</span>
                     </div>
                  </div>
                  
                  <!-- Multiple Rows = Proper Table -->
                  <div v-else class="bg-white dark:bg-zinc-900 rounded-xl border border-slate-200 dark:border-zinc-800 shadow-sm overflow-hidden">
                     <div class="flex items-center justify-between px-3 py-2 border-b border-slate-100 dark:border-zinc-800 bg-slate-50/80 dark:bg-zinc-800/50">
                        <span class="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">Results</span>
                        <span class="text-[10px] text-slate-400">{{ msg.chatResponse.row_count || msg.chatResponse.data.length }} rows</span>
                     </div>
                     <div class="overflow-x-auto max-h-[280px] overflow-y-auto">
                        <table class="w-full text-xs">
                           <thead class="sticky top-0 z-10 backdrop-blur-sm bg-slate-50 dark:bg-zinc-900/90">
                              <tr>
                                 <th v-for="col in msg.chatResponse.columns" :key="col" class="text-left px-3 py-2 font-semibold uppercase text-[10px] tracking-wider whitespace-nowrap text-indigo-600/70 dark:text-indigo-300/80 border-b border-slate-200 dark:border-zinc-800">{{ col }}</th>
                              </tr>
                           </thead>
                           <tbody>
                              <tr v-for="(row, ri) in msg.chatResponse.data.slice(0, 15)" :key="ri" class="border-b border-slate-100 dark:border-zinc-800/50 hover:bg-slate-50 dark:hover:bg-zinc-800/30 transition">
                                 <td v-for="col in msg.chatResponse.columns" :key="col" class="px-3 py-1.5 whitespace-nowrap text-slate-600 dark:text-slate-400">{{ row[col] ?? '—' }}</td>
                              </tr>
                           </tbody>
                        </table>
                     </div>
                     <div v-if="msg.chatResponse.data.length > 15" class="px-3 py-1.5 text-[10px] text-center border-t border-slate-100 dark:border-zinc-800 text-slate-400">
                        Showing 15 of {{ msg.chatResponse.data.length }} rows
                     </div>
                  </div>
               </div>
               
               <!-- Action Footer (Pin & Copy) -->
               <div v-if="!msg.isTyping" class="flex items-center gap-2 mt-1">
                  <button v-if="msg.content" @click="copyToClipboard(msg.content)" class="text-slate-400 hover:text-indigo-600 transition-colors p-1.5 rounded-md hover:bg-indigo-50 dark:hover:bg-indigo-900/30" title="Copy response text">
                     <iconify-icon icon="lucide:copy" class="text-sm" />
                  </button>
                  <button v-if="msg.chatResponse && msg.chatResponse.data && msg.chatResponse.data.length > 0" @click="openPinModal(msg.chatResponse)" class="flex items-center gap-1.5 text-xs font-medium text-slate-500 hover:text-emerald-600 transition-colors px-2 py-1.5 rounded-md hover:bg-emerald-50 dark:hover:bg-emerald-900/30 border border-slate-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 shadow-sm">
                     <iconify-icon icon="lucide:pin" />
                     Pin to Board
                  </button>
                  <span class="text-[10px] text-slate-300 dark:text-slate-600 ml-auto">
                     {{ msg.created_at ? new Date(msg.created_at).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'}) : new Date().toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'}) }}
                  </span>
               </div>
            </div>
          </div>
        </div>

        <!-- Sending state (when query is being executed) -->
        <div v-if="isSending && messages[messages.length - 1]?.role !== 'assistant'" class="flex gap-4 max-w-[95%] md:max-w-[90%] mr-auto items-start">
            <div class="w-8 h-8 rounded-full bg-indigo-100 dark:bg-indigo-900/50 flex items-center justify-center shrink-0 border border-indigo-200 dark:border-indigo-800 mt-1">
               <iconify-icon icon="lucide:bot" class="text-indigo-600 dark:text-indigo-400 text-sm" />
            </div>
            <div class="bg-white dark:bg-zinc-900 border border-slate-200 dark:border-zinc-800 rounded-2xl rounded-tl-sm px-5 py-4 shadow-sm flex items-center gap-3 text-indigo-500">
               <iconify-icon icon="lucide:loader-2" class="animate-spin text-lg" />
               <span class="text-sm font-medium animate-pulse">Querying database...</span>
            </div>
        </div>
      </div>
    </ScrollArea>

    <!-- Footer Input Layer -->
    <div class="p-4 bg-slate-50 dark:bg-zinc-950 border-t border-slate-200/80 dark:border-zinc-800 shrink-0">
       <div class="relative max-w-6xl mx-auto flex items-end gap-2 bg-white dark:bg-zinc-900 rounded-3xl p-1.5 border border-slate-200 dark:border-zinc-800 focus-within:border-indigo-500 focus-within:ring-1 focus-within:ring-indigo-500 transition-all shadow-sm">
          <textarea 
             v-model="inputMessage" 
             @keydown.enter.exact.prevent="sendMessage" 
             @input="adjustTextareaHeight"
             placeholder="Ask anything about your workspace data... (Press Enter to send)" 
             class="flex-1 max-h-32 min-h-[44px] bg-transparent border-0 focus:ring-0 resize-none py-3 px-4 text-[15px] text-slate-700 dark:text-slate-200 placeholder:text-slate-400" 
             rows="1"
             :disabled="isSending"
          ></textarea>
          <div class="pb-1.5 pr-1.5">
             <Button 
                @click="sendMessage" 
                :disabled="isSending || !inputMessage.trim()" 
                class="rounded-full w-10 h-10 p-0 bg-indigo-600 hover:bg-indigo-700 text-white shrink-0 shadow-md shadow-indigo-500/20 transition-all disabled:opacity-50 disabled:shadow-none"
             >
                <iconify-icon v-if="!isSending" icon="lucide:send" class="text-sm" />
                <iconify-icon v-else icon="lucide:loader-2" class="animate-spin text-sm" />
             </Button>
          </div>
       </div>
       <div class="text-center mt-3 text-[10px] font-medium text-slate-400">
         AI can make mistakes. Please verify important information.
       </div>
    </div>

    <!-- Pin Modal -->
    <Dialog v-model:open="isPinModalOpen">
       <DialogContent class="sm:max-w-md rounded-3xl border-slate-200 dark:border-zinc-800 bg-white dark:bg-zinc-950">
          <DialogHeader>
             <DialogTitle class="text-slate-800 dark:text-slate-100">Pin to Board</DialogTitle>
             <DialogDescription class="text-slate-500">
                Convert this insight into a permanent dashboard widget.
             </DialogDescription>
          </DialogHeader>
          <div class="space-y-4 py-4">
             <div class="space-y-2">
                <label class="text-xs font-bold uppercase text-slate-500">Widget Title</label>
                <Input v-model="pinConfig.title" placeholder="Give your widget a name" class="bg-slate-50 dark:bg-zinc-900 border-slate-200 dark:border-zinc-800" />
             </div>
             <div class="grid grid-cols-2 gap-4">
                <div class="space-y-2">
                   <label class="text-xs font-bold uppercase text-slate-500">Display Type</label>
                   <Select v-model="pinConfig.widget_type">
                      <SelectTrigger class="bg-slate-50 dark:bg-zinc-900 border-slate-200 dark:border-zinc-800">
                         <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                         <SelectItem value="table">Data Table</SelectItem>
                         <SelectItem value="chart">Chart</SelectItem>
                      </SelectContent>
                   </Select>
                </div>
                <div v-if="pinConfig.widget_type === 'chart'" class="space-y-2">
                   <label class="text-xs font-bold uppercase text-slate-500">Chart Type</label>
                   <Select v-model="pinConfig.chart_type">
                      <SelectTrigger class="bg-slate-50 dark:bg-zinc-900 border-slate-200 dark:border-zinc-800">
                         <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                         <SelectItem value="bar">Bar Chart</SelectItem>
                         <SelectItem value="line">Line Chart</SelectItem>
                         <SelectItem value="pie">Pie Chart</SelectItem>
                      </SelectContent>
                   </Select>
                </div>
             </div>
          </div>
          <DialogFooter>
             <Button variant="ghost" @click="isPinModalOpen = false" class="hover:bg-slate-100 dark:hover:bg-zinc-900">Cancel</Button>
             <Button class="bg-emerald-600 hover:bg-emerald-700 text-white shadow-md shadow-emerald-500/20" @click="handlePinToDashboard">
                <iconify-icon icon="lucide:pin" class="mr-2 h-4 w-4" />
                Finish Pinning
             </Button>
          </DialogFooter>
       </DialogContent>
    </Dialog>
  </div>
</template>

<style scoped>
/* Scoped styles to ensure clean markdown rendering */
:deep(.prose) {
  max-width: none;
}
:deep(.prose p:last-child) {
  margin-bottom: 0;
}
:deep(.prose p:first-child) {
  margin-top: 0;
}
:deep(.prose pre) {
  background-color: #0f172a;
  border-radius: 0.5rem;
  padding: 1rem;
  overflow-x: auto;
}

/* Hidden scrollbar but keeps functionality */
::-webkit-scrollbar {
  width: 6px;
}
::-webkit-scrollbar-thumb {
  background: rgba(0,0,0,0.1);
  border-radius: 10px;
}
</style>
