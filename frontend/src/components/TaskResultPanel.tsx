import { CheckCircle2, FileCode2, ListChecks, TerminalSquare } from 'lucide-react'
import type { TaskResult } from '../types/api'

function value(value: unknown): string {
  if (typeof value === 'string') return value
  return JSON.stringify(value, null, 2)
}

export function TaskResultPanel({ result }: { result: TaskResult | null }) {
  if (!result || (!result.plan && result.evidence.length === 0 && !result.verification)) return null

  return <section className="result-panel" aria-label="任务执行结果">
    {result.plan && <article className="result-card">
      <div className="result-card-title"><ListChecks size={17}/><strong>架构师执行计划</strong><span>v{result.plan_version}</span></div>
      <div className="result-list">{result.steps.map((step) => <div key={step.id} className="result-row"><span className={`state-pill state-${step.status}`}>{step.status}</span><span>{value(step.content.step_id || step.content.expected_result || step.id)}</span></div>)}</div>
    </article>}

    {result.tool_calls.length > 0 && <article className="result-card">
      <div className="result-card-title"><TerminalSquare size={17}/><strong>工具执行</strong></div>
      <div className="result-list">{result.tool_calls.map((call) => <details key={call.id}><summary><span>{call.tool_name}</span><span>{call.status}</span></summary><pre>{JSON.stringify({ arguments: call.arguments, result: call.result, error_type: call.error_type }, null, 2)}</pre></details>)}</div>
    </article>}

    {result.evidence.length > 0 && <article className="result-card">
      <div className="result-card-title"><FileCode2 size={17}/><strong>执行证据</strong><span>{result.evidence.length} 项</span></div>
      <div className="result-list">{result.evidence.map((item) => <details key={item.id}><summary><span>{item.kind}</span><span>{item.sha256 ? item.sha256.slice(0, 12) : '已记录'}</span></summary><pre>{JSON.stringify(item.content, null, 2)}</pre></details>)}</div>
    </article>}

    {result.verification && <article className="result-card result-card-verification">
      <div className="result-card-title"><CheckCircle2 size={17}/><strong>独立验证</strong></div>
      <p>{value(result.verification.rationale || result.verification.verdict)}</p>
      <div className="usage-line"><span>输入 {result.usage.input_tokens.toLocaleString()} tokens</span><span>输出 {result.usage.output_tokens.toLocaleString()} tokens</span><span>耗时 {(result.usage.latency_ms / 1000).toFixed(1)}s</span><span>费用 ${result.usage.estimated_cost_usd.toFixed(4)}</span></div>
    </article>}
  </section>
}
