import { useCallback, useEffect, useRef, useState } from 'react'
import Button from '@/components/ui/Button'
import Input from '@/components/ui/Input'
import Textarea from '@/components/ui/Textarea'
import { legalQuery } from '@/api/legalQuery'
import type { LegalCitation, LegalQueryResponse } from '@/api/legalQuery'
import { errorMessage } from '@/lib/utils'
import {
  SendIcon,
  EraserIcon,
  ChevronDownIcon,
  ChevronUpIcon,
  FileTextIcon,
  CheckCircleIcon,
  AlertCircleIcon,
  ClockIcon,
} from 'lucide-react'

// ── Types ─────────────────────────────────────────────────────────────

type Role = 'user' | 'assistant'

interface ChatEntry {
  id: string
  role: Role
  content: string
  response?: LegalQueryResponse
  error?: string
  loading?: boolean
}

// ── Helpers ───────────────────────────────────────────────────────────

const generateId = () =>
  typeof crypto !== 'undefined' && crypto.randomUUID
    ? crypto.randomUUID()
    : `id-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`

function statusColor(status: string) {
  if (status === 'HIEU_LUC') return 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900 dark:text-emerald-200'
  if (status === 'HET_HIEU_LUC') return 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200'
  if (status === 'SAP_HIEU_LUC') return 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200'
  return 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300'
}

function confidenceBadge(conf: number) {
  if (conf >= 0.85) return 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900 dark:text-emerald-200'
  if (conf >= 0.6) return 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200'
  return 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200'
}

// ── Sub-components ────────────────────────────────────────────────────

function CitationCard({ c }: { c: LegalCitation }) {
  const [expanded, setExpanded] = useState(false)
  const parts = [c.article, c.clause, c.point].filter(Boolean).join(' · ')
  return (
    <div className="border rounded-lg p-3 text-xs space-y-1 bg-muted/30">
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-1 font-medium flex-wrap">
          <FileTextIcon className="size-3 shrink-0" />
          <span>{c.doc_number}</span>
          {parts && <span className="text-muted-foreground">— {parts}</span>}
        </div>
        <div className="flex items-center gap-1 shrink-0 flex-wrap">
          {c.legal_score != null && (
            <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${confidenceBadge(c.legal_score)}`}>
              {(c.legal_score * 100).toFixed(0)}%
            </span>
          )}
          <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${statusColor(c.status)}`}>
            {c.status}
          </span>
        </div>
      </div>
      <div className="text-muted-foreground">
        {c.doc_type} · {c.issuer} · {c.issue_date}
      </div>
      <button
        className="text-primary underline-offset-2 hover:underline"
        onClick={() => setExpanded((v) => !v)}
      >
        {expanded ? 'Thu gọn' : 'Xem đoạn trích'}
      </button>
      {expanded && (
        <div className="mt-1 p-2 rounded bg-background border text-xs leading-relaxed max-h-40 overflow-y-auto whitespace-pre-wrap">
          {c.text}
        </div>
      )}
    </div>
  )
}

function AssistantBubble({ entry }: { entry: ChatEntry }) {
  const res = entry.response
  const [showCitations, setShowCitations] = useState(false)
  const [showAudit, setShowAudit] = useState(false)

  if (entry.loading) {
    return (
      <div className="flex gap-2 items-start">
        <div className="size-7 rounded-full bg-emerald-100 dark:bg-emerald-900 flex items-center justify-center shrink-0 text-emerald-700 dark:text-emerald-300 text-xs font-bold">
          AI
        </div>
        <div className="flex items-center gap-2 px-4 py-3 rounded-2xl rounded-tl-sm bg-muted max-w-xl">
          <div className="size-2 rounded-full bg-emerald-400 animate-bounce [animation-delay:-0.3s]" />
          <div className="size-2 rounded-full bg-emerald-400 animate-bounce [animation-delay:-0.15s]" />
          <div className="size-2 rounded-full bg-emerald-400 animate-bounce" />
        </div>
      </div>
    )
  }

  if (entry.error) {
    return (
      <div className="flex gap-2 items-start">
        <div className="size-7 rounded-full bg-red-100 dark:bg-red-900 flex items-center justify-center shrink-0 text-red-700 dark:text-red-300 text-xs font-bold">
          AI
        </div>
        <div className="px-4 py-3 rounded-2xl rounded-tl-sm bg-red-50 dark:bg-red-950 border border-red-200 dark:border-red-800 text-sm text-red-700 dark:text-red-300 max-w-xl">
          <AlertCircleIcon className="inline size-4 mr-1 align-text-bottom" />
          {entry.error}
        </div>
      </div>
    )
  }

  if (!res) return null

  const statusIcon =
    res.status === 'success' ? (
      <CheckCircleIcon className="size-3 text-emerald-600" />
    ) : res.status === 'insufficient_evidence' ? (
      <AlertCircleIcon className="size-3 text-yellow-600" />
    ) : (
      <AlertCircleIcon className="size-3 text-red-600" />
    )

  return (
    <div className="flex gap-2 items-start max-w-3xl">
      <div className="size-7 rounded-full bg-emerald-100 dark:bg-emerald-900 flex items-center justify-center shrink-0 text-emerald-700 dark:text-emerald-300 text-xs font-bold">
        AI
      </div>
      <div className="space-y-2 flex-1 min-w-0">
        {/* Status row */}
        <div className="flex items-center gap-2 flex-wrap">
          <div className="flex items-center gap-1 text-xs">
            {statusIcon}
            <span className="text-muted-foreground capitalize">{res.status.replace(/_/g, ' ')}</span>
          </div>
          <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${confidenceBadge(res.confidence)}`}>
            Confidence {(res.confidence * 100).toFixed(0)}%
          </span>
          {res.grounded && (
            <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200">
              Grounded
            </span>
          )}
          {res.metadata?.conflict_report?.has_conflicts && (
            <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200">
              {res.metadata.conflict_report.conflict_count} xung đột
            </span>
          )}
          <span className="text-[10px] text-muted-foreground flex items-center gap-0.5">
            <ClockIcon className="size-3" />
            {((res.metadata?.total_duration_ms ?? 0) / 1000).toFixed(1)}s
          </span>
        </div>

        {/* Answer */}
        <div className="px-4 py-3 rounded-2xl rounded-tl-sm bg-muted text-sm leading-relaxed whitespace-pre-wrap">
          {res.answer_with_citations || res.answer}
        </div>

        {/* Citations toggle */}
        {res.citations?.length > 0 && (
          <div className="space-y-1">
            <button
              className="flex items-center gap-1 text-xs text-primary hover:underline"
              onClick={() => setShowCitations((v) => !v)}
            >
              {showCitations ? <ChevronUpIcon className="size-3" /> : <ChevronDownIcon className="size-3" />}
              {res.citations.length} nguồn trích dẫn
            </button>
            {showCitations && (
              <div className="space-y-2 pl-2 border-l-2 border-emerald-200 dark:border-emerald-800">
                {res.citations.map((c) => (
                  <CitationCard key={c.chunk_id} c={c} />
                ))}
              </div>
            )}
          </div>
        )}

        {/* Audit trail */}
        {res.audit_trail?.length > 0 && (
          <div>
            <button
              className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
              onClick={() => setShowAudit((v) => !v)}
            >
              {showAudit ? <ChevronUpIcon className="size-3" /> : <ChevronDownIcon className="size-3" />}
              Pipeline trace ({res.audit_trail.length} bước)
            </button>
            {showAudit && (
              <div className="mt-1 space-y-1 pl-2 border-l-2 border-border">
                {res.audit_trail.map((step, i) => (
                  <div key={i} className="text-[11px] flex items-start gap-2">
                    <span
                      className={`mt-0.5 size-2 rounded-full shrink-0 ${step.status === 'ok' ? 'bg-emerald-400' : step.status === 'skipped' ? 'bg-gray-300' : 'bg-red-400'}`}
                    />
                    <div>
                      <span className="font-medium">{step.step}</span>
                      {step.duration_ms > 0 && (
                        <span className="text-muted-foreground"> ({step.duration_ms}ms)</span>
                      )}
                      {step.output_summary && (
                        <div className="text-muted-foreground">{step.output_summary}</div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

// ── Settings panel ────────────────────────────────────────────────────

interface PipelineSettings {
  top_k: number
  enable_rerank: boolean
  rerank_top_k: number
  enable_judge: boolean
  max_retries: number
  confidence_threshold: number
  enable_verification: boolean
  enable_lightrag: boolean
  enable_legal_scoring: boolean
  exclude_expired: boolean
  min_legal_score: number
  doc_type: string
  issuer: string
}

const DEFAULT_SETTINGS: PipelineSettings = {
  top_k: 20,
  enable_rerank: true,
  rerank_top_k: 10,
  enable_judge: true,
  max_retries: 2,
  confidence_threshold: 0.85,
  enable_verification: true,
  enable_lightrag: true,
  enable_legal_scoring: true,
  exclude_expired: false,
  min_legal_score: 0,
  doc_type: '',
  issuer: '',
}

function SettingsPanel({
  settings,
  onChange,
}: {
  settings: PipelineSettings
  onChange: (s: PipelineSettings) => void
}) {
  const set = <K extends keyof PipelineSettings>(key: K, val: PipelineSettings[K]) =>
    onChange({ ...settings, [key]: val })

  return (
    <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-xs p-4 border rounded-lg bg-muted/30">
      {/* Numeric fields */}
      {(
        [
          ['top_k', 'Top-K', 1, 100],
          ['rerank_top_k', 'Rerank Top-K', 1, 50],
          ['max_retries', 'Max Retries', 0, 5],
          ['confidence_threshold', 'Confidence Threshold', 0, 1, 0.05],
          ['min_legal_score', 'Min Legal Score', 0, 1, 0.05],
        ] as [keyof PipelineSettings, string, number, number, number?][]
      ).map(([key, label, min, max, step = 1]) => (
        <label key={key} className="flex items-center justify-between gap-2">
          <span className="text-muted-foreground">{label}</span>
          <input
            type="number"
            min={min}
            max={max}
            step={step}
            value={settings[key] as number}
            onChange={(e) => set(key, parseFloat(e.target.value) as any)}
            className="w-20 rounded border px-2 py-0.5 bg-background text-xs text-right"
          />
        </label>
      ))}

      {/* Boolean toggles */}
      {(
        [
          ['enable_rerank', 'Rerank'],
          ['enable_judge', 'LLM Judge'],
          ['enable_verification', 'Verification'],
          ['enable_lightrag', 'LightRAG KG'],
          ['enable_legal_scoring', 'Legal Scoring'],
          ['exclude_expired', 'Exclude Expired'],
        ] as [keyof PipelineSettings, string][]
      ).map(([key, label]) => (
        <label key={key} className="flex items-center justify-between gap-2 cursor-pointer">
          <span className="text-muted-foreground">{label}</span>
          <input
            type="checkbox"
            checked={settings[key] as boolean}
            onChange={(e) => set(key, e.target.checked as any)}
            className="accent-emerald-500"
          />
        </label>
      ))}

      {/* Text filters */}
      <label className="flex items-center justify-between gap-2 col-span-2">
        <span className="text-muted-foreground w-28 shrink-0">Loại văn bản</span>
        <Input
          value={settings.doc_type}
          onChange={(e) => set('doc_type', e.target.value)}
          placeholder="Nghị định, Thông tư…"
          className="h-6 text-xs"
        />
      </label>
      <label className="flex items-center justify-between gap-2 col-span-2">
        <span className="text-muted-foreground w-28 shrink-0">Cơ quan ban hành</span>
        <Input
          value={settings.issuer}
          onChange={(e) => set('issuer', e.target.value)}
          placeholder="Chính phủ, Bộ…"
          className="h-6 text-xs"
        />
      </label>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────

export default function LegalChat() {
  const [messages, setMessages] = useState<ChatEntry[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [showSettings, setShowSettings] = useState(false)
  const [settings, setSettings] = useState<PipelineSettings>(DEFAULT_SETTINGS)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const send = useCallback(async () => {
    const question = input.trim()
    if (!question || loading) return

    const userEntry: ChatEntry = { id: generateId(), role: 'user', content: question }
    const aiEntry: ChatEntry = { id: generateId(), role: 'assistant', content: '', loading: true }

    // Build conversation history from current messages before state update
    const history: { role: string; content: string }[] = messages.flatMap((m) => {
      if (m.role === 'user') return [{ role: 'user', content: m.content }]
      if (m.role === 'assistant' && m.response) return [{ role: 'assistant', content: m.response.answer || m.content }]
      return []
    })

    setMessages((prev) => [...prev, userEntry, aiEntry])
    setInput('')
    setLoading(true)

    try {
      const res = await legalQuery({
        question,
        conversation_history: history,
        top_k: settings.top_k,
        enable_rerank: settings.enable_rerank,
        rerank_top_k: settings.rerank_top_k,
        enable_judge: settings.enable_judge,
        max_retries: settings.max_retries,
        confidence_threshold: settings.confidence_threshold,
        enable_verification: settings.enable_verification,
        enable_lightrag: settings.enable_lightrag,
        enable_legal_scoring: settings.enable_legal_scoring,
        exclude_expired: settings.exclude_expired,
        min_legal_score: settings.min_legal_score,
        doc_type: settings.doc_type || undefined,
        issuer: settings.issuer || undefined,
      })

      setMessages((prev) =>
        prev.map((m) =>
          m.id === aiEntry.id ? { ...m, loading: false, response: res, content: res.answer } : m
        )
      )
    } catch (e) {
      setMessages((prev) =>
        prev.map((m) =>
          m.id === aiEntry.id ? { ...m, loading: false, error: errorMessage(e) } : m
        )
      )
    } finally {
      setLoading(false)
    }
  }, [input, loading, messages, settings])

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  const clearChat = () => {
    setMessages([])
    setInput('')
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header bar */}
      <div className="flex items-center justify-between px-4 py-2 border-b bg-background/80 backdrop-blur shrink-0">
        <div className="flex items-center gap-2">
          <span className="font-semibold text-sm">Tư vấn pháp luật</span>
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-800 dark:bg-emerald-900 dark:text-emerald-200 font-medium">
            /legal/query
          </span>
        </div>
        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="icon"
            tooltip="Xoá hội thoại"
            onClick={clearChat}
            disabled={messages.length === 0}
          >
            <EraserIcon className="size-4" />
          </Button>
          <Button
            variant={showSettings ? 'secondary' : 'ghost'}
            size="sm"
            onClick={() => setShowSettings((v) => !v)}
            className="text-xs gap-1"
          >
            Cài đặt pipeline
            {showSettings ? <ChevronUpIcon className="size-3" /> : <ChevronDownIcon className="size-3" />}
          </Button>
        </div>
      </div>

      {/* Settings panel */}
      {showSettings && (
        <div className="px-4 py-3 border-b shrink-0">
          <SettingsPanel settings={settings} onChange={setSettings} />
        </div>
      )}

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-muted-foreground text-sm gap-2">
            <FileTextIcon className="size-10 opacity-30" />
            <p>Hỏi bất kỳ câu hỏi pháp lý nào để bắt đầu</p>
            <p className="text-xs opacity-60">Pipeline 14 bước: truy xuất → rerank → sinh câu trả lời → trích dẫn</p>
          </div>
        )}
        {messages.map((entry) =>
          entry.role === 'user' ? (
            <div key={entry.id} className="flex justify-end">
              <div className="px-4 py-3 rounded-2xl rounded-tr-sm bg-emerald-500 text-white text-sm max-w-xl whitespace-pre-wrap">
                {entry.content}
              </div>
            </div>
          ) : (
            <AssistantBubble key={entry.id} entry={entry} />
          )
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input bar */}
      <div className="px-4 py-3 border-t bg-background/80 backdrop-blur shrink-0">
        <div className="flex gap-2 items-end">
          <Textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Nhập câu hỏi pháp lý... (Enter để gửi, Shift+Enter xuống dòng)"
            className="resize-none min-h-[40px] max-h-32 text-sm"
            rows={1}
            disabled={loading}
          />
          <Button
            onClick={send}
            disabled={!input.trim() || loading}
            size="icon"
            className="shrink-0 bg-emerald-500 hover:bg-emerald-600 text-white"
          >
            <SendIcon className="size-4" />
          </Button>
        </div>
        <p className="text-[10px] text-muted-foreground mt-1">
          Enter gửi · Shift+Enter xuống dòng · Lịch sử hội thoại được giữ tự động
        </p>
      </div>
    </div>
  )
}
