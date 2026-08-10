import { useEffect, useRef, useState } from 'react'
import { API_BASE_URL } from '../lib/api'
import type { ConversationMessage, StreamStatus } from '../types/api'

const createEventSource = (url: string) => new EventSource(url)

interface Options {
  conversationId: string | null
  after: number
  active: boolean
  onMessage: (message: ConversationMessage) => void
  onWarning: () => void
  eventSourceFactory?: (url: string) => EventSource
}

export function useConversationStream({
  conversationId,
  after,
  active,
  onMessage,
  onWarning,
  eventSourceFactory = createEventSource,
}: Options): StreamStatus {
  const [status, setStatus] = useState<StreamStatus>('idle')
  const handlers = useRef({ onMessage, onWarning })
  handlers.current = { onMessage, onWarning }

  useEffect(() => {
    if (!conversationId || !active) {
      setStatus(conversationId ? 'closed' : 'idle')
      return
    }

    let warned = false
    let disposed = false
    let cursor = after
    setStatus('connecting')
    const source = eventSourceFactory(
      `${API_BASE_URL}/conversations/${conversationId}/stream?after=${after}`,
    )

    source.onopen = () => {
      warned = false
      setStatus('connected')
    }
    source.addEventListener('message', (rawEvent) => {
      if (disposed) return
      try {
        const event = rawEvent as MessageEvent<string>
        const message = JSON.parse(event.data) as ConversationMessage
        if (!Number.isInteger(message.id) || message.id <= cursor) return
        cursor = message.id
        handlers.current.onMessage(message)
      } catch {
        setStatus('error')
        if (!warned) {
          warned = true
          handlers.current.onWarning()
        }
      }
    })
    source.addEventListener('heartbeat', () => {
      if (!disposed) setStatus('connected')
    })
    source.onerror = () => {
      if (disposed) return
      setStatus('reconnecting')
      if (!warned) {
        warned = true
        handlers.current.onWarning()
      }
    }

    return () => {
      disposed = true
      source.close()
    }
    // `after` is the initial cursor. Incoming messages must not recreate the stream.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, conversationId])

  return status
}
