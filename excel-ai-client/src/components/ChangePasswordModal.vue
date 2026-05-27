<script setup lang="ts">
import { ref, computed } from 'vue'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Separator } from '@/components/ui/separator'
import excelFileAPI from '@/services/excelApi'

const emit = defineEmits<{ (e: 'close'): void }>()

// The dialog open state — always open while this component is mounted
const open = ref(true)

// Form state
const currentPassword = ref('')
const newPassword = ref('')
const confirmPassword = ref('')
const isLoading = ref(false)
const successMessage = ref('')
const errorMessage = ref('')

// Show/hide toggles
const showCurrent = ref(false)
const showNew = ref(false)
const showConfirm = ref(false)

// Strength: 0-4 buckets
const strengthLevel = computed(() => {
  const len = newPassword.value.length
  if (!len) return 0
  if (len < 8) return 1
  if (len < 10) return 2
  if (len < 14) return 3
  return 4
})
const strengthLabel = computed(() => ['', 'Too short', 'Weak', 'Good', 'Strong'][strengthLevel.value])
const strengthColor = computed(() => [
  '', 'bg-destructive', 'bg-orange-400', 'bg-yellow-400', 'bg-green-500'
][strengthLevel.value])

// Field-level errors
const errors = computed(() => {
  const e: Record<string, string> = {}
  if (newPassword.value && newPassword.value.length < 8)
    e.newPassword = 'Must be at least 8 characters'
  if (newPassword.value && currentPassword.value && newPassword.value === currentPassword.value)
    e.newPassword = 'Must differ from current password'
  if (confirmPassword.value && confirmPassword.value !== newPassword.value)
    e.confirmPassword = 'Passwords do not match'
  return e
})

const isValid = computed(() =>
  currentPassword.value.trim() !== '' &&
  newPassword.value.length >= 8 &&
  confirmPassword.value === newPassword.value &&
  newPassword.value !== currentPassword.value
)

async function handleSubmit() {
  if (!isValid.value || isLoading.value) return
  isLoading.value = true
  errorMessage.value = ''
  successMessage.value = ''
  try {
    await excelFileAPI.changePassword(currentPassword.value, newPassword.value)
    successMessage.value = 'Password changed successfully!'
    currentPassword.value = ''
    newPassword.value = ''
    confirmPassword.value = ''
    setTimeout(() => handleClose(), 1800)
  } catch (err: any) {
    errorMessage.value = err?.response?.data?.detail || 'Failed to change password. Please try again.'
  } finally {
    isLoading.value = false
  }
}

function handleClose() {
  if (!isLoading.value) {
    open.value = false
    emit('close')
  }
}
</script>

<template>
  <Dialog :open="open" @update:open="(v) => { if (!v) handleClose() }">
    <DialogContent class="sm:max-w-[420px] gap-0 p-0 overflow-hidden">

      <!-- Header -->
      <DialogHeader class="px-6 pt-6 pb-4">
        <div class="flex items-center gap-3">
          <div class="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
            <iconify-icon icon="lucide:key-round" class="h-5 w-5" />
          </div>
          <div>
            <DialogTitle class="text-base">Change Password</DialogTitle>
            <DialogDescription class="text-xs mt-0.5">Update your account password securely</DialogDescription>
          </div>
        </div>
      </DialogHeader>

      <Separator />

      <!-- Form body -->
      <form class="px-6 py-5 space-y-4" @submit.prevent="handleSubmit" novalidate>

        <!-- Success banner -->
        <div
          v-if="successMessage"
          class="flex items-center gap-2 rounded-md border border-green-200 bg-green-50 px-3 py-2.5 text-sm text-green-700 dark:border-green-800 dark:bg-green-950/40 dark:text-green-400"
        >
          <iconify-icon icon="lucide:check-circle" class="h-4 w-4 shrink-0" />
          {{ successMessage }}
        </div>

        <!-- Error banner -->
        <div
          v-if="errorMessage"
          class="flex items-center gap-2 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2.5 text-sm text-destructive"
        >
          <iconify-icon icon="lucide:circle-alert" class="h-4 w-4 shrink-0" />
          {{ errorMessage }}
        </div>

        <!-- Current Password -->
        <div class="space-y-1.5">
          <label class="text-sm font-medium" for="cpw-current">Current Password</label>
          <div class="relative">
            <iconify-icon
              icon="lucide:lock"
              class="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground pointer-events-none"
            />
            <Input
              id="cpw-current"
              v-model="currentPassword"
              :type="showCurrent ? 'text' : 'password'"
              class="pl-9 pr-9"
              placeholder="Enter current password"
              autocomplete="current-password"
              :disabled="isLoading"
            />
            <button
              type="button"
              class="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors"
              @click="showCurrent = !showCurrent"
              tabindex="-1"
              aria-label="Toggle visibility"
            >
              <iconify-icon :icon="showCurrent ? 'lucide:eye-off' : 'lucide:eye'" class="h-4 w-4" />
            </button>
          </div>
        </div>

        <!-- New Password -->
        <div class="space-y-1.5">
          <label class="text-sm font-medium" for="cpw-new">New Password</label>
          <div class="relative">
            <iconify-icon
              icon="lucide:lock-keyhole"
              class="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground pointer-events-none"
            />
            <Input
              id="cpw-new"
              v-model="newPassword"
              :type="showNew ? 'text' : 'password'"
              :class="['pl-9 pr-9', errors.newPassword ? 'border-destructive focus-visible:ring-destructive/30' : '']"
              placeholder="At least 8 characters"
              autocomplete="new-password"
              :disabled="isLoading"
            />
            <button
              type="button"
              class="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors"
              @click="showNew = !showNew"
              tabindex="-1"
              aria-label="Toggle visibility"
            >
              <iconify-icon :icon="showNew ? 'lucide:eye-off' : 'lucide:eye'" class="h-4 w-4" />
            </button>
          </div>
          <p v-if="errors.newPassword" class="text-xs text-destructive">{{ errors.newPassword }}</p>
          <!-- Strength bar -->
          <div v-if="newPassword" class="space-y-1">
            <div class="flex gap-1 h-1">
              <div
                v-for="i in 4" :key="i"
                class="flex-1 rounded-full transition-all duration-300"
                :class="i <= strengthLevel ? [strengthColor, 'opacity-100'] : 'bg-muted opacity-60'"
              />
            </div>
            <p class="text-xs text-muted-foreground">{{ strengthLabel }}</p>
          </div>
        </div>

        <!-- Confirm Password -->
        <div class="space-y-1.5">
          <label class="text-sm font-medium" for="cpw-confirm">Confirm New Password</label>
          <div class="relative">
            <iconify-icon
              icon="lucide:shield-check"
              class="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground pointer-events-none"
            />
            <Input
              id="cpw-confirm"
              v-model="confirmPassword"
              :type="showConfirm ? 'text' : 'password'"
              :class="['pl-9 pr-9', errors.confirmPassword ? 'border-destructive focus-visible:ring-destructive/30' : '']"
              placeholder="Re-enter new password"
              autocomplete="new-password"
              :disabled="isLoading"
            />
            <button
              type="button"
              class="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors"
              @click="showConfirm = !showConfirm"
              tabindex="-1"
              aria-label="Toggle visibility"
            >
              <iconify-icon :icon="showConfirm ? 'lucide:eye-off' : 'lucide:eye'" class="h-4 w-4" />
            </button>
          </div>
          <p v-if="errors.confirmPassword" class="text-xs text-destructive">{{ errors.confirmPassword }}</p>
        </div>
      </form>

      <Separator />

      <!-- Footer -->
      <DialogFooter class="px-6 py-4 gap-2">
        <Button variant="outline" @click="handleClose" :disabled="isLoading">
          Cancel
        </Button>
        <Button
          type="submit"
          :disabled="!isValid || isLoading"
          @click="handleSubmit"
          class="gap-2"
        >
          <iconify-icon
            :icon="isLoading ? 'eos-icons:loading' : 'lucide:check'"
            :class="['h-4 w-4', isLoading && 'animate-spin']"
          />
          {{ isLoading ? 'Changing…' : 'Change Password' }}
        </Button>
      </DialogFooter>

    </DialogContent>
  </Dialog>
</template>
