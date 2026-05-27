<script setup lang="ts">
import { useRouter } from 'vue-router'
// Safety fallback: if this component is ever rendered directly,
// redirect to /register which router.js maps to login/index.vue
const router = useRouter()
router.replace('/register')
</script>

<template>
  <div />
</template>

