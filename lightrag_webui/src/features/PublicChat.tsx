import { type CSSProperties, type ReactNode, type KeyboardEvent, useCallback, useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { streamPublicChat } from '@/api/publicChatApi'
import { getPublicChatConfig, updatePublicChatConfig, type PublicChatConfig } from '@/api/workspace'
import {
  BotIcon,
  SendIcon,
  Settings2Icon,
  TrashIcon,
  XIcon,
  PlusIcon,
  ZapIcon,
  StopCircleIcon,
  CheckIcon,
  Loader2Icon,
} from 'lucide-react'

// ── Types ────────────────────────────────────────────────────────────────────

type Role = 'user' | 'assistant'

interface Message {
  id: string
  role: Role
  content: string
  streaming?: boolean
  error?: boolean
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

// ── Markdown-lite renderer ───────────────────────────────────────────────────

function renderMarkdownLite(text: string): ReactNode[] {
  const lines = text.split('\n')
  return lines.map((line, li) => {
    const parts: ReactNode[] = []
    const re = /(\*\*(.+?)\*\*|\*(.+?)\*|`(.+?)`)/g
    let last = 0
    let m: RegExpExecArray | null
    let key = 0
    while ((m = re.exec(line)) !== null) {
      if (m.index > last) parts.push(line.slice(last, m.index))
      if (m[2]) parts.push(<strong key={key++}>{m[2]}</strong>)
      else if (m[3]) parts.push(<em key={key++}>{m[3]}</em>)
      else if (m[4])
        parts.push(
          <code
            key={key++}
            className="px-1 py-0.5 rounded bg-black/10 dark:bg-white/10 font-mono text-[0.88em]"
          >
            {m[4]}
          </code>
        )
      last = m.index + m[0].length
    }
    if (last < line.length) parts.push(line.slice(last))
    return (
      <span key={li}>
        {parts}
        {li < lines.length - 1 && <br />}
      </span>
    )
  })
}

// ── Config Panel ─────────────────────────────────────────────────────────────

function ConfigPanel({
  workspace,
  config,
  onSaved,
  onClose,
}: {
  workspace: string
  config: PublicChatConfig
  onSaved: (c: PublicChatConfig) => void
  onClose: () => void
}) {
  const [draft, setDraft] = useState<PublicChatConfig>({ ...config })
  const [newQ, setNewQ] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const set = <K extends keyof PublicChatConfig>(k: K, v: PublicChatConfig[K]) =>
    setDraft((d) => ({ ...d, [k]: v }))

  const addQuestion = () => {
    const q = newQ.trim()
    if (!q) return
    setDraft((d) => ({ ...d, suggested_questions: [...d.suggested_questions, q] }))
    setNewQ('')
  }

  const removeQuestion = (i: number) =>
    setDraft((d) => ({
      ...d,
      suggested_questions: d.suggested_questions.filter((_: string, idx: number) => idx !== i),
    }))

  const save = async () => {
    setSaving(true)
    setError('')
    try {
      const saved = await updatePublicChatConfig(workspace, draft)
      onSaved(saved)
      onClose()
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? e?.message ?? 'Lỗi lưu cấu hình')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
      <div className="w-full max-w-lg bg-white dark:bg-zinc-900 rounded-2xl shadow-2xl overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-zinc-200 dark:border-zinc-700">
          <h2 className="font-semibold text-base">Cấu hình trang chat</h2>
          <button
            onClick={onClose}
            className="p-1 rounded-lg hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-500"
          >
            <XIcon className="size-4" />
          </button>
        </div>

        <div className="px-6 py-5 space-y-5 max-h-[70vh] overflow-y-auto">
          {error && (
            <div className="text-sm text-red-500 bg-red-50 dark:bg-red-950 px-3 py-2 rounded-lg">{error}</div>
          )}

          {/* Title */}
          <div>
            <label className="block text-xs font-medium text-zinc-500 mb-1.5">Tiêu đề hiển thị</label>
            <input
              className="w-full rounded-lg border border-zinc-200 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-800 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
              value={draft.title}
              onChange={(e) => set('title', e.target.value)}
              placeholder={`Trợ lý ${workspace}`}
            />
          </div>

          {/* Description */}
          <div>
            <label className="block text-xs font-medium text-zinc-500 mb-1.5">Mô tả ngắn</label>
            <input
              className="w-full rounded-lg border border-zinc-200 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-800 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
              value={draft.description}
              onChange={(e) => set('description', e.target.value)}
              placeholder="Hỏi bất kỳ điều gì…"
            />
          </div>

          {/* Mode + Top-K */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-medium text-zinc-500 mb-1.5">Query mode</label>
              <select
                className="w-full rounded-lg border border-zinc-200 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-800 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
                value={draft.mode}
                onChange={(e) => set('mode', e.target.value as PublicChatConfig['mode'])}
              >
                <option value="local">local</option>
                <option value="global">global</option>
                <option value="hybrid">hybrid</option>
                <option value="mix">mix</option>
                <option value="naive">naive</option>
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-zinc-500 mb-1.5">Top-K</label>
              <input
                type="number"
                min={1}
                max={100}
                className="w-full rounded-lg border border-zinc-200 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-800 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
                value={draft.top_k}
                onChange={(e) => set('top_k', Number(e.target.value))}
              />
            </div>
          </div>

          {/* Accent color */}
          <div>
            <label className="block text-xs font-medium text-zinc-500 mb-1.5">Màu chủ đạo</label>
            <div className="flex items-center gap-3">
              <input
                type="color"
                className="size-9 rounded-lg border border-zinc-200 dark:border-zinc-700 cursor-pointer"
                value={draft.accent_color}
                onChange={(e) => set('accent_color', e.target.value)}
              />
              <span className="text-sm text-zinc-500 font-mono">{draft.accent_color}</span>
            </div>
          </div>

          {/* Suggested questions */}
          <div>
            <label className="block text-xs font-medium text-zinc-500 mb-1.5">
              Câu hỏi gợi ý ({draft.suggested_questions.length})
            </label>
            <div className="space-y-2">
              {draft.suggested_questions.map((q: string, i: number) => (
                <div
                  key={i}
                  className="flex items-center gap-2 p-2.5 rounded-lg bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 text-sm"
                >
                  <span className="flex-1 truncate text-xs">{q}</span>
                  <button
                    onClick={() => removeQuestion(i)}
                    className="text-zinc-400 hover:text-red-500 shrink-0"
                  >
                    <XIcon className="size-3.5" />
                  </button>
                </div>
              ))}
              <div className="flex gap-2">
                <input
                  className="flex-1 rounded-lg border border-zinc-200 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-800 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
                  placeholder="Thêm câu hỏi gợi ý…"
                  value={newQ}
                  onChange={(e) => setNewQ(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && addQuestion()}
                />
                <button
                  onClick={addQuestion}
                  className="px-3 py-2 rounded-lg bg-emerald-500 hover:bg-emerald-600 text-white flex items-center gap-1"
                >
                  <PlusIcon className="size-4" />
                </button>
              </div>
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-zinc-200 dark:border-zinc-700">
          <button
            onClick={onClose}
            className="px-4 py-2 rounded-lg text-sm text-zinc-600 dark:text-zinc-400 hover:bg-zinc-100 dark:hover:bg-zinc-800"
          >
            Hủy
          </button>
          <button
            onClick={save}
            disabled={saving}
            className="px-4 py-2 rounded-lg text-sm bg-emerald-500 hover:bg-emerald-600 disabled:opacity-60 text-white flex items-center gap-1.5"
          >
            {saving ? <Loader2Icon className="size-4 animate-spin" /> : <CheckIcon className="size-4" />}
            Lưu
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Message bubbles ──────────────────────────────────────────────────────────

function UserBubble({ content }: { content: string }) {
  return (
    <div className="flex justify-end mb-6">
      <div className="max-w-[75%] px-4 py-3 rounded-2xl rounded-tr-sm bg-zinc-900 dark:bg-zinc-100 text-white dark:text-zinc-900 text-sm leading-relaxed whitespace-pre-wrap">
        {content}
      </div>
    </div>
  )
}

function AssistantBubble({
  content,
  streaming,
  error,
  accent,
}: {
  content: string
  streaming?: boolean
  error?: boolean
  accent: string
}) {
  return (
    <div className="flex gap-3 mb-6 items-start">
      <div
        className="size-7 rounded-full flex items-center justify-center shrink-0 mt-0.5 text-white"
        style={{ backgroundColor: accent }}
      >
        <BotIcon className="size-4" />
      </div>
      <div className="flex-1 min-w-0">
        {error ? (
          <div className="text-sm text-red-500 dark:text-red-400 leading-relaxed">{content}</div>
        ) : content ? (
          <div className="text-sm leading-[1.8] text-zinc-800 dark:text-zinc-200">
            {renderMarkdownLite(content)}
            {streaming && (
              <span className="inline-block w-[2px] h-[14px] ml-0.5 bg-zinc-400 dark:bg-zinc-500 rounded animate-pulse align-text-bottom" />
            )}
          </div>
        ) : (
          <div className="flex items-center gap-1.5 h-7">
            <span className="size-2 rounded-full animate-bounce [animation-delay:0ms]" style={{ backgroundColor: accent }} />
            <span className="size-2 rounded-full animate-bounce [animation-delay:150ms]" style={{ backgroundColor: accent }} />
            <span className="size-2 rounded-full animate-bounce [animation-delay:300ms]" style={{ backgroundColor: accent }} />
          </div>
        )}
      </div>
    </div>
  )
}

// ── Suggested pills ──────────────────────────────────────────────────────────

function SuggestedPills({
  questions,
  onSelect,
  accent,
  compact = false,
}: {
  questions: string[]
  onSelect: (q: string) => void
  accent: string
  compact?: boolean
}) {
  if (!questions.length) return null
  const list = compact ? questions.slice(0, 4) : questions
  return (
    <div className={`flex flex-wrap gap-2 ${compact ? '' : 'justify-center mt-6'}`}>
      {list.map((q, i) => (
        <button
          key={i}
          onClick={() => onSelect(q)}
          className={`rounded-full border transition-colors ${compact ? 'px-3 py-1.5 text-xs' : 'px-4 py-2 text-sm'}`}
          style={{ borderColor: `${accent}88`, color: accent } as CSSProperties}
          onMouseEnter={(e) => {
            const el = e.currentTarget as HTMLButtonElement
            el.style.backgroundColor = accent
            el.style.color = '#fff'
          }}
          onMouseLeave={(e) => {
            const el = e.currentTarget as HTMLButtonElement
            el.style.backgroundColor = ''
            el.style.color = accent
          }}
        >
          {compact && q.length > 50 ? q.slice(0, 50) + '…' : q}
        </button>
      ))}
    </div>
  )
}

// ── Main component ───────────────────────────────────────────────────────────

export default function PublicChat() {
  const { workspace = 'default' } = useParams<{ workspace: string }>()

  const [config, setConfig] = useState<PublicChatConfig>(DEFAULT_CONFIG)
  const [configLoading, setConfigLoading] = useState(true)
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [showConfig, setShowConfig] = useState(false)
  const [copied, setCopied] = useState(false)

  const abortRef = useRef<AbortController | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const streamingMsgIdRef = useRef<string | null>(null)

  const accent = config.accent_color || '#10b981'
  const title = config.title || `Trợ lý ${workspace}`
  const description = config.description || 'Hỏi bất kỳ điều gì để bắt đầu'

  // Load config from API on mount
  useEffect(() => {
    setConfigLoading(true)
    getPublicChatConfig(workspace)
      .then((cfg) => setConfig({ ...DEFAULT_CONFIG, ...cfg }))
      .catch(() => setConfig(DEFAULT_CONFIG))
      .finally(() => setConfigLoading(false))
  }, [workspace])

  // Auto-scroll
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // Auto-resize textarea
  const resizeTextarea = () => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`
  }

  const send = useCallback(
    async (text?: string) => {
      const question = (text ?? input).trim()
      if (!question || streaming) return

      const history = messages.flatMap((m) => {
        if (m.role === 'user') return [{ role: 'user', content: m.content }]
        if (m.role === 'assistant' && !m.error) return [{ role: 'assistant', content: m.content }]
        return []
      })

      const userMsg: Message = { id: uid(), role: 'user', content: question }
      const assistantId = uid()
      const assistantMsg: Message = { id: assistantId, role: 'assistant', content: '', streaming: true }

      streamingMsgIdRef.current = assistantId
      setMessages((prev) => [...prev, userMsg, assistantMsg])
      setInput('')
      setStreaming(true)

      if (textareaRef.current) textareaRef.current.style.height = 'auto'

      const controller = new AbortController()
      abortRef.current = controller

      await streamPublicChat(
        {
          query: question,
          mode: config.mode,
          top_k: config.top_k,
          workspace,
          history_messages: history,
        },
        (chunk) => {
          setMessages((prev) =>
            prev.map((m) => (m.id === assistantId ? { ...m, content: m.content + chunk } : m))
          )
        },
        () => {
          setMessages((prev) =>
            prev.map((m) => (m.id === assistantId ? { ...m, streaming: false } : m))
          )
          setStreaming(false)
          streamingMsgIdRef.current = null
        },
        (err) => {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId ? { ...m, content: err, streaming: false, error: true } : m
            )
          )
          setStreaming(false)
          streamingMsgIdRef.current = null
        },
        controller.signal
      )
    },
    [input, streaming, messages, config, workspace]
  )

  const stop = () => {
    abortRef.current?.abort()
    if (streamingMsgIdRef.current) {
      const id = streamingMsgIdRef.current
      setMessages((prev) => prev.map((m: Message) => (m.id === id ? { ...m, streaming: false } : m)))
    }
    setStreaming(false)
  }

  const clear = () => {
    stop()
    setMessages([])
    setInput('')
  }

  const copyLink = () => {
    navigator.clipboard.writeText(window.location.href).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
  }

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  const isEmpty = messages.length === 0

  return (
    <div className="min-h-screen bg-white dark:bg-zinc-950 flex flex-col">
      {/* Header */}
      <header className="sticky top-0 z-40 bg-white/80 dark:bg-zinc-950/80 backdrop-blur border-b border-zinc-200 dark:border-zinc-800">
        <div className="max-w-3xl mx-auto px-4 h-12 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <ZapIcon className="size-4" style={{ color: accent }} />
            <span className="font-semibold text-sm">{title}</span>
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-zinc-100 dark:bg-zinc-800 text-zinc-500 font-mono">
              {workspace}
            </span>
          </div>
          <div className="flex items-center gap-1">
            {messages.length > 0 && (
              <button
                onClick={clear}
                title="Xoá hội thoại"
                className="p-2 rounded-lg text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800"
              >
                <TrashIcon className="size-4" />
              </button>
            )}
            <button
              onClick={copyLink}
              title="Sao chép link"
              className="p-2 rounded-lg text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800"
            >
              {copied ? (
                <CheckIcon className="size-4 text-emerald-500" />
              ) : (
                <svg className="size-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101" />
                  <path strokeLinecap="round" strokeLinejoin="round" d="M10.172 13.828a4 4 0 015.656 0l4 4a4 4 0 01-5.656 5.656l-1.101-1.102" />
                </svg>
              )}
            </button>
            <button
              onClick={() => setShowConfig(true)}
              title="Cấu hình"
              className="p-2 rounded-lg text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800"
            >
              <Settings2Icon className="size-4" />
            </button>
          </div>
        </div>
      </header>

      {/* Messages area */}
      <div className="flex-1 overflow-y-auto">
        <div className="max-w-3xl mx-auto px-4 py-8">
          {configLoading ? (
            <div className="flex items-center justify-center min-h-[60vh]">
              <Loader2Icon className="size-6 animate-spin text-zinc-400" />
            </div>
          ) : isEmpty ? (
            <div className="flex flex-col items-center justify-center min-h-[60vh] text-center">
              <div
                className="size-16 rounded-2xl flex items-center justify-center mb-6 shadow-lg"
                style={{ backgroundColor: accent }}
              >
                <BotIcon className="size-8 text-white" />
              </div>
              <h1 className="text-2xl font-bold text-zinc-900 dark:text-zinc-100 mb-2">{title}</h1>
              <p className="text-zinc-500 dark:text-zinc-400 text-sm max-w-md">{description}</p>
              <SuggestedPills
                questions={config.suggested_questions}
                onSelect={(q) => send(q)}
                accent={accent}
              />
            </div>
          ) : (
            <>
              {messages.map((msg) =>
                msg.role === 'user' ? (
                  <UserBubble key={msg.id} content={msg.content} />
                ) : (
                  <AssistantBubble
                    key={msg.id}
                    content={msg.content}
                    streaming={msg.streaming}
                    error={msg.error}
                    accent={accent}
                  />
                )
              )}
            </>
          )}
          <div ref={bottomRef} />
        </div>
      </div>

      {/* Compact suggested pills when there are messages */}
      {!isEmpty && config.suggested_questions.length > 0 && !streaming && (
        <div className="max-w-3xl mx-auto w-full px-4 pb-2">
          <SuggestedPills
            questions={config.suggested_questions}
            onSelect={(q) => send(q)}
            accent={accent}
            compact
          />
        </div>
      )}

      {/* Input bar */}
      <div className="sticky bottom-0 bg-white/80 dark:bg-zinc-950/80 backdrop-blur border-t border-zinc-200 dark:border-zinc-800">
        <div className="max-w-3xl mx-auto px-4 py-3">
          <div
            className="flex items-end gap-2 rounded-2xl border border-zinc-200 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-900 px-4 py-3 focus-within:border-transparent focus-within:ring-2 transition-all"
            style={{ '--tw-ring-color': accent } as CSSProperties}
          >
            <textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => {
                setInput(e.target.value)
                resizeTextarea()
              }}
              onKeyDown={handleKeyDown}
              placeholder="Nhập câu hỏi… (Enter gửi, Shift+Enter xuống dòng)"
              className="flex-1 resize-none bg-transparent text-sm text-zinc-900 dark:text-zinc-100 placeholder-zinc-400 focus:outline-none min-h-[24px] max-h-[200px] leading-relaxed"
              rows={1}
            />
            {streaming ? (
              <button
                onClick={stop}
                className="shrink-0 size-8 rounded-full flex items-center justify-center text-zinc-400 hover:text-red-500 transition-colors"
                title="Dừng"
              >
                <StopCircleIcon className="size-5" />
              </button>
            ) : (
              <button
                onClick={() => send()}
                disabled={!input.trim()}
                className="shrink-0 size-8 rounded-full flex items-center justify-center text-white disabled:opacity-40 transition-opacity"
                style={{ backgroundColor: input.trim() ? accent : '#9ca3af' } as CSSProperties}
              >
                <SendIcon className="size-4" />
              </button>
            )}
          </div>
          <p className="text-[10px] text-zinc-400 text-center mt-2">
            Trung tâm Tin học Trường ĐH Khoa học Tự nhiên, ĐHQG TP.HCM
          </p>
        </div>
      </div>

      {/* Config modal */}
      {showConfig && (
        <ConfigPanel
          workspace={workspace}
          config={config}
          onSaved={setConfig}
          onClose={() => setShowConfig(false)}
        />
      )}
    </div>
  )
}
