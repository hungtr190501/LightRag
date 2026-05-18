import {
  type CSSProperties,
  type ReactNode,
  type KeyboardEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { streamPublicChat, type ReferenceItem } from '@/api/publicChatApi'
import { getPublicChatConfig, updatePublicChatConfig, type PublicChatConfig } from '@/api/workspace'
import {
  listSessions,
  createSession,
  addMessage,
  setFeedback,
  type SessionSummary,
  type Feedback,
} from '@/api/publicChatSessions'
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
} from 'lucide-react'

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

// ── Markdown-lite ─────────────────────────────────────────────────────────────

function renderMarkdownLite(text: string): ReactNode[] {
  const lines = text.split('\n')
  return lines.map((line, li) => {
    const parts: ReactNode[] = []
    const re = /(\*\*(.+?)\*\*|\*(.+?)\*|`(.+?)`)/g
    let last = 0; let m: RegExpExecArray | null; let key = 0
    while ((m = re.exec(line)) !== null) {
      if (m.index > last) parts.push(line.slice(last, m.index))
      if (m[2]) parts.push(<strong key={key++}>{m[2]}</strong>)
      else if (m[3]) parts.push(<em key={key++}>{m[3]}</em>)
      else if (m[4]) parts.push(<code key={key++} className="px-1 py-0.5 rounded bg-black/10 dark:bg-white/10 font-mono text-[0.88em]">{m[4]}</code>)
      last = m.index + m[0].length
    }
    if (last < line.length) parts.push(line.slice(last))
    return <span key={li}>{parts}{li < lines.length - 1 && <br />}</span>
  })
}

// ── Sources row ───────────────────────────────────────────────────────────────

function SourcesRow({ references, query, accent }: { references: ReferenceItem[]; query: string; accent: string }) {
  const [open, setOpen] = useState(false)
  const [selected, setSelected] = useState<{ ref: ReferenceItem; idx: string } | null>(null)
  if (!references.length) return null
  return (
    <>
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
              const idx = ref.reference_id ?? String(i + 1)
              return (
                <button
                  key={ref.chunk_id ?? i}
                  onClick={() => setSelected({ ref, idx })}
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
      <CitationModal open={selected !== null} onClose={() => setSelected(null)} reference={selected?.ref ?? null} citationIndex={selected?.idx ?? ''} query={query} />
    </>
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

  return (
    <div className="flex gap-3 mb-6 items-start">
      <div className="size-7 rounded-full flex items-center justify-center shrink-0 mt-0.5 text-white" style={{ backgroundColor: accent }}>
        <BotIcon className="size-4" />
      </div>
      <div className="flex-1 min-w-0">
        {msg.error ? (
          <div className="text-sm text-red-500 dark:text-red-400 leading-relaxed">{msg.content}</div>
        ) : msg.content ? (
          <>
            <div className="text-sm leading-[1.8] text-zinc-800 dark:text-zinc-200">
              {renderMarkdownLite(msg.content)}
              {msg.streaming && <span className="inline-block w-[2px] h-[14px] ml-0.5 bg-zinc-400 rounded animate-pulse align-text-bottom" />}
            </div>
            {!msg.streaming && (
              <>
                {msg.references && msg.references.length > 0 && (
                  <SourcesRow references={msg.references} query={msg.query ?? ''} accent={accent} />
                )}
                {/* Like / Dislike */}
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
  const [copied, setCopied] = useState(false)

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
          </div>
        </div>
      </header>

      {/* Body: sidebar + chat */}
      <div className="flex flex-1 overflow-hidden">
        {/* Sidebar */}
        {showSidebar && (
          <div className="w-60 shrink-0 border-r border-zinc-200 dark:border-zinc-800 overflow-hidden flex flex-col bg-white dark:bg-zinc-950">
            <SessionSidebar
              sessions={sessions}
              currentId={currentSessionId}
              accent={accent}
              onSelect={loadSession}
              onNew={newSession}
              onHistory={() => navigate(`/public-chat/${workspace}/history`)}
              loading={sessionsLoading}
            />
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
    </div>
  )
}
