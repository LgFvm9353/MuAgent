import { Send, Square } from 'lucide-react'
import { useState } from 'react'

interface TaskComposerProps {
  busy: boolean
  running: boolean
  onSubmit: (goal: string) => Promise<boolean>
  onCancel: () => Promise<void>
}

export function TaskComposer({ busy, running, onSubmit, onCancel }: TaskComposerProps) {
  const [goal, setGoal] = useState('')
  const [error, setError] = useState('')

  const submit = async () => {
    if (!goal.trim()) {
      setError('请输入任务目标')
      return
    }
    setError('')
    const created = await onSubmit(goal)
    if (created) setGoal('')
  }

  return <div className="composer-wrap">
    <div className={`composer ${error ? 'composer-error' : ''}`}>
      <textarea
        value={goal}
        onChange={(event) => {
          setGoal(event.target.value)
          if (error) setError('')
        }}
        onKeyDown={(event) => {
          if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
            event.preventDefault()
            void submit()
          }
        }}
        rows={2}
        maxLength={10000}
        placeholder="描述你希望 Agent 完成的任务…"
        disabled={busy}
      />
      <div className="flex items-end gap-2">
        {running && <button className="cancel-button" onClick={() => void onCancel()} disabled={busy} title="取消当前任务"><Square size={15}/></button>}
        <button className="send-button" onClick={() => void submit()} disabled={busy || !goal.trim()} title="发送任务"><Send size={18}/></button>
      </div>
    </div>
    <div className="mt-2 flex justify-between px-1 text-xs text-zinc-600">
      <span className="text-red-400">{error}</span>
      <span>Ctrl / ⌘ + Enter 发送</span>
    </div>
  </div>
}
