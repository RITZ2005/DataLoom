<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle
} from '@/components/ui/dialog'
import excelFileAPI, { type UploadResponse, type SavedQuestion } from '@/services/excelApi'
import { toast } from 'vue-sonner'

const router = useRouter()
const uploadProgress = ref(0)
const uploadStage = ref('')
const uploadMessage = ref('')
const isUploading = ref(false)
const uploadError = ref<string | null>(null)
const fileWaitingForProcess = ref<UploadResponse | null>(null)

// Auto-replay state
const showReplayDialog = ref(false)
const savedQuestions = ref<SavedQuestion[]>([])
const applyGeneric = ref(true)
const isReplaying = ref(false)
const replayProgress = ref({ current: 0, total: 0 })

const stageConfig: Record<string, { icon: string, label: string }> = {
  uploading: { icon: 'lucide:upload', label: 'Uploading' },
  initializing: { icon: 'lucide:settings', label: 'Initializing' },
  reading: { icon: 'lucide:file-search', label: 'Reading File' },
  metadata: { icon: 'lucide:database', label: 'Analyzing Metadata' },
  embedding: { icon: 'lucide:brain', label: 'Creating Embeddings' },
  saving: { icon: 'lucide:save', label: 'Saving to Database' },
  complete: { icon: 'lucide:check-circle', label: 'Complete' },
  error: { icon: 'lucide:x-circle', label: 'Error' }
}

async function handleFileUpload(event: Event) {
  const input = event.target as HTMLInputElement
  if (!input.files?.length) return

  const file = input.files[0]
  try {
    uploadProgress.value = 0
    uploadStage.value = 'uploading'
    uploadMessage.value = 'Starting upload...'
    isUploading.value = true
    uploadError.value = null
    
    const result = await excelFileAPI.uploadFileWithProgress(
      file, 
      (stage, current, total, message) => {
        uploadStage.value = stage
        uploadProgress.value = current
        uploadMessage.value = message
      }
    )
    
    fileWaitingForProcess.value = result
    input.value = ''
    uploadProgress.value = 100
    uploadStage.value = 'complete'
    uploadMessage.value = 'Upload complete!'

    // Check for saved questions at this file's scope
    await checkForSavedQuestions(result.file_uuid)
    
  } catch (error: any) {
    console.error('Upload failed:', error)
    uploadError.value = error?.message || 'Upload failed. Please try again.'
    uploadStage.value = 'error'
  } finally {
    isUploading.value = false
  }
}

async function checkForSavedQuestions(fileUuid: string) {
  try {
    const questions = await excelFileAPI.listSavedQuestionsForFile(fileUuid)
    if (questions.length > 0) {
      savedQuestions.value = questions
      applyGeneric.value = true
      showReplayDialog.value = true
    }
  } catch (e) {
    console.error('Failed to check saved questions:', e)
  }
}

function toggleGenericFilter(val: boolean | 'indeterminate') {
  applyGeneric.value = val === true
}

const filteredQuestions = () => {
  return savedQuestions.value.filter(q => q.question_category?.trim().toLowerCase() === 'generic' && applyGeneric.value)
}

const genericCount = () => savedQuestions.value.filter(q => q.question_category?.trim().toLowerCase() === 'generic').length

async function runAutoReplay() {
  if (!fileWaitingForProcess.value) return
  const questions = filteredQuestions().map(q => q.question_text)
  if (questions.length === 0) {
    showReplayDialog.value = false
    return
  }

  isReplaying.value = true
  replayProgress.value = { current: 0, total: questions.length }

  try {
    await excelFileAPI.batchQuery(fileWaitingForProcess.value.file_uuid, questions)
    showReplayDialog.value = false
    // Navigate to chat page with pre-filled history
    router.push({ path: '/app/chat', query: { fileId: fileWaitingForProcess.value.file_uuid } })
  } catch (e: any) {
    console.error('Auto-replay failed:', e)
    toast.error('Auto-replay failed. You can still chat with the file manually.')
    showReplayDialog.value = false
  } finally {
    isReplaying.value = false
  }
}

function skipReplay() {
  showReplayDialog.value = false
}

function goToDocuments() {
  router.push('/app')
}

function goToChat() {
  if (fileWaitingForProcess.value) {
    router.push({ path: '/app/chat', query: { fileId: fileWaitingForProcess.value.file_uuid } })
  } else {
    router.push('/app/chat')
  }
}

function resetUpload() {
  fileWaitingForProcess.value = null
  uploadError.value = null
  uploadProgress.value = 0
  uploadStage.value = ''
  uploadMessage.value = ''
  savedQuestions.value = []
  showReplayDialog.value = false
}

function getCurrentStageConfig() {
  return stageConfig[uploadStage.value] || stageConfig.uploading
}
</script>

<template>
  <div class="flex flex-col gap-6 pb-8 p-4 sm:p-6">
    <div class="sticky top-0 bg-background/80 backdrop-blur-xl z-10 pt-4 pb-3">
      <div class="flex items-center gap-3">
        <div class="w-10 h-10 rounded-xl bg-gradient-to-br from-primary/90 to-primary/60 flex items-center justify-center shadow-sm">
          <iconify-icon icon="lucide:upload-cloud" class="h-5 w-5 text-primary-foreground" />
        </div>
        <div>
          <h1 class="text-2xl font-semibold tracking-tight">Upload Documents</h1>
          <p class="text-sm text-muted-foreground">Upload Excel or CSV files for AI-powered analysis</p>
        </div>
      </div>
    </div>

    <div class="max-w-2xl mx-auto w-full">
      <Card class="glass-card border border-border/50 rounded-2xl shadow-sm hover:border-primary/30 transition-all duration-300">
        <CardHeader class="text-center pb-2">
          <CardTitle class="text-xl font-semibold">Upload New Document</CardTitle>
          <CardDescription class="text-sm">Drag and drop or click to select files</CardDescription>
        </CardHeader>
        <CardContent class="space-y-6 pt-4">
          
          <!-- Upload Area -->
          <div 
            v-if="!isUploading && !fileWaitingForProcess && !uploadError"
            class="border border-dashed border-border/60 rounded-2xl p-10 text-center hover:border-primary/40 hover:bg-primary/5 transition-all duration-300 cursor-pointer group"
          >
            <div class="w-16 h-16 rounded-2xl bg-muted/40 flex items-center justify-center mx-auto mb-5 group-hover:bg-primary/10 transition-colors duration-300">
              <iconify-icon icon="lucide:file-plus-2" class="h-8 w-8 text-muted-foreground/60 group-hover:text-primary/70 transition-colors duration-300" />
            </div>
            <div class="space-y-4 flex flex-col items-center">
              <label class="inline-flex items-center gap-2 px-6 py-2.5 bg-primary text-primary-foreground rounded-xl font-medium text-sm hover:bg-primary/90 cursor-pointer transition-colors shadow-sm">
                <iconify-icon icon="lucide:upload" class="h-4 w-4" />
                Choose File
                <input
                  type="file"
                  accept=".xlsx,.xls,.csv"
                  @change="handleFileUpload"
                  class="hidden"
                />
              </label>
              <p class="text-sm text-muted-foreground">or drag & drop your file here</p>
              <div class="flex items-center justify-center gap-2 text-xs text-muted-foreground/70">
                <span class="px-2.5 py-1 bg-muted/50 rounded-lg">.xlsx</span>
                <span class="px-2.5 py-1 bg-muted/50 rounded-lg">.xls</span>
                <span class="px-2.5 py-1 bg-muted/50 rounded-lg">.csv</span>
              </div>
            </div>
          </div>
          
          <!-- Uploading State -->
          <div v-if="isUploading" class="py-8 text-center">
            <div class="relative inline-block mb-6">
              <div class="w-20 h-20 rounded-full border-[3px] border-muted animate-spin border-t-primary mx-auto"></div>
              <div class="absolute inset-0 flex items-center justify-center">
                <iconify-icon :icon="getCurrentStageConfig().icon" class="h-8 w-8 text-primary" />
              </div>
            </div>
            
            <div class="mb-5">
              <p class="text-lg font-semibold">{{ getCurrentStageConfig().label }}</p>
              <p class="text-sm text-muted-foreground mt-1">{{ uploadMessage }}</p>
            </div>
            
            <div class="max-w-sm mx-auto">
              <div class="flex justify-between text-sm mb-2">
                <span class="text-muted-foreground">Progress</span>
                <span class="font-semibold text-primary">{{ uploadProgress }}%</span>
              </div>
              <div class="w-full bg-muted/50 rounded-full h-2 overflow-hidden">
                <div 
                  class="h-2 rounded-full transition-all duration-500 ease-out bg-gradient-to-r from-primary/80 to-primary"
                  :style="{ width: uploadProgress + '%' }"
                ></div>
              </div>
              
              <div class="flex justify-between mt-4 text-xs text-muted-foreground">
                <span :class="{'text-primary font-medium': uploadStage === 'reading'}">Reading</span>
                <span :class="{'text-primary font-medium': uploadStage === 'metadata'}">Metadata</span>
                <span :class="{'text-primary font-medium': uploadStage === 'embedding'}">Embedding</span>
                <span :class="{'text-primary font-medium': uploadStage === 'saving'}">Saving</span>
              </div>
            </div>
          </div>

          <!-- Error State -->
          <div v-if="uploadError" class="bg-destructive/5 border border-destructive/20 rounded-xl p-5">
            <div class="flex items-start gap-3">
              <div class="w-9 h-9 rounded-xl bg-destructive/10 flex items-center justify-center shrink-0">
                <iconify-icon icon="lucide:x-circle" class="h-5 w-5 text-destructive" />
              </div>
              <div class="flex-1">
                <p class="font-semibold text-sm">Upload Failed</p>
                <p class="text-sm text-muted-foreground mt-1">{{ uploadError }}</p>
                <Button size="sm" variant="outline" class="mt-3 rounded-lg" @click="resetUpload">Try Again</Button>
              </div>
            </div>
          </div>

          <!-- Success State -->
          <div v-if="fileWaitingForProcess && !isUploading" class="py-8 text-center">
            <div class="w-16 h-16 rounded-2xl bg-green-500/10 flex items-center justify-center mx-auto mb-4">
              <iconify-icon icon="lucide:check" class="h-8 w-8 text-green-600 dark:text-green-400" />
            </div>
            <h3 class="text-lg font-semibold">Upload Successful</h3>
            <p class="text-sm text-muted-foreground mt-2">
              <span class="font-medium text-foreground">{{ fileWaitingForProcess.filename }}</span> is ready for analysis
            </p>
            <div class="flex items-center justify-center gap-3 text-xs text-muted-foreground mt-2">
              <span class="px-2 py-1 bg-muted/50 rounded-lg">{{ fileWaitingForProcess.rows?.toLocaleString() }} rows</span>
              <span class="px-2 py-1 bg-muted/50 rounded-lg">{{ fileWaitingForProcess.columns?.length }} columns</span>
            </div>
            <div class="flex justify-center gap-3 mt-6">
              <Button class="rounded-xl" @click="goToDocuments">
                <iconify-icon icon="lucide:folder-open" class="h-4 w-4 mr-2" />
                View in Documents
              </Button>
              <Button variant="outline" class="rounded-xl" @click="goToChat">
                <iconify-icon icon="lucide:message-circle" class="h-4 w-4 mr-2" />
                Chat with Data
              </Button>
            </div>
            <Button variant="ghost" size="sm" class="mt-4 text-xs" @click="resetUpload">Upload Another File</Button>
          </div>
        </CardContent>
      </Card>

      <!-- Quick Tips -->
      <Card class="mt-6 glass-card border border-border/50 rounded-2xl shadow-sm">
        <CardContent class="pt-5 pb-5">
          <div class="flex items-start gap-3">
            <div class="w-8 h-8 rounded-xl bg-amber-500/10 flex items-center justify-center shrink-0">
              <iconify-icon icon="lucide:lightbulb" class="h-4 w-4 text-amber-600 dark:text-amber-400" />
            </div>
            <div>
              <p class="font-medium text-sm">Quick Tips</p>
              <ul class="text-xs text-muted-foreground mt-2 space-y-1.5">
                <li class="flex items-center gap-2"><span class="w-1 h-1 rounded-full bg-muted-foreground/40 shrink-0"></span>Upload Excel (.xlsx, .xls) or CSV files for analysis</li>
                <li class="flex items-center gap-2"><span class="w-1 h-1 rounded-full bg-muted-foreground/40 shrink-0"></span>Documents are automatically processed and embedded for AI chat</li>
                <li class="flex items-center gap-2"><span class="w-1 h-1 rounded-full bg-muted-foreground/40 shrink-0"></span>Larger files take longer to embed (100 rows per batch)</li>
                <li class="flex items-center gap-2"><span class="w-1 h-1 rounded-full bg-muted-foreground/40 shrink-0"></span>Use Chat to query your data using natural language</li>
              </ul>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>

    <!-- Auto-Replay Dialog -->
    <Dialog :open="showReplayDialog" @update:open="(v: boolean) => { if (!v && !isReplaying) showReplayDialog = false }">
      <DialogContent class="sm:max-w-md rounded-2xl">
        <DialogHeader>
          <DialogTitle class="flex items-center gap-2">
            <iconify-icon icon="lucide:bookmark-check" class="h-5 w-5 text-amber-500" />
            Saved Questions Found
          </DialogTitle>
          <DialogDescription>
            We found {{ savedQuestions.length }} saved question(s) for this directory. Would you like to auto-generate answers for this new file?
          </DialogDescription>
        </DialogHeader>

        <div class="space-y-4 py-2">
          <!-- Category checkboxes -->
          <div class="space-y-3">
            <div v-if="genericCount() > 0" class="flex items-center gap-3 p-3 rounded-lg border hover:bg-muted/50 transition-colors cursor-pointer" @click="applyGeneric = !applyGeneric">
              <Checkbox
                :checked="applyGeneric"
                :disabled="isReplaying"
                class="pointer-events-none"
              />
              <div class="flex-1">
                <div class="text-sm font-medium flex items-center gap-2">
                  <iconify-icon icon="lucide:globe" class="h-4 w-4 text-blue-500" />
                  Generic Questions
                  <span class="text-xs text-muted-foreground">({{ genericCount() }})</span>
                </div>
                <p class="text-xs text-muted-foreground mt-0.5">Applied to any file in this folder</p>
              </div>
            </div>

          </div>

          <!-- Preview of questions -->
          <div class="max-h-40 overflow-y-auto rounded-lg border bg-muted/30 p-3 space-y-1.5">
            <div
              v-for="q in filteredQuestions()"
              :key="q.id"
              class="text-xs flex items-start gap-2"
            >
              <iconify-icon
                icon="lucide:globe"
                class="h-3 w-3 mt-0.5 flex-shrink-0 text-blue-500"
              />
              <span class="text-gray-700 dark:text-gray-300">{{ q.question_text }}</span>
            </div>
            <div v-if="filteredQuestions().length === 0" class="text-xs text-muted-foreground text-center py-2">
              No questions selected
            </div>
          </div>

          <!-- Replaying progress -->
          <div v-if="isReplaying" class="flex items-center gap-3 p-3 rounded-lg bg-blue-50 dark:bg-blue-950/30 border border-blue-200 dark:border-blue-800">
            <iconify-icon icon="eos-icons:loading" class="h-5 w-5 text-blue-600 animate-spin" />
            <div>
              <p class="text-sm font-medium text-blue-900 dark:text-blue-100">Processing questions...</p>
              <p class="text-xs text-blue-700 dark:text-blue-300">This may take a moment</p>
            </div>
          </div>
        </div>

        <DialogFooter class="gap-2">
          <Button variant="ghost" size="sm" :disabled="isReplaying" @click="skipReplay">
            Skip
          </Button>
          <Button size="sm" :disabled="isReplaying || filteredQuestions().length === 0" @click="runAutoReplay">
            <iconify-icon v-if="isReplaying" icon="eos-icons:loading" class="h-4 w-4 mr-2 animate-spin" />
            <iconify-icon v-else icon="lucide:play" class="h-4 w-4 mr-2" />
            {{ isReplaying ? 'Processing...' : `Apply ${filteredQuestions().length} Question(s)` }}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </div>
</template>
