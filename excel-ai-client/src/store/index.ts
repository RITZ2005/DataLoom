import { defineStore } from 'pinia'

// Define the shape of your state
interface MainState {
  isPageBlocked: boolean;
}

export const main = defineStore('main', {
  // Provide the state with its type
  state: (): MainState => ({ 
    isPageBlocked: false 
  }),
  
  // Type your getters
  getters: {
    Boolean(state): boolean {
      return state.isPageBlocked;
    }
  },

  // Type your actions
  actions: {
    MUTATE_PAGE_BLOCKER(payload: boolean) {
      this.isPageBlocked = payload;
    }
  },
});
