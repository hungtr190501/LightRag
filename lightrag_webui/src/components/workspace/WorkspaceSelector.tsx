import { useState, useEffect } from 'react'
import Button from '@/components/ui/Button'
import { useWorkspaceStore } from '@/stores/workspace'
import WorkspacePanel from './WorkspacePanel'
import { LayersIcon } from 'lucide-react'

export default function WorkspaceSelector() {
  const currentWorkspace = useWorkspaceStore.use.currentWorkspace()
  const workspaces = useWorkspaceStore.use.workspaces()
  const fetchWorkspaces = useWorkspaceStore.use.fetchWorkspaces()
  const [panelOpen, setPanelOpen] = useState(false)

  useEffect(() => {
    fetchWorkspaces()
  }, [fetchWorkspaces])

  const currentInfo = workspaces.find((w) => w.name === currentWorkspace)
  const label = currentWorkspace || 'default'
  const color = currentInfo?.color || '#64748b'

  return (
    <>
      <Button
        variant="ghost"
        size="sm"
        className="h-7 gap-1.5 px-2 text-xs font-medium"
        tooltip="Chuyển đổi workspace"
        onClick={() => setPanelOpen(true)}
      >
        <LayersIcon className="size-3.5" />
        <div className="w-2 h-2 rounded-full shrink-0" style={{ background: color }} />
        <span className="max-w-[80px] truncate">{label}</span>
      </Button>

      <WorkspacePanel open={panelOpen} onClose={() => setPanelOpen(false)} />
    </>
  )
}
