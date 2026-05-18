import { useMemo } from 'react'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/Dialog'
import Badge from '@/components/ui/Badge'
import { FileTextIcon, HashIcon, BookOpenIcon } from 'lucide-react'
import type { ReferenceItem } from '@/api/lightrag'

interface CitationModalProps {
  open: boolean
  onClose: () => void
  reference: ReferenceItem | null
  citationIndex: string | number
  query?: string
}

function getFileName(filePath: string): string {
  return filePath.split('/').pop() || filePath
}

function getLawDomainColor(fileName: string): string {
  const lower = fileName.toLowerCase()
  if (lower.includes('ai') || lower.includes('trí tuệ nhân tạo')) return 'bg-purple-100 text-purple-800 dark:bg-purple-900/40 dark:text-purple-300'
  if (lower.includes('cntt') || lower.includes('công nghệ thông tin') || lower.includes('viễn thông')) return 'bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300'
  if (lower.includes('lao động') || lower.includes('bảo hiểm') || lower.includes('bhxh')) return 'bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300'
  if (lower.includes('thuế') || lower.includes('tài chính') || lower.includes('ngân hàng')) return 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/40 dark:text-yellow-300'
  if (lower.includes('đất đai') || lower.includes('nhà ở') || lower.includes('xây dựng')) return 'bg-orange-100 text-orange-800 dark:bg-orange-900/40 dark:text-orange-300'
  if (lower.includes('hình sự') || lower.includes('tố tụng')) return 'bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300'
  if (lower.includes('doanh nghiệp') || lower.includes('thương mại') || lower.includes('đầu tư')) return 'bg-indigo-100 text-indigo-800 dark:bg-indigo-900/40 dark:text-indigo-300'
  return 'bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-300'
}

function getLawType(fileName: string): string {
  const lower = fileName.toLowerCase()
  if (lower.startsWith('luat') || lower.startsWith('luật')) return 'Luật'
  if (lower.startsWith('nd') || lower.includes('nghi-dinh') || lower.includes('nghị định')) return 'Nghị định'
  if (lower.startsWith('tt') || lower.includes('thong-tu') || lower.includes('thông tư')) return 'Thông tư'
  if (lower.startsWith('qd') || lower.includes('quyet-dinh') || lower.includes('quyết định')) return 'Quyết định'
  if (lower.includes('nghi-quyet') || lower.includes('nghị quyết')) return 'Nghị quyết'
  if (lower.includes('chi-thi') || lower.includes('chỉ thị')) return 'Chỉ thị'
  return 'Văn bản'
}

// Vietnamese stop words to exclude from keyword matching
const STOP_WORDS = new Set([
  'và', 'của', 'là', 'trong', 'có', 'được', 'các', 'cho', 'với', 'theo',
  'từ', 'đến', 'về', 'này', 'đó', 'như', 'một', 'khi', 'tại', 'đã',
  'bởi', 'vào', 'ra', 'hay', 'hoặc', 'nếu', 'thì', 'mà', 'để', 'bằng',
  'qua', 'trên', 'dưới', 'sau', 'trước', 'giữa', 'sẽ', 'đang', 'cũng',
  'không', 'còn', 'vẫn', 'thêm', 'lại', 'rằng', 'hơn', 'do', 'vì',
  'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
  'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
  'should', 'may', 'might', 'shall', 'can', 'of', 'in', 'on', 'at',
  'to', 'for', 'with', 'by', 'from', 'that', 'this', 'it', 'its',
])

function extractKeywords(query: string): string[] {
  return query
    .toLowerCase()
    .split(/[\s,.;!?:'"()\[\]]+/)
    .filter((w) => w.length > 2 && !STOP_WORDS.has(w))
}

interface Segment {
  text: string
  highlight: boolean
}

function buildHighlightedSegments(text: string, keywords: string[]): Segment[] {
  if (!keywords.length) return [{ text, highlight: false }]

  // Build a regex that matches any keyword (case-insensitive, Vietnamese-aware)
  const escaped = keywords.map((k) => k.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
  const pattern = new RegExp(`(${escaped.join('|')})`, 'gi')

  const parts = text.split(pattern)
  return parts.map((part) => ({
    text: part,
    highlight: keywords.some((k) => part.toLowerCase() === k.toLowerCase()),
  }))
}

function ChunkContent({ text, keywords }: { text: string; keywords: string[] }) {
  const segments = useMemo(() => buildHighlightedSegments(text, keywords), [text, keywords])

  return (
    <div className="rounded-md border bg-muted/30 p-4 text-sm leading-relaxed text-foreground whitespace-pre-wrap font-sans">
      {segments.map((seg, i) =>
        seg.highlight ? (
          <mark
            key={i}
            className="bg-yellow-200 dark:bg-yellow-700/60 text-foreground rounded-sm px-0.5"
          >
            {seg.text}
          </mark>
        ) : (
          <span key={i}>{seg.text}</span>
        )
      )}
    </div>
  )
}

export default function CitationModal({ open, onClose, reference, citationIndex, query }: CitationModalProps) {
  const keywords = useMemo(() => (query ? extractKeywords(query) : []), [query])

  if (!reference) return null

  const fileName = getFileName(reference.file_path)
  const domainColor = getLawDomainColor(fileName)
  const lawType = getLawType(fileName)
  const hasChunkContent = reference.content && reference.content.length > 0
  const chunkNum = typeof reference.chunk_order_index === 'number'
    ? reference.chunk_order_index + 1
    : null

  return (
    <Dialog open={open} onOpenChange={(isOpen) => { if (!isOpen) onClose() }}>
      <DialogContent className="max-w-2xl max-h-[85vh] flex flex-col gap-0 p-0 overflow-hidden">
        {/* Header */}
        <DialogHeader className="px-6 pt-5 pb-4 border-b shrink-0">
          <div className="flex items-start gap-3">
            <div className="flex-shrink-0 w-9 h-9 rounded-full bg-primary/10 flex items-center justify-center">
              <BookOpenIcon className="w-4 h-4 text-primary" />
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 flex-wrap mb-1">
                <Badge variant="outline" className={`text-xs px-2 py-0.5 font-medium border-0 ${domainColor}`}>
                  {lawType}
                </Badge>
                <span className="text-xs text-muted-foreground">Tài liệu tham khảo [{citationIndex}]</span>
              </div>
              <DialogTitle className="text-sm font-semibold text-left leading-snug break-words">
                {fileName}
              </DialogTitle>
            </div>
          </div>
        </DialogHeader>

        {/* Metadata row */}
        <div className="px-6 py-3 border-b shrink-0">
          <div className="flex flex-wrap gap-4 text-xs text-muted-foreground">
            <div className="flex items-center gap-1.5">
              <FileTextIcon className="w-3.5 h-3.5" />
              <span className="truncate max-w-[300px]" title={reference.file_path}>
                {reference.file_path}
              </span>
            </div>

            {chunkNum !== null && (
              <div className="flex items-center gap-1.5">
                <HashIcon className="w-3.5 h-3.5" />
                <span>Đoạn {chunkNum}</span>
              </div>
            )}

            {typeof reference.line_start === 'number' && typeof reference.line_end === 'number' && (
              <div className="flex items-center gap-1.5 font-mono">
                <span>Dòng {reference.line_start}–{reference.line_end}</span>
              </div>
            )}

            {query && keywords.length > 0 && (
              <div className="flex items-center gap-1 flex-wrap">
                <span className="text-[10px] uppercase tracking-wide opacity-60">từ khoá:</span>
                {keywords.slice(0, 5).map((kw) => (
                  <span key={kw} className="bg-yellow-100 dark:bg-yellow-800/40 text-yellow-800 dark:text-yellow-200 rounded px-1 text-[11px]">
                    {kw}
                  </span>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Scrollable content — plain div for reliable scrolling */}
        <div className="flex-1 overflow-y-auto min-h-0 px-6 py-4 space-y-3">
          {hasChunkContent ? (
            reference.content!.map((chunk, idx) => (
              <ChunkContent key={idx} text={chunk} keywords={keywords} />
            ))
          ) : (
            <div className="flex items-center justify-center text-sm text-muted-foreground py-8">
              Không có nội dung đoạn trích.
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-3 border-t shrink-0 bg-muted/30">
          <p className="text-xs text-muted-foreground">
            {keywords.length > 0
              ? 'Các từ khoá trong câu hỏi được bôi vàng để dễ tìm kiếm.'
              : 'Đoạn văn bản này được trích xuất từ kho tri thức để hỗ trợ câu trả lời.'}
          </p>
        </div>
      </DialogContent>
    </Dialog>
  )
}
