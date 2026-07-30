import type { ChatMessage, ConversationMessage, TaskEvent, TaskState } from '../types/api'

const stateCopy: Record<TaskState, { content: string; tone?: ChatMessage['tone'] }> = {
  PENDING: { content: '任务已进入队列，等待 Agent 接手。' },
  ANALYZING: { content: 'Agent 正在分析任务目标和约束。' },
  DECIDING: { content: '多个 Agent 正在评估可行方案。' },
  PLANNING: { content: 'Agent 正在生成执行计划。' },
  POLICY_CHECK: { content: '正在检查工具权限与执行风险。' },
  WAITING_CONFIRMATION: { content: '任务需要人工确认后才能继续。', tone: 'warning' },
  EXECUTING: { content: 'Agent 正在执行计划中的步骤。' },
  VERIFYING: { content: 'Agent 正在验证执行结果。' },
  REPLANNING: { content: '验证发现偏差，Agent 正在调整计划。', tone: 'warning' },
  NEEDS_REVIEW: { content: '任务需要人工复核。', tone: 'warning' },
  SUCCEEDED: { content: '任务已成功完成。', tone: 'success' },
  FAILED: { content: '任务执行失败，请查看详细信息。', tone: 'error' },
  CANCELLED: { content: '任务已取消。', tone: 'warning' },
  REJECTED: { content: '任务因策略限制被拒绝。', tone: 'error' },
  BUDGET_EXCEEDED: { content: '任务已达到预算上限。', tone: 'error' },
}

export function conversationToMessage(message: ConversationMessage): ChatMessage {
  const labels: Record<string, Record<string, string> | string> = {
    architect: {
      analysis: '架构师 · 深度分析',
      delegation: '架构师 · 任务委派',
      synthesis: '架构师 · 汇总方案',
      planning: '架构师 · 最终计划',
      replanning: '架构师 · 调整计划',
    },
    reviewer: {
      review: '审查员 · 代码与测试',
      verification: '审查员 · 执行验证',
      handoff: '审查员 · 结果交付',
      specialist_failed: '审查员 · 执行失败',
    },
    designer: {
      design: '设计师 · 创意与体验',
      handoff: '设计师 · 结果交付',
      specialist_failed: '设计师 · 执行失败',
    },
    architect_planner: '架构师 · 最终计划',
    verifier: '审查员 · 执行验证',
    executor: 'Executor · 工具执行',
  }
  const label = labels[message.agent_id]
  const agentTitle = typeof label === 'string'
    ? label
    : label?.[message.phase] || message.agent_id
  const isUser = message.role === 'user'
  const isFinal = message.message_type === 'final_summary' || message.message_type === 'collaboration_result'
  const collaborationCopy: Record<string, string> = {
    parallel_started: '多 Agent · 并行分析',
    synthesis_started: 'Lead · 汇总中',
    handoff_requested: 'Agent · 协作交接',
    handoff_rejected: 'Agent · 交接已拒绝',
    collaboration_failed: '多 Agent · 协作失败',
  }
  const fullText = typeof message.content.text === 'string'
    ? message.content.text
    : message.summary
  return {
    id: `message-${message.id}`,
    role: isUser ? 'user' : 'agent',
    title: isUser ? undefined : isFinal ? '团队最终答案' : collaborationCopy[message.message_type] || agentTitle,
    content: fullText,
    createdAt: message.created_at,
    tone: isFinal
      ? message.content.state === 'SUCCEEDED' ? 'success' : 'warning'
      : undefined,
    details: isUser ? undefined : message.content,
    agentId: message.agent_id,
    phase: message.phase,
  }
}

export function eventToMessage(event: TaskEvent): ChatMessage {
  if (event.event_type === 'task_created') {
    return {
      id: `event-${event.id}`,
      role: 'agent',
      title: '任务已创建',
      content: '已收到你的目标，正在启动多 Agent 协作流程。',
      createdAt: event.created_at,
      details: event.payload,
    }
  }

  if (event.event_type === 'state_transition' && event.to_state) {
    const copy = stateCopy[event.to_state]
    const safeMessage = event.to_state === 'FAILED' && typeof event.payload.message === 'string'
      ? event.payload.message
      : copy.content
    return {
      id: `event-${event.id}`,
      role: 'agent',
      title: event.to_state === 'SUCCEEDED' ? '执行完成' : '执行进度',
      content: safeMessage,
      createdAt: event.created_at,
      tone: copy.tone,
      details: event.payload,
    }
  }

  return {
    id: `event-${event.id}`,
    role: 'agent',
    title: 'Agent 事件',
    content: `收到事件：${event.event_type}`,
    createdAt: event.created_at,
    details: event.payload,
  }
}
