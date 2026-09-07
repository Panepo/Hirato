import { ref } from 'vue'

import { apiUrl } from '../api/client'
import { useAuthStore } from '../stores/auth'

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

interface SendCallbacks {
  onSessionId?: (sessionId: string) => void
  onTitleUpdated?: (sessionId: string) => void
}

export function useChatStream() {
  const messages = ref<ChatMessage[]>([])
  const sending = ref(false)
  const metricsText = ref('')

  function reset() {
    messages.value = []
    metricsText.value = ''
  }

  async function streamInto(
    res: Response,
    assistantMsg: ChatMessage,
    callbacks: SendCallbacks,
  ): Promise<void> {
    if (!res.ok || !res.body) {
      const data = await res.json().catch(() => ({}))
      throw new Error(data.detail || res.statusText)
    }

    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })

      let boundary: number
      while ((boundary = buffer.indexOf('\n\n')) !== -1) {
        const eventText = buffer.slice(0, boundary)
        buffer = buffer.slice(boundary + 2)

        for (const line of eventText.split('\n')) {
          if (!line.startsWith('data: ')) continue
          let event: Record<string, unknown>
          try {
            event = JSON.parse(line.slice(6))
          } catch {
            continue
          }

          if (event.type === 'session') {
            callbacks.onSessionId?.(event.session_id as string)
          } else if (event.type === 'token') {
            assistantMsg.content += event.content as string
          } else if (event.type === 'metrics') {
            metricsText.value = `\u23F1 First word: ${event.ttfw}s\u2003|\u2003${event.wps} w/s\u2003|\u2003Total: ${event.total}s`
          } else if (event.type === 'done') {
            if (!assistantMsg.content) assistantMsg.content = 'No response generated.'
            if (event.title_updated && event.session_id) callbacks.onTitleUpdated?.(event.session_id as string)
          }
        }
      }
    }
  }

  async function sendMessage(
    text: string,
    channelId: string,
    sessionId: string | null,
    callbacks: SendCallbacks = {},
  ): Promise<void> {
    const auth = useAuthStore()

    messages.value.push({ role: 'user', content: text })
    const assistantMsg: ChatMessage = { role: 'assistant', content: '' }
    messages.value.push(assistantMsg)
    metricsText.value = 'Generating...'
    sending.value = true

    try {
      const res = await fetch(apiUrl('/chat/stream'), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(auth.token ? { Authorization: `Bearer ${auth.token}` } : {}),
        },
        body: JSON.stringify({ message: text, channel_id: channelId, session_id: sessionId }),
      })

      await streamInto(res, assistantMsg, callbacks)
    } catch (e) {
      assistantMsg.content = `Error: ${e instanceof Error ? e.message : String(e)}`
      metricsText.value = ''
    } finally {
      sending.value = false
    }
  }

  async function regenerateMessage(
    channelId: string,
    sessionId: string,
    callbacks: SendCallbacks = {},
  ): Promise<void> {
    if (!sessionId || sending.value) return
    const last = messages.value[messages.value.length - 1]
    if (!last || last.role !== 'assistant') return

    const auth = useAuthStore()

    messages.value.pop()
    const assistantMsg: ChatMessage = { role: 'assistant', content: '' }
    messages.value.push(assistantMsg)
    metricsText.value = 'Generating...'
    sending.value = true

    try {
      const res = await fetch(apiUrl('/chat/regenerate'), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(auth.token ? { Authorization: `Bearer ${auth.token}` } : {}),
        },
        body: JSON.stringify({ channel_id: channelId, session_id: sessionId }),
      })

      await streamInto(res, assistantMsg, callbacks)
    } catch (e) {
      assistantMsg.content = `Error: ${e instanceof Error ? e.message : String(e)}`
      metricsText.value = ''
    } finally {
      sending.value = false
    }
  }

  return { messages, sending, metricsText, sendMessage, regenerateMessage, reset }
}
