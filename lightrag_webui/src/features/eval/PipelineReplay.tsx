import { useCallback, useEffect, useState } from 'react'
import { toast } from 'sonner'
import Button from '@/components/ui/Button'
import Input from '@/components/ui/Input'
import { ChevronDownIcon, ChevronRightIcon, CheckCircleIcon, XCircleIcon, ClockIcon } from 'lucide-react'
import { getReplayData, type ReplayData } from '@/api/eval'

interface StepCardProps {
  step: Record<string, any>
  index: number
}

function StepCard({ step, index }: StepCardProps) {
  const [expanded, setExpanded] = useState(false)

  const statusIcon = step.status === 'success' ? (
    <CheckCircleIcon className="size-4 text-green-500" />
  ) : step.status === 'failure' ? (
    <XCircleIcon className="size-4 text-red-500" />
  ) : (
    <ClockIcon className="size-4 text-yellow-500" />
  )

  const durationMs = step.duration_ms ? `${Number(step.duration_ms).toFixed(0)}ms` : '-'

  return (
    <div className="rounded-lg border bg-card">
      <button
        className="flex w-full items-center gap-3 px-4 py-3 text-left"
        onClick={() => setExpanded(!expanded)}
      >
        <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-muted text-xs font-bold">
          {index + 1}
        </span>
        {statusIcon}
        <span className="flex-1 font-medium">{step.step || `Step ${index + 1}`}</span>
        <span className="text-xs text-muted-foreground">{durationMs}</span>
        {expanded ? (
          <ChevronDownIcon className="size-4 text-muted-foreground" />
        ) : (
          <ChevronRightIcon className="size-4 text-muted-foreground" />
        )}
      </button>

      {expanded && (
        <div className="border-t px-4 py-3 space-y-3 text-sm">
          {step.input_summary && (
            <div>
              <div className="mb-1 text-xs font-medium uppercase text-muted-foreground">Input</div>
              <div className="rounded bg-muted/40 px-3 py-2 text-xs font-mono">
                {step.input_summary}
              </div>
            </div>
          )}
          {step.output_summary && (
            <div>
              <div className="mb-1 text-xs font-medium uppercase text-muted-foreground">Output</div>
              <div className="rounded bg-muted/40 px-3 py-2 text-xs font-mono">
                {step.output_summary}
              </div>
            </div>
          )}
          {step.details && Object.keys(step.details).length > 0 && (
            <div>
              <div className="mb-1 text-xs font-medium uppercase text-muted-foreground">Details</div>
              <pre className="overflow-x-auto rounded bg-muted/40 px-3 py-2 text-xs">
                {JSON.stringify(step.details, null, 2)}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

interface PipelineReplayProps {
  resultId?: string | null
}

export default function PipelineReplay({ resultId: initialResultId }: PipelineReplayProps) {
  const [resultId, setResultId] = useState(initialResultId || '')
  const [inputId, setInputId] = useState(initialResultId || '')
  const [data, setData] = useState<ReplayData | null>(null)
  const [loading, setLoading] = useState(false)

  const loadReplay = useCallback(async (id: string) => {
    if (!id.trim()) return
    setLoading(true)
    try {
      const replay = await getReplayData(id.trim())
      setData(replay)
      setResultId(id.trim())
    } catch (e: any) {
      toast.error('Failed to load replay: ' + (e.message || e))
      setData(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (initialResultId) {
      setInputId(initialResultId)
      loadReplay(initialResultId)
    }
  }, [initialResultId, loadReplay])

  const pipelineTrace: Array<Record<string, any>> = data?.pipeline_trace || []

  const totalMs = pipelineTrace.reduce(
    (sum, s) => sum + (Number(s.duration_ms) || 0),
    0
  )

  return (
    <div className="space-y-4">
      {/* ID input */}
      <div className="flex items-center gap-3">
        <Input
          className="max-w-sm font-mono text-sm"
          placeholder="Run Result ID (UUID)"
          value={inputId}
          onChange={(e) => setInputId(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && loadReplay(inputId)}
        />
        <Button size="sm" onClick={() => loadReplay(inputId)} disabled={loading}>
          {loading ? 'Loading...' : 'Load Replay'}
        </Button>
      </div>

      {!data && !loading && (
        <div className="rounded-lg border border-dashed p-8 text-center text-muted-foreground">
          Enter a Run Result ID above, or click the "View Replay" icon from a Benchmark Run result.
        </div>
      )}

      {data && (
        <div className="space-y-4">
          {/* Question + Answer header */}
          <div className="rounded-lg border p-4 space-y-3">
            <div>
              <div className="mb-1 text-xs font-medium uppercase text-muted-foreground">Question</div>
              <div className="font-medium">{data.question}</div>
            </div>
            {data.error ? (
              <div>
                <div className="mb-1 text-xs font-medium uppercase text-muted-foreground text-red-500">Error</div>
                <div className="text-red-500 text-sm">{data.error}</div>
              </div>
            ) : (
              <div>
                <div className="mb-1 text-xs font-medium uppercase text-muted-foreground">Answer</div>
                <div className="text-sm">{data.answer}</div>
              </div>
            )}
            <div className="flex gap-4 text-sm text-muted-foreground">
              <span>Confidence: <strong>{data.confidence?.toFixed(2) ?? '-'}</strong></span>
              <span>Latency: <strong>{data.latency_ms ? `${Number(data.latency_ms).toFixed(0)}ms` : '-'}</strong></span>
              <span>Pipeline steps: <strong>{pipelineTrace.length}</strong></span>
              <span>Total traced: <strong>{totalMs.toFixed(0)}ms</strong></span>
            </div>
          </div>

          {/* Citations */}
          {data.citations && data.citations.length > 0 && (
            <div>
              <div className="mb-2 text-sm font-medium">Citations ({data.citations.length})</div>
              <div className="flex flex-wrap gap-2">
                {data.citations.map((c, i) => (
                  <span
                    key={i}
                    className="rounded bg-emerald-100 px-2 py-0.5 text-xs text-emerald-800 dark:bg-emerald-900 dark:text-emerald-200"
                  >
                    {c.doc_number || c.chunk_id || `[${i + 1}]`}
                    {c.article ? ` ${c.article}` : ''}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Pipeline trace */}
          <div>
            <div className="mb-2 text-sm font-medium">
              Pipeline Trace — {pipelineTrace.length} steps
            </div>
            {pipelineTrace.length === 0 ? (
              <div className="rounded-lg border border-dashed p-4 text-center text-sm text-muted-foreground">
                No pipeline trace data available for this result.
              </div>
            ) : (
              <div className="space-y-2">
                {pipelineTrace.map((step, i) => (
                  <StepCard key={i} step={step} index={i} />
                ))}
              </div>
            )}
          </div>

          {/* Retrieved chunks summary */}
          {data.retrieved_chunks && data.retrieved_chunks.length > 0 && (
            <div>
              <div className="mb-2 text-sm font-medium">
                Retrieved Chunks ({data.retrieved_chunks.length})
              </div>
              <div className="overflow-x-auto rounded-md border">
                <table className="w-full text-xs">
                  <thead className="bg-muted/50">
                    <tr>
                      <th className="px-3 py-2 text-left font-medium">Doc</th>
                      <th className="px-3 py-2 text-left font-medium">Article</th>
                      <th className="px-3 py-2 text-left font-medium">Score</th>
                      <th className="px-3 py-2 text-left font-medium">Source</th>
                      <th className="px-3 py-2 text-left font-medium">Preview</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.retrieved_chunks.map((c, i) => (
                      <tr key={i} className="border-t">
                        <td className="px-3 py-1.5 font-mono">{c.doc_number || '-'}</td>
                        <td className="px-3 py-1.5">{c.article || '-'}</td>
                        <td className="px-3 py-1.5">{c.score?.toFixed(3) ?? '-'}</td>
                        <td className="px-3 py-1.5">
                          <span className="rounded bg-blue-100 px-1.5 py-0.5 text-blue-800 dark:bg-blue-900 dark:text-blue-200">
                            {c.source || '-'}
                          </span>
                        </td>
                        <td className="max-w-xs truncate px-3 py-1.5 text-muted-foreground">
                          {c.text_preview || '-'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
