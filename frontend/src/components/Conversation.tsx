import { ArrowDown, Bot, Check, LoaderCircle, RefreshCw, TriangleAlert } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import type { ChatMessage, WorkspaceAgentId, WorkspaceAgentStatus } from '../types/api'
import { AgentMessage } from './AgentMessage'

const bottomThreshold = 96
const agentNames: Record<WorkspaceAgentId, string> = {
  scout: 'Scout',
  researcher: 'Researcher',
  worker: 'Worker',
  reviewer: 'Reviewer',
  oracle: 'Oracle',
  delegate: 'Delegate',
}

type AgentProgressItem = { id: WorkspaceAgentId; status: WorkspaceAgentStatus }

function AgentProgress({ agents }: { agents: AgentProgressItem[] }) {
  const running = agents.filter((agent) => agent.status === 'running' || agent.status === 'waiting')
  const completed = agents.filter((agent) => agent.status === 'completed')
  const failed = agents.filter((agent) => agent.status === 'failed')
  const names = (items: AgentProgressItem[]) => items.map((agent) => agentNames[agent.id] || agent.id).join(' · ')
  const current = running.length > 0 ? running : completed.length > 0 ? completed : failed
  const currentNames = names(current)
  const currentStatus = running.length > 0 ? 'running' : failed.length > 0 ? 'failed' : 'completed'

  return <div className="message-row agent-progress-row" role="status" aria-live="polite">
    <div className="avatar"><Bot size={17}/></div>
    <div className="agent-progress-message">
      <div className={`agent-progress-line agent-progress-${currentStatus}`}>
        {currentStatus === 'running'
          ? <LoaderCircle size={14} className="agent-status-spinner"/>
          : currentStatus === 'failed' ? <TriangleAlert size={14}/> : <Check size={14}/>}
        <strong>
          {currentStatus === 'running'
            ? 'Supervisor 正在协作'
            : currentStatus === 'failed' ? '协作需要重试' : 'Supervisor 已完成协作'}
        </strong>
        <span className="agent-progress-current">{currentNames}</span>
        {currentStatus === 'running' && <LoaderCircle size={13} className="agent-progress-trailing-spinner agent-status-spinner"/>}
      </div>
      {completed.length > 0 && currentStatus === 'running' && <small className="agent-progress-meta">已完成：{names(completed)}</small>}
      {failed.length > 0 && currentStatus === 'running' && <small className="agent-progress-meta agent-progress-meta-failed">失败：{names(failed)}</small>}
    </div>
  </div>
}

export function Conversation({ messages, loading, error, onRetry, progressAgents = [], onSupervisorReply }: { messages: ChatMessage[]; loading: boolean; error: string | null; onRetry: () => void; progressAgents?: AgentProgressItem[]; onSupervisorReply?: (requestId: string, reply: string) => Promise<void> }) {
  const rootRef = useRef<HTMLDivElement>(null)
  const initialized = useRef(false)
  const following = useRef(true)
  const [showJump, setShowJump] = useState(false)

  useEffect(() => {
    const scroller = rootRef.current?.closest('.message-panel')
    if (!(scroller instanceof HTMLElement)) return
    const onScroll = () => {
      const nearBottom = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < bottomThreshold
      following.current = nearBottom
      setShowJump(!nearBottom)
    }
    onScroll()
    scroller.addEventListener('scroll', onScroll, { passive: true })
    return () => scroller.removeEventListener('scroll', onScroll)
  }, [])

  useEffect(() => {
    const scroller = rootRef.current?.closest('.message-panel')
    if (!(scroller instanceof HTMLElement) || (messages.length === 0 && progressAgents.length === 0)) return
    if (!initialized.current) {
      initialized.current = true
      scroller.scrollTop = scroller.scrollHeight
      return
    }
    if (following.current) scroller.scrollTo({ top: scroller.scrollHeight, behavior: 'smooth' })
    else setShowJump(true)
  }, [messages, progressAgents.length])

  const jumpToBottom = () => {
    const scroller = rootRef.current?.closest('.message-panel')
    if (!(scroller instanceof HTMLElement)) return
    following.current = true
    setShowJump(false)
    scroller.scrollTo({ top: scroller.scrollHeight, behavior: 'smooth' })
  }

  if (loading) return <div ref={rootRef} className="empty-state"><RefreshCw className="animate-spin text-violet-400"/><p>正在加载任务记录…</p></div>
  if (error) return <div ref={rootRef} className="empty-state"><p className="text-red-300">{error}</p><button className="secondary-button" onClick={onRetry}><RefreshCw size={15}/>重试</button></div>
  if (messages.length === 0 && progressAgents.length === 0) return <div ref={rootRef} className="empty-state"><div className="hero-icon"><Bot size={32}/></div><h2>让多个 Agent 为你协作</h2><p>描述一个清晰的任务目标，系统将自动分析、规划、执行并验证结果。</p></div>
  return <div ref={rootRef} className="conversation">{messages.map((message) => <AgentMessage key={message.id} message={message} onSupervisorReply={onSupervisorReply}/>)}{progressAgents.length > 0 && <AgentProgress agents={progressAgents}/>} {showJump && <button className="jump-to-bottom" type="button" onClick={jumpToBottom}><ArrowDown size={14}/>回到底部</button>}</div>
}
