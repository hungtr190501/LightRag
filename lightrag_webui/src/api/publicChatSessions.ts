/**
 * Public Chat Session API — /public-chat/{workspace}/sessions
 * GET/POST/PATCH endpoints are unauthenticated (public users).
 * DELETE requires auth (admin).
 */
import axios from 'axios'
import { backendBaseUrl } from '@/lib/constants'
import { useSettingsStore } from '@/stores/settings'

const api = axios.create({ baseURL: backendBaseUrl, headers: { 'Content-Type': 'application/json' } })
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('LIGHTRAG-API-TOKEN')
  if (token) config.headers['Authorization'] = `Bearer ${token}`
  const apiKey = useSettingsStore.getState().apiKey
  if (apiKey) config.headers['X-API-Key'] = apiKey
  return config
})

// ── Types ─────────────────────────────────────────────────────────────────────

export type MessageRole = 'user' | 'assistant'
export type Feedback = 'like' | 'dislike' | null

export type SessionMessage = {
  id: string
  role: MessageRole
  content: string
  timestamp: string
  feedback: Feedback
  references?: Record<string, unknown>[]
}

export type SessionSummary = {
  id: string
  workspace: string
  title: string
  created_at: string
  updated_at: string
  message_count: number
  like_count: number
  dislike_count: number
}

export type SessionDetail = SessionSummary & {
  messages: SessionMessage[]
}

// ── API ───────────────────────────────────────────────────────────────────────

const base = (ws: string) => `/public-chat/${encodeURIComponent(ws)}/sessions`

export const listSessions = (ws: string): Promise<SessionSummary[]> =>
  api.get<SessionSummary[]>(base(ws)).then((r) => r.data)

export const createSession = (ws: string): Promise<{ id: string; title: string; created_at: string }> =>
  api.post(base(ws)).then((r) => r.data)

export const getSession = (ws: string, sid: string): Promise<SessionDetail> =>
  api.get<SessionDetail>(`${base(ws)}/${encodeURIComponent(sid)}`).then((r) => r.data)

export const deleteSession = (ws: string, sid: string): Promise<void> =>
  api.delete(`${base(ws)}/${encodeURIComponent(sid)}`).then(() => undefined)

export const addMessage = (
  ws: string,
  sid: string,
  msg: { role: MessageRole; content: string; references?: Record<string, unknown>[] }
): Promise<SessionMessage> =>
  api.post<SessionMessage>(`${base(ws)}/${encodeURIComponent(sid)}/messages`, msg).then((r) => r.data)

export const setFeedback = (
  ws: string,
  sid: string,
  mid: string,
  feedback: Feedback
): Promise<SessionMessage> =>
  api
    .patch<SessionMessage>(
      `${base(ws)}/${encodeURIComponent(sid)}/messages/${encodeURIComponent(mid)}/feedback`,
      { feedback }
    )
    .then((r) => r.data)
