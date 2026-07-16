import { useEffect, useRef, useState } from 'react'
import { API_BASE_URL } from '../lib/api'
import type { StreamStatus, TaskEvent } from '../types/api'

interface Options {
  taskId: string | null
  after: number
  active: boolean
  onEvent: (event: TaskEvent) => void
  onComplete: () => void
  onWarning: () => void
}

export function useTaskStream({ taskId, after, active, onEvent, onComplete, onWarning }: Options): StreamStatus {
  const [status, setStatus] = useState<StreamStatus>('idle')
  const handlers = useRef({ onEvent, onComplete, onWarning })
  handlers.current = { onEvent, onComplete, onWarning }

  useEffect(() => {
    if (!taskId || !active) {
      setStatus(taskId ? 'closed' : 'idle')
      return
    }

    let warned = false
    setStatus('connecting')
    const source = new EventSource(`${API_BASE_URL}/tasks/${taskId}/stream?after=${after}`)

    source.onopen = () => {
      warned = false
      setStatus('connected')
    }
    source.addEventListener('task_event', (message) => {
      const event = JSON.parse((message as MessageEvent<string>).data) as TaskEvent
      handlers.current.onEvent(event)
    })
    source.addEventListener('task_complete', () => {
      setStatus('closed')
      handlers.current.onComplete()
      source.close()
    })
    source.onerror = () => {
      setStatus('reconnecting')
      if (!warned) {
        warned = true
        handlers.current.onWarning()
      }
    }

    return () => {
      source.close()
    }
    // `after` is the initial cursor for this task. New events must not recreate the stream.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, taskId])

  return status
}
