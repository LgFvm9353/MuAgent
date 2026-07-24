import { Code2, File, FileJson, FileText, RefreshCw, TriangleAlert } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { ApiError, getTaskArtifactContent, getTaskArtifacts } from '../lib/api'
import type { ArtifactPreviewType, TaskArtifact, TaskArtifactContent } from '../types/api'

const typeLabel: Record<ArtifactPreviewType, string> = {
  text: '文本',
  markdown: 'Markdown',
  json: 'JSON',
  code: '代码',
  unsupported: '不支持预览',
}

function FileIcon({ type }: { type: ArtifactPreviewType }) {
  if (type === 'json') return <FileJson size={15}/>
  if (type === 'code') return <Code2 size={15}/>
  if (type === 'markdown' || type === 'text') return <FileText size={15}/>
  return <File size={15}/>
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function safeMarkdownUrl(url: string): string {
  const trimmed = url.trim()
  if (/^(https?:|mailto:)/i.test(trimmed) || trimmed.startsWith('#')) return trimmed
  return ''
}

function ContentPreview({ artifact }: { artifact: TaskArtifactContent }) {
  if (artifact.preview_type === 'markdown') {
    return <div className="artifact-markdown">
      <Markdown
        remarkPlugins={[remarkGfm]}
        urlTransform={safeMarkdownUrl}
        components={{
          a: ({ children, ...props }) => <a {...props} target="_blank" rel="noreferrer noopener">{children}</a>,
          img: ({ alt }) => <span className="artifact-image-placeholder">[图片：{alt || '无描述'}]</span>,
        }}
      >{artifact.content}</Markdown>
    </div>
  }

  let content = artifact.content
  let warning: string | null = null
  if (artifact.preview_type === 'json') {
    try {
      content = JSON.stringify(JSON.parse(content), null, 2)
    } catch {
      warning = 'JSON 尚未形成有效格式，当前按原始文本显示。'
    }
  }
  return <div className="artifact-code-wrap">
    {warning && <p className="artifact-preview-warning"><TriangleAlert size={13}/>{warning}</p>}
    <pre className="artifact-code"><code>{content}</code></pre>
  </div>
}

function errorText(error: unknown): string {
  if (error instanceof ApiError) {
    const messages: Record<string, string> = {
      preview_too_large: '文件超过 256 KB，无法在线预览。',
      preview_unsupported: '该文件类型暂不支持在线预览。',
      preview_not_utf8: '文件不是有效的 UTF-8 文本。',
      artifact_not_found: '文件已不存在，请刷新列表。',
      workspace_not_found: '任务尚未生成产物目录。',
    }
    return messages[error.message] || error.message
  }
  return '读取任务产物失败。'
}

export function TaskArtifactsPanel({ taskId, refreshKey }: { taskId: string; refreshKey: string }) {
  const [artifacts, setArtifacts] = useState<TaskArtifact[]>([])
  const [selectedPath, setSelectedPath] = useState<string | null>(null)
  const [content, setContent] = useState<TaskArtifactContent | null>(null)
  const [loadingList, setLoadingList] = useState(true)
  const [loadingContent, setLoadingContent] = useState(false)
  const [contentRevision, setContentRevision] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const listController = useRef<AbortController | null>(null)
  const contentController = useRef<AbortController | null>(null)

  const loadArtifacts = useCallback(async () => {
    listController.current?.abort()
    const controller = new AbortController()
    listController.current = controller
    setLoadingList(true)
    setError(null)
    try {
      const files = await getTaskArtifacts(taskId, controller.signal)
      setArtifacts(files)
      setSelectedPath((current) => {
        if (current && files.some((file) => file.path === current && file.preview_type !== 'unsupported')) return current
        return files.find((file) => file.preview_type !== 'unsupported')?.path || null
      })
    } catch (cause) {
      if (!(cause instanceof DOMException && cause.name === 'AbortError')) setError(errorText(cause))
    } finally {
      if (!controller.signal.aborted) setLoadingList(false)
    }
  }, [taskId])

  useEffect(() => {
    void loadArtifacts()
    return () => listController.current?.abort()
  }, [loadArtifacts, refreshKey])

  useEffect(() => {
    contentController.current?.abort()
    setContent(null)
    if (!selectedPath) return
    const controller = new AbortController()
    contentController.current = controller
    setLoadingContent(true)
    setError(null)
    void getTaskArtifactContent(taskId, selectedPath, controller.signal)
      .then((result) => { if (!controller.signal.aborted) setContent(result) })
      .catch((cause) => {
        if (!(cause instanceof DOMException && cause.name === 'AbortError')) setError(errorText(cause))
      })
      .finally(() => { if (!controller.signal.aborted) setLoadingContent(false) })
    return () => controller.abort()
  }, [contentRevision, selectedPath, taskId])

  const selected = useMemo(() => artifacts.find((file) => file.path === selectedPath) || null, [artifacts, selectedPath])

  return <section className="artifacts-panel" aria-label="任务产物在线预览">
    <div className="artifacts-heading">
      <div><span className="eyebrow">执行成果</span><h3>任务产物</h3></div>
      <button className="secondary-button" onClick={() => void loadArtifacts()} disabled={loadingList}><RefreshCw size={13}/>刷新</button>
    </div>
    {loadingList && artifacts.length === 0
      ? <div className="artifact-empty">正在读取任务产物…</div>
      : artifacts.length === 0
        ? <div className="artifact-empty">当前任务尚未生成可查看的文件。</div>
        : <div className="artifacts-layout">
          <nav className="artifact-list" aria-label="产物文件列表">
            {artifacts.map((artifact) => <button
              key={artifact.path}
              className={`artifact-list-item ${selectedPath === artifact.path ? 'artifact-list-item-active' : ''}`}
              disabled={artifact.preview_type === 'unsupported'}
              onClick={() => setSelectedPath(artifact.path)}
              title={artifact.preview_type === 'unsupported' ? '此文件类型不支持预览' : artifact.path}
            >
              <FileIcon type={artifact.preview_type}/>
              <span><strong>{artifact.path}</strong><small>{typeLabel[artifact.preview_type]} · {formatBytes(artifact.size_bytes)}</small></span>
            </button>)}
          </nav>
          <div className="artifact-preview">
            {selected && <header><div><strong>{selected.path}</strong><span>{typeLabel[selected.preview_type]} · {formatBytes(selected.size_bytes)}</span></div></header>}
            {error
              ? <div className="artifact-empty artifact-error"><TriangleAlert size={18}/>{error}<button className="secondary-button" onClick={() => setContentRevision((value) => value + 1)}>重试</button></div>
              : loadingContent
                ? <div className="artifact-empty">正在加载文件内容…</div>
                : content
                  ? <ContentPreview artifact={content}/>
                  : <div className="artifact-empty">请选择一个可预览文件。</div>}
          </div>
        </div>}
  </section>
}
