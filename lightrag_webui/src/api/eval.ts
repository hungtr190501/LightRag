/**
 * Evaluation API client — Golden Questions, Benchmark Runs, Failure Cases, Pipeline Replay.
 *
 * Reuses the same axiosInstance from lightrag.ts (auth, workspace headers).
 */
import axios from 'axios'
import { backendBaseUrl } from '@/lib/constants'
import { useSettingsStore } from '@/stores/settings'
import { WORKSPACE_HEADER_KEY } from '@/stores/workspace'

// Reuse the same pattern as lightrag.ts but with a dedicated instance
const evalApi = axios.create({
  baseURL: backendBaseUrl,
  headers: {
    'Content-Type': 'application/json',
  },
})

// Add auth + workspace interceptor (mirrors lightrag.ts)
evalApi.interceptors.request.use((config) => {
  const token = localStorage.getItem('LIGHTRAG-API-TOKEN')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  const apiKey = useSettingsStore.getState().apiKey
  if (apiKey) {
    config.headers['X-API-Key'] = apiKey
  }
  // Add workspace header if available
  const workspace = localStorage.getItem(WORKSPACE_HEADER_KEY)
  if (workspace) {
    config.headers['LIGHTRAG-WORKSPACE'] = workspace
  }
  return config
})

// ── Types ───────────────────────────────────────────────────────────

export type GoldenQuestion = {
  id: string
  question: string
  category: string
  difficulty: string
  expected_answer?: string
  expected_citations?: Array<{ doc_number: string; article?: string; clause?: string }>
  tags?: string[]
  notes?: string
  created_by: string
  created_at: string
  updated_at: string
  is_active: number
}

export type BenchmarkRun = {
  id: string
  name: string
  description?: string
  config_json: Record<string, any>
  model_info?: Record<string, any>
  dataset_version?: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  started_at?: string
  completed_at?: string
  total_questions: number
  completed_questions: number
  accuracy?: number
  citation_accuracy?: number
  hallucination_rate?: number
  avg_latency_ms?: number
  avg_confidence?: number
  metrics_json?: Record<string, any>
  created_at: string
}

export type RunResult = {
  id: string
  run_id: string
  question_id: string
  answer?: string
  confidence?: number
  latency_ms?: number
  pipeline_trace?: Array<Record<string, any>>
  retrieved_chunks?: Array<Record<string, any>>
  citations?: Array<Record<string, any>>
  is_correct?: number | null
  citation_valid?: number | null
  has_hallucination?: number | null
  evaluator_notes?: string
  evaluated_by?: string
  evaluated_at?: string
  error?: string
  created_at: string
}

export type FailureCase = {
  id: string
  source: string
  question: string
  answer?: string
  failure_type: string
  severity: string
  description?: string
  root_cause?: string
  pipeline_trace?: Array<Record<string, any>>
  run_id?: string
  question_id?: string
  status: string
  resolution?: string
  converted_to_golden: number
  created_by: string
  created_at: string
  updated_at: string
}

export type DatasetVersion = {
  id: string
  name: string
  description?: string
  question_ids: string[]
  question_count: number
  created_by: string
  created_at: string
}

export type PaginatedResponse<T> = {
  items: T[]
  total: number
  offset: number
  limit: number
}

export type ReplayData = {
  result_id: string
  question: string
  answer: string
  confidence?: number
  latency_ms?: number
  pipeline_trace: Array<Record<string, any>>
  retrieved_chunks: Array<Record<string, any>>
  citations: Array<Record<string, any>>
  error?: string
}

export type RunComparison = {
  run_a: { id: string; name: string; metrics: Record<string, any> }
  run_b: { id: string; name: string; metrics: Record<string, any> }
  summary: {
    total_questions: number
    improved: number
    degraded: number
    unchanged: number
  }
  per_question: Array<Record<string, any>>
}

// ── Golden Questions ────────────────────────────────────────────────

export const listGoldenQuestions = async (params?: {
  category?: string
  difficulty?: string
  is_active?: boolean
  offset?: number
  limit?: number
}): Promise<PaginatedResponse<GoldenQuestion>> => {
  const response = await evalApi.get('/eval/golden-questions', { params })
  return response.data
}

export const getGoldenQuestion = async (id: string): Promise<GoldenQuestion> => {
  const response = await evalApi.get(`/eval/golden-questions/${id}`)
  return response.data
}

export const createGoldenQuestion = async (data: {
  question: string
  category?: string
  difficulty?: string
  expected_answer?: string
  expected_citations?: Array<Record<string, any>>
  tags?: string[]
  notes?: string
}): Promise<GoldenQuestion> => {
  const response = await evalApi.post('/eval/golden-questions', data)
  return response.data
}

export const updateGoldenQuestion = async (
  id: string,
  data: Partial<{
    question: string
    category: string
    difficulty: string
    expected_answer: string
    expected_citations: Array<Record<string, any>>
    tags: string[]
    notes: string
    is_active: boolean
  }>
): Promise<GoldenQuestion> => {
  const response = await evalApi.put(`/eval/golden-questions/${id}`, data)
  return response.data
}

export const deleteGoldenQuestion = async (id: string): Promise<void> => {
  await evalApi.delete(`/eval/golden-questions/${id}`)
}

export const importGoldenQuestions = async (
  questions: Array<Record<string, any>>
): Promise<{ imported: number; errors: string[] }> => {
  const response = await evalApi.post('/eval/golden-questions/import', { questions })
  return response.data
}

export const exportGoldenQuestions = async (): Promise<{
  questions: GoldenQuestion[]
  count: number
}> => {
  const response = await evalApi.get('/eval/golden-questions/export')
  return response.data
}

// ── Benchmark Runs ──────────────────────────────────────────────────

export const listBenchmarkRuns = async (params?: {
  status?: string
  offset?: number
  limit?: number
}): Promise<PaginatedResponse<BenchmarkRun>> => {
  const response = await evalApi.get('/eval/benchmark-runs', { params })
  return response.data
}

export const getBenchmarkRun = async (id: string): Promise<BenchmarkRun> => {
  const response = await evalApi.get(`/eval/benchmark-runs/${id}`)
  return response.data
}

export const createBenchmarkRun = async (data: {
  name: string
  description?: string
  config?: Record<string, any>
  model_info?: Record<string, any>
  dataset_version?: string
}): Promise<BenchmarkRun> => {
  const response = await evalApi.post('/eval/benchmark-runs', data)
  return response.data
}

export const startBenchmarkRun = async (
  id: string
): Promise<{ message: string; run_id: string }> => {
  const response = await evalApi.post(`/eval/benchmark-runs/${id}/start`)
  return response.data
}

export const getRunResults = async (
  runId: string
): Promise<{ run: BenchmarkRun; results: RunResult[] }> => {
  const response = await evalApi.get(`/eval/benchmark-runs/${runId}/results`)
  return response.data
}

export const compareRuns = async (
  idA: string,
  idB: string
): Promise<RunComparison> => {
  const response = await evalApi.get('/eval/benchmark-runs/compare', {
    params: { a: idA, b: idB },
  })
  return response.data
}

// ── Run Results ─────────────────────────────────────────────────────

export const evaluateResult = async (
  resultId: string,
  data: {
    is_correct?: number
    citation_valid?: number
    has_hallucination?: number
    evaluator_notes?: string
    evaluated_by?: string
  }
): Promise<RunResult> => {
  const response = await evalApi.put(`/eval/run-results/${resultId}/evaluate`, data)
  return response.data
}

// ── Failure Cases ───────────────────────────────────────────────────

export const listFailureCases = async (params?: {
  status?: string
  failure_type?: string
  offset?: number
  limit?: number
}): Promise<PaginatedResponse<FailureCase>> => {
  const response = await evalApi.get('/eval/failure-cases', { params })
  return response.data
}

export const getFailureCase = async (id: string): Promise<FailureCase> => {
  const response = await evalApi.get(`/eval/failure-cases/${id}`)
  return response.data
}

export const createFailureCase = async (data: {
  question: string
  answer?: string
  failure_type: string
  severity?: string
  description?: string
  root_cause?: string
  source?: string
  run_id?: string
  question_id?: string
}): Promise<FailureCase> => {
  const response = await evalApi.post('/eval/failure-cases', data)
  return response.data
}

export const updateFailureCase = async (
  id: string,
  data: Partial<{
    status: string
    severity: string
    description: string
    root_cause: string
    resolution: string
  }>
): Promise<FailureCase> => {
  const response = await evalApi.put(`/eval/failure-cases/${id}`, data)
  return response.data
}

export const convertToGolden = async (
  id: string
): Promise<{ message: string; question_id: string }> => {
  const response = await evalApi.post(`/eval/failure-cases/${id}/convert-to-golden`)
  return response.data
}

// ── Pipeline Replay ─────────────────────────────────────────────────

export const getReplayData = async (resultId: string): Promise<ReplayData> => {
  const response = await evalApi.get(`/eval/replay/${resultId}`)
  return response.data
}

// ── Dataset Versions ────────────────────────────────────────────────

export const listDatasetVersions = async (): Promise<{
  items: DatasetVersion[]
}> => {
  const response = await evalApi.get('/eval/dataset-versions')
  return response.data
}

export const createDatasetVersion = async (data: {
  name: string
  description?: string
  question_ids?: string[]
}): Promise<DatasetVersion> => {
  const response = await evalApi.post('/eval/dataset-versions', data)
  return response.data
}
