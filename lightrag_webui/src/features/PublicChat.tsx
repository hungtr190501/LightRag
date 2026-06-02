import {
  type CSSProperties,
  type KeyboardEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { useParams, useNavigate } from 'react-router-dom'
import { streamPublicChat, type ReferenceItem, type AgenticStepEvent } from '@/api/publicChatApi'
import { getPublicChatConfig, updatePublicChatConfig, type PublicChatConfig } from '@/api/workspace'
import {
  listSessions,
  createSession,
  addMessage,
  setFeedback,
  type SessionSummary,
  type Feedback,
} from '@/api/publicChatSessions'
import { listPublicDocuments, uploadDocument, fetchPublicGraph, type PublicDocument, type GraphData } from '@/api/publicDocuments'
import CitationModal from '@/components/retrieval/CitationModal'
import {
  BotIcon,
  SendIcon,
  Settings2Icon,
  XIcon,
  PlusIcon,
  ZapIcon,
  StopCircleIcon,
  CheckIcon,
  Loader2Icon,
  BookOpenIcon,
  ThumbsUpIcon,
  ThumbsDownIcon,
  PanelLeftIcon,
  HistoryIcon,
  MessageSquarePlusIcon,
  UploadIcon,
  FileTextIcon,
  CheckCircle2Icon,
  XCircleIcon,
  ClockIcon,
  EyeIcon,
  NetworkIcon,
  Maximize2Icon,
  Minimize2Icon,
  LogInIcon,
  LogOutIcon,
} from 'lucide-react'
import { useAuthStore } from '@/stores/state'
import PublicLoginModal from '@/components/PublicLoginModal'

// ── Types ────────────────────────────────────────────────────────────────────

type Role = 'user' | 'assistant'

interface Message {
  id: string
  /** server-assigned id (after save) */
  serverId?: string
  role: Role
  content: string
  query?: string
  streaming?: boolean
  error?: boolean
  references?: ReferenceItem[]
  feedback?: Feedback
  agenticSteps?: AgenticStepEvent[]
}

const DEFAULT_CONFIG: PublicChatConfig = {
  title: '',
  description: '',
  mode: 'hybrid',
  top_k: 40,
  suggested_questions: [],
  accent_color: '#10b981',
}

// ── Helpers ──────────────────────────────────────────────────────────────────

const uid = () =>
  typeof crypto !== 'undefined' && crypto.randomUUID
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(36).slice(2)}`

function getFileName(fp: string) {
  return fp.split('/').pop() || fp
}

function fmtDate(iso: string) {
  try {
    return new Date(iso).toLocaleDateString('vi-VN', {
      day: '2-digit', month: '2-digit', year: 'numeric',
    })
  } catch { return iso }
}

// ── Markdown helpers ──────────────────────────────────────────────────────────

const REF_SECTION = /\n#{1,3}\s*(Tài liệu tham khảo|Nguồn tham khảo|Căn cứ pháp lý|Tài liệu căn cứ|References?)\s*(\n|$)/i

function stripReferencesSection(text: string): string {
  const idx = text.search(REF_SECTION)
  return idx !== -1 ? text.slice(0, idx).trimEnd() : text
}

// ── Sources row ───────────────────────────────────────────────────────────────

function SourcesRow({
  references, accent, onCite,
}: {
  references: ReferenceItem[]
  accent: string
  onCite: (ref: ReferenceItem, idx: string) => void
}) {
  const [open, setOpen] = useState(false)
  if (!references.length) return null
  return (
    <div className="mt-3">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 text-xs font-medium mb-2"
        style={{ color: accent }}
      >
        <BookOpenIcon className="size-3.5" />
        {references.length} tài liệu căn cứ
        <span className="text-zinc-400 font-normal">{open ? '↑' : '↓'}</span>
      </button>
      {open && (
        <div className="flex flex-wrap gap-2">
          {references.map((ref, i) => {
            const idx = String(i + 1)
            return (
              <button
                key={ref.chunk_id ?? i}
                onClick={() => onCite(ref, idx)}
                className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg border text-xs transition-colors"
                style={{ borderColor: `${accent}55`, color: accent } as CSSProperties}
                onMouseEnter={(e) => { const el = e.currentTarget as HTMLButtonElement; el.style.backgroundColor = accent; el.style.color = '#fff'; el.style.borderColor = accent }}
                onMouseLeave={(e) => { const el = e.currentTarget as HTMLButtonElement; el.style.backgroundColor = ''; el.style.color = accent; el.style.borderColor = `${accent}55` }}
                title={ref.file_path}
              >
                <BookOpenIcon className="size-3 shrink-0" />
                <span className="font-mono">[{idx}]</span>
                <span className="max-w-[160px] truncate">{getFileName(ref.file_path)}</span>
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}

// ── Config panel ──────────────────────────────────────────────────────────────

function ConfigPanel({ workspace, config, onSaved, onClose }: {
  workspace: string; config: PublicChatConfig
  onSaved: (c: PublicChatConfig) => void; onClose: () => void
}) {
  const [draft, setDraft] = useState<PublicChatConfig>({ ...config })
  const [newQ, setNewQ] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const set = <K extends keyof PublicChatConfig>(k: K, v: PublicChatConfig[K]) =>
    setDraft((d) => ({ ...d, [k]: v }))

  const addQ = () => { const q = newQ.trim(); if (!q) return; setDraft((d) => ({ ...d, suggested_questions: [...d.suggested_questions, q] })); setNewQ('') }
  const removeQ = (i: number) => setDraft((d) => ({ ...d, suggested_questions: d.suggested_questions.filter((_: string, idx: number) => idx !== i) }))

  const save = async () => {
    setSaving(true); setError('')
    try { const saved = await updatePublicChatConfig(workspace, draft); onSaved(saved); onClose() }
    catch (e: unknown) { const err = e as { response?: { data?: { detail?: string } }; message?: string }; setError(err?.response?.data?.detail ?? err?.message ?? 'Lỗi lưu') }
    finally { setSaving(false) }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
      <div className="w-full max-w-lg bg-white dark:bg-zinc-900 rounded-2xl shadow-2xl overflow-hidden">
        <div className="flex items-center justify-between px-6 py-4 border-b border-zinc-200 dark:border-zinc-700">
          <h2 className="font-semibold text-base">Cấu hình trang chat</h2>
          <button onClick={onClose} className="p-1 rounded-lg hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-500"><XIcon className="size-4" /></button>
        </div>
        <div className="px-6 py-5 space-y-5 max-h-[70vh] overflow-y-auto">
          {error && <div className="text-sm text-red-500 bg-red-50 dark:bg-red-950 px-3 py-2 rounded-lg">{error}</div>}
          <div>
            <label className="block text-xs font-medium text-zinc-500 mb-1.5">Tiêu đề hiển thị</label>
            <input className="w-full rounded-lg border border-zinc-200 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-800 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500" value={draft.title} onChange={(e) => set('title', e.target.value)} placeholder={`Trợ lý ${workspace}`} />
          </div>
          <div>
            <label className="block text-xs font-medium text-zinc-500 mb-1.5">Mô tả ngắn</label>
            <input className="w-full rounded-lg border border-zinc-200 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-800 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500" value={draft.description} onChange={(e) => set('description', e.target.value)} placeholder="Hỏi bất kỳ điều gì…" />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-medium text-zinc-500 mb-1.5">Query mode</label>
              <select className="w-full rounded-lg border border-zinc-200 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-800 px-3 py-2 text-sm focus:outline-none" value={draft.mode} onChange={(e) => set('mode', e.target.value as PublicChatConfig['mode'])}>
                {(['local', 'global', 'hybrid', 'mix', 'naive'] as const).map((m) => <option key={m} value={m}>{m}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-zinc-500 mb-1.5">Top-K</label>
              <input type="number" min={1} max={100} className="w-full rounded-lg border border-zinc-200 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-800 px-3 py-2 text-sm focus:outline-none" value={draft.top_k} onChange={(e) => set('top_k', Number(e.target.value))} />
            </div>
          </div>
          <div>
            <label className="block text-xs font-medium text-zinc-500 mb-1.5">Màu chủ đạo</label>
            <div className="flex items-center gap-3">
              <input type="color" className="size-9 rounded-lg border border-zinc-200 dark:border-zinc-700 cursor-pointer" value={draft.accent_color} onChange={(e) => set('accent_color', e.target.value)} />
              <span className="text-sm text-zinc-500 font-mono">{draft.accent_color}</span>
            </div>
          </div>
          <div>
            <label className="block text-xs font-medium text-zinc-500 mb-1.5">Câu hỏi gợi ý ({draft.suggested_questions.length})</label>
            <div className="space-y-2">
              {draft.suggested_questions.map((q: string, i: number) => (
                <div key={i} className="flex items-center gap-2 p-2.5 rounded-lg bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700">
                  <span className="flex-1 truncate text-xs">{q}</span>
                  <button onClick={() => removeQ(i)} className="text-zinc-400 hover:text-red-500 shrink-0"><XIcon className="size-3.5" /></button>
                </div>
              ))}
              <div className="flex gap-2">
                <input className="flex-1 rounded-lg border border-zinc-200 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-800 px-3 py-2 text-sm focus:outline-none" placeholder="Thêm câu hỏi gợi ý…" value={newQ} onChange={(e) => setNewQ(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && addQ()} />
                <button onClick={addQ} className="px-3 py-2 rounded-lg bg-emerald-500 hover:bg-emerald-600 text-white"><PlusIcon className="size-4" /></button>
              </div>
            </div>
          </div>
        </div>
        <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-zinc-200 dark:border-zinc-700">
          <button onClick={onClose} className="px-4 py-2 rounded-lg text-sm text-zinc-600 dark:text-zinc-400 hover:bg-zinc-100 dark:hover:bg-zinc-800">Hủy</button>
          <button onClick={save} disabled={saving} className="px-4 py-2 rounded-lg text-sm bg-emerald-500 hover:bg-emerald-600 disabled:opacity-60 text-white flex items-center gap-1.5">
            {saving ? <Loader2Icon className="size-4 animate-spin" /> : <CheckIcon className="size-4" />}Lưu
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Session sidebar ───────────────────────────────────────────────────────────

// ── Sources panel ─────────────────────────────────────────────────────────────

function DocStatusBadge({ status }: { status: string }) {
  if (status === 'processed')
    return <CheckCircle2Icon className="size-3.5 text-emerald-500 shrink-0" />
  if (status === 'failed')
    return <XCircleIcon className="size-3.5 text-red-500 shrink-0" />
  return <ClockIcon className="size-3.5 text-amber-400 shrink-0 animate-pulse" />
}

function DocViewModal({ doc, onClose }: { doc: PublicDocument; onClose: () => void }) {
  const filename = doc.file_path.split('/').pop() || doc.file_path
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-sm" onClick={onClose}>
      <div
        className="w-full max-w-lg bg-white dark:bg-zinc-900 rounded-2xl shadow-2xl overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-5 py-4 border-b border-zinc-200 dark:border-zinc-800">
          <div className="flex items-center gap-2 min-w-0">
            <FileTextIcon className="size-4 text-zinc-400 shrink-0" />
            <span className="text-sm font-semibold text-zinc-900 dark:text-zinc-100 truncate">{filename}</span>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-400">
            <XIcon className="size-4" />
          </button>
        </div>
        <div className="px-5 py-4 space-y-3">
          <div className="flex items-center gap-3 text-xs text-zinc-500">
            <span className="flex items-center gap-1"><DocStatusBadge status={doc.status} />{doc.status}</span>
            {doc.chunks_count != null && <span>{doc.chunks_count} đoạn</span>}
            {doc.created_at && <span>{new Date(doc.created_at).toLocaleDateString('vi-VN')}</span>}
          </div>
          {doc.content_summary && (
            <div>
              <div className="text-[11px] font-semibold text-zinc-400 uppercase tracking-wide mb-1.5">Nội dung mẫu</div>
              <p className="text-xs text-zinc-600 dark:text-zinc-300 leading-relaxed whitespace-pre-wrap bg-zinc-50 dark:bg-zinc-800/60 rounded-xl p-3 max-h-48 overflow-y-auto">
                {doc.content_summary}
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Graph modal ───────────────────────────────────────────────────────────────

import { UndirectedGraph } from 'graphology'
import { SigmaContainer, useRegisterEvents, useSigma } from '@react-sigma/core'
import { NodeBorderProgram } from '@sigma/node-border'
import { createEdgeCurveProgram } from '@sigma/edge-curve'
import { resolveNodeColor } from '@/utils/graphColor'
import { labelColorDarkTheme, nodeBorderColor, minNodeSize, maxNodeSize } from '@/lib/constants'
import '@react-sigma/core/lib/style.css'

function drawDarkNodeHover(
  context: CanvasRenderingContext2D,
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  data: any,
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  settings: any,
): void {
  const label = data.label as string | undefined
  if (!label) return
  const size: number = settings.labelSize
  const font: string = settings.labelFont
  const weight: string = settings.labelWeight
  context.font = `${weight} ${size}px ${font}`
  const PADDING = 2
  const textWidth = context.measureText(label).width
  const boxHeight = Math.round(size + 2 * PADDING)
  const radius = Math.max(data.size as number, size / 2) + PADDING
  const angleRadian = Math.asin(boxHeight / 2 / radius)
  const xDeltaCoord = Math.sqrt(Math.abs(Math.pow(radius, 2) - Math.pow(boxHeight / 2, 2)))
  const boxWidth = Math.round(textWidth + 5)

  context.fillStyle = 'rgba(12, 12, 18, 0.94)'
  context.shadowOffsetX = 0
  context.shadowOffsetY = 0
  context.shadowBlur = 8
  context.shadowColor = 'rgba(255,255,255,0.12)'
  context.beginPath()
  context.moveTo(data.x + xDeltaCoord, data.y + boxHeight / 2)
  context.lineTo(data.x + radius + boxWidth, data.y + boxHeight / 2)
  context.lineTo(data.x + radius + boxWidth, data.y - boxHeight / 2)
  context.lineTo(data.x + xDeltaCoord, data.y - boxHeight / 2)
  context.arc(data.x, data.y, radius, angleRadian, -angleRadian)
  context.closePath()
  context.fill()
  context.shadowOffsetX = 0
  context.shadowOffsetY = 0
  context.shadowBlur = 0

  context.fillStyle = '#ffffff'
  context.fillText(label, data.x + data.size + 3, data.y + size / 3)
}

function GraphDragEvents() {
  const registerEvents = useRegisterEvents()
  const sigma = useSigma()
  const [draggedNode, setDraggedNode] = useState<string | null>(null)

  useEffect(() => {
    registerEvents({
      downNode: (e) => {
        setDraggedNode(e.node)
        sigma.getGraph().setNodeAttribute(e.node, 'highlighted', true)
      },
      mousemovebody: (e) => {
        if (!draggedNode) return
        const pos = sigma.viewportToGraph(e)
        sigma.getGraph().setNodeAttribute(draggedNode, 'x', pos.x)
        sigma.getGraph().setNodeAttribute(draggedNode, 'y', pos.y)
        e.preventSigmaDefault()
        e.original.preventDefault()
        e.original.stopPropagation()
      },
      mouseup: () => {
        if (draggedNode) {
          setDraggedNode(null)
          sigma.getGraph().removeNodeAttribute(draggedNode, 'highlighted')
        }
      },
      mousedown: (e) => {
        const mouseEvent = e.original as MouseEvent
        if (mouseEvent.buttons !== 0 && !sigma.getCustomBBox()) {
          sigma.setCustomBBox(sigma.getBBox())
        }
      },
    })
  }, [registerEvents, sigma, draggedNode])

  return null
}

function buildPublicGraph(data: GraphData): { graph: UndirectedGraph; colorMap: Map<string, string> } {
  const graph = new UndirectedGraph()
  let colorMap = new Map<string, string>()

  // Collect degrees first
  const degreeCount = new Map<string, number>()
  data.edges.forEach((e) => {
    degreeCount.set(e.source, (degreeCount.get(e.source) ?? 0) + 1)
    degreeCount.set(e.target, (degreeCount.get(e.target) ?? 0) + 1)
  })
  const maxDeg = Math.max(1, ...Array.from(degreeCount.values()))
  const minDeg = Math.min(...Array.from(degreeCount.values()))
  const degRange = maxDeg - minDeg || 1

  const added = new Set<string>()
  data.nodes.forEach((n) => {
    if (added.has(n.id)) return
    added.add(n.id)
    const label = String(n.properties?.entity_id ?? n.labels?.[0] ?? n.id)
    const entityType = (n.properties?.entity_type as string | undefined) ?? n.labels?.[0] ?? ''
    const { color, map } = resolveNodeColor(entityType, colorMap)
    colorMap = map
    const deg = degreeCount.get(n.id) ?? 0
    const size = minNodeSize + (maxNodeSize - minNodeSize) * Math.pow((deg - minDeg) / degRange, 0.5)
    graph.addNode(n.id, {
      label,
      color,
      x: Math.random(),
      y: Math.random(),
      size: Math.max(minNodeSize, size),
      borderColor: nodeBorderColor,
      borderSize: 0.2,
    })
  })

  data.edges.forEach((e) => {
    if (!graph.hasNode(e.source) || !graph.hasNode(e.target)) return
    if (!graph.hasEdge(e.source, e.target)) {
      try {
        graph.addEdge(e.source, e.target, {
          type: 'curvedNoArrow',
          size: 1.5,
          label: (e.properties?.keywords as string | undefined) ?? undefined,
        })
      } catch { /* duplicate edge */ }
    }
  })

  return { graph, colorMap }
}

function PublicGraphModal({ workspace, accent, onClose }: { workspace: string; accent: string; onClose: () => void }) {
  const [loading, setLoading] = useState(true)
  const [fullscreen, setFullscreen] = useState(false)
  const [sigmaGraph, setSigmaGraph] = useState<UndirectedGraph | null>(null)
  const [colorMap, setColorMap] = useState<Map<string, string>>(new Map())
  const [counts, setCounts] = useState({ nodes: 0, edges: 0 })

  useEffect(() => {
    fetchPublicGraph(workspace, 3000)
      .then((data) => {
        const { graph, colorMap: cm } = buildPublicGraph(data)
        setSigmaGraph(graph)
        setColorMap(cm)
        setCounts({ nodes: data.nodes.length, edges: data.edges.length })
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [workspace])

  const sigmaSettings = {
    allowInvalidContainer: true,
    defaultEdgeType: 'curvedNoArrow',
    renderEdgeLabels: false,
    defaultEdgeColor: '#52525b',
    labelColor: { color: labelColorDarkTheme },
    labelSize: 13,
    labelGridCellSize: 80,
    labelRenderedSizeThreshold: 10,
    edgeProgramClasses: { curvedNoArrow: createEdgeCurveProgram() },
    nodeProgramClasses: { default: NodeBorderProgram },
    defaultNodeType: 'default',
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    defaultDrawNodeHover: drawDarkNodeHover as any,
  }

  const containerClass = fullscreen ? 'fixed inset-0 z-[60]' : 'fixed inset-4 z-50 rounded-2xl overflow-hidden'

  return (
    <div className={`${containerClass} flex flex-col bg-zinc-950 shadow-2xl`}>
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 bg-zinc-900 border-b border-zinc-800 shrink-0">
        <div className="flex items-center gap-2">
          <NetworkIcon className="size-4" style={{ color: accent }} />
          <span className="text-sm font-semibold text-zinc-100">Đồ thị quan hệ</span>
          {!loading && sigmaGraph && (
            <span className="text-xs text-zinc-500 font-mono">{counts.nodes} nút · {counts.edges} cạnh</span>
          )}
        </div>
        <div className="flex items-center gap-1">
          <button onClick={() => setFullscreen(v => !v)} className="p-1.5 rounded-lg text-zinc-400 hover:text-zinc-100 hover:bg-zinc-800">
            {fullscreen ? <Minimize2Icon className="size-4" /> : <Maximize2Icon className="size-4" />}
          </button>
          <button onClick={onClose} className="p-1.5 rounded-lg text-zinc-400 hover:text-zinc-100 hover:bg-zinc-800">
            <XIcon className="size-4" />
          </button>
        </div>
      </div>

      {/* Body */}
      <div className="flex flex-1 overflow-hidden">
        {/* Graph canvas */}
        <div className="flex-1 relative overflow-hidden">
          {loading ? (
            <div className="flex flex-col items-center justify-center h-full gap-3">
              <Loader2Icon className="size-8 animate-spin text-zinc-500" />
              <span className="text-xs text-zinc-500">Đang tải đồ thị…</span>
            </div>
          ) : !sigmaGraph || counts.nodes === 0 ? (
            <div className="flex flex-col items-center justify-center h-full gap-2 text-zinc-500">
              <NetworkIcon className="size-12 opacity-20" />
              <span className="text-sm">Chưa có dữ liệu đồ thị</span>
            </div>
          ) : (
            <SigmaContainer graph={sigmaGraph} className="size-full !bg-zinc-950" settings={sigmaSettings}>
              <GraphDragEvents />
            </SigmaContainer>
          )}
        </div>

        {/* Legend panel */}
        {!loading && colorMap.size > 0 && (
          <div className="w-44 shrink-0 border-l border-zinc-800 bg-zinc-900/60 overflow-y-auto p-3">
            <div className="text-[10px] font-semibold text-zinc-500 uppercase tracking-wide mb-2">Chú giải</div>
            <div className="space-y-1.5">
              {Array.from(colorMap.entries()).map(([type, color]) => (
                <div key={type} className="flex items-center gap-2">
                  <div className="size-3 rounded-full shrink-0" style={{ backgroundColor: color }} />
                  <span className="text-[11px] text-zinc-300 truncate capitalize">{type}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Footer */}
      {!loading && counts.nodes > 0 && (
        <div className="px-4 py-1.5 text-[10px] text-zinc-600 bg-zinc-900/50 shrink-0 border-t border-zinc-800">
          Kéo để di chuyển · Cuộn để zoom
        </div>
      )}
    </div>
  )
}

function SourcesPanel({ workspace, accent, isAdmin }: { workspace: string; accent: string; isAdmin: boolean }) {
  const [docs, setDocs] = useState<PublicDocument[]>([])
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [viewDoc, setViewDoc] = useState<PublicDocument | null>(null)
  const [showGraph, setShowGraph] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  const fetchDocs = useCallback(() => {
    listPublicDocuments(workspace)
      .then(setDocs)
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [workspace])

  useEffect(() => {
    fetchDocs()
    const timer = setInterval(fetchDocs, 10_000)
    return () => clearInterval(timer)
  }, [fetchDocs])

  const handleUpload = async (file: File) => {
    setUploading(true)
    try {
      await uploadDocument(workspace, file)
      await fetchDocs()
    } catch { /* ignore */ }
    finally { setUploading(false) }
  }

  return (
    <div className="flex flex-col h-full">
      {/* Action bar */}
      <div className="px-3 py-2 border-b border-zinc-200 dark:border-zinc-800 shrink-0 flex flex-col gap-2">
        {isAdmin && (
          <>
            <input ref={fileRef} type="file" className="hidden" accept=".pdf,.docx,.doc,.txt" onChange={(e) => { const f = e.target.files?.[0]; if (f) handleUpload(f); e.target.value = '' }} />
            <button
              onClick={() => fileRef.current?.click()}
              disabled={uploading}
              className="w-full flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-lg text-xs border border-dashed border-zinc-300 dark:border-zinc-700 text-zinc-500 dark:text-zinc-400 hover:border-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-300 disabled:opacity-50 transition-colors"
            >
              {uploading ? <Loader2Icon className="size-3.5 animate-spin" /> : <UploadIcon className="size-3.5" />}
              {uploading ? 'Đang tải lên…' : 'Tải lên tài liệu'}
            </button>
          </>
        )}
        <button
          onClick={() => setShowGraph(true)}
          className="w-full flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-lg text-xs border border-zinc-200 dark:border-zinc-700 text-zinc-500 dark:text-zinc-400 hover:border-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-300 transition-colors"
          style={{ borderColor: `${accent}44`, color: accent }}
        >
          <NetworkIcon className="size-3.5" />
          Xem đồ thị quan hệ
        </button>
      </div>

      {/* Document list */}
      <div className="flex-1 overflow-y-auto py-1">
        {loading ? (
          <div className="flex justify-center py-8"><Loader2Icon className="size-4 animate-spin text-zinc-400" /></div>
        ) : docs.length === 0 ? (
          <div className="text-xs text-zinc-400 text-center py-8 px-3">Chưa có tài liệu nào</div>
        ) : (
          docs.map((doc) => {
            const filename = doc.file_path.split('/').pop() || doc.file_path
            return (
              <div key={doc.id} className="flex items-center gap-2 px-3 py-2 mx-1 rounded-lg hover:bg-zinc-50 dark:hover:bg-zinc-800/50 group">
                <DocStatusBadge status={doc.status} />
                <span className="flex-1 text-xs text-zinc-700 dark:text-zinc-300 truncate leading-snug" title={filename}>
                  {filename}
                </span>
                <button
                  onClick={() => setViewDoc(doc)}
                  className="shrink-0 p-1 rounded text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-300 opacity-0 group-hover:opacity-100 transition-opacity"
                  title="Xem nội dung"
                >
                  <EyeIcon className="size-3.5" />
                </button>
              </div>
            )
          })
        )}
      </div>

      {/* Count footer */}
      {!loading && docs.length > 0 && (
        <div className="border-t border-zinc-200 dark:border-zinc-800 px-3 py-2 shrink-0">
          <span className="text-[10px] text-zinc-400">{docs.filter(d => d.status === 'processed').length}/{docs.length} tài liệu đã xử lý</span>
        </div>
      )}

      {viewDoc && <DocViewModal doc={viewDoc} onClose={() => setViewDoc(null)} />}
      {showGraph && <PublicGraphModal workspace={workspace} accent={accent} onClose={() => setShowGraph(false)} />}
    </div>
  )
}

function SessionSidebar({ sessions, currentId, accent, onSelect, onNew, onHistory, loading }: {
  sessions: SessionSummary[]; currentId: string | null; accent: string
  onSelect: (id: string) => void; onNew: () => void; onHistory: () => void; loading: boolean
}) {
  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between px-3 py-3 border-b border-zinc-200 dark:border-zinc-800 shrink-0">
        <span className="text-xs font-semibold text-zinc-500 uppercase tracking-wide">Lịch sử</span>
        <button onClick={onNew} title="Cuộc trò chuyện mới" className="p-1.5 rounded-lg hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-500">
          <MessageSquarePlusIcon className="size-4" />
        </button>
      </div>
      <div className="flex-1 overflow-y-auto py-1">
        {loading && <div className="flex items-center justify-center py-8"><Loader2Icon className="size-4 animate-spin text-zinc-400" /></div>}
        {!loading && sessions.length === 0 && (
          <div className="text-xs text-zinc-400 text-center py-8 px-3">Chưa có cuộc trò chuyện nào</div>
        )}
        {sessions.map((s) => (
          <button
            key={s.id}
            onClick={() => onSelect(s.id)}
            className={`w-full text-left px-3 py-2.5 rounded-lg mx-1 my-0.5 transition-colors group ${s.id === currentId ? 'bg-zinc-100 dark:bg-zinc-800' : 'hover:bg-zinc-50 dark:hover:bg-zinc-800/50'}`}
            style={{ width: 'calc(100% - 8px)' }}
          >
            <div className="text-xs font-medium text-zinc-800 dark:text-zinc-200 truncate leading-snug">
              {s.title}
            </div>
            <div className="flex items-center gap-2 mt-0.5">
              <span className="text-[10px] text-zinc-400">{fmtDate(s.updated_at)}</span>
              {s.like_count > 0 && (
                <span className="text-[10px] text-emerald-600 flex items-center gap-0.5">
                  <ThumbsUpIcon className="size-2.5" />{s.like_count}
                </span>
              )}
              {s.dislike_count > 0 && (
                <span className="text-[10px] text-red-500 flex items-center gap-0.5">
                  <ThumbsDownIcon className="size-2.5" />{s.dislike_count}
                </span>
              )}
            </div>
          </button>
        ))}
      </div>
      <div className="border-t border-zinc-200 dark:border-zinc-800 p-2 shrink-0">
        <button onClick={onHistory} className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-xs text-zinc-500 hover:bg-zinc-100 dark:hover:bg-zinc-800">
          <HistoryIcon className="size-3.5" />Xem toàn bộ lịch sử
        </button>
      </div>
    </div>
  )
}

// ── Agentic step indicator ────────────────────────────────────────────────────

const STEP_LABELS: Record<string, string> = {
  analyzing: 'Phân tích câu hỏi',
  rewriting: 'Cải thiện truy vấn',
  retrieving: 'Tra cứu văn bản',
  synthesizing: 'Tổng hợp câu trả lời',
}

const STEP_ORDER = ['analyzing', 'rewriting', 'retrieving', 'synthesizing']

function AgenticStepsIndicator({
  steps,
  streaming,
  accent,
}: {
  steps: AgenticStepEvent[]
  streaming: boolean
  accent: string
}) {
  if (!steps.length) return null

  const doneSteps = new Set(steps.map((s) => s.step))
  const lastStep = steps[steps.length - 1]
  const rewrittenQuery = steps.find((s) => s.rewritten)?.rewritten
  const subQuestions = steps.find((s) => s.sub_questions?.length)?.sub_questions

  return (
    <div className="mb-3 text-xs">
      {/* Step pills */}
      <div className="flex flex-wrap gap-1.5 mb-2">
        {STEP_ORDER.map((step) => {
          const done = doneSteps.has(step)
          const isActive = streaming && lastStep.step === step
          return (
            <span
              key={step}
              className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full font-medium transition-all ${
                done
                  ? isActive
                    ? 'text-white'
                    : 'opacity-70'
                  : 'opacity-20 text-zinc-400'
              }`}
              style={done ? { backgroundColor: isActive ? accent : `${accent}30`, color: isActive ? '#fff' : accent } : undefined}
            >
              {isActive && streaming ? (
                <span className="size-1.5 rounded-full animate-pulse inline-block" style={{ backgroundColor: '#fff' }} />
              ) : done ? (
                <span className="size-1.5 rounded-full inline-block" style={{ backgroundColor: accent }} />
              ) : null}
              {STEP_LABELS[step] ?? step}
            </span>
          )
        })}
      </div>
      {/* Rewritten query */}
      {rewrittenQuery && rewrittenQuery !== lastStep.message && (
        <div className="pl-1 text-zinc-500 dark:text-zinc-400 italic leading-relaxed">
          <span className="not-italic font-medium text-zinc-400">Truy vấn:</span>{' '}
          {rewrittenQuery}
        </div>
      )}
      {/* Sub-questions for multi-hop */}
      {subQuestions && subQuestions.length > 0 && (
        <div className="pl-1 mt-1 space-y-0.5">
          {subQuestions.map((q, i) => (
            <div key={i} className="text-zinc-400 flex gap-1.5">
              <span className="shrink-0" style={{ color: accent }}>↳</span>
              <span>{q}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Message bubbles ───────────────────────────────────────────────────────────

function UserBubble({ content }: { content: string }) {
  return (
    <div className="flex justify-end mb-6">
      <div className="max-w-[75%] px-4 py-3 rounded-2xl rounded-tr-sm bg-zinc-900 dark:bg-zinc-100 text-white dark:text-zinc-900 text-sm leading-relaxed whitespace-pre-wrap">
        {content}
      </div>
    </div>
  )
}

function AssistantBubble({ msg, accent, onFeedback }: {
  msg: Message; accent: string; onFeedback: (mid: string, f: Feedback) => void
}) {
  const isLiked = msg.feedback === 'like'
  const isDisliked = msg.feedback === 'dislike'
  const [citeSelected, setCiteSelected] = useState<{ ref: ReferenceItem; idx: string } | null>(null)

  const refs = msg.references ?? []

  // Sequential citation map: "1","2","3"... → ref (order matches the refs array)
  const refByNum = useMemo(() => {
    const m = new Map<string, ReferenceItem>()
    refs.forEach((r, i) => m.set(String(i + 1), r))
    return m
  }, [refs])

  // Remap original reference_ids → sequential numbers for display.
  // LLM text may cite [12],[7] but we renumber them to [1],[2] matching the refs array order.
  const idRemap = useMemo(() => {
    const m = new Map<string, string>()
    refs.forEach((r, i) => {
      const id = String(r.reference_id ?? '')
      if (id) m.set(id, String(i + 1))
    })
    return m
  }, [refs])

  // Pre-process text: strip refs section + normalize markdown + renumber + convert to links
  const displayText = useMemo(() => {
    if (!msg.content) return ''
    let text = refs.length > 0 ? stripReferencesSection(msg.content) : msg.content
    // Collapse [N][N] duplicate citations the LLM sometimes emits
    text = text.replace(/(\[\d+\])(\s*\1)+/g, '$1')
    // Fix ###N. / ###Word (no space after #) → ### N. / ### Word
    text = text.replace(/^(#{1,6})([^\s#\n])/gm, '$1 $2')
    // Remap original reference_ids → sequential 1,2,3...
    if (idRemap.size > 0) {
      text = text.replace(/\[(\d+)\]/g, (match, num) => {
        const seq = idRemap.get(num)
        return seq ? `[${seq}]` : match
      })
    }
    // Convert bare [N] to markdown links only when a matching ref exists
    text = text.replace(/\[(\d+)\]/g, (match, num) => refByNum.has(num) ? `[${match}](#cite-${num})` : match)
    return text
  }, [msg.content, refs, refByNum, idRemap])

  // Markdown components
  const mdComponents = useMemo(() => ({
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    p: ({ children, ...props }: any) => <p className="mb-2 last:mb-0" {...props}>{children}</p>,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    h1: ({ children, ...props }: any) => <h1 className="text-base font-bold mt-3 mb-1" {...props}>{children}</h1>,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    h2: ({ children, ...props }: any) => <h2 className="text-sm font-bold mt-3 mb-1" {...props}>{children}</h2>,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    h3: ({ children, ...props }: any) => <h3 className="text-sm font-semibold mt-2 mb-1 text-zinc-700 dark:text-zinc-300" {...props}>{children}</h3>,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    ul: ({ children, ...props }: any) => <ul className="list-disc list-inside space-y-0.5 mb-2 pl-1" {...props}>{children}</ul>,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    ol: ({ children, ...props }: any) => <ol className="list-decimal list-inside space-y-0.5 mb-2 pl-1" {...props}>{children}</ol>,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    li: ({ children, ...props }: any) => <li className="text-zinc-700 dark:text-zinc-300" {...props}>{children}</li>,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    strong: ({ children, ...props }: any) => <strong className="font-semibold text-zinc-900 dark:text-zinc-100" {...props}>{children}</strong>,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    code: ({ children, inline, ...props }: any) => inline
      ? <code className="px-1 py-0.5 rounded bg-zinc-100 dark:bg-zinc-800 font-mono text-[0.88em] text-zinc-700 dark:text-zinc-300" {...props}>{children}</code>
      : <code className="block p-3 rounded-lg bg-zinc-100 dark:bg-zinc-800 font-mono text-xs overflow-x-auto mb-2" {...props}>{children}</code>,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    blockquote: ({ children, ...props }: any) => <blockquote className="border-l-2 border-zinc-300 dark:border-zinc-600 pl-3 italic text-zinc-600 dark:text-zinc-400 mb-2" {...props}>{children}</blockquote>,
    // [N] citations become links with href="#cite-N" — intercept here
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    a: ({ href, children }: any) => {
      if (href?.startsWith('#cite-')) {
        const num = href.slice(6)
        const ref = refByNum.get(num)
        if (ref) return (
          <button
            onClick={() => setCiteSelected({ ref, idx: num })}
            className="inline-flex items-center justify-center px-1 py-0.5 mx-0.5 rounded font-mono text-[0.78em] font-semibold leading-none transition-colors hover:opacity-80"
            style={{ backgroundColor: `${accent}20`, color: accent }}
            title={getFileName(ref.file_path)}
          >
            {children}
          </button>
        )
      }
      return <a href={href} target="_blank" rel="noreferrer" className="underline" style={{ color: accent }}>{children}</a>
    },
  }), [accent, refByNum, setCiteSelected])

  const agenticSteps = msg.agenticSteps ?? []

  return (
    <div className="flex gap-3 mb-6 items-start">
      <div className="size-7 rounded-full flex items-center justify-center shrink-0 mt-0.5 text-white" style={{ backgroundColor: accent }}>
        <BotIcon className="size-4" />
      </div>
      <div className="flex-1 min-w-0">
        {agenticSteps.length > 0 && (
          <AgenticStepsIndicator steps={agenticSteps} streaming={!!msg.streaming} accent={accent} />
        )}
        {msg.error ? (
          <div className="text-sm text-red-500 dark:text-red-400 leading-relaxed">{msg.content}</div>
        ) : msg.content ? (
          <>
            <div className="text-sm leading-[1.8] text-zinc-800 dark:text-zinc-200 prose prose-sm max-w-none dark:prose-invert prose-p:my-1 prose-headings:text-zinc-800 dark:prose-headings:text-zinc-200">
              <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
                {displayText}
              </ReactMarkdown>
              {msg.streaming && <span className="inline-block w-[2px] h-[14px] ml-0.5 bg-zinc-400 rounded animate-pulse align-text-bottom" />}
            </div>
            {!msg.streaming && (
              <>
                {refs.length > 0 && (
                  <SourcesRow references={refs} accent={accent} onCite={(ref, idx) => setCiteSelected({ ref, idx })} />
                )}
                {msg.serverId && (
                  <div className="flex items-center gap-1 mt-2">
                    <button
                      onClick={() => onFeedback(msg.serverId!, 'like')}
                      title="Hữu ích"
                      className={`p-1.5 rounded-lg transition-colors ${isLiked ? 'text-emerald-600 bg-emerald-50 dark:bg-emerald-900/30' : 'text-zinc-400 hover:text-emerald-600 hover:bg-zinc-100 dark:hover:bg-zinc-800'}`}
                    >
                      <ThumbsUpIcon className="size-3.5" />
                    </button>
                    <button
                      onClick={() => onFeedback(msg.serverId!, 'dislike')}
                      title="Không hữu ích"
                      className={`p-1.5 rounded-lg transition-colors ${isDisliked ? 'text-red-500 bg-red-50 dark:bg-red-900/30' : 'text-zinc-400 hover:text-red-500 hover:bg-zinc-100 dark:hover:bg-zinc-800'}`}
                    >
                      <ThumbsDownIcon className="size-3.5" />
                    </button>
                  </div>
                )}
              </>
            )}
          </>
        ) : (
          <div className="flex items-center gap-1.5 h-7">
            {[0, 150, 300].map((d) => <span key={d} className="size-2 rounded-full animate-bounce" style={{ backgroundColor: accent, animationDelay: `${d}ms` }} />)}
          </div>
        )}
      </div>
      <CitationModal
        open={citeSelected !== null}
        onClose={() => setCiteSelected(null)}
        reference={citeSelected?.ref ?? null}
        citationIndex={citeSelected?.idx ?? ''}
        query={msg.query ?? ''}
      />
    </div>
  )
}

// ── Suggested pills ───────────────────────────────────────────────────────────

function SuggestedPills({ questions, onSelect, accent, compact = false }: {
  questions: string[]; onSelect: (q: string) => void; accent: string; compact?: boolean
}) {
  if (!questions.length) return null
  const list = compact ? questions.slice(0, 4) : questions
  return (
    <div className={`flex flex-wrap gap-2 ${compact ? '' : 'justify-center mt-6'}`}>
      {list.map((q: string, i: number) => (
        <button key={i} onClick={() => onSelect(q)}
          className={`rounded-full border transition-colors ${compact ? 'px-3 py-1.5 text-xs' : 'px-4 py-2 text-sm'}`}
          style={{ borderColor: `${accent}88`, color: accent } as CSSProperties}
          onMouseEnter={(e) => { const el = e.currentTarget as HTMLButtonElement; el.style.backgroundColor = accent; el.style.color = '#fff' }}
          onMouseLeave={(e) => { const el = e.currentTarget as HTMLButtonElement; el.style.backgroundColor = ''; el.style.color = accent }}
        >
          {compact && q.length > 50 ? q.slice(0, 50) + '…' : q}
        </button>
      ))}
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function PublicChat() {
  const { workspace = 'default' } = useParams<{ workspace: string }>()
  const navigate = useNavigate()

  const [config, setConfig] = useState<PublicChatConfig>(DEFAULT_CONFIG)
  const [configLoading, setConfigLoading] = useState(true)

  const [sessions, setSessions] = useState<SessionSummary[]>([])
  const [sessionsLoading, setSessionsLoading] = useState(true)
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null)

  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [showConfig, setShowConfig] = useState(false)
  const [showSidebar, setShowSidebar] = useState(true)
  const [sidebarTab, setSidebarTab] = useState<'sessions' | 'sources'>('sessions')
  const [copied, setCopied] = useState(false)
  const [isAdmin, setIsAdmin] = useState(!!localStorage.getItem('LIGHTRAG-API-TOKEN'))
  const [showLogin, setShowLogin] = useState(false)

  const abortRef = useRef<AbortController | null>(null)
  const scrollContainerRef = useRef<HTMLDivElement>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const streamingMsgIdRef = useRef<string | null>(null)
  const isNearBottomRef = useRef(true)
  const rafIdRef = useRef<number | null>(null)

  const accent = config.accent_color || '#10b981'
  const title = config.title || `Trợ lý ${workspace}`
  const description = config.description || 'Hỏi bất kỳ điều gì để bắt đầu'

  // Load config
  useEffect(() => {
    setConfigLoading(true)
    getPublicChatConfig(workspace)
      .then((cfg) => setConfig({ ...DEFAULT_CONFIG, ...cfg }))
      .catch(() => setConfig(DEFAULT_CONFIG))
      .finally(() => setConfigLoading(false))
  }, [workspace])

  // Load sessions list
  const refreshSessions = useCallback(async () => {
    setSessionsLoading(true)
    try {
      const list = await listSessions(workspace)
      setSessions(list)
    } catch { /* ignore */ }
    finally { setSessionsLoading(false) }
  }, [workspace])

  useEffect(() => { refreshSessions() }, [refreshSessions])

  // Smart scroll
  useEffect(() => {
    const el = scrollContainerRef.current
    if (!el) return
    const onScroll = () => { isNearBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 120 }
    el.addEventListener('scroll', onScroll, { passive: true })
    return () => el.removeEventListener('scroll', onScroll)
  }, [])

  const scrollToBottom = useCallback((force = false) => {
    if (!force && !isNearBottomRef.current) return
    if (rafIdRef.current !== null) cancelAnimationFrame(rafIdRef.current)
    rafIdRef.current = requestAnimationFrame(() => {
      const el = scrollContainerRef.current
      if (el) el.scrollTop = el.scrollHeight
      rafIdRef.current = null
    })
  }, [])

  useEffect(() => { if (streaming) scrollToBottom() }, [messages, streaming, scrollToBottom])

  const resizeTextarea = () => {
    const el = textareaRef.current; if (!el) return
    el.style.height = 'auto'; el.style.height = `${Math.min(el.scrollHeight, 200)}px`
  }

  // Load session messages
  const loadSession = useCallback(async (sid: string) => {
    if (streaming) return
    try {
      const detail = await import('@/api/publicChatSessions').then(m => m.getSession(workspace, sid))
      setCurrentSessionId(sid)
      setMessages(
        detail.messages.map((m) => ({
          id: uid(),
          serverId: m.id,
          role: m.role as Role,
          content: m.content,
          feedback: m.feedback,
          references: m.references as ReferenceItem[] | undefined,
        }))
      )
      isNearBottomRef.current = true
      scrollToBottom(true)
    } catch { /* ignore */ }
  }, [workspace, streaming, scrollToBottom])

  // New session
  const newSession = useCallback(async () => {
    if (streaming) return
    setCurrentSessionId(null)
    setMessages([])
    setInput('')
  }, [streaming])

  // Ensure session exists before first message
  const ensureSession = useCallback(async (): Promise<string> => {
    if (currentSessionId) return currentSessionId
    const { id } = await createSession(workspace)
    setCurrentSessionId(id)
    refreshSessions()
    return id
  }, [currentSessionId, workspace, refreshSessions])

  // Send message
  const send = useCallback(async (text?: string) => {
    const question = (text ?? input).trim()
    if (!question || streaming) return

    const history = messages.flatMap((m: Message) => {
      if (m.role === 'user') return [{ role: 'user', content: m.content }]
      if (m.role === 'assistant' && !m.error) return [{ role: 'assistant', content: m.content }]
      return []
    })

    const userLocalId = uid()
    const assistantId = uid()
    setMessages((prev) => [
      ...prev,
      { id: userLocalId, role: 'user', content: question },
      { id: assistantId, role: 'assistant', content: '', streaming: true, query: question },
    ])
    setInput('')
    setStreaming(true)
    isNearBottomRef.current = true
    scrollToBottom(true)
    if (textareaRef.current) textareaRef.current.style.height = 'auto'

    // Ensure session + save user message
    const sid = await ensureSession()
    try {
      const saved = await addMessage(workspace, sid, { role: 'user', content: question })
      setMessages((prev) => prev.map((m: Message) => m.id === userLocalId ? { ...m, serverId: saved.id } : m))
    } catch { /* non-fatal */ }

    const controller = new AbortController()
    abortRef.current = controller
    let finalContent = ''
    let finalRefs: ReferenceItem[] = []

    await streamPublicChat(
      { query: question, mode: config.mode, top_k: config.top_k, workspace, history_messages: history },
      (chunk) => {
        finalContent += chunk
        setMessages((prev) => prev.map((m: Message) => m.id === assistantId ? { ...m, content: m.content + chunk } : m))
      },
      async () => {
        setMessages((prev) => prev.map((m: Message) => m.id === assistantId ? { ...m, streaming: false } : m))
        setStreaming(false)
        streamingMsgIdRef.current = null
        // Save assistant message
        try {
          const saved = await addMessage(workspace, sid, {
            role: 'assistant',
            content: finalContent,
            references: finalRefs as Record<string, unknown>[],
          })
          setMessages((prev) => prev.map((m: Message) => m.id === assistantId ? { ...m, serverId: saved.id } : m))
          refreshSessions()
        } catch { /* non-fatal */ }
      },
      (err) => {
        setMessages((prev) => prev.map((m: Message) => m.id === assistantId ? { ...m, content: err, streaming: false, error: true } : m))
        setStreaming(false)
        streamingMsgIdRef.current = null
      },
      controller.signal,
      (refs) => {
        finalRefs = refs
        setMessages((prev) => prev.map((m: Message) => m.id === assistantId ? { ...m, references: refs } : m))
      },
      (stepEvent) => {
        setMessages((prev) => prev.map((m: Message) =>
          m.id === assistantId
            ? { ...m, agenticSteps: [...(m.agenticSteps ?? []), stepEvent] }
            : m
        ))
      }
    )
  }, [input, streaming, messages, config, workspace, ensureSession, refreshSessions, scrollToBottom])

  // Feedback
  const handleFeedback = useCallback(async (serverId: string, feedback: Feedback) => {
    if (!currentSessionId) return
    try {
      const updated = await setFeedback(workspace, currentSessionId, serverId, feedback)
      setMessages((prev) => prev.map((m: Message) => m.serverId === serverId ? { ...m, feedback: updated.feedback } : m))
      refreshSessions()
    } catch { /* ignore */ }
  }, [workspace, currentSessionId, refreshSessions])

  const stop = () => {
    abortRef.current?.abort()
    if (streamingMsgIdRef.current) {
      const id = streamingMsgIdRef.current
      setMessages((prev) => prev.map((m: Message) => m.id === id ? { ...m, streaming: false } : m))
    }
    setStreaming(false)
  }

  const copyLink = () => {
    navigator.clipboard.writeText(window.location.href).then(() => { setCopied(true); setTimeout(() => setCopied(false), 2000) })
  }

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() }
  }

  const isEmpty = messages.length === 0

  return (
    <div className="h-screen overflow-hidden bg-white dark:bg-zinc-950 flex flex-col">
      {/* Header */}
      <header className="sticky top-0 z-40 bg-white/80 dark:bg-zinc-950/80 backdrop-blur border-b border-zinc-200 dark:border-zinc-800 shrink-0">
        <div className="h-12 flex items-center justify-between px-4">
          <div className="flex items-center gap-2">
            <button onClick={() => setShowSidebar((v) => !v)} className="p-1.5 rounded-lg text-zinc-400 hover:bg-zinc-100 dark:hover:bg-zinc-800" title="Lịch sử">
              <PanelLeftIcon className="size-4" />
            </button>
            <ZapIcon className="size-4" style={{ color: accent }} />
            <span className="font-semibold text-sm">{title}</span>
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-zinc-100 dark:bg-zinc-800 text-zinc-500 font-mono hidden sm:inline">{workspace}</span>
          </div>
          <div className="flex items-center gap-1">
            <button onClick={() => { newSession() }} title="Cuộc trò chuyện mới" className="p-2 rounded-lg text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800">
              <MessageSquarePlusIcon className="size-4" />
            </button>
            <button onClick={copyLink} title="Sao chép link" className="p-2 rounded-lg text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800">
              {copied ? <CheckIcon className="size-4 text-emerald-500" /> : (
                <svg className="size-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101" />
                  <path strokeLinecap="round" strokeLinejoin="round" d="M10.172 13.828a4 4 0 015.656 0l4 4a4 4 0 01-5.656 5.656l-1.101-1.102" />
                </svg>
              )}
            </button>
            <button onClick={() => setShowConfig(true)} title="Cấu hình" className="p-2 rounded-lg text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800">
              <Settings2Icon className="size-4" />
            </button>
            {isAdmin ? (
              <button
                onClick={() => { useAuthStore.getState().logout(); setIsAdmin(false) }}
                title="Đăng xuất"
                className="p-2 rounded-lg text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800"
              >
                <LogOutIcon className="size-4" />
              </button>
            ) : (
              <button
                onClick={() => setShowLogin(true)}
                title="Đăng nhập quản trị"
                className="p-2 rounded-lg text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800"
              >
                <LogInIcon className="size-4" />
              </button>
            )}
          </div>
        </div>
      </header>

      {/* Body: sidebar + chat */}
      <div className="flex flex-1 overflow-hidden">
        {/* Sidebar */}
        {showSidebar && (
          <div className="w-60 shrink-0 border-r border-zinc-200 dark:border-zinc-800 overflow-hidden flex flex-col bg-white dark:bg-zinc-950">
            {/* Tab bar */}
            <div className="flex shrink-0 border-b border-zinc-200 dark:border-zinc-800">
              {(['sessions', 'sources'] as const).map((tab) => (
                <button
                  key={tab}
                  onClick={() => setSidebarTab(tab)}
                  className={`flex-1 py-2.5 text-[11px] font-medium transition-colors ${sidebarTab === tab ? 'border-b-2 text-zinc-900 dark:text-zinc-100' : 'text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-300'}`}
                  style={sidebarTab === tab ? { borderColor: accent } as CSSProperties : undefined}
                >
                  {tab === 'sessions' ? 'Hội thoại' : 'Nguồn'}
                </button>
              ))}
            </div>
            {sidebarTab === 'sessions' ? (
              <SessionSidebar
                sessions={sessions}
                currentId={currentSessionId}
                accent={accent}
                onSelect={loadSession}
                onNew={newSession}
                onHistory={() => navigate(`/public-chat/${workspace}/history`)}
                loading={sessionsLoading}
              />
            ) : (
              <SourcesPanel workspace={workspace} accent={accent} isAdmin={isAdmin} />
            )}
          </div>
        )}

        {/* Chat area */}
        <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
          <div ref={scrollContainerRef} className="flex-1 overflow-y-auto">
            <div className="max-w-3xl mx-auto px-4 py-8">
              {configLoading ? (
                <div className="flex items-center justify-center min-h-[60vh]"><Loader2Icon className="size-6 animate-spin text-zinc-400" /></div>
              ) : isEmpty ? (
                <div className="flex flex-col items-center justify-center min-h-[60vh] text-center">
                  <div className="size-16 rounded-2xl flex items-center justify-center mb-6 shadow-lg" style={{ backgroundColor: accent }}>
                    <BotIcon className="size-8 text-white" />
                  </div>
                  <h1 className="text-2xl font-bold text-zinc-900 dark:text-zinc-100 mb-2">{title}</h1>
                  <p className="text-zinc-500 dark:text-zinc-400 text-sm max-w-md">{description}</p>
                  <SuggestedPills questions={config.suggested_questions} onSelect={(q) => send(q)} accent={accent} />
                </div>
              ) : (
                messages.map((msg) =>
                  msg.role === 'user'
                    ? <UserBubble key={msg.id} content={msg.content} />
                    : <AssistantBubble key={msg.id} msg={msg} accent={accent} onFeedback={handleFeedback} />
                )
              )}
              <div ref={bottomRef} />
            </div>
          </div>

          {/* Compact suggested pills */}
          {!isEmpty && config.suggested_questions.length > 0 && !streaming && (
            <div className="max-w-3xl mx-auto w-full px-4 pb-2">
              <SuggestedPills questions={config.suggested_questions} onSelect={(q) => send(q)} accent={accent} compact />
            </div>
          )}

          {/* Input bar */}
          <div className="sticky bottom-0 bg-white/80 dark:bg-zinc-950/80 backdrop-blur border-t border-zinc-200 dark:border-zinc-800">
            <div className="max-w-3xl mx-auto px-4 py-3">
              <div className="flex items-end gap-2 rounded-2xl border border-zinc-200 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-900 px-4 py-3 focus-within:border-transparent focus-within:ring-2 transition-all" style={{ '--tw-ring-color': accent } as CSSProperties}>
                <textarea
                  ref={textareaRef} value={input}
                  onChange={(e) => { setInput(e.target.value); resizeTextarea() }}
                  onKeyDown={handleKeyDown}
                  placeholder="Nhập câu hỏi… (Enter gửi, Shift+Enter xuống dòng)"
                  className="flex-1 resize-none bg-transparent text-sm text-zinc-900 dark:text-zinc-100 placeholder-zinc-400 focus:outline-none min-h-[24px] max-h-[200px] leading-relaxed"
                  rows={1}
                />
                {streaming ? (
                  <button onClick={stop} className="shrink-0 size-8 rounded-full flex items-center justify-center text-zinc-400 hover:text-red-500" title="Dừng">
                    <StopCircleIcon className="size-5" />
                  </button>
                ) : (
                  <button onClick={() => send()} disabled={!input.trim()} className="shrink-0 size-8 rounded-full flex items-center justify-center text-white disabled:opacity-40" style={{ backgroundColor: input.trim() ? accent : '#9ca3af' } as CSSProperties}>
                    <SendIcon className="size-4" />
                  </button>
                )}
              </div>
              <p className="text-[10px] text-zinc-400 text-center mt-2">
                Powered by LightRAG · workspace: <span className="font-mono">{workspace}</span>
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Modals */}
      {showConfig && <ConfigPanel workspace={workspace} config={config} onSaved={setConfig} onClose={() => setShowConfig(false)} />}
      {showLogin && (
        <PublicLoginModal
          onClose={() => setShowLogin(false)}
          onSuccess={() => setIsAdmin(true)}
        />
      )}
    </div>
  )
}
