<script setup lang="ts">
import { ref, onMounted, nextTick, computed, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowDown } from '@element-plus/icons-vue'
import { useChatStore } from '@/stores/chat'
import { useKnowledgeBaseStore } from '@/stores/knowledgeBase'
import ChatMessage from '@/components/ChatMessage.vue'
import ChatInput from '@/components/ChatInput.vue'

const route = useRoute()
const chatStore = useChatStore()
const kbStore = useKnowledgeBaseStore()

const messagesEnd = ref<HTMLElement | null>(null)
const messagesArea = ref<HTMLElement | null>(null)
const isUserScrolledUp = ref(false)

const kbOptions = computed(() =>
  kbStore.list.map(kb => ({ id: kb.id, name: kb.name }))
)

const displayedMessages = computed(() => {
  const msgs = [...chatStore.messages]
  if (chatStore.streaming && chatStore.currentAnswer) {
    msgs.push({
      id: -9999, session_id: chatStore.currentSessionId || 0,
      role: 'assistant', content: chatStore.currentAnswer,
      citations: null, created_at: '',
    })
  }
  return msgs
})

async function handleSend(question: string, kbIds: string[]) {
  try {
    await chatStore.sendMessage(question, kbIds)
  } catch (err) {
    ElMessage.error('对话请求失败')
  }
}

async function handleRetry(errorMsg: { id: number; content: string }) {
  // 找到错误消息之前的最后一条用户消息
  const msgs = chatStore.messages
  const errorIdx = msgs.findIndex(m => m.id === errorMsg.id)
  if (errorIdx < 0) return
  const lastUserMsg = [...msgs].slice(0, errorIdx).reverse().find(m => m.role === 'user')
  if (!lastUserMsg) return
  // 删除错误消息
  chatStore.messages.splice(errorIdx, 1)
  // 重新发送
  try {
    await chatStore.sendMessage(lastUserMsg.content, [])
  } catch (err) {
    ElMessage.error('重试失败')
  }
}

async function handleNewSession() {
  await chatStore.createSession()
}

async function handleSelectSession(sessionId: number) {
  await chatStore.selectSession(sessionId)
}

async function handleDeleteSession(sessionId: number) {
  await chatStore.deleteSession(sessionId)
}

// ── 滚动逻辑 ──

async function scrollToBottom(smooth = true) {
  await nextTick()
  messagesEnd.value?.scrollIntoView({ behavior: smooth ? 'smooth' : 'instant' })
}

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
  scrollToBottom(false)
})

// "跳转最新"按钮
function scrollToLatest() {
  isUserScrolledUp.value = false
  scrollToBottom()
}

onMounted(async () => {
  await Promise.all([chatStore.fetchSessions(), kbStore.fetchList()])
  const sid = route.params.sessionId
  if (sid) {
    await chatStore.selectSession(Number(sid))
  }
  // 默认滚到底部
  scrollToBottom(false)
})
</script>

<template>
  <div class="chat-layout">
    <!-- 会话侧栏 -->
    <div class="session-sidebar">
      <div class="sidebar-header">
        <h3>会话</h3>
        <el-button type="primary" size="small" @click="handleNewSession">新对话</el-button>
      </div>
      <div class="session-list">
        <div
          v-for="s in chatStore.sessions"
          :key="s.id"
          class="session-item"
          :class="{ active: s.id === chatStore.currentSessionId }"
          @click="handleSelectSession(s.id)"
        >
          <div class="session-title">{{ s.title }}</div>
          <el-button
            text type="danger" size="small"
            class="session-del"
            @click.stop="handleDeleteSession(s.id)"
          >✕</el-button>
        </div>
        <el-empty v-if="!chatStore.sessions.length" description="暂无会话" :image-size="60" />
      </div>
    </div>

    <!-- 对话主区域 -->
    <div class="chat-main">
      <div
        ref="messagesArea"
        class="messages-area"
        v-if="displayedMessages.length"
        @scroll="onScroll"
      >
        <ChatMessage
          v-for="msg in displayedMessages"
          :key="msg.id"
          :role="msg.role"
          :content="msg.content"
          :citations="msg.citations"
          :streaming="msg.id === -9999"
          :is-error="msg.isError"
          @retry="handleRetry(msg)"
        />
        <div ref="messagesEnd" />

        <!-- 跳转最新按钮 -->
        <Transition name="fade">
          <button
            v-if="isUserScrolledUp"
            class="scroll-to-bottom"
            @click="scrollToLatest"
          >
            <el-icon><ArrowDown /></el-icon>
            <span>跳转到最新</span>
          </button>
        </Transition>
      </div>
      <div class="empty-state" v-else>
        <el-empty description="选择或创建会话开始对话" />
      </div>

      <ChatInput
        :disabled="chatStore.streaming"
        :kb-options="kbOptions"
        @send="handleSend"
      />
    </div>
  </div>
</template>

<style scoped>
.chat-layout {
  display: flex;
  gap: 0;
  height: calc(100vh - 60px - 48px);
  margin: -24px;
}

.session-sidebar {
  width: 240px;
  background: #fff;
  border-right: 1px solid #e4e7ed;
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
}

.sidebar-header {
  padding: 16px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid #e4e7ed;
}

.sidebar-header h3 {
  margin: 0;
  font-size: 16px;
}

.session-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}

.session-item {
  padding: 10px 12px;
  border-radius: 8px;
  cursor: pointer;
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 4px;
  transition: background 0.2s;
}

.session-item:hover { background: #f5f7fa; }
.session-item.active { background: #ecf5ff; color: #409eff; }
.session-title {
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
}
.session-del { opacity: 0; }
.session-item:hover .session-del { opacity: 1; }

.chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  background: #f5f7fa;
}

.messages-area {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
  position: relative;
}

.empty-state {
  flex: 1;
  display: flex;
  justify-content: center;
  align-items: center;
}

/* 跳转最新按钮 */
.scroll-to-bottom {
  position: sticky;
  bottom: 16px;
  float: right;
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 8px 16px;
  border: 1px solid #e4e7ed;
  border-radius: 20px;
  background: rgba(255, 255, 255, 0.9);
  backdrop-filter: blur(4px);
  cursor: pointer;
  font-size: 13px;
  color: #606266;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
  transition: all 0.2s;
  z-index: 10;
}
.scroll-to-bottom:hover {
  background: #fff;
  color: #409eff;
  border-color: #409eff;
}

/* 淡入淡出动画 */
.fade-enter-active, .fade-leave-active {
  transition: opacity 0.2s ease;
}
.fade-enter-from, .fade-leave-to {
  opacity: 0;
}
</style>
