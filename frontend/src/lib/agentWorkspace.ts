import { apiDateTimestamp } from './dateTime'
import type {
  AgentWorkspaceState,
  ConversationMessage,
  Task,
  TaskEvent,
  WorkspaceAgentId,
  WorkspaceAgentState,
  WorkspaceAgentStatus,
} from '../types/api'

const agentIds: WorkspaceAgentId[] = ['architect', 'reviewer', 'designer']

const initialSummary: Record<WorkspaceAgentId, string> = {
  architect: '等待分析任务并协调专家。',
  reviewer: '等待 Architect 委派技术审查。',
  designer: '等待 Architect 委派产品设计。',
}

function initialAgent(id: WorkspaceAgentId): WorkspaceAgentState {
  return {
    id,
    status: 'idle',
    phase: '等待开始',
    summary: initialSummary[id],
    startedAt: null,
    completedAt: null,
    updatedAt: null,
  }
}

function copyInitialState(): AgentWorkspaceState {
  return {
    architect: initialAgent('architect'),
    reviewer: initialAgent('reviewer'),
    designer: initialAgent('designer'),
  }
}

function normalizeAgentId(agentId: string): WorkspaceAgentId | null {
  if (agentIds.includes(agentId as WorkspaceAgentId)) return agentId as WorkspaceAgentId
  if (agentId === 'architect_planner') return 'architect'
  if (agentId === 'verifier') return 'reviewer'
  return null
}

function lifecycleStatus(message: ConversationMessage): WorkspaceAgentStatus | null {
  const explicit = message.content.status
  if (explicit === 'waiting' || explicit === 'running' || explicit === 'completed' || explicit === 'failed') {
    return explicit
  }
  if (message.phase === 'specialist_failed') return 'failed'
  if (message.phase === 'handoff' || message.phase === 'planning' || message.phase === 'verification') {
    return 'completed'
  }
  if (message.phase === 'analysis' || message.phase === 'review' || message.phase === 'design' || message.phase === 'synthesis' || message.phase === 'replanning') {
    return message.message_type === 'collaboration' ? 'running' : 'completed'
  }
  return null
}

function phaseLabel(agentId: WorkspaceAgentId, phase: string): string {
  const labels: Record<string, string> = {
    analysis: '分析任务',
    delegation: '委派专家',
    synthesis: '汇总专家结果',
    planning: '生成执行计划',
    replanning: '调整执行计划',
    review: '技术与测试审查',
    verification: '验证执行结果',
    design: '产品与交互设计',
    handoff: '交付专家结果',
    specialist_failed: '专家执行失败',
  }
  return labels[phase] || `${agentId} 协作`
}

function applyStatus(
  current: WorkspaceAgentState,
  status: WorkspaceAgentStatus,
  phase: string,
  summary: string,
  timestamp: string,
): WorkspaceAgentState {
  const starting = status === 'running' && current.status !== 'running'
  return {
    ...current,
    status,
    phase,
    summary,
    startedAt: starting ? timestamp : current.startedAt,
    completedAt: status === 'completed' || status === 'failed' ? timestamp : null,
    updatedAt: timestamp,
  }
}

function applyMessage(state: AgentWorkspaceState, message: ConversationMessage): void {
  const agentId = normalizeAgentId(message.agent_id)
  if (!agentId) return

  const status = lifecycleStatus(message)
  if (status) {
    state[agentId] = applyStatus(
      state[agentId],
      status,
      phaseLabel(agentId, message.phase),
      message.summary,
      message.created_at,
    )
  }

  if (message.phase === 'delegation') {
    const targets = Array.isArray(message.content.target_agents)
      ? message.content.target_agents.filter((target): target is WorkspaceAgentId => target === 'reviewer' || target === 'designer')
      : ['reviewer', 'designer'] as WorkspaceAgentId[]
    for (const target of targets) {
      if (state[target].status === 'idle') {
        state[target] = applyStatus(
          state[target],
          'waiting',
          '等待执行',
          `已收到 Architect 委派，等待启动。`,
          message.created_at,
        )
      }
    }
  }
}

function applyTaskFallback(state: AgentWorkspaceState, task: Task): void {
  if (task.state === 'PENDING') return
  if (task.state === 'ANALYZING' && state.architect.status === 'idle') {
    state.architect = applyStatus(state.architect, 'running', '分析任务', 'Architect 正在分析任务。', task.updated_at)
  }
  if (task.state === 'VERIFYING' && state.reviewer.phase !== '验证执行结果') {
    state.reviewer = applyStatus(state.reviewer, 'running', '验证执行结果', 'Reviewer 正在验证执行结果。', task.updated_at)
  }

  if (task.state === 'FAILED' || task.state === 'CANCELLED' || task.state === 'REJECTED' || task.state === 'BUDGET_EXCEEDED') {
    for (const id of agentIds) {
      if (state[id].status === 'running' || state[id].status === 'waiting') {
        state[id] = applyStatus(
          state[id],
          task.state === 'FAILED' ? 'failed' : 'completed',
          state[id].phase,
          task.state === 'FAILED' ? '任务终止，Agent 未完成当前阶段。' : '任务已结束。',
          task.updated_at,
        )
      }
    }
  }
}

export function deriveAgentWorkspace(
  task: Task,
  events: TaskEvent[],
  messages: ConversationMessage[],
): AgentWorkspaceState {
  const state = copyInitialState()
  const orderedMessages = messages
    .filter((message) => message.task_id === task.id)
    .sort((left, right) => {
      const timeDifference = apiDateTimestamp(left.created_at) - apiDateTimestamp(right.created_at)
      return timeDifference || left.id - right.id
    })

  for (const message of orderedMessages) applyMessage(state, message)

  const latestTaskUpdate = [...events]
    .filter((event) => event.to_state)
    .sort((left, right) => {
      const timeDifference = apiDateTimestamp(left.created_at) - apiDateTimestamp(right.created_at)
      return timeDifference || left.id - right.id
    })
    .at(-1)
  applyTaskFallback(state, latestTaskUpdate?.to_state
    ? { ...task, state: latestTaskUpdate.to_state, updated_at: latestTaskUpdate.created_at }
    : task)

  return state
}
