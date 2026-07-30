export type TaskState =
  | 'PENDING' | 'ANALYZING' | 'DECIDING' | 'PLANNING' | 'POLICY_CHECK'
  | 'WAITING_CONFIRMATION' | 'EXECUTING' | 'VERIFYING' | 'REPLANNING'
  | 'NEEDS_REVIEW' | 'SUCCEEDED' | 'FAILED' | 'CANCELLED' | 'REJECTED'
  | 'BUDGET_EXCEEDED'

export interface ConversationThread {
  id: string
  title: string
  created_at: string
  updated_at: string
  latest_task_id: string | null
  latest_task_state: TaskState | null
}

export type CollaborationMode = 'parallel' | 'serial'
export type CollaborationPhase =
  | 'routing' | 'parallel' | 'serial' | 'handoff' | 'synthesis'
  | 'waiting_confirmation' | 'completed' | 'failed' | 'needs_review'

export interface SkillSummary {
  id: string
  version: string
  description: string
  allowed_agents: WorkspaceAgentId[]
}

export interface McpServerStatus {
  id: string
  transport: 'stdio' | 'streamable_http'
  enabled: boolean
  status: 'disconnected' | 'connecting' | 'healthy' | 'unhealthy'
}

export interface ToolCallSummary {
  id: string
  agent_run_id: string | null
  canonical_tool_id: string
  source: 'local' | 'mcp'
  risk: 'low' | 'medium' | 'high'
  status: string
  arguments: Record<string, unknown>
}

export interface AgentRunSummary {
  id: string
  agent_id: WorkspaceAgentId
  model: string
  status: WorkspaceAgentStatus | 'queued' | 'waiting_confirmation' | 'cancelled'
  phase: CollaborationPhase | null
  skill_id: string | null
}

export interface ConversationTurn {
  turn_id: string | null
  task_id: string | null
  conversation_id: string
  state: TaskState | 'running' | 'completed' | 'failed' | 'escalated'
  route_source: 'explicit' | 'rule' | 'model' | 'fallback' | null
  collaboration_mode: CollaborationMode | null
  synthesize: boolean
  selected_agents: WorkspaceAgentId[]
  agent_runs: AgentRunSummary[]
}

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
  task_id: string | null
  conversation_id: string | null
  turn_id: string | null
  agent_run_id: string | null
  routing_decision_id: string | null
  handoff_id: string | null
  reply_to_message_id: number | null
  agent_id: string
  role: 'agent' | 'system' | 'tool' | 'user'
  message_type: string
  phase: string
  summary: string
  content: Record<string, unknown>
  mentions: string[]
  routing_metadata: Record<string, unknown>
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

export interface TaskArtifact {
  path: string
  name: string
  size_bytes: number
  modified_at: string
  preview_type: ArtifactPreviewType
}

export interface TaskArtifactContent extends TaskArtifact {
  content: string
}

export type ArtifactPreviewType = 'text' | 'markdown' | 'json' | 'code' | 'unsupported'

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

export type WorkspaceAgentId = 'architect' | 'reviewer' | 'designer'
export type WorkspaceAgentStatus = 'idle' | 'waiting' | 'running' | 'completed' | 'failed'

export interface WorkspaceAgentState {
  id: WorkspaceAgentId
  status: WorkspaceAgentStatus
  phase: string
  summary: string
  startedAt: string | null
  completedAt: string | null
  updatedAt: string | null
}

export type AgentWorkspaceState = Record<WorkspaceAgentId, WorkspaceAgentState>
