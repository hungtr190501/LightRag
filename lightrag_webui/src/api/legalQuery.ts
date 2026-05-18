/**
 * Legal Query API — calls /legal/query (14-step legal RAG pipeline).
 */
import axios from 'axios'
import { backendBaseUrl } from '@/lib/constants'
import { useSettingsStore } from '@/stores/settings'
import { WORKSPACE_HEADER_KEY } from '@/stores/workspace'

const api = axios.create({ baseURL: backendBaseUrl, headers: { 'Content-Type': 'application/json' } })
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('LIGHTRAG-API-TOKEN')
  if (token) config.headers.Authorization = `Bearer ${token}`
  const apiKey = useSettingsStore.getState().apiKey
  if (apiKey) config.headers['X-API-Key'] = apiKey
  const workspace = localStorage.getItem(WORKSPACE_HEADER_KEY)
  if (workspace) config.headers['LIGHTRAG-WORKSPACE'] = workspace
  return config
})

// ── Types ─────────────────────────────────────────────────────────────

export type LegalQueryConfig = {
  top_k?: number
  enable_rerank?: boolean
  rerank_top_k?: number
  enable_judge?: boolean
  max_retries?: number
  confidence_threshold?: number
  enable_verification?: boolean
  enable_lightrag?: boolean
  enable_legal_scoring?: boolean
  exclude_expired?: boolean
  min_legal_score?: number
  // filters
  doc_type?: string
  issuer?: string
  doc_numbers?: string[]
  effective_after?: string
}

export type LegalQueryRequest = {
  question: string
  conversation_history?: { role: string; content: string }[]
} & LegalQueryConfig

export type LegalCitation = {
  chunk_id: string
  text: string
  score: number
  rerank_score?: number
  legal_score?: number
  doc_number: string
  doc_type: string
  issuer: string
  issue_date: string
  effective_date: string
  article?: string
  clause?: string
  point?: string
  page_number: number
  status: string
  source: string
}

export type LegalQueryResponse = {
  status: 'success' | 'insufficient_evidence' | 'error'
  answer: string
  answer_with_citations: string
  confidence: number
  grounded: boolean
  citations: LegalCitation[]
  retrieved_chunks: LegalCitation[]
  metadata: {
    query_original: string
    query_rewritten: string
    retrieval_sources: string[]
    total_chunks_retrieved: number
    total_chunks_after_rerank: number
    retry_count: number
    total_duration_ms: number
    conflict_report?: { has_conflicts: boolean; conflict_count: number }
  }
  audit_trail: { step: string; status: string; duration_ms: number; output_summary: string }[]
  error_message: string
}

// ── API ───────────────────────────────────────────────────────────────

export const legalQuery = async (req: LegalQueryRequest): Promise<LegalQueryResponse> => {
  const { data } = await api.post<LegalQueryResponse>('/legal/query', req)
  return data
}
