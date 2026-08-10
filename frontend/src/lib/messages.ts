import type { ChatMessage, ConversationMessage, TaskEvent, TaskState } from '../types/api'
import { apiDateTimestamp } from './dateTime'

const stateCopy: Record<TaskState, { content: string; tone?: ChatMessage['tone'] }> = {
  PENDING: { content: 'Task queued.' }, ANALYZING: { content: 'Parent is selecting and running specialists.' }, DECIDING: { content: 'Agents are evaluating options.' }, PLANNING: { content: 'Preparing the execution plan.' }, POLICY_CHECK: { content: 'Checking tool policy and execution risk.' }, WAITING_CONFIRMATION: { content: 'Human confirmation is required.', tone: 'warning' }, EXECUTING: { content: 'Worker is executing the approved plan.' }, VERIFYING: { content: 'Reviewer is verifying execution.', }, REPLANNING: { content: 'Updating the execution plan.', tone: 'warning' }, NEEDS_REVIEW: { content: 'Task needs human review.', tone: 'warning' }, SUCCEEDED: { content: 'Task completed.', tone: 'success' }, FAILED: { content: 'Task failed.', tone: 'error' }, CANCELLED: { content: 'Task cancelled.', tone: 'warning' }, REJECTED: { content: 'Task rejected by policy.', tone: 'error' }, BUDGET_EXCEEDED: { content: 'Task budget exceeded.', tone: 'error' },
}

export function conversationToMessage(message: ConversationMessage): ChatMessage {
  const isUser = message.role === 'user'
  const isFinal = message.message_type === 'final_summary' || message.message_type === 'collaboration_result' || message.message_type === 'parallel_result'
  const isError = message.message_type === 'agent_error'
  return { id: `message-${message.id}`, role: isUser ? 'user' : 'agent', title: isUser ? undefined : isFinal ? 'Parent result' : `${message.agent_id} · ${message.phase}`, content: typeof message.content.text === 'string' ? message.content.text : message.summary, createdAt: message.created_at, tone: isError ? 'error' : isFinal ? message.content.state === 'SUCCEEDED' ? 'success' : 'warning' : undefined, details: isUser ? undefined : message.content, agentId: message.agent_id, phase: message.phase, isFinal }
}

function persistedMessageId(value: string): number | null {
  const match = /^message-(\d+)$/.exec(value)
  return match ? Number(match[1]) : null
}

/** Sort the rendered timeline by the server's actual time value, not the
 * lexical representation of timestamps with different timezone/fraction formats. */
export function compareChatMessages(left: ChatMessage, right: ChatMessage): number {
  const leftId = persistedMessageId(left.id)
  const rightId = persistedMessageId(right.id)
  // ConversationMessage.id is the authoritative causal order for persisted
  // user/agent messages, even when rows were delivered by different streams.
  if (leftId !== null && rightId !== null && leftId !== rightId) return leftId - rightId

  const leftTime = apiDateTimestamp(left.createdAt)
  const rightTime = apiDateTimestamp(right.createdAt)
  if (Number.isFinite(leftTime) && Number.isFinite(rightTime) && leftTime !== rightTime) {
    return leftTime - rightTime
  }
  return 0
}

export function eventToMessage(event: TaskEvent): ChatMessage {
  if (event.event_type === 'state_transition' && event.to_state) {
    const copy = stateCopy[event.to_state]
    return { id: `event-${event.id}`, role: 'agent', title: event.to_state === 'SUCCEEDED' ? 'Execution complete' : 'Task progress', content: event.to_state === 'FAILED' && typeof event.payload.message === 'string' ? event.payload.message : copy.content, createdAt: event.created_at, tone: copy.tone, details: event.payload }
  }
  return { id: `event-${event.id}`, role: 'agent', title: 'Task event', content: `Received event: ${event.event_type}`, createdAt: event.created_at, details: event.payload }
}
