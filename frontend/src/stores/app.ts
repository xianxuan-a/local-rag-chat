import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useAppStore = defineStore('app', () => {
  const sidebarCollapsed = ref(false)
  const mobileNavigationOpen = ref(false)

  function toggleSidebar(): void {
    sidebarCollapsed.value = !sidebarCollapsed.value
  }

  function setMobileNavigation(open: boolean): void {
    mobileNavigationOpen.value = open
  }

  return {
    sidebarCollapsed,
    mobileNavigationOpen,
    toggleSidebar,
    setMobileNavigation,
  }
})
