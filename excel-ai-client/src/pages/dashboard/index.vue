<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import excelFileAPI, { type FileInfo } from '@/services/excelApi'

const router = useRouter()
const files = ref<FileInfo[]>([])
const isLoading = ref(false)
const stats = ref({
  totalFiles: 0,
  totalRows: 0,
  totalColumns: 0
})

onMounted(async () => {
  await loadFiles()
})

async function loadFiles() {
  isLoading.value = true
  try {
    files.value = await excelFileAPI.listFiles()
    
    // Calculate stats
    stats.value.totalFiles = files.value.length
    stats.value.totalRows = files.value.reduce((sum, f) => sum + f.total_rows, 0)
    stats.value.totalColumns = files.value.reduce((sum, f) => sum + f.columns.length, 0)
  } catch (error: any) {
    console.error('Error loading files:', error)
  } finally {
    isLoading.value = false
  }
}

function goToFiles() {
  router.push('/app')
}

function goToUpload() {
  router.push('/app')
}

function goToChat() {
  router.push('/app/chat')
}
</script>

<template>
  <div class="flex flex-col gap-6">
    <!-- Header -->
    <div>
      <h1 class="text-2xl font-semibold tracking-tight">Excel Analysis Dashboard</h1>
      <p class="text-muted-foreground">Manage and analyze your Excel files with AI</p>
    </div>

    <!-- Stats Cards -->
    <div class="grid gap-4 md:grid-cols-3">
      <Card>
        <CardHeader class="pb-2">
          <div class="flex items-center gap-2">
            <iconify-icon icon="lucide:file-spreadsheet" class="h-6 w-6 text-primary" />
            <CardTitle class="text-sm font-medium">Total Files</CardTitle>
          </div>
        </CardHeader>
        <CardContent>
          <div class="text-2xl font-bold">{{ stats.totalFiles }}</div>
          <p class="text-xs text-muted-foreground">Excel files uploaded</p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader class="pb-2">
          <div class="flex items-center gap-2">
            <iconify-icon icon="lucide:rows-3" class="h-6 w-6 text-primary" />
            <CardTitle class="text-sm font-medium">Total Rows</CardTitle>
          </div>
        </CardHeader>
        <CardContent>
          <div class="text-2xl font-bold">{{ stats.totalRows.toLocaleString() }}</div>
          <p class="text-xs text-muted-foreground">Data records</p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader class="pb-2">
          <div class="flex items-center gap-2">
            <iconify-icon icon="lucide:columns-3" class="h-6 w-6 text-primary" />
            <CardTitle class="text-sm font-medium">Total Columns</CardTitle>
          </div>
        </CardHeader>
        <CardContent>
          <div class="text-2xl font-bold">{{ stats.totalColumns }}</div>
          <p class="text-xs text-muted-foreground">Data fields</p>
        </CardContent>
      </Card>
    </div>

    <!-- Main Action Cards -->
    <div class="grid gap-4 md:grid-cols-2">
      <Card class="cursor-pointer hover:shadow-lg transition-shadow" @click="goToUpload">
        <CardHeader>
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-2">
              <iconify-icon icon="lucide:upload" class="h-6 w-6 text-primary" />
              <div>
                <CardTitle>Upload Excel Files</CardTitle>
                <CardDescription>Upload and analyze Excel or CSV files</CardDescription>
              </div>
            </div>
            <Button>Browse</Button>
          </div>
        </CardHeader>
      </Card>

      <Card class="cursor-pointer hover:shadow-lg transition-shadow" @click="goToChat">
        <CardHeader>
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-2">
              <iconify-icon icon="lucide:message-circle" class="h-6 w-6 text-primary" />
              <div>
                <CardTitle>Chat with Excel</CardTitle>
                <CardDescription>Ask questions about your data using AI</CardDescription>
              </div>
            </div>
            <Button>Chat</Button>
          </div>
        </CardHeader>
      </Card>
    </div>

    <!-- Recent Files -->
    <Card v-if="files.length > 0">
      <CardHeader>
        <CardTitle>Recent Files</CardTitle>
        <CardDescription>Your uploaded Excel files</CardDescription>
      </CardHeader>
      <CardContent>
        <div class="space-y-3">
          <div
            v-for="file in files.slice(0, 5)"
            :key="file.file_uuid"
            class="flex items-center justify-between p-3 border rounded-lg hover:bg-muted/50 transition-colors"
          >
            <div class="flex items-center gap-3 flex-1">
              <iconify-icon icon="lucide:file-spreadsheet" class="h-4 w-4 text-muted-foreground" />
              <div class="flex-1">
                <span class="text-sm font-medium">{{ file.filename }}</span>
                <span class="text-xs text-muted-foreground ml-2">{{ file.total_rows }} rows • {{ file.columns.length }} columns</span>
              </div>
            </div>
            <Button variant="ghost" size="sm" @click="() => router.push('/app')">
              View
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>

    <!-- Empty State -->
    <Card v-else>
      <CardContent class="pt-12 pb-12 text-center space-y-4">
        <iconify-icon icon="lucide:file-spreadsheet" class="h-12 w-12 text-muted-foreground mx-auto" />
        <div>
          <p class="font-medium">No files uploaded yet</p>
          <p class="text-sm text-muted-foreground">Upload an Excel file to get started</p>
        </div>
        <Button @click="goToUpload">Upload File</Button>
      </CardContent>
    </Card>
  </div>
</template>