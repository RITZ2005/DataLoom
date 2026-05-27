<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import UserAuthForm from '@/components/login/UserAuthForm.vue'

const route = useRoute()
const isRegister = computed(() => route.path.includes('register'))
const isDark = ref(true)

const features = [
  {
    icon: 'lucide:zap',
    title: 'Instant Insights',
    description: 'Analyze thousands of rows instantly'
  },
  {
    icon: 'lucide:chart-column',
    title: 'Smart Visualizations',
    description: 'Intelligent Excel Chat & Dashboard Platform..'
  },
  {
    icon: 'lucide:bot',
    title: 'AI Data Assistant',
    description: 'Ask questions in natural language'
  }
]

function syncThemeState() {
  isDark.value = document.documentElement.classList.contains('dark')
}

function toggleTheme() {
  const root = document.documentElement
  isDark.value = !isDark.value
  root.classList.toggle('dark', isDark.value)
  localStorage.setItem('theme', isDark.value ? 'dark' : 'light')
}

// Watch for external theme changes (e.g. from ThemeToggle in navbar)
let observer: MutationObserver | null = null
onMounted(() => {
  syncThemeState()
  observer = new MutationObserver(() => syncThemeState())
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] })
})
onUnmounted(() => observer?.disconnect())

const bgImage = computed(() => isDark.value ? '/login-bg.png' : '/login-bg-light.png')
</script>

<template>
  <!-- Full-width background covers the entire page -->
  <div
    class="relative h-screen w-full overflow-hidden transition-colors duration-300"
    :style="{ backgroundImage: `url('${bgImage}')`, backgroundSize: 'cover', backgroundPosition: 'center right' }"
  >
    <!-- Gradient overlay: adapts to light/dark -->
    <div
      class="absolute inset-0 transition-colors duration-300"
      :class="isDark
        ? 'bg-gradient-to-r from-black/75 via-black/55 to-black/20'
        : 'bg-gradient-to-r from-white/70 via-white/40 to-transparent'"
    ></div>
    <!-- Subtle dot-grid texture -->
    <div
      class="absolute inset-0 transition-opacity duration-300"
      :class="isDark ? 'opacity-30' : 'opacity-15'"
      :style="isDark
        ? 'background-size: 28px 28px; background-image: linear-gradient(to right, rgb(255 255 255 / 0.06) 1px, transparent 1px), linear-gradient(to bottom, rgb(255 255 255 / 0.06) 1px, transparent 1px);'
        : 'background-size: 28px 28px; background-image: linear-gradient(to right, rgb(0 0 0 / 0.04) 1px, transparent 1px), linear-gradient(to bottom, rgb(0 0 0 / 0.04) 1px, transparent 1px);'"
    ></div>

    <!-- Theme toggle button (top-right corner) -->
    <button
      @click="toggleTheme"
      class="absolute right-6 top-6 z-20 flex h-10 w-10 items-center justify-center rounded-full border backdrop-blur-sm transition-all duration-200 hover:scale-105"
      :class="isDark
        ? 'border-white/20 bg-white/10 text-white hover:bg-white/20'
        : 'border-gray-300 bg-white/60 text-gray-700 hover:bg-white/80'"
      :title="isDark ? 'Switch to light mode' : 'Switch to dark mode'"
    >
      <iconify-icon :icon="isDark ? 'lucide:sun' : 'lucide:moon'" class="h-5 w-5" />
    </button>

    <!-- Page content: left text + right form side-by-side on large screens -->
    <div class="relative z-10 flex h-full flex-col lg:flex-row">

      <!-- Left: branding & feature list -->
      <div class="flex flex-1 flex-col justify-center px-8 py-8 lg:px-12 xl:px-16">
        <!-- MKCL logo at the top -->
<!--        <div class="flex items-center">-->
<!--          <div-->
<!--            class="flex items-center justify-center rounded-2xl border px-6 py-4 transition-all duration-200 shadow-lg"-->
<!--            :class="isDark-->
<!--              ? 'border-white/25 bg-white/15 shadow-white/5 backdrop-blur-sm'-->
<!--              : 'border-gray-200 bg-white shadow-gray-100'"-->
<!--          >-->
<!--            <img-->
<!--              src="/logo_mkcl_w-cropped.svg"-->
<!--              alt="MKCL"-->
<!--              class="h-16 w-auto"-->
<!--            />-->
<!--          </div>-->
<!--        </div>-->
        <!-- App icon + name below MKCL -->
        <div class="mt-4 flex flex-col gap-1">

          <span
            class="text-[36px] font-semibold transition-colors duration-200"
            :class="isDark ? 'text-white' : 'text-gray-900'"
          ><span class="dark:text-white">Excel</span>
          <span class="text-yellow-500">LOOM</span>
          </span>
          <div>
          <p
              class="text-sm font-normal leading-relaxed transition-colors duration-200"
              :class="isDark ? 'text-white/80' : 'text-gray-600'"
          >
            Intelligent Excel Chat & Dashboard Platform
          </p>
          </div>
        </div>

        <!-- Hero copy -->
        <div class="mt-6 max-w-lg space-y-3">
          <h2
            class="text-3xl font-bold leading-snug drop-shadow-md lg:text-4xl transition-colors duration-200"
            :class="isDark ? 'text-white' : 'text-gray-900'"
          >
            Transform Your<br/>Spreadsheets with AI
          </h2>

        </div>

        <!-- Feature cards -->
        <div class="mt-6 hidden space-y-2.5 lg:block">
          <div
            v-for="feature in features"
            :key="feature.title"
            class="flex items-center gap-3 rounded-xl border p-3 backdrop-blur-md transition-colors duration-200"
            :class="isDark
              ? 'border-white/10 bg-white/8'
              : 'border-gray-200/80 bg-white/50'"
          >
            <div
              class="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border transition-colors duration-200"
              :class="isDark ? 'border-white/20 bg-primary/40' : 'border-emerald-200 bg-emerald-600'"
            >
              <iconify-icon :icon="feature.icon" class="h-4 w-4 text-white" />
            </div>
            <div>
              <p
                class="text-sm font-semibold leading-tight transition-colors duration-200"
                :class="isDark ? 'text-white' : 'text-gray-900'"
              >{{ feature.title }}</p>
              <p
                class="text-xs leading-snug transition-colors duration-200"
                :class="isDark ? 'text-white/65' : 'text-gray-500'"
              >{{ feature.description }}</p>
            </div>
          </div>
        </div>
      </div>

      <!-- Right: floating glass form card -->
      <div class="flex flex-shrink-0 items-center justify-center px-5 py-6 lg:w-[480px] lg:px-8 xl:w-[520px]">
        <div
          class="w-full max-w-[440px] rounded-2xl border shadow-2xl backdrop-blur-2xl transition-colors duration-200"
          :class="isDark
            ? 'border-white/10 bg-zinc-900/80'
            : 'border-gray-200 bg-white/85'"
        >
          <div class="p-6 md:p-8">
            <!-- Header: title + toggle link in same row -->
            <div class="mb-5 space-y-1">
              <div>
                <h1 class="text-2xl font-bold tracking-tight text-foreground">
                  {{ isRegister ? 'Create an account' : 'Welcome back' }}
                </h1>
                <p class="mt-1 text-sm text-muted-foreground">
                  {{ isRegister ? 'Fill in the details below to get started' : 'Sign in to continue to your dashboard' }}
                </p>
              </div>
            </div>

            <UserAuthForm :is-register="isRegister" />
          </div>
        </div>
      </div>

    </div>
  </div>
</template>