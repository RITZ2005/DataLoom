import type { FileInfo, ProjectInfo } from '@/services/excelApi'

// ── Tree-node types ──────────────────────────────────────────────────

export interface FolderNode {
  type: 'folder'
  id: string
  name: string
  color?: string
  /** project / subproject metadata */
  projectId: string
  subprojectId?: string
  children: TreeNode[]
  fileCount: number
}

export interface FileNode {
  type: 'file'
  id: string
  name: string
  data: FileInfo
}

/**
 * Represents a parent Excel file whose individual sheets have been extracted
 * as separate file records grouped under the same `file_group_id`.
 */
export interface GroupNode {
  type: 'group'
  id: string          // group_id
  name: string        // derived display name (original filename without extension)
  originalFilename: string
  groupId: string
  children: FileNode[]
  sheetCount: number
}

export type TreeNode = FolderNode | FileNode | GroupNode

// ── Builder ──────────────────────────────────────────────────────────

/**
 * Converts flat files[] + projects[] into a nested tree that mirrors a
 * VS Code–style file explorer.
 *
 * Structure produced:
 *   ├─ <Project folders>
 *   │   ├─ <Subproject sub-folders>
 *   │   │   └─ files inside the subproject
 *   │   └─ files directly in the project (no subproject)
 *   └─ <Loose files> (no project_id — "root directory" files)
 */
export function buildFileTree(
  files: FileInfo[],
  projects: ProjectInfo[]
): TreeNode[] {
  const tree: TreeNode[] = []

  // — Separate grouped vs normal files ———————————————————————————
  const groupedFileMap = new Map<string, FileInfo[]>()  // group_id → sheets
  const ungroupedFiles: FileInfo[] = []

  for (const f of files) {
    if (f.file_group_id) {
      const arr = groupedFileMap.get(f.file_group_id) ?? []
      arr.push(f)
      groupedFileMap.set(f.file_group_id, arr)
    } else {
      ungroupedFiles.push(f)
    }
  }

  // Build lookup: projectId → ungrouped files, subprojectId → ungrouped files
  const projectFileMap = new Map<string, FileInfo[]>()
  const subprojectFileMap = new Map<string, FileInfo[]>()
  const rootFiles: FileInfo[] = []

  for (const f of ungroupedFiles) {
    if (f.subproject_id) {
      const arr = subprojectFileMap.get(f.subproject_id) ?? []
      arr.push(f)
      subprojectFileMap.set(f.subproject_id, arr)
    } else if (f.project_id) {
      const arr = projectFileMap.get(f.project_id) ?? []
      arr.push(f)
      projectFileMap.set(f.project_id, arr)
    } else {
      rootFiles.push(f)
    }
  }

  // Build a map of GroupNodes keyed by group_id,
  // and bucket them by subproject / project / root using the first sheet's location.
  const groupNodeMap = new Map<string, GroupNode>()
  const projectGroupMap = new Map<string, GroupNode[]>()
  const subprojectGroupMap = new Map<string, GroupNode[]>()
  const rootGroups: GroupNode[] = []

  for (const [groupId, sheets] of groupedFileMap.entries()) {
    // Derive display name: strip the " [SheetName]" suffix from the first file's filename
    const firstName = sheets[0].filename
    const baseName = firstName.replace(/\s*\[.*?\]$/, '')
    const name = baseName.replace(/\.(xlsx|xls)$/i, '')
    const node: GroupNode = {
      type: 'group',
      id: `group-${groupId}`,
      name,
      originalFilename: baseName,
      groupId,
      children: sheets.map(fileToNode),
      sheetCount: sheets.length,
    }
    groupNodeMap.set(groupId, node)

    // All sheets in a group share the same project/subproject — use the first sheet
    const rep = sheets[0]
    if (rep.subproject_id) {
      const arr = subprojectGroupMap.get(rep.subproject_id) ?? []
      arr.push(node)
      subprojectGroupMap.set(rep.subproject_id, arr)
    } else if (rep.project_id) {
      const arr = projectGroupMap.get(rep.project_id) ?? []
      arr.push(node)
      projectGroupMap.set(rep.project_id, arr)
    } else {
      rootGroups.push(node)
    }
  }

  // Create project folder nodes
  for (const project of projects) {
    const children: TreeNode[] = []

    // Add subproject folders
    for (const sub of project.subprojects ?? []) {
      const subFiles = subprojectFileMap.get(sub.subproject_id) ?? []
      const subGroups = subprojectGroupMap.get(sub.subproject_id) ?? []
      const subChildren: TreeNode[] = [
        ...subFiles.map(fileToNode),
        ...subGroups,
      ]
      const orderedSubChildren = sortNodesByPinned(subChildren)
      children.push({
        type: 'folder',
        id: `sub-${sub.subproject_id}`,
        name: sub.name,
        projectId: project.project_id,
        subprojectId: sub.subproject_id,
        children: orderedSubChildren,
        fileCount: subFiles.length + subGroups.reduce((s, g) => s + g.sheetCount, 0),
      })
    }

    // Add files and groups that belong directly to the project
    const directFiles = projectFileMap.get(project.project_id) ?? []
    const directGroups = projectGroupMap.get(project.project_id) ?? []
    for (const f of directFiles) {
      children.push(fileToNode(f))
    }
    for (const g of directGroups) {
      children.push(g)
    }

    const orderedChildren = sortNodesByPinned(children)

    const totalFileCount =
      directFiles.length +
      directGroups.reduce((s, g) => s + g.sheetCount, 0) +
      (project.subprojects ?? []).reduce(
        (sum, s) =>
          sum +
          (subprojectFileMap.get(s.subproject_id)?.length ?? 0) +
          (subprojectGroupMap.get(s.subproject_id) ?? []).reduce((a, g) => a + g.sheetCount, 0),
        0
      )

    tree.push({
      type: 'folder',
      id: `proj-${project.project_id}`,
      name: project.name,
      color: project.color,
      projectId: project.project_id,
      children: orderedChildren,
      fileCount: totalFileCount,
    })
  }

  // Append root-level files (no project)
  for (const f of rootFiles) {
    tree.push(fileToNode(f))
  }

  // Append root-level group nodes (multi-sheet files with no project)
  for (const g of rootGroups) {
    tree.push(g)
  }

  return sortNodesByPinned(tree)
}

// ── Helpers ───────────────────────────────────────────────────────────

function isPinnedNode(node: TreeNode): boolean {
  if (node.type === 'file') return Boolean(node.data.is_pinned)
  if (node.type === 'group') return node.children.length > 0 && node.children.every(child => child.data.is_pinned)
  return false
}

function sortNodesByPinned(nodes: TreeNode[]): TreeNode[] {
  const pinned: TreeNode[] = []
  const normal: TreeNode[] = []

  for (const node of nodes) {
    if (isPinnedNode(node)) pinned.push(node)
    else normal.push(node)
  }

  return [...pinned, ...normal]
}

function fileToNode(file: FileInfo): FileNode {
  return {
    type: 'file',
    id: file.file_uuid,
    name: file.filename,
    data: file,
  }
}
