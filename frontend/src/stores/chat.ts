import { defineStore } from 'pinia'
import { ref } from 'vue'
import { createSessionApi, getSessionsApi, getSessionApi, deleteSessionApi } from '@/api/chat'
import type { Session, Message } from '@/types'

const API_BASE = '/api/v1'

let _tempId = 0
function nextTempId() { _tempId--; return _tempId }

export const useChatStore = defineStore('chat', () => {
  const sessions = ref<Session[]>([])
  const currentSessionId = ref<number | null>(null)
  const messages = ref<Message[]>([])
  const streaming = ref(false)
  const currentAnswer = ref('')

  async function fetchSessions() {
    const res = await getSessionsApi()
    sessions.value = res.data.items || []
  }

  async function createSession() {
    const res = await createSessionApi()
    await fetchSessions()
    return res.data
  }

  async function selectSession(sessionId: number) {
    currentSessionId.value = sessionId
    const res = await getSessionApi(sessionId)
    messages.value = res.data.items || []
  }

  async function deleteSession(sessionId: number) {
    await deleteSessionApi(sessionId)
    if (currentSessionId.value === sessionId) {
      currentSessionId.value = null
      messages.value = []
    }
    await fetchSessions()
  }

  async function sendMessage(question: string, kbIds: string[]) {
    if (!currentSessionId.value) {
      const session = await createSession()
      currentSessionId.value = session.id
    }

    messages.value.push({
      id: nextTempId(), session_id: currentSessionId.value, role: 'user',
      content: question, citations: null, created_at: '',
    })

    streaming.value = true
    currentAnswer.value = ''

    const token = localStorage.getItem('token')
    const response = await fetch(`${API_BASE}/chat/stream`, {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, session_id: currentSessionId.value, knowledge_base_ids: kbIds }),
    })

    const reader = response.body!.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      // 统一换行符：sse-starlette 3.x 使用 \r\n，需先归一化为 \n
      buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n')

      const blocks = buffer.split('\n\n')
      buffer = blocks.pop() || ''

      for (const block of blocks) {
        const lines = block.split('\n')
        let eventType = ''
        let data = ''
        for (const line of lines) {
          if (line.startsWith('event: ')) eventType = line.slice(7)
          else if (line.startsWith('data: ')) data = line.slice(6)
        }

        if (eventType === 'token') {
          currentAnswer.value += data
        } else if (eventType === 'done') {
          if (currentAnswer.value) {
            messages.value.push({
              id: nextTempId(), session_id: currentSessionId.value!, role: 'assistant',
              content: currentAnswer.value, citations: null, created_at: '',
            })
            currentAnswer.value = ''
          }
        } else if (eventType === 'error') {
          console.error('对话错误:', data)
        }
      }
    }

    streaming.value = false
  }

  return {
    sessions, currentSessionId, messages, streaming, currentAnswer,
    fetchSessions, createSession, selectSession, deleteSession, sendMessage,
  }
})
