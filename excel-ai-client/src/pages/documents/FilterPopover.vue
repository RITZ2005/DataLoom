<script setup lang="ts">
import { ref, computed, nextTick, onMounted, onBeforeUnmount } from 'vue'
import { Input } from '@/components/ui/input'
import { Checkbox } from '@/components/ui/checkbox'
import { useDocumentsStore, type SortField } from '@/store/documents'

const store = useDocumentsStore()

const open = ref(false)
const triggerRef = ref<HTMLElement | null>(null)
const panelPosition = ref({ top: 0, left: 0 })

const sortOptions: { label: string; value: SortField; icon: string }[] = [
  { label: 'Date', value: 'date', icon: 'lucide:calendar' },
  { label: 'Name', value: 'name', icon: 'lucide:a-large-small' },
  { label: 'Rows', value: 'size', icon: 'lucide:rows-3' },
]

function toggleTag(tag: string) {
  const idx = store.filterTags.indexOf(tag)
  if (idx >= 0) {
    store.filterTags.splice(idx, 1)
  } else {
    store.filterTags.push(tag)
  }
}

function toggleSort(field: SortField) {
  if (store.sortField === field) {
    store.sortOrder = store.sortOrder === 'asc' ? 'desc' : 'asc'
  } else {
    store.sortField = field
    store.sortOrder = field === 'name' ? 'asc' : 'desc'
  }
}

function clearFilters() {
  store.filterTags.splice(0)
  store.showPinnedOnly = false
  store.showFavoritesOnly = false
}

const activeFilterCount = computed(() => {
  let count = 0
  if (store.filterTags.length > 0) count++
  if (store.showPinnedOnly) count++
  if (store.showFavoritesOnly) count++
  return count
})

function updatePanelPosition() {
  const trigger = triggerRef.value
  if (!trigger) return
  const rect = trigger.getBoundingClientRect()
  const panelWidth = 224 // w-56
  const margin = 8
  panelPosition.value = {
    top: Math.round(rect.bottom + 6),
    left: Math.max(margin, Math.min(window.innerWidth - panelWidth - margin, Math.round(rect.right - panelWidth))),
  }
}

function toggleOpen() {
  open.value = !open.value
  if (open.value) {
    nextTick(() => updatePanelPosition())
  }
}

function closePopover() {
  open.value = false
}

function onWindowResize() {
  if (open.value) updatePanelPosition()
}

onMounted(() => {
  window.addEventListener('resize', onWindowResize)
  window.addEventListener('scroll', onWindowResize, true)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', onWindowResize)
  window.removeEventListener('scroll', onWindowResize, true)
})
</script>

<template>
  <div class="flex items-center gap-1.5 w-full">
    <!-- Search input -->
    <div class="relative flex-1">
      <iconify-icon icon="lucide:search" class="absolute left-2 top-1/2 -translate-y-1/2 text-muted-foreground h-3.5 w-3.5" />
      <Input
        v-model="store.searchQuery"
        placeholder="Search…"
        class="pl-7 h-7 text-xs"
      />
    </div>

    <!-- Filter toggle button -->
    <div class="relative" ref="triggerRef">
      <button
        @click="toggleOpen"
        class="inline-flex items-center justify-center h-7 w-7 rounded-md border transition-colors"
        :class="activeFilterCount > 0
          ? 'bg-primary/10 border-primary/30 text-primary'
          : 'border-transparent text-muted-foreground hover:bg-muted hover:text-foreground'"
        title="Filters & Sort"
      >
        <iconify-icon icon="lucide:list-filter" class="h-3.5 w-3.5" />
        <span
          v-if="activeFilterCount > 0"
          class="absolute -top-1 -right-1 w-3.5 h-3.5 rounded-full bg-primary text-primary-foreground text-[9px] font-bold flex items-center justify-center"
        >
          {{ activeFilterCount }}
        </span>
      </button>

      <!-- Popover panel -->
      <Teleport to="body">
        <div v-if="open" class="fixed inset-0 z-[90]" @click="closePopover" />
      </Teleport>

      <Transition
        enter-active-class="transition ease-out duration-100"
        enter-from-class="opacity-0 scale-95"
        enter-to-class="opacity-100 scale-100"
        leave-active-class="transition ease-in duration-75"
        leave-from-class="opacity-100 scale-100"
        leave-to-class="opacity-0 scale-95"
      >
        <Teleport to="body">
          <div
            v-if="open"
            class="fixed z-[100] w-56 rounded-lg border bg-popover shadow-lg p-3 space-y-3"
            :style="{ top: panelPosition.top + 'px', left: panelPosition.left + 'px' }"
            @click.stop
          >
          <!-- Pinned -->
          <div>
            <button
              @click="store.showPinnedOnly = !store.showPinnedOnly"
              class="w-full flex items-center gap-2 text-xs px-2 py-1.5 rounded-md transition-colors"
              :class="store.showPinnedOnly
                ? 'bg-primary/10 text-primary'
                : 'hover:bg-muted text-foreground/80'"
            >
              <iconify-icon icon="lucide:pin" class="h-3.5 w-3.5" :class="store.showPinnedOnly ? 'text-primary' : ''" />
              <span>Pinned only</span>
              <iconify-icon v-if="store.showPinnedOnly" icon="lucide:check" class="h-3 w-3 ml-auto text-primary" />
            </button>
          </div>

          <!-- Favorites -->
          <div>
            <button
              @click="store.showFavoritesOnly = !store.showFavoritesOnly"
              class="w-full flex items-center gap-2 text-xs px-2 py-1.5 rounded-md transition-colors"
              :class="store.showFavoritesOnly
                ? 'bg-amber-50 text-amber-700 dark:bg-amber-950/30 dark:text-amber-400'
                : 'hover:bg-muted text-foreground/80'"
            >
              <iconify-icon icon="lucide:star" class="h-3.5 w-3.5" :class="store.showFavoritesOnly ? 'text-amber-500' : ''" />
              <span>Favorites only</span>
              <iconify-icon v-if="store.showFavoritesOnly" icon="lucide:check" class="h-3 w-3 ml-auto text-amber-600" />
            </button>
          </div>

          <!-- Tags section -->
          <div v-if="store.allTags.length > 0">
            <p class="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider px-2 mb-1">Tags</p>
            <div class="max-h-28 overflow-y-auto space-y-0.5">
              <button
                v-for="tag in store.allTags"
                :key="tag"
                @click="toggleTag(tag)"
                class="w-full flex items-center gap-2 text-xs px-2 py-1 rounded hover:bg-muted transition-colors text-left"
              >
                <Checkbox :checked="store.filterTags.includes(tag)" class="h-3 w-3" />
                <span>{{ tag }}</span>
              </button>
            </div>
          </div>

          <!-- Sort section -->
          <div>
            <p class="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider px-2 mb-1">Sort by</p>
            <div class="space-y-0.5">
              <button
                v-for="opt in sortOptions"
                :key="opt.value"
                @click="toggleSort(opt.value)"
                class="w-full flex items-center gap-2 text-xs px-2 py-1 rounded transition-colors text-left"
                :class="store.sortField === opt.value
                  ? 'bg-primary/10 text-primary font-medium'
                  : 'hover:bg-muted text-foreground/80'"
              >
                <iconify-icon :icon="opt.icon" class="h-3.5 w-3.5" />
                <span>{{ opt.label }}</span>
                <iconify-icon
                  v-if="store.sortField === opt.value"
                  :icon="store.sortOrder === 'asc' ? 'lucide:arrow-up' : 'lucide:arrow-down'"
                  class="h-3 w-3 ml-auto"
                />
              </button>
            </div>
          </div>

          <!-- Clear -->
          <button
            v-if="activeFilterCount > 0"
            @click="clearFilters"
            class="w-full text-center text-[11px] text-muted-foreground hover:text-foreground py-1 rounded hover:bg-muted transition-colors"
          >
            Clear all filters
          </button>
          </div>
        </Teleport>
      </Transition>
    </div>
  </div>
</template>
