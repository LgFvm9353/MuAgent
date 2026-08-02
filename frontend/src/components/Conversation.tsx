import { ArrowDown, Bot, RefreshCw } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import type { ChatMessage } from '../types/api'
import { AgentMessage } from './AgentMessage'

const bottomThreshold = 96

export function Conversation({ messages, loading, error, onRetry }: { messages: ChatMessage[]; loading: boolean; error: string | null; onRetry: () => void }) {
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
    if (!(scroller instanceof HTMLElement) || messages.length === 0) return
    if (!initialized.current) {
      initialized.current = true
      scroller.scrollTop = scroller.scrollHeight
      return
    }
    if (following.current) scroller.scrollTo({ top: scroller.scrollHeight, behavior: 'smooth' })
    else setShowJump(true)
  }, [messages])

  const jumpToBottom = () => {
    const scroller = rootRef.current?.closest('.message-panel')
    if (!(scroller instanceof HTMLElement)) return
    following.current = true
    setShowJump(false)
    scroller.scrollTo({ top: scroller.scrollHeight, behavior: 'smooth' })
  }

  if (loading) return <div ref={rootRef} className="empty-state"><RefreshCw className="animate-spin text-violet-400"/><p>正在加载任务记录…</p></div>
  if (error) return <div ref={rootRef} className="empty-state"><p className="text-red-300">{error}</p><button className="secondary-button" onClick={onRetry}><RefreshCw size={15}/>重试</button></div>
  if (messages.length === 0) return <div ref={rootRef} className="empty-state"><div className="hero-icon"><Bot size={32}/></div><h2>让多个 Agent 为你协作</h2><p>描述一个清晰的任务目标，系统将自动分析、规划、执行并验证结果。</p></div>
  return <div ref={rootRef} className="conversation">{messages.map((message) => <AgentMessage key={message.id} message={message}/>)}{showJump && <button className="jump-to-bottom" type="button" onClick={jumpToBottom}><ArrowDown size={14}/>回到底部</button>}</div>
}
