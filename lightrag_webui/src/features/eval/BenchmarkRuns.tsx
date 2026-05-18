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
import { PlusIcon, PlayIcon, EyeIcon } from 'lucide-react'
import {
  listBenchmarkRuns,
  createBenchmarkRun,
  startBenchmarkRun,
  getBenchmarkRun,
  getRunResults,
  listDatasetVersions,
  type BenchmarkRun,
  type RunResult,
  type DatasetVersion,
} from '@/api/eval'

const statusColor: Record<string, string> = {
  pending: 'bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-200',
  running: 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200',
  completed: 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200',
  failed: 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200',
}

function formatPercent(value?: number | null): string {
  if (value === undefined || value === null) return '-'
  return `${(value * 100).toFixed(1)}%`
}

function formatMs(value?: number | null): string {
  if (value === undefined || value === null) return '-'
  return `${value.toFixed(0)}ms`
}

interface BenchmarkRunsProps {
  onViewReplay?: (resultId: string) => void
}

export default function BenchmarkRuns({ onViewReplay }: BenchmarkRunsProps) {
  const [runs, setRuns] = useState<BenchmarkRun[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [createDialogOpen, setCreateDialogOpen] = useState(false)
  const [detailRun, setDetailRun] = useState<BenchmarkRun | null>(null)
  const [detailResults, setDetailResults] = useState<RunResult[]>([])
  const [datasets, setDatasets] = useState<DatasetVersion[]>([])

  // Create form
  const [formName, setFormName] = useState('')
  const [formDescription, setFormDescription] = useState('')
  const [formDataset, setFormDataset] = useState('')

  const loadRuns = useCallback(async () => {
    setLoading(true)
    try {
      const result = await listBenchmarkRuns({ limit: 50 })
      setRuns(result.items)
      setTotal(result.total)
    } catch (e: any) {
      toast.error('Failed to load runs: ' + (e.message || e))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadRuns()
  }, [loadRuns])

  const loadDatasets = async () => {
    try {
      const result = await listDatasetVersions()
      setDatasets(result.items || [])
    } catch {
      // Ignore — datasets are optional
    }
  }

  const openCreate = () => {
    setFormName('')
    setFormDescription('')
    setFormDataset('')
    loadDatasets()
    setCreateDialogOpen(true)
  }

  const handleCreate = async () => {
    if (!formName.trim()) {
      toast.error('Name is required')
      return
    }
    try {
      const run = await createBenchmarkRun({
        name: formName.trim(),
        description: formDescription.trim() || undefined,
        dataset_version: formDataset || undefined,
        config: {},
      })
      toast.success(`Run "${run.name}" created`)
      setCreateDialogOpen(false)
      loadRuns()
    } catch (e: any) {
      toast.error('Create failed: ' + (e.message || e))
    }
  }

  const handleStart = async (runId: string) => {
    try {
      await startBenchmarkRun(runId)
      toast.success('Benchmark run started (running in background)')
      // Poll for updates
      const pollInterval = setInterval(async () => {
        try {
          const updated = await getBenchmarkRun(runId)
          setRuns((prev) =>
            prev.map((r) => (r.id === runId ? updated : r))
          )
          if (updated.status === 'completed' || updated.status === 'failed') {
            clearInterval(pollInterval)
            toast.success(`Run ${updated.status}`)
            loadRuns()
          }
        } catch {
          clearInterval(pollInterval)
        }
      }, 5000)
    } catch (e: any) {
      toast.error('Start failed: ' + (e.message || e))
    }
  }

  const viewDetail = async (run: BenchmarkRun) => {
    setDetailRun(run)
    try {
      const data = await getRunResults(run.id)
      setDetailResults(data.results)
    } catch (e: any) {
      toast.error('Failed to load results: ' + (e.message || e))
    }
  }

  const closeDetail = () => {
    setDetailRun(null)
    setDetailResults([])
  }

  // Detail view
  if (detailRun) {
    return (
      <div className="space-y-4">
        <div className="flex items-center gap-3">
          <Button variant="outline" size="sm" onClick={closeDetail}>
            Back to Runs
          </Button>
          <h3 className="text-lg font-semibold">{detailRun.name}</h3>
          <span className={`rounded px-2 py-0.5 text-xs font-medium ${statusColor[detailRun.status]}`}>
            {detailRun.status}
          </span>
        </div>

        {/* Metrics summary */}
        <div className="grid grid-cols-5 gap-4">
          {[
            { label: 'Accuracy', value: formatPercent(detailRun.accuracy) },
            { label: 'Citation Accuracy', value: formatPercent(detailRun.citation_accuracy) },
            { label: 'Hallucination Rate', value: formatPercent(detailRun.hallucination_rate) },
            { label: 'Avg Latency', value: formatMs(detailRun.avg_latency_ms) },
            { label: 'Avg Confidence', value: formatPercent(detailRun.avg_confidence) },
          ].map(({ label, value }) => (
            <div key={label} className="rounded-lg border p-3 text-center">
              <div className="text-2xl font-bold">{value}</div>
              <div className="text-xs text-muted-foreground">{label}</div>
            </div>
          ))}
        </div>

        {/* Results table */}
        <div className="overflow-x-auto rounded-md border">
          <table className="w-full text-sm">
            <thead className="bg-muted/50">
              <tr>
                <th className="px-3 py-2 text-left font-medium">Question ID</th>
                <th className="px-3 py-2 text-left font-medium">Answer Preview</th>
                <th className="px-3 py-2 text-left font-medium">Confidence</th>
                <th className="px-3 py-2 text-left font-medium">Latency</th>
                <th className="px-3 py-2 text-left font-medium">Status</th>
                <th className="px-3 py-2 text-right font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {detailResults.map((r) => (
                <tr key={r.id} className="border-t hover:bg-muted/30">
                  <td className="px-3 py-2 font-mono text-xs">
                    {r.question_id.slice(0, 8)}...
                  </td>
                  <td className="max-w-xs truncate px-3 py-2">
                    {r.error ? (
                      <span className="text-red-500">{r.error}</span>
                    ) : (
                      (r.answer || '').slice(0, 100)
                    )}
                  </td>
                  <td className="px-3 py-2">{r.confidence?.toFixed(2) ?? '-'}</td>
                  <td className="px-3 py-2">{formatMs(r.latency_ms)}</td>
                  <td className="px-3 py-2">
                    {r.is_correct === 1 && <Badge className="bg-green-500">Correct</Badge>}
                    {r.is_correct === 0 && <Badge className="bg-red-500">Wrong</Badge>}
                    {r.is_correct === null && <Badge variant="outline">Not evaluated</Badge>}
                  </td>
                  <td className="px-3 py-2 text-right">
                    {onViewReplay && (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => onViewReplay(r.id)}
                        title="View pipeline replay"
                      >
                        <EyeIcon className="size-3.5" />
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    )
  }

  // Runs list view
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <Button onClick={openCreate} size="sm">
          <PlusIcon className="mr-1 size-4" /> Create Run
        </Button>
        <span className="ml-auto text-sm text-muted-foreground">{total} runs</span>
      </div>

      <div className="overflow-x-auto rounded-md border">
        <table className="w-full text-sm">
          <thead className="bg-muted/50">
            <tr>
              <th className="px-3 py-2 text-left font-medium">Name</th>
              <th className="px-3 py-2 text-left font-medium">Status</th>
              <th className="px-3 py-2 text-left font-medium">Progress</th>
              <th className="px-3 py-2 text-left font-medium">Accuracy</th>
              <th className="px-3 py-2 text-left font-medium">Avg Latency</th>
              <th className="px-3 py-2 text-left font-medium">Created</th>
              <th className="px-3 py-2 text-right font-medium">Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={7} className="px-3 py-8 text-center text-muted-foreground">
                  Loading...
                </td>
              </tr>
            ) : runs.length === 0 ? (
              <tr>
                <td colSpan={7} className="px-3 py-8 text-center text-muted-foreground">
                  No benchmark runs yet. Click "Create Run" to start.
                </td>
              </tr>
            ) : (
              runs.map((run) => (
                <tr key={run.id} className="border-t hover:bg-muted/30">
                  <td className="px-3 py-2 font-medium">{run.name}</td>
                  <td className="px-3 py-2">
                    <span
                      className={`rounded px-2 py-0.5 text-xs font-medium ${statusColor[run.status]}`}
                    >
                      {run.status}
                    </span>
                  </td>
                  <td className="px-3 py-2">
                    {run.completed_questions}/{run.total_questions}
                  </td>
                  <td className="px-3 py-2">{formatPercent(run.accuracy)}</td>
                  <td className="px-3 py-2">{formatMs(run.avg_latency_ms)}</td>
                  <td className="px-3 py-2 text-xs text-muted-foreground">
                    {run.created_at?.slice(0, 10)}
                  </td>
                  <td className="px-3 py-2 text-right">
                    {run.status === 'pending' && (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => handleStart(run.id)}
                        title="Start run"
                      >
                        <PlayIcon className="size-3.5" />
                      </Button>
                    )}
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => viewDetail(run)}
                      title="View results"
                    >
                      <EyeIcon className="size-3.5" />
                    </Button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Create Run Dialog */}
      <Dialog open={createDialogOpen} onOpenChange={setCreateDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Create Benchmark Run</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div>
              <label className="mb-1 block text-sm font-medium">Name *</label>
              <Input
                value={formName}
                onChange={(e) => setFormName(e.target.value)}
                placeholder="e.g. Qwen3-14B baseline v1"
              />
            </div>
            <div>
              <label className="mb-1 block text-sm font-medium">Description</label>
              <Textarea
                value={formDescription}
                onChange={(e) => setFormDescription(e.target.value)}
                rows={2}
                placeholder="What are you testing?"
              />
            </div>
            <div>
              <label className="mb-1 block text-sm font-medium">Dataset Version</label>
              <select
                className="w-full rounded border px-3 py-2 text-sm dark:bg-zinc-800"
                value={formDataset}
                onChange={(e) => setFormDataset(e.target.value)}
              >
                <option value="">All active questions</option>
                {datasets.map((ds) => (
                  <option key={ds.id} value={ds.id}>
                    {ds.name} ({ds.question_count} questions)
                  </option>
                ))}
              </select>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateDialogOpen(false)}>
              Cancel
            </Button>
            <Button onClick={handleCreate}>Create</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
