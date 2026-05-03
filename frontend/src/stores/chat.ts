import { defineStore } from 'pinia'
import { ref, watch } from 'vue'
import { createSessionApi, getSessionsApi, getSessionApi, deleteSessionApi } from '@/api/chat'
import { useSSE } from '@/composables/useSSE'
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

  const sse = useSSE({ maxRetries: 3, retryDelay: 1000 })

  // ── 持久化：流式过程中保存 currentAnswer 到 sessionStorage ──

  watch(currentAnswer, (val) => {
    if (streaming.value && currentSessionId.value) {
      sessionStorage.setItem(`streaming_${currentSessionId.value}`, val)
    }
  })

  function clearStreamingCache(sessionId: number) {
    sessionStorage.removeItem(`streaming_${sessionId}`)
  }

  function restoreStreamingAnswer(sessionId: number) {
    const saved = sessionStorage.getItem(`streaming_${sessionId}`)
    if (saved) {
      messages.value.push({
        id: nextTempId(), session_id: sessionId, role: 'assistant',
        content: saved + '\n\n（回答可能不完整，已从缓存恢复）',
        citations: null, created_at: '',
      })
      sessionStorage.removeItem(`streaming_${sessionId}`)
    }
  }

  // ── 会话 CRUD ──

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
    restoreStreamingAnswer(sessionId)
  }

  async function deleteSession(sessionId: number) {
    await deleteSessionApi(sessionId)
    if (currentSessionId.value === sessionId) {
      currentSessionId.value = null
      messages.value = []
    }
    clearStreamingCache(sessionId)
    await fetchSessions()
  }

  // ── 发送消息 ──

  async function sendMessage(question: string, kbIds: string[]) {
    if (!currentSessionId.value) {
      const session = await createSession()
      currentSessionId.value = session.id
    }

    // 插入用户消息
    messages.value.push({
      id: nextTempId(), session_id: currentSessionId.value, role: 'user',
      content: question, citations: null, created_at: '',
    })

    streaming.value = true
    currentAnswer.value = ''

    const token = localStorage.getItem('token')
    const sessionId = currentSessionId.value

    await sse.connect(
      `${API_BASE}/chat/stream`,
      { question, session_id: sessionId, knowledge_base_ids: kbIds },
      { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' },
      {
        onToken(data) {
          currentAnswer.value += data
        },
        onDone() {
          if (currentAnswer.value) {
            messages.value.push({
              id: nextTempId(), session_id: sessionId, role: 'assistant',
              content: currentAnswer.value, citations: null, created_at: '',
            })
          }
          currentAnswer.value = ''
          clearStreamingCache(sessionId)
        },
        onError(message) {
          messages.value.push({
            id: nextTempId(), session_id: sessionId, role: 'assistant',
            content: `对话出错：${message}`, citations: null, created_at: '',
            isError: true,
          })
          currentAnswer.value = ''
          clearStreamingCache(sessionId)
        },
        onReconnecting(attempt) {
          console.log(`SSE 重连中，第 ${attempt} 次...`)
        },
      },
    )

    streaming.value = false
  }

  return {
    sessions, currentSessionId, messages, streaming, currentAnswer,
    fetchSessions, createSession, selectSession, deleteSession, sendMessage,
  }
})
