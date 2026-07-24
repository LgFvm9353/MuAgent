import { Check, Circle, DraftingCompass, LoaderCircle, SearchCheck, TriangleAlert } from 'lucide-react'
import { useEffect, useState, type ComponentType } from 'react'
import { apiDateTimestamp, parseApiDate } from '../lib/dateTime'
import type { AgentWorkspaceState, WorkspaceAgentId, WorkspaceAgentState } from '../types/api'

const metadata: Record<WorkspaceAgentId, { name: string; role: string; icon: ComponentType<{ size?: number }> }> = {
  architect: { name: 'Architect', role: '分析、委派与汇总规划', icon: DraftingCompass },
  reviewer: { name: 'Reviewer', role: '技术审查、测试与验证', icon: SearchCheck },
  designer: { name: 'Designer', role: '产品方案与交互体验', icon: Circle },
}

const statusLabel = {
  idle: '等待',
  waiting: '已委派',
  running: '运行中',
  completed: '已完成',
  failed: '失败',
}

function formatDuration(start: string | null, end: string | null, now: number): string | null {
  if (!start) return null
  const elapsed = Math.max(0, (end ? apiDateTimestamp(end) : now) - apiDateTimestamp(start))
  if (!Number.isFinite(elapsed)) return null
  if (elapsed < 1000) return '<1 秒'
  const seconds = Math.floor(elapsed / 1000)
  if (seconds < 60) return `${seconds} 秒`
  return `${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒`
}

function StatusIcon({ agent }: { agent: WorkspaceAgentState }) {
  if (agent.status === 'running') return <LoaderCircle size={14} className="agent-status-spinner" />
  if (agent.status === 'completed') return <Check size={14} />
  if (agent.status === 'failed') return <TriangleAlert size={14} />
  return <Circle size={10} />
}

function AgentCard({ agent, now }: { agent: WorkspaceAgentState; now: number }) {
  const item = metadata[agent.id]
  const Icon = item.icon
  const duration = formatDuration(agent.startedAt, agent.completedAt, now)
  return <article className={`agent-workspace-card agent-workspace-${agent.id} agent-workspace-status-${agent.status}`}>
    <div className="agent-workspace-card-header">
      <div className="agent-workspace-icon"><Icon size={17}/></div>
      <div className="min-w-0"><h4>{item.name}</h4><p>{item.role}</p></div>
      <span className="agent-workspace-status"><StatusIcon agent={agent}/>{statusLabel[agent.status]}</span>
    </div>
    <div className="agent-workspace-card-body">
      <strong>{agent.phase}</strong>
      <p>{agent.summary}</p>
    </div>
    <div className="agent-workspace-card-footer">
      <span>{duration ? `耗时 ${duration}` : '尚未开始'}</span>
      {agent.updatedAt && <time dateTime={agent.updatedAt}>{parseApiDate(agent.updatedAt).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}</time>}
    </div>
  </article>
}

export function AgentWorkspace({ agents }: { agents: AgentWorkspaceState }) {
  const hasRunningAgent = Object.values(agents).some((agent) => agent.status === 'running')
  const [now, setNow] = useState(Date.now())

  useEffect(() => {
    if (!hasRunningAgent) return
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [hasRunningAgent])

  return <section className="agent-workspace" aria-label="三 Agent 实时工作区" aria-live="polite">
    <div className="agent-workspace-heading">
      <div><span className="eyebrow">实时协作</span><h3>三 Agent 工作区</h3></div>
      <p>Reviewer 与 Designer 接受委派后并行执行，Architect 最后汇总。</p>
    </div>
    <div className="agent-workspace-flow">
      <AgentCard agent={agents.architect} now={now}/>
      <div className="agent-workspace-specialists">
        <AgentCard agent={agents.reviewer} now={now}/>
        <AgentCard agent={agents.designer} now={now}/>
      </div>
    </div>
  </section>
}
