<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
const route = useRoute()
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue
} from '@/components/ui/select'
import { Checkbox } from '@/components/ui/checkbox'
import excelFileAPI, {
  type ETLConnectRequest,
  type ETLConnectResponse,
  type ETLExtractDataset,
  type ETLTableInfo,
  type ETLPreviewResponse,
  type ETLDryRunResponse,
  type ETLJobStatusResponse,
  type ETLConnectionInfo,
} from '@/services/excelApi'
import { toast } from 'vue-sonner'
import { Codemirror } from 'vue-codemirror'
import { python } from '@codemirror/lang-python'
import { sql } from '@codemirror/lang-sql'
import { oneDark } from '@codemirror/theme-one-dark'


const router = useRouter()

// ── Wizard State ────────────────────────────────────────────────────
const currentStep = ref(1)
const totalSteps = 5

// Step 1: Connection
const dbType = ref('mysql')
const host = ref('localhost')
const port = ref(3306)
const username = ref('')
const password = ref('')
const database = ref('')
const authSource = ref('admin')
const connectionName = ref('')
const isConnecting = ref(false)
const connectionId = ref('')
const availableTables = ref<ETLTableInfo[]>([])

// Step 2: Pipeline Selection
const connectionPipelines = ref<ETLJobStatusResponse[]>([])
const isLoadingPipelines = ref(false)

async function loadPipelinesForConnection() {
  if (!connectionId.value) return
  isLoadingPipelines.value = true
  try {
    connectionPipelines.value = await excelFileAPI.etlGetConnectionJobs(connectionId.value)
  } catch (err: any) {
    toast.error('Could not load pipelines for this connection')
  } finally {
    isLoadingPipelines.value = false
  }
}

const isSyncingJob = ref<string | null>(null)
const previewSyncJobId = ref<string | null>(null)
const isPreviewSyncOpen = ref(false)
const isConfirmingPreviewSync = ref(false)
const previewSyncRows = ref(0)
const previewSyncTables = ref<any[]>([])
const renamingPipelineJobId = ref<string | null>(null)
const renamePipelineValue = ref('')
const isSavingPipelineName = ref(false)

function getPipelineName(job: ETLJobStatusResponse): string {
  const j: any = job as any
  return j.pipeline_name || job.target_table || `Pipeline ${job.job_id.slice(0, 8)}`
}

function getLastSyncTimestamp(job: ETLJobStatusResponse): string {
  return job.completed_at || job.created_at || 'Never Synced'
}

function getDestinationTables(job: ETLJobStatusResponse): string[] {
  const outputs = Array.isArray(job.output_tables) ? job.output_tables : []
  const names = outputs
    .map((t: any) => (t?.table_name || t?.full_table_name || '').trim())
    .filter((t: string) => t.length > 0)
  const uniqueNames = Array.from(new Set(names))
  if (uniqueNames.length) return uniqueNames
  return job.target_table ? [job.target_table] : []
}

function getSourceCount(job: ETLJobStatusResponse): number {
  return Array.isArray(job.source_tables) ? job.source_tables.length : 0
}

function getLoadedRows(job: ETLJobStatusResponse): number {
  if (!Array.isArray(job.output_tables)) return 0
  return job.output_tables.reduce((acc: number, t: any) => {
    const count = Number(t?.row_count || 0)
    return acc + (Number.isFinite(count) ? count : 0)
  }, 0)
}

function openRenamePipeline(job: ETLJobStatusResponse) {
  renamingPipelineJobId.value = job.job_id
  renamePipelineValue.value = getPipelineName(job)
}

function closeRenamePipeline() {
  renamingPipelineJobId.value = null
  renamePipelineValue.value = ''
}

async function savePipelineName() {
  if (!renamingPipelineJobId.value) return
  const newName = renamePipelineValue.value.trim()
  if (!newName) {
    toast.error('Pipeline name cannot be empty')
    return
  }

  isSavingPipelineName.value = true
  try {
    await excelFileAPI.etlUpdateJob(renamingPipelineJobId.value, {
      pipeline_name: newName,
    })
    toast.success('Pipeline name updated')
    closeRenamePipeline()
    await loadPipelinesForConnection()
  } catch (err: any) {
    toast.error(err?.response?.data?.detail || 'Failed to update pipeline name')
  } finally {
    isSavingPipelineName.value = false
  }
}

function hasDeltaSourceMetadata(job: ETLJobStatusResponse): boolean {
  const sources = Array.isArray(job.source_tables) ? job.source_tables : []
  if (!sources.length) return false

  const firstSource = sources[0] as any
  if (firstSource && typeof firstSource === 'object') {
    return Boolean(firstSource.table_name || firstSource.custom_query)
  }

  if (typeof firstSource === 'string') {
    const label = firstSource.trim().toLowerCase()
    return !!label && !label.startsWith('dataset_')
  }

  return false
}

function canDeltaSync(job: ETLJobStatusResponse): boolean {
  const hasSource = hasDeltaSourceMetadata(job)
  return hasSource
}

function deltaSyncBlockedReason(job: ETLJobStatusResponse): string {
  if (!hasDeltaSourceMetadata(job)) return 'This pipeline is missing source metadata for Delta Sync. Recreate it from Step 3.'
  if ((job as any).sync_mode_type !== 'flag' && !job.sync_column) {
    return 'No sync column configured. If query uses {{LAST_SYNC_VALUE}}, sync column will be auto-detected; otherwise configure Flag mode.'
  }
  return ''
}

async function syncPipeline(jobId: string) {
  isSyncingJob.value = jobId
  try {
    const preview = await excelFileAPI.etlDeltaSync(jobId, undefined, true)
    if (!preview.success) {
      toast.error(preview.message || 'Preview failed')
      return
    }

    const totalRows = Number(preview.total_new_rows || 0)
    if (totalRows <= 0) {
      toast.info(preview.message || 'No new rows found')
      return
    }

    previewSyncJobId.value = jobId
    previewSyncRows.value = totalRows
    previewSyncTables.value = Array.isArray(preview.preview_tables) ? preview.preview_tables : []
    isPreviewSyncOpen.value = true
  } catch (err: any) {
    const errorDetail = err?.response?.data?.detail || 'Sync failed'
    toast.error(errorDetail)
  } finally {
    isSyncingJob.value = null
  }
}

async function continuePreviewSync() {
  if (!previewSyncJobId.value) return
  isConfirmingPreviewSync.value = true
  isSyncingJob.value = previewSyncJobId.value
  try {
    const result = await excelFileAPI.etlDeltaSync(previewSyncJobId.value)
    if (result.success) {
      toast.success(result.message)
      isPreviewSyncOpen.value = false
      previewSyncJobId.value = null
      previewSyncRows.value = 0
      previewSyncTables.value = []
      await loadPipelinesForConnection()
    }
  } catch (err: any) {
    const errorDetail = err?.response?.data?.detail || 'Sync failed'
    toast.error(errorDetail)
  } finally {
    isConfirmingPreviewSync.value = false
    isSyncingJob.value = null
  }
}

// Step 3: Table selection
const selectedTables = ref<string[]>([])
const extractMode = ref<'tables' | 'custom_query'>('tables')
const customDatasets = ref<ETLExtractDataset[]>([
  { output_name: 'dataset_1', custom_query: '' }
])
const previewData = ref<ETLPreviewResponse | null>(null)
const previewingTable = ref('')
const isLoadingPreview = ref(false)


const isGeneratingAI = ref(false)
const aiPrompt = ref('')
const generateTransformAI = async () => {
  if (!aiPrompt.value) return
  try {
    isGeneratingAI.value = true
    const tableContext = extractMode.value === 'tables'
      ? selectedTables.value.map(t => ({ name: t }))
      : buildExtractDatasets().map(d => ({ name: d.output_name || 'custom_dataset', query_mode: true }))
    const result = await excelFileAPI.etlGenerateTransform(aiPrompt.value, tableContext)
    transformScript.value = result.script
    toast.success('Script generated successfully')
  } catch (err: any) {
    toast.error('Failed: ' + (err.response?.data?.detail || err.message))
  } finally {
    isGeneratingAI.value = false
  }
}

// Step 3: Transform script
const transformScript = ref(`import pandas as pd

def transform(tables: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """
    Process extracted data.
    
    Args:
        tables: Dict mapping table_name -> DataFrame
                e.g. {"users": users_df, "orders": orders_df}
    
    Returns:
        Dict mapping output_name -> transformed DataFrame
    """
    # Example: access tables
    # df = tables["my_table"]
    
    # Your transformation logic here
    # df = df.dropna()
    # df["new_col"] = df["col_a"] + df["col_b"]
    
    # Return all tables (modified or as-is)
    return tables
`)
const isDryRunning = ref(false)
const dryRunResult = ref<ETLDryRunResponse | null>(null)

// Step 4: Load Config
const targetTable = ref('')
const pipelineName = ref('')
const syncMode = ref<'overwrite' | 'append'>('overwrite')
const syncColumn = ref('')
const primaryKeysStr = ref('')
const primaryKeys = computed(() => primaryKeysStr.value.split(',').map(s => s.trim()).filter(Boolean))

// Step 5: Execute
const isExecuting = ref(false)
const jobId = ref('')
const jobStatus = ref<ETLJobStatusResponse | null>(null)
const pollingTimer = ref<number | null>(null)

const apiOrigin = computed(() => {
  return typeof window !== 'undefined' ? window.location.origin : 'http://localhost'
})

function copyToClipboard(text: string) {
  if (typeof navigator !== 'undefined' && navigator.clipboard) {
    // Basic toast-like feedback could go here.
    navigator.clipboard.writeText(text).catch(() => {})
  }
}

// Saved connections
const savedConnections = ref<ETLConnectionInfo[]>([])
const isLoadingConnections = ref(false)

// ── Computed ────────────────────────────────────────────────────────
const canConnect = computed(() => {
  return host.value.trim() && database.value.trim() && username.value.trim()
})

const canProceedToTransform = computed(() => {
  if (extractMode.value === 'tables') {
    return selectedTables.value.length > 0
  }
  return buildExtractDatasets().length > 0
})

const canProceedToExecute = computed(() => {
  return true
})

const selectedExtractLabels = computed(() => {
  if (extractMode.value === 'tables') return selectedTables.value
  return buildExtractDatasets().map(d => d.output_name || 'custom_dataset')
})

const activePreviewTable = computed(() => {
  if (!previewingTable.value) return null
  return availableTables.value.find((t) => t.name === previewingTable.value) || null
})

const stepLabels = ['Connect', 'Pipelines', 'Select Tables', 'Transform', 'Execute']

// Port defaults per db type
watch(dbType, (val) => {
  if (val === 'mysql') port.value = 3306
  else if (val === 'postgresql') port.value = 5432
  else if (val === 'mongodb') port.value = 27017
})

watch(extractMode, () => {
  dryRunResult.value = null
})

// ── Step 1: Connect ─────────────────────────────────────────────────
async function handleConnect() {
  if (!canConnect.value) return
  isConnecting.value = true
  try {
    const params: ETLConnectRequest = {
      db_type: dbType.value,
      host: host.value,
      port: port.value,
      username: username.value,
      password: password.value,
      database: database.value,
      auth_source: dbType.value === 'mongodb' ? authSource.value : undefined,
      connection_name: connectionName.value || undefined,
    }
    const result = await excelFileAPI.etlConnect(params)
    connectionId.value = result.connection_id
    availableTables.value = result.tables
    toast.success(`Connected! Found ${result.tables.length} table(s)`)
    currentStep.value = 2
    if (result.tables.length > 0) {
      await previewTable(result.tables[0].name)
    }
    await loadPipelinesForConnection()
  } catch (err: any) {
    const msg = err?.response?.data?.detail || err?.message || 'Connection failed'
    toast.error(msg)
  } finally {
    isConnecting.value = false
  }
}

async function useSavedConnection(conn: ETLConnectionInfo) {
  // Instead of populating the form and waiting for password, 
  // immediately connect using the saved connection ID.
  isConnecting.value = true
  try {
    const params: ETLConnectRequest = {
      connection_id: conn.connection_id
    }
    const result = await excelFileAPI.etlConnect(params)
    connectionId.value = result.connection_id
    
    // Also fill the UI purely for visual confirmation
    dbType.value = conn.db_type
    host.value = conn.host
    port.value = conn.port
    database.value = conn.database_name
    connectionName.value = conn.name
    username.value = '********' // Obfuscated
    password.value = '********'

    availableTables.value = result.tables
    toast.success(`Connected! Found ${result.tables.length} table(s)`)
    currentStep.value = 2
    if (result.tables.length > 0) {
      await previewTable(result.tables[0].name)
    }
    await loadPipelinesForConnection()
  } catch (err: any) {
    const msg = err?.response?.data?.detail || err?.message || 'Connection failed'
    toast.error(msg)
  } finally {
    isConnecting.value = false
  }
}

async function loadSavedConnections() {
  isLoadingConnections.value = true
  try {
    savedConnections.value = await excelFileAPI.etlListConnections()
  } catch { /* ignore */ } finally {
    isLoadingConnections.value = false
  }
}

async function deleteSavedConnection(connId: string) {
  try {
    await excelFileAPI.etlDeleteConnection(connId)
    savedConnections.value = savedConnections.value.filter(c => c.connection_id !== connId)
    toast.success('Connection removed')
  } catch {
    toast.error('Failed to delete connection')
  }
}

// ── Step 2: Table Selection ─────────────────────────────────────────
function toggleTable(tableName: string) {
  if (extractMode.value === 'custom_query') {
    previewTable(tableName)
    return
  }

  const idx = selectedTables.value.indexOf(tableName)
  if (idx >= 0) {
    selectedTables.value.splice(idx, 1)
  } else {
    selectedTables.value.push(tableName)
  }
}

function selectAllTables() {
  if (extractMode.value === 'custom_query') return

  if (selectedTables.value.length === availableTables.value.length) {
    selectedTables.value = []
  } else {
    selectedTables.value = availableTables.value.map(t => t.name)
  }
}

async function previewTable(tableName: string) {
  previewingTable.value = tableName
  isLoadingPreview.value = true
  try {
    previewData.value = await excelFileAPI.etlPreviewTable(connectionId.value, tableName, 20)
  } catch (err: any) {
    toast.error(err?.response?.data?.detail || 'Preview failed')
  } finally {
    isLoadingPreview.value = false
  }
}

// ── Step 3: Transform + Dry Run ─────────────────────────────────────
async function handleDryRun() {
  isDryRunning.value = true
  dryRunResult.value = null
  try {
    const result = await excelFileAPI.etlDryRun(
      connectionId.value,
      extractMode.value === 'tables' ? selectedTables.value : [],
      transformScript.value,
      buildExtractDatasets()
    )
    dryRunResult.value = result
    if (result.success) {
      toast.success(`Dry-run succeeded in ${result.duration_seconds.toFixed(1)}s`)
    } else {
      toast.error('Dry-run failed — check the error below')
    }
  } catch (err: any) {
    toast.error(err?.response?.data?.detail || 'Dry-run failed')
  } finally {
    isDryRunning.value = false
  }
}

// ── Step 5: Execute Full Pipeline ───────────────────────────────────
async function handleExecute() {
  if (!connectionId.value) {
    toast.error('Connection is missing. Please reconnect and try again.')
    return
  }
  if (isExecuting.value) return

  const normalizedTargetTable = targetTable.value.trim() || undefined
  const normalizedPipelineName = pipelineName.value.trim() || undefined
  const normalizedSyncColumn = syncColumn.value.trim() || undefined

  const routeWorkspaceId = route.query.workspace_id ? String(route.query.workspace_id) : undefined
  if (!routeWorkspaceId) {
    toast.error('workspace_id is required to run ETL in this workspace.')
    return
  }

  isExecuting.value = true
  try {
    const result = await excelFileAPI.etlExecuteJob(
      connectionId.value,
      extractMode.value === 'tables' ? selectedTables.value : [],
      transformScript.value,
      buildExtractDatasets(),
      normalizedTargetTable,
      normalizedPipelineName,
      syncMode.value,
      normalizedSyncColumn,
      routeWorkspaceId,
      primaryKeys.value.length > 0 ? primaryKeys.value : undefined,
      editingJobId.value || undefined
    )
    jobId.value = result.job_id
    toast.success('Job submitted! Monitoring progress...')
    startPolling()
  } catch (err: any) {
    toast.error(err?.response?.data?.detail || 'Execution failed')
    isExecuting.value = false
  }
}

function startPolling() {
  if (pollingTimer.value) clearInterval(pollingTimer.value)
  pollingTimer.value = window.setInterval(async () => {
    try {
      const status = await excelFileAPI.etlJobStatus(jobId.value)
      jobStatus.value = status
      if (status.status === 'complete' || status.status === 'failed') {
        stopPolling()
        isExecuting.value = false
        if (status.status === 'complete') {
          toast.success('🎉 ETL pipeline complete! Data loaded into PostgreSQL.')
        } else {
          toast.error(`Pipeline failed: ${status.error_message || 'Unknown error'}`)
        }
      }
    } catch {
      // Keep polling
    }
  }, 2000)
}

function stopPolling() {
  if (pollingTimer.value) {
    clearInterval(pollingTimer.value)
    pollingTimer.value = null
  }
}

function addCustomDataset() {
  const nextIdx = customDatasets.value.length + 1
  customDatasets.value.push({
    output_name: `dataset_${nextIdx}`,
    custom_query: ''
  })
}

function removeCustomDataset(index: number) {
  customDatasets.value.splice(index, 1)
  if (customDatasets.value.length === 0) {
    customDatasets.value.push({ output_name: 'dataset_1', custom_query: '' })
  }
}

// ── Navigation ──────────────────────────────────────────────────────
function goBack() {
  if (currentStep.value > 1) currentStep.value--
}

function goNext() {
  if (currentStep.value === 3 && canProceedToTransform.value) {
    currentStep.value = 4
  } else if (currentStep.value === 4) {
    currentStep.value = 5
  }
}

function buildExtractDatasets(): ETLExtractDataset[] {
  if (extractMode.value === 'custom_query') {
    return customDatasets.value
      .map((d, idx) => ({
        custom_query: (d.custom_query || '').trim(),
        output_name: (d.output_name || '').trim() || `dataset_${idx + 1}`,
      }))
      .filter(d => d.custom_query.length > 0)
  }
  return []
}

function skipTransformAndContinue() {
  transformScript.value = `import pandas as pd
from typing import Dict

def transform(tables: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
    return tables
`
  dryRunResult.value = null
  currentStep.value = 5
}

function resetWizard() {
  currentStep.value = 1
  connectionId.value = ''
  availableTables.value = []
  selectedTables.value = []
  extractMode.value = 'tables'
  customDatasets.value = [{ output_name: 'dataset_1', custom_query: '' }]
  targetTable.value = ''
  pipelineName.value = ''
  syncMode.value = 'overwrite'
  primaryKeysStr.value = ''
  previewData.value = null
  dryRunResult.value = null
  jobId.value = ''
  jobStatus.value = null
  stopPolling()
}

// Edit pipeline state
const editingJobId = ref<string | null>(null)

// Sync config editing state
const syncConfigEditingJobId = ref<string | null>(null)
const syncConfigModeType = ref('hwm')
const syncConfigColumn = ref('')

function openSyncConfig(job: any) {
  syncConfigEditingJobId.value = job.job_id
  syncConfigModeType.value = job.sync_mode_type || 'hwm'
  syncConfigColumn.value = job.sync_column || ''
}

function closeSyncConfig() {
  syncConfigEditingJobId.value = null
}

async function saveSyncConfig(jobId: string) {
  try {
    const payload: any = { sync_mode_type: syncConfigModeType.value }
    if (syncConfigModeType.value === 'hwm' && syncConfigColumn.value.trim()) {
      payload.sync_column = syncConfigColumn.value.trim()
    }
    await excelFileAPI.etlUpdateSyncConfig(jobId, payload)
    toast.success('Sync config saved!')
    closeSyncConfig()
    await loadPipelinesForConnection()
  } catch (err: any) {
    toast.error(err?.response?.data?.detail || 'Failed to save sync config')
  }
}

async function deletePipeline(jobId: string) {
  if (!confirm('Are you sure you want to delete this pipeline? This will also delete all related tables from the workspace.')) return
  try {
    await excelFileAPI.etlDeleteJob(jobId)
    toast.success('Pipeline deleted successfully')
    await loadPipelinesForConnection()
  } catch (err: any) {
    toast.error(err?.response?.data?.detail || 'Failed to delete pipeline')
  }
}

async function editPipeline(jobId: string) {
  try {
    const detail = await excelFileAPI.etlGetJobDetail(jobId)
    editingJobId.value = jobId

    // Pre-fill wizard state from job detail
    const sources = detail.source_tables || []
    const hasCustomQuery = sources.some((s: any) => s.custom_query)

    if (hasCustomQuery) {
      extractMode.value = 'custom_query'
      customDatasets.value = sources.map((s: any) => ({
        output_name: s.output_name || '',
        custom_query: s.custom_query || ''
      }))
      selectedTables.value = []
    } else {
      extractMode.value = 'tables'
      selectedTables.value = sources.map((s: any) => s.table_name || s).filter(Boolean)
      customDatasets.value = [{ output_name: 'dataset_1', custom_query: '' }]
    }

    transformScript.value = detail.transform_script || transformScript.value
    targetTable.value = detail.target_table || ''
    pipelineName.value = detail.pipeline_name || ''
    syncColumn.value = detail.sync_column || ''
    syncMode.value = detail.sync_mode || 'append'
    primaryKeysStr.value = (detail.primary_keys || []).join(', ')

    // Jump to Step 3 (Select Tables)
    currentStep.value = 3
    toast.info('Pipeline loaded for editing. Modify and proceed.')
  } catch (err: any) {
    toast.error(err?.response?.data?.detail || 'Failed to load pipeline detail')
  }
}

async function handleSaveConfigOnly() {
  if (!editingJobId.value) return
  try {
    await excelFileAPI.etlUpdateJob(editingJobId.value, {
      source_tables: extractMode.value === 'tables'
        ? selectedTables.value.map(t => ({ table_name: t }))
        : buildExtractDatasets(),
      transform_script: transformScript.value,
      target_table: targetTable.value || undefined,
      pipeline_name: pipelineName.value.trim() || undefined,
      sync_mode: syncMode.value,
      sync_column: syncColumn.value || undefined,
      primary_keys: primaryKeys.value.length > 0 ? primaryKeys.value : undefined,
    })
    toast.success('Pipeline config saved successfully!')
    editingJobId.value = null
    currentStep.value = 2
    await loadPipelinesForConnection()
  } catch (err: any) {
    toast.error(err?.response?.data?.detail || 'Failed to save pipeline')
  }
}

// ── Inline Relationship Builder (Task 6) ────────────────────────
const pendingRelationships = ref<{ source: string; target: string }[]>([])
const isSavingRelationships = ref(false)

async function saveAllRelationships() {
  const wsId = route.query.workspace_id as string | undefined
  if (!wsId) {
    toast.error('No workspace ID found')
    return
  }

  const valid = pendingRelationships.value.filter(r => r.source && r.target)
  if (!valid.length) {
    toast.warning('No valid relationships to save')
    return
  }

  isSavingRelationships.value = true
  let saved = 0
  try {
    const { default: workspaceApi } = await import('@/services/workspaceApi')
    for (const rel of valid) {
      const [srcTable, ...srcColParts] = rel.source.split('.')
      const [tgtTable, ...tgtColParts] = rel.target.split('.')
      const srcCol = srcColParts.join('.')
      const tgtCol = tgtColParts.join('.')

      if (!srcTable || !srcCol || !tgtTable || !tgtCol) continue
      try {
        await workspaceApi.createRelationship(wsId, {
          source_table: srcTable,
          source_column: srcCol,
          target_table: tgtTable,
          target_column: tgtCol,
          relationship_type: 'foreign_key',
        })
        saved++
      } catch (err: any) {
        toast.error(`Failed: ${srcTable}.${srcCol} → ${tgtTable}.${tgtCol}`)
      }
    }
    if (saved > 0) {
      toast.success(`${saved} relationship(s) saved!`)
      pendingRelationships.value = []
    }
  } catch (err: any) {
    toast.error(err?.message || 'Failed to save relationships')
  } finally {
    isSavingRelationships.value = false
  }
}

// Initialization
onMounted(async () => {
  await loadSavedConnections()
  
  // Auto-connect if connection_id is in the URL query
  const queryConnId = route.query.connection_id as string | undefined
  if (queryConnId) {
    const found = savedConnections.value.find(c => c.connection_id === queryConnId)
    if (found) {
      await useSavedConnection(found)
    }
  }
})
</script>

<template>
  <div class="min-h-full bg-gradient-to-br from-background via-background to-muted/20 p-4 pb-10 sm:p-6">
    <!-- Header & Stepper (Merged) -->
    <div class="sticky top-0 z-10 mx-auto w-full max-w-7xl mb-6 rounded-3xl border border-border/50 bg-background/80 px-6 py-4 shadow-sm backdrop-blur-xl flex flex-col md:flex-row items-center gap-6 justify-between">
      <div class="flex items-center gap-3 shrink-0 self-start md:self-auto">
        <Button v-if="route.query.workspace_id" variant="ghost" size="icon" class="shrink-0" @click="router.push(`/app/workspaces/${route.query.workspace_id}`)">
           <iconify-icon icon="lucide:arrow-left" class="h-5 w-5 text-muted-foreground" />
        </Button>
        <div class="flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br from-violet-500/90 to-indigo-600/80 shadow-sm">
          <iconify-icon icon="lucide:database" class="h-6 w-6 text-white" />
        </div>
        <div>
          <h1 class="text-2xl font-semibold tracking-tight">ETL Pipeline</h1>
          <p class="text-sm text-muted-foreground hidden sm:block">Connect, transform, and load external databases</p>
        </div>
      </div>

      <!-- Step Indicator -->
      <div class="flex items-center justify-center gap-2 flex-1 w-full md:max-w-[500px]">
        <div
          v-for="(label, i) in stepLabels"
          :key="i"
          class="flex items-center gap-2"
          :class="{ 'flex-1': i < stepLabels.length - 1 }"
        >
          <div
            class="w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold shrink-0 transition-all duration-300"
            :class="[
              currentStep > i + 1
                ? 'bg-emerald-500 text-white'
                : currentStep === i + 1
                  ? 'bg-primary text-primary-foreground ring-2 ring-primary/30'
                  : 'bg-muted text-muted-foreground'
            ]"
          >
            <iconify-icon v-if="currentStep > i + 1" icon="lucide:check" class="h-4 w-4" />
            <span v-else>{{ i + 1 }}</span>
          </div>
          <span
            class="text-[11px] font-medium hidden sm:block"
            :class="currentStep === i + 1 ? 'text-foreground' : 'text-muted-foreground'"
          >{{ label }}</span>
          <div
            v-if="i < stepLabels.length - 1"
            class="flex-1 h-px transition-colors duration-300"
            :class="currentStep > i + 1 ? 'bg-emerald-400' : 'bg-border'"
          />
        </div>
      </div>
    </div>

    <!-- Main Content Area -->
    <div class="mx-auto w-full max-w-7xl">

      <!-- ═══════ STEP 1: CONNECT ═══════ -->
      <div v-if="currentStep === 1">
        <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <!-- Connection Form -->
          <Card class="lg:col-span-2 glass-card border border-border/50 rounded-3xl shadow-sm">
            <CardHeader class="pb-3">
              <CardTitle class="text-lg flex items-center gap-2">
                <iconify-icon icon="lucide:plug" class="h-5 w-5 text-violet-500" />
                Database Connection
              </CardTitle>
              <CardDescription>Enter your external database credentials</CardDescription>
            </CardHeader>
            <CardContent class="space-y-4">
              <!-- DB Type -->
              <div class="space-y-1.5">
                <label class="text-sm font-medium">Database Type</label>
                <Select v-model="dbType">
                  <SelectTrigger class="rounded-xl">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="mysql">MySQL</SelectItem>
                    <SelectItem value="postgresql">PostgreSQL</SelectItem>
                    <SelectItem value="mongodb">MongoDB</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div class="grid grid-cols-3 gap-3">
                <div class="col-span-2 space-y-1.5">
                  <label class="text-sm font-medium">Host</label>
                  <Input v-model="host" placeholder="localhost" class="rounded-xl" />
                </div>
                <div class="space-y-1.5">
                  <label class="text-sm font-medium">Port</label>
                  <Input v-model.number="port" type="number" class="rounded-xl" />
                </div>
              </div>

              <div class="grid grid-cols-2 gap-3">
                <div class="space-y-1.5">
                  <label class="text-sm font-medium">Username</label>
                  <Input v-model="username" placeholder="root" class="rounded-xl" />
                </div>
                <div class="space-y-1.5">
                  <label class="text-sm font-medium">Password</label>
                  <Input v-model="password" type="password" placeholder="••••••" class="rounded-xl" />
                </div>
              </div>

              <div class="space-y-1.5">
                <label class="text-sm font-medium">Database Name</label>
                <Input v-model="database" placeholder="my_database" class="rounded-xl" />
              </div>

              <!-- MongoDB auth source -->
              <div v-if="dbType === 'mongodb'" class="space-y-1.5">
                <label class="text-sm font-medium">Auth Source</label>
                <Input v-model="authSource" placeholder="admin" class="rounded-xl" />
              </div>

              <div class="space-y-1.5">
                <label class="text-sm font-medium text-muted-foreground">Connection Name (optional)</label>
                <Input v-model="connectionName" placeholder="My Production DB" class="rounded-xl" />
              </div>

              <Button
                class="w-full rounded-xl mt-2"
                :disabled="!canConnect || isConnecting"
                @click="handleConnect"
              >
                <iconify-icon
                  :icon="isConnecting ? 'lucide:loader-2' : 'lucide:zap'"
                  :class="['h-4 w-4 mr-2', isConnecting && 'animate-spin']"
                />
                {{ isConnecting ? 'Connecting...' : 'Connect & Discover Tables' }}
              </Button>
            </CardContent>
          </Card>

          <!-- Saved Connections -->
          <Card class="glass-card border border-border/50 rounded-3xl shadow-sm">
            <CardHeader class="pb-3">
              <CardTitle class="text-sm flex items-center gap-2">
                <iconify-icon icon="lucide:history" class="h-4 w-4 text-amber-500" />
                Recent Connections
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div v-if="isLoadingConnections" class="text-center py-6">
                <iconify-icon icon="lucide:loader-2" class="h-5 w-5 text-muted-foreground animate-spin" />
              </div>
              <div v-else-if="savedConnections.length === 0" class="text-center py-6 text-xs text-muted-foreground">
                No saved connections yet
              </div>
              <div v-else class="space-y-2">
                <div
                  v-for="conn in savedConnections"
                  :key="conn.connection_id"
                  class="p-3 rounded-xl border border-border/40 hover:border-primary/30 hover:bg-muted/30 transition-all cursor-pointer group"
                  @click="useSavedConnection(conn)"
                >
                  <div class="flex items-center justify-between">
                    <div class="min-w-0 flex-1">
                      <p class="text-sm font-medium truncate">{{ conn.name }}</p>
                      <p class="text-xs text-muted-foreground mt-0.5">
                        <Badge variant="secondary" class="text-[10px] px-1.5 py-0 mr-1">{{ conn.db_type }}</Badge>
                        {{ conn.host }}:{{ conn.port }}
                      </p>
                    </div>
                    <button
                      class="opacity-0 group-hover:opacity-100 transition-opacity p-1 rounded-md hover:bg-destructive/10"
                      @click.stop="deleteSavedConnection(conn.connection_id)"
                      title="Delete connection"
                    >
                      <iconify-icon icon="lucide:trash-2" class="h-3.5 w-3.5 text-destructive" />
                    </button>
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>

      <!-- ═══════ STEP 2: PIPELINES ═══════ -->
      <div v-if="currentStep === 2">
        <Card class="glass-card border border-border/50 rounded-3xl shadow-sm mb-6">
          <CardHeader class="pb-3 text-center">
            <CardTitle class="text-2xl font-bold">Pipelines for {{ connectionName || host }}</CardTitle>
            <CardDescription>Select an existing pipeline to sync data, or create a wholly new pipeline.</CardDescription>
          </CardHeader>
          <CardContent>
            <div v-if="isLoadingPipelines" class="py-8 text-center text-muted-foreground flex flex-col items-center">
              <iconify-icon icon="lucide:loader-2" class="animate-spin h-8 w-8 mb-2" />
              <span>Loading pipelines...</span>
            </div>
            <div v-else-if="connectionPipelines.length === 0" class="py-8 text-center text-muted-foreground border border-dashed rounded-xl border-border/40">
              <iconify-icon icon="lucide:database-zap" class="h-10 w-10 mx-auto mb-2 opacity-50" />
              <p>No pipelines found for this connection.</p>
            </div>
            <div v-else class="space-y-6">
              <div v-for="job in connectionPipelines" :key="job.job_id" class="space-y-4">
                <div class="p-5 rounded-2xl border border-border/50 hover:border-primary/30 hover:bg-muted/10 transition-all flex items-center justify-between group">
                  <div class="flex items-start gap-4">
                    <div class="h-10 w-10 rounded-full bg-primary/10 text-primary flex items-center justify-center shrink-0">
                      <iconify-icon icon="lucide:git-commit" class="h-5 w-5" />
                    </div>
                    <div class="space-y-2">
                      <h4 class="font-semibold flex items-center gap-2">
                        {{ getPipelineName(job) }}
                        <button
                          class="opacity-0 group-hover:opacity-100 transition-opacity p-1 rounded-md hover:bg-primary/10"
                          title="Rename Pipeline"
                          @click.stop="openRenamePipeline(job)"
                        >
                          <iconify-icon icon="lucide:pencil" class="h-3.5 w-3.5 text-muted-foreground" />
                        </button>
                        <Badge v-if="(job as any).sync_mode_type" variant="secondary" class="text-[9px] uppercase tracking-tighter">
                          {{ (job as any).sync_mode_type === 'hwm' ? 'Timestamp' : 'Flag' }}
                        </Badge>
                        <Badge
                          :variant="job.status === 'complete' ? 'default' : job.status === 'failed' ? 'destructive' : 'secondary'"
                          class="text-[9px] uppercase tracking-tighter"
                        >
                          {{ job.status }}
                        </Badge>
                      </h4>
                      <div class="text-xs text-muted-foreground mt-1 space-y-1">
                        <div class="flex flex-wrap items-center gap-1.5">
                          <span>Destination Tables:</span>
                          <Badge
                            v-for="tableName in getDestinationTables(job)"
                            :key="`${job.job_id}-${tableName}`"
                            variant="outline"
                            class="font-mono text-[10px]"
                          >
                            {{ tableName }}
                          </Badge>
                          <span v-if="getDestinationTables(job).length === 0" class="font-mono text-foreground">N/A</span>
                        </div>
                        <div class="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px]">
                          <span>Sources: <span class="font-semibold text-foreground">{{ getSourceCount(job) }}</span></span>
                          <span>Destinations: <span class="font-semibold text-foreground">{{ getDestinationTables(job).length }}</span></span>
                          <span>Loaded Rows: <span class="font-semibold text-foreground">{{ getLoadedRows(job) }}</span></span>
                          <span>Last Sync: <span class="font-mono text-foreground">{{ getLastSyncTimestamp(job) }}</span></span>
                        </div>
                      </div>
                    </div>
                  </div>
                  
                  <div class="flex items-center gap-3">
                    <Button
                      variant="ghost"
                      size="icon"
                      class="h-9 w-9 rounded-xl hover:bg-primary/10 text-muted-foreground hover:text-primary"
                      @click="openSyncConfig(job)"
                      title="Configure Sync"
                    >
                      <iconify-icon icon="lucide:settings-2" class="h-4 w-4" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      class="h-9 w-9 rounded-xl hover:bg-primary/10 text-muted-foreground hover:text-primary"
                      @click="editPipeline(job.job_id)"
                      title="Edit Pipeline"
                    >
                      <iconify-icon icon="lucide:edit-3" class="h-4 w-4" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      class="h-9 w-9 rounded-xl hover:bg-destructive/10 text-muted-foreground hover:text-destructive"
                      @click="deletePipeline(job.job_id)"
                      title="Delete Pipeline"
                    >
                      <iconify-icon icon="lucide:trash-2" class="h-4 w-4" />
                    </Button>
                    
                    <Button 
                      size="sm" 
                      variant="default"
                      class="rounded-xl"
                      :disabled="isSyncingJob === job.job_id || !canDeltaSync(job)"
                      :title="deltaSyncBlockedReason(job)"
                      @click="syncPipeline(job.job_id)"
                    >
                      <iconify-icon :icon="isSyncingJob === job.job_id ? 'lucide:loader-2' : 'lucide:refresh-cw'" 
                          :class="['h-4 w-4 mr-2', isSyncingJob === job.job_id && 'animate-spin']" />
                      {{ isSyncingJob === job.job_id ? 'Syncing...' : 'Delta Sync' }}
                    </Button>
                  </div>
                </div>

                <!-- Expanded Sync Config (Stable UI) -->
                <div v-if="syncConfigEditingJobId === job.job_id" class="p-5 rounded-2xl bg-muted/30 border border-border/40 animate-in slide-in-from-top-2 duration-300 space-y-4">
                  <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                    <div class="flex items-center gap-3">
                      <span class="text-xs font-semibold">Sync Mode:</span>
                      <div class="inline-flex rounded-lg bg-background p-1 border border-border/50">
                        <button
                          v-for="mode in ['hwm', 'flag']"
                          :key="mode"
                          class="px-3 py-1.5 text-[10px] rounded-md font-bold uppercase transition-all"
                          :class="syncConfigModeType === mode ? 'bg-primary text-primary-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'"
                          @click="syncConfigModeType = mode"
                        >{{ mode === 'hwm' ? 'Timestamp' : 'Flag-Based' }}</button>
                      </div>
                    </div>
                    
                    <div v-if="syncConfigModeType === 'hwm'" class="flex items-center gap-3 flex-1 max-w-sm">
                      <label class="text-xs font-semibold">Column:</label>
                      <Input v-model="syncConfigColumn" placeholder="e.g. updated_at" class="h-9 text-xs font-mono rounded-lg" />
                    </div>
                  </div>

                  <div class="flex items-center justify-end gap-2 pt-2 border-t border-border/20">
                    <Button variant="ghost" size="sm" class="text-xs h-8 px-4 rounded-lg" @click="closeSyncConfig()">Cancel</Button>
                    <Button size="sm" class="text-xs h-8 px-4 rounded-lg" @click="saveSyncConfig(job.job_id)">
                      Save Configuration
                    </Button>
                  </div>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
        
        <div class="flex justify-between items-center max-w-2xl mx-auto">
          <Button variant="outline" class="rounded-xl px-6" @click="currentStep = 1">
             <iconify-icon icon="lucide:arrow-left" class="mr-2" /> Back
          </Button>
          <Button variant="default" class="rounded-xl px-6 bg-emerald-600 hover:bg-emerald-700 text-white" @click="currentStep = 3">
              Create New Pipeline <iconify-icon icon="lucide:plus" class="ml-2" />
          </Button>
        </div>

        <Dialog v-model:open="isPreviewSyncOpen">
          <DialogContent class="sm:max-w-4xl rounded-3xl">
            <DialogHeader>
              <DialogTitle class="text-xl font-bold">Review New Delta Rows</DialogTitle>
              <DialogDescription>
                Found <span class="font-semibold text-foreground">{{ previewSyncRows }}</span> new rows ready to append. Review samples below, then continue.
              </DialogDescription>
            </DialogHeader>

            <div class="max-h-[60vh] overflow-y-auto space-y-4 pr-1">
              <div v-for="t in previewSyncTables" :key="t.table_name" class="rounded-2xl border border-border/50 bg-muted/20 p-4">
                <div class="flex items-center justify-between mb-3">
                  <h5 class="font-semibold text-sm">{{ t.table_name }}</h5>
                  <Badge variant="secondary" class="text-[10px]">{{ t.row_count }} rows</Badge>
                </div>
                <div class="overflow-x-auto rounded-xl border border-border/40">
                  <table class="w-full text-xs">
                    <thead class="bg-background/80">
                      <tr>
                        <th v-for="c in (t.columns || [])" :key="c" class="text-left px-2 py-2 font-semibold">{{ c }}</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr v-for="(r, ridx) in (t.preview || [])" :key="ridx" class="border-t border-border/30">
                        <td v-for="c in (t.columns || [])" :key="c" class="px-2 py-1.5 whitespace-nowrap">
                          {{ r[c] }}
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </div>
            </div>

            <DialogFooter class="gap-2">
              <Button variant="outline" @click="isPreviewSyncOpen = false" :disabled="isConfirmingPreviewSync">Cancel</Button>
              <Button class="bg-emerald-600 hover:bg-emerald-700" @click="continuePreviewSync" :disabled="isConfirmingPreviewSync">
                <iconify-icon :icon="isConfirmingPreviewSync ? 'lucide:loader-2' : 'lucide:check-circle-2'" :class="['mr-2 h-4 w-4', isConfirmingPreviewSync && 'animate-spin']" />
                {{ isConfirmingPreviewSync ? 'Appending...' : 'Continue & Append New Rows' }}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>

        <Dialog :open="!!renamingPipelineJobId" @update:open="(open) => { if (!open) closeRenamePipeline() }">
          <DialogContent class="sm:max-w-md rounded-2xl">
            <DialogHeader>
              <DialogTitle>Rename Pipeline</DialogTitle>
              <DialogDescription>Update the pipeline label shown in this list.</DialogDescription>
            </DialogHeader>
            <div class="space-y-2">
              <label class="text-sm font-medium">Pipeline Name</label>
              <Input
                v-model="renamePipelineValue"
                class="rounded-xl"
                placeholder="Enter pipeline name"
                @keydown.enter="savePipelineName"
              />
            </div>
            <DialogFooter>
              <Button variant="outline" class="rounded-xl" @click="closeRenamePipeline">Cancel</Button>
              <Button class="rounded-xl" :disabled="isSavingPipelineName" @click="savePipelineName">
                <iconify-icon
                  :icon="isSavingPipelineName ? 'lucide:loader-2' : 'lucide:save'"
                  :class="['h-4 w-4 mr-2', isSavingPipelineName && 'animate-spin']"
                />
                {{ isSavingPipelineName ? 'Saving...' : 'Save Name' }}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>

      <!-- ═══════ STEP 3: SELECT TABLES ═══════ -->
      <div v-if="currentStep === 3">
        
        <!-- Beautiful Toggle -->
        <div class="flex flex-col items-center justify-center mb-8">
          <div class="inline-flex items-center justify-center rounded-2xl bg-muted/80 p-1.5 shadow-inner border border-border/50 backdrop-blur-sm">
            <button
              type="button"
              class="inline-flex items-center justify-center whitespace-nowrap rounded-xl px-8 py-3 text-sm font-semibold transition-all duration-300"
              :class="extractMode === 'tables' ? 'bg-background text-foreground shadow-md ring-1 ring-border/50' : 'text-muted-foreground hover:text-foreground hover:bg-background/40'"
              @click="extractMode = 'tables'"
            >
              <iconify-icon icon="lucide:check-square" class="mr-2.5 h-4 w-4" />
              Select Tables
            </button>
            <button
              type="button"
              class="inline-flex items-center justify-center whitespace-nowrap rounded-xl px-8 py-3 text-sm font-semibold transition-all duration-300"
              :class="extractMode === 'custom_query' ? 'bg-background text-foreground shadow-md ring-1 ring-border/50' : 'text-muted-foreground hover:text-foreground hover:bg-background/40'"
              @click="extractMode = 'custom_query'"
            >
              <iconify-icon icon="lucide:square-terminal" class="mr-2.5 h-4 w-4" />
              Write Custom Query
            </button>
          </div>
          <p class="text-xs text-muted-foreground mt-4" v-if="extractMode === 'custom_query'">
            Your selected tables and schema dictionary are still available on the left for reference.
          </p>
        </div>

        <div
          class="grid grid-cols-1 gap-6"
          :class="extractMode === 'tables' ? 'xl:grid-cols-2 lg:grid-cols-2' : 'xl:grid-cols-12'"
        >
          <!-- Left side containing Tables and Schema -->
          <div
            class="flex flex-col gap-6"
            :class="extractMode === 'tables' ? 'lg:contents' : 'xl:col-span-4'"
          >
            <!-- Table Browser -->
            <Card
              class="glass-card border border-border/50 rounded-3xl shadow-sm flex flex-col"
              :class="extractMode === 'custom_query' ? 'max-h-[500px]' : ''"
            >
            <CardHeader class="pb-3">
              <div class="flex items-center justify-between">
                <CardTitle class="text-lg flex items-center gap-2">
                  <iconify-icon icon="lucide:table-2" class="h-5 w-5 text-blue-500" />
                  Available Tables
                  <Badge variant="secondary" class="ml-1">{{ availableTables.length }}</Badge>
                </CardTitle>
                <Button
                  v-if="extractMode === 'tables'"
                  variant="ghost"
                  size="sm"
                  class="text-xs"
                  @click="selectAllTables"
                >
                  {{ selectedTables.length === availableTables.length ? 'Deselect All' : 'Select All' }}
                </Button>
              </div>
            </CardHeader>
            <CardContent>
              <div class="space-y-1.5 max-h-[500px] overflow-y-auto pr-1">
                <div
                  v-for="table in availableTables"
                  :key="table.name"
                  class="flex items-center gap-3 p-3 rounded-xl border transition-all cursor-pointer"
                  :class="
                    selectedTables.includes(table.name) && extractMode === 'tables'
                      ? 'border-primary bg-primary/10 shadow-sm ring-1 ring-primary/30'
                      : 'border-border/40 hover:border-primary/40 hover:bg-muted/30'
                  "
                  @click="toggleTable(table.name)"
                >
                  <div
                    class="w-5 h-5 rounded-md border-2 flex items-center justify-center shrink-0 transition-colors"
                    :class="
                      selectedTables.includes(table.name) && extractMode === 'tables'
                        ? 'bg-primary border-primary text-primary-foreground'
                        : 'border-muted-foreground/30 bg-background'
                    "
                  >
                    <iconify-icon v-if="selectedTables.includes(table.name) && extractMode === 'tables'" icon="lucide:check" class="h-3.5 w-3.5" />
                  </div>
                  <div class="flex-1 min-w-0">
                    <p class="text-sm font-semibold truncate">{{ table.name }}</p>
                    <p v-if="table.row_count !== undefined" class="text-xs text-muted-foreground">
                      {{ table.row_count?.toLocaleString() }} rows
                    </p>
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    class="text-xs shrink-0"
                    @click.stop="previewTable(table.name)"
                    title="Preview Data"
                  >
                    <iconify-icon icon="lucide:eye" class="h-4 w-4" />
                  </Button>
                </div>
              </div>
            </CardContent>
          </Card>

          <!-- Schema + Preview -->
          <Card class="glass-card border border-border/50 rounded-3xl shadow-sm flex flex-col">
            <CardHeader class="pb-3">
              <CardTitle class="text-lg flex items-center gap-2">
                <iconify-icon icon="lucide:scan-text" class="h-5 w-5 text-emerald-500" />
                Schema & Preview
                <span v-if="previewingTable" class="text-sm font-normal text-muted-foreground">— {{ previewingTable }}</span>
              </CardTitle>
            </CardHeader>
            <CardContent class="space-y-4">
              <div class="rounded-xl border border-border/60 p-3 bg-muted/20">
                <p class="text-xs font-semibold mb-2">Columns</p>
                <div v-if="activePreviewTable?.columns?.length" class="max-h-[120px] overflow-y-auto space-y-1 pr-1">
                  <div
                    v-for="col in activePreviewTable.columns"
                    :key="col.name"
                    class="flex items-center justify-between text-xs rounded-md px-2 py-1 bg-background border border-border/50"
                  >
                    <span class="font-medium truncate mr-2">{{ col.name }}</span>
                    <span class="text-muted-foreground truncate">{{ col.type }}</span>
                  </div>
                </div>
                <p v-else class="text-xs text-muted-foreground">Preview a table to inspect columns.</p>
              </div>

              <div v-if="isLoadingPreview" class="flex justify-center py-8">
                <iconify-icon icon="lucide:loader-2" class="h-6 w-6 animate-spin text-muted-foreground" />
              </div>
              <div v-else-if="!previewData" class="text-center py-8 text-sm text-muted-foreground">
                <iconify-icon icon="lucide:mouse-pointer-click" class="h-8 w-8 mx-auto mb-3 opacity-40" />
                <p>Click the eye icon on a table to preview rows</p>
              </div>
              <div v-else class="overflow-auto max-h-[300px] rounded-lg border">
                <table class="w-full text-xs">
                  <thead class="bg-muted sticky top-0">
                    <tr>
                      <th
                        v-for="col in previewData.columns"
                        :key="col"
                        class="text-left px-3 py-2 font-semibold text-muted-foreground whitespace-nowrap"
                      >{{ col }}</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr
                      v-for="(row, i) in previewData.rows"
                      :key="i"
                      class="border-t hover:bg-muted/30"
                    >
                      <td
                        v-for="col in previewData.columns"
                        :key="col"
                        class="px-3 py-1.5 whitespace-nowrap max-w-[200px] truncate"
                      >{{ row[col] ?? '—' }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>
          </div> <!-- End Left Side -->

          <!-- Right side: Custom SQL Editor -->
          <div v-if="extractMode === 'custom_query'" class="xl:col-span-8 flex flex-col h-full min-h-[600px]">
            <Card class="glass-card border border-border/50 rounded-3xl shadow-sm flex-1 flex flex-col items-stretch overflow-hidden">
              <CardHeader class="pb-3 border-b border-border/10 bg-muted/5">
                <div class="flex items-center justify-between">
                  <CardTitle class="text-lg flex items-center gap-2">
                    <iconify-icon icon="lucide:square-terminal" class="h-5 w-5 text-amber-500" />
                    Custom Query Editor
                  </CardTitle>
                  <Button variant="default" size="sm" class="rounded-xl shadow-sm" @click="addCustomDataset">
                    <iconify-icon icon="lucide:plus" class="h-4 w-4 mr-2" /> Add Another Query
                  </Button>
                </div>
                <p class="text-sm text-muted-foreground mt-1">Map each SQL query to an output dataset.</p>
              </CardHeader>
              
              <CardContent class="p-6 overflow-y-auto flex-1 flex flex-col gap-6">
                <div
                  v-for="(dataset, idx) in customDatasets"
                  :key="idx"
                  class="flex flex-col gap-4 rounded-3xl border border-border/70 p-5 bg-background shadow-sm"
                >
                  <div class="flex items-center justify-between">
                    <div class="flex items-center gap-3">
                      <div class="flex h-8 w-8 items-center justify-center rounded-full bg-amber-500/10 text-amber-600 font-bold text-xs ring-1 ring-amber-500/20">
                        {{ idx + 1 }}
                      </div>
                      <h3 class="font-semibold text-foreground">Dataset Configuration</h3>
                    </div>
                    <Button
                      variant="ghost"
                      size="sm"
                      class="h-8 px-3 text-destructive hover:bg-destructive/10 rounded-xl"
                      :disabled="customDatasets.length === 1"
                      @click="removeCustomDataset(idx)"
                    >
                      <iconify-icon icon="lucide:trash-2" class="h-4 w-4 mr-2" /> Remove
                    </Button>
                  </div>

                  <div class="space-y-2 max-w-md">
                    <label class="text-sm font-medium">Output Logical Name</label>
                    <Input
                      v-model="dataset.output_name"
                      placeholder="e.g., student_data"
                      class="rounded-xl border-border/60"
                    />
                    <p class="text-[11px] text-muted-foreground">This name will be used in your Transform script.</p>
                  </div>

                  <div class="space-y-2 flex-1">
                    <label class="text-sm font-medium flex items-center justify-between">
                      SQL Query
                      <span class="text-[11px] text-muted-foreground font-normal">SELECT queries only</span>
                    </label>
                    <div class="relative overflow-hidden rounded-2xl border border-border/60 bg-[#0f172a] shadow-inner">
                      <div class="flex items-center justify-between px-4 py-2 bg-[#111827] border-b border-[#1f2937]">
                        <div class="flex gap-1.5">
                          <div class="w-2.5 h-2.5 rounded-full bg-slate-600" />
                          <div class="w-2.5 h-2.5 rounded-full bg-slate-600" />
                          <div class="w-2.5 h-2.5 rounded-full bg-slate-600" />
                        </div>
                        <span class="text-xs text-slate-400 ml-2 flex-1 font-mono">query_{{ idx + 1 }}.sql</span>
                        <Badge variant="outline" class="text-[10px] text-amber-500 border-amber-500/30 bg-amber-500/10">SQL</Badge>
                      </div>
                      <Codemirror
                        v-model="dataset.custom_query"
                        :style="{ height: customDatasets.length > 1 ? '250px' : '400px' }"
                        :autofocus="idx === 0"
                        :indent-with-tab="true"
                        :tab-size="2"
                        :extensions="[sql(), oneDark]"
                        class="text-[14px] text-left"
                      />
                    </div>
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>
        </div>

        <!-- Navigation -->
        <div class="flex justify-between mt-6">
          <Button variant="outline" class="rounded-xl" @click="goBack">
            <iconify-icon icon="lucide:arrow-left" class="h-4 w-4 mr-2" /> Back
          </Button>
          <Button class="rounded-xl" :disabled="!canProceedToTransform" @click="goNext">
            Continue to Transform
            <iconify-icon icon="lucide:arrow-right" class="h-4 w-4 ml-2" />
          </Button>
        </div>
      </div>

      <!-- ═══════ STEP 4: TRANSFORM ═══════ -->
      <div v-if="currentStep === 4">
        <Card class="glass-card border border-border/50 rounded-3xl shadow-sm">
          <CardHeader class="pb-3">
            <CardTitle class="text-lg flex items-center gap-2">
              <iconify-icon icon="lucide:code-2" class="h-5 w-5 text-orange-500" />
              Transform Script
            </CardTitle>
            <CardDescription>
              Write a Python function that processes your data. Selected tables:
              <span class="font-semibold">{{ selectedExtractLabels.join(', ') }}</span>
            </CardDescription>
          </CardHeader>
          <CardContent class="space-y-4">
            <!-- AI Script Generator & Code Editor -->
            <div class="mb-4 flex items-center gap-2 rounded-2xl border border-indigo-100 bg-indigo-50/50 p-4 dark:border-indigo-900 dark:bg-indigo-950/20">
              <div class="flex-1">
                <div class="flex items-center gap-2 text-indigo-700 dark:text-indigo-400 mb-2">
                  <iconify-icon icon="lucide:sparkles" />
                  <span class="text-sm font-semibold text-indigo-600 dark:text-indigo-400">AI Script Generator</span>
                </div>
                <div class="flex gap-2">
                  <Input v-model="aiPrompt" placeholder="Describe the transformation logic you need..." class="bg-white dark:bg-black/40 border-indigo-200 dark:border-indigo-800 flex-1 min-w-[300px]" @keyup.enter="generateTransformAI" />
                  <Button :disabled="isGeneratingAI || !aiPrompt" @click="generateTransformAI" class="bg-indigo-600 hover:bg-indigo-700 text-white min-w-[120px]">
                    <iconify-icon v-if="isGeneratingAI" icon="lucide:loader-2" class="h-4 w-4 mr-2 animate-spin" />
                    <iconify-icon v-else icon="lucide:wand-2" class="h-4 w-4 mr-2" />
                    Generate
                  </Button>
                </div>
              </div>
            </div>

            <div class="relative overflow-hidden rounded-2xl border border-border/50 bg-[#1e1e2e]">
              <div class="flex items-center justify-between px-4 py-2 bg-[#181825] border-b border-[#313244]">
                <div class="flex items-center gap-2">
                  <div class="flex gap-1.5">
                    <div class="w-3 h-3 rounded-full bg-red-500/80" />
                    <div class="w-3 h-3 rounded-full bg-yellow-500/80" />
                    <div class="w-3 h-3 rounded-full bg-green-500/80" />
                  </div>
                  <span class="text-xs text-gray-400 ml-2">transform.py</span>
                </div>
                <Badge variant="secondary" class="text-[10px]">Python</Badge>
              </div>
              
              <!-- Vue-Codemirror replacement -->
              <Codemirror
                v-model="transformScript"
                :style="{ height: '350px' }"
                :autofocus="true"
                :indent-with-tab="true"
                :tab-size="4"
                :extensions="[python(), oneDark]"
                class="text-[13px] text-left"
              />
            </div>

            <!-- Dry Run Button -->
            <div class="flex items-center gap-3">
              <Button
                variant="outline"
                    class="rounded-2xl"
                :disabled="isDryRunning"
                @click="handleDryRun"
              >
                <iconify-icon
                  :icon="isDryRunning ? 'lucide:loader-2' : 'lucide:flask-conical'"
                  :class="['h-4 w-4 mr-2', isDryRunning && 'animate-spin']"
                />
                {{ isDryRunning ? 'Running...' : 'Test (100 rows)' }}
              </Button>
              <Button
                variant="ghost"
                  class="rounded-2xl"
                @click="skipTransformAndContinue"
              >
                <iconify-icon icon="lucide:fast-forward" class="h-4 w-4 mr-2" />
                Skip to Load
              </Button>
              <span class="text-xs text-muted-foreground">Preview your transform on a small sample before full execution</span>
            </div>

            <!-- Dry Run Result -->
            <div v-if="dryRunResult">
              <Separator class="my-3" />
              <!-- Success -->
              <div v-if="dryRunResult.success" class="space-y-3">
                <div class="flex items-center gap-2">
                  <iconify-icon icon="lucide:check-circle" class="h-5 w-5 text-emerald-500" />
                  <span class="text-sm font-semibold text-emerald-600 dark:text-emerald-400">Dry-run succeeded</span>
                  <Badge variant="secondary" class="text-xs">{{ dryRunResult.duration_seconds.toFixed(1) }}s</Badge>
                </div>
                <div v-if="dryRunResult.output_tables?.length" class="space-y-3">
                  <div
                    v-for="table in dryRunResult.output_tables"
                    :key="table.name"
                    class="overflow-hidden rounded-2xl border border-emerald-200 dark:border-emerald-800/50"
                  >
                    <div class="px-4 py-2 bg-emerald-50 dark:bg-emerald-950/30 flex items-center gap-2">
                      <iconify-icon icon="lucide:table-2" class="h-4 w-4 text-emerald-600 dark:text-emerald-400" />
                      <span class="text-sm font-medium">{{ table.name }}</span>
                      <Badge variant="secondary" class="text-xs ml-auto">{{ table.row_count }} rows · {{ table.columns.length }} cols</Badge>
                    </div>
                    <div class="overflow-auto max-h-[200px]">
                      <table class="w-full text-xs">
                        <thead class="bg-muted sticky top-0">
                          <tr>
                            <th
                              v-for="col in table.columns"
                              :key="col"
                              class="text-left px-3 py-1.5 font-semibold text-muted-foreground whitespace-nowrap"
                            >{{ col }}</th>
                          </tr>
                        </thead>
                        <tbody>
                          <tr
                            v-for="(row, i) in (table.preview || []).slice(0, 10)"
                            :key="i"
                            class="border-t hover:bg-muted/30"
                          >
                            <td
                              v-for="col in table.columns"
                              :key="col"
                              class="px-3 py-1 whitespace-nowrap max-w-[180px] truncate"
                            >{{ row[col] ?? '—' }}</td>
                          </tr>
                        </tbody>
                      </table>
                    </div>
                  </div>
                </div>
              </div>
              <!-- Error -->
              <div v-else class="rounded-2xl border border-destructive/20 bg-destructive/5 p-4">
                <div class="flex items-start gap-3">
                  <iconify-icon icon="lucide:x-circle" class="h-5 w-5 text-destructive shrink-0 mt-0.5" />
                  <div>
                    <p class="text-sm font-semibold text-destructive">Transform Error</p>
                    <pre class="text-xs text-muted-foreground mt-2 whitespace-pre-wrap font-mono max-h-[200px] overflow-auto">{{ dryRunResult.error }}</pre>
                  </div>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>

        <!-- Navigation -->
        <div class="flex justify-between mt-6">
          <Button variant="outline" class="rounded-xl" @click="goBack">
            <iconify-icon icon="lucide:arrow-left" class="h-4 w-4 mr-2" /> Back
          </Button>
          <Button class="rounded-xl" @click="goNext">
            Continue to Execute
            <iconify-icon icon="lucide:arrow-right" class="h-4 w-4 ml-2" />
          </Button>
        </div>
      </div>

      <!-- ═══════ STEP 5: EXECUTE ═══════ -->
      <div v-if="currentStep === 5">
        <Card class="glass-card border border-border/50 rounded-3xl shadow-sm">
          <CardHeader class="pb-3">
            <CardTitle class="text-lg flex items-center gap-2">
              <iconify-icon icon="lucide:rocket" class="h-5 w-5 text-purple-500" />
              Execute Full Pipeline
            </CardTitle>
            <CardDescription>Review and run the complete ETL pipeline</CardDescription>
          </CardHeader>
          <CardContent class="space-y-5">
            <!-- Summary -->
            <div class="grid grid-cols-1 sm:grid-cols-3 gap-4">
              <div class="rounded-2xl border border-border/40 bg-muted/20 p-4">
                <div class="flex items-center gap-2 mb-2">
                  <iconify-icon icon="lucide:database" class="h-4 w-4 text-violet-500" />
                  <span class="text-xs font-medium text-muted-foreground">Source</span>
                </div>
                <p class="text-sm font-semibold">{{ dbType.toUpperCase() }}</p>
                <p class="text-xs text-muted-foreground">{{ host }}:{{ port }}/{{ database }}</p>
              </div>
              <div class="rounded-2xl border border-border/40 bg-muted/20 p-4">
                <div class="flex items-center gap-2 mb-2">
                  <iconify-icon icon="lucide:table-2" class="h-4 w-4 text-blue-500" />
                  <span class="text-xs font-medium text-muted-foreground">Tables</span>
                </div>
                <p class="text-sm font-semibold">{{ selectedExtractLabels.length }} dataset(s)</p>
                <p class="text-xs text-muted-foreground truncate">{{ selectedExtractLabels.join(', ') }}</p>
              </div>
              <div class="rounded-2xl border border-border/40 bg-muted/20 p-4">
                <div class="flex items-center gap-2 mb-2">
                  <iconify-icon icon="lucide:code-2" class="h-4 w-4 text-orange-500" />
                  <span class="text-xs font-medium text-muted-foreground">Transform</span>
                </div>
                <p class="text-sm font-semibold">Custom Script</p>
                <p class="text-xs text-muted-foreground">{{ transformScript.split('\n').length }} lines</p>
              </div>
            </div>

            <div class="space-y-1.5">
              <label class="text-sm font-medium">Pipeline Name</label>
              <Input
                v-model="pipelineName"
                class="rounded-xl"
                placeholder="Sales ingestion pipeline"
              />
              <p class="text-xs text-muted-foreground">
                Leave blank to auto-name from the selected tables or datasets.
              </p>
            </div>

            <div class="space-y-1.5">
              <label class="text-sm font-medium">Sync Mode (How should data be loaded?)</label>
              <div class="flex gap-4 mt-1">
                <label class="flex items-center gap-2 cursor-pointer">
                  <input type="radio" v-model="syncMode" value="append" class="text-indigo-600" />
                  <span class="text-sm">Append / Upsert (Delta Sync)</span>
                </label>
                <label class="flex items-center gap-2 cursor-pointer">
                  <input type="radio" v-model="syncMode" value="overwrite" class="text-indigo-600" />
                  <span class="text-sm">Overwrite (Drops Target Table)</span>
                </label>
              </div>
            </div>

            <div class="space-y-1.5">
              <label class="text-sm font-medium">Primary Keys (for UPSERT Delta Sync)</label>
              <Input
                v-model="primaryKeysStr"
                class="rounded-xl"
                placeholder="id, tenant_id (optional)"
              />
              <p class="text-xs text-muted-foreground">
                Comma-separated column names. If provided, incremental updates will UPSERT instead of inserting duplicates.
              </p>
            </div>

            <!-- Execute Button (before job starts) -->
            <div v-if="!jobId" class="flex flex-col items-center gap-3 py-4">
              <div class="flex items-center gap-4">
                <Button
                  v-if="editingJobId"
                  variant="outline"
                  size="lg"
                  class="rounded-xl px-8 border-amber-500/50 text-amber-600 hover:bg-amber-50"
                  @click="handleSaveConfigOnly"
                >
                  Save Config Only
                </Button>
                <Button
                  size="lg"
                  class="rounded-xl px-8"
                  :disabled="isExecuting"
                  @click="handleExecute"
                >
                  <iconify-icon
                    :icon="isExecuting ? 'lucide:loader-2' : 'lucide:play'"
                    :class="['h-5 w-5 mr-2', isExecuting && 'animate-spin']"
                  />
                  {{ isExecuting ? 'Starting...' : 'Run Full Pipeline' }}
                </Button>
              </div>
              <p class="text-xs text-muted-foreground">Extract → Transform → Load to PostgreSQL</p>
            </div>

            <!-- Job Progress -->
            <div v-if="jobStatus" class="space-y-4">
              <Separator />
              <div class="flex items-center gap-3">
                <div
                  class="flex h-10 w-10 items-center justify-center rounded-2xl"
                  :class="[
                    jobStatus.status === 'complete' ? 'bg-emerald-100 dark:bg-emerald-900/30' :
                    jobStatus.status === 'failed' ? 'bg-destructive/10' :
                    'bg-primary/10'
                  ]"
                >
                  <iconify-icon
                    :icon="
                      jobStatus.status === 'complete' ? 'lucide:check-circle' :
                      jobStatus.status === 'failed' ? 'lucide:x-circle' :
                      'lucide:loader-2'
                    "
                    :class="[
                      'h-5 w-5',
                      jobStatus.status === 'complete' ? 'text-emerald-600 dark:text-emerald-400' :
                      jobStatus.status === 'failed' ? 'text-destructive' :
                      'text-primary animate-spin'
                    ]"
                  />
                </div>
                <div>
                  <p class="text-sm font-semibold capitalize">{{ jobStatus.status }}</p>
                  <p class="text-xs text-muted-foreground">Job {{ jobId.slice(0, 8) }}…</p>
                </div>
              </div>

              <!-- Stage Progress Bar -->
              <div class="flex items-center gap-1">
                <div v-for="stage in ['extracting', 'transforming', 'loading', 'complete']" :key="stage"
                  class="flex-1 h-2 rounded-full transition-all duration-500"
                  :class="[
                    ['extracting','transforming','loading','complete'].indexOf(jobStatus.status) >= ['extracting','transforming','loading','complete'].indexOf(stage)
                      ? 'bg-primary'
                      : 'bg-muted'
                  ]"
                />
              </div>
              <div class="flex justify-between text-[10px] text-muted-foreground">
                <span>Extract</span>
                <span>Transform</span>
                <span>Load</span>
                <span>Done</span>
              </div>

              <!-- Error -->
              <div v-if="jobStatus.status === 'failed' && jobStatus.error_message"
                class="mt-3 rounded-2xl border border-destructive/20 bg-destructive/5 p-4">
                <pre class="text-xs text-destructive whitespace-pre-wrap font-mono">{{ jobStatus.error_message }}</pre>
              </div>

              <!-- Complete: output info -->
              <div v-if="jobStatus.status === 'complete' && jobStatus.output_tables?.length" class="space-y-3 mt-3">
                <p class="text-sm font-semibold text-emerald-600 dark:text-emerald-400">✅ Data loaded to PostgreSQL</p>
                <div v-for="t in jobStatus.output_tables" :key="t.table_name"
                  class="flex items-center gap-3 rounded-2xl border border-emerald-200 bg-emerald-50/50 p-3 dark:border-emerald-800/50 dark:bg-emerald-950/20">
                  <iconify-icon icon="lucide:table-2" class="h-4 w-4 text-emerald-600 dark:text-emerald-400 shrink-0" />
                  <div class="flex-1 min-w-0">
                    <p class="text-sm font-medium">{{ t.table_name }}</p>
                    <p class="text-xs text-muted-foreground">{{ t.row_count?.toLocaleString() }} rows · {{ t.columns?.length }} columns</p>
                  </div>
                </div>
                <p class="text-xs text-muted-foreground mt-2">
                  You can now chat with this data using the AI assistant. The SQL Agent will query your loaded tables directly.
                </p>
                <div v-if="jobStatus.output_tables?.length > 1 && route.query.workspace_id" class="mt-4 p-4 rounded-2xl border border-indigo-200 bg-indigo-50/50 dark:border-indigo-900 dark:bg-indigo-950/20">
                  <h4 class="text-sm font-semibold text-indigo-700 dark:text-indigo-400 mb-1 flex items-center gap-2">
                    <iconify-icon icon="lucide:network" class="h-4 w-4" />
                    Define Table Relationships <span class="text-xs font-normal text-indigo-400">(Optional)</span>
                  </h4>
                  <p class="text-xs text-indigo-600/80 dark:text-indigo-300 mb-3">Define how these tables relate (e.g. orders.customer_id → customers.id). This helps the AI write better JOIN queries for dashboards.</p>

                  <!-- Inline relationship rows -->
                  <div v-for="(rel, idx) in pendingRelationships" :key="idx"
                    class="grid grid-cols-[1fr_auto_1fr_auto_auto] items-center gap-2 mb-2">
                    <select v-model="rel.source" class="rounded-lg border px-2 py-1.5 text-xs bg-background">
                      <option value="" disabled>source_table.column</option>
                      <template v-for="t in jobStatus.output_tables" :key="t.table_name">
                        <option v-for="c in (t.columns || [])" :key="`${t.table_name}.${c}`" :value="`${t.table_name}.${c}`">
                          {{ t.table_name }}.{{ c }}
                        </option>
                      </template>
                    </select>
                    <span class="text-xs text-muted-foreground font-mono">→</span>
                    <select v-model="rel.target" class="rounded-lg border px-2 py-1.5 text-xs bg-background">
                      <option value="" disabled>target_table.column</option>
                      <template v-for="t in jobStatus.output_tables" :key="t.table_name">
                        <option v-for="c in (t.columns || [])" :key="`${t.table_name}.${c}`" :value="`${t.table_name}.${c}`">
                          {{ t.table_name }}.{{ c }}
                        </option>
                      </template>
                    </select>
                    <Badge variant="outline" class="text-[10px] shrink-0">FK</Badge>
                    <button @click="pendingRelationships.splice(idx, 1)" class="text-muted-foreground hover:text-destructive transition-colors">
                      <iconify-icon icon="lucide:x" class="h-3.5 w-3.5" />
                    </button>
                  </div>

                  <div class="flex items-center gap-2 mt-3">
                    <Button variant="outline" size="sm" class="rounded-lg text-xs" @click="pendingRelationships.push({ source: '', target: '' })">
                      <iconify-icon icon="lucide:plus" class="h-3 w-3 mr-1" /> Add Relationship
                    </Button>
                    <Button
                      v-if="pendingRelationships.some(r => r.source && r.target)"
                      size="sm" class="rounded-lg text-xs bg-indigo-600 hover:bg-indigo-700 text-white"
                      :disabled="isSavingRelationships"
                      @click="saveAllRelationships"
                    >
                      <iconify-icon :icon="isSavingRelationships ? 'lucide:loader-2' : 'lucide:save'" :class="['h-3 w-3 mr-1', isSavingRelationships && 'animate-spin']" />
                      Save Relationships
                    </Button>
                    <Button variant="ghost" size="sm" class="rounded-lg text-xs ml-auto" @click="$router.push(`/app/workspaces/${route.query.workspace_id}/catalog?tab=relationships`)">
                      <iconify-icon icon="lucide:external-link" class="h-3 w-3 mr-1" /> Open Catalog
                    </Button>
                  </div>
                  <p class="text-[10px] text-muted-foreground mt-2 italic">
                    Skip this step — the AI will automatically infer relationships from column names when generating dashboards.
                  </p>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>

        <!-- Navigation -->
        <div class="flex justify-between mt-6">
          <Button variant="outline" class="rounded-xl" @click="goBack" :disabled="isExecuting">
            <iconify-icon icon="lucide:arrow-left" class="h-4 w-4 mr-2" /> Back
          </Button>
          <Button v-if="jobStatus?.status === 'complete'" variant="outline" class="rounded-xl" @click="resetWizard">
            <iconify-icon icon="lucide:plus" class="h-4 w-4 mr-2" /> New Pipeline
          </Button>
        </div>
      </div>
    </div>
  </div>
</template>





