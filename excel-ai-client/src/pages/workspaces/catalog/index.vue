<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import workspaceApi, { 
  type WorkspaceDetailResponse, 
  type SemanticLayerResponse,
  type SemanticMetricRequest,
  type SemanticDimensionRequest,
  type SemanticSynonymRequest
} from '@/services/workspaceApi'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription
} from '@/components/ui/card'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { toast } from 'vue-sonner'

const route = useRoute()
const router = useRouter()
const workspaceId = route.params.workspaceId as string

const workspace = ref<WorkspaceDetailResponse | null>(null)
const semanticLayer = ref<SemanticLayerResponse | null>(null)
const isLoading = ref(true)
const isProfiling = ref(false)
const expandedTables = ref<Record<string, boolean>>({})

// --- Metadata Logic ---
async function fetchDetails() {
  isLoading.value = true
  try {
    workspace.value = await workspaceApi.getWorkspaceDetail(workspaceId)
  } catch (err: any) {
    toast.error('Failed to load workspace details')
    router.push('/app/workspaces')
  } finally {
    isLoading.value = false
  }
}

async function fetchSemanticLayer() {
  try {
    semanticLayer.value = await workspaceApi.getSemanticLayer(workspaceId)
  } catch (err: any) {
    console.error('Failed to load semantic layer', err)
  }
}

function toggleTable(tableName: string) {
  expandedTables.value[tableName] = !expandedTables.value[tableName]
}

async function handleProfileWorkspace() {
  isProfiling.value = true
  toast.info('Starting workspace profiling... This involves LLM analysis and may take a minute.')
  try {
    await workspaceApi.profileWorkspace(workspaceId)
    toast.success('Workspace profiled successfully! Descriptions and embeddings updated.')
    await fetchDetails()
  } catch (err: any) {
    toast.error('Profiling failed')
  } finally {
    isProfiling.value = false
  }
}

const editingId = ref<string | null>(null)
const editValue = ref('')

function startEdit(id: string, current: string) {
  editingId.value = id
  editValue.value = current || ''
}

async function saveTableDescription(tableName: string) {
  try {
    await workspaceApi.updateTableDescription(workspaceId, tableName, editValue.value)
    toast.success('Description updated')
    editingId.value = null
    await fetchDetails()
  } catch (err: any) {
    toast.error('Update failed')
  }
}

async function saveColumnDescription(columnId: string) {
  try {
    await workspaceApi.updateColumnDescription(workspaceId, columnId, editValue.value)
    toast.success('Description updated')
    editingId.value = null
    await fetchDetails()
  } catch (err: any) {
    toast.error('Update failed')
  }
}

// --- Relationships Logic ---
const relationships = ref<any[]>([])
const relForm = ref({ source_table: '', source_column: '', target_table: '', target_column: '', relationship_type: 'foreign_key' })

async function fetchRelationships() {
  try {
    relationships.value = await workspaceApi.getRelationships(workspaceId)
  } catch (err: any) {
    console.error('Failed to load relationships', err)
  }
}

async function createRelationship() {
  if (!relForm.value.source_table || !relForm.value.source_column || !relForm.value.target_table || !relForm.value.target_column) {
    toast.error('All fields are required')
    return
  }
  try {
    await workspaceApi.createRelationship(workspaceId, relForm.value)
    toast.success('Relationship added')
    relForm.value = { source_table: '', source_column: '', target_table: '', target_column: '', relationship_type: 'foreign_key' }
    await fetchRelationships()
  } catch (e: any) {
    toast.error('Failed to create relationship')
  }
}

async function deleteRelationship(id: string) {
  try {
    await workspaceApi.deleteRelationship(workspaceId, id)
    toast.success('Relationship deleted')
    await fetchRelationships()
  } catch (e: any) {
    toast.error('Failed to delete relationship')
  }
}

// --- Semantic Layer Logic ---
const metricForm = ref<SemanticMetricRequest>({ name: '', formula: '', description: '' })
const metricRelatedTablesInput = ref('')
const dimensionForm = ref<SemanticDimensionRequest>({ name: '', table_name: '', column_name: '', dim_type: 'categorical' })
const synonymForm = ref<SemanticSynonymRequest>({ keyword: '', mapped_to: '', mapped_type: 'column' })

async function createMetric() {
  if (!metricForm.value.name || !metricForm.value.formula) {
    toast.error('Name and formula are required')
    return
  }
  try {
    const relatedTables = metricRelatedTablesInput.value
      .split(',')
      .map((t) => t.trim())
      .filter((t, idx, arr) => t.length > 0 && arr.indexOf(t) === idx)

    await workspaceApi.createMetric(workspaceId, {
      ...metricForm.value,
      related_tables: relatedTables.length ? relatedTables : undefined,
    })
    toast.success('Metric added')
    metricForm.value = { name: '', formula: '', description: '' }
    metricRelatedTablesInput.value = ''
    await fetchSemanticLayer()
  } catch (e: any) {
    toast.error('Failed to create metric')
  }
}

async function deleteMetric(id: string) {
  try {
    await workspaceApi.deleteMetric(workspaceId, id)
    toast.success('Metric deleted')
    await fetchSemanticLayer()
  } catch (e: any) {
    toast.error('Failed to delete metric')
  }
}

async function createDimension() {
  if (!dimensionForm.value.name || !dimensionForm.value.table_name || !dimensionForm.value.column_name) {
    toast.error('Name, table, and column are required')
    return
  }
  try {
    await workspaceApi.createDimension(workspaceId, dimensionForm.value)
    toast.success('Dimension added')
    dimensionForm.value = { name: '', table_name: '', column_name: '', dim_type: 'categorical' }
    await fetchSemanticLayer()
  } catch (e: any) {
    toast.error('Failed to create dimension')
  }
}

async function deleteDimension(id: string) {
  try {
    await workspaceApi.deleteDimension(workspaceId, id)
    toast.success('Dimension deleted')
    await fetchSemanticLayer()
  } catch (e: any) {
    toast.error('Failed to delete dimension')
  }
}

async function createSynonym() {
  if (!synonymForm.value.keyword || !synonymForm.value.mapped_to) {
    toast.error('Keyword and mapping are required')
    return
  }
  try {
    await workspaceApi.createSynonym(workspaceId, synonymForm.value)
    toast.success('Synonym added')
    synonymForm.value = { keyword: '', mapped_to: '', mapped_type: 'column' }
    await fetchSemanticLayer()
  } catch (e: any) {
    toast.error('Failed to create synonym')
  }
}

async function deleteSynonym(id: string) {
  try {
    await workspaceApi.deleteSynonym(workspaceId, id)
    toast.success('Synonym deleted')
    await fetchSemanticLayer()
  } catch (e: any) {
    toast.error('Failed to delete synonym')
  }
}

onMounted(() => {
  fetchDetails()
  fetchSemanticLayer()
  fetchRelationships()
})
</script>

<template>
  <div class="p-6 space-y-6 max-w-7xl mx-auto min-h-screen">
    <!-- Breadcrumbs / Back -->
    <div class="flex items-center gap-2 text-sm text-muted-foreground">
      <button @click="router.push('/app/workspaces')" class="hover:text-foreground underline-offset-4 hover:underline">
        Workspaces
      </button>
      <iconify-icon icon="lucide:chevron-right" class="h-4 w-4" />
      <span class="text-foreground font-medium">{{ workspace?.name || 'Loading...' }}</span>
    </div>

    <!-- Header -->
    <div v-if="workspace" class="flex flex-col md:flex-row md:items-center justify-between gap-4 bg-gradient-to-r from-amber-50/80 via-white/60 to-orange-50/80 dark:from-amber-950/30 dark:via-black/20 dark:to-orange-950/20 p-6 rounded-3xl border border-amber-200/40 dark:border-amber-800/30 backdrop-blur-md shadow-sm">
      <div class="flex items-center gap-4">
        <div class="h-14 w-14 rounded-2xl bg-gradient-to-br from-amber-500 to-orange-500 flex items-center justify-center text-white shadow-lg shadow-amber-500/25 animate-[pulse_3s_ease-in-out_infinite]">
           <iconify-icon icon="lucide:book-open" class="h-7 w-7" />
        </div>
        <div>
          <h1 class="text-2xl font-bold tracking-tight">{{ workspace.name }}</h1>
          <div class="flex items-center gap-3 mt-1">
            <span class="text-xs font-mono text-muted-foreground bg-slate-100 dark:bg-zinc-800 px-2 py-0.5 rounded-md">{{ workspace.schema_name }}</span>
            <span class="text-xs text-muted-foreground">•</span>
            <span class="text-xs font-semibold text-amber-600 dark:text-amber-400">{{ workspace.table_count }} Tables</span>
          </div>
        </div>
      </div>
      <div class="flex items-center gap-3">
        <Button variant="outline" @click="handleProfileWorkspace" :disabled="isProfiling" class="rounded-xl border-amber-200 hover:bg-amber-50 dark:border-amber-900/50 transition-all hover:shadow-md">
           <iconify-icon v-if="isProfiling" icon="lucide:loader-2" class="mr-2 h-4 w-4 animate-spin" />
           <iconify-icon v-else icon="lucide:sparkles" class="mr-2 h-4 w-4 text-amber-500" />
           Auto-Profile
        </Button>
        <Button variant="outline" @click="router.push(`/app/workspaces/${workspaceId}/report`)" class="rounded-xl">
           <iconify-icon icon="lucide:file-text" class="mr-2 h-4 w-4 text-purple-500" />
           Reports
        </Button>
        <Button @click="router.push(`/app/workspaces/${workspaceId}/chat`)" class="rounded-xl bg-blue-600 hover:bg-blue-700 shadow-md shadow-blue-500/20 transition-all hover:shadow-lg">
           <iconify-icon icon="lucide:message-square" class="mr-2 h-4 w-4" />
           Chat with Data
        </Button>
      </div>
    </div>

    <!-- Main Content Tabs -->
    <div v-if="isLoading" class="space-y-4">
      <Card v-for="i in 3" :key="i" class="animate-pulse h-24 shadow-sm" />
    </div>

    <Tabs v-else :defaultValue="(route.query.tab as string) || 'catalog'" class="w-full">
      <TabsList class="grid w-[600px] grid-cols-3 mb-6">
        <TabsTrigger value="catalog">Physical Tables</TabsTrigger>
        <TabsTrigger value="semantic">Semantic Layer</TabsTrigger>
        <TabsTrigger value="relationships">Relationships</TabsTrigger>
      </TabsList>

      <!-- PHYSICAL TABLES TAB -->
      <TabsContent value="catalog" class="space-y-4">
        <div v-for="(table, tidx) in workspace?.tables" :key="table.table_name" class="border rounded-2xl bg-card/60 backdrop-blur-sm overflow-hidden transition-all duration-300 shadow-sm hover:shadow-md">
          <!-- Table Header / Trigger -->
          <div 
            @click="toggleTable(table.table_name)" 
            class="flex items-center justify-between p-4 cursor-pointer hover:bg-muted/30 transition-all duration-200 group"
          >
            <div class="flex items-center gap-3">
              <div :class="['h-10 w-10 rounded-xl flex items-center justify-center transition-all duration-300', expandedTables[table.table_name] ? 'bg-amber-500 text-white shadow-lg shadow-amber-500/25 scale-105' : 'bg-muted text-muted-foreground group-hover:bg-amber-100 dark:group-hover:bg-amber-500/20 group-hover:text-amber-600']">
                <iconify-icon icon="lucide:table" class="h-5 w-5" />
              </div>
              <div>
                <div class="font-bold text-base">{{ table.table_name }}</div>
                <div class="flex items-center gap-2 mt-0.5">
                  <span class="text-[11px] text-muted-foreground">{{ table.row_count.toLocaleString() }} rows</span>
                  <span class="text-[10px] text-muted-foreground">•</span>
                  <span class="text-[11px] text-muted-foreground">{{ table.columns?.length || 0 }} columns</span>
                </div>
              </div>
            </div>
            <div class="flex items-center gap-4">
              <div class="hidden md:block max-w-md text-sm text-muted-foreground truncate italic">
                {{ table.description || 'No description. Run profiling.' }}
              </div>
              <iconify-icon 
                icon="lucide:chevron-down" 
                class="h-5 w-5 transition-transform duration-300 ease-out" 
                :class="expandedTables[table.table_name] ? 'rotate-180 text-amber-500' : 'text-muted-foreground'" 
              />
            </div>
          </div>

          <!-- Expanded Content -->
          <div v-if="expandedTables[table.table_name]" class="p-6 border-t border-border/40 space-y-6">
            <!-- Table Description Section -->
            <div class="space-y-2">
              <div class="flex items-center justify-between">
                <h4 class="text-sm font-semibold uppercase tracking-wider text-muted-foreground">Business Description</h4>
                <Button variant="ghost" size="sm" v-if="editingId !== table.table_name" @click.stop="startEdit(table.table_name, table.description || '')">
                   <iconify-icon icon="lucide:edit-2" class="h-3 w-3 mr-1" /> Edit
                </Button>
              </div>
              <div v-if="editingId === table.table_name" class="flex gap-2">
                 <Input v-model="editValue" class="flex-1" />
                 <Button size="sm" @click="saveTableDescription(table.table_name)">Save</Button>
                 <Button size="sm" variant="ghost" @click="editingId = null">Cancel</Button>
              </div>
              <p v-else class="text-sm border p-3 rounded-lg bg-muted/30">
                {{ table.description || 'Click edit or run profiling to add a description for the AI agent.' }}
              </p>
            </div>

            <!-- Columns Table -->
            <div class="space-y-2">
              <h4 class="text-sm font-semibold uppercase tracking-wider text-muted-foreground">Columns</h4>
              <div class="rounded-xl border overflow-hidden">
                <Table>
                  <TableHeader class="bg-muted/50">
                    <TableRow>
                      <TableHead class="w-[200px]">Column Name</TableHead>
                      <TableHead class="w-[120px]">Type</TableHead>
                      <TableHead>Business Meaning</TableHead>
                      <TableHead class="w-[250px]">Stats/Samples</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    <TableRow v-for="col in table.columns" :key="col.column_id">
                      <TableCell class="font-mono text-sm underline underline-offset-4 decoration-border">{{ col.column_name }}</TableCell>
                      <TableCell>
                        <Badge variant="outline" class="font-mono text-[10px]">{{ col.data_type }}</Badge>
                      </TableCell>
                      <TableCell>
                         <div v-if="editingId === col.column_id" class="flex gap-2">
                           <Input v-model="editValue" class="h-8 text-sm" />
                           <Button size="icon" class="h-8 w-8" @click="saveColumnDescription(col.column_id)">
                              <iconify-icon icon="lucide:check" class="h-4 w-4" />
                           </Button>
                           <Button size="icon" variant="ghost" class="h-8 w-8" @click="editingId = null">
                              <iconify-icon icon="lucide:x" class="h-4 w-4" />
                           </Button>
                         </div>
                         <div v-else class="group flex items-center justify-between gap-2 max-w-xs text-sm">
                           <span class="truncate">{{ col.description || '-' }}</span>
                           <button class="opacity-0 group-hover:opacity-100 transition-opacity" @click.stop="startEdit(col.column_id, col.description || '')">
                             <iconify-icon icon="lucide:edit-3" class="h-3 w-3 text-muted-foreground" />
                           </button>
                         </div>
                      </TableCell>
                      <TableCell>
                         <div class="flex flex-wrap gap-1">
                            <Badge v-for="s in (col.sample_values || []).slice(0, 3)" :key="s" variant="secondary" class="text-[10px] font-normal px-1.5 py-0">
                              {{ s }}
                            </Badge>
                            <span v-if="(col.sample_values || []).length > 3" class="text-[10px] text-muted-foreground">...</span>
                         </div>
                      </TableCell>
                    </TableRow>
                  </TableBody>
                </Table>
              </div>
            </div>
          </div>
        </div>
      </TabsContent>

      <!-- SEMANTIC LAYER TAB -->
      <TabsContent value="semantic" class="space-y-6">
        
        <!-- Metrics -->
        <Card class="border border-border/50 shadow-sm">
          <CardHeader>
            <CardTitle class="flex items-center gap-2"><iconify-icon icon="lucide:calculator" class="text-emerald-500" /> Derived Metrics</CardTitle>
            <CardDescription>Define reusable business formulas that the AI can use (e.g. Net Revenue = gross - tax).</CardDescription>
          </CardHeader>
          <CardContent>
            <div class="grid grid-cols-1 md:grid-cols-5 gap-4 mb-6">
              <Input v-model="metricForm.name" placeholder="Name (e.g. Net Revenue)" />
              <Input v-model="metricForm.formula" placeholder="Formula (e.g. SUM(gross) - SUM(tax))" />
              <Input v-model="metricForm.description" placeholder="Description (Optional)" />
              <Input
                v-model="metricRelatedTablesInput"
                placeholder="Related tables (comma-separated, e.g. sales, costs)"
              />
              <Button @click="createMetric">Add Metric</Button>
            </div>
            
            <div v-if="semanticLayer?.metrics.length === 0" class="text-sm text-muted-foreground py-4 text-center border rounded-lg border-dashed">
              No metrics defined.
            </div>
            <Table v-else>
              <TableHeader>
                <TableRow>
                  <TableHead>Metric Name</TableHead>
                  <TableHead>Formula</TableHead>
                  <TableHead>Related Tables</TableHead>
                  <TableHead>Description</TableHead>
                  <TableHead class="w-[80px]"></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                <TableRow v-for="m in semanticLayer?.metrics" :key="m.metric_id">
                  <TableCell class="font-medium">{{ m.name }}</TableCell>
                  <TableCell class="font-mono text-xs">{{ m.formula }}</TableCell>
                  <TableCell class="text-xs">
                    {{ (m.related_tables && m.related_tables.length) ? m.related_tables.join(', ') : '-' }}
                  </TableCell>
                  <TableCell class="text-xs text-muted-foreground">{{ m.description }}</TableCell>
                  <TableCell>
                    <Button variant="ghost" size="icon" @click="deleteMetric(m.metric_id)" class="text-red-500 hover:bg-red-50 h-6 w-6">
                      <iconify-icon icon="lucide:trash" class="h-3 w-3" />
                    </Button>
                  </TableCell>
                </TableRow>
              </TableBody>
            </Table>
          </CardContent>
        </Card>

        <!-- Dimensions -->
        <Card class="border border-border/50 shadow-sm">
          <CardHeader>
            <CardTitle class="flex items-center gap-2"><iconify-icon icon="lucide:tag" class="text-blue-500" /> Important Dimensions</CardTitle>
            <CardDescription>Highlight specific columns as standard ways to slice data (e.g. Time = orders.created_at).</CardDescription>
          </CardHeader>
          <CardContent>
            <div class="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
              <Input v-model="dimensionForm.name" placeholder="Dimension Name (e.g. Date)" />
              <Input v-model="dimensionForm.table_name" placeholder="Table Name" />
              <Input v-model="dimensionForm.column_name" placeholder="Column Name" />
              <Button @click="createDimension">Add Dimension</Button>
            </div>
            
            <div v-if="semanticLayer?.dimensions.length === 0" class="text-sm text-muted-foreground py-4 text-center border rounded-lg border-dashed">
              No dimensions defined.
            </div>
            <Table v-else>
              <TableHeader>
                <TableRow>
                  <TableHead>Dim Name</TableHead>
                  <TableHead>Table.Column</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead class="w-[80px]"></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                <TableRow v-for="d in semanticLayer?.dimensions" :key="d.dimension_id">
                  <TableCell class="font-medium">{{ d.name }}</TableCell>
                  <TableCell class="font-mono text-xs">{{ d.table_name }}.{{ d.column_name }}</TableCell>
                  <TableCell class="text-xs text-muted-foreground capitalize">{{ d.dim_type }}</TableCell>
                  <TableCell>
                    <Button variant="ghost" size="icon" @click="deleteDimension(d.dimension_id)" class="text-red-500 hover:bg-red-50 h-6 w-6">
                      <iconify-icon icon="lucide:trash" class="h-3 w-3" />
                    </Button>
                  </TableCell>
                </TableRow>
              </TableBody>
            </Table>
          </CardContent>
        </Card>

        <!-- Synonyms -->
        <Card class="border border-border/50 shadow-sm">
          <CardHeader>
            <CardTitle class="flex items-center gap-2"><iconify-icon icon="lucide:link" class="text-violet-500" /> Term Synonyms</CardTitle>
            <CardDescription>Teach the AI alternative business terms (e.g. Sales -> revenue_usd).</CardDescription>
          </CardHeader>
          <CardContent>
            <div class="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
              <Input v-model="synonymForm.keyword" placeholder="When user says... (e.g. Sales)" />
              <Input v-model="synonymForm.mapped_to" placeholder="It means... (e.g. revenue_usd)" />
              <div class="flex items-center gap-2">
                 <span class="text-sm text-muted-foreground">Type: </span>
                 <Badge variant="outline">Column</Badge>
              </div>
              <Button @click="createSynonym">Add Synonym</Button>
            </div>
            
            <div v-if="semanticLayer?.synonyms.length === 0" class="text-sm text-muted-foreground py-4 text-center border rounded-lg border-dashed">
              No synonyms defined.
            </div>
            <Table v-else>
              <TableHeader>
                <TableRow>
                  <TableHead>Keyword</TableHead>
                  <TableHead>Mapped To</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead class="w-[80px]"></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                <TableRow v-for="s in semanticLayer?.synonyms" :key="s.synonym_id">
                  <TableCell class="font-medium">"{{ s.keyword }}"</TableCell>
                  <TableCell class="font-mono text-xs">{{ s.mapped_to }}</TableCell>
                  <TableCell class="text-xs text-muted-foreground capitalize">{{ s.mapped_type }}</TableCell>
                  <TableCell>
                    <Button variant="ghost" size="icon" @click="deleteSynonym(s.synonym_id)" class="text-red-500 hover:bg-red-50 h-6 w-6">
                      <iconify-icon icon="lucide:trash" class="h-3 w-3" />
                    </Button>
                  </TableCell>
                </TableRow>
              </TableBody>
            </Table>
          </CardContent>
        </Card>

      </TabsContent>

      <!-- RELATIONSHIPS TAB -->
      <TabsContent value="relationships" class="space-y-6">
        <Card class="border border-border/50 shadow-sm">
          <CardHeader>
            <CardTitle class="flex items-center gap-2"><iconify-icon icon="lucide:network" class="text-emerald-500" /> Table Relationships</CardTitle>
            <CardDescription>Define primary and foreign keys to enable multi-table, relational dashboard generation.</CardDescription>
          </CardHeader>
          <CardContent>
            <div class="grid grid-cols-1 md:grid-cols-5 gap-4 mb-6">
              <Input v-model="relForm.source_table" placeholder="Source Table (e.g. orders)" />
              <Input v-model="relForm.source_column" placeholder="Source Column (e.g. customer_id)" />
              <Input v-model="relForm.target_table" placeholder="Target Table (e.g. customers)" />
              <Input v-model="relForm.target_column" placeholder="Target Column (e.g. id)" />
              <Button @click="createRelationship">Add Relation</Button>
            </div>
            
            <div v-if="relationships.length === 0" class="text-sm text-muted-foreground py-4 text-center border rounded-lg border-dashed">
              No relationships defined. The LLM Analyst will try to infer them automatically.
            </div>
            <Table v-else>
              <TableHeader>
                <TableRow>
                  <TableHead>Source</TableHead>
                  <TableHead>Target</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Inferred By</TableHead>
                  <TableHead class="w-[80px]"></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                <TableRow v-for="r in relationships" :key="r.relationship_id">
                  <TableCell class="font-mono text-xs">{{ r.source_table }}.{{ r.source_column }}</TableCell>
                  <TableCell class="font-mono text-xs">{{ r.target_table }}.{{ r.target_column }}</TableCell>
                  <TableCell class="text-xs text-muted-foreground capitalize">{{ r.relationship_type }}</TableCell>
                  <TableCell>
                    <Badge variant="outline" :class="r.inferred_by === 'llm' ? 'bg-indigo-50 text-indigo-600' : 'bg-emerald-50 text-emerald-600'">
                      {{ r.inferred_by }}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <Button variant="ghost" size="icon" @click="deleteRelationship(r.relationship_id)" class="text-red-500 hover:bg-red-50 h-6 w-6">
                      <iconify-icon icon="lucide:trash" class="h-3 w-3" />
                    </Button>
                  </TableCell>
                </TableRow>
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </TabsContent>
    </Tabs>
  </div>
</template>
