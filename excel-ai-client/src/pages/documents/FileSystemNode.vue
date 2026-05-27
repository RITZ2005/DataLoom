<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { useDocumentsStore } from '@/store/documents'
import type { TreeNode, FolderNode, FileNode, GroupNode } from '@/utils/fileTree'
import type { FileInfo } from '@/services/excelApi'

const props = withDefaults(defineProps<{
  node: TreeNode
  depth?: number
  selectedFileId?: string | null
  isTrash?: boolean
}>(), {
  depth: 0,
  selectedFileId: null,
  isTrash: false,
})

const emit = defineEmits<{
  selectFile: [file: FileInfo]
  deleteFile: [file: FileInfo]
  restoreFile: [file: FileInfo]
  chatFile: [file: FileInfo]
  uploadToFolder: [projectId: string | null, subprojectId: string | null]
  addSheet: [groupId: string]
}>()

const store = useDocumentsStore()
const router = useRouter()

// ── Expand / collapse ────────────────────────────────────────────────
const isExpanded = computed(() => {
  if (props.node.type === 'group') {
    return store.expandedProjects.has(`group-${(props.node as GroupNode).groupId}`)
  }
  if (props.node.type !== 'folder') return false
  const folder = props.node as FolderNode
  if (folder.subprojectId) {
    return store.expandedProjects.has(`sub-${folder.subprojectId}`)
  }
  return store.expandedProjects.has(folder.projectId)
})

function toggleExpand() {
  if (props.node.type === 'group') {
    const key = `group-${(props.node as GroupNode).groupId}`
    if (store.expandedProjects.has(key)) store.expandedProjects.delete(key)
    else store.expandedProjects.add(key)
    return
  }
  if (props.node.type !== 'folder') return
  const folder = props.node as FolderNode
  const key = folder.subprojectId ? `sub-${folder.subprojectId}` : folder.projectId
  if (store.expandedProjects.has(key)) {
    store.expandedProjects.delete(key)
  } else {
    store.expandedProjects.add(key)
  }
}

// ── Rename state ─────────────────────────────────────────────────────
const isRenaming = ref(false)
const renameValue = ref('')

function startRename() {
  renameValue.value = props.node.name
  isRenaming.value = true
  closeContextMenu()
}

async function finishRename() {
  const name = renameValue.value.trim()
  if (!name || props.node.type !== 'folder') {
    isRenaming.value = false
    return
  }
  const folder = props.node as FolderNode
  if (folder.subprojectId) {
    await store.renameSubproject(folder.projectId, folder.subprojectId, name)
  } else {
    await store.renameProject(folder.projectId, name)
  }
  isRenaming.value = false
}

// ── Inline create subfolder ──────────────────────────────────────────
const creatingChild = ref(false)
const newChildName = ref('')

async function handleCreateChild() {
  const name = newChildName.value.trim()
  if (!name || props.node.type !== 'folder') return
  const folder = props.node as FolderNode
  if (!folder.subprojectId) {
    // Create subproject inside this project
    await store.createSubproject(folder.projectId, name)
    // Auto-expand
    const key = folder.projectId
    store.expandedProjects.add(key)
  }
  newChildName.value = ''
  creatingChild.value = false
}

// ── Three-dot menu (folders only) ────────────────────────────────────
const showDotMenu = ref(false)

// ── Context menu ─────────────────────────────────────────────────────
const ctxMenu = ref<{ x: number; y: number } | null>(null)

const FOLDER_COLORS = ['#3b82f6', '#ef4444', '#22c55e', '#f59e0b', '#8b5cf6', '#ec4899', '#06b6d4', '#6b7280']

function openContextMenu(e: MouseEvent) {
  e.preventDefault()
  e.stopPropagation()
  ctxMenu.value = { x: e.clientX, y: e.clientY }
}

function closeContextMenu() {
  ctxMenu.value = null
  showDotMenu.value = false
}

function emitUploadHere() {
  if (props.node.type !== 'folder') return
  const folder = props.node as FolderNode
  emit('uploadToFolder', folder.projectId, folder.subprojectId ?? null)
}

async function handleChangeColor(color: string) {
  if (props.node.type !== 'folder') return
  const folder = props.node as FolderNode
  await store.updateProjectColor(folder.projectId, color)
  closeContextMenu()
}

async function handleDeleteFolder() {
  if (props.node.type !== 'folder') return
  const folder = props.node as FolderNode
  if (folder.subprojectId) {
    if (!confirm('Delete this subfolder and ALL its files? This cannot be undone.')) return
    await store.deleteSubproject(folder.projectId, folder.subprojectId)
  } else {
    if (!confirm('Delete this folder and ALL its files? This cannot be undone.')) return
    await store.deleteProject(folder.projectId)
  }
  closeContextMenu()
}

function startCreateChild() {
  creatingChild.value = true
  newChildName.value = ''
  // Expand parent
  if (props.node.type === 'folder') {
    const folder = props.node as FolderNode
    store.expandedProjects.add(folder.subprojectId ? `sub-${folder.subprojectId}` : folder.projectId)
  }
  closeContextMenu()
}

// ── File-specific helpers ────────────────────────────────────────────
const showTagInput = ref(false)
const tagInputValue = ref('')
const showMoveDialog = ref(false)

function getGroupFiles() {
  return props.node.type === 'group' ? (props.node as GroupNode).children.map(child => child.data) : []
}

function getGroupFileIds() {
  return getGroupFiles().map(file => file.file_uuid)
}

function getGroupRepresentativeFile() {
  return getGroupFiles()[0] ?? null
}

function isGroupPinned() {
  const files = getGroupFiles()
  return files.length > 0 && files.every(file => file.is_pinned)
}

function isGroupFavorited() {
  const files = getGroupFiles()
  return files.length > 0 && files.every(file => file.is_favorite)
}

function getGroupTags() {
  const tagSet = new Set<string>()
  getGroupFiles().forEach(file => (file.tags || []).forEach(tag => tagSet.add(tag)))
  return Array.from(tagSet)
}

function openTagInput() {
  if (props.node.type === 'file') {
    const file = (props.node as FileNode).data
    tagInputValue.value = (file.tags || []).join(', ')
  } else if (props.node.type === 'group') {
    tagInputValue.value = getGroupTags().join(', ')
  } else {
    return
  }
  showTagInput.value = true
  closeContextMenu()
}

function closeTagInput() {
  showTagInput.value = false
}

async function saveTags() {
  const tags = tagInputValue.value.split(',').map(t => t.trim()).filter(Boolean)
  if (props.node.type === 'file') {
    const file = (props.node as FileNode).data
    await store.updateTags(file.file_uuid, tags)
  } else if (props.node.type === 'group') {
    await store.updateGroupTags(getGroupFileIds(), tags)
  } else {
    return
  }
  showTagInput.value = false
}

async function handlePin() {
  if (props.node.type === 'file') {
    await store.togglePin((props.node as FileNode).data.file_uuid)
  } else if (props.node.type === 'group') {
    await store.updateGroupPinned(getGroupFileIds(), !isGroupPinned())
  } else {
    return
  }
  closeContextMenu()
}

async function handleFavorite() {
  if (props.node.type === 'file') {
    await store.toggleFavorite((props.node as FileNode).data.file_uuid)
  } else if (props.node.type === 'group') {
    await store.updateGroupFavorite(getGroupFileIds(), !isGroupFavorited())
  } else {
    return
  }
  closeContextMenu()
}

async function handleMoveFile(folderId: string | null, subId: string | null = null) {
  if (props.node.type !== 'file') return
  await store.moveFile((props.node as FileNode).data.file_uuid, folderId, subId)
  showMoveDialog.value = false
  closeContextMenu()
}

function handleDeleteFile() {
  if (props.node.type === 'file') {
    emit('deleteFile', (props.node as FileNode).data)
  } else if (props.node.type === 'group') {
    const representative = getGroupRepresentativeFile()
    if (representative) emit('deleteFile', representative)
  } else {
    return
  }
  closeContextMenu()
}

async function handleDeleteGroup() {
  if (props.node.type !== 'group') return
  const prompt = props.isTrash
    ? `Permanently delete workbook "${props.node.name}" and all extracted sheets? This cannot be undone.`
    : `Delete workbook "${props.node.name}" and all extracted sheets? This cannot be undone.`
  if (!confirm(prompt)) return
  if (props.isTrash) {
    await Promise.all(getGroupFileIds().map(fileUuid => store.permanentDeleteFile(fileUuid)))
  } else {
    await store.bulkDelete(getGroupFileIds())
  }
  closeContextMenu()
}

async function handleRestoreGroup() {
  if (props.node.type !== 'group') return
  await Promise.all(getGroupFileIds().map(fileUuid => store.restoreFile(fileUuid)))
  closeContextMenu()
}

async function handleMoveGroup(folderId: string | null, subId: string | null = null) {
  if (props.node.type !== 'group') return
  await store.bulkMove(getGroupFileIds(), folderId, subId)
  showMoveDialog.value = false
  closeContextMenu()
}

function handleGroupChat() {
  const representative = getGroupRepresentativeFile()
  if (!representative) return
  emit('chatFile', representative)
  closeContextMenu()
}

const indentPx = computed(() => `${props.depth * 16}px`)
</script>

<template>
  <!-- ═══ FOLDER NODE ═══ -->
  <template v-if="node.type === 'folder'">
    <div class="group flex items-center" @contextmenu="openContextMenu">
      <!-- Indent spacer -->
      <div :style="{ width: indentPx }" class="flex-shrink-0" />

      <!-- Rename mode -->
      <div v-if="isRenaming" class="flex-1 flex items-center gap-1 py-0.5 pr-1">
        <Input
          v-model="renameValue"
          class="h-6 text-xs flex-1"
          @keyup.enter="finishRename"
          @keyup.escape="isRenaming = false"
          autofocus
        />
        <Button variant="default" size="sm" class="h-6 px-1.5" @click="finishRename">
          <iconify-icon icon="lucide:check" class="h-3 w-3" />
        </Button>
      </div>

      <!-- Normal folder row -->
      <button
        v-else
        class="flex-1 flex items-center gap-1.5 py-1 px-1.5 rounded-md text-sm transition-colors duration-100 min-w-0
               hover:bg-muted/70 active:bg-muted text-foreground/90"
        @click="toggleExpand"
      >
        <iconify-icon
          :icon="isExpanded ? 'lucide:chevron-down' : 'lucide:chevron-right'"
          class="h-3.5 w-3.5 flex-shrink-0 text-foreground/60 transition-transform duration-150"
          style="stroke-width: 2.5"
        />
        <iconify-icon
          :icon="isExpanded ? 'lucide:folder-open' : 'lucide:folder'"
          class="h-4 w-4 flex-shrink-0"
          :style="(node as FolderNode).color ? { color: (node as FolderNode).color } : {}"
        />
        <span class="truncate text-[13px] font-medium">{{ node.name }}</span>
        <span class="ml-auto text-[11px] text-muted-foreground/70 flex-shrink-0 tabular-nums pr-0.5">
          {{ (node as FolderNode).fileCount }}
        </span>
      </button>

      <!-- Hover actions for folder: + upload  |  ⋯ menu -->
      <div class="hidden group-hover:flex items-center gap-0.5 flex-shrink-0 mr-1" @click.stop>
        <!-- + Add file here -->
        <button
          @click="emitUploadHere"
          class="p-0.5 rounded hover:bg-muted transition-colors"
          title="Upload file here"
        >
          <iconify-icon icon="lucide:plus" class="h-3.5 w-3.5 text-muted-foreground" />
        </button>
        <!-- ⋯ Three-dot menu (only for project-level folders) -->
        <div v-if="!(node as FolderNode).subprojectId" class="relative">
          <button
            @click="showDotMenu = !showDotMenu"
            class="p-0.5 rounded hover:bg-muted transition-colors"
            title="More actions"
          >
            <iconify-icon icon="lucide:ellipsis" class="h-3.5 w-3.5 text-muted-foreground" />
          </button>
          <!-- Dropdown -->
          <div v-if="showDotMenu" class="fixed inset-0 z-[99]" @click="showDotMenu = false" />
          <div
            v-if="showDotMenu"
            class="absolute right-0 top-full mt-0.5 z-[100] min-w-[150px] rounded-lg border bg-popover shadow-xl p-1 text-sm"
          >
            <button class="w-full text-left px-3 py-1.5 rounded hover:bg-muted flex items-center gap-2 text-xs" @click="startCreateChild(); showDotMenu = false">
              <iconify-icon icon="lucide:folder-plus" class="h-3.5 w-3.5" /> Add Subfolder
            </button>
            <button class="w-full text-left px-3 py-1.5 rounded hover:bg-muted flex items-center gap-2 text-xs" @click="startRename(); showDotMenu = false">
              <iconify-icon icon="lucide:pencil" class="h-3.5 w-3.5" /> Rename
            </button>
            <div class="border-t my-0.5" />
            <button class="w-full text-left px-3 py-1.5 rounded hover:bg-destructive/10 text-destructive flex items-center gap-2 text-xs" @click="handleDeleteFolder(); showDotMenu = false">
              <iconify-icon icon="lucide:trash-2" class="h-3.5 w-3.5" /> Delete
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- Children (expanded) -->
    <template v-if="isExpanded">
      <FileSystemNode
        v-for="child in (node as FolderNode).children"
        :key="child.id"
        :node="child"
        :depth="depth + 1"
        :selectedFileId="selectedFileId"
        :isTrash="isTrash"
        @selectFile="(f: FileInfo) => emit('selectFile', f)"
        @deleteFile="(f: FileInfo) => emit('deleteFile', f)"
        @restoreFile="(f: FileInfo) => emit('restoreFile', f)"
        @chatFile="(f: FileInfo) => emit('chatFile', f)"
        @uploadToFolder="(pId: string | null, sId: string | null) => emit('uploadToFolder', pId, sId)"
        @addSheet="(gId: string) => emit('addSheet', gId)"
      />

      <!-- Inline create subfolder input -->
      <div v-if="creatingChild" class="flex items-center gap-1 py-0.5" :style="{ paddingLeft: `${(depth + 1) * 16 + 6}px` }">
        <Input
          v-model="newChildName"
          placeholder="Subfolder name"
          class="h-6 text-xs flex-1"
          @keyup.enter="handleCreateChild"
          @keyup.escape="creatingChild = false"
          autofocus
        />
        <Button variant="default" size="sm" class="h-6 px-1.5 text-[10px]" @click="handleCreateChild" :disabled="!newChildName.trim()">
          <iconify-icon icon="lucide:check" class="h-3 w-3" />
        </Button>
        <Button variant="ghost" size="sm" class="h-6 w-6 px-0" @click="creatingChild = false">
          <iconify-icon icon="lucide:x" class="h-3 w-3" />
        </Button>
      </div>
    </template>

    <!-- Folder context menu -->
    <Teleport to="body">
      <div
        v-if="ctxMenu"
        class="fixed z-[100] min-w-[160px] rounded-lg border bg-popover shadow-xl p-1 text-sm"
        :style="{ left: ctxMenu.x + 'px', top: ctxMenu.y + 'px' }"
        @click.stop
      >
        <button class="w-full text-left px-3 py-1.5 rounded hover:bg-muted flex items-center gap-2" @click="startRename">
          <iconify-icon icon="lucide:pencil" class="h-3.5 w-3.5" /> Rename
        </button>
        <button
          v-if="!(node as FolderNode).subprojectId"
          class="w-full text-left px-3 py-1.5 rounded hover:bg-muted flex items-center gap-2"
          @click="startCreateChild"
        >
          <iconify-icon icon="lucide:folder-plus" class="h-3.5 w-3.5" /> Add Subfolder
        </button>
        <!-- Color picker (only for project-level folders) -->
        <div v-if="!(node as FolderNode).subprojectId" class="px-3 py-1.5">
          <p class="text-xs text-muted-foreground mb-1">Color</p>
          <div class="flex gap-1 flex-wrap">
            <button
              v-for="c in FOLDER_COLORS"
              :key="c"
              @click="handleChangeColor(c)"
              class="w-5 h-5 rounded-full border-2 transition-all hover:scale-110"
              :class="(node as FolderNode).color === c ? 'border-foreground' : 'border-transparent'"
              :style="{ backgroundColor: c }"
            />
          </div>
        </div>
        <div class="border-t my-1" />
        <button class="w-full text-left px-3 py-1.5 rounded hover:bg-destructive/10 text-destructive flex items-center gap-2" @click="handleDeleteFolder">
          <iconify-icon icon="lucide:trash-2" class="h-3.5 w-3.5" /> Delete
        </button>
      </div>
      <div v-if="ctxMenu" class="fixed inset-0 z-[99]" @click="closeContextMenu" @contextmenu.prevent="closeContextMenu" />
    </Teleport>
  </template>

  <!-- ═══ GROUP NODE (multi-sheet Excel) ═══ -->
  <template v-else-if="node.type === 'group'">
    <div class="group flex items-center">
      <div :style="{ width: indentPx }" class="flex-shrink-0" />
      <button
        class="flex-1 flex items-center gap-1.5 py-1 px-1.5 rounded-md text-sm transition-colors duration-100 min-w-0
               hover:bg-muted/70 active:bg-muted text-foreground/90"
        @click="toggleExpand"
      >
        <iconify-icon
          :icon="isExpanded ? 'lucide:chevron-down' : 'lucide:chevron-right'"
          class="h-3.5 w-3.5 flex-shrink-0 text-foreground/60 transition-transform duration-150"
          style="stroke-width: 2.5"
        />
        <iconify-icon
          icon="lucide:layers"
          class="h-4 w-4 flex-shrink-0 text-blue-500"
        />
        <span class="truncate text-[13px] font-medium">{{ node.name }}</span>
        <span class="ml-auto text-[11px] text-muted-foreground/70 flex-shrink-0 tabular-nums pr-0.5">
          {{ (node as GroupNode).sheetCount }} sheet{{ (node as GroupNode).sheetCount !== 1 ? 's' : '' }}
        </span>
      </button>

      <iconify-icon v-if="isGroupPinned()" icon="lucide:pin" class="h-2.5 w-2.5 text-primary/70 flex-shrink-0" />
      <iconify-icon v-if="isGroupFavorited()" icon="lucide:star" class="h-2.5 w-2.5 text-amber-500 flex-shrink-0" />

      <div class="relative flex items-center gap-0.5 flex-shrink-0 mr-1" @click.stop>
        <button
          @click="emit('addSheet', (node as GroupNode).groupId)"
          class="p-0.5 rounded hover:bg-muted transition-colors"
          title="Add another sheet from this file"
        >
          <iconify-icon icon="lucide:plus" class="h-3.5 w-3.5 text-muted-foreground" />
        </button>

        <button
          @click="showDotMenu = !showDotMenu"
          class="p-0.5 rounded hover:bg-muted transition-colors"
          title="Workbook actions"
        >
          <iconify-icon icon="lucide:ellipsis" class="h-3.5 w-3.5 text-muted-foreground" />
        </button>

        <div v-if="showDotMenu" class="fixed inset-0 z-[99]" @click="showDotMenu = false" />
        <div
          v-if="showDotMenu"
          class="absolute right-0 top-full mt-1 z-[100] min-w-[190px] rounded-lg border bg-popover p-1 text-sm shadow-xl"
        >
          <button v-if="!isTrash" class="w-full text-left px-3 py-1.5 rounded hover:bg-muted flex items-center gap-2" @click="handleGroupChat(); showDotMenu = false">
            <iconify-icon icon="lucide:message-square" class="h-3.5 w-3.5" /> Chat with Data
          </button>
          <button v-if="!isTrash" class="w-full text-left px-3 py-1.5 rounded hover:bg-muted flex items-center gap-2" @click="handlePin(); showDotMenu = false">
            <iconify-icon :icon="isGroupPinned() ? 'lucide:pin-off' : 'lucide:pin'" class="h-3.5 w-3.5" />
            {{ isGroupPinned() ? 'Unpin' : 'Pin' }}
          </button>
          <button v-if="!isTrash" class="w-full text-left px-3 py-1.5 rounded hover:bg-muted flex items-center gap-2" @click="handleFavorite(); showDotMenu = false">
            <iconify-icon :icon="isGroupFavorited() ? 'lucide:star-off' : 'lucide:star'" class="h-3.5 w-3.5" />
            {{ isGroupFavorited() ? 'Unfavorite' : 'Favorite' }}
          </button>
          <button v-if="!isTrash" class="w-full text-left px-3 py-1.5 rounded hover:bg-muted flex items-center gap-2" @click="openTagInput(); showDotMenu = false">
            <iconify-icon icon="lucide:tag" class="h-3.5 w-3.5" /> Edit Tags
          </button>
          <button v-if="!isTrash" class="w-full text-left px-3 py-1.5 rounded hover:bg-muted flex items-center gap-2" @click="showMoveDialog = true; showDotMenu = false">
            <iconify-icon icon="lucide:folder-input" class="h-3.5 w-3.5" /> Move to...
          </button>
          <div class="border-t my-1" />
          <button v-if="isTrash" class="w-full text-left px-3 py-1.5 rounded hover:bg-muted flex items-center gap-2" @click="handleRestoreGroup(); showDotMenu = false">
            <iconify-icon icon="lucide:undo-2" class="h-3.5 w-3.5" /> Restore
          </button>
          <button class="w-full text-left px-3 py-1.5 rounded hover:bg-destructive/10 text-destructive flex items-center gap-2" @click="handleDeleteGroup(); showDotMenu = false">
            <iconify-icon icon="lucide:trash-2" class="h-3.5 w-3.5" /> Delete
          </button>
        </div>
      </div>
    </div>

    <div v-if="showTagInput" class="flex gap-1 items-center py-0.5" :style="{ paddingLeft: `${depth * 16 + 22}px` }" @click.stop>
      <Input
        v-model="tagInputValue"
        placeholder="tag1, tag2..."
        class="h-5 text-[11px] flex-1"
        @keyup.enter="saveTags"
        @keyup.escape="closeTagInput"
        autofocus
      />
      <Button variant="default" size="sm" class="h-5 px-1.5 text-[10px]" @click="saveTags">Save</Button>
      <Button variant="ghost" size="sm" class="h-5 w-5 px-0" @click="closeTagInput" title="Close tag editor">
        <iconify-icon icon="lucide:x" class="h-3 w-3" />
      </Button>
    </div>

    <Teleport to="body">
      <div v-if="showMoveDialog" class="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4" @click="showMoveDialog = false">
        <div class="w-full max-w-sm bg-popover rounded-xl border shadow-2xl p-4 space-y-3" @click.stop>
          <h3 class="text-sm font-semibold flex items-center gap-2">
            <iconify-icon icon="lucide:folder-input" class="h-4 w-4 text-primary" />
            Move "{{ node.name }}"
          </h3>
          <div class="max-h-60 overflow-y-auto space-y-1">
            <button @click="handleMoveGroup(null, null)" class="w-full text-left text-sm px-3 py-2 rounded-md hover:bg-muted flex items-center gap-2">
              <iconify-icon icon="lucide:inbox" class="h-4 w-4 text-muted-foreground" /> Root Directory
            </button>
            <template v-for="p in store.projects" :key="p.project_id">
              <button @click="handleMoveGroup(p.project_id, null)" class="w-full text-left text-sm px-3 py-2 rounded-md hover:bg-muted flex items-center gap-2">
                <iconify-icon icon="lucide:folder" class="h-4 w-4" :style="p.color ? { color: p.color } : {}" />
                {{ p.name }}
              </button>
              <button
                v-for="sub in p.subprojects"
                :key="sub.subproject_id"
                @click="handleMoveGroup(p.project_id, sub.subproject_id)"
                class="w-full text-left text-sm pl-8 pr-3 py-1.5 rounded-md hover:bg-muted flex items-center gap-2"
              >
                <iconify-icon icon="lucide:folder-open" class="h-3.5 w-3.5" /> {{ sub.name }}
              </button>
            </template>
          </div>
          <div class="flex justify-end">
            <Button variant="ghost" size="sm" @click="showMoveDialog = false">Cancel</Button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- Sheet children (expanded) -->
    <template v-if="isExpanded">
      <div
        v-for="child in (node as GroupNode).children"
        :key="child.id"
        class="group flex items-center gap-1.5 py-1 px-1.5 rounded-md cursor-pointer transition-all duration-100 border-l-[3px]"
        :class="selectedFileId === child.data.file_uuid
          ? 'border-l-primary bg-primary/8 text-foreground'
          : 'hover:bg-muted/60 text-foreground/80 border-l-transparent hover:border-l-muted-foreground/30'"
        :style="{ paddingLeft: `${(depth + 1) * 16 + 6}px` }"
        @click="emit('selectFile', child.data)"
      >
        <iconify-icon icon="lucide:table" class="h-3.5 w-3.5 flex-shrink-0 text-emerald-500/80" />
        <div class="flex-1 min-w-0">
          <span class="truncate text-sm block leading-tight" :title="child.data.sheet_name ?? child.name">
            {{ child.data.sheet_name ?? child.name }}
          </span>
          <div class="flex items-center gap-1 mt-0.5">
            <span class="inline-flex items-center gap-0.5 text-[10px] text-muted-foreground/60 bg-muted/60 rounded px-1 py-px">
              <iconify-icon icon="lucide:rows-3" class="h-2.5 w-2.5" />
              {{ child.data.total_rows?.toLocaleString() ?? '?' }}
            </span>
          </div>
        </div>
      </div>
    </template>
  </template>

  <!-- ═══ FILE NODE ═══ -->
  <template v-else-if="node.type === 'file'">
    <div
      class="group flex items-center gap-1.5 py-1 px-1.5 rounded-md cursor-pointer transition-all duration-100 border-l-[3px]"
      :class="selectedFileId === (node as FileNode).data.file_uuid
        ? 'border-l-primary bg-primary/8 text-foreground'
        : 'hover:bg-muted/60 text-foreground/80 border-l-transparent hover:border-l-muted-foreground/30'"
      :style="{ paddingLeft: `${depth * 16 + 6}px` }"
      @click="emit('selectFile', (node as FileNode).data)"
    >
      <!-- File icon -->
      <iconify-icon icon="lucide:file-spreadsheet" class="h-4 w-4 flex-shrink-0 text-primary" />

      <!-- File name + metadata -->
      <div class="flex-1 min-w-0">
        <span class="truncate text-sm block leading-tight" :title="node.name">{{ node.name }}</span>
        <div class="flex items-center gap-1 mt-0.5">
          <span class="inline-flex items-center gap-0.5 text-[10px] text-muted-foreground/60 bg-muted/60 rounded px-1 py-px">
            <iconify-icon icon="lucide:rows-3" class="h-2.5 w-2.5" />
            {{ (node as FileNode).data.total_rows?.toLocaleString() ?? '?' }}
          </span>
          <span class="inline-flex items-center gap-0.5 text-[10px] text-muted-foreground/60 bg-muted/60 rounded px-1 py-px">
            <iconify-icon icon="lucide:columns-3" class="h-2.5 w-2.5" />
            {{ (node as FileNode).data.columns?.length ?? '?' }}
          </span>
        </div>
      </div>

      <!-- Status icons inline -->
      <iconify-icon
        v-if="(node as FileNode).data.is_pinned"
        icon="lucide:pin"
        class="h-2.5 w-2.5 text-primary/70 flex-shrink-0"
      />
      <iconify-icon
        v-if="(node as FileNode).data.is_favorite"
        icon="lucide:star"
        class="h-2.5 w-2.5 text-amber-500 flex-shrink-0"
      />

      <div class="relative ml-auto flex items-center" @click.stop>
        <button
          class="flex h-6 w-6 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          title="More actions"
          @click="showDotMenu = !showDotMenu"
        >
          <iconify-icon icon="lucide:ellipsis" class="h-3.5 w-3.5" />
        </button>

        <div v-if="showDotMenu" class="fixed inset-0 z-[99]" @click="showDotMenu = false" />
        <div
          v-if="showDotMenu"
          class="absolute right-0 top-full z-[100] mt-1 min-w-[180px] rounded-lg border bg-popover p-1 text-sm shadow-xl"
        >
          <button v-if="!isTrash" class="w-full text-left px-3 py-1.5 rounded hover:bg-muted flex items-center gap-2" @click="emit('chatFile', (node as FileNode).data); showDotMenu = false">
            <iconify-icon icon="lucide:message-square" class="h-3.5 w-3.5" /> Chat with Data
          </button>
          <button v-if="!isTrash" class="w-full text-left px-3 py-1.5 rounded hover:bg-muted flex items-center gap-2" @click="handlePin(); showDotMenu = false">
            <iconify-icon :icon="(node as FileNode).data.is_pinned ? 'lucide:pin-off' : 'lucide:pin'" class="h-3.5 w-3.5" />
            {{ (node as FileNode).data.is_pinned ? 'Unpin' : 'Pin' }}
          </button>
          <button v-if="!isTrash" class="w-full text-left px-3 py-1.5 rounded hover:bg-muted flex items-center gap-2" @click="handleFavorite(); showDotMenu = false">
            <iconify-icon :icon="(node as FileNode).data.is_favorite ? 'lucide:star-off' : 'lucide:star'" class="h-3.5 w-3.5" />
            {{ (node as FileNode).data.is_favorite ? 'Unfavorite' : 'Favorite' }}
          </button>
          <button v-if="!isTrash" class="w-full text-left px-3 py-1.5 rounded hover:bg-muted flex items-center gap-2" @click="openTagInput(); showDotMenu = false">
            <iconify-icon icon="lucide:tag" class="h-3.5 w-3.5" /> Edit Tags
          </button>
          <button v-if="!isTrash" class="w-full text-left px-3 py-1.5 rounded hover:bg-muted flex items-center gap-2" @click="showMoveDialog = true; showDotMenu = false">
            <iconify-icon icon="lucide:folder-input" class="h-3.5 w-3.5" /> Move to...
          </button>
          <div class="border-t my-1" />
          <button v-if="isTrash" class="w-full text-left px-3 py-1.5 rounded hover:bg-muted flex items-center gap-2" @click="emit('restoreFile', (node as FileNode).data); showDotMenu = false">
            <iconify-icon icon="lucide:undo-2" class="h-3.5 w-3.5" /> Restore
          </button>
          <button class="w-full text-left px-3 py-1.5 rounded hover:bg-destructive/10 text-destructive flex items-center gap-2" @click="handleDeleteFile(); showDotMenu = false">
            <iconify-icon icon="lucide:trash-2" class="h-3.5 w-3.5" /> Delete
          </button>
        </div>
      </div>
    </div>

    <!-- Tag input inline (shows below the file row) -->
    <div v-if="showTagInput" class="flex gap-1 items-center py-0.5" :style="{ paddingLeft: `${depth * 16 + 22}px` }" @click.stop>
      <Input
        v-model="tagInputValue"
        placeholder="tag1, tag2..."
        class="h-5 text-[11px] flex-1"
        @keyup.enter="saveTags"
        @keyup.escape="closeTagInput"
        autofocus
      />
      <Button variant="default" size="sm" class="h-5 px-1.5 text-[10px]" @click="saveTags">Save</Button>
      <Button variant="ghost" size="sm" class="h-5 w-5 px-0" @click="closeTagInput" title="Close tag editor">
        <iconify-icon icon="lucide:x" class="h-3 w-3" />
      </Button>
    </div>
    <!-- Move dialog -->
    <Teleport to="body">
      <div v-if="showMoveDialog" class="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4" @click="showMoveDialog = false">
        <div class="w-full max-w-sm bg-popover rounded-xl border shadow-2xl p-4 space-y-3" @click.stop>
          <h3 class="text-sm font-semibold flex items-center gap-2">
            <iconify-icon icon="lucide:folder-input" class="h-4 w-4 text-primary" />
            Move "{{ node.name }}"
          </h3>
          <div class="max-h-60 overflow-y-auto space-y-1">
            <button @click="handleMoveFile(null, null)" class="w-full text-left text-sm px-3 py-2 rounded-md hover:bg-muted flex items-center gap-2">
              <iconify-icon icon="lucide:inbox" class="h-4 w-4 text-muted-foreground" /> Root Directory
            </button>
            <template v-for="p in store.projects" :key="p.project_id">
              <button @click="handleMoveFile(p.project_id, null)" class="w-full text-left text-sm px-3 py-2 rounded-md hover:bg-muted flex items-center gap-2">
                <iconify-icon icon="lucide:folder" class="h-4 w-4" :style="p.color ? { color: p.color } : {}" />
                {{ p.name }}
              </button>
              <button
                v-for="sub in p.subprojects"
                :key="sub.subproject_id"
                @click="handleMoveFile(p.project_id, sub.subproject_id)"
                class="w-full text-left text-sm pl-8 pr-3 py-1.5 rounded-md hover:bg-muted flex items-center gap-2"
              >
                <iconify-icon icon="lucide:folder-open" class="h-3.5 w-3.5" /> {{ sub.name }}
              </button>
            </template>
          </div>
          <div class="flex justify-end">
            <Button variant="ghost" size="sm" @click="showMoveDialog = false">Cancel</Button>
          </div>
        </div>
      </div>
    </Teleport>
  </template>
</template>
