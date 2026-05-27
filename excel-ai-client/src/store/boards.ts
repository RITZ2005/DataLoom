import { defineStore } from 'pinia'
import { ref } from 'vue'
import excelFileAPI, { type BoardInfo } from '@/services/excelApi'

export const useBoards = defineStore('boards', () => {
  const boards = ref<BoardInfo[]>([])
  const isLoading = ref(false)
  const activeWidgetId = ref<string | null>(null)
  const screens = ref<Array<{ id: string; name: string }>>([
    { id: 'screen-1', name: 'Dashboard' },
  ])
  const activeScreenId = ref('screen-1')

  async function fetchBoards() {
    isLoading.value = true
    try {
      boards.value = await excelFileAPI.listBoards()
    } catch (e) {
      console.error('Failed to fetch boards:', e)
    } finally {
      isLoading.value = false
    }
  }

  async function createBoard(name: string) {
    const board = await excelFileAPI.createBoard(name)
    boards.value.unshift(board)
    return board
  }

  async function deleteBoard(boardId: string) {
    await excelFileAPI.deleteBoard(boardId)
    boards.value = boards.value.filter(b => b.board_id !== boardId)
  }

  function setActiveWidget(widgetId: string | null) {
    activeWidgetId.value = widgetId
  }

  function addScreen(name?: string) {
    const id = `screen-${Date.now()}`
    screens.value.push({ id, name: name || `Screen ${screens.value.length + 1}` })
    activeScreenId.value = id
  }

  function setActiveScreen(screenId: string) {
    activeScreenId.value = screenId
  }

  return {
    boards,
    isLoading,
    activeWidgetId,
    screens,
    activeScreenId,
    fetchBoards,
    createBoard,
    deleteBoard,
    setActiveWidget,
    addScreen,
    setActiveScreen,
  }
})
