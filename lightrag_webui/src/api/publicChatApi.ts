/**
 * Public Chat API — streams from /query/stream without requiring full auth.
 * Auto-fetches a guest token on first call if no token is stored.
 */
import { backendBaseUrl } from '@/lib/constants'
import type { ReferenceItem } from '@/api/lightrag'

export type { ReferenceItem }

async function getOrFetchToken(): Promise<string | null> {
  const stored = localStorage.getItem('LIGHTRAG-API-TOKEN')
  if (stored) return stored
  try {
    const res = await fetch(`${backendBaseUrl}/auth/status`)
    if (!res.ok) return null
    const data = await res.json()
    if (!data.auth_configured && data.access_token) {
      localStorage.setItem('LIGHTRAG-API-TOKEN', data.access_token)
      return data.access_token
    }
  } catch {
    // ignore
  }
  return null
}

export type StreamChunkHandler = (chunk: string) => void
export type StreamReferencesHandler = (refs: ReferenceItem[]) => void
export type StreamDoneHandler = () => void
export type StreamErrorHandler = (err: string) => void

export interface PublicChatRequest {
  query: string
  mode?: string
  top_k?: number
  workspace?: string
  history_messages?: { role: string; content: string }[]
}

export async function streamPublicChat(
  req: PublicChatRequest,
  onChunk: StreamChunkHandler,
  onDone: StreamDoneHandler,
  onError: StreamErrorHandler,
  signal?: AbortSignal,
  onReferences?: StreamReferencesHandler
): Promise<void> {
  const token = await getOrFetchToken()

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  }
  if (token) headers['Authorization'] = `Bearer ${token}`
  if (req.workspace) headers['LIGHTRAG-WORKSPACE'] = req.workspace

  const body = {
    query: req.query,
    mode: req.mode ?? 'hybrid',
    top_k: req.top_k ?? 40,
    stream: true,
    include_references: true,
    history_messages: req.history_messages ?? [],
  }

  let response: Response
  try {
    response = await fetch(`${backendBaseUrl}/query/stream`, {
      method: 'POST',
      headers,
      body: JSON.stringify(body),
      signal,
    })
  } catch (err: unknown) {
    if (err instanceof Error && err.name === 'AbortError') return
    onError(err instanceof Error ? err.message : 'Network error')
    return
  }

  if (!response.ok) {
    let msg = `HTTP ${response.status}`
    try {
      const j = await response.json()
      msg = j.detail ?? msg
    } catch { /* ignore */ }
    onError(msg)
    return
  }

  if (!response.body) {
    onError('Empty response body')
    return
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  const processLine = (line: string) => {
    const trimmed = line.trim()
    if (!trimmed) return
    try {
      const parsed = JSON.parse(trimmed)
      if (parsed.response != null) {
        onChunk(parsed.response)
      } else if (parsed.references && Array.isArray(parsed.references)) {
        onReferences?.(parsed.references as ReferenceItem[])
      } else if (parsed.error) {
        onError(parsed.error)
      }
    } catch { /* not JSON */ }
  }

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() ?? ''
      for (const line of lines) processLine(line)
    }
    if (buffer.trim()) processLine(buffer)
  } catch (err: unknown) {
    if (!(err instanceof Error && err.name === 'AbortError')) {
      onError(err instanceof Error ? err.message : 'Stream read error')
    }
  }

  onDone()
}
