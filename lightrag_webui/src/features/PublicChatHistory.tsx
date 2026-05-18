import { type CSSProperties, useCallback, useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  listSessions,
  deleteSession,
  getSession,
  type SessionSummary,
  type SessionDetail,
  type SessionMessage,
} from '@/api/publicChatSessions'
import { getPublicChatConfig, type PublicChatConfig } from '@/api/workspace'
import {
  ArrowLeftIcon,
  ThumbsUpIcon,
  ThumbsDownIcon,
  Trash2Icon,
  ChevronDownIcon,
  ChevronRightIcon,
  MessageSquareIcon,
  ZapIcon,
  Loader2Icon,
  SearchIcon,
  BotIcon,
  UserIcon,
} from 'lucide-react'

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtDate(iso: string) {
  try {
    return new Date(iso).toLocaleString('vi-VN', {
      day: '2-digit', month: '2-digit', year: 'numeric',
      hour: '2-digit', minute: '2-digit',
    })
  } catch { return iso }
}

function fmtDateShort(iso: string) {
  try {
    return new Date(iso).toLocaleDateString('vi-VN', { day: '2-digit', month: '2-digit', year: 'numeric' })
  } catch { return iso }
}

const DEFAULT_CONFIG: PublicChatConfig = {
  title: '', description: '', mode: 'hybrid', top_k: 40,
  suggested_questions: [], accent_color: '#10b981',
}

// ── Session row ───────────────────────────────────────────────────────────────

function SessionRow({
  session,
  accent,
  onDelete,
}: {
  session: SessionSummary
  accent: string
  onDelete: (id: string) => void
}) {
  const [expanded, setExpanded] = useState(false)
  const [detail, setDetail] = useState<SessionDetail | null>(null)
  const [loadingDetail, setLoadingDetail] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const { workspace = 'default' } = useParams<{ workspace: string }>()
  const navigate = useNavigate()

  const toggle = async () => {
    if (!expanded && !detail) {
      setLoadingDetail(true)
      try {
        const d = await getSession(workspace, session.id)
        setDetail(d)
      } catch { /* ignore */ }
      finally { setLoadingDetail(false) }
    }
    setExpanded((v) => !v)
  }

  return (
    <div className="border border-zinc-200 dark:border-zinc-700 rounded-xl overflow-hidden">
      {/* Row header */}
      <div className="flex items-center gap-3 px-4 py-3 bg-white dark:bg-zinc-900 hover:bg-zinc-50 dark:hover:bg-zinc-800/50 transition-colors">
        <button onClick={toggle} className="flex items-center gap-3 flex-1 min-w-0 text-left">
          <div className="shrink-0 text-zinc-400">
            {loadingDetail
              ? <Loader2Icon className="size-4 animate-spin" />
              : expanded
              ? <ChevronDownIcon className="size-4" />
              : <ChevronRightIcon className="size-4" />}
          </div>
          <div className="flex-1 min-w-0">
            <div className="text-sm font-medium text-zinc-900 dark:text-zinc-100 truncate">{session.title}</div>
            <div className="flex items-center gap-3 mt-0.5 flex-wrap">
              <span className="text-[11px] text-zinc-400">{fmtDate(session.updated_at)}</span>
              <span className="text-[11px] text-zinc-400 flex items-center gap-0.5">
                <MessageSquareIcon className="size-3" />{session.message_count} tin
              </span>
              {session.like_count > 0 && (
                <span className="text-[11px] text-emerald-600 flex items-center gap-0.5">
                  <ThumbsUpIcon className="size-3" />{session.like_count}
                </span>
              )}
              {session.dislike_count > 0 && (
                <span className="text-[11px] text-red-500 flex items-center gap-0.5">
                  <ThumbsDownIcon className="size-3" />{session.dislike_count}
                </span>
              )}
            </div>
          </div>
        </button>

        {/* Actions */}
        <div className="flex items-center gap-1 shrink-0">
          <button
            onClick={() => navigate(`/public-chat/${workspace}?session=${session.id}`)}
            className="px-2.5 py-1.5 rounded-lg text-xs border border-zinc-200 dark:border-zinc-700 text-zinc-600 dark:text-zinc-400 hover:bg-zinc-100 dark:hover:bg-zinc-800"
            title="Mở trong chat"
          >
            Mở
          </button>
          {!confirmDelete ? (
            <button
              onClick={() => setConfirmDelete(true)}
              className="p-1.5 rounded-lg text-zinc-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20"
              title="Xoá"
            >
              <Trash2Icon className="size-4" />
            </button>
          ) : (
            <div className="flex items-center gap-1">
              <button
                onClick={() => { onDelete(session.id); setConfirmDelete(false) }}
                className="px-2 py-1 rounded text-xs bg-red-500 hover:bg-red-600 text-white"
              >
                Xoá
              </button>
              <button
                onClick={() => setConfirmDelete(false)}
                className="px-2 py-1 rounded text-xs border border-zinc-300 dark:border-zinc-600 text-zinc-600 dark:text-zinc-400 hover:bg-zinc-100 dark:hover:bg-zinc-800"
              >
                Huỷ
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Expanded messages */}
      {expanded && (
        <div className="border-t border-zinc-200 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-900/50 px-4 py-4 space-y-3 max-h-[500px] overflow-y-auto">
          {!detail ? (
            <div className="flex justify-center py-4"><Loader2Icon className="size-4 animate-spin text-zinc-400" /></div>
          ) : detail.messages.length === 0 ? (
            <div className="text-sm text-zinc-400 text-center py-4">Không có tin nhắn</div>
          ) : (
            detail.messages.map((msg: SessionMessage) => (
              <div key={msg.id} className={`flex gap-2 ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                {msg.role === 'assistant' && (
                  <div className="size-6 rounded-full flex items-center justify-center shrink-0 mt-0.5 text-white text-[10px]" style={{ backgroundColor: accent }}>
                    <BotIcon className="size-3.5" />
                  </div>
                )}
                <div className={`max-w-[80%] ${msg.role === 'user' ? 'order-first' : ''}`}>
                  <div className={`px-3 py-2 rounded-xl text-xs leading-relaxed whitespace-pre-wrap ${
                    msg.role === 'user'
                      ? 'bg-zinc-900 dark:bg-zinc-100 text-white dark:text-zinc-900 rounded-tr-sm'
                      : 'bg-white dark:bg-zinc-800 text-zinc-800 dark:text-zinc-200 border border-zinc-200 dark:border-zinc-700 rounded-tl-sm'
                  }`}>
                    {msg.content}
                  </div>
                  <div className={`flex items-center gap-2 mt-1 ${msg.role === 'user' ? 'justify-end' : ''}`}>
                    <span className="text-[10px] text-zinc-400">{fmtDateShort(msg.timestamp)}</span>
                    {msg.feedback === 'like' && <span className="text-[10px] text-emerald-600 flex items-center gap-0.5"><ThumbsUpIcon className="size-3" />Hữu ích</span>}
                    {msg.feedback === 'dislike' && <span className="text-[10px] text-red-500 flex items-center gap-0.5"><ThumbsDownIcon className="size-3" />Không hữu ích</span>}
                  </div>
                </div>
                {msg.role === 'user' && (
                  <div className="size-6 rounded-full bg-zinc-200 dark:bg-zinc-700 flex items-center justify-center shrink-0 mt-0.5">
                    <UserIcon className="size-3.5 text-zinc-500" />
                  </div>
                )}
              </div>
            ))
          )}
        </div>
      )}
    </div>
  )
}

// ── Stats bar ─────────────────────────────────────────────────────────────────

function StatsBar({ sessions, accent }: { sessions: SessionSummary[]; accent: string }) {
  const total = sessions.length
  const totalMsgs = sessions.reduce((s, x) => s + x.message_count, 0)
  const totalLikes = sessions.reduce((s, x) => s + x.like_count, 0)
  const totalDislikes = sessions.reduce((s, x) => s + x.dislike_count, 0)

  const stats = [
    { label: 'Cuộc trò chuyện', value: total },
    { label: 'Tin nhắn', value: totalMsgs },
    { label: 'Hữu ích', value: totalLikes, color: '#10b981' },
    { label: 'Không hữu ích', value: totalDislikes, color: '#ef4444' },
  ]

  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
      {stats.map((s) => (
        <div key={s.label} className="bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-700 rounded-xl px-4 py-3">
          <div className="text-2xl font-bold" style={{ color: s.color ?? accent }}>{s.value}</div>
          <div className="text-xs text-zinc-500 mt-0.5">{s.label}</div>
        </div>
      ))}
    </div>
  )
}

// ── Main ──────────────────────────────────────────────────────────────────────

export default function PublicChatHistory() {
  const { workspace = 'default' } = useParams<{ workspace: string }>()
  const navigate = useNavigate()

  const [config, setConfig] = useState<PublicChatConfig>(DEFAULT_CONFIG)
  const [sessions, setSessions] = useState<SessionSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [filter, setFilter] = useState<'all' | 'liked' | 'disliked'>('all')

  const accent = config.accent_color || '#10b981'
  const title = config.title || `Trợ lý ${workspace}`

  useEffect(() => {
    getPublicChatConfig(workspace)
      .then((c) => setConfig({ ...DEFAULT_CONFIG, ...c }))
      .catch(() => { /* ignore */ })
  }, [workspace])

  const fetchSessions = useCallback(async () => {
    setLoading(true)
    try {
      const list = await listSessions(workspace)
      setSessions(list)
    } catch { /* ignore */ }
    finally { setLoading(false) }
  }, [workspace])

  useEffect(() => { fetchSessions() }, [fetchSessions])

  const handleDelete = useCallback(async (id: string) => {
    try {
      await deleteSession(workspace, id)
      setSessions((prev) => prev.filter((s) => s.id !== id))
    } catch { /* ignore */ }
  }, [workspace])

  const filtered = sessions.filter((s) => {
    const matchSearch = !search || s.title.toLowerCase().includes(search.toLowerCase())
    const matchFilter =
      filter === 'all' ||
      (filter === 'liked' && s.like_count > 0) ||
      (filter === 'disliked' && s.dislike_count > 0)
    return matchSearch && matchFilter
  })

  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-zinc-950">
      {/* Header */}
      <header className="sticky top-0 z-40 bg-white/80 dark:bg-zinc-950/80 backdrop-blur border-b border-zinc-200 dark:border-zinc-800">
        <div className="max-w-4xl mx-auto px-4 h-12 flex items-center gap-3">
          <button
            onClick={() => navigate(`/public-chat/${workspace}`)}
            className="p-1.5 rounded-lg text-zinc-400 hover:bg-zinc-100 dark:hover:bg-zinc-800"
            title="Quay lại chat"
          >
            <ArrowLeftIcon className="size-4" />
          </button>
          <ZapIcon className="size-4" style={{ color: accent }} />
          <span className="font-semibold text-sm">{title}</span>
          <span className="text-zinc-400 text-sm">/</span>
          <span className="text-sm text-zinc-500">Lịch sử trò chuyện</span>
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-zinc-100 dark:bg-zinc-800 text-zinc-500 font-mono ml-auto hidden sm:inline">
            {workspace}
          </span>
        </div>
      </header>

      <div className="max-w-4xl mx-auto px-4 py-6">
        {/* Stats */}
        {!loading && sessions.length > 0 && <StatsBar sessions={sessions} accent={accent} />}

        {/* Filters */}
        <div className="flex flex-col sm:flex-row gap-3 mb-4">
          <div className="relative flex-1">
            <SearchIcon className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-zinc-400" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Tìm kiếm theo tiêu đề…"
              className="w-full pl-9 pr-4 py-2 rounded-xl border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 text-sm focus:outline-none focus:ring-2"
              style={{ '--tw-ring-color': accent } as CSSProperties}
            />
          </div>
          <div className="flex gap-2">
            {(['all', 'liked', 'disliked'] as const).map((f) => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                className={`px-3 py-2 rounded-xl text-xs border transition-colors ${
                  filter === f
                    ? 'text-white border-transparent'
                    : 'border-zinc-200 dark:border-zinc-700 text-zinc-600 dark:text-zinc-400 bg-white dark:bg-zinc-900 hover:bg-zinc-50 dark:hover:bg-zinc-800'
                }`}
                style={filter === f ? { backgroundColor: accent } as CSSProperties : undefined}
              >
                {f === 'all' ? 'Tất cả' : f === 'liked' ? '👍 Hữu ích' : '👎 Không hữu ích'}
              </button>
            ))}
          </div>
        </div>

        {/* Session list */}
        {loading ? (
          <div className="flex items-center justify-center py-16">
            <Loader2Icon className="size-6 animate-spin text-zinc-400" />
          </div>
        ) : filtered.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 text-zinc-400">
            <MessageSquareIcon className="size-10 opacity-30 mb-3" />
            <p className="text-sm">
              {sessions.length === 0 ? 'Chưa có cuộc trò chuyện nào' : 'Không tìm thấy kết quả phù hợp'}
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            {filtered.map((s) => (
              <SessionRow key={s.id} session={s} accent={accent} onDelete={handleDelete} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
