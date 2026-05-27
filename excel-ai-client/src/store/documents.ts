import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import excelFileAPI, {
  type FileInfo,
  type ProjectInfo,
  type DashboardWidget
} from '@/services/excelApi'

export type SortField = 'date' | 'name' | 'size'
export type SortOrder = 'asc' | 'desc'

// Dashboard layout: { fileUuid: { widgetId: { x, y, w, h } } }
export interface WidgetLayout {
  x: number
  y: number
  w: number
  h: number
}

export interface DashboardLayout {
  [widgetId: string]: WidgetLayout
}

export const useDocumentsStore = defineStore('documents', () => {
  // ── Core data ──────────────────────────────────────────────────────
  const files = ref<FileInfo[]>([])
  const trashFiles = ref<FileInfo[]>([])
  const projects = ref<ProjectInfo[]>([])
  const isLoading = ref(false)
  const isLoadingProjects = ref(false)

  // ── Filters ────────────────────────────────────────────────────────
  const searchQuery = ref('')
  const filterTags = ref<string[]>([])
  const showPinnedOnly = ref(false)
  const showFavoritesOnly = ref(false)
  const sortField = ref<SortField>('date')
  const sortOrder = ref<SortOrder>('desc')
  const viewMode = ref<'active' | 'trash'>('active')

  // ── Expanded state for folder tree ─────────────────────────────────
  const expandedProjects = ref<Set<string>>(new Set())

  // ── Dashboard layout persistence ───────────────────────────────────
  const dashboardLayouts = ref<{ [fileUuid: string]: DashboardLayout }>({})
  const dashboardLockState = ref<{ [fileUuid: string]: boolean }>({})
  // ── Compare Mode state ─────────────────────────────────────────
  const isCompareMode = ref(false)
  const compareFileId = ref<string | null>(null)
  const compareWidgets = ref<DashboardWidget[]>([])
  const compareFileInfo = ref<FileInfo | null>(null)
  const isCompareLoading = ref(false)

  function setCompareMode(enabled: boolean, fileId?: string) {
    isCompareMode.value = enabled
    if (!enabled) {
      compareFileId.value = null
      compareWidgets.value = []
      compareFileInfo.value = null
      isCompareLoading.value = false
    } else if (fileId) {
      compareFileId.value = fileId
    }
  }

  function setCompareWidgets(widgets: DashboardWidget[]) {
    compareWidgets.value = widgets
  }

  function setCompareFileInfo(info: FileInfo | null) {
    compareFileInfo.value = info
  }
  function saveDashboardLayout(fileUuid: string, widgets: DashboardWidget[]) {
    const layout: DashboardLayout = {}
    widgets.forEach(w => {
      layout[w.id] = {
        x: (w as any).gridX ?? 0,
        y: (w as any).gridY ?? 0,
        w: w.gridW,
        h: w.gridH
      }
    })
    dashboardLayouts.value[fileUuid] = layout
    localStorage.setItem(`dashboard-layout-${fileUuid}`, JSON.stringify(layout))
  }

  function loadDashboardLayout(fileUuid: string): DashboardLayout | null {
    const cached = dashboardLayouts.value[fileUuid]
    if (cached) return cached
    
    const stored = localStorage.getItem(`dashboard-layout-${fileUuid}`)
    if (stored) {
      const layout = JSON.parse(stored)
      dashboardLayouts.value[fileUuid] = layout
      return layout
    }
    return null
  }

  function setDashboardLockState(fileUuid: string, locked: boolean) {
    dashboardLockState.value[fileUuid] = locked
  }

  function getDashboardLockState(fileUuid: string): boolean {
    return dashboardLockState.value[fileUuid] ?? false
  }

  // ── Dashboard color theme ──────────────────────────────────────
  function setDashboardTheme(fileUuid: string, theme: string) {
    localStorage.setItem(`dashboard-theme-${fileUuid}`, theme)
  }

  function getDashboardTheme(fileUuid: string): string {
    return localStorage.getItem(`dashboard-theme-${fileUuid}`) || 'emerald'
  }

  // ── Data fetching ──────────────────────────────────────────────────
  async function fetchFiles() {
    isLoading.value = true
    try {
      const [active, trash] = await Promise.all([
        excelFileAPI.listFiles(),
        excelFileAPI.listTrashFiles()
      ])
      files.value = active
      trashFiles.value = trash
    } catch (e: any) {
      console.error('Failed to load files:', e?.message || e)
    } finally {
      isLoading.value = false
    }
  }

  async function fetchProjects() {
    isLoadingProjects.value = true
    try {
      projects.value = await excelFileAPI.listProjects()
    } catch (e: any) {
      console.error('Failed to load projects:', e?.message || e)
    } finally {
      isLoadingProjects.value = false
    }
  }

  async function fetchAll() {
    await Promise.all([fetchFiles(), fetchProjects()])
  }

  // ── Getters / computed ─────────────────────────────────────────────
  const baseFiles = computed(() =>
    viewMode.value === 'active' ? files.value : trashFiles.value
  )

  const searchedFiles = computed(() => {
    if (!searchQuery.value) return baseFiles.value
    const q = searchQuery.value.toLowerCase()
    return baseFiles.value.filter(f =>
      f.filename.toLowerCase().includes(q)
    )
  })

  const filteredFiles = computed(() => {
    let list = searchedFiles.value

    // Tag filter
    if (filterTags.value.length > 0) {
      list = list.filter(f =>
        filterTags.value.some(tag => (f.tags || []).includes(tag))
      )
    }

    // Pinned
    if (showPinnedOnly.value) {
      list = list.filter(f => f.is_pinned)
    }

    // Favorites
    if (showFavoritesOnly.value) {
      list = list.filter(f => f.is_favorite)
    }

    return list
  })

  const sortedFiles = computed(() => {
    const arr = [...filteredFiles.value]
    const dir = sortOrder.value === 'asc' ? 1 : -1
    arr.sort((a, b) => {
      if (a.is_pinned !== b.is_pinned) {
        return a.is_pinned ? -1 : 1
      }

      switch (sortField.value) {
        case 'name':
          return dir * a.filename.localeCompare(b.filename)
        case 'size':
          return dir * ((a.total_rows || 0) - (b.total_rows || 0))
        case 'date':
        default: {
          const da = new Date(a.created_on || 0).getTime()
          const db2 = new Date(b.created_on || 0).getTime()
          return dir * (da - db2)
        }
      }
    })
    return arr
  })

  const allTags = computed(() => {
    const tagSet = new Set<string>()
    files.value.forEach(f => (f.tags || []).forEach(t => tagSet.add(t)))
    return Array.from(tagSet).sort()
  })

  // ── Project Splits ─────────────────────────────────────────────────
  const regularFolders = computed(() => projects.value.filter(p => !p.is_dashboard))
  const dashboardFolders = computed(() => projects.value.filter(p => p.is_dashboard))

  // ── Folder (project) mutations ─────────────────────────────────────
  async function createProject(name: string, color?: string, is_dashboard?: boolean, source_file_uuid?: string) {
    const project = await excelFileAPI.createProject(name, color, is_dashboard, source_file_uuid)
    projects.value.unshift(project)
    return project
  }

  async function renameProject(projectId: string, name: string) {
    await excelFileAPI.updateProject(projectId, { name })
    const p = projects.value.find(pr => pr.project_id === projectId)
    if (p) p.name = name
  }

  async function updateProjectColor(projectId: string, color: string) {
    await excelFileAPI.updateProject(projectId, { color })
    const p = projects.value.find(pr => pr.project_id === projectId)
    if (p) p.color = color
  }

  async function deleteProject(projectId: string) {
    await excelFileAPI.deleteProject(projectId)
    projects.value = projects.value.filter(p => p.project_id !== projectId)
    // Remove files belonging to this project from local state
    files.value = files.value.filter(f => f.project_id !== projectId)
  }

  // ── Subfolder (subproject) mutations ────────────────────────────────
  async function createSubproject(projectId: string, name: string) {
    const sub = await excelFileAPI.createSubproject(projectId, name)
    const project = projects.value.find(p => p.project_id === projectId)
    if (project) (project.subprojects ??= []).unshift(sub)
    return sub
  }

  async function renameSubproject(projectId: string, subprojectId: string, name: string) {
    await excelFileAPI.updateSubproject(projectId, subprojectId, { name })
    const project = projects.value.find(p => p.project_id === projectId)
    const sub = project?.subprojects?.find(s => s.subproject_id === subprojectId)
    if (sub) sub.name = name
  }

  async function deleteSubproject(projectId: string, subprojectId: string) {
    await excelFileAPI.deleteSubproject(projectId, subprojectId)
    const project = projects.value.find(p => p.project_id === projectId)
    if (project) {
      project.subprojects = (project.subprojects ?? []).filter(s => s.subproject_id !== subprojectId)
    }
    files.value = files.value.filter(f => f.subproject_id !== subprojectId)
  }

  // ── File mutations ─────────────────────────────────────────────────
  async function moveFile(fileUuid: string, folderId: string | null, subfolderId: string | null = null) {
    await excelFileAPI.moveFile(fileUuid, folderId, subfolderId)
    const file = files.value.find(f => f.file_uuid === fileUuid)
    if (file) {
      file.project_id = folderId ?? undefined
      file.subproject_id = subfolderId ?? undefined
    }
  }

  async function togglePin(fileUuid: string) {
    const file = files.value.find(f => f.file_uuid === fileUuid)
    if (!file) return
    const newVal = !file.is_pinned
    await excelFileAPI.updateFileMetadata(fileUuid, { is_pinned: newVal })
    file.is_pinned = newVal
  }

  async function toggleFavorite(fileUuid: string) {
    const file = files.value.find(f => f.file_uuid === fileUuid)
    if (!file) return
    const newVal = !file.is_favorite
    await excelFileAPI.updateFileMetadata(fileUuid, { is_favorite: newVal })
    file.is_favorite = newVal
  }

  async function updateTags(fileUuid: string, tags: string[]) {
    await excelFileAPI.updateFileMetadata(fileUuid, { tags })
    const file = files.value.find(f => f.file_uuid === fileUuid)
    if (file) file.tags = tags
  }

  async function updateGroupPinned(fileIds: string[], pinned: boolean) {
    await Promise.all(fileIds.map(fileUuid => excelFileAPI.updateFileMetadata(fileUuid, { is_pinned: pinned })))
    const set = new Set(fileIds)
    files.value.forEach(file => {
      if (set.has(file.file_uuid)) file.is_pinned = pinned
    })
    trashFiles.value.forEach(file => {
      if (set.has(file.file_uuid)) file.is_pinned = pinned
    })
  }

  async function updateGroupFavorite(fileIds: string[], favorite: boolean) {
    await Promise.all(fileIds.map(fileUuid => excelFileAPI.updateFileMetadata(fileUuid, { is_favorite: favorite })))
    const set = new Set(fileIds)
    files.value.forEach(file => {
      if (set.has(file.file_uuid)) file.is_favorite = favorite
    })
    trashFiles.value.forEach(file => {
      if (set.has(file.file_uuid)) file.is_favorite = favorite
    })
  }

  async function updateGroupTags(fileIds: string[], tags: string[]) {
    await Promise.all(fileIds.map(fileUuid => excelFileAPI.updateFileMetadata(fileUuid, { tags })))
    const set = new Set(fileIds)
    files.value.forEach(file => {
      if (set.has(file.file_uuid)) file.tags = [...tags]
    })
    trashFiles.value.forEach(file => {
      if (set.has(file.file_uuid)) file.tags = [...tags]
    })
  }

  async function softDeleteFile(fileUuid: string) {
    await excelFileAPI.deleteFile(fileUuid)
    const idx = files.value.findIndex(f => f.file_uuid === fileUuid)
    if (idx >= 0) {
      const [removed] = files.value.splice(idx, 1)
      trashFiles.value.unshift({ ...removed, deleted_at: new Date().toISOString() })
    }
  }

  async function restoreFile(fileUuid: string) {
    await excelFileAPI.restoreFile(fileUuid)
    const idx = trashFiles.value.findIndex(f => f.file_uuid === fileUuid)
    if (idx >= 0) {
      const [restored] = trashFiles.value.splice(idx, 1)
      files.value.unshift(restored)
    }
  }

  async function permanentDeleteFile(fileUuid: string) {
    await excelFileAPI.permanentDeleteFile(fileUuid)
    trashFiles.value = trashFiles.value.filter(f => f.file_uuid !== fileUuid)
  }

  async function bulkDelete(fileIds: string[]) {
    await excelFileAPI.bulkDeleteFiles(fileIds)
    const set = new Set(fileIds)
    const removed = files.value.filter(f => set.has(f.file_uuid))
    files.value = files.value.filter(f => !set.has(f.file_uuid))
    removed.forEach(f => trashFiles.value.unshift({ ...f, deleted_at: new Date().toISOString() }))
  }

  async function bulkMove(fileIds: string[], folderId: string | null, subfolderId: string | null = null) {
    await excelFileAPI.bulkMoveFiles(fileIds, folderId, subfolderId)
    const set = new Set(fileIds)
    files.value.forEach(f => {
      if (set.has(f.file_uuid)) {
        f.project_id = folderId ?? undefined
        f.subproject_id = subfolderId ?? undefined
      }
    })
  }

  return {
    // State
    files, trashFiles, projects, isLoading, isLoadingProjects,
    searchQuery, filterTags, showPinnedOnly, showFavoritesOnly,
    sortField, sortOrder, viewMode, expandedProjects,
    dashboardLayouts, dashboardLockState,
    isCompareMode, compareFileId, compareWidgets, compareFileInfo, isCompareLoading,

    // Getters
    sortedFiles, allTags, regularFolders, dashboardFolders,

    // Fetch
    fetchFiles, fetchProjects, fetchAll,

    // Folder ops
    createProject, renameProject, updateProjectColor, deleteProject,
    createSubproject, renameSubproject, deleteSubproject,

    // File ops
    moveFile, togglePin, toggleFavorite, updateTags,
    updateGroupPinned, updateGroupFavorite, updateGroupTags,
    softDeleteFile, restoreFile, permanentDeleteFile,
    bulkDelete, bulkMove,

    // Dashboard layout
    saveDashboardLayout, loadDashboardLayout, setDashboardLockState, getDashboardLockState,
    setDashboardTheme, getDashboardTheme,

    // Compare mode
    setCompareMode, setCompareWidgets, setCompareFileInfo
  }
})
