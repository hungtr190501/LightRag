import axios from 'axios'
import { backendBaseUrl } from '@/lib/constants'
import { useSettingsStore } from '@/stores/settings'

const api = axios.create({
  baseURL: backendBaseUrl,
  headers: { 'Content-Type': 'application/json' }
})

api.interceptors.request.use((config) => {
  const apiKey = useSettingsStore.getState().apiKey
  const token = localStorage.getItem('LIGHTRAG-API-TOKEN')
  if (token) config.headers['Authorization'] = `Bearer ${token}`
  if (apiKey) config.headers['X-API-Key'] = apiKey
  return config
})

export type WorkspaceInfo = {
  name: string
  description?: string
  color?: string
  created_at?: string
}

export const listWorkspaces = (): Promise<WorkspaceInfo[]> =>
  api.get<WorkspaceInfo[]>('/workspaces').then((r) => r.data)

export const createWorkspace = (data: Omit<WorkspaceInfo, 'created_at'>): Promise<WorkspaceInfo> =>
  api.post<WorkspaceInfo>('/workspaces', data).then((r) => r.data)

export const updateWorkspace = (
  name: string,
  data: Partial<Pick<WorkspaceInfo, 'description' | 'color'>>
): Promise<WorkspaceInfo> =>
  api.patch<WorkspaceInfo>(`/workspaces/${encodeURIComponent(name)}`, data).then((r) => r.data)

export const deleteWorkspace = (name: string): Promise<{ status: string; name: string }> =>
  api.delete(`/workspaces/${encodeURIComponent(name)}`).then((r) => r.data)

export type PublicChatConfig = {
  title: string
  description: string
  mode: 'local' | 'global' | 'hybrid' | 'mix' | 'naive'
  top_k: number
  suggested_questions: string[]
  accent_color: string
}

export const getPublicChatConfig = (name: string): Promise<PublicChatConfig> =>
  api.get<PublicChatConfig>(`/workspaces/${encodeURIComponent(name)}/public-chat-config`).then((r) => r.data)

export const updatePublicChatConfig = (name: string, config: PublicChatConfig): Promise<PublicChatConfig> =>
  api.put<PublicChatConfig>(`/workspaces/${encodeURIComponent(name)}/public-chat-config`, config).then((r) => r.data)
