import './assets/index.css'
import 'iconify-icon'
// import './assets/template.scss'

import { createApp } from 'vue'
import { createPinia } from 'pinia'

import App from './App.vue'
import router from './router/router'
import { MQLOptions } from './plugins/mqlOptions'
import piniaPluginPersistedstate from 'pinia-plugin-persistedstate';

const initializeTheme = () => {
    const root = document.documentElement
    const savedTheme = localStorage.getItem('theme')
    const themeColors = ['red', 'rose', 'orange', 'green', 'blue', 'yellow', 'violet', 'black']

    const isDarkMode = savedTheme ? savedTheme === 'dark' : true
    root.classList.toggle('dark', isDarkMode)

    // Palette switching is temporarily disabled, but keep the original cleanup logic for later reuse.
    // const oldThemeColors = ['red', 'rose', 'orange', 'green', 'blue', 'yellow', 'violet']
    // oldThemeColors.forEach((color) => root.classList.remove(color))
    // localStorage.removeItem('color')

    themeColors.forEach((color) => root.classList.remove(color))
    root.classList.add('green')
    localStorage.setItem('color', 'green')
}

initializeTheme()

const piniaStore = createPinia()
piniaStore.use(piniaPluginPersistedstate)
const app = createApp(App)
const baseURL = '/server'
const cdnBaseURL = '/cdnserver'

app.use(piniaStore)
app.use(router)
// window.sessionStorage.setItem('user-token', "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2VySWQiOiJwcmFqd2FscEBta2NsLm9yZyIsImdyb3VwcyI6WyJDb21wYW55QWRtaW4iXSwiY2xpZW50SVAiOiI0NS4xMjcuMTIxLjE0IiwiaGl0c0NvdW50IjowLCJ0b2tlbiI6IiIsIm1ldGFkYXRhIjoie1wiY29tcGFueUlkXCI6XCIxTWc2TkQ5bW9MTmVKVHhRemtXbEd1SG02UGNcIixcInByb2plY3ROYW1lXCI6XCJQbGF5R3JvdW5kXCIsXCJwcm9qZWN0SWRcIjpcIjFNZzZWa2JNMU1RaGhLaDh6MnFHU2E0MkhJWVwifSIsImV4cCI6MTc2Mjg0MzMyN30.-S_dwJXw0PG93Aipbcf4HDSrYbtliGQaY8tkWVbzA_g")

MQLOptions.baseURL = baseURL
MQLOptions.cdnBaseURL = cdnBaseURL
MQLOptions.cdnConfig = [
    {
        bucketName: 'projectConfig',
        clientId: '1NdOhs02GToVSXoWcyBcBctXHd9',
        isPrivateBucket: false,
        purposeId: '1NdOhs02GToVSXoWcyBcBctXHd9',
        bucketId: '1NdOhs02GToVSXoWcyBcBctXHd9'
    }
]
app.mount('#app')