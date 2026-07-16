import { Bot, CircleDot, Plus, X } from 'lucide-react'
import type { Task } from '../types/api'

const labels: Record<string, string> = { SUCCEEDED: '已完成', FAILED: '失败', CANCELLED: '已取消', PENDING: '等待中', EXECUTING: '执行中' }

export function TaskSidebar({ tasks, selectedId, open, onClose, onSelect, onNew }: { tasks: Task[]; selectedId: string | null; open: boolean; onClose: () => void; onSelect: (task: Task) => void; onNew: () => void }) {
  return <aside className={`sidebar ${open ? 'sidebar-open' : ''}`}>
    <div className="flex h-16 items-center justify-between border-b border-white/8 px-4"><div className="flex items-center gap-2 font-semibold"><Bot className="text-violet-400" size={20}/>任务记录</div><button className="icon-button lg:hidden" onClick={onClose} aria-label="关闭任务列表"><X size={18}/></button></div>
    <div className="p-3"><button className="new-task" onClick={onNew}><Plus size={17}/>新建任务</button></div>
    <div className="flex-1 overflow-y-auto px-2 pb-4">{tasks.length === 0 ? <p className="px-3 py-8 text-center text-sm text-zinc-500">还没有任务记录</p> : tasks.map((task) => <button key={task.id} className={`task-item ${selectedId === task.id ? 'task-item-active' : ''}`} onClick={() => onSelect(task)}><span className="line-clamp-2 text-left text-sm leading-5">{task.goal}</span><span className="mt-2 flex items-center justify-between text-xs text-zinc-500"><span className="flex items-center gap-1"><CircleDot size={11}/>{labels[task.state] || '进行中'}</span><time>{new Date(task.updated_at).toLocaleDateString('zh-CN')}</time></span></button>)}</div>
  </aside>
}
