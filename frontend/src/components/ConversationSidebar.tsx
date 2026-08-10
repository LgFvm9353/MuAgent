import { Bot, CircleDot, Plus, X } from 'lucide-react'
import { parseApiDate } from '../lib/dateTime'
import type { ConversationThread } from '../types/api'

const labels: Record<string, string> = {
  SUCCEEDED: '已完成',
  FAILED: '失败',
  CANCELLED: '已取消',
  PENDING: '等待中',
  EXECUTING: '执行中',
  WAITING_CONFIRMATION: '等待确认',
  NEEDS_REVIEW: '需处理',
}

interface Props {
  conversations: ConversationThread[]
  selectedId: string | null
  open: boolean
  onClose: () => void
  onSelect: (conversation: ConversationThread) => void
  onNew: () => void
}

export function ConversationSidebar({
  conversations,
  selectedId,
  open,
  onClose,
  onSelect,
  onNew,
}: Props) {
  return <aside className={`sidebar ${open ? 'sidebar-open' : ''}`}>
    <div className="flex h-16 items-center justify-between border-b border-white/8 px-4">
      <div className="flex items-center gap-2 font-semibold"><Bot className="text-violet-400" size={20}/>对话记录</div>
      <button className="icon-button lg:hidden" onClick={onClose} aria-label="关闭对话列表"><X size={18}/></button>
    </div>
    <div className="p-3"><button className="new-task" onClick={onNew} aria-label="新建对话" title="新建对话"><Plus size={17}/></button></div>
    <div className="flex-1 overflow-y-auto px-2 pb-4">
      {conversations.length === 0
        ? <p className="px-3 py-8 text-center text-sm text-zinc-500">还没有对话</p>
        : conversations.map((conversation) => <button
            key={conversation.id}
            className={`task-item ${selectedId === conversation.id ? 'task-item-active' : ''}`}
            onClick={() => onSelect(conversation)}
          >
            <span className="line-clamp-2 text-left text-sm leading-5">{conversation.title}</span>
            <span className={`mt-2 flex items-center text-xs text-zinc-500 ${conversation.latest_task_state ? 'justify-between' : 'justify-end'}`}>
              {conversation.latest_task_state && <span className="flex items-center gap-1"><CircleDot size={11}/>{labels[conversation.latest_task_state] || '进行中'}</span>}
              <time>{parseApiDate(conversation.updated_at).toLocaleDateString('zh-CN')}</time>
            </span>
          </button>)}
    </div>
  </aside>
}
