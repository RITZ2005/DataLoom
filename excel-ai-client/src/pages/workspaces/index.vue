<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import workspaceApi, { type WorkspaceResponse } from '@/services/workspaceApi'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog'
import {
  Card,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { toast } from 'vue-sonner'

const router = useRouter()
const workspaces = ref<WorkspaceResponse[]>([])
const isLoading = ref(true)
const searchQuery = ref('')

const filteredWorkspaces = computed(() => {
  if (!searchQuery.value.trim()) return workspaces.value
  const q = searchQuery.value.toLowerCase()
  return workspaces.value.filter(ws =>
    ws.name.toLowerCase().includes(q) || (ws.description || '').toLowerCase().includes(q)
  )
})

// Create modal state
const isCreateModalOpen = ref(false)
const isCreating = ref(false)
const newWorkspace = ref({
  name: '',
  description: ''
})

async function fetchWorkspaces() {
  isLoading.value = true
  try {
    workspaces.value = await workspaceApi.listWorkspaces()
  } catch (err: any) {
    toast.error('Failed to load workspaces')
    console.error(err)
  } finally {
    isLoading.value = false
  }
}

async function handleCreateWorkspace() {
  if (!newWorkspace.value.name.trim()) {
    toast.error('Workspace name is required')
    return
  }

  isCreating.value = true
  try {
    const created = await workspaceApi.createWorkspace({
      name: newWorkspace.value.name,
      description: newWorkspace.value.description
    })
    toast.success(`Workspace "${created.name}" created successfully`)
    isCreateModalOpen.value = false
    newWorkspace.value = { name: '', description: '' }
    await fetchWorkspaces()
  } catch (err: any) {
    toast.error(err.response?.data?.detail || 'Failed to create workspace')
  } finally {
    isCreating.value = false
  }
}

// Edit modal state
const isEditModalOpen = ref(false)
const isUpdating = ref(false)
const editingWorkspaceId = ref('')
const editWorkspaceForm = ref({
  name: '',
  description: ''
})

function openEditModal(ws: WorkspaceResponse) {
  editingWorkspaceId.value = ws.workspace_id
  editWorkspaceForm.value = {
    name: ws.name,
    description: ws.description || ''
  }
  isEditModalOpen.value = true
}

async function handleUpdateWorkspace() {
  if (!editWorkspaceForm.value.name.trim()) {
    toast.error('Workspace name is required')
    return
  }

  isUpdating.value = true
  try {
    await workspaceApi.updateWorkspace(editingWorkspaceId.value, {
      name: editWorkspaceForm.value.name,
      description: editWorkspaceForm.value.description
    })
    toast.success('Workspace updated successfully')
    isEditModalOpen.value = false
    await fetchWorkspaces()
  } catch (err: any) {
    toast.error(err.response?.data?.detail || 'Failed to update workspace')
  } finally {
    isUpdating.value = false
  }
}

async function handleDeleteWorkspace(id: string, name: string) {
  if (!confirm(`Are you sure you want to delete "${name}"? This will permanently remove all data in this workspace.`)) {
    return
  }

  try {
    await workspaceApi.deleteWorkspace(id)
    toast.success('Workspace deleted')
    await fetchWorkspaces()
  } catch (err: any) {
    toast.error('Failed to delete workspace')
  }
}

onMounted(fetchWorkspaces)

async function navigateToEtl(workspaceId: string) {
  try {
    const result = await workspaceApi.getEtlConnection(workspaceId)
    if (result.connection_id) {
      router.push(`/app/etl?workspace_id=${workspaceId}&connection_id=${result.connection_id}`)
    } else {
      router.push(`/app/etl?workspace_id=${workspaceId}`)
    }
  } catch {
    router.push(`/app/etl?workspace_id=${workspaceId}`)
  }
}

function copySchemaName(schemaName: string) {
  navigator.clipboard.writeText(schemaName)
  toast.success(`Schema name "${schemaName}" copied to clipboard!`)
}

// Gradient palette for cards
const gradients = [
  'from-amber-500 to-orange-500',
  'from-blue-500 to-indigo-500',
  'from-emerald-500 to-teal-500',
  'from-violet-500 to-purple-500',
  'from-rose-500 to-pink-500',
  'from-cyan-500 to-sky-500',
]
function getGradient(idx: number) {
  return gradients[idx % gradients.length]
}

const cardGlows = [
  'hover:shadow-amber-500/10 dark:hover:shadow-amber-500/5',
  'hover:shadow-blue-500/10 dark:hover:shadow-blue-500/5',
  'hover:shadow-emerald-500/10 dark:hover:shadow-emerald-500/5',
  'hover:shadow-violet-500/10 dark:hover:shadow-violet-500/5',
  'hover:shadow-rose-500/10 dark:hover:shadow-rose-500/5',
  'hover:shadow-cyan-500/10 dark:hover:shadow-cyan-500/5',
]
function getCardGlow(idx: number) {
  return cardGlows[idx % cardGlows.length]
}

const cardBorders = [
  'group-hover:border-amber-500/30 dark:group-hover:border-amber-500/20',
  'group-hover:border-blue-500/30 dark:group-hover:border-blue-500/20',
  'group-hover:border-emerald-500/30 dark:group-hover:border-emerald-500/20',
  'group-hover:border-violet-500/30 dark:group-hover:border-violet-500/20',
  'group-hover:border-rose-500/30 dark:group-hover:border-rose-500/20',
  'group-hover:border-cyan-500/30 dark:group-hover:border-cyan-500/20',
]
function getCardBorder(idx: number) {
  return cardBorders[idx % cardBorders.length]
}

// Collapsible analytics state & computed stats
const showAnalytics = ref(true)

const totalWorkspaces = computed(() => workspaces.value.length)
const totalTables = computed(() => {
  return workspaces.value.reduce((acc, ws) => acc + (ws.table_count || 0), 0)
})

const averageTables = computed(() => {
  if (workspaces.value.length === 0) return '0.0'
  return (totalTables.value / workspaces.value.length).toFixed(1)
})

const largestWorkspace = computed(() => {
  if (workspaces.value.length === 0) return null
  return [...workspaces.value].sort((a, b) => b.table_count - a.table_count)[0]
})

// Dynamic Storage Density Profiles
const emptyCount = computed(() => workspaces.value.filter(ws => (ws.table_count || 0) === 0).length)
const lightweightCount = computed(() => workspaces.value.filter(ws => (ws.table_count || 0) > 0 && (ws.table_count || 0) <= 2).length)
const mediumCount = computed(() => workspaces.value.filter(ws => (ws.table_count || 0) >= 3 && (ws.table_count || 0) <= 5).length)
const heavyCount = computed(() => workspaces.value.filter(ws => (ws.table_count || 0) > 5).length)
</script>

<template>
  <div class="p-6 space-y-8 max-w-7xl mx-auto min-h-screen">
    <!-- Header -->
    <div class="flex flex-col md:flex-row md:items-center justify-between gap-6">
      <div class="space-y-1">
        <div class="flex items-center gap-3">
          <div class="h-11 w-11 rounded-2xl bg-gradient-to-br from-amber-500 to-orange-500 flex items-center justify-center shadow-lg shadow-amber-500/20">
            <iconify-icon icon="lucide:layers" class="h-6 w-6 text-white" />
          </div>
          <h1 class="text-3xl font-bold tracking-tight bg-gradient-to-r from-slate-900 via-amber-600 to-orange-600 dark:from-white dark:via-amber-400 dark:to-orange-400 bg-clip-text text-transparent">
            Analytics Workspaces
          </h1>
        </div>
        <p class="text-muted-foreground text-sm ml-14">
          Manage isolated PostgreSQL environments for secure data analytics.
        </p>
      </div>
      <Button @click="isCreateModalOpen = true" class="bg-gradient-to-r from-amber-500 to-orange-500 hover:from-amber-600 hover:to-orange-600 hover:scale-[1.02] active:scale-[0.98] transition-all duration-200 shadow-lg shadow-amber-500/25 dark:shadow-amber-500/10 rounded-xl h-11 px-6 text-sm font-semibold">
        <iconify-icon icon="lucide:plus" class="mr-2 h-4 w-4" />
        New Workspace
      </Button>
    </div>

    <!-- Stats Banner / Simplified Platform Overview -->
    <div v-if="workspaces.length > 0" class="grid grid-cols-1 sm:grid-cols-3 gap-6 animate-fade-in">
      <!-- Total Workspaces Card -->
      <div class="relative overflow-hidden rounded-2xl border border-amber-100/50 dark:border-zinc-800 bg-white/70 dark:bg-zinc-900/70 backdrop-blur-md p-6 flex items-center justify-between shadow-sm group hover:shadow-md transition-all duration-300">
        <div class="space-y-1">
          <p class="text-xs font-bold text-amber-600 dark:text-amber-400 uppercase tracking-wider">Active Clusters</p>
          <p class="text-2xl font-bold text-slate-800 dark:text-zinc-100 tracking-tight">{{ totalWorkspaces }} Workspaces</p>
          <p class="text-[10px] text-muted-foreground">Isolated query environments</p>
        </div>
        <div class="h-12 w-12 rounded-xl bg-amber-50 dark:bg-amber-950/40 flex items-center justify-center text-amber-500 group-hover:scale-110 transition-transform duration-300 shadow-sm">
          <iconify-icon icon="lucide:layers" class="h-6 w-6" />
        </div>
        <div class="absolute -bottom-6 -right-6 h-24 w-24 rounded-full bg-amber-500/5 blur-xl"></div>
      </div>

      <!-- Total Tables Card -->
      <div class="relative overflow-hidden rounded-2xl border border-emerald-100/50 dark:border-zinc-800 bg-white/70 dark:bg-zinc-900/70 backdrop-blur-md p-6 flex items-center justify-between shadow-sm group hover:shadow-md transition-all duration-300">
        <div class="space-y-1">
          <p class="text-xs font-bold text-emerald-600 dark:text-emerald-400 uppercase tracking-wider">Registered Tables</p>
          <p class="text-2xl font-bold text-slate-800 dark:text-zinc-100 tracking-tight">{{ totalTables }} Datasets</p>
          <p class="text-[10px] text-muted-foreground">Cataloged inside environments</p>
        </div>
        <div class="h-12 w-12 rounded-xl bg-emerald-50 dark:bg-emerald-950/40 flex items-center justify-center text-emerald-500 group-hover:scale-110 transition-transform duration-300 shadow-sm">
          <iconify-icon icon="lucide:table-2" class="h-6 w-6" />
        </div>
        <div class="absolute -bottom-6 -right-6 h-24 w-24 rounded-full bg-emerald-500/5 blur-xl"></div>
      </div>

      <!-- Database Engine Card -->
      <div class="relative overflow-hidden rounded-2xl border border-blue-100/50 dark:border-zinc-800 bg-white/70 dark:bg-zinc-900/70 backdrop-blur-md p-6 flex items-center justify-between shadow-sm group hover:shadow-md transition-all duration-300">
        <div class="space-y-1">
          <p class="text-xs font-bold text-blue-600 dark:text-blue-400 uppercase tracking-wider">Database Engine</p>
          <p class="text-xl font-bold text-slate-800 dark:text-zinc-100 tracking-tight flex items-center gap-1.5 mt-0.5 leading-none">
            <span class="h-2.5 w-2.5 rounded-full bg-green-500 animate-pulse shrink-0"></span>
            PostgreSQL 18
          </p>
          <p class="text-[10px] text-muted-foreground">Secure connection pool active</p>
        </div>
        <div class="h-12 w-12 rounded-xl bg-blue-50 dark:bg-blue-950/40 flex items-center justify-center text-blue-500 group-hover:scale-110 transition-transform duration-300 shadow-sm">
          <iconify-icon icon="lucide:database" class="h-6 w-6" />
        </div>
        <div class="absolute -bottom-6 -right-6 h-24 w-24 rounded-full bg-blue-500/5 blur-xl"></div>
      </div>
    </div>

    <!-- Search Bar -->
    <div v-if="workspaces.length > 0" class="relative max-w-md">
      <div class="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none">
        <iconify-icon icon="lucide:search" class="h-4 w-4 text-muted-foreground" />
      </div>
      <Input
        v-model="searchQuery"
        placeholder="Search workspaces..."
        class="pl-10 h-11 rounded-xl bg-white/70 dark:bg-zinc-900/70 backdrop-blur-sm border-slate-200 dark:border-zinc-800 shadow-sm focus-visible:ring-amber-500 focus-visible:ring-1 transition-all duration-200"
      />
    </div>

    <!-- Loading State -->
    <div v-if="isLoading" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
      <div v-for="i in 3" :key="i" class="animate-pulse rounded-2xl border border-border/50 bg-card/50 p-6 space-y-4">
        <div class="flex items-center justify-between">
          <div class="h-12 w-12 bg-muted rounded-xl"></div>
          <div class="h-6 bg-muted rounded-md w-20"></div>
        </div>
        <div class="space-y-2">
          <div class="h-6 bg-muted rounded w-3/4"></div>
          <div class="h-4 bg-muted rounded w-1/2"></div>
        </div>
        <div class="h-10 bg-muted rounded-xl"></div>
        <div class="grid grid-cols-5 gap-1 pt-2">
          <div v-for="j in 5" :key="j" class="h-12 bg-muted rounded-xl"></div>
        </div>
      </div>
    </div>

    <!-- Empty State -->
    <div v-else-if="workspaces.length === 0" class="flex flex-col items-center justify-center py-24 bg-gradient-to-b from-amber-50/30 to-transparent dark:from-amber-950/10 rounded-3xl border-2 border-dashed border-amber-200/50 dark:border-amber-800/30 shadow-inner">
       <div class="h-20 w-20 rounded-2xl bg-gradient-to-br from-amber-100 to-orange-100 dark:from-amber-900/30 dark:to-orange-900/20 flex items-center justify-center mb-5 shadow-lg shadow-amber-500/10">
         <iconify-icon icon="lucide:briefcase" class="h-10 w-10 text-amber-600" />
       </div>
       <h3 class="text-xl font-bold text-slate-800 dark:text-zinc-100">No workspaces yet</h3>
       <p class="text-muted-foreground mt-2 max-w-sm text-center text-sm">
         Create your first workspace to start cataloging databases and chatting with your data.
       </p>
       <Button @click="isCreateModalOpen = true" class="mt-6 bg-gradient-to-r from-amber-500 to-orange-500 rounded-xl shadow-md px-6 py-5 hover:scale-105 active:scale-98 transition-transform">
         <iconify-icon icon="lucide:plus" class="mr-2 h-4 w-4" />
         Get Started
       </Button>
    </div>

    <!-- No search results -->
    <div v-else-if="filteredWorkspaces.length === 0 && searchQuery" class="text-center py-16 text-muted-foreground border-2 border-dashed border-slate-100 dark:border-zinc-800 rounded-3xl">
      <iconify-icon icon="lucide:search-x" class="h-12 w-12 mx-auto mb-4 text-slate-300 dark:text-zinc-700 animate-bounce" />
      <p class="text-base font-medium">No workspaces match "{{ searchQuery }}"</p>
      <p class="text-xs text-muted-foreground/80 mt-1">Try refining your search terms or create a new workspace.</p>
    </div>

    <!-- Workspace Grid -->
    <div v-else class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
      <Card
        v-for="(ws, idx) in filteredWorkspaces"
        :key="ws.workspace_id"
        :class="['group hover:shadow-2xl hover:-translate-y-1 transition-all duration-300 border-slate-100 dark:border-zinc-800 bg-white/80 dark:bg-zinc-900/80 backdrop-blur-md overflow-hidden relative rounded-2xl card-enter', getCardGlow(idx), getCardBorder(idx)]"
        :style="{ animationDelay: `${idx * 80}ms` }"
      >
        <!-- Action buttons (Edit & Delete) -->
        <div class="absolute top-4 right-4 opacity-0 group-hover:opacity-100 transition-opacity duration-300 z-10 flex items-center gap-1.5">
          <Button variant="ghost" size="icon" class="h-8 w-8 text-slate-400 hover:text-amber-500 hover:bg-amber-50 dark:hover:bg-amber-950/30 rounded-lg transition-all duration-200" @click="openEditModal(ws)" title="Edit workspace">
             <iconify-icon icon="lucide:pencil" class="h-3.5 w-3.5" />
          </Button>
          <Button variant="ghost" size="icon" class="h-8 w-8 text-slate-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-950/30 rounded-lg transition-all duration-200" @click="handleDeleteWorkspace(ws.workspace_id, ws.name)" title="Delete workspace">
             <iconify-icon icon="lucide:trash-2" class="h-3.5 w-3.5" />
          </Button>
        </div>

        <CardHeader class="pb-3 px-5 pt-5">
          <div class="flex items-center justify-between">
            <div :class="['h-11 w-11 rounded-xl bg-gradient-to-br flex items-center justify-center text-white shadow-md transform group-hover:scale-105 transition-all duration-300', getGradient(idx)]">
               <iconify-icon icon="lucide:layout" class="h-5 w-5" />
            </div>
            <div class="flex items-center gap-1.5">
              <!-- Tables badge -->
              <span class="inline-flex items-center gap-1 text-[10px] font-bold tracking-wider uppercase px-2 py-0.5 bg-emerald-50 dark:bg-emerald-950/40 text-emerald-600 dark:text-emerald-400 rounded-lg border border-emerald-100/60 dark:border-emerald-900/30 shadow-xs">
                <iconify-icon icon="lucide:table-2" class="h-3.5 w-3.5" />
                {{ ws.table_count }} {{ ws.table_count === 1 ? 'Table' : 'Tables' }}
              </span>

              <!-- Dynamic Density Pill -->
              <span v-if="ws.table_count === 0" class="inline-flex items-center gap-1 text-[9px] font-bold uppercase px-2 py-0.5 bg-slate-50 dark:bg-zinc-800/50 text-slate-400 dark:text-zinc-500 rounded-lg border border-slate-200/40 dark:border-zinc-750">
                Empty
              </span>
              <span v-else-if="ws.table_count <= 2" class="inline-flex items-center gap-1 text-[9px] font-bold uppercase px-2 py-0.5 bg-amber-50/70 dark:bg-amber-950/20 text-amber-600 dark:text-amber-400 rounded-lg border border-amber-100/30 dark:border-amber-900/10">
                Light
              </span>
              <span v-else-if="ws.table_count <= 5" class="inline-flex items-center gap-1 text-[9px] font-bold uppercase px-2 py-0.5 bg-blue-50/70 dark:bg-blue-950/20 text-blue-600 dark:text-blue-400 rounded-lg border border-blue-100/30 dark:border-blue-900/10">
                Balanced
              </span>
              <span v-else class="inline-flex items-center gap-1 text-[9px] font-bold uppercase px-2 py-0.5 bg-purple-50/70 dark:bg-purple-950/20 text-purple-600 dark:text-purple-400 rounded-lg border border-purple-100/30 dark:border-purple-900/10">
                Dense
              </span>
            </div>
          </div>
          <CardTitle class="mt-4 text-[21px] font-bold tracking-tight text-slate-800 dark:text-zinc-100 group-hover:bg-gradient-to-r group-hover:from-amber-500 group-hover:to-orange-600 group-hover:bg-clip-text group-hover:text-transparent transition-all duration-300">
            {{ ws.name }}
          </CardTitle>
          <div :class="['pl-3 border-l-2 mt-2 transition-colors duration-300', 
            idx % 6 === 0 ? 'border-amber-100 dark:border-zinc-800 group-hover:border-amber-500/40' :
            idx % 6 === 1 ? 'border-blue-100 dark:border-zinc-800 group-hover:border-blue-500/40' :
            idx % 6 === 2 ? 'border-emerald-100 dark:border-zinc-800 group-hover:border-emerald-500/40' :
            idx % 6 === 3 ? 'border-violet-100 dark:border-zinc-800 group-hover:border-violet-500/40' :
            idx % 6 === 4 ? 'border-rose-100 dark:border-zinc-800 group-hover:border-rose-500/40' :
                            'border-cyan-100 dark:border-zinc-800 group-hover:border-cyan-500/40'
          ]">
            <CardDescription class="line-clamp-2 min-h-[2.5rem] text-xs leading-relaxed text-slate-500 dark:text-zinc-400">
              {{ ws.description || 'No description provided for this workspace.' }}
            </CardDescription>
          </div>
        </CardHeader>

        <!-- Database Badge Row -->
        <div class="pt-0 pb-4 px-5">
          <div class="group/db flex items-center justify-between px-3 py-2 rounded-xl bg-slate-50/50 dark:bg-zinc-800/30 border border-slate-100 dark:border-zinc-800/50 hover:bg-slate-100/50 dark:hover:bg-zinc-850 transition-colors duration-200">
            <button
              class="flex items-center gap-2 text-[10px] font-mono text-slate-500 dark:text-zinc-400 truncate max-w-[70%]"
              @click="copySchemaName(ws.schema_name)"
              title="Click to copy schema name"
            >
              <iconify-icon icon="lucide:database" class="h-3.5 w-3.5 text-slate-400 group-hover/db:text-amber-500 shrink-0 transition-colors animate-pulse" />
              <span class="truncate">{{ ws.schema_name }}</span>
              <iconify-icon icon="lucide:copy" class="h-2.5 w-2.5 opacity-0 group-hover/db:opacity-100 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 transition-opacity" />
            </button>
            <div class="flex items-center gap-1.5 text-[9px] font-medium text-slate-400 dark:text-zinc-500">
              <span class="px-1 py-0.5 rounded bg-slate-100 dark:bg-zinc-800 text-[8px] font-bold text-slate-500 dark:text-zinc-400 border border-slate-200/50 dark:border-zinc-700/30">PG-18</span>
              <span v-if="ws.created_at">{{ new Date(ws.created_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' }) }}</span>
            </div>
          </div>
        </div>

        <!-- Navigation Tiles -->
        <CardFooter class="grid grid-cols-5 gap-1.5 pt-4 border-t border-slate-100 dark:border-zinc-800/60 px-4 pb-4 bg-slate-50/20 dark:bg-zinc-900/20">
           <!-- Catalog -->
           <button
             class="group/btn flex flex-col items-center justify-center gap-1.5 py-2.5 rounded-xl text-[10px] font-bold text-slate-600 dark:text-slate-300 hover:text-amber-600 dark:hover:text-amber-400 bg-white/70 dark:bg-zinc-900/30 hover:bg-amber-50 dark:hover:bg-amber-950/30 border border-slate-100/60 dark:border-zinc-800/40 hover:border-amber-100 dark:hover:border-amber-900/30 transition-all duration-300 shadow-sm"
             @click="router.push(`/app/workspaces/${ws.workspace_id}`)"
             title="Database Catalog"
           >
              <div class="h-8 w-8 rounded-lg bg-white dark:bg-zinc-800/80 group-hover/btn:bg-amber-100/60 dark:group-hover/btn:bg-amber-900/50 flex items-center justify-center text-amber-500 transition-all duration-300 shadow-sm border border-slate-50 dark:border-zinc-700/30">
                <iconify-icon icon="lucide:book-open" class="h-4 w-4 transform group-hover/btn:scale-110 transition-transform duration-300" />
              </div>
              Catalog
           </button>

           <!-- Chat -->
           <button
             class="group/btn flex flex-col items-center justify-center gap-1.5 py-2.5 rounded-xl text-[10px] font-bold text-slate-600 dark:text-slate-300 hover:text-blue-600 dark:hover:text-blue-400 bg-white/70 dark:bg-zinc-900/30 hover:bg-blue-50 dark:hover:bg-blue-950/30 border border-slate-100/60 dark:border-zinc-800/40 hover:border-blue-100 dark:hover:border-blue-900/30 transition-all duration-300 shadow-sm"
             @click="router.push(`/app/workspaces/${ws.workspace_id}/chat`)"
             title="AI Chat"
           >
              <div class="h-8 w-8 rounded-lg bg-white dark:bg-zinc-800/80 group-hover/btn:bg-blue-100/60 dark:group-hover/btn:bg-blue-900/50 flex items-center justify-center text-blue-500 transition-all duration-300 shadow-sm border border-slate-50 dark:border-zinc-700/30">
                <iconify-icon icon="lucide:message-square" class="h-4 w-4 transform group-hover/btn:scale-110 transition-transform duration-300" />
              </div>
              Chat
           </button>

           <!-- Board -->
           <button
             class="group/btn flex flex-col items-center justify-center gap-1.5 py-2.5 rounded-xl text-[10px] font-bold text-slate-600 dark:text-slate-300 hover:text-emerald-600 dark:hover:text-emerald-400 bg-white/70 dark:bg-zinc-900/30 hover:bg-emerald-50 dark:hover:bg-emerald-950/30 border border-slate-100/60 dark:border-zinc-800/40 hover:border-emerald-100 dark:hover:border-emerald-900/30 transition-all duration-300 shadow-sm"
             @click="router.push(`/app/workspaces/${ws.workspace_id}/dashboard`)"
             title="Analytics Dashboard"
           >
              <div class="h-8 w-8 rounded-lg bg-white dark:bg-zinc-800/80 group-hover/btn:bg-emerald-100/60 dark:group-hover/btn:bg-emerald-900/50 flex items-center justify-center text-emerald-500 transition-all duration-300 shadow-sm border border-slate-50 dark:border-zinc-700/30">
                <iconify-icon icon="lucide:layout-dashboard" class="h-4 w-4 transform group-hover/btn:scale-110 transition-transform duration-300" />
              </div>
              Board
           </button>

           <!-- Report -->
           <button
             class="group/btn flex flex-col items-center justify-center gap-1.5 py-2.5 rounded-xl text-[10px] font-bold text-slate-600 dark:text-slate-300 hover:text-purple-600 dark:hover:text-purple-400 bg-white/70 dark:bg-zinc-900/30 hover:bg-purple-50 dark:hover:bg-purple-950/30 border border-slate-100/60 dark:border-zinc-800/40 hover:border-purple-100 dark:hover:border-purple-900/30 transition-all duration-300 shadow-sm"
             @click="router.push(`/app/workspaces/${ws.workspace_id}/report`)"
             title="SQL Reports"
           >
              <div class="h-8 w-8 rounded-lg bg-white dark:bg-zinc-800/80 group-hover/btn:bg-purple-100/60 dark:group-hover/btn:bg-purple-900/50 flex items-center justify-center text-purple-500 transition-all duration-300 shadow-sm border border-slate-50 dark:border-zinc-700/30">
                <iconify-icon icon="lucide:file-text" class="h-4 w-4 transform group-hover/btn:scale-110 transition-transform duration-300" />
              </div>
              Report
           </button>

           <!-- ETL -->
           <button
             class="group/btn flex flex-col items-center justify-center gap-1.5 py-2.5 rounded-xl text-[10px] font-bold text-slate-600 dark:text-slate-300 hover:text-violet-600 dark:hover:text-violet-400 bg-white/70 dark:bg-zinc-900/30 hover:bg-violet-50 dark:hover:bg-violet-950/30 border border-slate-100/60 dark:border-zinc-800/40 hover:border-violet-100 dark:hover:border-violet-900/30 transition-all duration-300 shadow-sm"
             @click="navigateToEtl(ws.workspace_id)"
             title="ETL Sync"
           >
              <div class="h-8 w-8 rounded-lg bg-white dark:bg-zinc-800/80 group-hover/btn:bg-violet-100/60 dark:group-hover/btn:bg-violet-900/50 flex items-center justify-center text-violet-500 transition-all duration-300 shadow-sm border border-slate-50 dark:border-zinc-700/30">
                <iconify-icon icon="lucide:zap" class="h-4 w-4 transform group-hover/btn:scale-110 transition-transform duration-300" />
              </div>
              ETL
           </button>
        </CardFooter>
      </Card>
    </div>

    <!-- Create Workspace Dialog -->
    <Dialog v-model:open="isCreateModalOpen">
      <DialogContent class="sm:max-w-[425px] rounded-2xl p-6 bg-white dark:bg-zinc-900 border border-slate-200 dark:border-zinc-800 shadow-2xl">
        <DialogHeader class="space-y-3">
          <DialogTitle class="flex items-center gap-3 text-lg font-bold text-slate-800 dark:text-zinc-100">
            <div class="h-9 w-9 rounded-xl bg-gradient-to-br from-amber-500 to-orange-500 flex items-center justify-center shadow-md shadow-amber-500/20">
              <iconify-icon icon="lucide:plus" class="h-5 w-5 text-white" />
            </div>
            Create Workspace
          </DialogTitle>
          <DialogDescription class="text-xs text-muted-foreground">
            Give your analytics workspace a name. This creates a dedicated, isolated PostgreSQL schema for cataloging and conversational query analysis.
          </DialogDescription>
        </DialogHeader>
        <div class="grid gap-4 py-4">
          <div class="space-y-2">
            <label class="text-xs font-bold text-slate-500 dark:text-zinc-400 uppercase tracking-wider">Workspace Name</label>
            <Input v-model="newWorkspace.name" placeholder="e.g. Sales Analysis" @keyup.enter="handleCreateWorkspace" class="rounded-xl h-11 border-slate-200 dark:border-zinc-800 focus-visible:ring-amber-500 focus-visible:ring-1" />
          </div>
          <div class="space-y-2">
            <label class="text-xs font-bold text-slate-500 dark:text-zinc-400 uppercase tracking-wider">Description (Optional)</label>
            <Textarea v-model="newWorkspace.description" placeholder="What kind of analysis will you do here?" class="rounded-xl min-h-[100px] border-slate-200 dark:border-zinc-800 focus-visible:ring-amber-500 focus-visible:ring-1 resize-none" />
          </div>
        </div>
        <DialogFooter class="gap-2 sm:gap-0 pt-2">
          <Button variant="ghost" @click="isCreateModalOpen = false" class="rounded-xl h-11 font-medium hover:bg-slate-100 dark:hover:bg-zinc-800 text-slate-500 dark:text-zinc-400">Cancel</Button>
          <Button @click="handleCreateWorkspace" :disabled="isCreating" class="bg-gradient-to-r from-amber-500 to-orange-500 rounded-xl shadow-md h-11 px-5 font-semibold text-white hover:scale-[1.02] active:scale-[0.98] transition-transform">
            <iconify-icon v-if="isCreating" icon="lucide:loader-2" class="mr-2 h-4 w-4 animate-spin" />
            Create Workspace
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <!-- Edit Workspace Dialog -->
    <Dialog v-model:open="isEditModalOpen">
      <DialogContent class="sm:max-w-[425px] rounded-2xl p-6 bg-white dark:bg-zinc-900 border border-slate-200 dark:border-zinc-800 shadow-2xl">
        <DialogHeader class="space-y-3">
          <DialogTitle class="flex items-center gap-3 text-lg font-bold text-slate-800 dark:text-zinc-100">
            <div class="h-9 w-9 rounded-xl bg-gradient-to-br from-amber-500 to-orange-500 flex items-center justify-center shadow-md shadow-amber-500/20">
              <iconify-icon icon="lucide:pencil" class="h-5 w-5 text-white" />
            </div>
            Edit Workspace
          </DialogTitle>
          <DialogDescription class="text-xs text-muted-foreground">
            Modify the workspace name and description attributes. Changes take effect immediately across all dashboard views.
          </DialogDescription>
        </DialogHeader>
        <div class="grid gap-4 py-4">
          <div class="space-y-2">
            <label class="text-xs font-bold text-slate-500 dark:text-zinc-400 uppercase tracking-wider">Workspace Name</label>
            <Input v-model="editWorkspaceForm.name" placeholder="e.g. Sales Analysis" @keyup.enter="handleUpdateWorkspace" class="rounded-xl h-11 border-slate-200 dark:border-zinc-800 focus-visible:ring-amber-500 focus-visible:ring-1" />
          </div>
          <div class="space-y-2">
            <label class="text-xs font-bold text-slate-500 dark:text-zinc-400 uppercase tracking-wider">Description</label>
            <Textarea v-model="editWorkspaceForm.description" placeholder="What kind of analysis will you do here?" class="rounded-xl min-h-[100px] border-slate-200 dark:border-zinc-800 focus-visible:ring-amber-500 focus-visible:ring-1 resize-none" />
          </div>
        </div>
        <DialogFooter class="gap-2 sm:gap-0 pt-2">
          <Button variant="ghost" @click="isEditModalOpen = false" class="rounded-xl h-11 font-medium hover:bg-slate-100 dark:hover:bg-zinc-800 text-slate-500 dark:text-zinc-400">Cancel</Button>
          <Button @click="handleUpdateWorkspace" :disabled="isUpdating" class="bg-gradient-to-r from-amber-500 to-orange-500 rounded-xl shadow-md h-11 px-5 font-semibold text-white hover:scale-[1.02] active:scale-[0.98] transition-transform">
            <iconify-icon v-if="isUpdating" icon="lucide:loader-2" class="mr-2 h-4 w-4 animate-spin" />
            Save Changes
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </div>
</template>

<style scoped>
.line-clamp-2 {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
@keyframes cardEnter {
  from { opacity: 0; transform: translateY(16px); }
  to { opacity: 1; transform: translateY(0); }
}
.card-enter {
  animation: cardEnter 0.5s ease-out both;
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}
.animate-fade-in {
  animation: fadeIn 0.4s ease-out both;
}
</style>
