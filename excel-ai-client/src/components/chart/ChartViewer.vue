<template>
  <div class="chart-container">
    <!-- Loading State -->
    <div v-if="isLoading" class="chart-wrapper">
      <div class="skeleton-loader">
        <div class="skeleton-title"></div>
        <div class="skeleton-subtitle"></div>
        <div class="skeleton-chart"></div>
      </div>
    </div>

    <!-- Chart Content -->
    <div v-else-if="chartData && hasData" class="chart-wrapper" ref="chartContainer">
      <!-- Smart Title with Insights -->
      <div class="chart-header">
        <div class="chart-title-section">
          <h3 class="chart-title">{{ enhancedTitle }}</h3>
          <p v-if="chartInsight" class="chart-insight">{{ chartInsight }}</p>
          <p class="chart-meta">{{ chartMeta }}</p>
        </div>
      </div>
      
      <!-- Bar Chart -->
      <div v-if="chartData.chart_type === 'bar'" v-show="barChartData.labels.length > 0" class="chart-canvas-wrapper">
        <Bar :data="barChartData" :options="chartOptions" />
      </div>
      
      <!-- Pie Chart -->
      <div v-else-if="chartData.chart_type === 'pie'" v-show="pieChartData.labels.length > 0" class="chart-canvas-wrapper">
        <Pie :data="pieChartData" :options="chartOptions" />
      </div>
      
      <!-- Doughnut Chart -->
      <div v-else-if="chartData.chart_type === 'doughnut'" v-show="doughnutChartData.labels.length > 0" class="chart-canvas-wrapper">
        <Doughnut :data="doughnutChartData" :options="doughnutChartOptions" />
      </div>
      
      <!-- Polar Area Chart -->
      <div v-else-if="chartData.chart_type === 'polarArea'" v-show="polarChartData.labels.length > 0" class="chart-canvas-wrapper">
        <PolarArea :data="polarChartData" :options="polarChartOptions" />
      </div>
      
      <!-- Line Chart -->
      <div v-else-if="chartData.chart_type === 'line'" v-show="lineChartData.labels.length > 0" class="chart-canvas-wrapper">
        <Line :data="lineChartData" :options="chartOptions" />
      </div>
      
      <!-- Area Chart -->
      <div v-else-if="chartData.chart_type === 'area'" v-show="areaChartData.labels.length > 0" class="chart-canvas-wrapper">
        <Line :data="areaChartData" :options="areaChartOptions" />
      </div>
      
      <!-- Scatter Chart -->
      <div v-else-if="chartData.chart_type === 'scatter'" v-show="scatterChartData.datasets.length > 0" class="chart-canvas-wrapper">
        <Scatter :data="scatterChartData" :options="scatterChartOptions" />
      </div>
      
      <!-- Fallback -->
      <div v-else class="text-muted-foreground">
        <p>Unable to render chart type: {{ chartData.chart_type }}</p>
        <pre class="text-xs">{{ JSON.stringify(chartData, null, 2) }}</pre>
      </div>
    </div>
    
    <!-- Empty State -->
    <div v-else class="empty-state">
      <div class="empty-state-icon">📊</div>
      <h3 class="empty-state-title">No Chart Data Available</h3>
      <p class="empty-state-description">
        Try asking for a visualization of your data
      </p>
      <div class="empty-state-suggestions">
        <p class="suggestions-title">💡 Try these examples:</p>
        <ul class="suggestions-list">
          <li>"Show bar chart of sales by region"</li>
          <li>"Create pie chart of department distribution"</li>
          <li>"Plot scatter chart of age vs salary"</li>
          <li>"Display line chart showing trends over time"</li>
        </ul>
      </div>
    </div>
  </div>
</template>


<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Bar, Pie, Line, Scatter, Doughnut, PolarArea } from 'vue-chartjs'
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  RadialLinearScale,
  PointElement,
  LineElement,
  BarElement,
  ArcElement,
  Title,
  Tooltip,
  Legend
} from 'chart.js'

ChartJS.register(
  CategoryScale,
  LinearScale,
  RadialLinearScale,
  PointElement,
  LineElement,
  BarElement,
  ArcElement,
  Title,
  Tooltip,
  Legend
)

interface ChartDataInterface {
  chart_type: 'bar' | 'pie' | 'doughnut' | 'polarArea' | 'line' | 'area' | 'scatter'
  title?: string
  data: Record<string, number> | Array<{x: number; y: number}>
  insights?: string  // Backend-generated comprehensive insights
}

interface Props {
  chartData?: ChartDataInterface
}

const props = withDefaults(defineProps<Props>(), {
  chartData: undefined
})

const chartContainer = ref<HTMLElement | null>(null)
const isLoading = ref(false)

// Check if chart has valid data
const hasData = computed(() => {
  if (!props.chartData) return false
  if (Array.isArray(props.chartData.data)) {
    return props.chartData.data.length > 0
  }
  return Object.keys(props.chartData.data).length > 0
})

// Generate enhanced title with context
const enhancedTitle = computed(() => {
  if (!props.chartData?.title) return 'Chart'
  return props.chartData.title
})

// Display backend-generated insights (comprehensive analysis)
const chartInsight = computed(() => {
  // Use backend insights if available
  if (props.chartData?.insights) {
    return props.chartData.insights
  }
  
  // Fallback to basic client-side insight for backwards compatibility
  if (!props.chartData || Array.isArray(props.chartData.data)) return null
  
  const data = props.chartData.data as Record<string, number>
  const entries = Object.entries(data)
  if (entries.length === 0) return null
  
  // Find highest value
  const sorted = entries.sort(([, a], [, b]) => b - a)
  const [topKey, topValue] = sorted[0]
  const total = entries.reduce((sum, [, val]) => sum + val, 0)
  const percentage = ((topValue / total) * 100).toFixed(1)
  
  return `🏆 Top: ${topKey} (${percentage}%)`
})

// Generate metadata (e.g., "Showing 12 categories")
const chartMeta = computed(() => {
  if (!props.chartData) return ''
  
  if (Array.isArray(props.chartData.data)) {
    const count = props.chartData.data.length
    return `📊 ${count} data point${count !== 1 ? 's' : ''}`
  }
  
  const count = Object.keys(props.chartData.data).length
  return `📊 Showing ${count} categor${count !== 1 ? 'ies' : 'y'}`
})


function downloadPNG() {
  try {
    const el = chartContainer.value
    if (!el) return
    const canvas = el.querySelector('canvas') as HTMLCanvasElement | null
    if (!canvas) return
    const dataUrl = canvas.toDataURL('image/png')
    const link = document.createElement('a')
    const filename = (props.chartData?.title || 'chart').replace(/[^a-z0-9-_]/gi, '_') + '.png'
    link.href = dataUrl
    link.download = filename
    document.body.appendChild(link)
    link.click()
    link.remove()
  } catch (e) {
    // silent
     
    console.error('Download PNG failed', e)
  }
}

function downloadCSV() {
  try {
    if (!props.chartData) return
    const rows: string[] = []
    rows.push('label,value')
    for (const [k, v] of Object.entries(props.chartData.data)) {
      // Escape quotes
      const label = String(k).replace(/"/g, '""')
      rows.push(`"${label}",${v}`)
    }
    const csv = rows.join('\n')
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    const filename = (props.chartData.title || 'chart_data').replace(/[^a-z0-9-_]/gi, '_') + '.csv'
    link.href = url
    link.setAttribute('download', filename)
    document.body.appendChild(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(url)
  } catch (e) {
     
    console.error('Download CSV failed', e)
  }
}

const chartOptions = {
  responsive: true,
  maintainAspectRatio: false,
  plugins: {
    legend: {
      display: true,
      position: 'top' as const
    },
    title: {
      display: false
    }
  }
}

const barChartData = computed(() => {
  if (!props.chartData) return { labels: [], datasets: [] }
  const labels = Object.keys(props.chartData.data)
  const values = Object.values(props.chartData.data)
  return {
    labels,
    datasets: [
      {
        label: props.chartData.title || 'Data',
        data: values,
        backgroundColor: 'rgba(59, 130, 246, 0.5)',
        borderColor: 'rgb(59, 130, 246)',
        borderWidth: 1
      }
    ]
  }
})

const pieChartData = computed(() => {
  if (!props.chartData) return { labels: [], datasets: [] }
  const labels = Object.keys(props.chartData.data)
  const values = Object.values(props.chartData.data)
  const colors = [
    'rgba(59, 130, 246, 0.7)',
    'rgba(16, 185, 129, 0.7)',
    'rgba(245, 158, 11, 0.7)',
    'rgba(239, 68, 68, 0.7)',
    'rgba(168, 85, 247, 0.7)',
    'rgba(236, 72, 153, 0.7)',
    'rgba(14, 165, 233, 0.7)',
    'rgba(34, 197, 94, 0.7)'
  ]
  return {
    labels,
    datasets: [
      {
        data: values,
        backgroundColor: colors.slice(0, labels.length),
        borderColor: colors.slice(0, labels.length),
        borderWidth: 2
      }
    ]
  }
})

const doughnutChartData = computed(() => {
  if (!props.chartData) return { labels: [], datasets: [] }
  const labels = Object.keys(props.chartData.data)
  const values = Object.values(props.chartData.data)
  const colors = [
    'rgba(59, 130, 246, 0.8)',
    'rgba(16, 185, 129, 0.8)',
    'rgba(245, 158, 11, 0.8)',
    'rgba(239, 68, 68, 0.8)',
    'rgba(168, 85, 247, 0.8)',
    'rgba(236, 72, 153, 0.8)',
    'rgba(14, 165, 233, 0.8)',
    'rgba(34, 197, 94, 0.8)',
    'rgba(229, 231, 235, 0.8)',
    'rgba(107, 114, 128, 0.8)'
  ]
  return {
    labels,
    datasets: [
      {
        data: values,
        backgroundColor: colors.slice(0, labels.length),
        borderColor: '#ffffff',
        borderWidth: 3
      }
    ]
  }
})

const doughnutChartOptions = {
  responsive: true,
  maintainAspectRatio: false,
  plugins: {
    legend: {
      display: true,
      position: 'bottom' as const
    },
    title: {
      display: false
    }
  },
  cutout: '50%'
}

const polarChartData = computed(() => {
  if (!props.chartData) return { labels: [], datasets: [] }
  const labels = Object.keys(props.chartData.data)
  const values = Object.values(props.chartData.data)
  const colors = [
    'rgba(59, 130, 246, 0.6)',
    'rgba(16, 185, 129, 0.6)',
    'rgba(245, 158, 11, 0.6)',
    'rgba(239, 68, 68, 0.6)',
    'rgba(168, 85, 247, 0.6)',
    'rgba(236, 72, 153, 0.6)',
    'rgba(14, 165, 233, 0.6)',
    'rgba(34, 197, 94, 0.6)',
    'rgba(229, 231, 235, 0.6)',
    'rgba(107, 114, 128, 0.6)',
    'rgba(249, 115, 22, 0.6)',
    'rgba(101, 116, 205, 0.6)'
  ]
  return {
    labels,
    datasets: [
      {
        label: props.chartData.title || 'Data',
        data: values,
        backgroundColor: colors.slice(0, labels.length),
        borderColor: colors.slice(0, labels.length).map(c => c.replace('0.6', '1')),
        borderWidth: 2
      }
    ]
  }
})

const polarChartOptions = {
  responsive: true,
  maintainAspectRatio: false,
  plugins: {
    legend: {
      display: true,
      position: 'top' as const
    },
    title: {
      display: false
    }
  },
  scales: {
    r: {
      beginAtZero: true
    }
  }
}

const lineChartData = computed(() => {
  if (!props.chartData) return { labels: [], datasets: [] }
  const labels = Object.keys(props.chartData.data)
  const values = Object.values(props.chartData.data)
  return {
    labels,
    datasets: [
      {
        label: props.chartData.title || 'Data',
        data: values,
        borderColor: 'rgb(59, 130, 246)',
        backgroundColor: 'rgba(59, 130, 246, 0.1)',
        tension: 0.3,
        borderWidth: 2
      }
    ]
  }
})

const areaChartData = computed(() => {
  if (!props.chartData) return { labels: [], datasets: [] }
  const labels = Object.keys(props.chartData.data)
  const values = Object.values(props.chartData.data)
  return {
    labels,
    datasets: [
      {
        label: props.chartData.title || 'Data',
        data: values,
        borderColor: 'rgb(59, 130, 246)',
        backgroundColor: 'rgba(59, 130, 246, 0.3)',
        fill: true,
        tension: 0.3,
        borderWidth: 2
      }
    ]
  }
})

const areaChartOptions = {
  responsive: true,
  maintainAspectRatio: false,
  plugins: {
    legend: {
      display: true,
      position: 'top' as const
    },
    title: {
      display: false
    }
  },
  scales: {
    x: {
      display: true,
      grid: {
        display: true
      }
    },
    y: {
      display: true,
      beginAtZero: true
    }
  }
}

const scatterChartOptions = {
  responsive: true,
  maintainAspectRatio: false,
  plugins: {
    legend: {
      display: true,
      position: 'top' as const
    },
    title: {
      display: false
    }
  },
  scales: {
    x: {
      type: 'linear' as const,
      position: 'bottom' as const,
      title: {
        display: true,
        text: 'X Axis'
      }
    },
    y: {
      title: {
        display: true,
        text: 'Y Axis'
      }
    }
  }
}

const scatterChartData = computed(() => {
  if (!props.chartData) return { datasets: [] }
  
  let points: Array<{x: number; y: number}> = []
  
  // Check if data is already in point format {x, y}
  if (Array.isArray(props.chartData.data)) {
    points = (props.chartData.data as Array<{x: number; y: number}>).filter(
      p => typeof p.x === 'number' && typeof p.y === 'number'
    )
  } else if (typeof props.chartData.data === 'object') {
    // Convert record format {key: value} to points
    // Use index as x, value as y
    const values = Object.entries(props.chartData.data)
    points = values.map(([key, value], index) => ({
      x: index,
      y: value as number
    }))
  }
  
  return {
    datasets: [
      {
        label: props.chartData.title || 'Data Points',
        data: points,
        backgroundColor: 'rgba(59, 130, 246, 0.6)',
        borderColor: 'rgb(59, 130, 246)',
        borderWidth: 2,
        pointRadius: 5,
        pointHoverRadius: 7
      }
    ]
  }
})

// Ensure chartContainer is up-to-date when data changes
watch(() => props.chartData, () => {
  // noop for now; ensures reactivity and that canvas exists
})
</script>

<style scoped>
.chart-container {
  width: 100%;
  padding: 1rem;
}

.chart-wrapper {
  background: hsl(var(--card));
  border-radius: 0.5rem;
  padding: 1.5rem;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
  animation: fadeIn 0.3s ease-in-out;
}

@keyframes fadeIn {
  from {
    opacity: 0;
    transform: translateY(10px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

/* Chart Header Styles */
.chart-header {
  margin-bottom: 1.5rem;
}

.chart-title-section {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.chart-title {
  font-size: 1.25rem;
  font-weight: 600;
  color: hsl(var(--foreground));
  margin: 0;
}

.chart-insight {
  font-size: 0.875rem;
  color: #059669;
  font-weight: 500;
  margin: 0;
  line-height: 1.6;
  padding: 0.75rem;
  background: hsl(var(--muted));
  border-left: 3px solid #10b981;
  border-radius: 0.25rem;
}

.chart-meta {
  font-size: 0.75rem;
  color: hsl(var(--muted-foreground));
  margin: 0;
}

.chart-canvas-wrapper {
  animation: slideUp 0.4s ease-out;
  min-height: 400px;
  height: 100%;
}

@keyframes slideUp {
  from {
    opacity: 0;
    transform: translateY(20px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

/* Loading Skeleton Styles */
.skeleton-loader {
  padding: 1rem 0;
}

.skeleton-title {
  height: 28px;
  width: 60%;
  background: linear-gradient(90deg, hsl(var(--muted)) 25%, hsl(var(--border)) 50%, hsl(var(--muted)) 75%);
  background-size: 200% 100%;
  animation: shimmer 1.5s infinite;
  border-radius: 4px;
  margin-bottom: 0.75rem;
}

.skeleton-subtitle {
  height: 16px;
  width: 40%;
  background: linear-gradient(90deg, hsl(var(--muted)) 25%, hsl(var(--border)) 50%, hsl(var(--muted)) 75%);
  background-size: 200% 100%;
  animation: shimmer 1.5s infinite;
  border-radius: 4px;
  margin-bottom: 1.5rem;
}

.skeleton-chart {
  height: 300px;
  width: 100%;
  background: linear-gradient(90deg, hsl(var(--muted)) 25%, hsl(var(--border)) 50%, hsl(var(--muted)) 75%);
  background-size: 200% 100%;
  animation: shimmer 1.5s infinite;
  border-radius: 8px;
}

@keyframes shimmer {
  0% {
    background-position: -200% 0;
  }
  100% {
    background-position: 200% 0;
  }
}

/* Empty State Styles */
.empty-state {
  text-align: center;
  padding: 3rem 2rem;
  background: hsl(var(--card));
  border-radius: 0.5rem;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
}

.empty-state-icon {
  font-size: 4rem;
  margin-bottom: 1rem;
  opacity: 0.5;
}

.empty-state-title {
  font-size: 1.25rem;
  font-weight: 600;
  color: hsl(var(--foreground));
  margin-bottom: 0.5rem;
}

.empty-state-description {
  color: hsl(var(--muted-foreground));
  margin-bottom: 2rem;
  font-size: 0.875rem;
}

.empty-state-suggestions {
  max-width: 400px;
  margin: 0 auto;
  text-align: left;
  background: hsl(var(--muted));
  border-radius: 0.5rem;
  padding: 1.5rem;
  border: 1px solid hsl(var(--border));
}

.suggestions-title {
  font-weight: 600;
  color: hsl(var(--foreground));
  margin-bottom: 0.75rem;
  font-size: 0.875rem;
}

.suggestions-list {
  list-style: none;
  padding: 0;
  margin: 0;
}

.suggestions-list li {
  padding: 0.5rem 0;
  color: hsl(var(--muted-foreground));
  font-size: 0.875rem;
  border-bottom: 1px solid hsl(var(--border));
}

.suggestions-list li:last-child {
  border-bottom: none;
}

.suggestions-list li::before {
  content: '→ ';
  color: #3b82f6;
  font-weight: bold;
  margin-right: 0.5rem;
}

.suggestions-list li:hover {
  color: #3b82f6;
  cursor: pointer;
  background: hsl(var(--card));
  margin: 0 -0.5rem;
  padding: 0.5rem 0.5rem;
  border-radius: 0.25rem;
  transition: all 0.2s;
}
</style>
