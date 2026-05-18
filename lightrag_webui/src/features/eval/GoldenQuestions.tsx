import { useCallback, useEffect, useState } from 'react'
import { toast } from 'sonner'
import Button from '@/components/ui/Button'
import Input from '@/components/ui/Input'
import Textarea from '@/components/ui/Textarea'
import Badge from '@/components/ui/Badge'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/Dialog'
import { PlusIcon, PencilIcon, TrashIcon, DownloadIcon, UploadIcon } from 'lucide-react'
import {
  listGoldenQuestions,
  createGoldenQuestion,
  updateGoldenQuestion,
  deleteGoldenQuestion,
  exportGoldenQuestions,
  importGoldenQuestions,
  type GoldenQuestion,
} from '@/api/eval'

const CATEGORIES = [
  'exact_retrieval',
  'dependency_expansion',
  'temporal_reasoning',
  'amendment_resolution',
  'conflict_detection',
  'legal_hierarchy',
  'hallucination_defense',
  'citation_validation',
  'multi_hop_reasoning',
  'general',
]

const DIFFICULTIES = ['easy', 'medium', 'hard', 'expert']

const difficultyColor: Record<string, string> = {
  easy: 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200',
  medium: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200',
  hard: 'bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200',
  expert: 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200',
}

export default function GoldenQuestions() {
  const [questions, setQuestions] = useState<GoldenQuestion[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [page, setPage] = useState(0)
  const [filterCategory, setFilterCategory] = useState('')
  const [filterDifficulty, setFilterDifficulty] = useState('')
  const [dialogOpen, setDialogOpen] = useState(false)
  const [editingQuestion, setEditingQuestion] = useState<GoldenQuestion | null>(null)

  // Form state
  const [formQuestion, setFormQuestion] = useState('')
  const [formCategory, setFormCategory] = useState('general')
  const [formDifficulty, setFormDifficulty] = useState('medium')
  const [formExpectedAnswer, setFormExpectedAnswer] = useState('')
  const [formNotes, setFormNotes] = useState('')
  const [formTags, setFormTags] = useState('')

  const pageSize = 20

  const loadQuestions = useCallback(async () => {
    setLoading(true)
    try {
      const result = await listGoldenQuestions({
        category: filterCategory || undefined,
        difficulty: filterDifficulty || undefined,
        offset: page * pageSize,
        limit: pageSize,
      })
      setQuestions(result.items)
      setTotal(result.total)
    } catch (e: any) {
      toast.error('Failed to load questions: ' + (e.message || e))
    } finally {
      setLoading(false)
    }
  }, [page, filterCategory, filterDifficulty])

  useEffect(() => {
    loadQuestions()
  }, [loadQuestions])

  const openCreate = () => {
    setEditingQuestion(null)
    setFormQuestion('')
    setFormCategory('general')
    setFormDifficulty('medium')
    setFormExpectedAnswer('')
    setFormNotes('')
    setFormTags('')
    setDialogOpen(true)
  }

  const openEdit = (q: GoldenQuestion) => {
    setEditingQuestion(q)
    setFormQuestion(q.question)
    setFormCategory(q.category)
    setFormDifficulty(q.difficulty)
    setFormExpectedAnswer(q.expected_answer || '')
    setFormNotes(q.notes || '')
    setFormTags((q.tags || []).join(', '))
    setDialogOpen(true)
  }

  const handleSave = async () => {
    if (!formQuestion.trim()) {
      toast.error('Question is required')
      return
    }
    try {
      const data = {
        question: formQuestion.trim(),
        category: formCategory,
        difficulty: formDifficulty,
        expected_answer: formExpectedAnswer.trim() || undefined,
        notes: formNotes.trim() || undefined,
        tags: formTags
          .split(',')
          .map((t) => t.trim())
          .filter(Boolean),
      }
      if (editingQuestion) {
        await updateGoldenQuestion(editingQuestion.id, data)
        toast.success('Question updated')
      } else {
        await createGoldenQuestion(data)
        toast.success('Question created')
      }
      setDialogOpen(false)
      loadQuestions()
    } catch (e: any) {
      toast.error('Save failed: ' + (e.message || e))
    }
  }

  const handleDelete = async (id: string) => {
    if (!confirm('Deactivate this question?')) return
    try {
      await deleteGoldenQuestion(id)
      toast.success('Question deactivated')
      loadQuestions()
    } catch (e: any) {
      toast.error('Delete failed: ' + (e.message || e))
    }
  }

  const handleExport = async () => {
    try {
      const data = await exportGoldenQuestions()
      const blob = new Blob([JSON.stringify(data.questions, null, 2)], {
        type: 'application/json',
      })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `golden_questions_${new Date().toISOString().slice(0, 10)}.json`
      a.click()
      URL.revokeObjectURL(url)
      toast.success(`Exported ${data.count} questions`)
    } catch (e: any) {
      toast.error('Export failed: ' + (e.message || e))
    }
  }

  const handleImport = async () => {
    const input = document.createElement('input')
    input.type = 'file'
    input.accept = '.json'
    input.onchange = async (e) => {
      const file = (e.target as HTMLInputElement).files?.[0]
      if (!file) return
      try {
        const text = await file.text()
        const parsed = JSON.parse(text)
        const questions = Array.isArray(parsed) ? parsed : parsed.questions || []
        const result = await importGoldenQuestions(questions)
        toast.success(`Imported ${result.imported} questions`)
        if (result.errors.length > 0) {
          toast.warning(`${result.errors.length} errors during import`)
        }
        loadQuestions()
      } catch (e: any) {
        toast.error('Import failed: ' + (e.message || e))
      }
    }
    input.click()
  }

  const totalPages = Math.ceil(total / pageSize)

  return (
    <div className="space-y-4">
      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-3">
        <Button onClick={openCreate} size="sm">
          <PlusIcon className="mr-1 size-4" /> Add Question
        </Button>
        <Button onClick={handleExport} variant="outline" size="sm">
          <DownloadIcon className="mr-1 size-4" /> Export
        </Button>
        <Button onClick={handleImport} variant="outline" size="sm">
          <UploadIcon className="mr-1 size-4" /> Import
        </Button>

        <select
          className="rounded border px-2 py-1 text-sm dark:bg-zinc-800"
          value={filterCategory}
          onChange={(e) => {
            setFilterCategory(e.target.value)
            setPage(0)
          }}
        >
          <option value="">All Categories</option>
          {CATEGORIES.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>

        <select
          className="rounded border px-2 py-1 text-sm dark:bg-zinc-800"
          value={filterDifficulty}
          onChange={(e) => {
            setFilterDifficulty(e.target.value)
            setPage(0)
          }}
        >
          <option value="">All Difficulties</option>
          {DIFFICULTIES.map((d) => (
            <option key={d} value={d}>
              {d}
            </option>
          ))}
        </select>

        <span className="ml-auto text-sm text-muted-foreground">
          {total} questions
        </span>
      </div>

      {/* Table */}
      <div className="overflow-x-auto rounded-md border">
        <table className="w-full text-sm">
          <thead className="bg-muted/50">
            <tr>
              <th className="px-3 py-2 text-left font-medium">Question</th>
              <th className="px-3 py-2 text-left font-medium">Category</th>
              <th className="px-3 py-2 text-left font-medium">Difficulty</th>
              <th className="px-3 py-2 text-left font-medium">Tags</th>
              <th className="px-3 py-2 text-right font-medium">Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={5} className="px-3 py-8 text-center text-muted-foreground">
                  Loading...
                </td>
              </tr>
            ) : questions.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-3 py-8 text-center text-muted-foreground">
                  No golden questions yet. Click "Add Question" to create one.
                </td>
              </tr>
            ) : (
              questions.map((q) => (
                <tr key={q.id} className="border-t hover:bg-muted/30">
                  <td className="max-w-md truncate px-3 py-2">{q.question}</td>
                  <td className="px-3 py-2">
                    <Badge variant="outline" className="text-xs">
                      {q.category}
                    </Badge>
                  </td>
                  <td className="px-3 py-2">
                    <span
                      className={`rounded px-2 py-0.5 text-xs font-medium ${difficultyColor[q.difficulty] || ''}`}
                    >
                      {q.difficulty}
                    </span>
                  </td>
                  <td className="px-3 py-2">
                    {(q.tags || []).map((t, i) => (
                      <Badge key={i} variant="secondary" className="mr-1 text-xs">
                        {t}
                      </Badge>
                    ))}
                  </td>
                  <td className="px-3 py-2 text-right">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => openEdit(q)}
                    >
                      <PencilIcon className="size-3.5" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => handleDelete(q.id)}
                    >
                      <TrashIcon className="size-3.5" />
                    </Button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={page === 0}
            onClick={() => setPage((p) => p - 1)}
          >
            Previous
          </Button>
          <span className="text-sm">
            Page {page + 1} of {totalPages}
          </span>
          <Button
            variant="outline"
            size="sm"
            disabled={page >= totalPages - 1}
            onClick={() => setPage((p) => p + 1)}
          >
            Next
          </Button>
        </div>
      )}

      {/* Create/Edit Dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>
              {editingQuestion ? 'Edit Golden Question' : 'Create Golden Question'}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div>
              <label className="mb-1 block text-sm font-medium">Question *</label>
              <Textarea
                value={formQuestion}
                onChange={(e) => setFormQuestion(e.target.value)}
                rows={3}
                placeholder="Enter the Vietnamese legal question..."
              />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="mb-1 block text-sm font-medium">Category</label>
                <select
                  className="w-full rounded border px-3 py-2 text-sm dark:bg-zinc-800"
                  value={formCategory}
                  onChange={(e) => setFormCategory(e.target.value)}
                >
                  {CATEGORIES.map((c) => (
                    <option key={c} value={c}>
                      {c}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="mb-1 block text-sm font-medium">Difficulty</label>
                <select
                  className="w-full rounded border px-3 py-2 text-sm dark:bg-zinc-800"
                  value={formDifficulty}
                  onChange={(e) => setFormDifficulty(e.target.value)}
                >
                  {DIFFICULTIES.map((d) => (
                    <option key={d} value={d}>
                      {d}
                    </option>
                  ))}
                </select>
              </div>
            </div>
            <div>
              <label className="mb-1 block text-sm font-medium">Expected Answer</label>
              <Textarea
                value={formExpectedAnswer}
                onChange={(e) => setFormExpectedAnswer(e.target.value)}
                rows={3}
                placeholder="Reference answer (optional)"
              />
            </div>
            <div>
              <label className="mb-1 block text-sm font-medium">Tags (comma-separated)</label>
              <Input
                value={formTags}
                onChange={(e) => setFormTags(e.target.value)}
                placeholder="e.g. dat-dai, 2024, nha-o"
              />
            </div>
            <div>
              <label className="mb-1 block text-sm font-medium">Notes</label>
              <Textarea
                value={formNotes}
                onChange={(e) => setFormNotes(e.target.value)}
                rows={2}
                placeholder="Internal notes..."
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)}>
              Cancel
            </Button>
            <Button onClick={handleSave}>
              {editingQuestion ? 'Update' : 'Create'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
