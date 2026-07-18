import type { ConversationMessage, PendingConfirmation, Task, TaskContract, TaskEvent } from '../types/api'

export const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '')

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status?: number,
    readonly code = 'UNKNOWN_ERROR',
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

function errorMessage(value: unknown): string | undefined {
  if (typeof value === 'string') return value
  if (Array.isArray(value)) {
    return value.map((item) => {
      if (typeof item === 'object' && item && 'msg' in item) return String(item.msg)
      return String(item)
    }).join('；')
  }
  return undefined
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...init?.headers },
    })
  } catch {
    throw new ApiError('无法连接后端服务，请确认 FastAPI 已启动。', undefined, 'NETWORK_ERROR')
  }

  if (!response.ok) {
    let detail: unknown
    try {
      const body = await response.json() as { detail?: unknown }
      detail = body.detail
    } catch {
      detail = undefined
    }
    throw new ApiError(errorMessage(detail) || `请求失败（${response.status}）`, response.status, 'HTTP_ERROR')
  }

  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export function listTasks(): Promise<Task[]> {
  return request('/tasks?limit=50&offset=0')
}

export function getTask(taskId: string): Promise<Task> {
  return request(`/tasks/${taskId}`)
}

export function getTaskEvents(taskId: string): Promise<TaskEvent[]> {
  return request(`/tasks/${taskId}/events`)
}

export function getTaskMessages(taskId: string): Promise<ConversationMessage[]> {
  return request(`/tasks/${taskId}/messages?after=0&limit=500`)
}

export function getPendingConfirmations(taskId: string): Promise<PendingConfirmation[]> {
  return request(`/tasks/${taskId}/confirmations/pending`)
}

export function decideConfirmation(
  taskId: string,
  confirmation: PendingConfirmation,
  approved: boolean,
): Promise<unknown> {
  return request(`/tasks/${taskId}/confirmations`, {
    method: 'POST',
    body: JSON.stringify({
      plan_id: confirmation.plan_id,
      plan_version: confirmation.plan_version,
      call_hash: confirmation.call_hash,
      approved,
      decided_by: 'local-user',
    }),
  })
}

export function buildTaskContract(goal: string): TaskContract {
  const taskId = crypto.randomUUID()
  return {
    task_id: taskId,
    goal: goal.trim(),
    inputs: {},
    constraints: [],
    acceptance_criteria: [{
      description: '任务目标已完成并返回可验证的结果',
      verification_method: '检查 Agent 最终状态与执行证据',
    }],
    allowed_tools: [
      'list_workspace_files',
      'read_workspace_file',
      'create_workspace_file',
      'modify_workspace_file',
      'run_allowlisted_check',
    ],
    denied_tools: [],
    failure_policy: '遇到不可恢复错误时停止执行并报告原因',
  }
}

export function createTask(goal: string): Promise<Task> {
  return request('/tasks', { method: 'POST', body: JSON.stringify(buildTaskContract(goal)) })
}

export function cancelTask(taskId: string): Promise<Task> {
  return request(`/tasks/${taskId}/cancel`, { method: 'POST' })
}
