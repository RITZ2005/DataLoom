<script setup lang="ts">
import SidebarLinks from './SidebarLinks.vue'
import { Button } from '@/components/ui/button'

import { Login } from '@/store/login'

const loginStore = Login()

const links = [
  {
    title: 'Dashboard',
    to: '/dashboard',
    icon: 'lucide:layout-dashboard'
  },
  {
    title: 'Upload',
    to: '/dashboard/upload',
    icon: 'lucide:upload-cloud'
  },
  {
    title: 'Documents',
    to: '/dashboard/files',
    icon: 'lucide:file-text'
  },
  {
    title: 'Chat',
    to: '/dashboard/chat',
    icon: 'lucide:message-square'
  }
];

const accountLinks = [
  {
    title: 'Sign Out',
    to: '/logout',
    icon: 'lucide:log-out',
    action: () => loginStore.logout()
  }
]
</script>

<template>
  <aside
    class="flex flex-col h-screen gap-2 border-r fixed bg-muted/40 lg:w-52 w-16 transition-[width]"
  >
    <div class="flex h-16 items-center border-b px-2 lg:px-4 shrink-0 gap-1 justify-between">
      <Button variant="outline" size="icon" class="w-8 h-8">
        <iconify-icon icon="lucide:menu"></iconify-icon>
      </Button>

      <Button variant="outline" size="icon" class="w-8 h-8">
        <iconify-icon icon="lucide:plus"></iconify-icon>
      </Button>
    </div>

    <nav class="flex flex-col gap-2 justify-between h-full relative">
      <div>
        <SidebarLinks :links="links" />
      </div>

      <div class="border-y text-center bg-background py-3">
        <div
          v-for="link in accountLinks"
          :key="link.title"
          class="flex items-center gap-3 px-4 py-2 mx-2 transition-colors rounded-lg hover:text-primary hover:bg-muted justify-center lg:justify-normal text-muted-foreground cursor-pointer"
          @click="link.action ? link.action() : null"
        >
          <iconify-icon :icon="link.icon"></iconify-icon>
          <span class="hidden lg:block text-nowrap">{{ link.title }}</span>
        </div>
      </div>
    </nav>
  </aside>
</template>
