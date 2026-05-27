<script setup lang="ts">
import { ref, computed } from 'vue'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle, DialogTrigger
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Codemirror } from 'vue-codemirror'
import type { Extension } from '@codemirror/state'
import { go } from '@codemirror/lang-go' // Import the Go language support

const props = defineProps<{
  collaborators: string[],
  project: string,
  status: string
}>()
const extensions = ref<any[]>([])
const isModalOpen = ref(false)
const isFullscreen = ref(false) // Track fullscreen state
const code = ref('') // Define the code property

const themeName = 'coolGlow'; // Replace with the desired theme name

const loadTheme = async (themeName: string) => {
  const themes = await import('thememirror') as unknown as Record<string, unknown>
  return themes[themeName] as Extension | undefined
}

loadTheme(themeName).then((theme) => {
  extensions.value = theme ? [theme, go()] : [go()] // Add selected theme when available
});

const handleIconClick = () => {
  isModalOpen.value = true
}

const toggleFullscreen = () => {
  isFullscreen.value = !isFullscreen.value
}

const iconColor = computed(() => {
  return props.status === 'in-progress' ? 'red' : 'green'
})

// Define the log and handleReady methods
const log = (event: string, data: any) => {
  console.log(event, data)
}

const handleReady = () => {
  console.log('Codemirror is ready')
}
</script>

<template>
  <div class="text-left font-medium flex items-center" style="font-size: 16px;">
    <iconify-icon
        icon="lucide:house-plus"
        @click="handleIconClick"
        :style="{ cursor: 'pointer', color: iconColor, marginRight: '8px' }"
    />

    <Dialog v-model:open="isModalOpen">
      <DialogTrigger as-child>
        <iconify-icon
            icon="lucide:app-window-mac"
            style="cursor: pointer; margin-right: 8px;"
        />
      </DialogTrigger>
      <DialogContent :class="{ 'fullscreen': isFullscreen }" class="dialog-content">
        <DialogHeader class="p-6 pb-0 flex justify-between items-center">
          <div>
            <DialogTitle>Edit profile</DialogTitle>
            <DialogDescription>
              Make changes to your profile here. Click save when you're done.
            </DialogDescription>
          </div>
          <Button @click="toggleFullscreen">
            {{ isFullscreen ? 'Exit Fullscreen' : 'Fullscreen' }}
          </Button>
        </DialogHeader>
        <div class="grid gap-4 py-4 overflow-y-auto px-6" :class="{ 'fullscreen-codemirror': isFullscreen }">
          <codemirror
              v-model="code"
              placeholder="Code goes here..."
              :style="{ height: '100%', width: '100%' }"
              :autofocus="true"
              :indent-with-tab="true"
              :tab-size="2"
              :extensions="extensions"
              @ready="handleReady"
              @change="log('change', $event)"
              @focus="log('focus', $event)"
              @blur="log('blur', $event)"
          />
        </div>
        <DialogFooter class="p-6 pt-0">
          <Button type="submit" variant="ghost">
            Save changes
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </div>
</template>

<style scoped>
.dialog-content {
  width: auto;
  max-width: 90vw; /* Adjust as needed */
}

.fullscreen {
  width: 100vw;
  max-width: 100vw;
  height: 100vh;
  max-height: 100vh;
  border-radius: 0;
}

.fullscreen-codemirror {
  width: 100%;
  height: calc(100vh - 120px); /* Adjust based on header and footer height */
}
</style>