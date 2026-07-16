import { Bot, Menu, Plus, Wifi, WifiOff } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Conversation } from './components/Conversation'
import { TaskComposer } from './components/TaskComposer'
import { TaskSidebar } from './components/TaskSidebar'
import { ToastProvider, useToast } from './components/ToastProvider'
import { useTaskStream } from './hooks/useTaskStream'
import { ApiError, cancelTask, createTask, getTask, getTaskEvents, listTasks } from './lib/api'
import { eventToMessage } from './lib/messages'
import type { ChatMessage, Task, TaskEvent, TaskState } from './types/api'

const terminal = new Set<TaskState>(['SUCCEEDED', 'FAILED', 'CANCELLED', 'REJECTED', 'BUDGET_EXCEEDED'])

function errorText(error: unknown) {
  return error instanceof ApiError ? error.message : '发生未知错误，请稍后重试。'
}

function Workbench() {
  const { show } = useToast()
  const [tasks, setTasks] = useState<Task[]>([])
  const [selected, setSelected] = useState<Task | null>(null)
  const [events, setEvents] = useState<TaskEvent[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [sidebarOpen, setSidebarOpen] = useState(false)

  const loadTasks = useCallback(async () => {
    setLoading(true); setError(null)
    try {
      const result = await listTasks()
      setTasks(result)
      setSelected((current) => current || result[0] || null)
    } catch (cause) { setError(errorText(cause)) } finally { setLoading(false) }
  }, [])

  useEffect(() => { void loadTasks() }, [loadTasks])

  const loadSelected = useCallback(async (task: Task) => {
    setSelected(task); setEvents([]); setError(null); setLoading(true); setSidebarOpen(false)
    try {
      const [detail, timeline] = await Promise.all([getTask(task.id), getTaskEvents(task.id)])
      setSelected(detail); setEvents(timeline)
    } catch (cause) { setError(errorText(cause)) } finally { setLoading(false) }
  }, [])

  useEffect(() => {
    if (!selected || loading || events.length > 0) return
    void loadSelected(selected)
    // Selection identity is the trigger; loading/events are guarded state, not triggers.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected?.id, loadSelected])

  const updateEvent = useCallback((event: TaskEvent) => {
    setEvents((items) => items.some((item) => item.id === event.id) ? items : [...items, event])
    if (event.to_state) {
      setSelected((task) => task ? { ...task, state: event.to_state as TaskState, updated_at: event.created_at } : task)
      setTasks((items) => items.map((task) => task.id === selected?.id ? { ...task, state: event.to_state as TaskState, updated_at: event.created_at } : task))
    }
  }, [selected?.id])

  const refreshSelected = useCallback(async () => {
    if (!selected) return
    try {
      const task = await getTask(selected.id)
      setSelected(task); setTasks((items) => items.map((item) => item.id === task.id ? task : item))
    } catch { /* SSE completion refresh is best-effort. */ }
  }, [selected])

  const streamStatus = useTaskStream({
    taskId: selected?.id || null,
    after: events.at(-1)?.id || 0,
    active: Boolean(selected && !terminal.has(selected.state) && !loading),
    onEvent: updateEvent,
    onComplete: () => void refreshSelected(),
    onWarning: () => show({ tone: 'warning', title: '实时连接中断', description: '系统正在自动重连。', dedupeKey: 'sse-warning' }),
  })

  const messages = useMemo<ChatMessage[]>(() => selected ? [{ id: `goal-${selected.id}`, role: 'user', content: selected.goal, createdAt: selected.created_at }, ...events.map(eventToMessage)] : [], [events, selected])
  const running = Boolean(selected && !terminal.has(selected.state))

  const submit = async (goal: string) => {
    setBusy(true)
    try {
      const task = await createTask(goal)
      setTasks((items) => [task, ...items]); setSelected(task); setEvents([]); setError(null)
      show({ tone: 'success', title: '任务已创建', description: '多 Agent 协作流程已启动。' })
    } catch (cause) { show({ tone: 'error', title: '创建任务失败', description: errorText(cause) }) } finally { setBusy(false) }
  }

  const cancel = async () => {
    if (!selected) return
    setBusy(true)
    try {
      const task = await cancelTask(selected.id)
      setSelected(task); setTasks((items) => items.map((item) => item.id === task.id ? task : item))
      show({ tone: 'success', title: '取消请求已提交' })
    } catch (cause) { show({ tone: 'error', title: '取消任务失败', description: errorText(cause) }) } finally { setBusy(false) }
  }

  const newTask = () => { setSelected(null); setEvents([]); setError(null); setSidebarOpen(false) }
  const connected = streamStatus === 'connected'

  return <div className="app-shell">
    <TaskSidebar tasks={tasks} selectedId={selected?.id || null} open={sidebarOpen} onClose={() => setSidebarOpen(false)} onSelect={(task) => void loadSelected(task)} onNew={newTask}/>
    {sidebarOpen && <button className="sidebar-overlay" onClick={() => setSidebarOpen(false)} aria-label="关闭任务列表"/>}
    <main className="main-panel">
      <header className="topbar"><div className="flex items-center gap-3"><button className="icon-button lg:hidden" onClick={() => setSidebarOpen(true)} aria-label="打开任务列表"><Menu size={19}/></button><div className="brand-mark"><Bot size={19}/></div><div><h1>Agent Console</h1><p>多 Agent 协作工作台</p></div></div><div className="flex items-center gap-2"><button className="secondary-button hidden sm:flex" onClick={newTask}><Plus size={15}/>新建任务</button><div className={`connection ${connected ? 'connection-online' : ''}`}>{connected ? <Wifi size={14}/> : <WifiOff size={14}/>}<span>{connected ? '实时连接' : streamStatus === 'reconnecting' ? '正在重连' : 'API 已连接'}</span></div></div></header>
      {selected && <div className="task-heading"><div className="min-w-0"><span className="eyebrow">当前任务</span><h2 className="truncate">{selected.goal}</h2></div><span className={`state-pill state-${selected.state.toLowerCase()}`}>{selected.state.replaceAll('_', ' ')}</span></div>}
      <section className="message-panel"><Conversation messages={messages} loading={loading} error={error} onRetry={() => selected ? void loadSelected(selected) : void loadTasks()}/></section>
      <TaskComposer busy={busy} running={running} onSubmit={submit} onCancel={cancel}/>
    </main>
  </div>
}

export default function App() { return <ToastProvider><Workbench/></ToastProvider> }
