<script setup lang="ts">
import { ref, onMounted, computed, watch, nextTick } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import {
  HoverCard, HoverCardContent, HoverCardTrigger
} from '@/components/ui/hover-card'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle
} from '@/components/ui/dialog'
import ChatPage from '@/pages/chat/index.vue'
import ChangePasswordModal from '@/components/ChangePasswordModal.vue'
import excelFileAPI, { type FileInfo, type ChunkData, type UploadResponse, type SavedQuestion, type UploadRawResponse, type ExtractSheetRequest } from '@/services/excelApi'
import { toast } from 'vue-sonner'
import { useDocumentsStore } from '@/store/documents'
import { useBoards } from '@/store/boards'
import FileSystemNode from './FileSystemNode.vue'
import FilterPopover from './FilterPopover.vue'
import { buildFileTree, type TreeNode } from '@/utils/fileTree'

// --- Interfaces ---
interface PreviewData {
  columns: string[]
  data: Record<string, any>[]
  total_rows: number
  preview_rows: number
}

// --- Store ---
const store = useDocumentsStore()
const boardStore = useBoards()
const router = useRouter()
const route = useRoute()

// --- File tree ---
const folderFileTree = computed<TreeNode[]>(() =>
  buildFileTree(store.sortedFiles, store.regularFolders)
)

// Accordion state
const activeAccordion = ref<'folders' | 'dashboards' | ''>('folders')

// Inline new-folder creation at explorer root
const creatingRootFolder = ref(false)
const newRootFolderName = ref('')
const creatingDashboard = ref(false)
const newDashboardName = ref('')

async function handleCreateRootFolder() {
  const name = newRootFolderName.value.trim()
  if (!name) return
  await store.createProject(name, undefined, false)
  newRootFolderName.value = ''
  creatingRootFolder.value = false
}

async function handleCreateDashboard() {
  const name = newDashboardName.value.trim()
  if (!name) return
  const board = await boardStore.createBoard(name)
  newDashboardName.value = ''
  creatingDashboard.value = false
  router.push({ name: 'insight-board', params: { boardId: board.board_id } })
}

// --- Local Page State ---
const selectedFile = ref<FileInfo | null>(null)
const activePanel = ref<'settings' | 'chat'>('settings')
const chatPageRef = ref<InstanceType<typeof ChatPage> | null>(null)
const sidebarOpen = ref(true)

function toggleSidebar() {
  sidebarOpen.value = !sidebarOpen.value
}

function syncExplorerSectionToRoute(section: 'folders' | 'dashboards' | '') {
  const current = String(route.query.explorer || '')
  const next = section || ''
  if (current === next) return
  const nextQuery: Record<string, any> = { ...route.query }
  if (next) nextQuery.explorer = next
  else delete nextQuery.explorer
  router.replace({ query: nextQuery })
}

function applyExplorerSectionFromRoute() {
  const raw = String(route.query.explorer || '').trim().toLowerCase()
  if (raw === 'folders' || raw === 'dashboards') {
    activeAccordion.value = raw
    return
  }
  activeAccordion.value = 'folders'
}

function toggleExplorerSection(section: 'folders' | 'dashboards') {
  activeAccordion.value = activeAccordion.value === section ? '' : section
  if (activeAccordion.value !== 'folders') creatingRootFolder.value = false
  if (activeAccordion.value !== 'dashboards') creatingDashboard.value = false
  syncExplorerSectionToRoute(activeAccordion.value)
}

const explorerTitle = computed(() => {
  if (activeAccordion.value === 'folders') return 'Folders & Files'
  if (activeAccordion.value === 'dashboards') return 'Insight Boards'
  return 'Workspace'
})

const filteredBoards = computed(() => {
  const q = String(store.searchQuery || '').trim().toLowerCase()
  if (!q) return boardStore.boards
  return boardStore.boards.filter((board: any) => {
    const name = String(board?.name || '').toLowerCase()
    const id = String(board?.board_id || '').toLowerCase()
    return name.includes(q) || id.includes(q)
  })
})

function handlePrimaryCreateAction() {
  if (activeAccordion.value === 'dashboards') {
    creatingDashboard.value = true
    newDashboardName.value = ''
    return
  }
  triggerUpload(null, null)
}

// Upload State
const showUploadModal = ref(false)
const showChangePasswordModal = ref(false)
const isEmptyingTrash = ref(false)
const uploadProgress = ref(0)
const uploadStage = ref('')
const uploadMessage = ref('')
const isUploading = ref(false)
const uploadError = ref<string | null>(null)
const fileWaitingForProcess = ref<UploadResponse | null>(null)
const uploadProjectId = ref<string | null>(null)
const uploadSubprojectId = ref<string | null>(null)

// ── Sheet-picker state (multi-sheet Excel upload) ─────────────────────────
const showSheetPickerModal = ref(false)
const rawUploadResult = ref<UploadRawResponse | null>(null)
const selectedSheets = ref<string[]>([])
const isExtractingSheets = ref(false)
const extractResults = ref<{ sheet: string; done: boolean; error?: string }[]>([])
const addSheetGroupId = ref<string | null>(null)  // for “Add Sheet” flow on existing group
// Holds all extracted sheets for a batch questions dialog shown once after import
const pendingExtractedSheets = ref<UploadResponse[]>([])


// Auto-replay State
const showReplayDialog = ref(false)
const savedQuestions = ref<SavedQuestion[]>([])
const isReplaying = ref(false)

function normalizeQuestionCategory(category: string | null | undefined): string {
  const raw = String(category || '').trim()
  if (!raw) return 'Generic'
  if (raw.toLowerCase() === 'generic') return 'Generic'
  return raw
}

function normalizeSavedQuestions(questions: SavedQuestion[]): SavedQuestion[] {
  return (questions || []).map((q) => ({
    ...q,
    question_category: normalizeQuestionCategory(q.question_category),
  }))
}

// Category state for upload replay — derived from questions
const replayCategories = computed(() => {
  const catSet = new Set<string>()
  savedQuestions.value.forEach(q => catSet.add(q.question_category))
  return Array.from(catSet).sort()
})
const selectedCategories = ref<Set<string>>(new Set())
// Per-question selection: Set of selected question IDs
const selectedQuestionIds = ref<Set<number>>(new Set())
// Track which categories are expanded in the replay dialog
const replayExpandedCats = ref<Set<string>>(new Set())

function toggleReplayCatExpand(cat: string) {
  const s = new Set(replayExpandedCats.value)
  if (s.has(cat)) s.delete(cat)
  else s.add(cat)
  replayExpandedCats.value = s
}

function questionsForReplayCat(cat: string) {
  return savedQuestions.value.filter(q => q.question_category === cat)
}

function isCatPartiallySelected(catName: string): boolean {
  const qs = questionsForReplayCat(catName)
  const selectedCount = qs.filter(q => selectedQuestionIds.value.has(q.id)).length
  return selectedCount > 0 && selectedCount < qs.length
}

function toggleReplayQuestion(q: SavedQuestion) {
  const qIds = new Set(selectedQuestionIds.value)
  const catSet = new Set(selectedCategories.value)
  if (qIds.has(q.id)) {
    qIds.delete(q.id)
    // If no more questions in this category are selected, deselect category too
    const anyLeft = questionsForReplayCat(q.question_category).some(qq => qq.id !== q.id && qIds.has(qq.id))
    if (!anyLeft) catSet.delete(q.question_category)
  } else {
    qIds.add(q.id)
    catSet.add(q.question_category)
  }
  selectedQuestionIds.value = qIds
  selectedCategories.value = catSet
}


// Preview & Chunk State
const showPreviewModal = ref(false)
const previewData = ref<PreviewData | null>(null)
const showChunksModal = ref(false)
const chunksData = ref<ChunkData | null>(null)
const chunksPage = ref(1)
const chunksLimit = ref(50)
const isLoadingChunks = ref(false)

const stageConfig: Record<string, { icon: string; label: string }> = {
  uploading: { icon: 'lucide:upload', label: 'Uploading' },
  initializing: { icon: 'lucide:settings', label: 'Initializing' },
  reading: { icon: 'lucide:file-search', label: 'Reading File' },
  metadata: { icon: 'lucide:database', label: 'Analyzing Metadata' },
  embedding: { icon: 'lucide:brain', label: 'Creating Embeddings' },
  saving: { icon: 'lucide:save', label: 'Saving to Database' },
  complete: { icon: 'lucide:check-circle', label: 'Complete' },
  error: { icon: 'lucide:x-circle', label: 'Error' }
}

// --- Computed ---

const uploadAssignmentLabel = computed(() => {
  if (!uploadProjectId.value) return 'Root Directory'
  const project = store.projects.find(p => p.project_id === uploadProjectId.value)
  if (!project) return 'Root Directory'
  if (!uploadSubprojectId.value) return project.name
  const subproject = project.subprojects?.find(s => s.subproject_id === uploadSubprojectId.value)
  if (!subproject) return project.name
  return `${project.name} / ${subproject.name}`
})

const _skipProjectWatch = ref(false)

watch(uploadProjectId, (next, prev) => {
  if (_skipProjectWatch.value) {
    _skipProjectWatch.value = false
    return
  }
  if (next !== prev) {
    uploadSubprojectId.value = null
  }
})

// --- Methods ---

onMounted(async () => {
  await Promise.all([store.fetchAll(), boardStore.fetchBoards()])
  applyExplorerSectionFromRoute()
  // Auto-select file if navigated with ?fileId=
  const fileId = route.query.fileId as string | undefined
  if (fileId) {
    const file = store.sortedFiles.find(f => f.file_uuid === fileId)
    if (file) selectFile(file)
  }
})

watch(() => route.query.explorer, () => {
  applyExplorerSectionFromRoute()
})



function toggleViewMode(mode: 'active' | 'trash') {
  store.viewMode = mode
  selectedFile.value = null
}

function selectFile(file: FileInfo) {
  selectedFile.value = file
  activePanel.value = 'settings'
}

function formatDate(dateString?: string): string {
  if (!dateString) return 'N/A'
  try {
    return new Date(dateString).toLocaleDateString('en-US', {
      year: 'numeric', 
      month: 'short', 
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    })
  } catch {
    return 'Invalid Date'
  }
}

// --- Actions ---

async function confirmDeleteBoard(boardId: string) {
  if (confirm('Delete this insight board?')) await boardStore.deleteBoard(boardId)
}

async function softDeleteFile(file: FileInfo) {
  if (!confirm(`Are you sure you want to move "${file.filename}" to the Recycle Bin?`)) return
  try {
    await store.softDeleteFile(file.file_uuid)
    toast.success('Moved to trash', { description: file.filename })
    if (selectedFile.value?.file_uuid === file.file_uuid) {
      selectedFile.value = null
    }
  } catch (error) {
    console.error('Delete failed:', error)
    toast.error('Failed to move to trash')
  }
}

async function restoreFile(file: FileInfo) {
  try {
    await store.restoreFile(file.file_uuid)
    toast.success('Restored', { description: file.filename })
    if (selectedFile.value?.file_uuid === file.file_uuid) {
      selectedFile.value = null
    }
  } catch (error) {
    console.error('Restore failed:', error)
    toast.error('Failed to restore')
  }
}

async function permanentDeleteFile(file: FileInfo) {
  if (!confirm(`Permanently delete "${file.filename}"? This action cannot be undone.`)) return
  try {
    await store.permanentDeleteFile(file.file_uuid)
    toast.success('Permanently deleted', { description: file.filename })
    if (selectedFile.value?.file_uuid === file.file_uuid) {
      selectedFile.value = null
    }
  } catch (error) {
    console.error('Permanent delete failed:', error)
    toast.error('Failed to delete')
  }
}

async function handleTreeDelete(file: FileInfo) {
  if (store.viewMode === 'trash') {
    await permanentDeleteFile(file)
    return
  }
  await softDeleteFile(file)
}

async function emptyAllTrash() {
  const count = store.trashFiles.length
  if (!count) return
  if (!confirm(`Permanently delete all ${count} file(s) in trash? This cannot be undone.`)) return
  isEmptyingTrash.value = true
  try {
    const result = await excelFileAPI.emptyTrash()
    toast.success('Trash emptied', { description: result.message })
    selectedFile.value = null
    await store.fetchAll()
  } catch (error: any) {
    console.error('Empty trash failed:', error)
    toast.error('Failed to empty trash')
  } finally {
    isEmptyingTrash.value = false
  }
}

async function previewFile(file: FileInfo) {
  try {
    const preview = await excelFileAPI.previewFile(file.file_uuid, 10)
    previewData.value = {
      columns: preview.columns,
      data: preview.data,
      total_rows: preview.total_rows,
      preview_rows: preview.preview_rows
    }
    showPreviewModal.value = true
  } catch (error: any) {
    console.error('Preview failed:', error)
    toast.error('Preview failed')
  }
}

async function downloadData(file: FileInfo, format: 'json' | 'csv') {
  try {
    const response = await excelFileAPI.exportFile(file.file_uuid, format)
    
    const dataStr = typeof response.data === 'string' ? response.data : JSON.stringify(response.data, null, 2)
    const blob = new Blob([dataStr], { type: format === 'json' ? 'application/json' : 'text/csv' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `${file.filename.replace(/\.[^.]+$/, '')}.${format}`
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    URL.revokeObjectURL(url)
  } catch (error) {
    console.error('Download failed:', error)
    toast.error('Download failed')
  }
}

async function deleteFileCache(file: FileInfo) {
  if (!confirm(`Delete cached responses for "${file.filename}"? This will force fresh results.`)) return
  try {
    const response = await excelFileAPI.deleteFileCache(file.file_uuid)
    toast.success('File Cache Deleted', {
      description: `${file.filename} (${response.deleted} entries)`
    })
  } catch (error) {
    console.error('Cache delete failed:', error)
    toast.error('Failed to delete cache', {
      description: file.filename
    })
  }
}

// --- Chunk Viewer Methods ---
async function openChunksModal() {
  if (!selectedFile.value) return
  chunksPage.value = 1
  chunksLimit.value = 50 
  showChunksModal.value = true
  await loadChunks()
}

async function loadChunks() {
  if (!selectedFile.value) return
  isLoadingChunks.value = true
  try {
    chunksData.value = await excelFileAPI.getFileChunks(selectedFile.value.file_uuid, chunksPage.value, chunksLimit.value)
  } catch (error) {
    console.error('Failed to load chunks:', error)
    toast.error('Failed to load chunks')
  } finally {
    isLoadingChunks.value = false
  }
}

async function changeChunksPage(delta: number) {
  if (!chunksData.value) return
  const newPage = chunksPage.value + delta
  if (newPage < 1 || newPage > chunksData.value.total_pages) return
  chunksPage.value = newPage
  await loadChunks()
}

async function copyChunk(content: string) {
  try {
    await navigator.clipboard.writeText(content)
    toast.success('Chunk copied')
  } catch (err) {
    console.error('Failed to copy chunk:', err)
  }
}

// --- Upload Methods ---
function triggerUpload(preselectedProjectId?: string | null, preselectedSubprojectId?: string | null) {
  showUploadModal.value = true
  // Skip the watcher reset if we're setting both project and subproject
  if (preselectedProjectId && preselectedSubprojectId) {
    _skipProjectWatch.value = true
  }
  uploadProjectId.value = preselectedProjectId || null
  uploadSubprojectId.value = preselectedSubprojectId || null
  resetUploadForNewFile()
}

function triggerUploadToFolder(projectId: string | null, subprojectId: string | null) {
  triggerUpload(projectId, subprojectId)
}
function closeUploadModal() {
  showUploadModal.value = false
  resetUpload()
}

// Close modal UI only — preserves fileWaitingForProcess for replay
function closeUploadModalOnly() {
  showUploadModal.value = false
}
function resetUpload() {
  fileWaitingForProcess.value = null
  uploadError.value = null
  uploadProgress.value = 0
  uploadStage.value = ''
  uploadMessage.value = ''
  uploadProjectId.value = null
  uploadSubprojectId.value = null
}

function resetUploadForNewFile() {
  fileWaitingForProcess.value = null
  uploadError.value = null
  uploadProgress.value = 0
  uploadStage.value = ''
  uploadMessage.value = ''
  isUploading.value = false
}
function getCurrentStageConfig() { return stageConfig[uploadStage.value] || stageConfig.uploading }

function getColumnMeta(col: string) {
  const stats = selectedFile.value?.column_stats
  if (!stats?.columns) return null
  return stats.columns[col] || null
}

async function handleFileUpload(event: Event) {
  const input = event.target as HTMLInputElement
  if (!input.files?.length) return

  const file = input.files[0]
  const ext = file.name.split('.').pop()?.toLowerCase()

  // Excel files: detect single vs multi-sheet
  if (ext === 'xlsx' || ext === 'xls') {
    try {
      isUploading.value = true
      uploadStage.value = 'uploading'
      uploadMessage.value = 'Reading sheets…'
      uploadProgress.value = 30
      const raw = await excelFileAPI.uploadRaw(file)

      // Single-sheet Excel → treat as regular file (same as CSV path)
      if (raw.sheets.length <= 1) {
        uploadMessage.value = 'Processing file…'
        uploadProgress.value = 40
        const result = await excelFileAPI.uploadFileWithProgress(
          file,
          (stage, current, _total, message) => {
            uploadStage.value = stage
            uploadProgress.value = current
            uploadMessage.value = message
          },
          uploadProjectId.value,
          uploadSubprojectId.value
        )
        fileWaitingForProcess.value = result
        uploadProgress.value = 100
        uploadStage.value = 'complete'
        uploadMessage.value = 'Upload complete!'
        await store.fetchAll()
        input.value = ''
        closeUploadModalOnly()
        await nextTick()
        await checkForSavedQuestions(result.file_uuid)
        isUploading.value = false
        return
      }

      // Multi-sheet → show sheet picker
      rawUploadResult.value = raw
      selectedSheets.value = [...raw.sheets]  // pre-select all sheets
      extractResults.value = raw.sheets.map(s => ({ sheet: s, done: false }))
      addSheetGroupId.value = null
      input.value = ''
      isUploading.value = false
      uploadProgress.value = 0
      uploadMessage.value = ''
      showUploadModal.value = false
      showSheetPickerModal.value = true
    } catch (error) {
      console.error('Raw upload failed:', error)
      uploadError.value = String(error)
      uploadStage.value = 'error'
      isUploading.value = false
    }
    return
  }

  // Original CSV / single-sheet path
  try {
    uploadProgress.value = 0
    uploadStage.value = 'uploading'
    uploadMessage.value = 'Starting upload...'
    isUploading.value = true
    uploadError.value = null

    const result = await excelFileAPI.uploadFileWithProgress(
      file,
      (stage, current, _total, message) => {
        uploadStage.value = stage
        uploadProgress.value = current
        uploadMessage.value = message
      },
      uploadProjectId.value,
      uploadSubprojectId.value
    )

    fileWaitingForProcess.value = result
    uploadProgress.value = 100
    uploadStage.value = 'complete'
    uploadMessage.value = 'Upload complete!'

    await store.fetchAll()
    input.value = ''

    // Close the upload modal first, then check for saved questions
    closeUploadModalOnly()
    await nextTick()
    await checkForSavedQuestions(result.file_uuid)
  } catch (error) {
    console.error('Upload failed:', error)
    uploadError.value = String(error)
    uploadStage.value = 'error'
  }
  finally {
    isUploading.value = false
  }
}

// --- Auto-Replay Functions ---
async function triggerAddSheet(groupId: string) {
  addSheetGroupId.value = groupId

  // Inherit the project/subproject from an existing sheet in this group so the
  // new sheet lands in the same folder, not at the root directory.
  const existingSheet = store.files.find((f: FileInfo) => f.file_group_id === groupId)
  uploadProjectId.value = existingSheet?.project_id ?? null
  uploadSubprojectId.value = existingSheet?.subproject_id ?? null
  // Open a hidden file input that accepts only Excel files
  const inp = document.createElement('input')
  inp.type = 'file'
  inp.accept = '.xlsx,.xls'
  inp.onchange = async (e) => {
    const target = e.target as HTMLInputElement
    const file = target.files?.[0]
    if (!file) return
    try {
      isUploading.value = true
      uploadStage.value = 'uploading'
      uploadMessage.value = 'Reading sheets…'
      const raw = await excelFileAPI.uploadRaw(file)
      rawUploadResult.value = raw
      selectedSheets.value = [...raw.sheets]
      extractResults.value = raw.sheets.map(s => ({ sheet: s, done: false }))
      isUploading.value = false
      showSheetPickerModal.value = true
    } catch (err) {
      console.error('Add sheet upload error:', err)
      toast.error('Failed to read file')
      isUploading.value = false
    }
  }
  inp.click()
}

async function processSelectedSheets() {
  if (!rawUploadResult.value || selectedSheets.value.length === 0) return
  isExtractingSheets.value = true
  let groupId = addSheetGroupId.value
  const extracted: UploadResponse[] = []

  for (const sheet of selectedSheets.value) {
    const idx = extractResults.value.findIndex(r => r.sheet === sheet)
    try {
      const req: ExtractSheetRequest = {
        temp_id: rawUploadResult.value.temp_id,
        sheet_name: sheet,
        existing_group_id: groupId ?? undefined,
        project_id: uploadProjectId.value ?? undefined,
        subproject_id: uploadSubprojectId.value ?? undefined,
      }
      const res = await excelFileAPI.extractSheet(req)
      if (!groupId) groupId = res.group_id  // reuse group for subsequent sheets
      if (idx >= 0) extractResults.value[idx].done = true
      // Collect response in UploadResponse shape for the replay dialog
      extracted.push({
        status: 'success',
        message: '',
        file_uuid: res.file_uuid,
        filename: res.filename,
        table_name: res.table_name ?? '',
        rows: res.rows,
        columns: res.columns,
      })
    } catch (err) {
      console.error(`Failed to extract sheet '${sheet}':`, err)
      if (idx >= 0) extractResults.value[idx].error = String(err)
    }
  }

  isExtractingSheets.value = false
  await store.fetchAll()
  showSheetPickerModal.value = false
  rawUploadResult.value = null
  addSheetGroupId.value = null

  // Kick off the saved-questions dialog for all extracted sheets at once
  if (extracted.length > 0) {
    pendingExtractedSheets.value = extracted
    await checkSavedQuestionsForSheets()
  }
}

// --- Auto-Replay Functions ---

async function checkForSavedQuestions(fileUuid: string) {
  try {
    const questions = normalizeSavedQuestions(await excelFileAPI.listSavedQuestionsForFile(fileUuid))
    if (questions.length > 0) {
      savedQuestions.value = questions
      selectedCategories.value = new Set()
      selectedQuestionIds.value = new Set()
      replayExpandedCats.value = new Set()
      await nextTick()
      showReplayDialog.value = true
    } else {
      toast.success('File uploaded successfully', { description: 'You can now chat with your data.' })
    }
  } catch (e) {
    console.error('Failed to check saved questions:', e)
    toast.success('File uploaded successfully')
  }
}

async function checkSavedQuestionsForSheets() {
  const count = pendingExtractedSheets.value.length
  try {
    const unique = new Map<string, SavedQuestion>()
    for (const sheet of pendingExtractedSheets.value) {
      const scoped = normalizeSavedQuestions(await excelFileAPI.listSavedQuestionsForFile(sheet.file_uuid))
      for (const q of scoped) {
        const key = String(q.id || `${q.question_text}::${q.question_category}`).trim()
        if (!unique.has(key)) unique.set(key, q)
      }
    }
    const questions = Array.from(unique.values())

    if (questions.length > 0) {
      savedQuestions.value = questions
      selectedCategories.value = new Set()
      selectedQuestionIds.value = new Set()
      replayExpandedCats.value = new Set()
      await nextTick()
      showReplayDialog.value = true
    } else {
      pendingExtractedSheets.value = []
      toast.success(`${count} sheet(s) imported successfully`, { description: `You can now chat with your data.` })
    }
  } catch (e) {
    console.error('Failed to check saved questions for sheets:', e)
    pendingExtractedSheets.value = []
    toast.success(`${count} sheet(s) imported successfully`)
  }
}
const replayFilteredQuestions = () => {
  return savedQuestions.value.filter(q => selectedQuestionIds.value.has(q.id))
}

function toggleCategory(catName: string) {
  const newSet = new Set(selectedCategories.value)
  const qIds = new Set(selectedQuestionIds.value)
  const expanded = new Set(replayExpandedCats.value)
  if (newSet.has(catName) && !isCatPartiallySelected(catName)) {
    // Fully selected → deselect all & collapse
    newSet.delete(catName)
    questionsForReplayCat(catName).forEach(q => qIds.delete(q.id))
    expanded.delete(catName)
  } else {
    // Partially or not selected → select all & expand so user can fine-tune
    newSet.add(catName)
    questionsForReplayCat(catName).forEach(q => qIds.add(q.id))
    expanded.add(catName)
  }
  selectedCategories.value = newSet
  selectedQuestionIds.value = qIds
  replayExpandedCats.value = expanded
}

function categoryQuestionCount(catName: string) {
  return savedQuestions.value.filter(q => q.question_category === catName).length
}

async function runAutoReplay() {
  // ─ Multi-sheet batch replay ─
  if (pendingExtractedSheets.value.length > 0) {
    const questions = replayFilteredQuestions().map(q => q.question_text)
    if (questions.length === 0) {
      showReplayDialog.value = false
      pendingExtractedSheets.value = []
      return
    }
    isReplaying.value = true
    const count = pendingExtractedSheets.value.length
    try {
      for (const sheet of pendingExtractedSheets.value) {
        await excelFileAPI.batchQuery(sheet.file_uuid, questions)
      }
      showReplayDialog.value = false
      toast.success(`Questions applied to ${count} sheet(s)`)
    } catch (e: any) {
      console.error('Batch replay failed:', e)
      toast.error('Auto-replay failed. You can still chat with the files manually.')
      showReplayDialog.value = false
    } finally {
      isReplaying.value = false
      pendingExtractedSheets.value = []
    }
    return
  }

  // ─ Single-file replay (original flow) ─
  if (!fileWaitingForProcess.value) return
  const questions = replayFilteredQuestions().map(q => q.question_text)
  if (questions.length === 0) {
    showReplayDialog.value = false
    return
  }

  isReplaying.value = true

  try {
    await excelFileAPI.batchQuery(fileWaitingForProcess.value.file_uuid, questions)
    showReplayDialog.value = false
    // Navigate to inline chat with the uploaded file
    goToChatWithFile({
      file_uuid: fileWaitingForProcess.value.file_uuid,
      filename: fileWaitingForProcess.value.filename,
      table_name: fileWaitingForProcess.value.table_name,
      total_rows: fileWaitingForProcess.value.rows,
      columns: fileWaitingForProcess.value.columns,
      column_stats: {}
    })
  } catch (e: any) {
    console.error('Auto-replay failed:', e)
    toast.error('Auto-replay failed. You can still chat with the file manually.')
    showReplayDialog.value = false
  } finally {
    isReplaying.value = false
    resetUpload()
  }
}

function skipReplay() {
  showReplayDialog.value = false
  if (pendingExtractedSheets.value.length > 0) {
    const count = pendingExtractedSheets.value.length
    pendingExtractedSheets.value = []
    toast.success(`${count} sheet(s) imported successfully`)
  } else {
    resetUpload()
  }
}

function goToChat(file: FileInfo) {
  selectedFile.value = file
  activePanel.value = 'chat'
}

function goToDashboard(file: FileInfo) {
  router.push({ name: 'smart-dashboard', query: { fileId: file.file_uuid } })
}

function goToChatWithFile(file: FileInfo) {
  const found = store.files.find(f => f.file_uuid === file.file_uuid)
  if (found) {
    selectFile(found)
    activePanel.value = 'chat'
    closeUploadModal()
  } else {
    // If mostly new, just set it manually
    selectedFile.value = file
    activePanel.value = 'chat'
    closeUploadModal()
  }
}

</script>

<template>
  <div class="flex flex-col h-[calc(100vh-3.5rem)] overflow-hidden">
    <div class="flex flex-col xl:flex-row h-full overflow-hidden p-3 gap-3">
      
      <!-- Sidebar -->
      <aside
        :class="['shrink-0 flex flex-col h-full glass-panel rounded-2xl overflow-hidden transition-all duration-300 ease-in-out', sidebarOpen ? 'xl:w-72 w-full' : 'w-0 xl:w-0 border-0 p-0', activePanel === 'chat' ? 'hidden xl:flex' : 'flex']"
      >
        <div class="w-72 flex flex-col h-full">
        
        <!-- Header -->
        <div class="px-3 pt-3 pb-2 border-b border-white/15 dark:border-white/5 space-y-2">
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-2">
              <h2 class="font-semibold text-sm uppercase tracking-wide text-muted-foreground">
                {{ explorerTitle }}
              </h2>
            </div>
            <div class="flex items-center gap-0.5">
              <Button
                size="sm"
                variant="ghost"
                class="h-7 px-2"
                :title="activeAccordion === 'dashboards' ? 'Create Insight Board' : 'Upload Data Source'"
                @click="handlePrimaryCreateAction"
              >
                <iconify-icon icon="lucide:plus" class="h-4 w-4" />
              </Button>
            </div>
          </div>

          <!-- View mode toggle (segmented pill) -->
          <div class="relative bg-white/40 dark:bg-white/5 p-1 rounded-full grid grid-cols-2">
            <!-- Sliding pill indicator -->
            <div
              class="absolute top-1 bottom-1 rounded-full bg-white/80 dark:bg-white/10 shadow-md transition-all duration-300 ease-in-out"
              :style="{ left: store.viewMode === 'active' ? '4px' : '50%', width: 'calc(50% - 4px)' }"
            />
            <button 
              @click="toggleViewMode('active')"
              class="relative z-10 text-[11px] font-semibold py-1.5 rounded-full transition-colors duration-200 flex items-center justify-center gap-1.5"
              :class="store.viewMode === 'active' ? 'text-foreground' : 'text-muted-foreground hover:text-foreground/70'"
            >
              <iconify-icon icon="lucide:file-text" class="h-3 w-3" /> Documents
            </button>
            <button 
              @click="toggleViewMode('trash')"
              class="relative z-10 text-[11px] font-semibold py-1.5 rounded-full transition-colors duration-200 flex items-center justify-center gap-1.5"
              :class="store.viewMode === 'trash' ? 'text-destructive' : 'text-muted-foreground hover:text-foreground/70'"
            >
              <iconify-icon icon="lucide:trash-2" class="h-3 w-3" /> Trash
            </button>
          </div>

          <!-- Empty Trash button -->
          <Button
            v-if="store.viewMode === 'trash' && store.trashFiles.length > 0"
            variant="destructive"
            size="sm"
            class="w-full text-xs h-7"
            :disabled="isEmptyingTrash"
            @click="emptyAllTrash"
          >
            <iconify-icon :icon="isEmptyingTrash ? 'eos-icons:loading' : 'lucide:trash-2'" :class="['h-3 w-3 mr-1.5', isEmptyingTrash && 'animate-spin']" />
            {{ isEmptyingTrash ? 'Emptying…' : `Empty Trash (${store.trashFiles.length})` }}
          </Button>

          <!-- Search + Filter popover -->
          <FilterPopover />
        </div>

             <!-- Explorer area: VS Code-style icon rail + single pane -->
        <div class="flex-1 overflow-hidden py-1 px-1">
          <div class="m-1 h-full overflow-hidden rounded-md border bg-card shadow-sm">
            <Transition name="explorer-pane" mode="out-in">
              <div v-if="activeAccordion" :key="activeAccordion" class="h-full min-w-0 flex flex-col">
              <div v-if="activeAccordion === 'folders'" class="h-10 shrink-0 border-b border-white/10 dark:border-white/5 px-2.5 flex items-center justify-between bg-muted/20">
                <span class="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground flex items-center gap-1.5">
                  <iconify-icon icon="lucide:folder-tree" class="h-3.5 w-3.5" />
                  Folders & Files
                </span>
                <button
                  @click="creatingRootFolder = true; newRootFolderName = ''"
                  class="p-1 rounded hover:bg-muted text-muted-foreground hover:text-foreground transition-colors"
                  title="New Folder"
                >
                  <iconify-icon icon="lucide:folder-plus" class="h-3.5 w-3.5" />
                </button>
              </div>

              <div v-else class="h-10 shrink-0 border-b border-indigo-100 dark:border-indigo-900/50 px-2.5 flex items-center justify-between bg-indigo-50/50 dark:bg-indigo-950/20">
                <span class="text-[11px] font-semibold uppercase tracking-wide text-indigo-700 dark:text-indigo-400 flex items-center gap-1.5">
                  <iconify-icon icon="lucide:layout-dashboard" class="h-3.5 w-3.5" />
                  Insight Boards
                </span>
                <button
                  @click="creatingDashboard = true; newDashboardName = ''"
                  class="p-1 rounded hover:bg-indigo-100 dark:hover:bg-indigo-900/60 text-indigo-600 dark:text-indigo-400 transition-colors"
                  title="New Dashboard"
                >
                  <iconify-icon icon="lucide:plus" class="h-3.5 w-3.5" />
                </button>
              </div>

              <div class="flex-1 overflow-y-auto p-1">
                <template v-if="activeAccordion === 'folders'">
                  <div v-if="creatingRootFolder" class="flex items-center gap-1 px-1.5 py-1">
                    <Input
                      v-model="newRootFolderName"
                      placeholder="Folder name"
                      class="h-6 text-xs flex-1"
                      @keyup.enter="handleCreateRootFolder"
                      @keyup.escape="creatingRootFolder = false"
                      autofocus
                    />
                    <Button variant="default" size="sm" class="h-6 px-1.5 text-[10px]" @click="handleCreateRootFolder" :disabled="!newRootFolderName.trim()">
                      <iconify-icon icon="lucide:check" class="h-3 w-3" />
                    </Button>
                    <Button variant="ghost" size="sm" class="h-6 w-6 px-0" @click="creatingRootFolder = false">
                      <iconify-icon icon="lucide:x" class="h-3 w-3" />
                    </Button>
                  </div>

                  <FileSystemNode
                    v-for="node in folderFileTree"
                    :key="node.id"
                    :node="node"
                    :depth="0"
                    :selectedFileId="selectedFile?.file_uuid ?? null"
                    :isTrash="store.viewMode === 'trash'"
                    @selectFile="selectFile"
                    @deleteFile="softDeleteFile"
                    @restoreFile="restoreFile"
                    @chatFile="goToChatWithFile"
                    @uploadToFolder="(pId, sId) => triggerUpload(pId, sId)"
                    @addSheet="(gId) => triggerAddSheet(gId)"
                  />
                  <div v-if="folderFileTree.length === 0" class="text-center py-6 px-4">
                    <p class="text-[10px] text-muted-foreground/60 uppercase tracking-wider">No folders or files</p>
                  </div>
                </template>

                <template v-else>
                  <div v-if="creatingDashboard" class="px-1.5 py-1 space-y-1.5">
                    <Input
                      v-model="newDashboardName"
                      placeholder="Board name"
                      class="h-6 text-xs w-full border-indigo-200 focus-visible:ring-indigo-400"
                      @keyup.enter="handleCreateDashboard"
                      @keyup.escape="creatingDashboard = false"
                      autofocus
                    />
                    <div class="flex items-center gap-1">
                      <Button variant="default" size="sm" class="h-6 px-2 text-[10px] bg-indigo-600 hover:bg-indigo-700 flex-1" @click="handleCreateDashboard" :disabled="!newDashboardName.trim()">
                        Create
                      </Button>
                      <Button variant="ghost" size="sm" class="h-6 w-6 px-0 text-indigo-400 hover:text-indigo-600" @click="creatingDashboard = false">
                        <iconify-icon icon="lucide:x" class="h-3 w-3" />
                      </Button>
                    </div>
                  </div>

                  <div class="flex flex-col gap-0.5">
                    <button
                      v-for="board in filteredBoards"
                      :key="board.board_id"
                      class="w-full text-left flex items-center gap-2 px-2 py-1.5 hover:bg-muted/70 rounded-md transition-colors text-sm font-medium text-foreground/90 group"
                      @click="router.push({ name: 'insight-board', params: { boardId: board.board_id } })"
                    >
                      <iconify-icon icon="lucide:layout-dashboard" class="h-4 w-4 text-indigo-500/80 shrink-0" />
                      <span class="truncate">{{ board.name }}</span>
                      <Badge v-if="board.file_count" variant="secondary" class="text-[9px] h-4 px-1.5 ml-auto shrink-0">{{ board.file_count }}</Badge>

                      <div class="opacity-0 group-hover:opacity-100 transition-opacity flex items-center gap-1 shrink-0"
                           :class="board.file_count ? '' : 'ml-auto'">
                        <button
                          @click.stop="confirmDeleteBoard(board.board_id)"
                          class="p-1 rounded hover:bg-destructive/10 text-destructive text-xs"
                          title="Delete Board"
                        >
                          <iconify-icon icon="lucide:trash-2" class="h-3.5 w-3.5" />
                        </button>
                      </div>
                    </button>
                  </div>
                  <div v-if="filteredBoards.length === 0" class="text-center py-6 px-4">
                    <p class="text-[10px] text-muted-foreground/60 uppercase tracking-wider">No insight boards</p>
                  </div>
                </template>
              </div>
            </div>
            </Transition>
          </div>
        </div>

        <!-- Footer status bar -->
        <div class="px-3 py-1.5 border-t border-white/15 dark:border-white/5 bg-white/20 dark:bg-white/5 flex items-center justify-between text-[11px] text-muted-foreground">
          <span>{{ store.sortedFiles.length }} file{{ store.sortedFiles.length !== 1 ? 's' : '' }}</span>
          <span>{{ store.projects.length }} folder{{ store.projects.length !== 1 ? 's' : '' }}</span>
        </div>
        </div>
      </aside>

      <div class="flex-1 flex flex-col min-w-0 glass-panel rounded-2xl overflow-hidden">
        
        <div v-if="selectedFile" class="flex flex-col h-full">
          
          <div class="h-14 border-b border-white/15 dark:border-white/5 flex items-center justify-between px-5 bg-white/30 dark:bg-white/5">
            <div class="flex items-center gap-3 overflow-hidden">
              <!-- Sidebar toggle -->
              <button @click="toggleSidebar()"
                :title="sidebarOpen ? 'Hide sidebar (Explorer)' : 'Show sidebar (Explorer)'"
                :class="['rounded-lg p-1.5 transition', sidebarOpen ? 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300' : 'text-slate-400 hover:bg-slate-100 hover:text-slate-700 dark:text-slate-500 dark:hover:bg-slate-800 dark:hover:text-slate-300']"
              >
                <iconify-icon :icon="sidebarOpen ? 'lucide:panel-left-close' : 'lucide:panel-left-open'" class="h-4 w-4" />
              </button>
              <div class="h-5 w-px bg-border/50" />
              <Button v-if="activePanel === 'chat'" variant="ghost" size="icon" class="h-8 w-8" @click="activePanel = 'settings'">
                <iconify-icon icon="lucide:arrow-left" class="h-4 w-4" />
              </Button>
              <div class="min-w-0">
                <h1 class="font-bold text-base truncate flex items-center gap-2">
                  {{ selectedFile.filename }}
                  <Badge v-if="store.viewMode === 'trash'" variant="destructive" class="text-[10px] h-5">Deleted</Badge>
                </h1>
                <p class="text-[11px] text-muted-foreground flex items-center gap-1.5">
                  <span class="font-mono">{{ selectedFile.file_uuid.slice(0,8) }}</span>
                  <span class="text-muted-foreground/40">·</span>
                  <span>{{ selectedFile.total_rows.toLocaleString() }} rows</span>
                  <span class="text-muted-foreground/40">·</span>
                  <span>{{ selectedFile.columns.length }} columns</span>
                </p>
              </div>
            </div>
            
            <div v-if="activePanel === 'settings' && store.viewMode === 'active'" class="flex items-center gap-2">
               <Button @click="goToDashboard(selectedFile)" size="sm" variant="outline" class="border-muted-foreground/20 text-muted-foreground hover:bg-muted hover:text-foreground">
                 <iconify-icon icon="lucide:layout-dashboard" class="mr-1.5 h-3.5 w-3.5" />
                 Dashboard
               </Button>
               <Button @click="goToChat(selectedFile)" size="sm" class="bg-primary hover:bg-primary/90 text-primary-foreground shadow-md font-semibold">
                 <iconify-icon icon="lucide:message-square" class="mr-1.5 h-3.5 w-3.5" />
                 Chat with Data
               </Button>
            </div>
            <div v-else-if="activePanel === 'chat'" class="flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                @click="chatPageRef?.clearChat()"
                title="Clear chat history"
                class="h-8 hover:bg-destructive/10 hover:text-destructive hover:border-destructive/30"
              >
                <iconify-icon icon="lucide:trash-2" class="mr-1.5 h-3.5 w-3.5" />
                Clear History
              </Button>
            </div>
          </div>

          <div class="flex-1 overflow-y-auto">
            
            <div v-if="activePanel === 'settings'" class="p-4 md:p-5 space-y-5">
              
              <!-- Stats Row -->
              <div class="grid grid-cols-2 md:grid-cols-4 gap-3">
                <div class="rounded-2xl glass-card p-4 text-center">
                  <div class="inline-flex items-center justify-center w-10 h-10 rounded-full bg-blue-500/10 text-blue-500 mb-2">
                    <iconify-icon icon="lucide:rows-3" class="h-5 w-5" />
                  </div>
                  <div class="text-xl font-bold text-foreground">{{ selectedFile.total_rows.toLocaleString() }}</div>
                  <p class="text-[11px] text-muted-foreground uppercase tracking-wider font-medium mt-0.5">Rows</p>
                </div>
                <div class="rounded-2xl glass-card p-4 text-center">
                  <div class="inline-flex items-center justify-center w-10 h-10 rounded-full bg-violet-500/10 text-violet-500 mb-2">
                    <iconify-icon icon="lucide:columns-3" class="h-5 w-5" />
                  </div>
                  <div class="text-xl font-bold text-foreground">{{ selectedFile.columns.length }}</div>
                  <p class="text-[11px] text-muted-foreground uppercase tracking-wider font-medium mt-0.5">Columns</p>
                </div>
                <div class="rounded-2xl glass-card p-4 text-center">
                  <div class="inline-flex items-center justify-center w-10 h-10 rounded-full bg-emerald-500/10 text-emerald-500 mb-2">
                    <iconify-icon icon="lucide:file-spreadsheet" class="h-5 w-5" />
                  </div>
                  <div class="text-xl font-bold text-foreground">{{ selectedFile.filename.split('.').pop()?.toUpperCase() }}</div>
                  <p class="text-[11px] text-muted-foreground uppercase tracking-wider font-medium mt-0.5">Format</p>
                </div>
                <div class="rounded-2xl glass-card p-4 text-center" :class="store.viewMode === 'trash' ? 'border-destructive/30 bg-destructive/5' : ''">
                  <div class="inline-flex items-center justify-center w-10 h-10 rounded-full mb-2" :class="store.viewMode === 'trash' ? 'bg-destructive/10 text-destructive' : 'bg-amber-500/10 text-amber-500'">
                    <iconify-icon :icon="store.viewMode === 'trash' ? 'lucide:trash-2' : 'lucide:calendar'" class="h-5 w-5" />
                  </div>
                  <div class="text-sm font-bold" :class="store.viewMode === 'trash' ? 'text-destructive' : 'text-foreground'">
                    {{ store.viewMode === 'active' ? formatDate(selectedFile.created_on) : formatDate(selectedFile.deleted_at) }}
                  </div>
                  <p class="text-[11px] text-muted-foreground uppercase tracking-wider font-medium mt-0.5">
                    {{ store.viewMode === 'active' ? 'Uploaded' : 'Deleted' }}
                  </p>
                </div>
              </div>

              <!-- Column Structure -->
              <div class="rounded-2xl glass-card p-4">
                <h3 class="text-sm font-semibold mb-3 flex items-center gap-2 text-foreground">
                  <iconify-icon icon="lucide:columns-3" class="h-4 w-4 text-primary" /> Data Columns
                </h3>
                <div class="flex flex-wrap gap-1.5">
                  <HoverCard v-for="col in selectedFile.columns" :key="col" :open-delay="200" :close-delay="100">
                    <HoverCardTrigger as-child>
                      <Badge variant="secondary" class="px-3 py-1 font-medium text-xs cursor-default rounded-full bg-muted/80 text-foreground/80 border border-border/50 transition-all duration-200 hover:bg-primary hover:text-primary-foreground hover:border-primary hover:shadow-sm">
                        {{ col }}
                      </Badge>
                    </HoverCardTrigger>
                    <HoverCardContent class="w-72 text-xs" align="start" :side-offset="6">
                      <div class="space-y-2">
                        <div class="flex items-center justify-between">
                          <span class="font-semibold text-sm">{{ col }}</span>
                          <Badge variant="outline" class="text-[10px] px-1.5 py-0">
                            {{ getColumnMeta(col)?.type || 'unknown' }}
                          </Badge>
                        </div>
                        <div v-if="getColumnMeta(col)" class="space-y-1.5">
                          <div class="flex justify-between text-muted-foreground">
                            <span>Unique values</span>
                            <span class="text-foreground font-medium">{{ getColumnMeta(col).unique_count }}</span>
                          </div>
                          <div class="flex justify-between text-muted-foreground">
                            <span>Null values</span>
                            <span class="text-foreground font-medium">{{ getColumnMeta(col).null_count }}</span>
                          </div>
                          <div v-if="getColumnMeta(col).most_frequent" class="flex justify-between text-muted-foreground">
                            <span>Most frequent</span>
                            <span class="text-foreground font-medium truncate ml-2 max-w-[140px]">{{ getColumnMeta(col).most_frequent }}</span>
                          </div>
                          <div v-if="getColumnMeta(col).min != null" class="flex justify-between text-muted-foreground">
                            <span>Range</span>
                            <span class="text-foreground font-medium">{{ getColumnMeta(col).min }} – {{ getColumnMeta(col).max }}</span>
                          </div>
                          <div v-if="getColumnMeta(col).mean != null" class="flex justify-between text-muted-foreground">
                            <span>Mean</span>
                            <span class="text-foreground font-medium">{{ Number(getColumnMeta(col).mean).toFixed(2) }}</span>
                          </div>
                          <div v-if="getColumnMeta(col).median != null" class="flex justify-between text-muted-foreground">
                            <span>Median</span>
                            <span class="text-foreground font-medium">{{ Number(getColumnMeta(col).median).toFixed(2) }}</span>
                          </div>
                          <div v-if="getColumnMeta(col).samples?.length" class="pt-1 border-t">
                            <span class="text-muted-foreground">Top values:</span>
                            <div class="flex flex-wrap gap-1 mt-1">
                              <Badge v-for="s in getColumnMeta(col).samples.slice(0, 6)" :key="s" variant="outline" class="text-[10px] px-1.5 py-0 font-normal">
                                {{ s }}
                              </Badge>
                              <span v-if="getColumnMeta(col).samples.length > 6" class="text-muted-foreground text-[10px]">
                                +{{ getColumnMeta(col).samples.length - 6 }} more
                              </span>
                            </div>
                          </div>
                        </div>
                        <p v-else class="text-muted-foreground">No metadata available</p>
                      </div>
                    </HoverCardContent>
                  </HoverCard>
                </div>
              </div>

              <div v-if="store.viewMode === 'active'" class="space-y-4">
                <!-- Quick Actions -->
                <div class="rounded-2xl glass-card p-4">
                  <h3 class="text-sm font-semibold mb-3 flex items-center gap-2 text-foreground">
                    <iconify-icon icon="lucide:zap" class="h-4 w-4 text-primary" /> Quick Actions
                  </h3>
                  <div class="grid grid-cols-4 gap-2">
                    <button
                      class="flex items-center justify-center gap-2 rounded-xl glass-btn px-3 py-2.5 text-xs font-medium text-foreground/80 transition-all duration-150 hover:border-primary/40 hover:bg-primary/5 hover:text-primary active:scale-[0.97]"
                      @click="previewFile(selectedFile)"
                    >
                      <iconify-icon icon="lucide:eye" class="h-4 w-4 text-primary flex-shrink-0" />
                      <span>Preview Data</span>
                    </button>
                    <button
                      class="flex items-center justify-center gap-2 rounded-xl glass-btn px-3 py-2.5 text-xs font-medium text-foreground/80 transition-all duration-150 hover:border-primary/40 hover:bg-primary/5 hover:text-primary active:scale-[0.97]"
                      @click="openChunksModal()"
                    >
                      <iconify-icon icon="lucide:layers" class="h-4 w-4 text-primary flex-shrink-0" />
                      <span>Vector Chunks</span>
                    </button>
                    <button
                      class="flex items-center justify-center gap-2 rounded-xl glass-btn px-3 py-2.5 text-xs font-medium text-foreground/80 transition-all duration-150 hover:border-primary/40 hover:bg-primary/5 hover:text-primary active:scale-[0.97]"
                      @click="downloadData(selectedFile, 'csv')"
                    >
                      <iconify-icon icon="lucide:file-spreadsheet" class="h-4 w-4 text-primary flex-shrink-0" />
                      <span>Export CSV</span>
                    </button>
                    <button
                      class="flex items-center justify-center gap-2 rounded-xl glass-btn px-3 py-2.5 text-xs font-medium text-foreground/80 transition-all duration-150 hover:border-primary/40 hover:bg-primary/5 hover:text-primary active:scale-[0.97]"
                      @click="downloadData(selectedFile, 'json')"
                    >
                      <iconify-icon icon="lucide:file-json" class="h-4 w-4 text-primary flex-shrink-0" />
                      <span>Export JSON</span>
                    </button>
                  </div>
                </div>

                <!-- Cache & Danger Zone -->
                <div class="grid grid-cols-2 gap-3">
                  <div class="rounded-2xl glass-card p-4">
                    <div class="flex items-center gap-3 mb-3">
                      <div class="flex items-center justify-center w-8 h-8 rounded-lg bg-orange-500/10 text-orange-500 flex-shrink-0">
                        <iconify-icon icon="lucide:database" class="h-4 w-4" />
                      </div>
                      <div>
                        <h3 class="text-sm font-semibold text-foreground">Cache</h3>
                        <p class="text-xs text-muted-foreground">Clear cached responses</p>
                      </div>
                    </div>
                    <Button variant="outline" size="sm" class="h-8 text-xs rounded-lg w-full" @click="deleteFileCache(selectedFile)">
                      <iconify-icon icon="lucide:eraser" class="mr-1.5 h-3.5 w-3.5" /> Clear Cache
                    </Button>
                  </div>
                  <div class="rounded-2xl glass-card p-4">
                    <div class="flex items-center gap-3 mb-3">
                      <div class="flex items-center justify-center w-8 h-8 rounded-lg bg-muted text-muted-foreground flex-shrink-0">
                        <iconify-icon icon="lucide:trash-2" class="h-4 w-4" />
                      </div>
                      <div>
                        <h3 class="text-sm font-semibold text-foreground">Remove File</h3>
                        <p class="text-xs text-muted-foreground">Move to recycle bin</p>
                      </div>
                    </div>
                    <Button variant="outline" size="sm" class="h-8 text-xs rounded-lg w-full text-destructive hover:bg-destructive/10 hover:text-destructive border-border" @click="softDeleteFile(selectedFile)">
                      <iconify-icon icon="lucide:trash-2" class="mr-1.5 h-3.5 w-3.5" /> Delete
                    </Button>
                  </div>
                </div>
              </div>

              <div v-else class="space-y-6">
                <div class="glass-card p-6 rounded-2xl flex flex-col items-center text-center space-y-4">
                  <iconify-icon icon="lucide:recycle" class="h-12 w-12 text-muted-foreground" />
                  <div>
                    <h3 class="font-semibold text-lg">File is in Recycle Bin</h3>
                    <p class="text-sm text-muted-foreground max-w-md mx-auto">
                      This file was deleted on {{ formatDate(selectedFile.deleted_at) }}. You can restore it to continue analysis or delete it permanently.
                    </p>
                  </div>
                  <div class="flex gap-4 pt-2">
                    <Button size="lg" class="bg-primary hover:bg-primary/90 text-primary-foreground w-40" @click="restoreFile(selectedFile)">
                      <iconify-icon icon="lucide:undo-2" class="mr-2 h-4 w-4" /> Restore
                    </Button>
                    <Button size="lg" variant="destructive" class="w-40" @click="permanentDeleteFile(selectedFile)">
                      <iconify-icon icon="lucide:x-circle" class="mr-2 h-4 w-4" /> Delete Forever
                    </Button>
                  </div>
                </div>
              </div>

            </div>

            <div v-else class="h-full">
              <ChatPage ref="chatPageRef" :file-id="selectedFile.file_uuid" :key="selectedFile.file_uuid" />
            </div>

          </div>
        </div>

        <div v-else class="flex-1 flex flex-col items-center justify-center text-muted-foreground relative">
          <!-- Sidebar toggle when no file selected -->
          <button @click="toggleSidebar()"
            :title="sidebarOpen ? 'Hide sidebar (Explorer)' : 'Show sidebar (Explorer)'"
            :class="['absolute top-4 left-4 rounded-lg p-1.5 transition', sidebarOpen ? 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300' : 'text-slate-400 hover:bg-slate-100 hover:text-slate-700 dark:text-slate-500 dark:hover:bg-slate-800 dark:hover:text-slate-300']"
          >
            <iconify-icon :icon="sidebarOpen ? 'lucide:panel-left-close' : 'lucide:panel-left-open'" class="h-4 w-4" />
          </button>
          <div class="w-16 h-16 rounded-2xl bg-muted/30 flex items-center justify-center mb-5">
            <iconify-icon icon="lucide:mouse-pointer-2" class="h-7 w-7 opacity-40" />
          </div>
          <p class="text-base font-medium">Select a file to view details</p>
          <p class="text-sm opacity-60 mt-1">Choose from the sidebar on the left</p>
        </div>

      </div>
    </div>

    <div v-if="showUploadModal" class="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4">
      <Card class="w-full max-w-xl flex flex-col">
        <CardHeader class="border-b flex flex-row items-center justify-between space-y-0 pb-4">
          <div>
            <CardTitle class="flex items-center gap-2">
              <iconify-icon icon="lucide:upload-cloud" class="h-5 w-5 text-primary" />
              Upload Document
            </CardTitle>
          </div>
          <Button variant="ghost" size="icon" class="h-8 w-8" @click="closeUploadModal">
            <iconify-icon icon="lucide:x" class="h-4 w-4" />
          </Button>
        </CardHeader>

        <CardContent class="space-y-6 pt-4">
          <div class="flex items-center rounded-lg border bg-muted/30 px-3 py-2 text-sm mb-4">
            <div class="flex items-center gap-2 min-w-0">
              <iconify-icon icon="lucide:folder" class="h-4 w-4 text-primary flex-shrink-0" />
              <span class="font-medium text-foreground truncate">{{ uploadAssignmentLabel }}</span>
            </div>
          </div>
          <div
            v-if="!isUploading && !fileWaitingForProcess && !uploadError"
            class="border-2 border-dashed border-muted-foreground/20 rounded-xl p-10 text-center hover:border-primary/40 hover:bg-primary/[0.02] transition-all group/drop"
          >
            <div class="w-14 h-14 rounded-full bg-primary/10 flex items-center justify-center mx-auto mb-4 group-hover/drop:bg-primary/15 transition-colors">
              <iconify-icon icon="lucide:upload-cloud" class="h-7 w-7 text-primary" />
            </div>
            <div class="space-y-3 flex flex-col items-center">
              <label class="inline-flex items-center gap-2 px-5 py-2.5 bg-primary text-primary-foreground rounded-lg font-semibold text-sm hover:bg-primary/90 cursor-pointer transition-colors shadow-sm">
                <iconify-icon icon="lucide:upload" class="h-4 w-4" />
                Choose File
                <input
                  type="file"
                  accept=".xlsx,.xls,.csv"
                  @change="handleFileUpload"
                  class="hidden"
                />
              </label>
              <p class="text-muted-foreground text-sm mt-1">or drag & drop your file here</p>
              <div class="flex items-center gap-3 mt-3">
                <Badge variant="secondary" class="text-[10px]">.xlsx</Badge>
                <Badge variant="secondary" class="text-[10px]">.xls</Badge>
                <Badge variant="secondary" class="text-[10px]">.csv</Badge>
              </div>
            </div>
          </div>

          <div v-if="isUploading" class="py-6 text-center">
            <div class="relative inline-block mb-6">
              <div class="w-20 h-20 rounded-full border-4 border-muted animate-spin border-t-primary mx-auto"></div>
              <div class="absolute inset-0 flex items-center justify-center">
                <iconify-icon :icon="getCurrentStageConfig().icon" class="h-8 w-8 text-primary" />
              </div>
            </div>

            <div class="mb-4">
              <p class="text-lg font-semibold">{{ getCurrentStageConfig().label }}</p>
              <p class="text-sm text-muted-foreground mt-1">{{ uploadMessage }}</p>
            </div>
            
            <div class="max-w-md mx-auto">
              <div class="flex justify-between text-sm mb-2">
                <span class="text-muted-foreground">Progress</span>
                <span class="font-bold text-primary">{{ uploadProgress }}%</span>
              </div>
              <div class="w-full bg-muted rounded-full h-3 overflow-hidden">
                <div
                  class="h-3 rounded-full transition-all duration-500 ease-out bg-gradient-to-r from-blue-500 to-indigo-500"
                  :style="{ width: uploadProgress + '%' }"
                ></div>
              </div>
            </div>
          </div>

          <div v-if="uploadError" class="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-4">
            <div class="flex items-start gap-3">
              <iconify-icon icon="lucide:x-circle" class="h-6 w-6 text-red-600 dark:text-red-500 mt-0.5" />
              <div class="flex-1">
                <p class="font-semibold text-red-900 dark:text-red-100">Upload Failed</p>
                <p class="text-sm text-red-800 dark:text-red-200 mt-1">{{ uploadError }}</p>
                <Button size="sm" variant="outline" class="mt-3" @click="resetUpload">Try Again</Button>
              </div>
            </div>
          </div>

          <div v-if="fileWaitingForProcess && !isUploading" class="py-6 text-center">
            <div class="w-16 h-16 rounded-full bg-green-100 dark:bg-green-900/30 flex items-center justify-center mx-auto mb-4">
              <iconify-icon icon="lucide:check" class="h-8 w-8 text-green-600 dark:text-green-500" />
            </div>
            <h3 class="text-lg font-bold text-green-900 dark:text-green-100">Upload Successful!</h3>
            <p class="text-muted-foreground mt-2">
              <span class="font-medium">{{ fileWaitingForProcess.filename }}</span> is ready for analysis
            </p>
            <div class="flex flex-col items-center gap-2 mt-6">
              <Button
                size="lg"
                class="w-64 bg-blue-600 hover:bg-blue-700 text-white shadow-md"
                @click="goToChatWithFile({
                  file_uuid: fileWaitingForProcess.file_uuid,
                  filename: fileWaitingForProcess.filename,
                  table_name: fileWaitingForProcess.table_name,
                  total_rows: fileWaitingForProcess.rows,
                  columns: fileWaitingForProcess.columns,
                  column_stats: {}
                })"
              >
                <iconify-icon icon="lucide:message-square" class="h-4 w-4 mr-2" />
                Chat with Data
              </Button>
              <div class="flex gap-2">
                <Button variant="ghost" size="sm" class="text-xs" @click="closeUploadModal">
                  <iconify-icon icon="lucide:folder-open" class="h-3.5 w-3.5 mr-1" />
                  View in Documents
                </Button>
                <Button variant="ghost" size="sm" class="text-xs" @click="resetUploadForNewFile">
                  <iconify-icon icon="lucide:upload" class="h-3.5 w-3.5 mr-1" />
                  Upload Another
                </Button>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>

    <!-- ── Sheet Picker Modal ── -->
    <div v-if="showSheetPickerModal" class="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4">
      <Card class="w-full max-w-md">
        <CardHeader class="border-b pb-4">
          <CardTitle class="flex items-center gap-2">
            <iconify-icon icon="lucide:layers" class="h-5 w-5 text-emerald-500" />
            Select Sheets to Import
          </CardTitle>
          <CardDescription>
            {{ rawUploadResult?.filename }} — choose which sheets to import as separate datasets.
          </CardDescription>
        </CardHeader>
        <CardContent class="pt-4 space-y-3">
          <div class="space-y-1.5 max-h-64 overflow-y-auto pr-1">
            <label
              v-for="sheet in rawUploadResult?.sheets"
              :key="sheet"
              class="flex items-center gap-3 px-3 py-2 rounded-lg border cursor-pointer transition-colors"
              :class="selectedSheets.includes(sheet) ? 'border-primary bg-primary/5' : 'border-border hover:bg-muted/50'"
            >
              <input
                type="checkbox"
                class="h-4 w-4 accent-primary"
                :value="sheet"
                v-model="selectedSheets"
              />
              <iconify-icon icon="lucide:table" class="h-4 w-4 text-emerald-500 flex-shrink-0" />
              <span class="text-sm font-medium truncate">{{ sheet }}</span>
              <iconify-icon
                v-if="extractResults.find(r => r.sheet === sheet)?.done"
                icon="lucide:check-circle-2"
                class="ml-auto h-4 w-4 text-green-500 flex-shrink-0"
              />
              <iconify-icon
                v-else-if="extractResults.find(r => r.sheet === sheet)?.error"
                icon="lucide:x-circle"
                class="ml-auto h-4 w-4 text-red-500 flex-shrink-0"
              />
            </label>
          </div>

          <div v-if="isExtractingSheets" class="flex items-center gap-2 text-sm text-muted-foreground">
            <iconify-icon icon="lucide:loader-2" class="h-4 w-4 animate-spin" />
            Importing selected sheets…
          </div>
        </CardContent>
        <CardContent class="border-t pt-4 flex justify-between items-center">
          <div class="flex gap-2">
            <Button variant="ghost" size="sm" @click="selectedSheets = [...(rawUploadResult?.sheets ?? [])]">All</Button>
            <Button variant="ghost" size="sm" @click="selectedSheets = []">None</Button>
          </div>
          <div class="flex gap-2">
            <Button
              variant="ghost"
              size="sm"
              :disabled="isExtractingSheets"
              @click="showSheetPickerModal = false; rawUploadResult = null; addSheetGroupId = null"
            >
              Cancel
            </Button>
            <Button
              variant="default"
              size="sm"
              :disabled="isExtractingSheets || selectedSheets.length === 0"
              @click="processSelectedSheets"
            >
              <iconify-icon icon="lucide:download" class="h-4 w-4 mr-1" />
              Import {{ selectedSheets.length }} sheet{{ selectedSheets.length !== 1 ? 's' : '' }}
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>

    <div v-if="showPreviewModal && previewData" class="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4">
      <Card class="w-full max-w-4xl max-h-96 flex flex-col">
        <CardHeader class="border-b flex flex-row items-center justify-between space-y-0 pb-4">
          <div>
            <CardTitle class="flex items-center gap-2">
              <iconify-icon icon="lucide:eye" class="h-5 w-5" />
              Data Preview
            </CardTitle>
            <CardDescription>{{ previewData.preview_rows }} rows shown ({{ previewData.total_rows }} total)</CardDescription>
          </div>
          <Button variant="ghost" size="sm" @click="showPreviewModal = false">
            <iconify-icon icon="lucide:x" class="h-4 w-4" />
          </Button>
        </CardHeader>
        <CardContent class="flex-1 overflow-auto p-0 relative">
          <table class="w-full text-sm border-collapse">
            <thead class="sticky top-0 bg-muted z-10">
              <tr>
                <th v-for="(col, idx) in previewData.columns" :key="idx" class="border px-3 py-2 text-left font-semibold text-xs whitespace-nowrap">
                  {{ col }}
                </th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(row, rowIdx) in previewData.data" :key="rowIdx" class="hover:bg-muted/50">
                <td v-for="(col, colIdx) in previewData.columns" :key="colIdx" class="border px-3 py-2 text-xs">
                  {{ row[col] ?? '-' }}
                </td>
              </tr>
            </tbody>
          </table>
        </CardContent>
      </Card>
    </div>

    <div v-if="showChunksModal && chunksData" class="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4">
      <Card class="w-full max-w-4xl max-h-[80vh] flex flex-col">
        <CardHeader class="border-b flex flex-row items-center justify-between space-y-0 pb-4">
          <div>
            <CardTitle class="flex items-center gap-2">
              <iconify-icon icon="lucide:layers" class="h-5 w-5" />
              Vector Chunks
            </CardTitle>
            <CardDescription>
              Showing {{ (chunksData.page - 1) * chunksData.limit + 1 }}-{{ Math.min(chunksData.page * chunksData.limit, chunksData.total_rows) }} 
            </CardDescription>
          </div>
          <Button variant="ghost" size="sm" @click="showChunksModal = false">
            <iconify-icon icon="lucide:x" class="h-4 w-4" />
          </Button>
        </CardHeader>

        <CardContent class="flex-1 overflow-auto p-0 relative">
          <div v-if="isLoadingChunks" class="flex items-center justify-center p-8">
            <iconify-icon icon="lucide:loader-2" class="h-8 w-8 animate-spin text-primary" />
          </div>
          <table v-else class="w-full text-sm border-collapse">
            <thead class="sticky top-0 z-10 bg-muted">
              <tr class="bg-muted">
                  <th class="px-3 py-2 text-left font-semibold text-xs text-muted-foreground border-b whitespace-nowrap">#</th>
                  <th v-for="col in (chunksData.columns || [])" :key="col" class="px-3 py-2 text-left font-semibold text-xs text-muted-foreground border-b whitespace-nowrap">
                    {{ col }}
                  </th>
                  <th class="px-2 py-2 border-b"></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="chunk in chunksData.chunks" :key="chunk.row_index" class="border-b hover:bg-muted/40 transition-colors">
                <td class="px-3 py-2 font-mono text-xs text-muted-foreground whitespace-nowrap">{{ chunk.row_index }}</td>
                <td v-for="col in (chunksData.columns || [])" :key="col" class="px-3 py-2 text-xs font-mono whitespace-nowrap max-w-[200px] truncate" :title="chunk.data?.[col] != null ? String(chunk.data[col]) : '—'">
                  <span v-if="chunk.data?.[col] != null">{{ chunk.data[col] }}</span>
                  <span v-else class="text-muted-foreground/50">—</span>
                </td>
                <td class="px-2 py-2 whitespace-nowrap">
                  <Button variant="ghost" size="icon" class="h-6 w-6" @click="copyChunk(chunk.content)">
                    <iconify-icon icon="lucide:copy" class="h-3 w-3" />
                  </Button>
                </td>
              </tr>
            </tbody>
          </table>
        </CardContent>
        
        <div class="border-t p-4 flex items-center justify-between bg-muted/20">
          <Button variant="outline" size="sm" :disabled="chunksPage <= 1" @click="changeChunksPage(-1)">Previous</Button>
          <span class="text-sm font-medium">Page {{ chunksPage }} of {{ chunksData.total_pages }}</span>
          <Button variant="outline" size="sm" :disabled="chunksPage >= chunksData.total_pages" @click="changeChunksPage(1)">Next</Button>
        </div>
      </Card>
    </div>

    <!-- Auto-Replay Dialog -->
    <Dialog :open="showReplayDialog" @update:open="(v: boolean) => { if (!v && !isReplaying) skipReplay() }">
      <DialogContent class="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle class="flex items-center gap-2">
            <iconify-icon icon="lucide:bookmark-check" class="h-5 w-5 text-amber-500" />
            Saved Questions Found
          </DialogTitle>
          <DialogDescription>
            We found {{ savedQuestions.length }} saved question(s). Select a category to include its questions, then fine-tune individual ones.
          </DialogDescription>
        </DialogHeader>

        <div class="space-y-4 py-2">
          <!-- Categories with per-question toggles -->
          <div>
            <div class="flex items-center justify-between mb-2">
              <p class="text-xs font-semibold text-muted-foreground uppercase tracking-wide">Categories &amp; Questions</p>
              <div class="flex items-center gap-1.5">
                <button
                  class="text-xs text-primary hover:underline"
                  @click="selectedCategories = new Set(replayCategories); selectedQuestionIds = new Set(savedQuestions.map(q => q.id)); replayExpandedCats = new Set(replayCategories)"
                >All</button>
                <span class="text-muted-foreground text-xs">/</span>
                <button
                  class="text-xs text-muted-foreground hover:underline"
                  @click="selectedCategories = new Set(); selectedQuestionIds = new Set(); replayExpandedCats = new Set()"
                >None</button>
              </div>
            </div>
            <div class="space-y-1.5 max-h-72 overflow-y-auto pr-0.5">
              <div v-for="cat in replayCategories" :key="cat" class="rounded-lg border overflow-hidden">
                <!-- Category row -->
                <div
                  class="flex items-center gap-2.5 p-2.5 hover:bg-muted/30 transition-colors cursor-pointer"
                  @click="toggleCategory(cat)"
                >
                  <!-- Checkbox (tri-state) -->
                  <div
                    class="h-4 w-4 shrink-0 rounded-sm border border-primary shadow grid place-content-center transition-colors"
                    :class="selectedCategories.has(cat) ? 'bg-primary text-primary-foreground' : ''"
                  >
                    <iconify-icon v-if="selectedCategories.has(cat) && !isCatPartiallySelected(cat)" icon="lucide:check" class="h-3 w-3" />
                    <iconify-icon v-else-if="isCatPartiallySelected(cat)" icon="lucide:minus" class="h-3 w-3 text-primary" />
                  </div>
                  <div class="flex-1 flex items-center gap-2">
                    <iconify-icon :icon="cat === 'Generic' ? 'lucide:globe' : 'lucide:tag'" :class="cat === 'Generic' ? 'h-3.5 w-3.5 text-blue-500' : 'h-3.5 w-3.5 text-amber-500'" />
                    <span class="text-sm font-medium">{{ cat }}</span>
                    <Badge variant="secondary" class="text-[10px] h-4 px-1.5">
                      {{ questionsForReplayCat(cat).filter(q => selectedQuestionIds.has(q.id)).length }}/{{ categoryQuestionCount(cat) }}
                    </Badge>
                  </div>
                  <!-- Expand/collapse questions -->
                  <button
                    class="h-5 w-5 flex items-center justify-center rounded hover:bg-muted/60 transition-colors flex-shrink-0 text-muted-foreground"
                    @click.stop="toggleReplayCatExpand(cat)"
                    :title="replayExpandedCats.has(cat) ? 'Collapse' : 'Expand questions'"
                  >
                    <iconify-icon :icon="replayExpandedCats.has(cat) ? 'lucide:chevron-up' : 'lucide:chevron-down'" class="h-3.5 w-3.5" />
                  </button>
                </div>

                <!-- Per-question list -->
                <div v-if="replayExpandedCats.has(cat)" class="border-t bg-muted/20 divide-y divide-border/50">
                  <div
                    v-for="q in questionsForReplayCat(cat)"
                    :key="q.id"
                    class="flex items-start gap-2 px-3 py-2 hover:bg-muted/40 transition-colors cursor-pointer"
                    @click="toggleReplayQuestion(q)"
                  >
                    <div
                      class="h-3.5 w-3.5 mt-0.5 shrink-0 rounded-sm border border-primary/70 shadow grid place-content-center transition-colors"
                      :class="selectedQuestionIds.has(q.id) ? 'bg-primary text-primary-foreground' : ''"
                    >
                      <iconify-icon v-if="selectedQuestionIds.has(q.id)" icon="lucide:check" class="h-2.5 w-2.5" />
                    </div>
                    <span class="text-xs text-foreground/80 flex-1 leading-relaxed">{{ q.question_text }}</span>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- Replaying progress -->
          <div v-if="isReplaying" class="flex items-center gap-3 p-3 rounded-lg bg-blue-50 dark:bg-blue-950/30 border border-blue-200 dark:border-blue-800">
            <iconify-icon icon="eos-icons:loading" class="h-5 w-5 text-blue-600 animate-spin" />
            <div>
              <p class="text-sm font-medium text-blue-900 dark:text-blue-100">Processing questions...</p>
              <p class="text-xs text-blue-700 dark:text-blue-300">This may take a moment</p>
            </div>
          </div>
        </div>

        <DialogFooter class="gap-2">
          <Button variant="ghost" size="sm" :disabled="isReplaying" @click="skipReplay">
            Skip
          </Button>
          <Button size="sm" :disabled="isReplaying || replayFilteredQuestions().length === 0" @click="runAutoReplay">
            <iconify-icon v-if="isReplaying" icon="eos-icons:loading" class="h-4 w-4 mr-2 animate-spin" />
            <iconify-icon v-else icon="lucide:play" class="h-4 w-4 mr-2" />
            {{ isReplaying ? 'Processing...' : `Apply ${replayFilteredQuestions().length} Question(s)` }}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <!-- Change Password Modal -->
    <ChangePasswordModal
      v-if="showChangePasswordModal"
      @close="showChangePasswordModal = false"
    />

  </div>
</template>

<style scoped>
/* Transition Utilities */
.transition-all {
  transition: all 0.2s ease-in-out;
}

.explorer-pane-enter-active,
.explorer-pane-leave-active {
  transition: opacity 0.22s ease, transform 0.22s ease;
}

.explorer-pane-enter-from,
.explorer-pane-leave-to {
  opacity: 0;
  transform: translateY(6px);
}
</style>
