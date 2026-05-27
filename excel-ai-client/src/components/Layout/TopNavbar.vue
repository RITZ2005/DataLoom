<script setup lang="ts">
import { computed, ref, watch, reactive, onMounted, onBeforeUnmount } from 'vue'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger
} from '@/components/ui/dropdown-menu'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog'
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar'
import { Separator } from '@/components/ui/separator'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import ThemeToggle from '@/components/ui/ThemeToggle.vue'
import ChangePasswordModal from '@/components/ChangePasswordModal.vue'
import { Login } from '@/store/login'
import excelFileAPI, { excelApiClient, type CategoryItem, type SavedQuestion } from '@/services/excelApi'
import { toast } from 'vue-sonner'

const loginStore = Login()
const route = useRoute()
const router = useRouter()
const showProfile = ref(false)
const showChangePasswordModal = ref(false)
const topbarShareLink = ref('')

const langfuseOn = computed(() => loginStore.userData?.langfuse_enabled ?? false)

function syncTopbarShareLink(event?: Event) {
  const custom = event as CustomEvent<string> | undefined
  if (custom?.detail !== undefined) {
    topbarShareLink.value = custom.detail || ''
  }
}

onMounted(() => {
  window.addEventListener('topbar-share-link-updated', syncTopbarShareLink as EventListener)
})

onBeforeUnmount(() => {
  window.removeEventListener('topbar-share-link-updated', syncTopbarShareLink as EventListener)
})

const isDocumentsRoute = computed(() => {
  return route.name === 'documents' || String(route.path || '').includes('/documents')
})

const activeExplorerSection = computed<'folders' | 'dashboards' | ''>(() => {
  const raw = String(route.query.explorer || '').trim().toLowerCase()
  if (raw === 'folders' || raw === 'dashboards') return raw
  return 'folders'
})

function toggleTopExplorer(section: 'folders' | 'dashboards') {
  if (!isDocumentsRoute.value) return
  const next = activeExplorerSection.value === section ? '' : section
  const nextQuery: Record<string, any> = { ...route.query }
  if (next) nextQuery.explorer = next
  else delete nextQuery.explorer
  router.replace({ query: nextQuery })
}

const activeTopSection = computed<'folders' | 'dashboards' | ''>(() => {
    const routeName = String(route.name || '')
    const routeMode = route.query.mode

    // Documents page uses explicit explorer query state.
    if (isDocumentsRoute.value) {
      if (activeExplorerSection.value === 'dashboards') return 'dashboards'
      return 'folders'
    }

    // File dashboard should check if it's database mode or excel mode.
    if (routeName === 'smart-dashboard') {
      if (routeMode === 'connection' || routeMode === 'table') return 'dashboards'
      return 'folders'
    }

  // Insight board/project/shared dashboard contexts should highlight Boards.
  if (routeName === 'smart-dashboard-project' || routeName === 'insight-board' || routeName === 'shared-dashboard') {
    return 'dashboards'
  }

  return ''
})

watch(() => route.fullPath, () => {
  if (activeTopSection.value !== 'dashboards') {
    topbarShareLink.value = ''
  }
}, { immediate: true })

function openWorkspace(explorer?: 'folders' | 'dashboards') {
  const query: Record<string, any> = { ...route.query }
  if (explorer) query.explorer = explorer
  else delete query.explorer
  router.push({ path: '/app', query })
}

// Avatar state
const avatarUrl = ref(localStorage.getItem('user-avatar') || '')
const avatarFileInput = ref<HTMLInputElement | null>(null)

// Predefined human avatar options (bitmoji-style)
interface HumanAvatar {
  id: string
  skin: string       // skin color
  hair: string       // hair color
  hairStyle: 'short' | 'long' | 'curly' | 'buzz' | 'wavy' | 'bun'
  bg: string          // gradient bg class
  bgColors: [string, string]  // actual hex for canvas
  accessory?: 'glasses' | 'sunglasses'
}

const predefinedAvatars: HumanAvatar[] = [
  { id: 'h1', skin: '#FDDCB1', hair: '#3B2314', hairStyle: 'short', bg: 'from-blue-400 to-indigo-400', bgColors: ['#60a5fa', '#818cf8'] },
  { id: 'h2', skin: '#F5C5A3', hair: '#1A1A1A', hairStyle: 'long', bg: 'from-rose-400 to-pink-400', bgColors: ['#fb7185', '#f472b6'] },
  { id: 'h3', skin: '#8D5524', hair: '#1A1A1A', hairStyle: 'curly', bg: 'from-amber-400 to-orange-400', bgColors: ['#fbbf24', '#fb923c'] },
  { id: 'h4', skin: '#FDDCB1', hair: '#C9872E', hairStyle: 'wavy', bg: 'from-emerald-400 to-teal-400', bgColors: ['#34d399', '#2dd4bf'] },
  { id: 'h5', skin: '#D4A06A', hair: '#1A1A1A', hairStyle: 'buzz', bg: 'from-violet-400 to-purple-400', bgColors: ['#a78bfa', '#c084fc'], accessory: 'glasses' },
  { id: 'h6', skin: '#F5C5A3', hair: '#D4A438', hairStyle: 'bun', bg: 'from-cyan-400 to-blue-400', bgColors: ['#22d3ee', '#60a5fa'] },
  { id: 'h7', skin: '#6B4226', hair: '#1A1A1A', hairStyle: 'short', bg: 'from-green-400 to-emerald-400', bgColors: ['#4ade80', '#34d399'], accessory: 'sunglasses' },
  { id: 'h8', skin: '#FDDCB1', hair: '#B83232', hairStyle: 'long', bg: 'from-fuchsia-400 to-pink-400', bgColors: ['#e879f9', '#f472b6'] },
  { id: 'h9', skin: '#D4A06A', hair: '#3B2314', hairStyle: 'wavy', bg: 'from-orange-400 to-amber-400', bgColors: ['#fb923c', '#fbbf24'] },
  { id: 'h10', skin: '#F5C5A3', hair: '#1A1A1A', hairStyle: 'curly', bg: 'from-sky-400 to-blue-400', bgColors: ['#38bdf8', '#60a5fa'], accessory: 'glasses' },
  { id: 'h11', skin: '#8D5524', hair: '#3B2314', hairStyle: 'bun', bg: 'from-lime-400 to-green-400', bgColors: ['#a3e635', '#4ade80'] },
  { id: 'h12', skin: '#FDDCB1', hair: '#D4A438', hairStyle: 'buzz', bg: 'from-indigo-400 to-violet-400', bgColors: ['#818cf8', '#a78bfa'] },
]

function _drawHumanAvatar(ctx: CanvasRenderingContext2D, avatar: HumanAvatar, size: number) {
  const s = size
  const cx = s / 2, cy = s / 2

  // Background gradient
  const gradient = ctx.createLinearGradient(0, 0, s, s)
  gradient.addColorStop(0, avatar.bgColors[0])
  gradient.addColorStop(1, avatar.bgColors[1])
  ctx.fillStyle = gradient
  ctx.beginPath()
  ctx.arc(cx, cy, s / 2, 0, Math.PI * 2)
  ctx.fill()

  // Neck
  ctx.fillStyle = avatar.skin
  ctx.fillRect(cx - s * 0.09, cy + s * 0.22, s * 0.18, s * 0.18)

  // Shirt/body hint at bottom
  ctx.fillStyle = avatar.bgColors[1]
  ctx.beginPath()
  ctx.ellipse(cx, cy + s * 0.46, s * 0.28, s * 0.12, 0, Math.PI, 0)
  ctx.fill()

  // Face
  ctx.fillStyle = avatar.skin
  ctx.beginPath()
  ctx.ellipse(cx, cy - s * 0.02, s * 0.22, s * 0.26, 0, 0, Math.PI * 2)
  ctx.fill()

  // Ears
  ctx.beginPath()
  ctx.ellipse(cx - s * 0.22, cy - s * 0.02, s * 0.05, s * 0.06, 0, 0, Math.PI * 2)
  ctx.fill()
  ctx.beginPath()
  ctx.ellipse(cx + s * 0.22, cy - s * 0.02, s * 0.05, s * 0.06, 0, 0, Math.PI * 2)
  ctx.fill()

  // Hair
  ctx.fillStyle = avatar.hair
  const hTop = cy - s * 0.28

  if (avatar.hairStyle === 'short') {
    ctx.beginPath()
    ctx.ellipse(cx, hTop + s * 0.06, s * 0.24, s * 0.16, 0, Math.PI, 0)
    ctx.fill()
  } else if (avatar.hairStyle === 'long') {
    ctx.beginPath()
    ctx.ellipse(cx, hTop + s * 0.06, s * 0.25, s * 0.17, 0, Math.PI, 0)
    ctx.fill()
    // Side hair
    ctx.fillRect(cx - s * 0.25, cy - s * 0.12, s * 0.06, s * 0.32)
    ctx.fillRect(cx + s * 0.19, cy - s * 0.12, s * 0.06, s * 0.32)
  } else if (avatar.hairStyle === 'curly') {
    for (let a = -3; a <= 3; a++) {
      ctx.beginPath()
      ctx.arc(cx + a * s * 0.06, hTop + s * 0.04, s * 0.09, 0, Math.PI * 2)
      ctx.fill()
    }
    ctx.beginPath()
    ctx.arc(cx - s * 0.2, cy - s * 0.06, s * 0.07, 0, Math.PI * 2)
    ctx.fill()
    ctx.beginPath()
    ctx.arc(cx + s * 0.2, cy - s * 0.06, s * 0.07, 0, Math.PI * 2)
    ctx.fill()
  } else if (avatar.hairStyle === 'buzz') {
    ctx.beginPath()
    ctx.ellipse(cx, hTop + s * 0.08, s * 0.23, s * 0.13, 0, Math.PI, 0)
    ctx.fill()
  } else if (avatar.hairStyle === 'wavy') {
    ctx.beginPath()
    ctx.ellipse(cx, hTop + s * 0.06, s * 0.26, s * 0.18, 0, Math.PI, 0)
    ctx.fill()
    // Side waves
    ctx.beginPath()
    ctx.ellipse(cx - s * 0.24, cy - s * 0.04, s * 0.06, s * 0.14, -0.15, 0, Math.PI * 2)
    ctx.fill()
    ctx.beginPath()
    ctx.ellipse(cx + s * 0.24, cy - s * 0.04, s * 0.06, s * 0.14, 0.15, 0, Math.PI * 2)
    ctx.fill()
  } else if (avatar.hairStyle === 'bun') {
    ctx.beginPath()
    ctx.ellipse(cx, hTop + s * 0.06, s * 0.24, s * 0.15, 0, Math.PI, 0)
    ctx.fill()
    // Bun on top
    ctx.beginPath()
    ctx.arc(cx, hTop - s * 0.06, s * 0.1, 0, Math.PI * 2)
    ctx.fill()
  }

  // Eyes
  ctx.fillStyle = '#FFFFFF'
  ctx.beginPath()
  ctx.ellipse(cx - s * 0.09, cy - s * 0.05, s * 0.05, s * 0.038, 0, 0, Math.PI * 2)
  ctx.fill()
  ctx.beginPath()
  ctx.ellipse(cx + s * 0.09, cy - s * 0.05, s * 0.05, s * 0.038, 0, 0, Math.PI * 2)
  ctx.fill()

  // Pupils
  ctx.fillStyle = '#2C1810'
  ctx.beginPath()
  ctx.arc(cx - s * 0.085, cy - s * 0.045, s * 0.022, 0, Math.PI * 2)
  ctx.fill()
  ctx.beginPath()
  ctx.arc(cx + s * 0.095, cy - s * 0.045, s * 0.022, 0, Math.PI * 2)
  ctx.fill()

  // Eye shine
  ctx.fillStyle = '#FFFFFF'
  ctx.beginPath()
  ctx.arc(cx - s * 0.078, cy - s * 0.052, s * 0.008, 0, Math.PI * 2)
  ctx.fill()
  ctx.beginPath()
  ctx.arc(cx + s * 0.102, cy - s * 0.052, s * 0.008, 0, Math.PI * 2)
  ctx.fill()

  // Eyebrows
  ctx.strokeStyle = avatar.hair
  ctx.lineWidth = s * 0.018
  ctx.lineCap = 'round'
  ctx.beginPath()
  ctx.moveTo(cx - s * 0.13, cy - s * 0.1)
  ctx.quadraticCurveTo(cx - s * 0.09, cy - s * 0.13, cx - s * 0.05, cy - s * 0.1)
  ctx.stroke()
  ctx.beginPath()
  ctx.moveTo(cx + s * 0.05, cy - s * 0.1)
  ctx.quadraticCurveTo(cx + s * 0.09, cy - s * 0.13, cx + s * 0.13, cy - s * 0.1)
  ctx.stroke()

  // Nose
  ctx.strokeStyle = darkenColor(avatar.skin, 0.18)
  ctx.lineWidth = s * 0.014
  ctx.beginPath()
  ctx.moveTo(cx, cy - s * 0.01)
  ctx.quadraticCurveTo(cx + s * 0.03, cy + s * 0.04, cx, cy + s * 0.05)
  ctx.stroke()

  // Mouth - smile
  ctx.strokeStyle = darkenColor(avatar.skin, 0.3)
  ctx.lineWidth = s * 0.016
  ctx.beginPath()
  ctx.moveTo(cx - s * 0.07, cy + s * 0.1)
  ctx.quadraticCurveTo(cx, cy + s * 0.16, cx + s * 0.07, cy + s * 0.1)
  ctx.stroke()

  // Cheek blush
  ctx.fillStyle = 'rgba(255, 130, 130, 0.2)'
  ctx.beginPath()
  ctx.ellipse(cx - s * 0.15, cy + s * 0.06, s * 0.04, s * 0.025, 0, 0, Math.PI * 2)
  ctx.fill()
  ctx.beginPath()
  ctx.ellipse(cx + s * 0.15, cy + s * 0.06, s * 0.04, s * 0.025, 0, 0, Math.PI * 2)
  ctx.fill()

  // Accessories
  if (avatar.accessory === 'glasses') {
    ctx.strokeStyle = '#333333'
    ctx.lineWidth = s * 0.014
    // Left lens
    ctx.beginPath()
    ctx.ellipse(cx - s * 0.09, cy - s * 0.045, s * 0.065, s * 0.048, 0, 0, Math.PI * 2)
    ctx.stroke()
    // Right lens
    ctx.beginPath()
    ctx.ellipse(cx + s * 0.09, cy - s * 0.045, s * 0.065, s * 0.048, 0, 0, Math.PI * 2)
    ctx.stroke()
    // Bridge
    ctx.beginPath()
    ctx.moveTo(cx - s * 0.025, cy - s * 0.045)
    ctx.lineTo(cx + s * 0.025, cy - s * 0.045)
    ctx.stroke()
    // Temples
    ctx.beginPath()
    ctx.moveTo(cx - s * 0.155, cy - s * 0.05)
    ctx.lineTo(cx - s * 0.22, cy - s * 0.06)
    ctx.stroke()
    ctx.beginPath()
    ctx.moveTo(cx + s * 0.155, cy - s * 0.05)
    ctx.lineTo(cx + s * 0.22, cy - s * 0.06)
    ctx.stroke()
  } else if (avatar.accessory === 'sunglasses') {
    ctx.fillStyle = 'rgba(0,0,0,0.75)'
    ctx.beginPath()
    ctx.ellipse(cx - s * 0.09, cy - s * 0.045, s * 0.068, s * 0.05, 0, 0, Math.PI * 2)
    ctx.fill()
    ctx.beginPath()
    ctx.ellipse(cx + s * 0.09, cy - s * 0.045, s * 0.068, s * 0.05, 0, 0, Math.PI * 2)
    ctx.fill()
    ctx.strokeStyle = '#222222'
    ctx.lineWidth = s * 0.018
    ctx.beginPath()
    ctx.moveTo(cx - s * 0.025, cy - s * 0.05)
    ctx.lineTo(cx + s * 0.025, cy - s * 0.05)
    ctx.stroke()
    ctx.beginPath()
    ctx.moveTo(cx - s * 0.155, cy - s * 0.05)
    ctx.lineTo(cx - s * 0.22, cy - s * 0.06)
    ctx.stroke()
    ctx.beginPath()
    ctx.moveTo(cx + s * 0.155, cy - s * 0.05)
    ctx.lineTo(cx + s * 0.22, cy - s * 0.06)
    ctx.stroke()
  }
}

function darkenColor(hex: string, amount: number): string {
  const r = Math.max(0, parseInt(hex.slice(1, 3), 16) - 255 * amount)
  const g = Math.max(0, parseInt(hex.slice(3, 5), 16) - 255 * amount)
  const b = Math.max(0, parseInt(hex.slice(5, 7), 16) - 255 * amount)
  return `rgb(${r},${g},${b})`
}

// Cache rendered avatar previews
const avatarPreviews = ref<Record<string, string>>({})

function getAvatarPreview(avatar: HumanAvatar): string {
  if (avatarPreviews.value[avatar.id]) return avatarPreviews.value[avatar.id]
  const canvas = document.createElement('canvas')
  canvas.width = 128
  canvas.height = 128
  const ctx = canvas.getContext('2d')!
  _drawHumanAvatar(ctx, avatar, 128)
  const url = canvas.toDataURL('image/png')
  avatarPreviews.value[avatar.id] = url
  return url
}

function selectPredefinedAvatar(avatar: HumanAvatar) {
  const canvas = document.createElement('canvas')
  canvas.width = 256
  canvas.height = 256
  const ctx = canvas.getContext('2d')!
  _drawHumanAvatar(ctx, avatar, 256)
  const dataUrl = canvas.toDataURL('image/png')
  avatarUrl.value = dataUrl
  localStorage.setItem('user-avatar', dataUrl)
  window.dispatchEvent(new CustomEvent('avatar-changed'))
  toast.success('Avatar updated')
}

function handleAvatarChange(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  if (file.size > 2 * 1024 * 1024) {
    toast.error('Image must be under 2 MB')
    return
  }
  const reader = new FileReader()
  reader.onload = () => {
    const dataUrl = reader.result as string
    avatarUrl.value = dataUrl
    localStorage.setItem('user-avatar', dataUrl)
    window.dispatchEvent(new CustomEvent('avatar-changed'))
    toast.success('Avatar updated')
  }
  reader.readAsDataURL(file)
}

function removeAvatar() {
  avatarUrl.value = ''
  localStorage.removeItem('user-avatar')
  window.dispatchEvent(new CustomEvent('avatar-changed'))
  toast.success('Avatar removed')
}

let _tracesRetryTimer: ReturnType<typeof setTimeout> | null = null
const tracesLoading = ref(false)

async function openTraces() {
  // Cancel any pending retry before starting fresh
  if (_tracesRetryTimer) { clearTimeout(_tracesRetryTimer); _tracesRetryTimer = null }
  tracesLoading.value = true
  try {
    const { data } = await excelApiClient.get('/api/langfuse-token', { params: { target: 'traces' } })
    tracesLoading.value = false
    const fallback = `${import.meta.env.VITE_API_URL || ''}/api/langfuse-sso`
    const url = data?.sso_url ?? fallback
    window.open(url, '_blank', 'noopener')
  } catch (err: any) {
    if (err?.response?.status === 503) {
      // Session is still being prepared — auto-retry every 3 s
      toast.info('Setting up your Traces session… opening automatically when ready.')
      _tracesRetryTimer = setTimeout(openTraces, 3000)
    } else {
      tracesLoading.value = false
      toast.error('Could not open Traces. Make sure FastAPI and Langfuse are running.')
    }
  }
}
const showCategories = ref(false)

// Category management state
const categories = ref<CategoryItem[]>([])
const allQuestions = ref<SavedQuestion[]>([])
const isLoadingCategories = ref(false)
const newCategoryName = ref('')
const isCreating = ref(false)
const editingCategoryName_original = ref<string | null>(null)
const editingCategoryName = ref('')
const deletingCategoryName = ref<string | null>(null)
const expandedCategories = reactive<Set<string>>(new Set())

// Question editing state
const editingQuestionId = ref<number | null>(null)
const editingQuestionText = ref('')
const savingQuestionId = ref<number | null>(null)

function startEditQuestion(q: SavedQuestion) {
  editingQuestionId.value = q.id
  editingQuestionText.value = q.question_text
}

function cancelEditQuestion() {
  editingQuestionId.value = null
  editingQuestionText.value = ''
}

async function saveQuestionEdit(q: SavedQuestion) {
  const text = editingQuestionText.value.trim()
  if (!text || text === q.question_text) {
    cancelEditQuestion()
    return
  }
  savingQuestionId.value = q.id
  try {
    await excelFileAPI.updateSavedQuestion(q.id, { question_text: text })
    const idx = allQuestions.value.findIndex(qItem => qItem.id === q.id)
    if (idx !== -1) allQuestions.value[idx] = { ...allQuestions.value[idx], question_text: text }
    editingQuestionId.value = null
    editingQuestionText.value = ''
    toast.success('Question updated')
  } catch (e: any) {
    toast.error(e?.response?.data?.detail || 'Failed to update question')
  } finally {
    savingQuestionId.value = null
  }
}

function toggleExpand(catName: string) {
  if (expandedCategories.has(catName)) {
    expandedCategories.delete(catName)
  } else {
    expandedCategories.add(catName)
  }
}

function questionsForCategory(catName: string) {
  return allQuestions.value.filter(q => q.question_category === catName)
}

async function loadCategories() {
  isLoadingCategories.value = true
  try {
    const [cats, questions] = await Promise.all([
      excelFileAPI.listCategories(),
      excelFileAPI.listSavedQuestions()
    ])
    categories.value = cats
    allQuestions.value = questions
  } catch (e) {
    console.error('Failed to load categories:', e)
    toast.error('Failed to load categories')
  } finally {
    isLoadingCategories.value = false
  }
}

async function createCategory() {
  const name = newCategoryName.value.trim()
  if (!name) return
  // Check duplicate locally
  if (categories.value.some(c => c.name.toLowerCase() === name.toLowerCase())) {
    toast.error(`Category "${name}" already exists`)
    return
  }
  isCreating.value = true
  // Add locally — persists when a question is bookmarked under it
  categories.value.push({ name, question_count: 0, is_default: false })
  newCategoryName.value = ''
  toast.success(`Category "${name}" created`)
  isCreating.value = false
}

function startEditing(cat: CategoryItem) {
  editingCategoryName_original.value = cat.name
  editingCategoryName.value = cat.name
}

function cancelEditing() {
  editingCategoryName_original.value = null
  editingCategoryName.value = ''
}

async function saveEditing(originalName: string) {
  const name = editingCategoryName.value.trim()
  if (!name) return
  try {
    await excelFileAPI.renameCategory(originalName, name)
    const idx = categories.value.findIndex(c => c.name === originalName)
    if (idx !== -1) categories.value[idx] = { ...categories.value[idx], name }
    editingCategoryName_original.value = null
    editingCategoryName.value = ''
    toast.success('Category renamed')
  } catch (e: any) {
    toast.error(e?.response?.data?.detail || 'Failed to rename category')
  }
}

async function deleteCategory(catName: string) {
  deletingCategoryName.value = catName
  try {
    await excelFileAPI.deleteCategory(catName)
    categories.value = categories.value.filter(c => c.name !== catName)
    allQuestions.value = allQuestions.value.filter(q => q.question_category !== catName)
    expandedCategories.delete(catName)
    toast.success('Category deleted')
  } catch (e: any) {
    toast.error(e?.response?.data?.detail || 'Failed to delete category')
  } finally {
    deletingCategoryName.value = null
  }
}

async function deleteQuestion(questionId: number, catName: string) {
  try {
    await excelFileAPI.deleteSavedQuestion(questionId)
    allQuestions.value = allQuestions.value.filter(q => q.id !== questionId)
    // Update question count on the category
    const cat = categories.value.find(c => c.name === catName)
    if (cat) cat.question_count = Math.max(0, cat.question_count - 1)
    toast.success('Question removed')
  } catch (e: any) {
    toast.error(e?.response?.data?.detail || 'Failed to delete question')
  }
}

watch(showCategories, (v) => {
  if (v) loadCategories()
})

const userInitials = computed(() => {
  const name = loginStore.userData?.name
  if (!name) return loginStore.userData?.email?.charAt(0).toUpperCase() || '?'
  const parts = name.trim().split(/\s+/)
  if (parts.length >= 2) {
    return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
  }
  return name.charAt(0).toUpperCase()
})

const displayName = computed(() => loginStore.userData?.name || loginStore.userData?.email || 'User')
const displayEmail = computed(() => loginStore.userData?.email || '')
const displayRole = computed(() => {
  const role = loginStore.userData?.role
  if (!role) return 'User'
  return role.charAt(0).toUpperCase() + role.slice(1)
})

function handleLogout() {
  loginStore.logout()
}



// Fetch user info on mount to get langfuse_enabled
onMounted(() => {
  loginStore.fetchUserInfo()
})
</script>

<template>
  <nav class="h-14 glass-nav flex gap-2 justify-between px-5 items-center">
    <div class="flex items-center gap-4">
      <div class="flex items-center gap-3">

        <div class="flex items-center">
          <span
              class="text-[34px] leading-none font-semibold tracking-tight transition-colors duration-200"
              :class="'text-gray-900 dark:text-white'"
          ><span class="dark:text-white">Excel</span>
          <span class="text-yellow-500">LOOM</span>
          </span>
        </div>
        <div class="ml-1 flex items-center gap-2.5 rounded-lg bg-transparent px-1.5 py-0.5">
          <button
            @click="openWorkspace()"
            title="Go to Workspace"
            class="h-9 w-9 rounded-md inline-flex items-center justify-center text-muted-foreground transition-all hover:bg-muted hover:text-foreground"
          >
            <iconify-icon icon="lucide:house" class="h-5 w-5" />
          </button>
          <div class="flex items-center gap-1.5 rounded-lg border border-border/45 bg-muted/25 p-1">
          <button
            @click="openWorkspace('folders')"
            title="Open Folders & Files"
            :class="[
              'h-9 rounded-md px-3.5 inline-flex items-center gap-2 text-[12px] font-semibold transition-all',
              activeTopSection === 'folders'
                ? 'bg-emerald-100/85 text-emerald-800 ring-1 ring-emerald-200/80 dark:bg-emerald-900/35 dark:text-emerald-200 dark:ring-emerald-700/45'
                : 'text-muted-foreground hover:bg-emerald-50/80 hover:text-emerald-700 dark:hover:bg-emerald-900/20 dark:hover:text-emerald-300'
            ]"
          >
            <iconify-icon icon="lucide:folder-tree" class="h-5 w-5" />
            <span>Folders &amp; Files</span>
          </button>
          <button
            @click="router.push('/app/workspaces')"
            title="Open Analytics Workspaces"
            :class="[
              'h-9 rounded-md px-3.5 inline-flex items-center gap-2 text-[12px] font-semibold transition-all',
              $route.path.includes('/app/workspaces')
                ? 'bg-amber-100/85 text-amber-800 ring-1 ring-amber-200/80 dark:bg-amber-900/35 dark:text-amber-200 dark:ring-amber-700/45'
                : 'text-muted-foreground hover:bg-amber-50 hover:text-amber-700 dark:hover:bg-amber-900/30 dark:hover:text-amber-300'
            ]"
          >
            <iconify-icon icon="lucide:briefcase" class="h-5 w-5" />
            <span>Workspaces</span>
          </button>
          <button
            @click="openWorkspace('dashboards')"
            title="Open Insight Boards"
            :class="[
              'h-9 rounded-md px-3.5 inline-flex items-center gap-2 text-[12px] font-semibold transition-all',
              activeTopSection === 'dashboards'
                ? 'bg-indigo-100/85 text-indigo-800 ring-1 ring-indigo-200/80 dark:bg-indigo-900/35 dark:text-indigo-200 dark:ring-indigo-700/45'
                : 'text-muted-foreground hover:bg-indigo-50 hover:text-indigo-700 dark:hover:bg-indigo-900/30 dark:hover:text-indigo-300'
            ]"
          >
            <iconify-icon icon="lucide:layout-dashboard" class="h-5 w-5" />
            <span>Insight Boards</span>
          </button>
          <div v-if="topbarShareLink && activeTopSection === 'dashboards'"
            class="hidden xl:flex items-center gap-1.5 rounded-lg border border-emerald-200/80 bg-emerald-50/70 px-2 py-1 text-[11px] text-emerald-700 dark:border-emerald-700/40 dark:bg-emerald-500/10 dark:text-emerald-300">
            <iconify-icon icon="lucide:link" class="h-3.5 w-3.5 shrink-0" />
            <input
              :value="topbarShareLink"
              readonly
              @focus="($event.target as HTMLInputElement).select()"
              class="w-[320px] bg-transparent font-medium outline-none"
              title="Share link (click to select, Ctrl+C to copy)"
            />
          </div>
          </div>
          <RouterLink
            to="/app/etl"
            :class="[
              'h-9 rounded-md px-3.5 inline-flex items-center gap-2 text-[12px] font-semibold transition-all',
              $route.name === 'etl-pipeline'
                ? 'bg-violet-100/85 text-violet-800 ring-1 ring-violet-200/80 dark:bg-violet-900/35 dark:text-violet-200 dark:ring-violet-700/45'
                : 'text-muted-foreground hover:bg-violet-50/80 hover:text-violet-700 dark:hover:bg-violet-900/20 dark:hover:text-violet-300'
            ]"
          >
            <iconify-icon icon="lucide:database" class="h-5 w-5" />
            <span>ETL Pipeline</span>
          </RouterLink>
        </div>
      </div>
    </div>
    <div class="flex items-center gap-3">
      <ThemeToggle />
      <DropdownMenu>
        <DropdownMenuTrigger class="focus:outline-none">
          <div class="relative group">
            <div class="absolute -inset-0.5 rounded-full bg-gradient-to-br from-primary/50 to-primary/20 opacity-0 group-hover:opacity-100 transition-opacity" />
            <Avatar class="relative h-9 w-9 ring-2 ring-border hover:ring-primary/40 transition-all cursor-pointer">
              <AvatarImage v-if="avatarUrl" :src="avatarUrl" alt="Avatar" />
              <AvatarFallback class="text-xs font-semibold bg-gradient-to-br from-primary/20 to-primary/5">{{ userInitials }}</AvatarFallback>
            </Avatar>
          </div>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" class="w-60 p-1.5 rounded-xl">
          <div class="flex items-center gap-3 px-2 py-2.5">
            <Avatar class="h-10 w-10 shrink-0">
              <AvatarImage v-if="avatarUrl" :src="avatarUrl" alt="Avatar" />
              <AvatarFallback class="text-sm font-semibold bg-gradient-to-br from-primary/20 to-primary/5">{{ userInitials }}</AvatarFallback>
            </Avatar>
            <div class="min-w-0 flex-1">
              <p class="text-sm font-semibold leading-none truncate">{{ displayName }}</p>
              <p class="text-xs text-muted-foreground mt-1 truncate">{{ displayEmail }}</p>
            </div>
          </div>
          <DropdownMenuSeparator />
          <DropdownMenuItem class="cursor-pointer rounded-lg gap-2.5 py-2" @click="showProfile = true">
            <iconify-icon icon="lucide:user" class="h-4 w-4 text-muted-foreground" /> Profile
          </DropdownMenuItem>
          <DropdownMenuItem class="cursor-pointer rounded-lg gap-2.5 py-2" @click="showCategories = true">
            <iconify-icon icon="lucide:tags" class="h-4 w-4 text-muted-foreground" /> Manage Categories
          </DropdownMenuItem>
          <DropdownMenuItem v-if="langfuseOn" class="cursor-pointer rounded-lg gap-2.5 py-2" @click="openTraces" :disabled="tracesLoading">
            <iconify-icon
              :icon="tracesLoading ? 'lucide:loader-2' : 'lucide:activity'"
              :class="['h-4 w-4 text-muted-foreground', tracesLoading && 'animate-spin']"
            /> {{ tracesLoading ? 'Opening…' : 'Traces' }}
          </DropdownMenuItem>

          <DropdownMenuSeparator />
          <DropdownMenuItem class="cursor-pointer rounded-lg gap-2.5 py-2" @click="showChangePasswordModal = true">
            <iconify-icon icon="lucide:key-round" class="h-4 w-4 text-muted-foreground" /> Change Password
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem class="text-red-500 focus:text-red-500 cursor-pointer rounded-lg gap-2.5 py-2" @click="handleLogout">
            <iconify-icon icon="lucide:log-out" class="h-4 w-4" /> Log out
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  </nav>

  <!-- Profile Dialog -->
  <Dialog v-model:open="showProfile">
    <DialogContent class="sm:max-w-md rounded-2xl">
      <DialogHeader>
        <DialogTitle class="text-lg">Profile</DialogTitle>
        <DialogDescription>Your account information</DialogDescription>
      </DialogHeader>
      <div class="flex flex-col items-center gap-5 py-6">
        <!-- Avatar with upload -->
        <div class="relative group">
          <div class="absolute -inset-1 rounded-full bg-gradient-to-br from-primary/40 via-primary/20 to-transparent blur-sm" />
          <Avatar class="relative h-24 w-24 text-3xl ring-2 ring-border shadow-lg">
            <AvatarImage v-if="avatarUrl" :src="avatarUrl" alt="Avatar" />
            <AvatarFallback class="font-semibold bg-gradient-to-br from-primary/20 to-primary/5">{{ userInitials }}</AvatarFallback>
          </Avatar>
          <button
            @click="avatarFileInput?.click()"
            class="absolute inset-0 rounded-full bg-black/50 text-white opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center"
          >
            <iconify-icon icon="lucide:camera" class="h-6 w-6" />
          </button>
          <input
            ref="avatarFileInput"
            type="file"
            accept="image/png,image/jpeg,image/webp"
            class="hidden"
            @change="handleAvatarChange"
          />
        </div>
        <div class="flex items-center gap-2">
          <Button v-if="avatarUrl" variant="ghost" size="sm" class="text-xs text-muted-foreground" @click="removeAvatar">
            <iconify-icon icon="lucide:trash-2" class="h-3 w-3 mr-1" /> Remove photo
          </Button>
          <Button variant="ghost" size="sm" class="text-xs text-muted-foreground" @click="avatarFileInput?.click()">
            <iconify-icon icon="lucide:upload" class="h-3 w-3 mr-1" /> {{ avatarUrl ? 'Change' : 'Upload' }} photo
          </Button>
        </div>
        <div class="text-center">
          <h3 class="text-lg font-semibold">{{ displayName }}</h3>
          <p class="text-sm text-muted-foreground">{{ displayEmail }}</p>
        </div>

        <!-- Predefined Avatars -->
        <div class="w-full">
          <p class="text-xs font-medium text-muted-foreground mb-2.5">Choose an avatar</p>
          <div class="grid grid-cols-6 gap-2">
            <button
              v-for="avatar in predefinedAvatars"
              :key="avatar.id"
              @click="selectPredefinedAvatar(avatar)"
              class="w-10 h-10 rounded-full overflow-hidden transition-all hover:scale-110 hover:ring-2 hover:ring-primary/50 active:scale-95"
              title="Select avatar"
            >
              <img :src="getAvatarPreview(avatar)" :alt="avatar.id" class="w-full h-full" />
            </button>
          </div>
        </div>
      </div>
      <Separator />
      <div class="space-y-4 py-3">
        <div class="flex justify-between items-center">
          <span class="text-sm text-muted-foreground">Name</span>
          <span class="text-sm font-medium">{{ displayName }}</span>
        </div>
        <div class="flex justify-between items-center">
          <span class="text-sm text-muted-foreground">Email</span>
          <span class="text-sm font-medium">{{ displayEmail }}</span>
        </div>
        <div class="flex justify-between items-center">
          <span class="text-sm text-muted-foreground">Role</span>
          <Badge variant="secondary" class="capitalize">{{ displayRole }}</Badge>
        </div>
      </div>
    </DialogContent>
  </Dialog>

  <!-- Category Management Dialog -->
  <Dialog v-model:open="showCategories">
    <DialogContent class="sm:max-w-lg">
      <DialogHeader>
        <DialogTitle class="flex items-center gap-2">
          <iconify-icon icon="lucide:tags" class="h-5 w-5 text-amber-500" />
          Manage Categories
        </DialogTitle>
        <DialogDescription>Create, rename, or delete question categories used for bookmarking and auto-replay.</DialogDescription>
      </DialogHeader>

      <!-- Create new category -->
      <div class="flex items-center gap-2 pt-2">
        <Input
          v-model="newCategoryName"
          placeholder="New category name..."
          class="h-8 text-sm flex-1"
          @keyup.enter="createCategory"
        />
        <Button size="sm" class="h-8" :disabled="!newCategoryName.trim() || isCreating" @click="createCategory">
          <iconify-icon v-if="isCreating" icon="svg-spinners:180-ring-with-bg" class="h-3.5 w-3.5 mr-1" />
          <iconify-icon v-else icon="lucide:plus" class="h-3.5 w-3.5 mr-1" />
          Add
        </Button>
      </div>

      <Separator />

      <!-- Category list -->
      <div class="max-h-[460px] overflow-y-auto space-y-1.5 pr-1">
        <div v-if="isLoadingCategories" class="text-center py-8">
          <iconify-icon icon="svg-spinners:180-ring-with-bg" class="h-6 w-6 text-muted-foreground" />
        </div>
        <div v-else-if="categories.length === 0" class="text-center py-8 text-sm text-muted-foreground">
          No categories yet. Create one above.
        </div>
        <div
          v-for="cat in categories"
          :key="cat.name"
          class="rounded-lg border overflow-hidden"
        >
          <!-- Category header row -->
          <div class="flex items-center gap-2.5 p-2.5 hover:bg-muted/30 transition-colors group cursor-pointer"
            @click="questionsForCategory(cat.name).length > 0 ? toggleExpand(cat.name) : null"
          >
            <!-- Expand chevron (only shown if questions exist) -->
            <iconify-icon
              v-if="questionsForCategory(cat.name).length > 0"
              :icon="expandedCategories.has(cat.name) ? 'lucide:chevron-down' : 'lucide:chevron-right'"
              class="h-3.5 w-3.5 text-muted-foreground flex-shrink-0 transition-transform"
            />
            <span v-else class="h-3.5 w-3.5 flex-shrink-0" />

            <!-- Category icon -->
            <iconify-icon
              :icon="cat.is_default ? 'lucide:globe' : 'lucide:tag'"
              :class="cat.is_default ? 'h-4 w-4 text-blue-500 flex-shrink-0' : 'h-4 w-4 text-amber-500 flex-shrink-0'"
            />

            <!-- Editing mode -->
            <template v-if="editingCategoryName_original === cat.name">
              <Input
                v-model="editingCategoryName"
                class="h-7 text-sm flex-1"
                @keyup.enter="saveEditing(cat.name)"
                @keyup.escape="cancelEditing"
                autofocus
                @click.stop
              />
              <Button variant="default" size="sm" class="h-7 px-2" @click.stop="saveEditing(cat.name)" :disabled="!editingCategoryName.trim()">
                <iconify-icon icon="lucide:check" class="h-3 w-3" />
              </Button>
              <Button variant="ghost" size="sm" class="h-7 px-2" @click.stop="cancelEditing">
                <iconify-icon icon="lucide:x" class="h-3 w-3" />
              </Button>
            </template>

            <!-- Display mode -->
            <template v-else>
              <div class="flex-1 min-w-0">
                <div class="flex items-center gap-1.5">
                  <span class="text-sm font-medium truncate">{{ cat.name }}</span>
                  <Badge v-if="cat.is_default" variant="outline" class="text-[10px] h-4 px-1.5 flex-shrink-0">Default</Badge>
                  <Badge v-else variant="secondary" class="text-[10px] h-4 px-1.5 flex-shrink-0">Custom</Badge>
                  <Badge v-if="questionsForCategory(cat.name).length > 0" variant="secondary" class="text-[10px] h-4 px-1.5 flex-shrink-0">
                    {{ questionsForCategory(cat.name).length }}
                  </Badge>
                </div>
              </div>
              <!-- Actions (only for non-default categories) -->
              <div v-if="!cat.is_default" class="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0">
                <Button variant="ghost" size="sm" class="h-7 w-7 px-0" @click.stop="startEditing(cat)" title="Rename">
                  <iconify-icon icon="lucide:pencil" class="h-3 w-3" />
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  class="h-7 w-7 px-0 text-red-500 hover:text-red-600"
                  @click.stop="deleteCategory(cat.name)"
                  :disabled="deletingCategoryName === cat.name"
                  title="Delete category"
                >
                  <iconify-icon :icon="deletingCategoryName === cat.name ? 'svg-spinners:180-ring-with-bg' : 'lucide:trash-2'" class="h-3 w-3" />
                </Button>
              </div>
            </template>
          </div>

          <!-- Questions list (expanded) -->
          <div v-if="expandedCategories.has(cat.name) && questionsForCategory(cat.name).length > 0"
            class="border-t bg-muted/20 divide-y divide-border/50"
          >
            <div
              v-for="q in questionsForCategory(cat.name)"
              :key="q.id"
              class="flex items-start gap-2 px-3 py-2 group/q hover:bg-muted/40 transition-colors"
            >
              <iconify-icon icon="lucide:message-square" class="h-3.5 w-3.5 mt-1 flex-shrink-0 text-muted-foreground" />

              <!-- Editing mode -->
              <template v-if="editingQuestionId === q.id">
                <Input
                  v-model="editingQuestionText"
                  class="h-7 text-xs flex-1"
                  @keyup.enter="saveQuestionEdit(q)"
                  @keyup.escape="cancelEditQuestion"
                  autofocus
                  @click.stop
                />
                <Button variant="default" size="sm" class="h-6 w-6 px-0 flex-shrink-0"
                  :disabled="!editingQuestionText.trim() || savingQuestionId === q.id"
                  @click.stop="saveQuestionEdit(q)" title="Save"
                >
                  <iconify-icon :icon="savingQuestionId === q.id ? 'svg-spinners:180-ring-with-bg' : 'lucide:check'" class="h-3 w-3" />
                </Button>
                <Button variant="ghost" size="sm" class="h-6 w-6 px-0 flex-shrink-0"
                  @click.stop="cancelEditQuestion" title="Cancel"
                >
                  <iconify-icon icon="lucide:x" class="h-3 w-3" />
                </Button>
              </template>

              <!-- Display mode -->
              <template v-else>
                <span class="text-xs text-foreground/80 flex-1 leading-relaxed">{{ q.question_text }}</span>
                <div class="flex items-center gap-0.5 opacity-0 group-hover/q:opacity-100 transition-opacity flex-shrink-0">
                  <Button variant="ghost" size="sm" class="h-6 w-6 px-0"
                    @click.stop="startEditQuestion(q)" title="Edit question"
                  >
                    <iconify-icon icon="lucide:pencil" class="h-3 w-3" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    class="h-6 w-6 px-0 text-red-400 hover:text-red-600"
                    @click.stop="deleteQuestion(q.id, cat.name)"
                    title="Remove question"
                  >
                    <iconify-icon icon="lucide:x" class="h-3 w-3" />
                  </Button>
                </div>
              </template>
            </div>
          </div>
        </div>
      </div>
    </DialogContent>
  </Dialog>

  <!-- Change Password Modal -->
  <ChangePasswordModal
    v-if="showChangePasswordModal"
    @close="showChangePasswordModal = false"
  />
</template>
