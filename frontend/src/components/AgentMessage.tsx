import { Bot, Check, Copy, User } from 'lucide-react'
import { useEffect, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { parseApiDate } from '../lib/dateTime'
import type { ChatMessage } from '../types/api'

export function AgentMessage({ message }: { message: ChatMessage }) {
  const [copied, setCopied] = useState(false)
  const isUser = message.role === 'user'
  const agentClass = message.agentId ? ` agent-${message.agentId.replaceAll('_', '-')}` : ''

  useEffect(() => {
    if (!copied) return
    const timer = window.setTimeout(() => setCopied(false), 1800)
    return () => window.clearTimeout(timer)
  }, [copied])

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(message.content)
      setCopied(true)
    } catch { /* Clipboard access may be unavailable outside a secure context. */ }
  }

  return <article className={`message-row ${isUser ? 'message-row-user' : ''}${message.isFinal ? ' message-row-final' : ''}${agentClass}`}>
    <div className={`avatar ${isUser ? 'avatar-user' : ''}`}>{isUser ? <User size={17}/> : <Bot size={17}/>}</div>
    <div className={`message ${isUser ? 'message-user' : `message-${message.tone || 'default'}`}${message.isFinal ? ' message-final' : ''}`}>
      {!isUser && <div className="message-title"><span>{message.title}</span><button className="message-copy" type="button" onClick={() => void copy()}>{copied ? <Check size={13}/> : <Copy size={13}/>} {copied ? '已复制' : '复制'}</button></div>}
      {isUser && message.title && <div className="message-title"><span>{message.title}</span></div>}
      {message.isFinal
        ? <div className="message-markdown"><ReactMarkdown remarkPlugins={[remarkGfm]} components={{ a: ({ children, ...props }) => <a {...props} target="_blank" rel="noreferrer noopener">{children}</a> }}>{message.content}</ReactMarkdown></div>
        : <p className="whitespace-pre-wrap leading-7">{message.content}</p>}
      <time className="mt-2 block text-[11px] opacity-45">{parseApiDate(message.createdAt).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}</time>
    </div>
  </article>
}
