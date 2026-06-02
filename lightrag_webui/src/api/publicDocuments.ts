import axios from 'axios'
import { backendBaseUrl } from '@/lib/constants'

const api = axios.create({ baseURL: backendBaseUrl, headers: { 'Content-Type': 'application/json' } })
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('LIGHTRAG-API-TOKEN')
  if (token) config.headers['Authorization'] = `Bearer ${token}`
  return config
})

export type PublicWorkspace = {
  name: string
  title: string
  description: string
  accent_color: string
}

export type PublicDocument = {
  id: string
  file_path: string
  status: string
  chunks_count: number | null
  created_at: string
  content_summary: string
}

export const listPublicWorkspaces = (): Promise<PublicWorkspace[]> =>
  api.get<PublicWorkspace[]>('/public-chat/workspaces').then((r) => r.data)

export const listPublicDocuments = (workspace: string): Promise<PublicDocument[]> =>
  api.get<PublicDocument[]>(`/public-chat/${encodeURIComponent(workspace)}/documents`).then((r) => r.data)

export type GraphNode = { id: string; labels: string[]; properties: Record<string, unknown> }
export type GraphEdge = { id: string; source: string; target: string; properties: Record<string, unknown> }
export type GraphData = { nodes: GraphNode[]; edges: GraphEdge[] }

export const fetchPublicGraph = (workspace: string, maxNodes = 300): Promise<GraphData> =>
  api.get<GraphData>(`/public-chat/${encodeURIComponent(workspace)}/graph`, { params: { max_nodes: maxNodes } }).then((r) => r.data)

export const uploadDocument = (workspace: string, file: File): Promise<void> => {
  const form = new FormData()
  form.append('file', file)
  return api.post('/documents/upload', form, {
    headers: {
      'Content-Type': 'multipart/form-data',
      'LIGHTRAG-WORKSPACE': workspace,
    },
  }).then(() => undefined)
}
