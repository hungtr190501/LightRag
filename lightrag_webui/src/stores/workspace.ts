import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'
import { createSelectors } from '@/lib/utils'
import type { WorkspaceInfo } from '@/api/workspace'
import * as workspaceApi from '@/api/workspace'

// Simple localStorage key used by axios/fetch interceptors (avoids Zustand import in api layer)
export const WORKSPACE_HEADER_KEY = 'LIGHTRAG-ACTIVE-WORKSPACE'

function syncWorkspaceToStorage(name: string) {
  if (name) {
    localStorage.setItem(WORKSPACE_HEADER_KEY, name)
  } else {
    localStorage.removeItem(WORKSPACE_HEADER_KEY)
  }
}

interface WorkspaceState {
  workspaces: WorkspaceInfo[]
  currentWorkspace: string
  setCurrentWorkspace: (name: string) => void
  fetchWorkspaces: () => Promise<void>
  createWorkspace: (data: Omit<WorkspaceInfo, 'created_at'>) => Promise<void>
  updateWorkspace: (name: string, data: Partial<Pick<WorkspaceInfo, 'description' | 'color'>>) => Promise<void>
  deleteWorkspace: (name: string) => Promise<void>
}

export const useWorkspaceStore = createSelectors(
  create<WorkspaceState>()(
    persist(
      (set, get) => ({
        workspaces: [],
        currentWorkspace: '',

        setCurrentWorkspace: (name) => {
          set({ currentWorkspace: name })
          syncWorkspaceToStorage(name)
        },

        fetchWorkspaces: async () => {
          try {
            const workspaces = await workspaceApi.listWorkspaces()
            set({ workspaces })
          } catch (err) {
            console.error('Failed to fetch workspaces:', err)
          }
        },

        createWorkspace: async (data) => {
          await workspaceApi.createWorkspace(data)
          await get().fetchWorkspaces()
        },

        updateWorkspace: async (name, data) => {
          await workspaceApi.updateWorkspace(name, data)
          await get().fetchWorkspaces()
        },

        deleteWorkspace: async (name) => {
          await workspaceApi.deleteWorkspace(name)
          const { currentWorkspace } = get()
          await get().fetchWorkspaces()
          if (currentWorkspace === name) {
            set({ currentWorkspace: '' })
            syncWorkspaceToStorage('')
          }
        },
      }),
      {
        name: 'lightrag-workspace',
        storage: createJSONStorage(() => localStorage),
        partialize: (state) => ({ currentWorkspace: state.currentWorkspace }),
        // On page reload: sync the persisted workspace to the simple key
        onRehydrateStorage: () => (state) => {
          if (state) syncWorkspaceToStorage(state.currentWorkspace ?? '')
        },
      }
    )
  )
)
