import { Bot, Menu, Plus, Wifi, WifiOff } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AgentWorkingIndicator } from './components/AgentWorkspace'
import { CollaborationDetails } from './components/CollaborationDetails'
import { Conversation } from './components/Conversation'
import { ConversationSidebar } from './components/ConversationSidebar'
import { TaskComposer } from './components/TaskComposer'
import { ToastProvider, useToast } from './components/ToastProvider'
import { useConversationStream } from './hooks/useConversationStream'
import { useTaskStream } from './hooks/useTaskStream'
import {
  ApiError,
  cancelTask,
  createConversation,
  getConversation,
  getConversationMessages,
  getTask,
  getTaskEvents,
  getTaskResult,
  listPendingSupervisorRequests,
  replyToSupervisorRequest,
  listConversations,
  sendConversationMessage,
} from './lib/api'
import { deriveAgentWorkspace, deriveConversationAgentWorkspace } from './lib/agentWorkspace'
import { compareChatMessages, conversationToMessage } from './lib/messages'
import type {
  ChatMessage,
  ConversationMessage,
  ConversationThread,
  Task,
  TaskEvent,
  TaskResult,
  TaskState,
  SupervisorRequest,
  WorkspaceAgentId,
  WorkspaceAgentStatus,
} from './types/api'

const terminal = new Set<TaskState>(['NEEDS_REVIEW', 'SUCCEEDED', 'FAILED', 'CANCELLED', 'REJECTED', 'BUDGET_EXCEEDED'])

function errorText(error: unknown) {
  return error instanceof ApiError ? error.message : '发生未知错误，请稍后重试。'
}

function Workbench() {
  const { show } = useToast()
  const [threads, setThreads] = useState<ConversationThread[]>([])
  const [selected, setSelected] = useState<ConversationThread | null>(null)
  const [activeTask, setActiveTask] = useState<Task | null>(null)
  const [events, setEvents] = useState<TaskEvent[]>([])
  const [conversation, setConversation] = useState<ConversationMessage[]>([])
  const [supervisorRequests, setSupervisorRequests] = useState<SupervisorRequest[]>([])
  const [result, setResult] = useState<TaskResult | null>(null)
  const [optimisticWorkingAgents, setOptimisticWorkingAgents] = useState<Array<{ id: WorkspaceAgentId; status: WorkspaceAgentStatus }>>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const loadGeneration = useRef(0)
  const loadController = useRef<AbortController | null>(null)

  const loadThreads = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const items = await listConversations()
      setThreads(items)
      setSelected((current) => current || items[0] || null)
    } catch (cause) {
      setError(errorText(cause))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void loadThreads() }, [loadThreads])

  useEffect(() => {
    if (!selected) {
      setSupervisorRequests([])
      return
    }
    let disposed = false
    const poll = async () => {
      try {
        const items = await listPendingSupervisorRequests(selected.id)
        if (!disposed) setSupervisorRequests(items)
      } catch {
        // The request inbox is best-effort; the conversation stream remains authoritative.
      }
    }
    void poll()
    const timer = window.setInterval(() => void poll(), 1000)
    return () => { disposed = true; window.clearInterval(timer) }
  }, [selected?.id])

  const loadSelected = useCallback(async (thread: ConversationThread) => {
    const generation = ++loadGeneration.current
    loadController.current?.abort()
    const controller = new AbortController()
    loadController.current = controller
    setSelected(thread)
    setEvents([])
    setConversation([])
    setResult(null)
    setOptimisticWorkingAgents([])
    setError(null)
    setLoading(true)
    setSidebarOpen(false)
    try {
      const [detail, messages] = await Promise.all([
        getConversation(thread.id, controller.signal),
        getConversationMessages(thread.id, controller.signal),
      ])
      if (generation !== loadGeneration.current) return
      setSelected(detail)
      setConversation(messages)
      if (detail.latest_task_id) {
        const [task, timeline, taskResult] = await Promise.all([
          getTask(detail.latest_task_id, controller.signal),
          getTaskEvents(detail.latest_task_id, controller.signal),
          getTaskResult(detail.latest_task_id, controller.signal),
        ])
        if (generation !== loadGeneration.current) return
        setActiveTask(task)
        setEvents(timeline)
        setResult(taskResult)
      } else {
        setActiveTask(null)
      }
    } catch (cause) {
      if (generation === loadGeneration.current && !(cause instanceof DOMException && cause.name === 'AbortError')) {
        setError(errorText(cause))
      }
    } finally {
      if (generation === loadGeneration.current) {
        loadController.current = null
        setLoading(false)
      }
    }
  }, [])

  useEffect(() => {
    if (!selected || loading || conversation.length > 0 || activeTask) return
    void loadSelected(selected)
    // Selection identity is the trigger; loaded state only prevents duplicate requests.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected?.id, loadSelected])

  const refreshSelected = useCallback(async () => {
    if (!selected) return
    try {
      const [thread, messages] = await Promise.all([
        getConversation(selected.id),
        getConversationMessages(selected.id),
      ])
      setSelected(thread)
      setConversation(messages)
      setThreads((items) => items.map((item) => item.id === thread.id ? thread : item))
      if (thread.latest_task_id) {
        const [task, timeline, taskResult] = await Promise.all([
          getTask(thread.latest_task_id),
          getTaskEvents(thread.latest_task_id),
          getTaskResult(thread.latest_task_id),
        ])
        setActiveTask(task)
        setEvents(timeline)
        setResult(taskResult)
      }
    } catch { /* SSE refresh is best-effort. */ }
  }, [selected])

  const updateEvent = useCallback((event: TaskEvent) => {
    setEvents((items) => items.some((item) => item.id === event.id) ? items : [...items, event])
    if (!event.to_state) return
    setActiveTask((task) => task ? { ...task, state: event.to_state as TaskState, updated_at: event.created_at } : task)
    setSelected((thread) => thread ? { ...thread, latest_task_state: event.to_state as TaskState, updated_at: event.created_at } : thread)
  }, [activeTask?.id])

  const updateMessage = useCallback((message: ConversationMessage) => {
    setConversation((items) => items.some((item) => item.id === message.id) ? items : [...items, message])
    if (message.phase === 'root' && ['agent_message', 'agent_error'].includes(message.message_type)) {
      setOptimisticWorkingAgents((items) => items.map((item) => ({ ...item, status: message.message_type === 'agent_error' ? 'failed' : 'completed' })))
      window.setTimeout(() => setOptimisticWorkingAgents([]), 3500)
    }
  }, [])

  // Message delivery can come from two SSE streams, so the React array is
  // not guaranteed to be append-ordered. Use the largest server cursor when
  // reconnecting instead of assuming the last array item is the newest one.
  const latestConversationMessageId = useMemo(
    () => conversation.reduce((latest, message) => Math.max(latest, message.id), 0),
    [conversation],
  )
  const latestTaskMessageId = useMemo(
    () => conversation.reduce(
      (latest, message) => message.task_id === activeTask?.id ? Math.max(latest, message.id) : latest,
      0,
    ),
    [activeTask?.id, conversation],
  )

  const conversationStreamStatus = useConversationStream({
    conversationId: selected?.id || null,
    after: latestConversationMessageId,
    active: Boolean(selected && !loading),
    onMessage: updateMessage,
    onWarning: () => show({
      tone: 'warning',
      title: '对话实时连接中断',
      description: '系统正在自动重连。',
      dedupeKey: 'conversation-sse-warning',
    }),
  })

  const taskStreamStatus = useTaskStream({
    taskId: activeTask?.id || null,
    after: events.reduce((latest, event) => Math.max(latest, event.id), 0),
    messageAfter: latestTaskMessageId,
    active: Boolean(activeTask && !terminal.has(activeTask.state) && !loading),
    onEvent: updateEvent,
    onMessage: updateMessage,
    onComplete: () => void refreshSelected(),
    onWarning: () => show({ tone: 'warning', title: '实时连接中断', description: '系统正在自动重连。', dedupeKey: 'sse-warning' }),
  })

  const messages = useMemo<ChatMessage[]>(
    () => {
      const inlineRequests = supervisorRequests.map((request) => ({
        id: `supervisor-${request.request_id}`,
        role: 'agent' as const,
        title: `${request.agent} 等待你的决定`,
        content: request.message,
        createdAt: request.created_at,
        tone: 'warning' as const,
        agentId: request.agent,
        phase: 'supervisor',
        supervisorRequest: request,
      }))
      return [...conversation.map(conversationToMessage), ...inlineRequests]
        .sort(compareChatMessages)
    },
    [conversation, supervisorRequests],
  )
  const agentWorkspace = useMemo(
    () => activeTask
      ? deriveAgentWorkspace(activeTask, events, conversation.filter((message) => message.task_id === activeTask.id))
      : deriveConversationAgentWorkspace(conversation),
    [activeTask, conversation, events],
  )

  const running = Boolean(activeTask && !terminal.has(activeTask.state))
  const progressAgents = useMemo<Array<{ id: WorkspaceAgentId; status: WorkspaceAgentStatus }>>(() => {
    if (activeTask && agentWorkspace && !terminal.has(activeTask.state)) return Object.values(agentWorkspace).filter((agent) => agent.status !== 'idle').map((agent) => ({ id: agent.id, status: agent.status }))
    if (activeTask || optimisticWorkingAgents.length === 0) return []
    const observed = new Map(Object.values(agentWorkspace).filter((agent) => agent.status !== 'idle').map((agent) => [agent.id, agent.status]))
    return optimisticWorkingAgents.map((agent) => ({
      ...agent,
      status: observed.get(agent.id) === 'completed' || observed.get(agent.id) === 'failed' ? observed.get(agent.id)! : agent.status,
    }))
  }, [activeTask, agentWorkspace, optimisticWorkingAgents])

  const submit = async (goal: string) => {
    if (!selected) return false
    setBusy(true)
    const mentioned = Array.from(goal.matchAll(/(?:^|\s)@(scout|researcher|planner|worker|reviewer|context-builder|oracle|delegate)(?=\s|$)/g), (match) => match[1] as WorkspaceAgentId)
    const selectedAgents: WorkspaceAgentId[] = mentioned.length > 0 ? mentioned : ['delegate']
    setOptimisticWorkingAgents(selectedAgents.map((id) => ({ id, status: 'running' })))
    try {
      const turn = await sendConversationMessage(selected.id, goal)
      const thread = await getConversation(selected.id)
      if (turn.task_id) {
        setActiveTask(await getTask(turn.task_id))
      } else {
        setActiveTask(null)
      }
      setSelected(thread)
      setThreads((items) => items.map((item) => item.id === thread.id ? thread : item))
      setEvents([])
      setResult(null)
      const messages = await getConversationMessages(selected.id)
      setConversation(messages)
      if (!turn.task_id && (turn.state === 'completed' || turn.state === 'failed' || messages.some((message) => message.turn_id === turn.turn_id && message.phase === 'root'))) {
        setOptimisticWorkingAgents([])
      }
      show({
        tone: turn.state === 'escalated' ? 'warning' : 'success',
        title: turn.state === 'escalated' ? '需要受控执行' : '消息已发送',
        description: turn.state === 'escalated'
          ? '该请求涉及副作用，已阻止聊天 Agent 直接执行。'
          : turn.collaboration_mode === 'parallel' && turn.selected_agents.length > 1
            ? `${turn.selected_agents.join('、')} 已开始并行独立分析。`
            : `${turn.selected_agents.join('、')} 已开始单 Agent 响应。`,
      })
      if (!turn.task_id) {
        for (const delay of [500, 1500, 4000, 8000]) {
          window.setTimeout(() => { void refreshSelected() }, delay)
        }
      }
      return true
    } catch (cause) {
      setOptimisticWorkingAgents([])
      show({ tone: 'error', title: '发送失败', description: errorText(cause) })
      return false
    } finally {
      setBusy(false)
    }
  }

  const newConversation = async () => {
    setBusy(true)
    try {
      const thread = await createConversation()
      setThreads((items) => [thread, ...items])
      setSelected(thread)
      setActiveTask(null)
      setEvents([])
      setConversation([])
      setResult(null)
      setOptimisticWorkingAgents([])
      setError(null)
      setSidebarOpen(false)
    } catch (cause) {
      show({ tone: 'error', title: '新建对话失败', description: errorText(cause) })
    } finally {
      setBusy(false)
    }
  }

  const cancel = async () => {
    if (!activeTask) return
    setBusy(true)
    try {
      setActiveTask(await cancelTask(activeTask.id))
      show({ tone: 'success', title: '取消请求已提交' })
    } catch (cause) {
      show({ tone: 'error', title: '取消任务失败', description: errorText(cause) })
    } finally { setBusy(false) }
  }

  const replySupervisor = async (requestId: string, reply: string) => {
    await replyToSupervisorRequest(requestId, reply)
    setSupervisorRequests((items) => items.filter((item) => item.request_id !== requestId))
  }

  const connected = conversationStreamStatus === 'connected'
    || taskStreamStatus === 'connected'
  return <div className="app-shell">
    <ConversationSidebar conversations={threads} selectedId={selected?.id || null} open={sidebarOpen} onClose={() => setSidebarOpen(false)} onSelect={(thread) => void loadSelected(thread)} onNew={() => void newConversation()}/>
    {sidebarOpen && <button className="sidebar-overlay" onClick={() => setSidebarOpen(false)} aria-label="关闭对话列表"/>}
    <main className="main-panel">
      <header className="topbar">
        <div className="flex items-center gap-3"><button className="icon-button lg:hidden" onClick={() => setSidebarOpen(true)} aria-label="打开对话列表"><Menu size={19}/></button><div className="brand-mark"><Bot size={19}/></div><div><h1>Agent Console</h1><p>多 Agent 持续对话工作台</p></div></div>
        <div className="flex items-center gap-2"><button className="secondary-button hidden sm:flex" disabled={busy} onClick={() => void newConversation()}><Plus size={15}/>新建对话</button><div className={`connection ${connected ? 'connection-online' : ''}`}>{connected ? <Wifi size={14}/> : <WifiOff size={14}/>}<span>{connected ? '实时连接' : conversationStreamStatus === 'reconnecting' || taskStreamStatus === 'reconnecting' ? '正在重连' : 'API 已连接'}</span></div></div>
      </header>
      {selected && <div className="task-heading"><div className="min-w-0"><span className="eyebrow">当前对话</span><h2 className="truncate">{selected.title}</h2></div><div className="flex items-center gap-2"><AgentWorkingIndicator agents={agentWorkspace}/>{activeTask && <span className={`state-pill state-${activeTask.state.toLowerCase()}`}>{activeTask.state.replaceAll('_', ' ')}</span>}</div></div>}
      <section className="message-panel"><Conversation messages={messages} loading={loading} error={error} progressAgents={progressAgents} onSupervisorReply={replySupervisor} onRetry={() => selected ? void loadSelected(selected) : void loadThreads()}/>{activeTask && agentWorkspace && <CollaborationDetails task={activeTask} agents={agentWorkspace} events={events} result={result}/>}</section>
      {selected ? <TaskComposer busy={busy} running={running} onSubmit={submit} onCancel={cancel}/> : <div className="p-6 text-center text-sm text-zinc-500">请先新建一个对话。</div>}
    </main>
  </div>
}

export default function App() { return <ToastProvider><Workbench/></ToastProvider> }
