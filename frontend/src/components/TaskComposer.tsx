import { Send, Square } from 'lucide-react'
import { useRef, useState } from 'react'

interface TaskComposerProps { busy: boolean; running: boolean; onSubmit: (goal: string) => Promise<boolean>; onCancel: () => Promise<void> }
type AgentId = 'scout' | 'researcher' | 'worker' | 'reviewer' | 'oracle' | 'delegate'
interface AgentOption { id: AgentId; name: string; description: string }
interface MentionQuery { start: number; end: number; query: string }

const agentOptions: AgentOption[] = [
  { id: 'scout', name: 'Scout', description: 'Local codebase reconnaissance' },
  { id: 'researcher', name: 'Researcher', description: 'External documentation and facts' },
  { id: 'worker', name: 'Worker', description: 'Implementation and validation' },
  { id: 'reviewer', name: 'Reviewer', description: 'Review, testing and verification' },
  { id: 'oracle', name: 'Oracle', description: 'Adversarial second opinion' },
  { id: 'delegate', name: 'Delegate', description: 'General-purpose delegation' },
]

function mentionAtCursor(value: string, cursor: number): MentionQuery | null {
  const prefix = value.slice(0, cursor)
  const match = prefix.match(/(?:^|\s)@([^\s@]*)$/)
  if (!match || match.index === undefined) return null
  const start = match.index + (match[0].startsWith('@') ? 0 : 1)
  return { start, end: cursor, query: match[1].toLowerCase() }
}

function selectedAgentIds(value: string): Set<string> {
  return new Set(Array.from(value.matchAll(/(?:^|\s)@(scout|researcher|worker|reviewer|oracle|delegate)(?=\s|$)/g), (match) => match[1]))
}

export function TaskComposer({ busy, running, onSubmit, onCancel }: TaskComposerProps) {
  const [goal, setGoal] = useState('')
  const [error, setError] = useState('')
  const [mention, setMention] = useState<MentionQuery | null>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const selected = selectedAgentIds(goal)
  const matches = mention ? agentOptions.filter((agent) => !selected.has(agent.id) && `${agent.id} ${agent.name}`.toLowerCase().includes(mention.query)) : []
  const mentionOpen = Boolean(mention && matches.length > 0)
  const updateMention = (value: string, cursor: number | null) => setMention(cursor === null ? null : mentionAtCursor(value, cursor))
  const selectAgent = (agent: AgentOption) => {
    if (!mention) return
    const insertion = `@${agent.id} `
    const nextGoal = `${goal.slice(0, mention.start)}${insertion}${goal.slice(mention.end)}`
    const nextCursor = mention.start + insertion.length
    setGoal(nextGoal); setMention(null)
    requestAnimationFrame(() => { textareaRef.current?.focus(); textareaRef.current?.setSelectionRange(nextCursor, nextCursor) })
  }
  const submit = async () => {
    if (!goal.trim()) { setError('Enter a task goal'); return }
    setError('')
    if (await onSubmit(goal)) { setGoal(''); setMention(null) }
  }
  return <div className="composer-wrap">
    {mentionOpen && <div className="agent-mention-picker" id="agent-mention-options" role="listbox" aria-label="Select an agent">
      {matches.map((agent) => <button className="agent-mention-option" key={agent.id} type="button" role="option" onMouseDown={(event) => { event.preventDefault(); selectAgent(agent) }}>
        <span className={`agent-mention-avatar agent-mention-${agent.id}`}>{agent.name.at(0)}</span><span className="agent-mention-copy"><strong>{agent.name} <small>@{agent.id}</small></strong><span>{agent.description}</span></span>
      </button>)}
    </div>}
    <div className={`composer ${error ? 'composer-error' : ''}`}>
      <textarea ref={textareaRef} value={goal} onChange={(event) => { setGoal(event.target.value); updateMention(event.target.value, event.target.selectionStart); if (error) setError('') }} onClick={(event) => updateMention(event.currentTarget.value, event.currentTarget.selectionStart)} onKeyUp={(event) => { if (!['Enter', 'Escape'].includes(event.key)) updateMention(event.currentTarget.value, event.currentTarget.selectionStart) }} onKeyDown={(event) => { if (event.key === 'Escape' && mention) { event.preventDefault(); setMention(null); return }; if (event.key === 'Enter' && mentionOpen && !event.ctrlKey && !event.metaKey) { event.preventDefault(); selectAgent(matches[0]); return }; if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) { event.preventDefault(); void submit() } }} rows={2} maxLength={10000} placeholder="Describe the task; use @ to select a capability agent" disabled={busy} aria-autocomplete="list" aria-controls="agent-mention-options" aria-expanded={mentionOpen} />
      <div className="flex items-end gap-2">{running && <button className="cancel-button" onClick={() => void onCancel()} disabled={busy} title="Cancel task"><Square size={15}/></button>}<button className="send-button" onClick={() => void submit()} disabled={busy || !goal.trim()} title="Send task"><Send size={18}/></button></div>
    </div>
    <div className="mt-2 flex justify-between px-1 text-xs text-zinc-600"><span className="text-red-400">{error}</span><span>Enter a goal · Ctrl / Cmd + Enter to send</span></div>
  </div>
}
