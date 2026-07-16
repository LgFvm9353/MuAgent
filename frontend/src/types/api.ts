export type TaskState =
  | 'PENDING' | 'ANALYZING' | 'DECIDING' | 'PLANNING' | 'POLICY_CHECK'
  | 'WAITING_CONFIRMATION' | 'EXECUTING' | 'VERIFYING' | 'REPLANNING'
  | 'NEEDS_REVIEW' | 'SUCCEEDED' | 'FAILED' | 'CANCELLED' | 'REJECTED'
  | 'BUDGET_EXCEEDED'

export interface Task {
  id: string
  trace_id: string
  goal: string
  state: TaskState
  version: number
  cancel_requested: boolean
  created_at: string
  updated_at: string
}

export interface TaskEvent {
  id: number
  event_type: string
  from_state: TaskState | null
  to_state: TaskState | null
  payload: Record<string, unknown>
  created_at: string
}

export interface TaskContract {
  task_id: string
  goal: string
  inputs: Record<string, string>
  constraints: string[]
  acceptance_criteria: Array<{ description: string; verification_method: string }>
  allowed_tools: string[]
  denied_tools: string[]
  workspace_relative: string
  failure_policy: string
}

export interface ChatMessage {
  id: string
  role: 'user' | 'agent'
  title?: string
  content: string
  createdAt: string
  tone?: 'default' | 'success' | 'warning' | 'error'
  details?: Record<string, unknown>
}

export type StreamStatus = 'idle' | 'connecting' | 'connected' | 'reconnecting' | 'closed' | 'error'
export type ToastTone = 'success' | 'warning' | 'error'
