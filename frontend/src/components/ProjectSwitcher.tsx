import { FolderOpen } from 'lucide-react'
import type { ProjectSummary } from '../types/api'

interface ProjectSwitcherProps {
  project: ProjectSummary | null
  busy: boolean
  onOpen: () => Promise<void>
}

export function ProjectSwitcher({ project, busy, onOpen }: ProjectSwitcherProps) {
  return <section className="flex items-center gap-3 border-b border-zinc-800 px-4 py-2">
    <FolderOpen size={15} className="text-zinc-500"/>
    <div className="min-w-0 flex-1">
      <span className="block text-[10px] uppercase tracking-wider text-zinc-600">当前项目</span>
      <strong className="block truncate text-xs text-zinc-300" title={project?.root_path || '未打开项目'}>
        {project ? project.name : '未打开项目'}
      </strong>
    </div>
    <button className="secondary-button" disabled={busy} onClick={() => void onOpen()}>
      <FolderOpen size={14}/>打开项目
    </button>
  </section>
}
