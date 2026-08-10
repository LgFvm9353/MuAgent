import { Check, Circle, Compass, FileSearch, Lightbulb, LoaderCircle, SearchCheck, ShieldCheck, TriangleAlert } from 'lucide-react'
import { useEffect, useState, type ComponentType } from 'react'
import { apiDateTimestamp, parseApiDate } from '../lib/dateTime'
import type { AgentWorkspaceState, WorkspaceAgentState } from '../types/api'

const metadata: Record<string, { name: string; role: string; icon: ComponentType<{ size?: number }> }> = {
  scout: { name: 'Scout', role: 'Local codebase reconnaissance', icon: Compass },
  researcher: { name: 'Researcher', role: 'External documentation and evidence', icon: FileSearch },
  worker: { name: 'Worker', role: 'Implementation and validation', icon: Lightbulb },
  reviewer: { name: 'Reviewer', role: 'Review, testing and verification', icon: SearchCheck },
  oracle: { name: 'Oracle', role: 'Adversarial second opinion', icon: ShieldCheck },
  delegate: { name: 'Delegate', role: 'General-purpose delegation', icon: Circle },
}

const statusLabel = { idle: 'Idle', waiting: 'Waiting', running: 'Running', completed: 'Completed', failed: 'Failed' }

function formatDuration(start: string | null, end: string | null, now: number): string | null {
  if (!start) return null
  const elapsed = Math.max(0, (end ? apiDateTimestamp(end) : now) - apiDateTimestamp(start))
  if (!Number.isFinite(elapsed)) return null
  if (elapsed < 1000) return '<1s'
  const seconds = Math.floor(elapsed / 1000)
  return seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}m ${seconds % 60}s`
}

function StatusIcon({ agent }: { agent: WorkspaceAgentState }) {
  if (agent.status === 'running') return <LoaderCircle size={14} className="agent-status-spinner" />
  if (agent.status === 'completed') return <Check size={14} />
  if (agent.status === 'failed') return <TriangleAlert size={14} />
  return <Circle size={10} />
}

function AgentCard({ agent, now }: { agent: WorkspaceAgentState; now: number }) {
  const item = metadata[agent.id] ?? { name: agent.id, role: 'Capability agent', icon: Circle }
  const Icon = item.icon
  const duration = formatDuration(agent.startedAt, agent.completedAt, now)
  return <article className={`agent-workspace-card agent-workspace-${agent.id} agent-workspace-status-${agent.status}`}>
    <div className="agent-workspace-card-header">
      <div className="agent-workspace-icon"><Icon size={17}/></div>
      <div className="min-w-0"><h4>{item.name}</h4><p>{item.role}</p></div>
      <span className="agent-workspace-status"><StatusIcon agent={agent}/>{statusLabel[agent.status]}</span>
    </div>
    <div className="agent-workspace-card-body"><strong>{agent.phase}</strong><p>{agent.summary}</p></div>
    <div className="agent-workspace-card-footer">
      <span>{duration ? `Elapsed ${duration}` : 'Not started'}</span>
      {agent.updatedAt && <time dateTime={agent.updatedAt}>{parseApiDate(agent.updatedAt).toLocaleTimeString()}</time>}
    </div>
  </article>
}

export function AgentWorkspace({ agents, compact = false }: { agents: AgentWorkspaceState; compact?: boolean }) {
  const values = Object.values(agents)
  const hasRunningAgent = values.some((agent) => agent.status === 'running')
  const [now, setNow] = useState(Date.now())
  useEffect(() => {
    if (!hasRunningAgent) return
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [hasRunningAgent])

  return <section className={`agent-workspace${compact ? ' agent-workspace-compact' : ''}`} aria-label="Capability agent workspace" aria-live="polite">
    {!compact && <div className="agent-workspace-heading"><div><span className="eyebrow">Live collaboration</span><h3>Capability Agent Workspace</h3></div><p>Selected specialists run in parallel from the same task snapshot.</p></div>}
    <div className="agent-workspace-flow">{values.map((agent) => <AgentCard key={agent.id} agent={agent} now={now}/>)}</div>
  </section>
}

export function AgentWorkingIndicator({ agents }: { agents: AgentWorkspaceState }) {
  const running = Object.values(agents).filter((agent) => agent.status === 'running')
  if (running.length === 0) return null
  const names = running.map((agent) => metadata[agent.id]?.name || agent.id)
  return <div className="agent-working-indicator" role="status" aria-live="polite">
    <LoaderCircle size={14} className="agent-status-spinner" aria-hidden="true" />
    <span>正在工作：{names.join('、')}</span>
  </div>
}
