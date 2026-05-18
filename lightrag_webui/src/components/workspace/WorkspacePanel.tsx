import { useState, useEffect } from 'react'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/Dialog'
import Button from '@/components/ui/Button'
import Input from '@/components/ui/Input'
import { useWorkspaceStore } from '@/stores/workspace'
import type { WorkspaceInfo } from '@/api/workspace'
import { PlusIcon, TrashIcon, CheckIcon, PencilIcon } from 'lucide-react'

const PRESET_COLORS = [
  '#6366f1', '#8b5cf6', '#ec4899', '#ef4444',
  '#f97316', '#eab308', '#22c55e', '#14b8a6',
  '#3b82f6', '#06b6d4', '#64748b', '#78716c',
]

interface Props {
  open: boolean
  onClose: () => void
}

export default function WorkspacePanel({ open, onClose }: Props) {
  const workspaces = useWorkspaceStore.use.workspaces()
  const currentWorkspace = useWorkspaceStore.use.currentWorkspace()
  const fetchWorkspaces = useWorkspaceStore.use.fetchWorkspaces()
  const createWorkspace = useWorkspaceStore.use.createWorkspace()
  const updateWorkspace = useWorkspaceStore.use.updateWorkspace()
  const deleteWorkspace = useWorkspaceStore.use.deleteWorkspace()
  const setCurrentWorkspace = useWorkspaceStore.use.setCurrentWorkspace()

  const [newName, setNewName] = useState('')
  const [newDescription, setNewDescription] = useState('')
  const [newColor, setNewColor] = useState(PRESET_COLORS[0])
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState('')

  const [editingName, setEditingName] = useState<string | null>(null)
  const [editDescription, setEditDescription] = useState('')
  const [editColor, setEditColor] = useState('')
  const [saving, setSaving] = useState(false)

  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)

  useEffect(() => {
    if (open) {
      fetchWorkspaces()
      setError('')
      setNewName('')
      setNewDescription('')
      setNewColor(PRESET_COLORS[0])
      setEditingName(null)
      setConfirmDelete(null)
    }
  }, [open, fetchWorkspaces])

  const handleCreate = async () => {
    const name = newName.trim()
    if (!name) { setError('Tên workspace không được để trống'); return }
    if (!/^[a-z0-9_-]+$/i.test(name)) { setError('Tên chỉ được chứa chữ, số, dấu gạch ngang và gạch dưới'); return }
    setCreating(true)
    setError('')
    try {
      await createWorkspace({ name, description: newDescription.trim(), color: newColor })
      setNewName('')
      setNewDescription('')
      setNewColor(PRESET_COLORS[0])
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || 'Lỗi tạo workspace')
    } finally {
      setCreating(false)
    }
  }

  const startEdit = (ws: WorkspaceInfo) => {
    setEditingName(ws.name)
    setEditDescription(ws.description || '')
    setEditColor(ws.color || PRESET_COLORS[0])
  }

  const handleSaveEdit = async () => {
    if (!editingName) return
    setSaving(true)
    try {
      await updateWorkspace(editingName, { description: editDescription, color: editColor })
      setEditingName(null)
    } catch (e: any) {
      console.error('Failed to update workspace:', e)
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (name: string) => {
    if (confirmDelete !== name) { setConfirmDelete(name); return }
    try {
      await deleteWorkspace(name)
      setConfirmDelete(null)
    } catch (e: any) {
      console.error('Failed to delete workspace:', e)
    }
  }

  const handleSelect = (name: string) => {
    setCurrentWorkspace(name === currentWorkspace ? '' : name)
  }

  return (
    <Dialog open={open} onOpenChange={(v) => { if (!v) onClose() }}>
      <DialogContent className="max-w-lg max-h-[80vh] flex flex-col gap-0 p-0">
        <DialogHeader className="px-5 pt-5 pb-3 border-b border-border/40">
          <DialogTitle>Quản lý Workspace</DialogTitle>
          <p className="text-xs text-muted-foreground mt-0.5">
            Mỗi workspace có đồ thị kiến thức và kho tài liệu riêng.
          </p>
        </DialogHeader>

        <div className="flex-1 overflow-y-auto px-5 py-3 space-y-2">
          {/* Default workspace */}
          <div
            className={`flex items-center gap-3 rounded-lg border px-3 py-2 cursor-pointer transition-colors ${
              currentWorkspace === ''
                ? 'border-primary/60 bg-primary/5'
                : 'border-border/40 hover:bg-muted/40'
            }`}
            onClick={() => handleSelect('')}
          >
            <div className="w-3 h-3 rounded-full bg-slate-400 shrink-0" />
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium">default</p>
              <p className="text-xs text-muted-foreground truncate">Workspace mặc định</p>
            </div>
            {currentWorkspace === '' && <CheckIcon className="size-4 text-primary shrink-0" />}
          </div>

          {/* Registered workspaces */}
          {workspaces.map((ws) => (
            <div key={ws.name} className={`rounded-lg border transition-colors ${
              currentWorkspace === ws.name ? 'border-primary/60 bg-primary/5' : 'border-border/40'
            }`}>
              {editingName === ws.name ? (
                <div className="p-3 space-y-2">
                  <div className="flex items-center gap-2">
                    <div className="w-3 h-3 rounded-full shrink-0" style={{ background: editColor }} />
                    <span className="text-sm font-medium">{ws.name}</span>
                  </div>
                  <Input
                    value={editDescription}
                    onChange={(e) => setEditDescription(e.target.value)}
                    placeholder="Mô tả..."
                    className="h-8 text-sm"
                  />
                  <div className="flex gap-1.5 flex-wrap">
                    {PRESET_COLORS.map((c) => (
                      <button
                        key={c}
                        className={`w-5 h-5 rounded-full border-2 transition-all ${editColor === c ? 'border-foreground scale-110' : 'border-transparent hover:scale-110'}`}
                        style={{ background: c }}
                        onClick={() => setEditColor(c)}
                      />
                    ))}
                  </div>
                  <div className="flex gap-2 justify-end">
                    <Button variant="ghost" size="sm" onClick={() => setEditingName(null)}>Hủy</Button>
                    <Button variant="default" size="sm" disabled={saving} onClick={handleSaveEdit}>
                      {saving ? 'Đang lưu...' : 'Lưu'}
                    </Button>
                  </div>
                </div>
              ) : (
                <div
                  className="flex items-center gap-3 px-3 py-2 cursor-pointer hover:bg-muted/30"
                  onClick={() => handleSelect(ws.name)}
                >
                  <div
                    className="w-3 h-3 rounded-full shrink-0"
                    style={{ background: ws.color || '#64748b' }}
                  />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium">{ws.name}</p>
                    {ws.description && (
                      <p className="text-xs text-muted-foreground truncate">{ws.description}</p>
                    )}
                  </div>
                  {currentWorkspace === ws.name && <CheckIcon className="size-4 text-primary shrink-0" />}
                  <button
                    className="p-1 rounded hover:bg-muted text-muted-foreground hover:text-foreground transition-colors shrink-0"
                    onClick={(e) => { e.stopPropagation(); startEdit(ws) }}
                    title="Chỉnh sửa"
                  >
                    <PencilIcon className="size-3.5" />
                  </button>
                  <button
                    className={`p-1 rounded transition-colors shrink-0 ${
                      confirmDelete === ws.name
                        ? 'bg-red-500 text-white hover:bg-red-600'
                        : 'hover:bg-muted text-muted-foreground hover:text-red-500'
                    }`}
                    onClick={(e) => { e.stopPropagation(); handleDelete(ws.name) }}
                    title={confirmDelete === ws.name ? 'Nhấn lần nữa để xác nhận xóa' : 'Xóa workspace'}
                  >
                    <TrashIcon className="size-3.5" />
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>

        {/* Create new workspace */}
        <div className="border-t border-border/40 px-5 py-4 space-y-3">
          <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Tạo workspace mới</p>
          <div className="flex gap-2">
            <Input
              value={newName}
              onChange={(e) => { setNewName(e.target.value); setError('') }}
              placeholder="Tên workspace (vd: luat-ai)"
              className="h-8 text-sm flex-1"
              onKeyDown={(e) => { if (e.key === 'Enter') handleCreate() }}
            />
            <Input
              value={newDescription}
              onChange={(e) => setNewDescription(e.target.value)}
              placeholder="Mô tả (tuỳ chọn)"
              className="h-8 text-sm flex-1"
            />
          </div>
          <div className="flex items-center gap-3">
            <div className="flex gap-1.5 flex-wrap flex-1">
              {PRESET_COLORS.map((c) => (
                <button
                  key={c}
                  className={`w-5 h-5 rounded-full border-2 transition-all ${newColor === c ? 'border-foreground scale-110' : 'border-transparent hover:scale-110'}`}
                  style={{ background: c }}
                  onClick={() => setNewColor(c)}
                />
              ))}
            </div>
            <Button
              variant="default"
              size="sm"
              disabled={creating || !newName.trim()}
              onClick={handleCreate}
              className="shrink-0"
            >
              <PlusIcon className="size-4" />
              {creating ? 'Đang tạo...' : 'Tạo'}
            </Button>
          </div>
          {error && <p className="text-xs text-red-500">{error}</p>}
        </div>
      </DialogContent>
    </Dialog>
  )
}
