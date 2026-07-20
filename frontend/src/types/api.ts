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

export interface ConversationMessage {
  id: number
  task_id: string
  agent_id: string
  role: 'agent' | 'system' | 'tool'
  message_type: string
  phase: string
  summary: string
  content: Record<string, unknown>
  source_id: string
  created_at: string
}

export interface PendingConfirmation {
  plan_id: string
  plan_version: number
  step_id: string
  tool_name: string
  arguments: Record<string, unknown>
  impact: string
  risk: string
  call_hash: string
}

export interface TaskContract {
  task_id: string
  goal: string
  inputs: Record<string, string>
  constraints: string[]
  acceptance_criteria: Array<{ description: string; verification_method: string }>
  allowed_tools: string[]
  denied_tools: string[]
  failure_policy: string
}

export interface TaskResult {
  task: Task
  plan: { steps?: Array<Record<string, unknown>> } | null
  plan_version: number | null
  steps: Array<{ id: string; status: string; content: Record<string, unknown> }>
  tool_calls: Array<{
    id: string
    step_id: string
    tool_name: string
    status: string
    arguments: Record<string, unknown>
    result: Record<string, unknown> | null
    error_type: string | null
  }>
  verification: Record<string, unknown> | null
  evidence: Array<{
    id: string
    kind: string
    content: Record<string, unknown>
    sha256: string | null
    created_at: string
  }>
  usage: {
    input_tokens: number
    output_tokens: number
    estimated_cost_usd: number
    latency_ms: number
  }
}

export interface ChatMessage {
  id: string
  role: 'user' | 'agent'
  title?: string
  content: string
  createdAt: string
  tone?: 'default' | 'success' | 'warning' | 'error'
  details?: Record<string, unknown>
  agentId?: string
  phase?: string
}

export type StreamStatus = 'idle' | 'connecting' | 'connected' | 'reconnecting' | 'closed' | 'error'
export type ToastTone = 'success' | 'warning' | 'error'
