import { useState, useEffect, useCallback, useRef } from 'react'
import {
  getLegalDocuments,
  updateLegalDocument,
  deleteLegalDocument,
  ingestLegalPdf,
  LegalDocumentItem,
  UpdateDocMetaRequest,
  LegalDocumentStatus,
} from '@/api/legal'
import Button from '@/components/ui/Button'
import Badge from '@/components/ui/Badge'
import Input from '@/components/ui/Input'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/Dialog'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/Select'
import {
  RefreshCwIcon,
  PencilIcon,
  Trash2Icon,
  SearchIcon,
  UploadIcon,
  ChevronDownIcon,
  ChevronUpIcon,
  CheckCircleIcon,
  XCircleIcon,
  Loader2Icon,
} from 'lucide-react'

// ── Constants ────────────────────────────────────────────────────────

const STATUS_LABELS: Record<LegalDocumentStatus, string> = {
  HIEU_LUC: 'Hiệu lực',
  SAP_HIEU_LUC: 'Sắp hiệu lực',
  HET_HIEU_LUC: 'Hết hiệu lực',
  BI_THAY_THE: 'Bị thay thế',
}

const STATUS_COLORS: Record<LegalDocumentStatus, string> = {
  HIEU_LUC: 'border-transparent bg-emerald-100 text-emerald-800 dark:bg-emerald-900 dark:text-emerald-200',
  SAP_HIEU_LUC: 'border-transparent bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200',
  HET_HIEU_LUC: 'border-transparent bg-gray-200 text-gray-600 dark:bg-gray-700 dark:text-gray-400',
  BI_THAY_THE: 'border-transparent bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200',
}

const STATUS_OPTIONS: LegalDocumentStatus[] = ['HIEU_LUC', 'SAP_HIEU_LUC', 'HET_HIEU_LUC', 'BI_THAY_THE']

const DOC_TYPES = [
  'Hiến pháp', 'Bộ luật', 'Luật', 'Pháp lệnh', 'Nghị quyết',
  'Nghị định', 'Thông tư liên tịch', 'Thông tư', 'Quyết định', 'Công văn',
]

// ── Status badge ─────────────────────────────────────────────────────

function StatusBadge({ status }: { status: string }) {
  const s = status as LegalDocumentStatus
  return (
    <Badge className={STATUS_COLORS[s] ?? 'border-transparent bg-secondary text-secondary-foreground'}>
      {STATUS_LABELS[s] ?? status}
    </Badge>
  )
}

// ── Upload panel ─────────────────────────────────────────────────────

type UploadState = 'idle' | 'uploading' | 'processing' | 'done' | 'error'

interface UploadResult {
  doc_id: string
  total_chunks?: number
  extraction_method?: string
  lightrag_status?: string
  errors: string[]
}

function UploadPanel({ onUploaded }: { onUploaded: () => void }) {
  const [open, setOpen] = useState(false)
  const [file, setFile] = useState<File | null>(null)
  const [form, setForm] = useState({
    doc_number: '',
    doc_type: 'Nghị định',
    issuer: '',
    issue_date: '',
    effective_date: '',
    title: '',
    legal_domain: '',
    use_ocr: false,
  })
  const [state, setState] = useState<UploadState>('idle')
  const [progress, setProgress] = useState(0)
  const [result, setResult] = useState<UploadResult | null>(null)
  const [errorMsg, setErrorMsg] = useState('')
  const fileInputRef = useRef<HTMLInputElement>(null)

  const reset = () => {
    setFile(null)
    setState('idle')
    setProgress(0)
    setResult(null)
    setErrorMsg('')
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  const handleUpload = async () => {
    if (!file) return
    setState('uploading')
    setProgress(0)
    setErrorMsg('')
    try {
      const res = await ingestLegalPdf(
        { file, ...form },
        (pct) => {
          setProgress(pct)
          if (pct === 100) setState('processing')
        }
      )
      setResult({
        doc_id: res.doc_id,
        total_chunks: res.qdrant_chunks?.total_chunks,
        extraction_method: res.qdrant_chunks?.extraction_method,
        lightrag_status: res.lightrag_status,
        errors: res.errors,
      })
      setState('done')
      onUploaded()
    } catch (e: any) {
      setErrorMsg(e?.response?.data?.detail ?? String(e))
      setState('error')
    }
  }

  const f = (key: keyof typeof form, label: string, placeholder = '') => (
    <div className="grid grid-cols-3 items-center gap-3">
      <label className="text-right text-xs font-medium text-muted-foreground">{label}</label>
      <Input
        className="col-span-2 h-7 text-sm"
        placeholder={placeholder}
        value={form[key] as string}
        onChange={(e) => setForm((p) => ({ ...p, [key]: e.target.value }))}
        disabled={state === 'uploading' || state === 'processing'}
      />
    </div>
  )

  return (
    <div className="rounded-md border bg-muted/20">
      {/* Header toggle */}
      <button
        className="flex w-full items-center gap-2 px-4 py-2.5 text-sm font-medium hover:bg-muted/40 transition-colors rounded-md"
        onClick={() => setOpen((v) => !v)}
      >
        <UploadIcon className="h-4 w-4 text-emerald-500" />
        <span>Upload văn bản pháp lý mới</span>
        <span className="ml-1 text-xs text-muted-foreground">(PDF / DOCX / MD / ảnh → Qdrant legal index)</span>
        <div className="flex-1" />
        {open ? <ChevronUpIcon className="h-4 w-4" /> : <ChevronDownIcon className="h-4 w-4" />}
      </button>

      {open && (
        <div className="border-t px-4 py-3 space-y-3">
          {/* File picker */}
          <div className="grid grid-cols-3 items-center gap-3">
            <label className="text-right text-xs font-medium text-muted-foreground">File</label>
            <div className="col-span-2 flex items-center gap-2">
              <input
                ref={fileInputRef}
                type="file"
                accept=".pdf,.docx,.md,.markdown,.txt,.png,.jpg,.jpeg,.tiff,.tif,.bmp,.webp"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0] ?? null
                  setFile(f)
                  if (f && !form.title) setForm((p) => ({ ...p, title: f.name }))
                  setState('idle')
                  setResult(null)
                }}
              />
              <Button
                variant="outline"
                size="sm"
                className="h-7 text-xs"
                onClick={() => fileInputRef.current?.click()}
                disabled={state === 'uploading' || state === 'processing'}
              >
                Chọn file
              </Button>
              <span className="text-xs text-muted-foreground truncate max-w-[200px]">
                {file ? file.name : 'Chưa chọn file'}
              </span>
            </div>
          </div>

          {/* Metadata fields */}
          {f('doc_number', 'Số hiệu', 'VD: 45/2026/NĐ-CP')}

          <div className="grid grid-cols-3 items-center gap-3">
            <label className="text-right text-xs font-medium text-muted-foreground">Loại VB</label>
            <Select
              value={form.doc_type}
              onValueChange={(v) => setForm((p) => ({ ...p, doc_type: v }))}
              disabled={state === 'uploading' || state === 'processing'}
            >
              <SelectTrigger className="col-span-2 h-7 text-sm">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {DOC_TYPES.map((t) => <SelectItem key={t} value={t}>{t}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>

          {f('issuer', 'Cơ quan', 'VD: Chính phủ')}
          {f('issue_date', 'Ngày ban hành', 'YYYY-MM-DD')}
          {f('effective_date', 'Ngày hiệu lực', 'YYYY-MM-DD')}
          {f('legal_domain', 'Lĩnh vực', 'VD: đất đai, lao động')}

          <div className="grid grid-cols-3 items-center gap-3">
            <label className="text-right text-xs font-medium text-muted-foreground">Dùng OCR</label>
            <div className="col-span-2 flex items-center gap-2">
              <input
                type="checkbox"
                className="h-3.5 w-3.5"
                checked={form.use_ocr}
                onChange={(e) => setForm((p) => ({ ...p, use_ocr: e.target.checked }))}
                disabled={state === 'uploading' || state === 'processing'}
              />
              <span className="text-xs text-muted-foreground">Ép OCR (tự động nếu PDF scan)</span>
            </div>
          </div>

          {/* Progress / result */}
          {(state === 'uploading' || state === 'processing') && (
            <div className="space-y-1">
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <Loader2Icon className="h-3.5 w-3.5 animate-spin" />
                {state === 'uploading' ? `Đang upload... ${progress}%` : 'Đang xử lý (chunking + embedding)...'}
              </div>
              {state === 'uploading' && (
                <div className="h-1.5 w-full rounded-full bg-muted overflow-hidden">
                  <div
                    className="h-full bg-emerald-500 transition-all"
                    style={{ width: `${progress}%` }}
                  />
                </div>
              )}
            </div>
          )}

          {state === 'done' && result && (
            <div className="rounded-md bg-emerald-50 dark:bg-emerald-950/30 border border-emerald-200 dark:border-emerald-800 px-3 py-2 text-xs space-y-0.5">
              <div className="flex items-center gap-1.5 font-medium text-emerald-700 dark:text-emerald-300">
                <CheckCircleIcon className="h-3.5 w-3.5" />
                Upload thành công
              </div>
              <div className="text-muted-foreground">
                doc_id: <span className="font-mono">{result.doc_id}</span>
                {result.total_chunks != null && ` · ${result.total_chunks} chunks`}
                {result.extraction_method && ` · ${result.extraction_method}`}
              </div>
              <div className="flex items-center gap-3 text-muted-foreground">
                <span>Qdrant: <span className="text-emerald-600 font-medium">✓ indexed</span></span>
                {result.lightrag_status && (
                  <span>
                    LightRAG KG:{' '}
                    <span className={
                      result.lightrag_status === 'processed' || result.lightrag_status === 'preprocessed'
                        ? 'text-emerald-600 font-medium'
                        : result.lightrag_status === 'failed'
                        ? 'text-destructive font-medium'
                        : 'text-amber-600 font-medium'
                    }>
                      {result.lightrag_status}
                    </span>
                  </span>
                )}
              </div>
              {result.errors.length > 0 && (
                <div className="text-amber-600 text-xs">{result.errors.join(' | ')}</div>
              )}
            </div>
          )}

          {state === 'error' && (
            <div className="flex items-start gap-1.5 text-xs text-destructive">
              <XCircleIcon className="h-3.5 w-3.5 mt-0.5 shrink-0" />
              {errorMsg}
            </div>
          )}

          {/* Action buttons */}
          <div className="flex justify-end gap-2 pt-1">
            {(state === 'done' || state === 'error') && (
              <Button variant="outline" size="sm" className="h-7 text-xs" onClick={reset}>
                Upload tiếp
              </Button>
            )}
            {(state === 'idle' || state === 'error') && (
              <Button
                size="sm"
                className="h-7 text-xs"
                onClick={handleUpload}
                disabled={!file}
              >
                Upload & Index
              </Button>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

// ── Edit dialog ──────────────────────────────────────────────────────

interface EditDialogProps {
  doc: LegalDocumentItem | null
  onClose: () => void
  onSaved: () => void
}

function EditDialog({ doc, onClose, onSaved }: EditDialogProps) {
  const [form, setForm] = useState<UpdateDocMetaRequest>({})
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (doc) {
      setForm({
        doc_number: doc.doc_number,
        doc_type: doc.doc_type,
        issuer: doc.issuer,
        issue_date: doc.issue_date,
        effective_date: doc.effective_date,
        status: doc.status,
        is_primary_source: doc.is_primary_source,
      })
      setError('')
    }
  }, [doc])

  const handleSave = async () => {
    if (!doc) return
    setSaving(true)
    setError('')
    try {
      await updateLegalDocument(doc.doc_id, form)
      onSaved()
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? 'Lỗi khi lưu')
    } finally {
      setSaving(false)
    }
  }

  const field = (key: keyof UpdateDocMetaRequest, label: string) => (
    <div className="grid grid-cols-3 items-center gap-4">
      <label className="text-right text-sm font-medium">{label}</label>
      <Input
        className="col-span-2 h-8"
        value={(form[key] as string) ?? ''}
        onChange={(e) => setForm((f) => ({ ...f, [key]: e.target.value }))}
      />
    </div>
  )

  return (
    <Dialog open={!!doc} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Chỉnh sửa metadata văn bản</DialogTitle>
        </DialogHeader>

        <div className="grid gap-3 py-2">
          {field('doc_number', 'Số hiệu')}
          {field('doc_type', 'Loại văn bản')}
          {field('issuer', 'Cơ quan ban hành')}
          {field('issue_date', 'Ngày ban hành')}
          {field('effective_date', 'Ngày hiệu lực')}

          <div className="grid grid-cols-3 items-center gap-4">
            <label className="text-right text-sm font-medium">Trạng thái</label>
            <Select
              value={form.status}
              onValueChange={(v) => setForm((f) => ({ ...f, status: v as LegalDocumentStatus }))}
            >
              <SelectTrigger className="col-span-2 h-8">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {STATUS_OPTIONS.map((s) => (
                  <SelectItem key={s} value={s}>{STATUS_LABELS[s]}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="grid grid-cols-3 items-center gap-4">
            <label className="text-right text-sm font-medium">Nguồn chính</label>
            <div className="col-span-2 flex items-center gap-2">
              <input
                type="checkbox"
                className="h-4 w-4"
                checked={form.is_primary_source ?? true}
                onChange={(e) => setForm((f) => ({ ...f, is_primary_source: e.target.checked }))}
              />
              <span className="text-sm text-muted-foreground">is_primary_source</span>
            </div>
          </div>
        </div>

        {error && <p className="text-sm text-destructive px-1">{error}</p>}

        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={saving}>Huỷ</Button>
          <Button onClick={handleSave} disabled={saving}>
            {saving ? 'Đang lưu...' : 'Lưu'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ── Delete confirm dialog ─────────────────────────────────────────────

interface DeleteDialogProps {
  doc: LegalDocumentItem | null
  onClose: () => void
  onDeleted: () => void
}

function DeleteDialog({ doc, onClose, onDeleted }: DeleteDialogProps) {
  const [deleting, setDeleting] = useState(false)
  const [error, setError] = useState('')

  const handleDelete = async () => {
    if (!doc) return
    setDeleting(true)
    setError('')
    try {
      await deleteLegalDocument(doc.doc_id)
      onDeleted()
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? 'Lỗi khi xoá')
      setDeleting(false)
    }
  }

  return (
    <Dialog open={!!doc} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>Xác nhận xoá văn bản</DialogTitle>
        </DialogHeader>
        <p className="text-sm text-muted-foreground py-2">
          Xoá toàn bộ chunks của văn bản{' '}
          <span className="font-semibold text-foreground">{doc?.doc_number}</span> khỏi Qdrant.
          Hành động này không thể hoàn tác.
        </p>
        {error && <p className="text-sm text-destructive">{error}</p>}
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={deleting}>Huỷ</Button>
          <Button variant="destructive" onClick={handleDelete} disabled={deleting}>
            {deleting ? 'Đang xoá...' : 'Xoá'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ── Main component ───────────────────────────────────────────────────

export default function LegalDocumentManager() {
  const [docs, setDocs] = useState<LegalDocumentItem[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [search, setSearch] = useState('')
  const [filterStatus, setFilterStatus] = useState<string>('all')
  const [editDoc, setEditDoc] = useState<LegalDocumentItem | null>(null)
  const [deleteDoc, setDeleteDoc] = useState<LegalDocumentItem | null>(null)

  const fetchDocs = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const data = await getLegalDocuments({ limit: 500 })
      setDocs(data)
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? 'Không thể tải danh sách. Kiểm tra Qdrant (QDRANT_HOST) đã chạy chưa.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchDocs() }, [fetchDocs])

  const filtered = docs.filter((d) => {
    const matchStatus = filterStatus === 'all' || d.status === filterStatus
    const q = search.toLowerCase()
    const matchSearch =
      !q ||
      d.doc_number.toLowerCase().includes(q) ||
      d.doc_type.toLowerCase().includes(q) ||
      d.issuer.toLowerCase().includes(q)
    return matchStatus && matchSearch
  })

  return (
    <div className="flex flex-col h-full p-4 gap-3">
      {/* Upload panel */}
      <UploadPanel onUploaded={fetchDocs} />

      {/* Toolbar */}
      <div className="flex items-center gap-3 flex-wrap">
        <span className="text-sm font-medium text-muted-foreground">
          {loading ? 'Đang tải...' : `${filtered.length} / ${docs.length} văn bản`}
        </span>
        <div className="flex-1" />
        <div className="relative">
          <SearchIcon className="absolute left-2 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            className="pl-8 h-8 w-56"
            placeholder="Tìm số hiệu, loại, cơ quan..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <Select value={filterStatus} onValueChange={setFilterStatus}>
          <SelectTrigger className="h-8 w-44">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Tất cả trạng thái</SelectItem>
            {STATUS_OPTIONS.map((s) => (
              <SelectItem key={s} value={s}>{STATUS_LABELS[s]}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Button variant="outline" size="sm" onClick={fetchDocs} disabled={loading} tooltip="Tải lại">
          <RefreshCwIcon className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
        </Button>
      </div>

      {error && (
        <div className="rounded-md border border-destructive/50 bg-destructive/10 px-4 py-3 text-sm text-destructive">
          {error}
        </div>
      )}

      {/* Table */}
      <div className="flex-1 overflow-auto rounded-md border">
        <table className="w-full text-sm">
          <thead className="sticky top-0 bg-muted/80 backdrop-blur">
            <tr className="border-b">
              <th className="px-3 py-2 text-left font-medium">Số hiệu</th>
              <th className="px-3 py-2 text-left font-medium">Loại</th>
              <th className="px-3 py-2 text-left font-medium">Cơ quan</th>
              <th className="px-3 py-2 text-left font-medium">Ngày ban hành</th>
              <th className="px-3 py-2 text-left font-medium">Ngày hiệu lực</th>
              <th className="px-3 py-2 text-left font-medium">Trạng thái</th>
              <th className="px-3 py-2 text-right font-medium">Chunks</th>
              <th className="px-3 py-2 text-center font-medium">Thao tác</th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 && !loading && (
              <tr>
                <td colSpan={8} className="px-3 py-12 text-center text-muted-foreground">
                  <div className="flex flex-col items-center gap-2">
                    <span>Chưa có văn bản nào trong Qdrant legal index.</span>
                    <span className="text-xs">Dùng form Upload phía trên để thêm tài liệu.</span>
                  </div>
                </td>
              </tr>
            )}
            {filtered.map((doc) => (
              <tr key={doc.doc_id} className="border-b hover:bg-muted/40 transition-colors">
                <td className="px-3 py-2 font-medium max-w-[160px] truncate" title={doc.doc_number}>
                  {doc.doc_number}
                </td>
                <td className="px-3 py-2 text-muted-foreground max-w-[120px] truncate" title={doc.doc_type}>
                  {doc.doc_type}
                </td>
                <td className="px-3 py-2 text-muted-foreground max-w-[140px] truncate" title={doc.issuer}>
                  {doc.issuer}
                </td>
                <td className="px-3 py-2 text-muted-foreground whitespace-nowrap">
                  {doc.issue_date || '—'}
                </td>
                <td className="px-3 py-2 text-muted-foreground whitespace-nowrap">
                  {doc.effective_date || '—'}
                </td>
                <td className="px-3 py-2">
                  <StatusBadge status={doc.status} />
                </td>
                <td className="px-3 py-2 text-right tabular-nums">
                  {doc.chunks_count}
                </td>
                <td className="px-3 py-2">
                  <div className="flex items-center justify-center gap-1">
                    <Button
                      variant="ghost"
                      size="icon"
                      tooltip="Chỉnh sửa"
                      onClick={() => setEditDoc(doc)}
                    >
                      <PencilIcon className="h-3.5 w-3.5" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      tooltip="Xoá"
                      onClick={() => setDeleteDoc(doc)}
                      className="text-destructive hover:text-destructive"
                    >
                      <Trash2Icon className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <EditDialog
        doc={editDoc}
        onClose={() => setEditDoc(null)}
        onSaved={() => { setEditDoc(null); fetchDocs() }}
      />
      <DeleteDialog
        doc={deleteDoc}
        onClose={() => setDeleteDoc(null)}
        onDeleted={() => { setDeleteDoc(null); fetchDocs() }}
      />
    </div>
  )
}
