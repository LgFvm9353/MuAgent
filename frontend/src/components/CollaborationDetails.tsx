import { Check, ChevronDown, LoaderCircle, TriangleAlert } from 'lucide-react'
import { AgentWorkspace } from './AgentWorkspace'
import { TaskArtifactsPanel } from './TaskArtifactsPanel'
import { TaskResultPanel } from './TaskResultPanel'
import { parseApiDate } from '../lib/dateTime'
import type { AgentWorkspaceState, Task, TaskEvent, TaskResult } from '../types/api'

const terminalStates = new Set(['NEEDS_REVIEW', 'SUCCEEDED', 'FAILED', 'CANCELLED', 'REJECTED', 'BUDGET_EXCEEDED'])
const failedStates = new Set(['FAILED', 'REJECTED', 'BUDGET_EXCEEDED'])

function eventLabel(event: TaskEvent) {
  if (event.event_type === 'task_created') return '任务已创建'
  if (event.event_type === 'state_transition' && event.to_state) {
    return event.to_state.replaceAll('_', ' ')
  }
  return event.event_type.replaceAll('_', ' ')
}

export function CollaborationDetails({ task, agents, events, result }: {
  task: Task
  agents: AgentWorkspaceState
  events: TaskEvent[]
  result: TaskResult | null
}) {
  const completed = terminalStates.has(task.state)
  const failed = failedStates.has(task.state)
  const activeAgents = Object.values(agents).filter((agent) => agent.status !== 'idle').length
  const Icon = failed ? TriangleAlert : completed ? Check : LoaderCircle
  const summary = failed
    ? '协作未完成'
    : completed
      ? `${activeAgents || 1} 个 Agent 已完成协作`
      : `${activeAgents || 1} 个 Agent 正在协作`

  return <details className="collaboration-details">
    <summary>
      <span className={`collaboration-icon${failed ? ' collaboration-icon-error' : completed ? ' collaboration-icon-success' : ''}`}>
        <Icon size={15} className={completed ? undefined : 'agent-status-spinner'}/>
      </span>
      <span className="collaboration-summary"><strong>{summary}</strong><small>{task.state.replaceAll('_', ' ')}</small></span>
      <span className="collaboration-toggle"><ChevronDown size={15}/>展开详情</span>
    </summary>
    <div className="collaboration-body">
      <AgentWorkspace agents={agents} compact/>
      {events.length > 0 && <section className="collaboration-timeline" aria-label="执行过程">
        <h4>执行过程</h4>
        <ol>{events.map((event) => <li key={event.id}>
          <span/>
          <div><strong>{eventLabel(event)}</strong><time dateTime={event.created_at}>{parseApiDate(event.created_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}</time></div>
        </li>)}</ol>
      </section>}
      <TaskArtifactsPanel taskId={task.id} refreshKey={task.updated_at}/>
      {result && <TaskResultPanel result={result}/>}
    </div>
  </details>
}
