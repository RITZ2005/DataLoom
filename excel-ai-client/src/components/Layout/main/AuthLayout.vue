<script setup lang="ts">
import TopNavbar from '@/components/Layout/TopNavbar.vue'
</script>

<template>
  <div class="flex flex-col min-h-screen bg-gradient-water">
    <TopNavbar />
    <main class="flex flex-col flex-1 overflow-hidden">
<!--      <div class="flex items-center">-->
<!--        <h1 class="text-lg font-semibold md:text-2xl">Page Title</h1>-->
<!--      </div>-->
      <slot />
    </main>
  </div>
</template>
