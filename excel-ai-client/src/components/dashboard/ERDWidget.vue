<script setup lang="ts">
import { ref, onMounted, watch, nextTick } from 'vue'
import mermaid from 'mermaid'

const props = defineProps({
  mermaidCode: {
    type: String,
    required: true
  },
  id: {
    type: String,
    required: true
  }
})

const containerRef = ref<HTMLElement | null>(null)

const renderMermaid = async () => {
  if (!containerRef.value) return
  if (!props.mermaidCode) return

  try {
    mermaid.initialize({ startOnLoad: false, theme: 'default' })
    const { svg } = await mermaid.render(`mermaid-${props.id}`, props.mermaidCode)
    containerRef.value.innerHTML = svg
  } catch (error) {
    console.error('Failed to render ERD:', error)
    if (containerRef.value) {
      containerRef.value.innerHTML = `<div class="text-red-500 text-sm p-4 text-center">Failed to render ERD. Please check the markup.</div>`
    }
  }
}

onMounted(() => {
  renderMermaid()
})

watch(() => props.mermaidCode, () => {
  renderMermaid()
})
</script>

<template>
  <div ref="containerRef" class="w-full h-full flex items-center justify-center overflow-auto">
    <!-- Mermaid SVG will be injected here -->
  </div>
</template>
