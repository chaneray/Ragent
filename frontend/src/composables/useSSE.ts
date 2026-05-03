import { ref } from 'vue'

export interface SSECallbacks {
  onToken: (data: string) => void
  onDone: () => void
  onError: (message: string) => void
  onReconnecting?: (attempt: number) => void
}

export interface SSEOptions {
  maxRetries?: number
  retryDelay?: number
}

/** 读取超时：超过此时间未收到数据，视为断线 */
const READ_TIMEOUT_MS = 30_000

export function useSSE(options?: SSEOptions) {
  const maxRetries = options?.maxRetries ?? 3
  const baseDelay = options?.retryDelay ?? 1000

  const isStreaming = ref(false)
  const retryCount = ref(0)
  let abortController: AbortController | null = null

  /**
   * 解析 SSE 块，提取事件类型和数据
   * SSE 协议：多行 data: 用换行符连接
   */
  function parseSSEBlock(block: string): { eventType: string; data: string } {
    let eventType = ''
    const dataLines: string[] = []
    for (const line of block.split('\n')) {
      if (line.startsWith('event: ')) eventType = line.slice(7)
      else if (line.startsWith('data: ')) dataLines.push(line.slice(6))
      else if (line === 'data:') dataLines.push('')
    }
    return { eventType, data: dataLines.join('\n') }
  }

  /**
   * 单次 SSE 连接（不含重连）
   * 返回 true 表示正常结束，false 表示中断
   */
  async function connectOnce(
    url: string,
    body: object,
    headers: Record<string, string>,
    callbacks: SSECallbacks,
  ): Promise<boolean> {
    abortController = new AbortController()

    const response = await fetch(url, {
      method: 'POST',
      headers,
      body: JSON.stringify(body),
      signal: abortController.signal,
    })

    // HTTP 错误处理
    if (!response.ok) {
      let errorMsg = `请求失败 (${response.status})`
      try {
        const errBody = await response.text()
        const parsed = JSON.parse(errBody)
        errorMsg = parsed.detail || errorMsg
      } catch { /* 忽略解析失败 */ }
      callbacks.onError(errorMsg)
      return false
    }

    if (!response.body) {
      callbacks.onError('响应体为空')
      return false
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let receivedDone = false
    let lastDataTime = Date.now()

    // 带超时的读取：防止服务端断开后 read() 永久挂起
    function readWithTimeout(): Promise<ReadableStreamReadResult<Uint8Array>> {
      return Promise.race([
        reader.read(),
        new Promise<ReadableStreamReadResult<Uint8Array>>((_, reject) => {
          const elapsed = Date.now() - lastDataTime
          const remaining = READ_TIMEOUT_MS - elapsed
          const timer = setTimeout(
            () => reject(new Error(`读取超时（${READ_TIMEOUT_MS / 1000}s 未收到数据）`)),
            Math.max(remaining, 1000),
          )
          // abort 时清除定时器
          abortController?.signal.addEventListener('abort', () => clearTimeout(timer))
        }),
      ])
    }

    try {
      while (true) {
        const { done, value } = await readWithTimeout()
        if (done) break
        lastDataTime = Date.now()

        // 统一换行符：sse-starlette 3.x 使用 \r\n
        buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n')
        const blocks = buffer.split('\n\n')
        buffer = blocks.pop() || ''

        for (const block of blocks) {
          if (!block.trim()) continue
          const { eventType, data } = parseSSEBlock(block)

          if (eventType === 'token') {
            callbacks.onToken(data)
          } else if (eventType === 'done') {
            receivedDone = true
            callbacks.onDone()
          } else if (eventType === 'error') {
            callbacks.onError(data || '对话出错')
            return false
          }
        }
      }
    } catch (err) {
      if (abortController?.signal.aborted) {
        return false // 用户主动取消
      }
      throw err // 网络错误，交给重连逻辑
    }

    // 流结束但未收到 done 事件，视为异常
    if (!receivedDone) {
      throw new Error('流结束但未收到 done 事件')
    }

    return true
  }

  /**
   * 带重连的 SSE 连接
   */
  async function connect(
    url: string,
    body: object,
    headers: Record<string, string>,
    callbacks: SSECallbacks,
  ): Promise<void> {
    isStreaming.value = true
    retryCount.value = 0

    try {
      while (retryCount.value <= maxRetries) {
        try {
          const success = await connectOnce(url, body, headers, callbacks)
          if (success) return
          // 非网络错误（如 HTTP 错误），不重连
          return
        } catch (err) {
          // 用户主动取消
          if (abortController?.signal.aborted) return

          retryCount.value++
          if (retryCount.value > maxRetries) {
            callbacks.onError('连接中断，请重试')
            return
          }

          // 指数退避
          const delay = baseDelay * Math.pow(2, retryCount.value - 1)
          callbacks.onReconnecting?.(retryCount.value)
          await new Promise(resolve => setTimeout(resolve, delay))
        }
      }
    } finally {
      isStreaming.value = false
      abortController = null
    }
  }

  /**
   * 手动取消正在进行的流
   */
  function abort() {
    abortController?.abort()
  }

  return { isStreaming, retryCount, connect, abort }
}
