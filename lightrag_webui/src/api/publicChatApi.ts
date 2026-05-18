/**
 * Public Chat API — streams from /query/stream without requiring full auth.
 * Auto-fetches a guest token on first call if no token is stored.
 */
import { backendBaseUrl } from '@/lib/constants'

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
export type StreamDoneHandler = () => void
export type StreamErrorHandler = (err: string) => void

export interface PublicChatRequest {
  query: string
  mode?: string
  top_k?: number
  stream?: boolean
  workspace?: string
  history_messages?: { role: string; content: string }[]
}

export async function streamPublicChat(
  req: PublicChatRequest,
  onChunk: StreamChunkHandler,
  onDone: StreamDoneHandler,
  onError: StreamErrorHandler,
  signal?: AbortSignal
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
  } catch (err: any) {
    if (err?.name === 'AbortError') return
    onError(err?.message ?? 'Network error')
    return
  }

  if (!response.ok) {
    let msg = `HTTP ${response.status}`
    try { msg = (await response.json()).detail ?? msg } catch { /* ignore */ }
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

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() ?? ''

      for (const line of lines) {
        const trimmed = line.trim()
        if (!trimmed) continue
        try {
          const parsed = JSON.parse(trimmed)
          if (parsed.response != null) {
            onChunk(parsed.response)
          } else if (parsed.error) {
            onError(parsed.error)
          }
        } catch {
          // not JSON — skip
        }
      }
    }
    // flush remaining buffer
    if (buffer.trim()) {
      try {
        const parsed = JSON.parse(buffer.trim())
        if (parsed.response != null) onChunk(parsed.response)
        else if (parsed.error) onError(parsed.error)
      } catch { /* ignore */ }
    }
  } catch (err: any) {
    if (err?.name !== 'AbortError') onError(err?.message ?? 'Stream read error')
  }

  onDone()
}
