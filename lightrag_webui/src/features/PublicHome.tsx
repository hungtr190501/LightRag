import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  listWorkspaces,
  createWorkspace,
  updateWorkspace,
  deleteWorkspace,
  getPublicChatConfig,
  updatePublicChatConfig,
  type WorkspaceInfo,
  type PublicChatConfig,
} from '@/api/workspace'
import { listPublicWorkspaces, type PublicWorkspace } from '@/api/publicDocuments'
import { useAuthStore } from '@/stores/state'
import useTheme from '@/hooks/useTheme'
import PublicLoginModal from '@/components/PublicLoginModal'
import {
  ZapIcon,
  ArrowRightIcon,
  BookOpenIcon,
  Loader2Icon,
  MoonIcon,
  SunIcon,
  PlusIcon,
  PencilIcon,
  Trash2Icon,
  XIcon,
  CheckIcon,
  LogInIcon,
  LogOutIcon,
} from 'lucide-react'

// ── Types ────────────────────────────────────────────────────────────────────

type NotebookItem = WorkspaceInfo & {
  title: string
  accent_color: string
  publicDescription: string
  hasPublicConfig: boolean
}

const ACCENT_PRESETS = ['#10b981', '#6366f1', '#f59e0b', '#ef4444', '#3b82f6', '#8b5cf6', '#ec4899', '#14b8a6']

// ── Notebook form modal ───────────────────────────────────────────────────────

function NotebookModal({
  target,
  onClose,
  onSaved,
}: {
  target?: NotebookItem
  onClose: () => void
  onSaved: () => void
}) {
  const isEdit = !!target
  const [name, setName] = useState(target?.name ?? '')
  const [description, setDescription] = useState(target?.description ?? '')
  const [color, setColor] = useState(target?.color ?? '#6366f1')
  const [title, setTitle] = useState(target?.title ?? '')
  const [publicDesc, setPublicDesc] = useState(target?.publicDescription ?? '')
  const [accent, setAccent] = useState(target?.accent_color ?? '#10b981')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const nameRef = useRef<HTMLInputElement>(null)

  useEffect(() => { nameRef.current?.focus() }, [])

  const handleSave = async () => {
    if (!isEdit && !name.trim()) { setError('Tên notebook không được để trống'); return }
    setSaving(true); setError('')
    try {
      const wsName = isEdit ? target!.name : name.trim()
      if (!isEdit) {
        await createWorkspace({ name: wsName, description, color })
      } else {
        await updateWorkspace(wsName, { description, color })
      }
      await updatePublicChatConfig(wsName, {
        title: title || wsName,
        description: publicDesc,
        mode: 'hybrid',
        top_k: 40,
        suggested_questions: target?.hasPublicConfig ? [] : [],
        accent_color: accent,
      })
      onSaved()
      onClose()
    } catch (e: unknown) {
      setError((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Lỗi khi lưu')
    } finally { setSaving(false) }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-sm" onClick={onClose}>
      <div className="w-full max-w-md bg-white dark:bg-zinc-900 rounded-2xl shadow-2xl overflow-hidden" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-zinc-200 dark:border-zinc-800">
          <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">
            {isEdit ? `Sửa: ${target!.name}` : 'Tạo notebook mới'}
          </h2>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-400">
            <XIcon className="size-4" />
          </button>
        </div>

        <div className="px-5 py-4 space-y-4 max-h-[70vh] overflow-y-auto">
          {/* Workspace info */}
          <div>
            <div className="text-[11px] font-semibold text-zinc-400 uppercase tracking-wide mb-2">Workspace</div>
            {!isEdit && (
              <div className="mb-3">
                <label className="text-xs text-zinc-600 dark:text-zinc-400 mb-1 block">Tên (ID) *</label>
                <input
                  ref={nameRef}
                  value={name}
                  onChange={(e) => setName(e.target.value.replace(/\s+/g, '-').toLowerCase())}
                  placeholder="vi-du: luat-dan-su"
                  className="w-full px-3 py-2 rounded-xl border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                />
                <p className="text-[10px] text-zinc-400 mt-1">Chỉ chữ thường, số và dấu gạch ngang. Không thể đổi sau khi tạo.</p>
              </div>
            )}
            <div className="mb-3">
              <label className="text-xs text-zinc-600 dark:text-zinc-400 mb-1 block">Mô tả nội bộ</label>
              <input
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Ghi chú nội bộ về workspace này"
                className="w-full px-3 py-2 rounded-xl border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
            </div>
            <div>
              <label className="text-xs text-zinc-600 dark:text-zinc-400 mb-1 block">Màu nhận diện</label>
              <div className="flex gap-2 flex-wrap">
                {ACCENT_PRESETS.map((c) => (
                  <button key={c} onClick={() => setColor(c)} className={`size-6 rounded-full transition-transform ${color === c ? 'ring-2 ring-offset-2 ring-zinc-400 scale-110' : ''}`} style={{ backgroundColor: c }} />
                ))}
              </div>
            </div>
          </div>

          {/* Public chat config */}
          <div className="border-t border-zinc-200 dark:border-zinc-800 pt-4">
            <div className="text-[11px] font-semibold text-zinc-400 uppercase tracking-wide mb-2">Hiển thị công khai</div>
            <div className="mb-3">
              <label className="text-xs text-zinc-600 dark:text-zinc-400 mb-1 block">Tiêu đề hiển thị</label>
              <input
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder={`Trợ lý ${name || 'AI'}`}
                className="w-full px-3 py-2 rounded-xl border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
            </div>
            <div className="mb-3">
              <label className="text-xs text-zinc-600 dark:text-zinc-400 mb-1 block">Mô tả công khai</label>
              <textarea
                value={publicDesc}
                onChange={(e) => setPublicDesc(e.target.value)}
                placeholder="Mô tả ngắn gọn về notebook này cho người dùng"
                rows={2}
                className="w-full px-3 py-2 rounded-xl border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 resize-none"
              />
            </div>
            <div>
              <label className="text-xs text-zinc-600 dark:text-zinc-400 mb-1 block">Màu accent (giao diện chat)</label>
              <div className="flex gap-2 flex-wrap">
                {ACCENT_PRESETS.map((c) => (
                  <button key={c} onClick={() => setAccent(c)} className={`size-6 rounded-full transition-transform ${accent === c ? 'ring-2 ring-offset-2 ring-zinc-400 scale-110' : ''}`} style={{ backgroundColor: c }} />
                ))}
              </div>
            </div>
          </div>

          {error && <p className="text-xs text-red-500">{error}</p>}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 px-5 py-4 border-t border-zinc-200 dark:border-zinc-800">
          <button onClick={onClose} className="px-4 py-2 rounded-xl text-sm text-zinc-600 dark:text-zinc-400 hover:bg-zinc-100 dark:hover:bg-zinc-800">
            Huỷ
          </button>
          <button
            onClick={handleSave}
            disabled={saving || (!isEdit && !name.trim())}
            className="px-4 py-2 rounded-xl text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 flex items-center gap-1.5"
          >
            {saving ? <Loader2Icon className="size-4 animate-spin" /> : <CheckIcon className="size-4" />}
            {isEdit ? 'Lưu thay đổi' : 'Tạo notebook'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Delete confirm ────────────────────────────────────────────────────────────

function DeleteConfirm({ name, onClose, onDeleted }: { name: string; onClose: () => void; onDeleted: () => void }) {
  const [deleting, setDeleting] = useState(false)
  const handleDelete = async () => {
    setDeleting(true)
    try { await deleteWorkspace(name); onDeleted(); onClose() }
    catch { setDeleting(false) }
  }
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-sm" onClick={onClose}>
      <div className="w-full max-w-sm bg-white dark:bg-zinc-900 rounded-2xl shadow-2xl p-6" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100 mb-2">Xoá notebook?</h3>
        <p className="text-xs text-zinc-500 mb-4">
          Workspace <span className="font-mono font-semibold text-zinc-700 dark:text-zinc-300">{name}</span> sẽ bị xoá vĩnh viễn cùng toàn bộ cấu hình. Dữ liệu RAG không bị ảnh hưởng.
        </p>
        <div className="flex gap-2 justify-end">
          <button onClick={onClose} className="px-4 py-2 rounded-xl text-sm text-zinc-600 dark:text-zinc-400 hover:bg-zinc-100 dark:hover:bg-zinc-800">Huỷ</button>
          <button onClick={handleDelete} disabled={deleting} className="px-4 py-2 rounded-xl text-sm font-medium text-white bg-red-600 hover:bg-red-700 disabled:opacity-50 flex items-center gap-1.5">
            {deleting && <Loader2Icon className="size-4 animate-spin" />}
            Xoá
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Notebook card ─────────────────────────────────────────────────────────────

function NotebookCard({
  nb,
  isAdmin,
  onEdit,
  onDelete,
}: {
  nb: NotebookItem
  isAdmin: boolean
  onEdit: (nb: NotebookItem) => void
  onDelete: (name: string) => void
}) {
  const navigate = useNavigate()
  const accent = nb.accent_color || '#10b981'

  return (
    <div className="group relative bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-2xl overflow-hidden hover:shadow-lg hover:-translate-y-0.5 transition-all duration-200">
      {/* Accent strip */}
      <div className="h-1.5 w-full" style={{ backgroundColor: accent }} />

      <div className="px-5 py-4">
        <div className="flex items-start gap-3 mb-2">
          <div className="size-9 rounded-xl flex items-center justify-center shrink-0 mt-0.5" style={{ backgroundColor: `${accent}20` }}>
            <ZapIcon className="size-4" style={{ color: accent }} />
          </div>
          <div className="flex-1 min-w-0">
            <h3 className="font-semibold text-zinc-900 dark:text-zinc-100 text-sm leading-tight truncate">
              {nb.title || nb.name}
            </h3>
            <span className="text-[11px] text-zinc-400 font-mono">{nb.name}</span>
          </div>
          {/* Admin actions — show on hover */}
          {isAdmin && (
            <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity shrink-0">
              <button
                onClick={(e) => { e.stopPropagation(); onEdit(nb) }}
                className="p-1.5 rounded-lg text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-zinc-800"
                title="Sửa"
              >
                <PencilIcon className="size-3.5" />
              </button>
              <button
                onClick={(e) => { e.stopPropagation(); onDelete(nb.name) }}
                className="p-1.5 rounded-lg text-zinc-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20"
                title="Xoá"
              >
                <Trash2Icon className="size-3.5" />
              </button>
            </div>
          )}
        </div>

        {nb.publicDescription && (
          <p className="text-xs text-zinc-500 dark:text-zinc-400 line-clamp-2 mb-3 min-h-[2rem]">
            {nb.publicDescription}
          </p>
        )}

        <button
          onClick={() => navigate(`/public-chat/${nb.name}`)}
          className="flex items-center gap-1 text-xs font-medium mt-3 transition-colors hover:opacity-80"
          style={{ color: accent }}
        >
          <span>Bắt đầu trò chuyện</span>
          <ArrowRightIcon className="size-3 group-hover:translate-x-0.5 transition-transform" />
        </button>
      </div>
    </div>
  )
}

// ── Main ──────────────────────────────────────────────────────────────────────

export default function PublicHome() {
  const { theme, setTheme } = useTheme()
  const [isAdmin, setIsAdmin] = useState(!!localStorage.getItem('LIGHTRAG-API-TOKEN'))
  const [showLogin, setShowLogin] = useState(false)

  const [notebooks, setNotebooks] = useState<NotebookItem[]>([])
  const [loading, setLoading] = useState(true)
  const [showCreate, setShowCreate] = useState(false)
  const [editTarget, setEditTarget] = useState<NotebookItem | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null)

  const handleLogout = () => {
    useAuthStore.getState().logout()
    setIsAdmin(false)
  }

  const fetchNotebooks = useCallback(async () => {
    setLoading(true)
    try {
      if (isAdmin) {
        const workspaces = await listWorkspaces()
        const items: NotebookItem[] = await Promise.all(
          workspaces.map(async (ws) => {
            try {
              const cfg: PublicChatConfig = await getPublicChatConfig(ws.name)
              return {
                ...ws,
                title: cfg.title || ws.name,
                accent_color: cfg.accent_color || '#10b981',
                publicDescription: cfg.description || '',
                hasPublicConfig: true,
              }
            } catch {
              return {
                ...ws,
                title: ws.name,
                accent_color: ws.color || '#10b981',
                publicDescription: ws.description || '',
                hasPublicConfig: false,
              }
            }
          })
        )
        setNotebooks(items)
      } else {
        const pubs: PublicWorkspace[] = await listPublicWorkspaces()
        setNotebooks(
          pubs.map((p) => ({
            name: p.name,
            title: p.title,
            accent_color: p.accent_color,
            publicDescription: p.description,
            hasPublicConfig: true,
          }))
        )
      }
    } catch { setNotebooks([]) }
    finally { setLoading(false) }
  }, [isAdmin])

  useEffect(() => { fetchNotebooks() }, [fetchNotebooks])

  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-zinc-950">
      {/* Header */}
      <header className="sticky top-0 z-40 bg-white/80 dark:bg-zinc-950/80 backdrop-blur border-b border-zinc-200 dark:border-zinc-800">
        <div className="max-w-5xl mx-auto px-4 h-14 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <BookOpenIcon className="size-5 text-emerald-500" />
            <span className="font-bold text-sm text-zinc-900 dark:text-zinc-100">Trợ Lý AI Pháp Luật</span>
          </div>
          <div className="flex items-center gap-2">
            {isAdmin && (
              <button
                onClick={() => setShowCreate(true)}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-medium bg-indigo-600 hover:bg-indigo-700 text-white transition-colors"
              >
                <PlusIcon className="size-3.5" />
                Tạo notebook
              </button>
            )}
            {isAdmin ? (
              <button
                onClick={handleLogout}
                title="Đăng xuất"
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-medium text-zinc-500 dark:text-zinc-400 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors"
              >
                <LogOutIcon className="size-3.5" />
                Đăng xuất
              </button>
            ) : (
              <button
                onClick={() => setShowLogin(true)}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-medium text-zinc-500 dark:text-zinc-400 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors"
              >
                <LogInIcon className="size-3.5" />
                Đăng nhập
              </button>
            )}
            <button
              onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
              className="p-2 rounded-lg text-zinc-400 hover:bg-zinc-100 dark:hover:bg-zinc-800"
            >
              {theme === 'dark' ? <SunIcon className="size-4" /> : <MoonIcon className="size-4" />}
            </button>
          </div>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-4 py-12">
        {/* Hero */}
        <div className="text-center mb-10">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-400 text-xs font-medium mb-4">
            <ZapIcon className="size-3" />
            Powered by AI
          </div>
          <h1 className="text-3xl sm:text-4xl font-bold text-zinc-900 dark:text-zinc-100 mb-3">
            Sổ Tay Pháp Luật
          </h1>
          <p className="text-zinc-500 dark:text-zinc-400 max-w-md mx-auto text-sm">
            Mỗi sổ tay là một bộ văn bản pháp luật. Chọn lĩnh vực bạn cần tư vấn.
          </p>
        </div>

        {/* Grid */}
        {loading ? (
          <div className="flex justify-center py-20">
            <Loader2Icon className="size-6 animate-spin text-zinc-400" />
          </div>
        ) : notebooks.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 text-zinc-400">
            <BookOpenIcon className="size-12 opacity-30 mb-3" />
            <p className="text-sm">Chưa có notebook nào</p>
            {isAdmin && (
              <button onClick={() => setShowCreate(true)} className="mt-3 flex items-center gap-1.5 px-4 py-2 rounded-xl text-sm font-medium bg-indigo-600 hover:bg-indigo-700 text-white">
                <PlusIcon className="size-4" /> Tạo notebook đầu tiên
              </button>
            )}
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {notebooks.map((nb) => (
              <NotebookCard
                key={nb.name}
                nb={nb}
                isAdmin={isAdmin}
                onEdit={setEditTarget}
                onDelete={setDeleteTarget}
              />
            ))}
          </div>
        )}
      </main>

      {/* Modals */}
      {showCreate && (
        <NotebookModal onClose={() => setShowCreate(false)} onSaved={fetchNotebooks} />
      )}
      {editTarget && (
        <NotebookModal target={editTarget} onClose={() => setEditTarget(null)} onSaved={fetchNotebooks} />
      )}
      {deleteTarget && (
        <DeleteConfirm
          name={deleteTarget}
          onClose={() => setDeleteTarget(null)}
          onDeleted={fetchNotebooks}
        />
      )}
      {showLogin && (
        <PublicLoginModal
          onClose={() => setShowLogin(false)}
          onSuccess={() => { setIsAdmin(true); fetchNotebooks() }}
        />
      )}
    </div>
  )
}
