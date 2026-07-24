import { Bot, ChevronDown, User } from 'lucide-react'
import { parseApiDate } from '../lib/dateTime'
import type { ChatMessage } from '../types/api'

export function AgentMessage({ message }: { message: ChatMessage }) {
  const isUser = message.role === 'user'
  const agentClass = message.agentId ? ` agent-${message.agentId.replaceAll('_', '-')}` : ''
  return <article className={`message-row ${isUser ? 'message-row-user' : ''}${agentClass}`}><div className={`avatar ${isUser ? 'avatar-user' : ''}`}>{isUser ? <User size={17}/> : <Bot size={17}/>}</div><div className={`message ${isUser ? 'message-user' : `message-${message.tone || 'default'}`}`}>{message.title && <div className="mb-1 text-xs font-semibold uppercase tracking-wider opacity-60">{message.title}</div>}<p className="whitespace-pre-wrap leading-7">{message.content}</p><time className="mt-2 block text-[11px] opacity-45">{parseApiDate(message.createdAt).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}</time>{message.details && Object.keys(message.details).length > 0 && <details className="mt-3 border-t border-current/10 pt-2 text-xs opacity-70"><summary className="flex cursor-pointer list-none items-center gap-1"><ChevronDown size={13}/>展开完整发言</summary><pre className="mt-2 overflow-x-auto whitespace-pre-wrap rounded-lg bg-black/20 p-3">{JSON.stringify(message.details, null, 2)}</pre></details>}</div></article>
}
