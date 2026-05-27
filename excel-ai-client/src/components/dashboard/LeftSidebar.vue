<script setup lang="ts">
import { ref } from 'vue'

const props = defineProps<{
  visible: boolean
  sidebarOpen: boolean
  studioTab: 'elements' | 'screens' | 'design'
  boardScreens: Array<{ id: string; name: string }>
  boardScreenPreviews?: Record<string, { total: number; chart: number; kpi: number; insight: number; list: number; summary: number }>
  boardScreenThumbnails?: Record<string, string>
  activeScreenId: string
  themeKeys: string[]
  activeTheme: string
  getSwatchStyle: (key: string) => Record<string, string>
  boardFiles?: Array<{ file_uuid: string; filename: string; table_name?: string; total_rows?: number }>
  activeWidget?: any
  widgetStyleOptions?: {
    roundedCorners?: boolean
    cornerRadius?: 'sm' | 'md' | 'lg'
    imageBg?: boolean
    imageUrl?: string
    canvasColor?: string
    dropShadow?: boolean
    shadowSize?: 'sm' | 'md' | 'lg'
    stroke?: boolean
    strokeColor?: string
    strokeWidth?: number
  }
  dashboardDesign?: {
    texture?: 'none' | 'dots' | 'grid' | 'gradient'
    density?: 'compact' | 'cozy' | 'airy'
    cardStyle?: 'flat' | 'soft' | 'glass'
  }
}>()

const emit = defineEmits<{
  'update:studioTab': [tab: 'elements' | 'screens' | 'design']
  'update:elementFilterTab': [tab: 'all' | 'favorites']
  'open-style-chooser': [element: { id: string; label: string; icon: string; query: string; category: 'basics' | 'charts' | 'tables' }]
  'activate-screen': [id: string]
  'rename-screen': [id: string, name: string]
  'delete-screen': [id: string]
  'add-screen': []
  'set-theme': [key: string]
  'update-widget-style': [key: string, value: any]
  'update-dashboard-design': [key: string, value: any]
}>()

const editingScreenId = ref<string | null>(null)
const editingScreenName = ref('')

function startEditingScreen(screenId: string, currentName: string) {
  editingScreenId.value = screenId
  editingScreenName.value = currentName
}

function saveScreenName() {
  if (editingScreenId.value) {
    emit('rename-screen', editingScreenId.value, editingScreenName.value)
  }
  editingScreenId.value = null
}

function cancelEditingScreen() {
  editingScreenId.value = null
}
</script>

<template>
  <aside
    v-if="props.visible"
    :class="[
      'shrink-0 glass-panel rounded-2xl flex flex-col h-full transition-all duration-300 ease-in-out overflow-hidden',
      props.sidebarOpen ? 'w-72' : 'w-0 border-transparent shadow-none',
    ]"
  >
    <div class="w-72 flex flex-col h-full">
      <div class="px-2.5 pt-2.5 pb-2 border-b border-slate-100 dark:border-white/5">
        <div class="grid grid-cols-3 gap-1 rounded-lg bg-slate-100 p-1 dark:bg-slate-800/70">
          <button
            @click="emit('update:studioTab', 'elements')"
            :class="['rounded-md px-2 py-1.5 text-xs font-semibold transition', props.studioTab === 'elements' ? 'bg-white text-slate-800 shadow-sm dark:bg-slate-700 dark:text-slate-100' : 'text-slate-500 dark:text-slate-400']"
          >
            Files
          </button>
          <button
            @click="emit('update:studioTab', 'screens')"
            :class="['rounded-md px-2 py-1.5 text-xs font-semibold transition', props.studioTab === 'screens' ? 'bg-white text-slate-800 shadow-sm dark:bg-slate-700 dark:text-slate-100' : 'text-slate-500 dark:text-slate-400']"
          >
            Screens
          </button>
          <button
            @click="emit('update:studioTab', 'design')"
            :class="['rounded-md px-2 py-1.5 text-xs font-semibold transition', props.studioTab === 'design' ? 'bg-white text-slate-800 shadow-sm dark:bg-slate-700 dark:text-slate-100' : 'text-slate-500 dark:text-slate-400']"
          >
            Design
          </button>
        </div>
      </div>

      <!-- FILES TAB -->
      <template v-if="props.studioTab === 'elements'">
        <slot name="elements-footer">
          <div class="flex-1 overflow-y-auto p-3 space-y-2">
            <div class="rounded-lg border border-slate-200/80 bg-white/70 p-3 dark:border-white/10 dark:bg-slate-900/50">
              <p class="text-xs font-semibold text-slate-700 dark:text-slate-300 mb-2">Board Files</p>
              <div class="space-y-2">
                <div v-if="!props.boardFiles || props.boardFiles.length === 0" class="text-xs text-slate-400 dark:text-slate-500 py-4 text-center">
                  No files in this board
                </div>
                <div
                  v-for="file in props.boardFiles"
                  :key="file.file_uuid"
                  class="flex items-start gap-2 p-2 rounded-lg border border-slate-200 bg-white hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-800 dark:hover:bg-slate-700/60 cursor-pointer transition"
                >
                  <iconify-icon icon="lucide:file-spreadsheet" class="w-4 h-4 mt-0.5 text-slate-500 dark:text-slate-400 flex-shrink-0" />
                  <div class="flex-1 min-w-0">
                    <p class="text-xs font-medium text-slate-700 dark:text-slate-200 truncate">{{ file.filename }}</p>
                    <p class="text-[10px] text-slate-500 dark:text-slate-400">{{ (file.total_rows || 0).toLocaleString() }} rows</p>
                  </div>
                  <span class="inline-flex px-2 py-0.5 bg-emerald-100/50 dark:bg-emerald-500/20 text-emerald-700 dark:text-emerald-300 text-[10px] font-medium rounded whitespace-nowrap">
                    Data
                  </span>
                </div>
              </div>
            </div>
          </div>
        </slot>
      </template>

      <!-- SCREENS TAB -->
      <template v-else-if="props.studioTab === 'screens'">
        <div class="flex-1 overflow-y-auto p-3 space-y-3">
          <div class="rounded-lg border border-slate-200/80 bg-white/70 p-3 dark:border-white/10 dark:bg-slate-900/50">
            <p class="text-xs font-semibold text-slate-700 dark:text-slate-300 mb-3">Dashboard Pages</p>
            <div class="space-y-2">
              <div
                v-for="screen in props.boardScreens"
                :key="screen.id"
                :class="[
                  'rounded-lg border p-3 transition',
                  props.activeScreenId === screen.id
                    ? 'border-emerald-300 bg-emerald-50 dark:border-emerald-500/40 dark:bg-emerald-500/10'
                    : 'border-slate-200 hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800'
                ]"
              >
                <div v-if="editingScreenId === screen.id" class="flex items-center gap-2">
                  <input
                    v-model="editingScreenName"
                    @keyup.enter="saveScreenName"
                    @keyup.escape="cancelEditingScreen"
                    autofocus
                    class="flex-1 rounded-md border border-slate-300 bg-white px-2 py-1 text-xs dark:border-slate-600 dark:bg-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-emerald-500"
                  />
                  <button
                    @click="saveScreenName"
                    class="rounded px-2 py-1 bg-emerald-600 text-white text-xs hover:bg-emerald-700 transition"
                  >
                    Save
                  </button>
                </div>
                <div v-else class="flex items-center justify-between gap-2">
                  <div
                    @click="emit('activate-screen', screen.id)"
                    class="flex-1 cursor-pointer"
                  >
                    <div class="mb-2 aspect-[16/10] w-full overflow-hidden rounded border border-slate-300 bg-white shadow-sm dark:border-slate-600 dark:bg-slate-900">
                      <img
                        v-if="props.boardScreenThumbnails?.[screen.id]"
                        :src="props.boardScreenThumbnails[screen.id]"
                        alt="Screen preview"
                        class="h-full w-full object-cover object-top"
                        loading="lazy"
                      />
                      <div v-else class="h-full w-full p-2">
                        <div class="mb-1 h-2.5 rounded bg-slate-100 dark:bg-slate-700" />
                        <div class="grid grid-cols-3 gap-1">
                          <div class="h-4 rounded bg-emerald-100/80 dark:bg-emerald-500/20" />
                          <div class="h-4 rounded bg-emerald-100/80 dark:bg-emerald-500/20" />
                          <div class="h-4 rounded bg-teal-100/80 dark:bg-teal-500/20" />
                        </div>
                        <div class="mt-1 grid grid-cols-2 gap-1">
                          <div class="h-9 rounded bg-rose-100/70 dark:bg-rose-500/15" />
                          <div class="h-9 rounded bg-amber-100/70 dark:bg-amber-500/15" />
                        </div>
                      </div>
                    </div>
                    <div class="mb-2 flex items-center gap-1">
                      <span class="inline-flex rounded bg-slate-100 px-1 py-0.5 text-[9px] font-semibold text-slate-500 dark:bg-slate-700 dark:text-slate-300">{{ props.boardScreenPreviews?.[screen.id]?.total || 0 }} widgets</span>
                      <span class="inline-flex rounded bg-emerald-50 px-1 py-0.5 text-[9px] text-emerald-600 dark:bg-emerald-500/10 dark:text-emerald-300">C {{ props.boardScreenPreviews?.[screen.id]?.chart || 0 }}</span>
                      <span class="inline-flex rounded bg-emerald-50 px-1 py-0.5 text-[9px] text-emerald-600 dark:bg-emerald-500/10 dark:text-emerald-300">K {{ props.boardScreenPreviews?.[screen.id]?.kpi || 0 }}</span>
                    </div>
                    <p class="text-xs font-medium text-slate-700 dark:text-slate-200 truncate">{{ screen.name }}</p>
                  </div>
                  <div class="flex flex-col gap-1">
                    <button
                      @click="startEditingScreen(screen.id, screen.name)"
                      class="rounded p-1 text-slate-400 hover:bg-slate-200 dark:hover:bg-slate-700 transition"
                      title="Rename"
                    >
                      <iconify-icon icon="lucide:edit-2" class="w-3.5 h-3.5" />
                    </button>
                    <button
                      v-if="props.boardScreens.length > 1"
                      @click="emit('delete-screen', screen.id)"
                      class="rounded p-1 text-slate-400 hover:bg-red-100 hover:text-red-600 dark:hover:bg-red-500/20 dark:hover:text-red-400 transition"
                      title="Delete"
                    >
                      <iconify-icon icon="lucide:trash-2" class="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>
              </div>
            </div>
            <button
              @click="emit('add-screen')"
              class="w-full mt-3 rounded-lg bg-emerald-600 px-3 py-2 text-xs font-semibold text-white transition hover:bg-emerald-700"
            >
              + Add Page
            </button>
          </div>
        </div>
      </template>

      <!-- DESIGN TAB -->
      <template v-else>
        <div class="flex-1 overflow-y-auto p-3 space-y-3">
          <div class="rounded-lg border border-slate-200/80 bg-white/70 p-3 dark:border-white/10 dark:bg-slate-900/50">
            <p class="text-xs font-semibold text-slate-700 dark:text-slate-300 mb-2">Active Theme</p>
            <button
              v-for="key in props.themeKeys"
              :key="key"
              @click="emit('set-theme', key)"
              :class="[
                'w-full rounded-lg border p-2 text-left transition shadow-sm text-xs font-medium mb-2',
                props.activeTheme === key
                  ? 'border-emerald-300 bg-emerald-50 dark:border-emerald-500/40 dark:bg-emerald-500/10'
                  : 'border-slate-200 hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800',
              ]"
            >
              <div class="flex items-center justify-between">
                <span class="text-slate-700 dark:text-slate-200">{{ key.charAt(0).toUpperCase() + key.slice(1) }}</span>
                <span v-if="props.activeTheme === key" class="inline-flex h-4 w-4 items-center justify-center rounded-full bg-emerald-600 text-white">
                  <iconify-icon icon="lucide:check" class="h-2.5 w-2.5" />
                </span>
              </div>
              <div class="mt-1 h-6 rounded-md" :style="props.getSwatchStyle(key).background ? { background: props.getSwatchStyle(key).background } : { background: '#6366f1' }" />
            </button>
          </div>

          <div class="rounded-lg border border-slate-200/80 bg-white/70 p-3 dark:border-white/10 dark:bg-slate-900/50">
            <p class="text-xs font-semibold text-slate-700 dark:text-slate-300 mb-3">Canvas Experience</p>

            <div class="mb-3">
              <p class="mb-1 text-[11px] font-medium text-slate-500 dark:text-slate-400">Texture</p>
              <div class="grid grid-cols-2 gap-1 rounded bg-slate-100 dark:bg-slate-800 p-1">
                <button @click="emit('update-dashboard-design', 'texture', 'none')" :class="['rounded px-2 py-1 text-xs', props.dashboardDesign?.texture === 'none' ? 'bg-white dark:bg-slate-700' : 'text-slate-500']">None</button>
                <button @click="emit('update-dashboard-design', 'texture', 'dots')" :class="['rounded px-2 py-1 text-xs', props.dashboardDesign?.texture === 'dots' ? 'bg-white dark:bg-slate-700' : 'text-slate-500']">Dots</button>
                <button @click="emit('update-dashboard-design', 'texture', 'grid')" :class="['rounded px-2 py-1 text-xs', props.dashboardDesign?.texture === 'grid' ? 'bg-white dark:bg-slate-700' : 'text-slate-500']">Grid</button>
                <button @click="emit('update-dashboard-design', 'texture', 'gradient')" :class="['rounded px-2 py-1 text-xs', props.dashboardDesign?.texture === 'gradient' ? 'bg-white dark:bg-slate-700' : 'text-slate-500']">Gradient</button>
              </div>
            </div>

            <div class="mb-3">
              <p class="mb-1 text-[11px] font-medium text-slate-500 dark:text-slate-400">Density</p>
              <div class="grid grid-cols-3 gap-1 rounded bg-slate-100 dark:bg-slate-800 p-1">
                <button @click="emit('update-dashboard-design', 'density', 'compact')" :class="['rounded px-2 py-1 text-xs', props.dashboardDesign?.density === 'compact' ? 'bg-white dark:bg-slate-700' : 'text-slate-500']">Compact</button>
                <button @click="emit('update-dashboard-design', 'density', 'cozy')" :class="['rounded px-2 py-1 text-xs', props.dashboardDesign?.density === 'cozy' ? 'bg-white dark:bg-slate-700' : 'text-slate-500']">Cozy</button>
                <button @click="emit('update-dashboard-design', 'density', 'airy')" :class="['rounded px-2 py-1 text-xs', props.dashboardDesign?.density === 'airy' ? 'bg-white dark:bg-slate-700' : 'text-slate-500']">Airy</button>
              </div>
            </div>

            <div>
              <p class="mb-1 text-[11px] font-medium text-slate-500 dark:text-slate-400">Card Style</p>
              <div class="grid grid-cols-3 gap-1 rounded bg-slate-100 dark:bg-slate-800 p-1">
                <button @click="emit('update-dashboard-design', 'cardStyle', 'flat')" :class="['rounded px-2 py-1 text-xs', props.dashboardDesign?.cardStyle === 'flat' ? 'bg-white dark:bg-slate-700' : 'text-slate-500']">Flat</button>
                <button @click="emit('update-dashboard-design', 'cardStyle', 'soft')" :class="['rounded px-2 py-1 text-xs', props.dashboardDesign?.cardStyle === 'soft' ? 'bg-white dark:bg-slate-700' : 'text-slate-500']">Soft</button>
                <button @click="emit('update-dashboard-design', 'cardStyle', 'glass')" :class="['rounded px-2 py-1 text-xs', props.dashboardDesign?.cardStyle === 'glass' ? 'bg-white dark:bg-slate-700' : 'text-slate-500']">Glass</button>
              </div>
            </div>
          </div>

          <!-- Widget Customization -->
          <div v-if="props.activeWidget" class="rounded-lg border border-slate-200/80 bg-white/70 p-3 dark:border-white/10 dark:bg-slate-900/50">
            <p class="text-xs font-semibold text-slate-700 dark:text-slate-300 mb-3">Widget Customization</p>
            
            <div class="mb-3">
              <label class="flex items-center justify-between text-xs text-slate-600 dark:text-slate-300 mb-2">
                <span>Rounded Corners</span>
                <input type="checkbox" class="accent-emerald-600" @change="(e: any) => emit('update-widget-style', 'roundedCorners', e.target.checked)" />
              </label>
              <div class="grid grid-cols-3 gap-1 rounded bg-slate-100 dark:bg-slate-800 p-1">
                <button @click="emit('update-widget-style', 'cornerRadius', 'sm')" class="rounded px-2 py-1 text-xs bg-white dark:bg-slate-700">Small</button>
                <button @click="emit('update-widget-style', 'cornerRadius', 'md')" class="rounded px-2 py-1 text-xs bg-white dark:bg-slate-700">Medium</button>
                <button @click="emit('update-widget-style', 'cornerRadius', 'lg')" class="rounded px-2 py-1 text-xs bg-white dark:bg-slate-700">Large</button>
              </div>
            </div>

            <div class="mb-3">
              <label class="block text-xs font-medium text-slate-600 dark:text-slate-300 mb-2">Canvas Color</label>
              <input
                type="color"
                :value="props.widgetStyleOptions?.canvasColor || '#ffffff'"
                @change="(e: any) => emit('update-widget-style', 'canvasColor', e.target.value)"
                class="w-full h-8 rounded-md border border-slate-200 dark:border-slate-700"
              />
            </div>

            <div class="mb-3">
              <label class="flex items-center justify-between text-xs text-slate-600 dark:text-slate-300 mb-2">
                <span>Drop Shadow</span>
                <input type="checkbox" class="accent-emerald-600" @change="(e: any) => emit('update-widget-style', 'dropShadow', e.target.checked)" />
              </label>
              <div v-if="props.widgetStyleOptions?.dropShadow" class="grid grid-cols-3 gap-1 rounded bg-slate-100 dark:bg-slate-800 p-1">
                <button @click="emit('update-widget-style', 'shadowSize', 'sm')" class="rounded px-2 py-1 text-xs bg-white dark:bg-slate-700">Small</button>
                <button @click="emit('update-widget-style', 'shadowSize', 'md')" class="rounded px-2 py-1 text-xs bg-white dark:bg-slate-700">Medium</button>
                <button @click="emit('update-widget-style', 'shadowSize', 'lg')" class="rounded px-2 py-1 text-xs bg-white dark:bg-slate-700">Large</button>
              </div>
            </div>

            <div>
              <label class="flex items-center justify-between text-xs text-slate-600 dark:text-slate-300 mb-2">
                <span>Border Stroke</span>
                <input type="checkbox" class="accent-emerald-600" @change="(e: any) => emit('update-widget-style', 'stroke', e.target.checked)" />
              </label>
              <div v-if="props.widgetStyleOptions?.stroke" class="space-y-2">
                <div>
                  <label class="block text-[10px] text-slate-500 dark:text-slate-400 mb-1">Color</label>
                  <input type="color" :value="props.widgetStyleOptions?.strokeColor || '#000000'" @change="(e: any) => emit('update-widget-style', 'strokeColor', e.target.value)" class="w-full h-6 rounded-md border border-slate-200 dark:border-slate-700" />
                </div>
                <div>
                  <label class="block text-[10px] text-slate-500 dark:text-slate-400 mb-1">Width (px)</label>
                  <input type="number" min="1" max="8" :value="props.widgetStyleOptions?.strokeWidth || 1" @change="(e: any) => emit('update-widget-style', 'strokeWidth', parseInt(e.target.value))" class="w-full rounded-md border border-slate-200 bg-white px-2 py-1 text-xs dark:border-slate-700 dark:bg-slate-800" />
                </div>
              </div>
            </div>
          </div>
        </div>
      </template>
    </div>
  </aside>
</template>
