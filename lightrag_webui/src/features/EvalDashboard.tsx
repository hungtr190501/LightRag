import { useState } from 'react'
import { ClipboardListIcon, PlayIcon, AlertTriangleIcon, SearchCodeIcon } from 'lucide-react'
import GoldenQuestions from '@/features/eval/GoldenQuestions'
import BenchmarkRuns from '@/features/eval/BenchmarkRuns'
import FailureCases from '@/features/eval/FailureCases'
import PipelineReplay from '@/features/eval/PipelineReplay'

type EvalPage = 'golden-questions' | 'benchmark-runs' | 'failure-cases' | 'pipeline-replay'

interface NavItemProps {
  value: EvalPage
  current: EvalPage
  icon: React.ReactNode
  label: string
  onClick: (v: EvalPage) => void
}

function NavItem({ value, current, icon, label, onClick }: NavItemProps) {
  const active = value === current
  return (
    <button
      onClick={() => onClick(value)}
      className={`flex w-full items-center gap-2.5 rounded-md px-3 py-2 text-sm font-medium transition-colors ${
        active
          ? 'bg-primary text-primary-foreground'
          : 'text-muted-foreground hover:bg-muted hover:text-foreground'
      }`}
    >
      <span className="size-4 shrink-0">{icon}</span>
      {label}
    </button>
  )
}

export default function EvalDashboard() {
  const [currentPage, setCurrentPage] = useState<EvalPage>('golden-questions')
  const [replayResultId, setReplayResultId] = useState<string | null>(null)

  const handleViewReplay = (resultId: string) => {
    setReplayResultId(resultId)
    setCurrentPage('pipeline-replay')
  }

  const navItems: { value: EvalPage; icon: React.ReactNode; label: string }[] = [
    { value: 'golden-questions', icon: <ClipboardListIcon className="size-4" />, label: 'Golden Questions' },
    { value: 'benchmark-runs', icon: <PlayIcon className="size-4" />, label: 'Benchmark Runs' },
    { value: 'failure-cases', icon: <AlertTriangleIcon className="size-4" />, label: 'Failure Cases' },
    { value: 'pipeline-replay', icon: <SearchCodeIcon className="size-4" />, label: 'Pipeline Replay' },
  ]

  return (
    <div className="flex h-full">
      {/* Left sidebar */}
      <aside className="flex w-52 shrink-0 flex-col gap-1 border-r p-3">
        <p className="mb-2 px-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Evaluation
        </p>
        {navItems.map((item) => (
          <NavItem
            key={item.value}
            value={item.value}
            current={currentPage}
            icon={item.icon}
            label={item.label}
            onClick={setCurrentPage}
          />
        ))}
      </aside>

      {/* Main content */}
      <main className="min-w-0 flex-1 overflow-auto p-6">
        {currentPage === 'golden-questions' && <GoldenQuestions />}
        {currentPage === 'benchmark-runs' && <BenchmarkRuns onViewReplay={handleViewReplay} />}
        {currentPage === 'failure-cases' && <FailureCases />}
        {currentPage === 'pipeline-replay' && <PipelineReplay resultId={replayResultId} />}
      </main>
    </div>
  )
}
