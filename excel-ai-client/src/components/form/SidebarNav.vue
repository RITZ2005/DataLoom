<script setup lang="ts">
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

interface Item {
  title: string
  href: string
}

const sidebarNavItems: Item[] = [
  {
    title: 'Profile',
    href: '/dashboard/form',
  },
  {
    title: 'Account',
    href: '/dashboard/form/account',
  },
  {
    title: 'Appearance',
    href: '/dashboard/form/appearance',
  },
  {
    title: 'Notifications',
    href: '/dashboard/form/notifications',
  },
  {
    title: 'Display',
    href: '/dashboard/form/display',
  },
  {
    title: 'Date & Time',
    href: '/dashboard/form/daterange',
  },
  {
    title: 'MQL Request Demo',
    href: '/dashboard/form/MQLRequestDemo',
  },
]
</script>

<template>
  <nav class="flex space-x-2 lg:flex-col lg:space-x-0 lg:space-y-1">
    <Button
      v-for="item in sidebarNavItems"
      :key="item.title"
      as="a"
      @click="() => $router.push(item.href)"
      variant="ghost"
      :class="cn(
        'w-auto text-left justify-start',
        $route.path === `${item.href}` && 'bg-muted hover:bg-muted',
      )"
    >
      {{ item.title }}
    </Button>
  </nav>
</template>