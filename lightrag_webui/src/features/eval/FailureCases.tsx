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
import { PlusIcon, ArrowRightIcon } from 'lucide-react'
import {
  listFailureCases,
  createFailureCase,
  updateFailureCase,
  convertToGolden,
  type FailureCase,
} from '@/api/eval'

const FAILURE_TYPES = [
  'hallucination',
  'wrong_citation',
  'missing_context',
  'wrong_law',
  'conflict_missed',
  'incomplete_answer',
  'other',
]

const SEVERITIES = ['low', 'medium', 'high', 'critical']
const STATUSES = ['open', 'investigating', 'resolved', 'wontfix']

const severityColor: Record<string, string> = {
  low: 'bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-200',
  medium: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200',
  high: 'bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200',
  critical: 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200',
}

const statusColor: Record<string, string> = {
  open: 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200',
  investigating: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200',
  resolved: 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200',
  wontfix: 'bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-200',
}

export default function FailureCases() {
  const [cases, setCases] = useState<FailureCase[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [filterStatus, setFilterStatus] = useState('')
  const [filterType, setFilterType] = useState('')
  const [createDialogOpen, setCreateDialogOpen] = useState(false)
  const [editCase, setEditCase] = useState<FailureCase | null>(null)

  // Create form
  const [formQuestion, setFormQuestion] = useState('')
  const [formAnswer, setFormAnswer] = useState('')
  const [formType, setFormType] = useState('hallucination')
  const [formSeverity, setFormSeverity] = useState('medium')
  const [formDescription, setFormDescription] = useState('')

  // Edit form
  const [editStatus, setEditStatus] = useState('')
  const [editResolution, setEditResolution] = useState('')

  const loadCases = useCallback(async () => {
    setLoading(true)
    try {
      const result = await listFailureCases({
        status: filterStatus || undefined,
        failure_type: filterType || undefined,
        limit: 50,
      })
      setCases(result.items)
      setTotal(result.total)
    } catch (e: any) {
      toast.error('Failed to load failure cases: ' + (e.message || e))
    } finally {
      setLoading(false)
    }
  }, [filterStatus, filterType])

  useEffect(() => {
    loadCases()
  }, [loadCases])

  const openCreate = () => {
    setFormQuestion('')
    setFormAnswer('')
    setFormType('hallucination')
    setFormSeverity('medium')
    setFormDescription('')
    setCreateDialogOpen(true)
  }

  const handleCreate = async () => {
    if (!formQuestion.trim()) {
      toast.error('Question is required')
      return
    }
    try {
      await createFailureCase({
        question: formQuestion.trim(),
        answer: formAnswer.trim() || undefined,
        failure_type: formType,
        severity: formSeverity,
        description: formDescription.trim() || undefined,
        source: 'manual',
      })
      toast.success('Failure case created')
      setCreateDialogOpen(false)
      loadCases()
    } catch (e: any) {
      toast.error('Create failed: ' + (e.message || e))
    }
  }

  const openEdit = (fc: FailureCase) => {
    setEditCase(fc)
    setEditStatus(fc.status)
    setEditResolution(fc.resolution || '')
  }

  const handleUpdateStatus = async () => {
    if (!editCase) return
    try {
      await updateFailureCase(editCase.id, {
        status: editStatus,
        resolution: editResolution.trim() || undefined,
      })
      toast.success('Failure case updated')
      setEditCase(null)
      loadCases()
    } catch (e: any) {
      toast.error('Update failed: ' + (e.message || e))
    }
  }

  const handleConvertToGolden = async (id: string) => {
    if (!confirm('Convert this failure case to a golden question?')) return
    try {
      const result = await convertToGolden(id)
      toast.success(`Converted to golden question: ${result.question_id.slice(0, 8)}...`)
      loadCases()
    } catch (e: any) {
      toast.error('Conversion failed: ' + (e.message || e))
    }
  }

  return (
    <div className="space-y-4">
      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-3">
        <Button onClick={openCreate} size="sm">
          <PlusIcon className="mr-1 size-4" /> Report Failure
        </Button>

        <select
          className="rounded border px-2 py-1 text-sm dark:bg-zinc-800"
          value={filterStatus}
          onChange={(e) => setFilterStatus(e.target.value)}
        >
          <option value="">All Statuses</option>
          {STATUSES.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>

        <select
          className="rounded border px-2 py-1 text-sm dark:bg-zinc-800"
          value={filterType}
          onChange={(e) => setFilterType(e.target.value)}
        >
          <option value="">All Types</option>
          {FAILURE_TYPES.map((t) => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>

        <span className="ml-auto text-sm text-muted-foreground">{total} cases</span>
      </div>

      {/* Table */}
      <div className="overflow-x-auto rounded-md border">
        <table className="w-full text-sm">
          <thead className="bg-muted/50">
            <tr>
              <th className="px-3 py-2 text-left font-medium">Question</th>
              <th className="px-3 py-2 text-left font-medium">Type</th>
              <th className="px-3 py-2 text-left font-medium">Severity</th>
              <th className="px-3 py-2 text-left font-medium">Status</th>
              <th className="px-3 py-2 text-left font-medium">Source</th>
              <th className="px-3 py-2 text-right font-medium">Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={6} className="px-3 py-8 text-center text-muted-foreground">
                  Loading...
                </td>
              </tr>
            ) : cases.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-3 py-8 text-center text-muted-foreground">
                  No failure cases tracked yet.
                </td>
              </tr>
            ) : (
              cases.map((fc) => (
                <tr key={fc.id} className="border-t hover:bg-muted/30">
                  <td className="max-w-xs truncate px-3 py-2">{fc.question}</td>
                  <td className="px-3 py-2">
                    <Badge variant="outline" className="text-xs">{fc.failure_type}</Badge>
                  </td>
                  <td className="px-3 py-2">
                    <span className={`rounded px-2 py-0.5 text-xs font-medium ${severityColor[fc.severity] || ''}`}>
                      {fc.severity}
                    </span>
                  </td>
                  <td className="px-3 py-2">
                    <span className={`rounded px-2 py-0.5 text-xs font-medium ${statusColor[fc.status] || ''}`}>
                      {fc.status}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-xs">{fc.source}</td>
                  <td className="px-3 py-2 text-right">
                    <Button variant="ghost" size="sm" onClick={() => openEdit(fc)} title="Update status">
                      Edit
                    </Button>
                    {!fc.converted_to_golden && (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => handleConvertToGolden(fc.id)}
                        title="Convert to golden question"
                      >
                        <ArrowRightIcon className="size-3.5" />
                      </Button>
                    )}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Create Dialog */}
      <Dialog open={createDialogOpen} onOpenChange={setCreateDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Report Failure Case</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div>
              <label className="mb-1 block text-sm font-medium">Question *</label>
              <Textarea
                value={formQuestion}
                onChange={(e) => setFormQuestion(e.target.value)}
                rows={2}
                placeholder="The question that caused the failure..."
              />
            </div>
            <div>
              <label className="mb-1 block text-sm font-medium">Answer (the wrong answer)</label>
              <Textarea
                value={formAnswer}
                onChange={(e) => setFormAnswer(e.target.value)}
                rows={2}
                placeholder="The incorrect or problematic answer..."
              />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="mb-1 block text-sm font-medium">Failure Type</label>
                <select
                  className="w-full rounded border px-3 py-2 text-sm dark:bg-zinc-800"
                  value={formType}
                  onChange={(e) => setFormType(e.target.value)}
                >
                  {FAILURE_TYPES.map((t) => (
                    <option key={t} value={t}>{t}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="mb-1 block text-sm font-medium">Severity</label>
                <select
                  className="w-full rounded border px-3 py-2 text-sm dark:bg-zinc-800"
                  value={formSeverity}
                  onChange={(e) => setFormSeverity(e.target.value)}
                >
                  {SEVERITIES.map((s) => (
                    <option key={s} value={s}>{s}</option>
                  ))}
                </select>
              </div>
            </div>
            <div>
              <label className="mb-1 block text-sm font-medium">Description</label>
              <Textarea
                value={formDescription}
                onChange={(e) => setFormDescription(e.target.value)}
                rows={2}
                placeholder="What went wrong?"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateDialogOpen(false)}>Cancel</Button>
            <Button onClick={handleCreate}>Create</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Edit Status Dialog */}
      <Dialog open={editCase !== null} onOpenChange={(open) => !open && setEditCase(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Update Failure Case</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div className="text-sm text-muted-foreground">
              {editCase?.question}
            </div>
            <div>
              <label className="mb-1 block text-sm font-medium">Status</label>
              <select
                className="w-full rounded border px-3 py-2 text-sm dark:bg-zinc-800"
                value={editStatus}
                onChange={(e) => setEditStatus(e.target.value)}
              >
                {STATUSES.map((s) => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-sm font-medium">Resolution</label>
              <Textarea
                value={editResolution}
                onChange={(e) => setEditResolution(e.target.value)}
                rows={3}
                placeholder="How was this issue resolved?"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditCase(null)}>Cancel</Button>
            <Button onClick={handleUpdateStatus}>Update</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
