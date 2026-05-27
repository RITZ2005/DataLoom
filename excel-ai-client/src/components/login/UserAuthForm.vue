<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Login } from '@/store/login'
import { toast } from 'vue-sonner'

const props = defineProps<{
  isRegister?: boolean
}>()

const router = useRouter()
const loginStore = Login()
const isLoading = ref(false)
const email = ref('')
const password = ref('')
const username = ref('')
const name = ref('')
const showPassword = ref(false)

async function onSubmit(event: Event) {
  event.preventDefault()
  if (!email.value || !password.value) {
    toast.error('Please fill in all fields')
    return
  }
  
  if (props.isRegister && !username.value) {
    toast.error('Please enter a username')
    return
  }

  isLoading.value = true
  try {
    let success = false
    if (props.isRegister) {
      success = await loginStore.register(
        email.value,
        username.value,
        password.value,
        name.value || username.value
      )
    } else {
      success = await loginStore.login(email.value, password.value)
    }
    if (success) {
      toast.success(props.isRegister ? 'Account created successfully!' : 'Login successful!')
      router.push('/app')
    } else {
      toast.error('Authentication failed')
    }
  } catch (error: any) {
    toast.error(error.message || 'An error occurred during authentication')
    console.error(error)
  } finally {
    isLoading.value = false
  }
}
</script>

<template>
  <div :class="cn('grid gap-6', $attrs.class ?? '')">
    <form @submit="onSubmit">
      <div class="grid gap-4">
        <div v-if="isRegister" class="grid gap-1.5">
          <Label for="username" class="text-sm font-medium text-foreground/90">
            Username
          </Label>
          <div class="relative group">
            <div class="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground group-focus-within:text-foreground transition-colors">
              <iconify-icon icon="lucide:user" class="h-4 w-4" />
            </div>
            <Input
                id="username"
                v-model="username"
                placeholder="johndoe"
                type="text"
                auto-capitalize="none"
                auto-complete="username"
                :disabled="isLoading"
                class="pl-10 h-9 transition-colors bg-background text-foreground"
            />
          </div>
        </div>
        
        <div v-if="isRegister" class="grid gap-1.5">
          <Label for="name" class="text-sm font-medium text-foreground/90">
            Full Name <span class="text-muted-foreground text-xs">(optional)</span>
          </Label>
          <div class="relative group">
            <div class="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground group-focus-within:text-foreground transition-colors">
              <iconify-icon icon="lucide:user-circle" class="h-4 w-4" />
            </div>
            <Input
                id="name"
                v-model="name"
                placeholder="John Doe"
                type="text"
                auto-capitalize="none"
                auto-complete="name"
                :disabled="isLoading"
                class="pl-10 h-9 transition-colors bg-background text-foreground"
            />
          </div>
        </div>
        
        <div class="grid gap-1.5">
          <Label for="email" class="text-sm font-medium text-foreground/90">
            Email or Username
          </Label>
          <div class="relative group">
            <div class="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground group-focus-within:text-foreground transition-colors">
              <iconify-icon icon="lucide:mail" class="h-4 w-4" />
            </div>
            <Input
                id="email"
                v-model="email"
              placeholder="name@example.com or your username"
              type="text"
                auto-capitalize="none"
                auto-complete="email"
                auto-correct="off"
                :disabled="isLoading"
                class="h-9 bg-background pl-10 text-foreground transition-colors"
            />
          </div>
        </div>
        
        <div class="grid gap-1.5">
          <div class="flex items-center justify-between">
            <Label for="password" class="text-sm font-medium text-foreground/90">
              Password
            </Label>
            <router-link v-if="!isRegister" to="/forgot-password" class="text-xs text-muted-foreground hover:text-foreground transition-colors">
              Forgot password?
            </router-link>
          </div>
          <div class="relative group">
            <div class="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground group-focus-within:text-foreground transition-colors">
              <iconify-icon icon="lucide:lock" class="h-4 w-4" />
            </div>
            <Input
                id="password"
                v-model="password"
                :placeholder="isRegister ? 'Create a strong password' : '••••••••'"
                :type="showPassword ? 'text' : 'password'"
                auto-complete="current-password"
                :disabled="isLoading"
                class="h-9 bg-background pl-10 pr-10 text-foreground transition-colors"
            />
            <button
                type="button"
                @click="showPassword = !showPassword"
                class="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors"
                tabindex="-1"
            >
              <iconify-icon :icon="showPassword ? 'lucide:eye-off' : 'lucide:eye'" class="h-4 w-4" />
            </button>
          </div>
          <p v-if="isRegister" class="text-xs text-muted-foreground">
            Must be at least 8 characters long
          </p>
        </div>
        
        <Button
            type="submit"
            :disabled="isLoading"
          class="mt-1 h-10 w-full font-semibold bg-emerald-600 hover:bg-emerald-700 text-white"
        >
          <iconify-icon v-if="isLoading" icon="svg-spinners:180-ring-with-bg" class="mr-2 h-4 w-4" />
          <iconify-icon v-else :icon="isRegister ? 'lucide:user-plus' : 'lucide:log-in'" class="mr-2 h-4 w-4" />
          {{ isRegister ? 'Create Account' : 'Sign In' }}
        </Button>

        <div v-if="isRegister" class="border-t pt-3 text-center text-sm text-muted-foreground">
          Already have an account?
          <router-link to="/login" class="ml-1 font-medium text-primary hover:opacity-90 transition-opacity">
            Sign in
          </router-link>
        </div>

        <template v-if="!isRegister">
          <div class="grid grid-cols-2 gap-2.5 py-0.5">
            <div class="flex items-center gap-2 rounded-lg border border-border/50 bg-muted/50 px-2.5 py-2">
              <iconify-icon icon="lucide:shield-check" class="h-4 w-4 shrink-0 text-emerald-600 dark:text-emerald-400" />
              <div>
                <p class="text-xs font-semibold text-foreground">Trusted & Secure</p>
                <p class="text-[10px] text-muted-foreground">Enterprise-grade security</p>
              </div>
            </div>
            <div class="flex items-center gap-2 rounded-lg border border-border/50 bg-muted/50 px-2.5 py-2">
              <iconify-icon icon="lucide:brain-circuit" class="h-4 w-4 shrink-0 text-emerald-600 dark:text-emerald-400" />
              <div>
                <p class="text-xs font-semibold text-foreground">AI-Powered</p>
                <p class="text-[10px] text-muted-foreground">Smart insights instantly</p>
              </div>
            </div>
          </div>

          <div class="border-t pt-3 text-center text-sm text-muted-foreground">
            Don't have an account?
            <router-link to="/register" class="ml-1 font-medium text-primary hover:opacity-90 transition-opacity">
              Sign up
            </router-link>
          </div>
        </template>
      </div>
    </form>
  </div>
</template>