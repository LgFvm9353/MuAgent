import { useEffect, useRef, useState } from 'react'
import { API_BASE_URL } from '../lib/api'
import type { ConversationMessage, StreamStatus, TaskEvent } from '../types/api'

interface Options {
  taskId: string | null
  after: number
  messageAfter: number
  active: boolean
  onEvent: (event: TaskEvent) => void
  onMessage: (message: ConversationMessage) => void
  onComplete: () => void
  onWarning: () => void
}

export function useTaskStream({ taskId, after, messageAfter, active, onEvent, onMessage, onComplete, onWarning }: Options): StreamStatus {
  const [status, setStatus] = useState<StreamStatus>('idle')
  const handlers = useRef({ onEvent, onMessage, onComplete, onWarning })
  handlers.current = { onEvent, onMessage, onComplete, onWarning }

  useEffect(() => {
    if (!taskId || !active) {
      setStatus(taskId ? 'closed' : 'idle')
      return
    }

    let warned = false
    setStatus('connecting')
    const source = new EventSource(`${API_BASE_URL}/tasks/${taskId}/stream?after=${after}&message_after=${messageAfter}`)

    source.onopen = () => {
      warned = false
      setStatus('connected')
    }
    source.addEventListener('task_event', (message) => {
      const event = JSON.parse((message as MessageEvent<string>).data) as TaskEvent
      handlers.current.onEvent(event)
    })
    source.addEventListener('conversation_message', (event) => {
      const message = JSON.parse((event as MessageEvent<string>).data) as ConversationMessage
      handlers.current.onMessage(message)
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
