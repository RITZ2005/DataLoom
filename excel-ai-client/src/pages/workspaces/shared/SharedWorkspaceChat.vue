<script setup lang="ts">
/**
 * SharedWorkspaceChat.vue
 * Public chatbot interface for shared workspaces — no auth required.
 * Supports light & dark mode toggle.
 */
import { ref, computed, onMounted, nextTick, watch } from 'vue'
import { useRoute } from 'vue-router'
import workspaceApi from '@/services/workspaceApi'

const route = useRoute()
const token = computed(() => route.params.token as string)

interface ChatMessage {
  id: number
  role: 'user' | 'assistant'
  content: string
  chatResponse?: {
    sql?: string
    columns?: string[]
    data?: any[]
    row_count?: number
  }
  timestamp: string
}

const messages = ref<ChatMessage[]>([])
const inputText = ref('')
const isLoading = ref(false)
const chatContainer = ref<HTMLElement | null>(null)
let msgCounter = 0

// ── THEME TOGGLE ──
const isDark = ref(false)

function initTheme() {
  const saved = localStorage.getItem('shared-theme')
  if (saved) {
    isDark.value = saved === 'dark'
  } else {
    isDark.value = window.matchMedia('(prefers-color-scheme: dark)').matches
  }
  applyTheme()
}

function toggleTheme() {
  isDark.value = !isDark.value
  localStorage.setItem('shared-theme', isDark.value ? 'dark' : 'light')
  applyTheme()
}

function applyTheme() {
  document.documentElement.classList.toggle('dark', isDark.value)
}

// Auto-scroll to bottom
function scrollToBottom() {
  nextTick(() => {
    if (chatContainer.value) {
      chatContainer.value.scrollTop = chatContainer.value.scrollHeight
    }
  })
}

watch(messages, scrollToBottom, { deep: true })

async function sendMessage() {
  const question = inputText.value.trim()
  if (!question || isLoading.value) return
  inputText.value = ''

  messages.value.push({
    id: ++msgCounter,
    role: 'user',
    content: question,
    timestamp: new Date().toLocaleTimeString()
  })
  scrollToBottom()

  isLoading.value = true

  try {
    const result = await workspaceApi.sharedWorkspaceChat(token.value, question)
    messages.value.push({
      id: ++msgCounter,
      role: 'assistant',
      content: result.explanation || result.message || 'Here are your results:',
      chatResponse: {
        sql: result.sql,
        columns: result.columns,
        data: result.data,
        row_count: result.row_count
      },
      timestamp: new Date().toLocaleTimeString()
    })
  } catch (e: any) {
    const detail = e?.response?.data?.detail || 'Something went wrong. Please try again.'
    messages.value.push({
      id: ++msgCounter,
      role: 'assistant',
      content: detail,
      timestamp: new Date().toLocaleTimeString()
    })
  } finally {
    isLoading.value = false
    scrollToBottom()
  }
}

function handleClose() {
  window.parent.postMessage({ type: 'closeChatbot' }, '*')
}

function downloadCSV(columns: string[], data: any[]) {
  if (!columns?.length || !data?.length) return
  const header = columns.join(',')
  const csvRows = data.map(r => columns.map(c => `"${String(r[c] ?? '').replace(/"/g, '""')}"`).join(','))
  const csv = [header, ...csvRows].join('\n')
  const blob = new Blob([csv], { type: 'text/csv' })
  const url = window.URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `data_export_${Date.now()}.csv`
  a.click()
}

const SUGGESTIONS = [
  'Show me a summary of all data',
  'What are the top 10 records?',
  'How many rows are there?',
  'Show distribution by category',
]

onMounted(() => {
  initTheme()
  messages.value.push({
    id: ++msgCounter,
    role: 'assistant',
    content: 'Hello! 👋 I\'m your data assistant. Ask me anything about this workspace — I\'ll query the data and give you insights.',
    timestamp: new Date().toLocaleTimeString()
  })
})
</script>

<template>
  <div :class="['h-screen flex flex-col overflow-hidden transition-colors duration-300', isDark ? 'bg-gradient-to-b from-slate-950 via-slate-900 to-indigo-950/80 text-white' : 'bg-gradient-to-b from-slate-50 via-white to-indigo-50/20 text-slate-900']">

    <!-- Header -->
    <header :class="['shrink-0 flex items-center justify-between px-5 py-3 backdrop-blur-xl border-b transition-colors duration-300', isDark ? 'bg-white/[0.03] border-white/[0.06]' : 'bg-white/80 border-slate-200/60']">
      <div class="flex items-center gap-3">
        <div class="h-9 w-9 flex items-center justify-center rounded-xl bg-gradient-to-br from-indigo-500 to-violet-600 text-white text-sm font-bold shadow-lg shadow-indigo-500/30">
          <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
        </div>
        <div>
          <h1 :class="['text-sm font-semibold', isDark ? 'text-white/90' : 'text-slate-800']">Data Assistant</h1>
          <p :class="['text-[10px]', isDark ? 'text-white/40' : 'text-slate-400']">Ask questions about your workspace data</p>
        </div>
      </div>
      <div class="flex items-center gap-2">
        <!-- Theme Toggle -->
        <button @click="toggleTheme" :class="['group relative h-8 w-16 rounded-full border-2 transition-all duration-300 flex items-center', isDark ? 'bg-zinc-800 border-zinc-600' : 'bg-amber-50 border-amber-200']" title="Toggle theme">
          <span :class="['absolute h-6 w-6 rounded-full flex items-center justify-center text-xs transition-all duration-300 shadow-md', isDark ? 'translate-x-[30px] bg-indigo-500 text-white' : 'translate-x-[2px] bg-amber-400 text-amber-900']">
            <svg v-if="isDark" xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>
            <svg v-else xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>
          </span>
        </button>
        <!-- Status -->
        <span :class="['inline-flex items-center gap-1.5 px-3 py-1 text-[10px] font-medium rounded-full border', isDark ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' : 'bg-emerald-50 text-emerald-600 border-emerald-200']">
          <span class="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse"/>Online
        </span>
        <button @click="handleClose" :class="['p-2 rounded-lg transition', isDark ? 'hover:bg-white/[0.06] text-white/40 hover:text-white/80' : 'hover:bg-slate-100 text-slate-400 hover:text-slate-600']" title="Close">
          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>
        </button>
      </div>
    </header>

    <!-- Messages -->
    <div ref="chatContainer" class="flex-1 overflow-y-auto px-4 py-6 space-y-6 scroll-smooth" style="scrollbar-width:thin">

      <div v-for="msg in messages" :key="msg.id" :class="['flex gap-3', msg.role === 'user' ? 'justify-end' : 'justify-start']">
        <!-- Assistant Avatar -->
        <div v-if="msg.role === 'assistant'" class="shrink-0 h-8 w-8 rounded-full bg-gradient-to-br from-indigo-500 to-violet-600 flex items-center justify-center text-xs font-bold text-white shadow-lg shadow-indigo-500/20 mt-1">AI</div>

        <div :class="[
          'max-w-[85%] rounded-2xl px-4 py-3 text-sm leading-relaxed transition-colors duration-300',
          msg.role === 'user'
            ? 'bg-indigo-600 text-white rounded-br-md shadow-lg shadow-indigo-500/20'
            : isDark
              ? 'bg-white/[0.06] text-white/85 rounded-bl-md border border-white/[0.06]'
              : 'bg-slate-100 text-slate-700 rounded-bl-md border border-slate-200/60'
        ]">
          <p class="whitespace-pre-wrap">{{ msg.content }}</p>

          <!-- Data Results -->
          <div v-if="msg.chatResponse?.columns?.length && msg.chatResponse?.data?.length" class="mt-3">
            <div :class="['rounded-xl overflow-hidden border', isDark ? 'bg-black/20 border-white/[0.06]' : 'bg-white border-slate-200']">
              <div :class="['px-3 py-2 border-b flex items-center justify-between', isDark ? 'bg-white/[0.03] border-white/[0.06]' : 'bg-slate-50 border-slate-200']">
                <span :class="['text-[10px] font-semibold uppercase tracking-wider', isDark ? 'text-white/50' : 'text-slate-500']">Results</span>
                <div class="flex items-center gap-2">
                  <button @click="downloadCSV(msg.chatResponse.columns, msg.chatResponse.data)" :class="['flex items-center gap-1 px-2 py-1 text-[10px] font-semibold rounded-md border transition', isDark ? 'border-white/10 text-white/50 hover:bg-white/[0.06] hover:text-white/80' : 'border-slate-200 text-slate-500 hover:bg-indigo-50 hover:text-indigo-600 hover:border-indigo-200']" title="Download CSV">
                    <svg xmlns="http://www.w3.org/2000/svg" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                    CSV
                  </button>
                  <span :class="['text-[10px]', isDark ? 'text-white/30' : 'text-slate-400']">{{ msg.chatResponse.row_count }} rows</span>
                </div>
              </div>
              <div class="overflow-x-auto max-h-[250px] overflow-y-auto">
                <table class="w-full text-xs">
                  <thead :class="['sticky top-0 backdrop-blur-sm', isDark ? 'bg-slate-900/80' : 'bg-slate-50']">
                    <tr>
                      <th v-for="col in msg.chatResponse.columns" :key="col" :class="['text-left px-3 py-2 font-semibold uppercase text-[10px] tracking-wider whitespace-nowrap', isDark ? 'text-indigo-300/80' : 'text-indigo-600/70']">{{ col }}</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="(row, ri) in (msg.chatResponse.data || []).slice(0, 15)" :key="ri" :class="['border-t transition', isDark ? 'border-white/[0.04] hover:bg-white/[0.02]' : 'border-slate-100 hover:bg-slate-50']">
                      <td v-for="col in msg.chatResponse.columns" :key="col" :class="['px-3 py-1.5 whitespace-nowrap', isDark ? 'text-white/60' : 'text-slate-600']">{{ row[col] ?? '—' }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <div v-if="(msg.chatResponse.row_count || 0) > 15" :class="['px-3 py-1.5 text-[10px] text-center border-t', isDark ? 'text-white/30 border-white/[0.04]' : 'text-slate-400 border-slate-100']">
                Showing 15 of {{ msg.chatResponse.row_count }} rows
              </div>
            </div>
          </div>

          <p :class="['text-[9px] mt-2 text-right', msg.role === 'user' ? 'opacity-50' : isDark ? 'opacity-30' : 'opacity-40']">{{ msg.timestamp }}</p>
        </div>

        <!-- User Avatar -->
        <div v-if="msg.role === 'user'" :class="['shrink-0 h-8 w-8 rounded-full flex items-center justify-center text-xs font-bold mt-1', isDark ? 'bg-white/10 text-white' : 'bg-indigo-100 text-indigo-600']">U</div>
      </div>

      <!-- Typing Indicator -->
      <div v-if="isLoading" class="flex gap-3 justify-start">
        <div class="shrink-0 h-8 w-8 rounded-full bg-gradient-to-br from-indigo-500 to-violet-600 flex items-center justify-center text-xs font-bold text-white shadow-lg shadow-indigo-500/20 mt-1">AI</div>
        <div :class="['rounded-2xl rounded-bl-md px-5 py-4 border', isDark ? 'bg-white/[0.06] border-white/[0.06]' : 'bg-slate-100 border-slate-200/60']">
          <div class="flex items-center gap-1.5">
            <div class="h-2 w-2 rounded-full bg-indigo-400 animate-bounce" style="animation-delay:0ms"/>
            <div class="h-2 w-2 rounded-full bg-violet-400 animate-bounce" style="animation-delay:150ms"/>
            <div class="h-2 w-2 rounded-full bg-pink-400 animate-bounce" style="animation-delay:300ms"/>
          </div>
        </div>
      </div>
    </div>

    <!-- Suggestions -->
    <div v-if="messages.length <= 1" class="shrink-0 px-4 pb-3">
      <p :class="['text-[10px] font-bold uppercase tracking-wider mb-2 pl-1', isDark ? 'text-white/30' : 'text-slate-400']">Try asking</p>
      <div class="flex flex-wrap gap-2">
        <button v-for="s in SUGGESTIONS" :key="s" @click="inputText = s; sendMessage()" :class="['px-3 py-1.5 text-xs rounded-full border transition-all', isDark ? 'bg-white/[0.05] border-white/[0.08] text-white/50 hover:bg-white/[0.1] hover:text-white/80 hover:border-white/[0.15]' : 'bg-slate-100 border-slate-200 text-slate-500 hover:bg-indigo-50 hover:text-indigo-600 hover:border-indigo-200']">{{ s }}</button>
      </div>
    </div>

    <!-- Input -->
    <div :class="['shrink-0 p-4 backdrop-blur-xl border-t transition-colors duration-300', isDark ? 'bg-white/[0.02] border-white/[0.06]' : 'bg-white/80 border-slate-200/60']">
      <div class="max-w-3xl mx-auto flex gap-3">
        <div class="flex-1 relative">
          <input
            v-model="inputText"
            @keydown.enter="sendMessage"
            :disabled="isLoading"
            type="text"
            placeholder="Ask a question about your data…"
            :class="['w-full h-11 rounded-xl border px-4 pr-12 text-sm outline-none transition disabled:opacity-50', isDark ? 'bg-white/[0.06] border-white/[0.08] text-white/90 placeholder-white/25 focus:border-indigo-500/50 focus:ring-2 focus:ring-indigo-500/20' : 'bg-slate-50 border-slate-200 text-slate-800 placeholder-slate-400 focus:border-indigo-400 focus:ring-2 focus:ring-indigo-500/20']"
          />
        </div>
        <button
          @click="sendMessage"
          :disabled="isLoading || !inputText.trim()"
          class="h-11 px-5 rounded-xl bg-gradient-to-r from-indigo-600 to-violet-600 text-white text-sm font-semibold hover:from-indigo-500 hover:to-violet-500 disabled:opacity-40 shadow-lg shadow-indigo-500/20 transition flex items-center gap-2"
        >
          <svg v-if="isLoading" class="animate-spin h-4 w-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"/></svg>
          <svg v-else xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m22 2-7 20-4-9-9-4Z"/><path d="M22 2 11 13"/></svg>
          Send
        </button>
      </div>
    </div>
  </div>
</template>
