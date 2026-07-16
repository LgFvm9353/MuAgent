import { Bot, RefreshCw } from 'lucide-react'
import { useEffect, useRef } from 'react'
import type { ChatMessage } from '../types/api'
import { AgentMessage } from './AgentMessage'

export function Conversation({ messages, loading, error, onRetry }: { messages: ChatMessage[]; loading: boolean; error: string | null; onRetry: () => void }) {
  const endRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])
  if (loading) return <div className="empty-state"><RefreshCw className="animate-spin text-violet-400"/><p>正在加载任务记录…</p></div>
  if (error) return <div className="empty-state"><p className="text-red-300">{error}</p><button className="secondary-button" onClick={onRetry}><RefreshCw size={15}/>重试</button></div>
  if (messages.length === 0) return <div className="empty-state"><div className="hero-icon"><Bot size={32}/></div><h2>让多个 Agent 为你协作</h2><p>描述一个清晰的任务目标，系统将自动分析、规划、执行并验证结果。</p></div>
  return <div className="conversation">{messages.map((message) => <AgentMessage key={message.id} message={message}/>)}<div ref={endRef}/></div>
}
