<script setup lang="ts">
const props = defineProps<{
  visible: boolean
  top: number
  left: number
}>()

const emit = defineEmits<{
  (e: 'duplicate'): void
  (e: 'delete'): void
}>()
</script>

<template>
  <div
    v-if="props.visible"
    class="fixed z-40"
    :style="{ top: props.top + 'px', left: props.left + 'px', transform: 'translateX(-50%)' }"
    @click.stop
  >
    <div class="flex items-center gap-1 rounded-lg bg-slate-950 px-2 py-1.5 text-white shadow-xl">
      <button @click="emit('duplicate')" class="rounded p-1 transition hover:bg-white/15" title="Duplicate">
        <iconify-icon icon="lucide:copy-plus" class="h-4 w-4" />
      </button>
      <button @click="emit('delete')" class="rounded p-1 transition hover:bg-white/15" title="Delete">
        <iconify-icon icon="lucide:trash-2" class="h-4 w-4" />
      </button>
    </div>
  </div>
</template>
