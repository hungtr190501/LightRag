/**
 * Legal document management API client.
 * Endpoints: GET/PATCH/DELETE /legal/documents
 */
import axios from 'axios'
import { backendBaseUrl } from '@/lib/constants'
import { useSettingsStore } from '@/stores/settings'
import { WORKSPACE_HEADER_KEY } from '@/stores/workspace'

const legalApi = axios.create({
  baseURL: backendBaseUrl,
  headers: { 'Content-Type': 'application/json' },
})

// Multipart instance for file upload
const legalUploadApi = axios.create({ baseURL: backendBaseUrl })

const _authInterceptor = (config: any) => {
  const token = localStorage.getItem('LIGHTRAG-API-TOKEN')
  if (token) config.headers.Authorization = `Bearer ${token}`
  const apiKey = useSettingsStore.getState().apiKey
  if (apiKey) config.headers['X-API-Key'] = apiKey
  const workspace = localStorage.getItem(WORKSPACE_HEADER_KEY)
  if (workspace) config.headers['LIGHTRAG-WORKSPACE'] = workspace
  return config
}

legalUploadApi.interceptors.request.use(_authInterceptor)

legalApi.interceptors.request.use(_authInterceptor)

// ── Types ────────────────────────────────────────────────────────────

export type LegalDocumentStatus = 'HIEU_LUC' | 'HET_HIEU_LUC' | 'BI_THAY_THE' | 'SAP_HIEU_LUC'

export type LegalDocumentItem = {
  doc_id: string
  doc_number: string
  doc_type: string
  issuer: string
  issue_date: string
  effective_date: string
  status: LegalDocumentStatus
  is_primary_source: boolean
  legal_priority: number
  chunks_count: number
}

export type UpdateDocMetaRequest = {
  doc_type?: string
  doc_number?: string
  issuer?: string
  issue_date?: string
  effective_date?: string
  status?: LegalDocumentStatus
  is_primary_source?: boolean
}

export type ListDocumentsParams = {
  doc_type?: string
  status?: string
  limit?: number
}

export type IngestLegalPdfParams = {
  file: File
  doc_number?: string
  doc_type?: string
  issuer?: string
  issue_date?: string
  effective_date?: string
  title?: string
  legal_domain?: string
  enable_contextual?: boolean
  use_ocr?: boolean
}

export type IngestResponse = {
  doc_id: string
  qdrant_chunks?: { parent_count: number; child_count: number; total_chunks: number; extraction_method: string }
  lightrag_status?: string
  graph_relations?: number
  errors: string[]
}

// ── API functions ────────────────────────────────────────────────────

export const ingestLegalPdf = async (
  params: IngestLegalPdfParams,
  onUploadProgress?: (pct: number) => void
): Promise<IngestResponse> => {
  const form = new FormData()
  form.append('file', params.file)
  if (params.doc_number) form.append('doc_number', params.doc_number)
  if (params.doc_type) form.append('doc_type', params.doc_type)
  if (params.issuer) form.append('issuer', params.issuer)
  if (params.issue_date) form.append('issue_date', params.issue_date)
  if (params.effective_date) form.append('effective_date', params.effective_date)
  if (params.title) form.append('title', params.title)
  if (params.legal_domain) form.append('legal_domain', params.legal_domain)
  form.append('enable_contextual', String(params.enable_contextual ?? true))
  form.append('use_ocr', String(params.use_ocr ?? false))

  const { data } = await legalUploadApi.post<IngestResponse>('/legal/ingest/pdf', form, {
    onUploadProgress: (e) => {
      if (onUploadProgress && e.total) {
        onUploadProgress(Math.round((e.loaded * 100) / e.total))
      }
    },
  })
  return data
}

export const getLegalDocuments = async (params?: ListDocumentsParams): Promise<LegalDocumentItem[]> => {
  const { data } = await legalApi.get<LegalDocumentItem[]>('/legal/documents', { params })
  return data
}

export const updateLegalDocument = async (
  docId: string,
  updates: UpdateDocMetaRequest
): Promise<{ doc_id: string; updated_chunks: number; updates: UpdateDocMetaRequest }> => {
  const { data } = await legalApi.patch(`/legal/documents/${encodeURIComponent(docId)}`, updates)
  return data
}

export const deleteLegalDocument = async (
  docId: string
): Promise<{ doc_id: string; deleted_chunks: number }> => {
  const { data } = await legalApi.delete(`/legal/documents/${encodeURIComponent(docId)}`)
  return data
}
