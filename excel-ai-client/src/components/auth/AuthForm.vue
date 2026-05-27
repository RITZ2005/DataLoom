<script setup lang="ts">
import { ref } from 'vue'

// import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { useRouter } from 'vue-router';
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Login } from '@/store/login'
import { toast } from "vue-sonner"
// import MQL from "@/plugins/mql";
const router = useRouter();

const isLoading = ref(false)
async function onSubmit(event: Event) {
  event.preventDefault()
  await login()
}

const loginStore = Login()
const username = ref('')
const password = ref('')

async function login() {
  const email = username.value.trim().toLowerCase()
  if (!email || !password.value) {
    toast.error('Please enter email and password')
    return
  }
  isLoading.value = true
  // new MQL() //LocalLoginSvc
  //   .setActivity('o.[query_1HlQ1KcZpAxctpBRZbR79N3iB7P]')
  //   .setData({ loginId: lowerCaseUsername })
  //   .fetch()
  //   .then((rs: any) => {
  //     let res = rs.getActivity('query_1HlQ1KcZpAxctpBRZbR79N3iB7P', false);
  //     if (rs.isValid('query_1HlQ1KcZpAxctpBRZbR79N3iB7P')) {
  //       if (res === null) {
  //         console.log("Email Id Not found");
  //         return;
  //       }
  //       loginStore.setLoginId(lowerCaseUsername);
  //       router.push('/dashboard')

  //       console.log("login successful",loginStore.loginId)
  //     } else {
  //       rs.showErrorToast('query_1HlQ1KcZpAxctpBRZbR79N3iB7P');
  //     }
  //   });
  try {
    const ok = await loginStore.login(email, password.value)
    if (ok) {
      router.push('/dashboard')
      return
    }
    toast.error('Wrong credentials, please try again.')
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : 'Login failed'
    toast.error(message)
  } finally {
    isLoading.value = false
  }
}


</script>

<template>
  <div>
    <VPImage alt="Login" width="1280" height="800" class="block" :image="{
      dark: '/examples/login-dark.png',
      light: '/examples/login-light.png',
    }" />
    <form @submit="onSubmit">
      <div class="grid gap-2">
        <div class="grid gap-1">
          <Label class="sr-only" for="email">
            Email
          </Label>
          <Input id="email" placeholder="enter email Id" type="email" auto-capitalize="none" auto-complete="email"
            auto-correct="off" :disabled="isLoading" v-model="username" />
        </div>
        <div class="grid gap-1">
          <Label class="sr-only" for="password">
            Password
          </Label>
          <Input id="password" placeholder="enter password" type="password" auto-capitalize="none" auto-complete="email"
            auto-correct="off" :disabled="isLoading" v-model="password" />
        </div>
        <Button type="submit" :disabled="isLoading" @click="login">
          <iconify-icon v-if="isLoading" icon="svg-spinners:180-ring-with-bg" class="mr-2 h-4 w-4" />
          Sign In
        </Button>
      </div>
    </form>
    <!-- <div class="relative">
      <div class="absolute inset-0 flex items-center">
        <span class="w-full border-t" />
      </div>
      <div class="relative flex justify-center text-xs uppercase">
        <span class="bg-background px-2 text-muted-foreground">
          Or continue with
        </span>
      </div>
    </div>
    <Button variant="outline" type="button" :disabled="isLoading">
      <iconify-icon v-if="isLoading"icon="svg-spinners:180-ring-with-bg" class="mr-2 h-4 w-4" />
      <iconify-icon icon="mdi:github" class="mr-2 h-4 w-4" />
      GitHub
    </Button> -->
  </div>
</template>