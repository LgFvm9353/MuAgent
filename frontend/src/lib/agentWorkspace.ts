import { apiDateTimestamp } from './dateTime'
import type { AgentWorkspaceState, ConversationMessage, Task, TaskEvent, WorkspaceAgentId, WorkspaceAgentState, WorkspaceAgentStatus } from '../types/api'

const agentIds: WorkspaceAgentId[] = ['scout', 'researcher', 'planner', 'worker', 'reviewer', 'context-builder', 'oracle', 'delegate']
const initialSummary: Record<WorkspaceAgentId, string> = Object.fromEntries(agentIds.map((id) => [id, 'Waiting for selection'])) as Record<WorkspaceAgentId, string>
function initialAgent(id: WorkspaceAgentId): WorkspaceAgentState { return { id, status: 'idle', phase: 'Waiting', summary: initialSummary[id], startedAt: null, completedAt: null, updatedAt: null } }
function copyInitialState(): AgentWorkspaceState { return Object.fromEntries(agentIds.map((id) => [id, initialAgent(id)])) as AgentWorkspaceState }
function normalizeAgentId(agentId: string): WorkspaceAgentId | null { return agentIds.includes(agentId as WorkspaceAgentId) ? agentId as WorkspaceAgentId : null }
function lifecycleStatus(message: ConversationMessage): WorkspaceAgentStatus | null {
  const explicit = message.content.status
  if (explicit === 'waiting' || explicit === 'running' || explicit === 'completed' || explicit === 'failed') return explicit
  if (message.phase === 'specialist_failed') return 'failed'
  if (message.phase === 'planning' || message.phase === 'verification' || message.phase === 'specialist_completed') return 'completed'
  if (message.phase === 'specialist' || message.phase === 'fanout' || message.phase === 'synthesis' || message.phase === 'replanning') return message.message_type === 'collaboration' ? 'running' : 'completed'
  return null
}
function phaseLabel(agentId: WorkspaceAgentId, phase: string): string { return ({ specialist: 'Specialist analysis', specialist_completed: 'Specialist complete', specialist_failed: 'Specialist failed', planning: 'Execution plan', replanning: 'Replanning', verification: 'Verification', synthesis: 'Parent synthesis' } as Record<string, string>)[phase] || `${agentId} collaboration` }
function applyStatus(current: WorkspaceAgentState, status: WorkspaceAgentStatus, phase: string, summary: string, timestamp: string): WorkspaceAgentState {
  return { ...current, status, phase, summary, startedAt: status === 'running' && current.status !== 'running' ? timestamp : current.startedAt, completedAt: status === 'completed' || status === 'failed' ? timestamp : null, updatedAt: timestamp }
}
function applyMessage(state: AgentWorkspaceState, message: ConversationMessage): void {
  const agentId = normalizeAgentId(message.agent_id); if (!agentId) return
  const status = lifecycleStatus(message); if (status) state[agentId] = applyStatus(state[agentId], status, phaseLabel(agentId, message.phase), message.summary, message.created_at)
}
function applyTaskFallback(state: AgentWorkspaceState, task: Task): void {
  if (task.state === 'PENDING') return
  if (task.state === 'ANALYZING') for (const id of agentIds) if (state[id].status === 'idle') state[id] = applyStatus(state[id], 'running', 'Selecting specialists', 'Parent is selecting capability agents.', task.updated_at)
  if (task.state === 'VERIFYING' && state.reviewer.status === 'idle') state.reviewer = applyStatus(state.reviewer, 'running', 'Verification', 'Reviewer is verifying execution.', task.updated_at)
  if (['FAILED', 'CANCELLED', 'REJECTED', 'BUDGET_EXCEEDED'].includes(task.state)) for (const id of agentIds) if (state[id].status === 'running' || state[id].status === 'waiting') state[id] = applyStatus(state[id], task.state === 'FAILED' ? 'failed' : 'completed', state[id].phase, task.state === 'FAILED' ? 'Task failed.' : 'Task ended.', task.updated_at)
}
export function deriveAgentWorkspace(task: Task, events: TaskEvent[], messages: ConversationMessage[]): AgentWorkspaceState {
  const state = copyInitialState()
  const orderedMessages = messages.filter((message) => message.task_id === task.id).sort((left, right) => apiDateTimestamp(left.created_at) - apiDateTimestamp(right.created_at) || left.id - right.id)
  for (const message of orderedMessages) applyMessage(state, message)
  const latest = [...events].filter((event) => event.to_state).sort((left, right) => apiDateTimestamp(left.created_at) - apiDateTimestamp(right.created_at) || left.id - right.id).at(-1)
  applyTaskFallback(state, latest?.to_state ? { ...task, state: latest.to_state, updated_at: latest.created_at } : task)
  return state
}

/** Chat turns have no Task record, but still publish specialist lifecycle messages. */
export function deriveConversationAgentWorkspace(messages: ConversationMessage[]): AgentWorkspaceState {
  const state = copyInitialState()
  const orderedMessages = [...messages]
    .filter((message) => message.message_type === 'collaboration')
    .sort((left, right) => apiDateTimestamp(left.created_at) - apiDateTimestamp(right.created_at) || left.id - right.id)
  for (const message of orderedMessages) applyMessage(state, message)
  return state
}
