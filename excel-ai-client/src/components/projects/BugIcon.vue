<!-- src/components/BugIcon.vue -->
<script setup lang="ts">
import { ref, computed } from 'vue'

const props = defineProps<{
  initialColor?: boolean
}>()

const isRed = ref(props.initialColor ?? true)
const toggleColor = () => {
  isRed.value = !isRed.value
}

const iconStyle = computed(() => ({
  cursor: 'pointer',
  color: isRed.value ? 'red' : 'blue',
  fontSize: '16px'
}))
</script>

<template>
  <iconify-icon
    icon="lucide:bug"
    :style="iconStyle"
    @click="toggleColor"
  />
</template>