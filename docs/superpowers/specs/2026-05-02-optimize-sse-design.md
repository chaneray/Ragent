# 前端 SSE 流式输出优化设计

## 背景

当前前端 SSE 流式对话存在 8 个问题：

1. **流式输出无 Markdown 结构** — 流式时是连续粘连的纯文本，刷新后才显示 MD 格式。原因：LLM 逐 token 输出时 Markdown 标记不完整（如 `# 标` 还没成为 `# 标题`），markdown-it 无法识别为标题结构
2. **进入对话默认显示最顶端** — 应该默认滚到底部显示最新消息
3. **无断线重连** — 网络波动时流直接断开，没有恢复机制
4. **错误处理不足** — `event: error` 仅 `console.error`，用户无感知
5. **无打字机效果** — token 逐个追加但没有光标闪烁
6. **滚动行为粗暴** — 用户手动上滚后仍被强制拉回底部
7. **SSE 逻辑与 Store 耦合** — SSE 解析、协议处理全写在 Pinia store 的 `sendMessage` 中
8. **流式中刷新丢失回答** — `currentAnswer` 是内存状态，刷新即丢失

## 架构设计

### 文件结构

```
frontend/src/
├── composables/
│   └── useSSE.ts          ← 新建：SSE 流式逻辑
├── stores/
│   └── chat.ts            ← 修改：精简，SSE 逻辑委托给 composable
├── views/
│   └── Chat.vue           ← 修改：智能滚动 + 跳转按钮
├── components/
│   └── ChatMessage.vue    ← 修改：流式纯文本+光标 / 结束后 MD 渲染
```

### 职责划分

| 层 | 职责 | 不管什么 |
|---|------|----------|
| `useSSE` | SSE 连接、协议解析、断线重连、错误封装 | 不管 UI 状态 |
| `chat store` | 消息列表、会话、streaming 状态、currentAnswer | 不管 SSE 协议细节 |
| `Chat.vue` | 滚动行为、跳转按钮、消息合成 | 不管 SSE 连接 |
| `ChatMessage.vue` | 渲染策略（纯文本 vs MD）、光标 | 不管数据来源 |

### 数据流

```
用户发送 → store.sendMessage() → useSSE.connect(url, body, callbacks)
                                      ↓ onToken
                                  store.currentAnswer += token
                                      ↓ onDone
                                  store.messages.push(assistant)
                                      ↓ onError
                                  store.messages.push(error bubble)
                                      ↓ onDisconnect (自动重连)
                                  useSSE.reconnect() → 续传内容
```

## 详细设计

### 1. useSSE Composable

**文件**: `src/composables/useSSE.ts`

#### API

```ts
interface SSECallbacks {
  onToken: (data: string) => void
  onDone: () => void
  onError: (message: string) => void
  onReconnecting?: (attempt: number) => void
}

interface SSEOptions {
  maxRetries?: number        // 默认 3
  retryDelay?: number        // 默认 1000ms，指数退避
}

function useSSE(options?: SSEOptions) {
  const isStreaming = ref(false)
  const retryCount = ref(0)

  async function connect(
    url: string,
    body: object,
    headers: Record<string, string>,
    callbacks: SSECallbacks
  ): Promise<void>

  function abort(): void  // 手动取消（用户发新消息时中止旧流）

  return { isStreaming, retryCount, connect, abort }
}
```

#### SSE 协议解析

保持现有三种事件格式：

- `event: token\ndata: <文本>\n\n` — 逐 token 累加
- `event: done\ndata: \n\n` — 流结束
- `event: error\ndata: <错误信息>\n\n` — 错误

解析逻辑从 store 移入 composable，新增：

- **HTTP 错误处理**：`fetch` 返回非 200 时，读取响应体作为错误消息，触发 `onError`
- **`response.body` 空值检查**：移除 `!` 非空断言，null 时触发 `onError`
- **AbortController 支持**：`connect` 内部创建 `AbortController`，`abort()` 时调用 `controller.abort()`，中止正在进行的 fetch 请求

#### 断线重连

```
流中断（reader.read() 抛异常或 done=true 但未收到 done 事件）
  → 等待 retryDelay（指数退避：1s → 2s → 4s）
  → 重新 POST 相同请求（question + session_id + kb_ids）
  → onToken 继续累加（内容续传）
  → 超过 maxRetries → onError("连接中断，请重试")
```

重连时后端无状态，重新 POST 会重新生成回答。`currentAnswer` 不清空，新内容追加到已有内容后。用户体验上是连续的。

**用户消息去重**：`sendMessage` 在首次发送时插入用户消息到 `messages`，重连由 composable 内部处理，不调用 `sendMessage`，因此不会重复插入用户消息。

### 2. Chat Store 精简

**文件**: `src/stores/chat.ts`

变更：

- `sendMessage` 中的 fetch + SSE 解析逻辑全部移除，改为调用 `useSSE().connect()`
- 新增 `isError` 字段到 Message 类型
- 错误时插入错误气泡（`role: 'assistant'`, `isError: true`）
- 新增持久化：流式过程中将 `currentAnswer` 写入 `sessionStorage`
- 流完成/出错时清理 sessionStorage 缓存
- 初始化时检查 sessionStorage，如有缓存则恢复

`sendMessage` 精简后伪代码：

```ts
async function sendMessage(question: string, kbIds: string[]) {
  // 1. 确保有会话
  // 2. 插入用户消息
  // 3. 设置 streaming=true, currentAnswer=''
  // 4. 调用 sse.connect()，传入回调
  //    - onToken: currentAnswer += data
  //    - onDone: messages.push(assistant), 清理缓存
  //    - onError: messages.push(error bubble), 清理缓存
  //    - onReconnecting: 可选 UI 提示
}
```

#### Message 类型扩展

```ts
interface Message {
  id: number
  session_id: number
  role: 'user' | 'assistant'
  content: string
  citations: string | null
  created_at: string
  isError?: boolean  // 新增：错误气泡标记
}
```

### 3. 渲染策略（ChatMessage.vue）

**文件**: `src/components/ChatMessage.vue`

#### 流式 vs 完成状态

```
streaming=true  → 纯文本 + 闪烁光标 "▌"
streaming=false → markdown-it 渲染的 HTML
```

通过新增 `streaming` prop 控制：

```vue
<div v-if="streaming" class="text streaming">{{ content }}</div>
<div v-else class="markdown-body" v-html="renderMarkdown(content)" />
```

#### 闪烁光标

使用 `::after` 伪元素，避免污染纯文本内容：

```css
.streaming::after {
  content: '▌';
  animation: blink 1s step-end infinite;
  color: #409eff;
  margin-left: 1px;
}
@keyframes blink {
  50% { opacity: 0; }
}
```

流结束时通过移除 `.streaming` class（即 `streaming` prop 变为 false）自动隐藏光标，切换为 MD 渲染。

#### 错误气泡样式

```css
.error-bubble {
  background: #fef0f0;
  border-color: #f56c6c;
  color: #f56c6c;
}
```

#### Props 变更

```ts
const props = defineProps<{
  role: 'user' | 'assistant'
  content: string
  citations?: string | null
  streaming?: boolean   // 新增
  isError?: boolean     // 新增
}>()
```

### 4. 滚动行为（Chat.vue）

**文件**: `src/views/Chat.vue`

#### 三个场景

| 场景 | 当前行为 | 目标行为 |
|------|----------|----------|
| 进入对话/切换会话 | 显示最顶端 | 默认滚到底部 |
| 流式输出中 | 每个 token 都强制拉回底部 | 检测用户是否手动上滚，上滚时不拉回 |
| 用户手动上滚后 | 无法快速回到最新 | 显示"跳转最新"悬浮按钮 |

#### 智能滚动逻辑

```ts
const isUserScrolledUp = ref(false)
const messagesArea = ref<HTMLElement | null>(null)

// 监听用户滚动：距离底部 > 100px 视为"手动上滚"
function onScroll() {
  const el = messagesArea.value
  if (!el) return
  isUserScrolledUp.value = el.scrollHeight - el.scrollTop - el.clientHeight > 100
}

// 流式输出时：只有用户没上滚才自动滚底
watch(() => chatStore.currentAnswer, () => {
  if (!isUserScrolledUp.value) scrollToBottom()
})

// 切换会话 / 加载消息后：强制滚底
watch(() => chatStore.messages.length, () => {
  isUserScrolledUp.value = false
  scrollToBottom()
})
```

#### "跳转最新"按钮

```vue
<Transition name="fade">
  <button v-if="isUserScrolledUp" class="scroll-to-bottom" @click="scrollToLatest">
    <el-icon><ArrowDown /></el-icon> 跳转到最新
  </button>
</Transition>
```

- 固定在消息区域右下角，半透明悬浮按钮
- 仅在 `isUserScrolledUp=true` 时显示
- 点击后 `scrollToBottom()` + 重置 `isUserScrolledUp=false`
- 使用 `<Transition>` 做淡入淡出

#### scrollToBottom 改进

```ts
async function scrollToBottom(smooth = true) {
  await nextTick()
  messagesEnd.value?.scrollIntoView({ behavior: smooth ? 'smooth' : 'instant' })
}
```

切换会话时用 `behavior: 'instant'` 避免动画延迟。

### 5. 消息持久化

流式过程中将 `currentAnswer` 写入 `sessionStorage`：

```ts
// 每次 currentAnswer 变化时保存
watch(currentAnswer, (val) => {
  if (streaming.value && currentSessionId.value) {
    sessionStorage.setItem(`streaming_${currentSessionId.value}`, val)
  }
})

// store 初始化时恢复
function restoreStreamingAnswer(sessionId: number) {
  const saved = sessionStorage.getItem(`streaming_${sessionId}`)
  if (saved) {
    // 流已断开，将缓存内容作为普通消息插入
    messages.value.push({
      id: nextTempId(), session_id: sessionId, role: 'assistant',
      content: saved, citations: null, created_at: '', isError: false,
    })
    sessionStorage.removeItem(`streaming_${sessionId}`)
  }
}

// 流完成/出错时清理
function clearStreamingCache(sessionId: number) {
  sessionStorage.removeItem(`streaming_${sessionId}`)
}
```

使用 `sessionStorage` 而非 `localStorage`，避免跨标签页干扰。

**不完整回答处理**：如果页面刷新时 LLM 回答只生成了一半，恢复的消息可能不完整。这是可接受的 v1 行为，用户可以重新发送问题。

## 实施顺序

| 阶段 | 内容 | 涉及文件 |
|------|------|----------|
| 1 | 创建 `useSSE` composable | 新建 `composables/useSSE.ts` |
| 2 | 精简 `chat store`，委托 SSE 逻辑 | `stores/chat.ts`, `types/index.ts` |
| 3 | ChatMessage 渲染策略 + 光标 | `components/ChatMessage.vue` |
| 4 | 智能滚动 + 跳转按钮 | `views/Chat.vue` |
| 5 | 错误气泡 + 消息持久化 | `stores/chat.ts`, `components/ChatMessage.vue` |

阶段 1-2 是核心架构变更，阶段 3-5 是体验优化，互相独立可以分开提交。

## 后端影响

无需后端改动。断线重连时重新 POST 相同请求，后端当前的无状态设计已支持。

## 测试要点

1. 流式输出时光标闪烁，结束后切换为 MD 渲染
2. 进入对话自动滚到底部
3. 流式中手动上滚不被拉回，出现"跳转最新"按钮
4. 断网模拟：流中断后自动重连，内容继续累加
5. 错误气泡显示红色样式
6. 刷新页面后未完成的回答从 sessionStorage 恢复
7. 代码块、表格等复杂 MD 在流结束后正确渲染
