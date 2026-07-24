import { Bot, Menu, Plus, Wifi, WifiOff } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AgentWorkspace } from './components/AgentWorkspace'
import { Conversation } from './components/Conversation'
import { ConversationSidebar } from './components/ConversationSidebar'
import { TaskArtifactsPanel } from './components/TaskArtifactsPanel'
import { TaskComposer } from './components/TaskComposer'
import { TaskResultPanel } from './components/TaskResultPanel'
import { ToastProvider, useToast } from './components/ToastProvider'
import { useTaskStream } from './hooks/useTaskStream'
import {
  ApiError,
  cancelTask,
  createConversation,
  decideConfirmation,
  getConversation,
  getConversationMessages,
  getPendingConfirmations,
  getTask,
  getTaskEvents,
  getTaskResult,
  listConversations,
  sendConversationMessage,
} from './lib/api'
import { deriveAgentWorkspace } from './lib/agentWorkspace'
import { apiDateTimestamp } from './lib/dateTime'
import { conversationToMessage, eventToMessage } from './lib/messages'
import type {
  ChatMessage,
  ConversationMessage,
  ConversationThread,
  PendingConfirmation,
  Task,
  TaskEvent,
  TaskResult,
  TaskState,
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
  const [confirmations, setConfirmations] = useState<PendingConfirmation[]>([])
  const [result, setResult] = useState<TaskResult | null>(null)
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

  const loadSelected = useCallback(async (thread: ConversationThread) => {
    const generation = ++loadGeneration.current
    loadController.current?.abort()
    const controller = new AbortController()
    loadController.current = controller
    setSelected(thread)
    setEvents([])
    setConversation([])
    setConfirmations([])
    setResult(null)
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
        const [task, timeline, pending, taskResult] = await Promise.all([
          getTask(detail.latest_task_id, controller.signal),
          getTaskEvents(detail.latest_task_id, controller.signal),
          getPendingConfirmations(detail.latest_task_id, controller.signal),
          getTaskResult(detail.latest_task_id, controller.signal),
        ])
        if (generation !== loadGeneration.current) return
        setActiveTask(task)
        setEvents(timeline)
        setConfirmations(pending)
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
        const [task, timeline, pending, taskResult] = await Promise.all([
          getTask(thread.latest_task_id),
          getTaskEvents(thread.latest_task_id),
          getPendingConfirmations(thread.latest_task_id),
          getTaskResult(thread.latest_task_id),
        ])
        setActiveTask(task)
        setEvents(timeline)
        setConfirmations(pending)
        setResult(taskResult)
      }
    } catch { /* SSE refresh is best-effort. */ }
  }, [selected])

  const updateEvent = useCallback((event: TaskEvent) => {
    setEvents((items) => items.some((item) => item.id === event.id) ? items : [...items, event])
    if (!event.to_state) return
    setActiveTask((task) => task ? { ...task, state: event.to_state as TaskState, updated_at: event.created_at } : task)
    setSelected((thread) => thread ? { ...thread, latest_task_state: event.to_state as TaskState, updated_at: event.created_at } : thread)
    if (event.to_state === 'WAITING_CONFIRMATION' && activeTask?.id) {
      void Promise.all([getPendingConfirmations(activeTask.id), getTaskResult(activeTask.id)])
        .then(([pending, taskResult]) => { setConfirmations(pending); setResult(taskResult) })
        .catch(() => undefined)
    }
  }, [activeTask?.id])

  const updateMessage = useCallback((message: ConversationMessage) => {
    setConversation((items) => items.some((item) => item.id === message.id) ? items : [...items, message])
  }, [])

  const streamStatus = useTaskStream({
    taskId: activeTask?.id || null,
    after: events.at(-1)?.id || 0,
    messageAfter: conversation.filter((message) => message.task_id === activeTask?.id).at(-1)?.id || 0,
    active: Boolean(activeTask && !terminal.has(activeTask.state) && !loading),
    onEvent: updateEvent,
    onMessage: updateMessage,
    onComplete: () => void refreshSelected(),
    onWarning: () => show({ tone: 'warning', title: '实时连接中断', description: '系统正在自动重连。', dedupeKey: 'sse-warning' }),
  })

  const messages = useMemo<ChatMessage[]>(() => [
    ...events.map(eventToMessage),
    ...conversation.map(conversationToMessage),
  ].sort((left, right) => apiDateTimestamp(left.createdAt) - apiDateTimestamp(right.createdAt)), [conversation, events])
  const agentWorkspace = useMemo(
    () => activeTask
      ? deriveAgentWorkspace(
          activeTask,
          events,
          conversation.filter((message) => message.task_id === activeTask.id),
        )
      : null,
    [activeTask, conversation, events],
  )

  const running = Boolean(activeTask && !terminal.has(activeTask.state))

  const submit = async (goal: string) => {
    if (!selected) return false
    setBusy(true)
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
      setConfirmations([])
      setResult(null)
      const messages = await getConversationMessages(selected.id)
      setConversation(messages)
      show({
        tone: turn.state === 'escalated' ? 'warning' : 'success',
        title: turn.state === 'escalated' ? '需要受控执行' : '消息已发送',
        description: turn.state === 'escalated'
          ? '该请求涉及副作用，已阻止聊天 Agent 直接执行。'
          : `${turn.selected_agents.join('、')} 已开始独立响应。`,
      })
      if (!turn.task_id) {
        window.setTimeout(() => { void refreshSelected() }, 1500)
      }
      return true
    } catch (cause) {
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
      setConfirmations([])
      setResult(null)
      setError(null)
      setSidebarOpen(false)
    } catch (cause) {
      show({ tone: 'error', title: '新建对话失败', description: errorText(cause) })
    } finally {
      setBusy(false)
    }
  }

  const decide = async (confirmation: PendingConfirmation, approved: boolean) => {
    if (!activeTask) return
    setBusy(true)
    try {
      await decideConfirmation(activeTask.id, confirmation, approved)
      setConfirmations(await getPendingConfirmations(activeTask.id))
      show({ tone: approved ? 'success' : 'warning', title: approved ? '已批准执行步骤' : '已拒绝执行步骤' })
      await refreshSelected()
    } catch (cause) {
      show({ tone: 'error', title: '提交确认失败', description: errorText(cause) })
    } finally { setBusy(false) }
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

  const connected = streamStatus === 'connected'
  return <div className="app-shell">
    <ConversationSidebar conversations={threads} selectedId={selected?.id || null} open={sidebarOpen} onClose={() => setSidebarOpen(false)} onSelect={(thread) => void loadSelected(thread)} onNew={() => void newConversation()}/>
    {sidebarOpen && <button className="sidebar-overlay" onClick={() => setSidebarOpen(false)} aria-label="关闭对话列表"/>}
    <main className="main-panel">
      <header className="topbar">
        <div className="flex items-center gap-3"><button className="icon-button lg:hidden" onClick={() => setSidebarOpen(true)} aria-label="打开对话列表"><Menu size={19}/></button><div className="brand-mark"><Bot size={19}/></div><div><h1>Agent Console</h1><p>多 Agent 持续对话工作台</p></div></div>
        <div className="flex items-center gap-2"><button className="secondary-button hidden sm:flex" disabled={busy} onClick={() => void newConversation()}><Plus size={15}/>新建对话</button><div className={`connection ${connected ? 'connection-online' : ''}`}>{connected ? <Wifi size={14}/> : <WifiOff size={14}/>}<span>{connected ? '实时连接' : streamStatus === 'reconnecting' ? '正在重连' : 'API 已连接'}</span></div></div>
      </header>
      {selected && <div className="task-heading"><div className="min-w-0"><span className="eyebrow">当前对话</span><h2 className="truncate">{selected.title}</h2></div>{activeTask && <span className={`state-pill state-${activeTask.state.toLowerCase()}`}>{activeTask.state.replaceAll('_', ' ')}</span>}</div>}
      <section className="message-panel">{agentWorkspace && <AgentWorkspace agents={agentWorkspace}/>} {activeTask && <TaskArtifactsPanel taskId={activeTask.id} refreshKey={activeTask.updated_at}/>}<Conversation messages={messages} loading={loading} error={error} onRetry={() => selected ? void loadSelected(selected) : void loadThreads()}/>{result && <details className="mx-4 mb-4"><summary className="cursor-pointer text-sm text-violet-300">查看当前轮运行详情</summary><TaskResultPanel result={result}/></details>}</section>
      {confirmations.length > 0 && <section className="confirmation-panel">{confirmations.map((confirmation) => <article className="confirmation-card" key={confirmation.call_hash}><div><strong>Executor 请求人工确认</strong><p>{confirmation.tool_name} · {confirmation.risk}</p><p>{confirmation.impact}</p><details><summary>查看工具参数</summary><pre>{JSON.stringify(confirmation.arguments, null, 2)}</pre></details></div><div className="confirmation-actions"><button className="secondary-button" disabled={busy} onClick={() => void decide(confirmation, false)}>拒绝</button><button className="primary-button" disabled={busy} onClick={() => void decide(confirmation, true)}>批准</button></div></article>)}</section>}
      {selected ? <TaskComposer busy={busy} running={running} onSubmit={submit} onCancel={cancel}/> : <div className="p-6 text-center text-sm text-zinc-500">请先新建一个对话。</div>}
    </main>
  </div>
}

export default function App() { return <ToastProvider><Workbench/></ToastProvider> }
