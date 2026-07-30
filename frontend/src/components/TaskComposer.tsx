import { Send, Square } from 'lucide-react'
import { useRef, useState } from 'react'

interface TaskComposerProps {
  busy: boolean
  running: boolean
  onSubmit: (goal: string) => Promise<boolean>
  onCancel: () => Promise<void>
}

interface AgentOption {
  id: 'architect' | 'reviewer' | 'designer'
  name: string
  description: string
}

interface MentionQuery {
  start: number
  end: number
  query: string
}

const agentOptions: AgentOption[] = [
  { id: 'architect', name: 'Architect', description: '架构、后端与实现规划' },
  { id: 'reviewer', name: 'Reviewer', description: '审查、测试、安全与验证' },
  { id: 'designer', name: 'Designer', description: '前端、交互与视觉设计' },
]

function mentionAtCursor(value: string, cursor: number): MentionQuery | null {
  const prefix = value.slice(0, cursor)
  const match = prefix.match(/(?:^|\s)@([^\s@]*)$/)
  if (!match || match.index === undefined) return null
  const start = match.index + (match[0].startsWith('@') ? 0 : 1)
  return { start, end: cursor, query: match[1].toLowerCase() }
}

function selectedAgentIds(value: string): Set<string> {
  return new Set(Array.from(value.matchAll(/(?:^|\s)@(architect|reviewer|designer)(?=\s|$)/g), (match) => match[1]))
}

export function TaskComposer({ busy, running, onSubmit, onCancel }: TaskComposerProps) {
  const [goal, setGoal] = useState('')
  const [error, setError] = useState('')
  const [mention, setMention] = useState<MentionQuery | null>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const selected = selectedAgentIds(goal)
  const matches = mention
    ? agentOptions.filter((agent) => (
        !selected.has(agent.id)
        && (`${agent.id} ${agent.name}`.toLowerCase().includes(mention.query))
      ))
    : []
  const mentionOpen = Boolean(mention && matches.length > 0)

  const updateMention = (value: string, cursor: number | null) => {
    setMention(cursor === null ? null : mentionAtCursor(value, cursor))
  }

  const selectAgent = (agent: AgentOption) => {
    if (!mention) return
    const insertion = `@${agent.id} `
    const nextGoal = `${goal.slice(0, mention.start)}${insertion}${goal.slice(mention.end)}`
    const nextCursor = mention.start + insertion.length
    setGoal(nextGoal)
    setMention(null)
    requestAnimationFrame(() => {
      textareaRef.current?.focus()
      textareaRef.current?.setSelectionRange(nextCursor, nextCursor)
    })
  }

  const submit = async () => {
    if (!goal.trim()) {
      setError('请输入任务目标')
      return
    }
    setError('')
    const created = await onSubmit(goal)
    if (created) {
      setGoal('')
      setMention(null)
    }
  }

  return <div className="composer-wrap">
    {mentionOpen && <div className="agent-mention-picker" id="agent-mention-options" role="listbox" aria-label="选择 Agent">
      {matches.map((agent) => <button
        className="agent-mention-option"
        key={agent.id}
        type="button"
        role="option"
        aria-selected="false"
        onMouseDown={(event) => {
          event.preventDefault()
          selectAgent(agent)
        }}
      >
        <span className={`agent-mention-avatar agent-mention-${agent.id}`}>{agent.name.at(0)}</span>
        <span className="agent-mention-copy">
          <strong>{agent.name} <small>@{agent.id}</small></strong>
          <span>{agent.description}</span>
        </span>
      </button>)}
    </div>}
    <div className={`composer ${error ? 'composer-error' : ''}`}>
      <textarea
        ref={textareaRef}
        value={goal}
        onChange={(event) => {
          setGoal(event.target.value)
          updateMention(event.target.value, event.target.selectionStart)
          if (error) setError('')
        }}
        onClick={(event) => updateMention(event.currentTarget.value, event.currentTarget.selectionStart)}
        onKeyUp={(event) => {
          if (!['Enter', 'Escape'].includes(event.key)) {
            updateMention(event.currentTarget.value, event.currentTarget.selectionStart)
          }
        }}
        onKeyDown={(event) => {
          if (event.key === 'Escape' && mention) {
            event.preventDefault()
            setMention(null)
            return
          }
          if (event.key === 'Enter' && mentionOpen && !event.ctrlKey && !event.metaKey) {
            event.preventDefault()
            selectAgent(matches[0])
            return
          }
          if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
            event.preventDefault()
            void submit()
          }
        }}
        rows={2}
        maxLength={10000}
        placeholder="描述你希望 Agent 完成的任务…"
        disabled={busy}
        aria-autocomplete="list"
        aria-controls="agent-mention-options"
        aria-expanded={mentionOpen}
      />
      <div className="flex items-end gap-2">
        {running && <button className="cancel-button" onClick={() => void onCancel()} disabled={busy} title="取消当前任务"><Square size={15}/></button>}
        <button className="send-button" onClick={() => void submit()} disabled={busy || !goal.trim()} title="发送任务"><Send size={18}/></button>
      </div>
    </div>
    <div className="mt-2 flex justify-between px-1 text-xs text-zinc-600">
      <span className="text-red-400">{error}</span>
      <span>输入 @ 选择 Agent · Ctrl / ⌘ + Enter 发送</span>
    </div>
  </div>
}
