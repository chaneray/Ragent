<script setup lang="ts">
import { ref, onMounted, nextTick, computed, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowDown, QuestionFilled } from '@element-plus/icons-vue'
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
const selectedKbIds = ref<string[]>([])

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
  selectedKbIds.value = kbIds
  try {
    await chatStore.sendMessage(question, kbIds)
  } catch (err) {
    ElMessage.error('对话请求失败')
  }
}

async function handleClarification(option: string) {
  try {
    await chatStore.answerClarification(option, selectedKbIds.value)
  } catch (err) {
    ElMessage.error('澄清回答失败')
  }
}

async function handleRetry(errorMsg: { id: number; content: string }) {
  const msgs = chatStore.messages
  const errorIdx = msgs.findIndex(m => m.id === errorMsg.id)
  if (errorIdx < 0) return
  const lastUserMsg = [...msgs].slice(0, errorIdx).reverse().find(m => m.role === 'user')
  if (!lastUserMsg) return
  chatStore.messages.splice(errorIdx, 1)
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

function onScroll() {
  const el = messagesArea.value
  if (!el) return
  isUserScrolledUp.value = el.scrollHeight - el.scrollTop - el.clientHeight > 100
}

watch(() => chatStore.currentAnswer, () => {
  if (!isUserScrolledUp.value) scrollToBottom()
})

watch(() => chatStore.messages.length, () => {
  isUserScrolledUp.value = false
  scrollToBottom(false)
})

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
        v-if="displayedMessages.length || chatStore.clarification"
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

        <!-- 澄清问题 -->
        <div v-if="chatStore.clarification" class="clarification-card">
          <div class="clarification-header">
            <el-icon><QuestionFilled /></el-icon>
            <span>需要澄清</span>
          </div>
          <div class="clarification-question">{{ chatStore.clarification.question }}</div>
          <div class="clarification-options">
            <el-button
              v-for="option in chatStore.clarification.options"
              :key="option"
              type="primary"
              plain
              size="small"
              @click="handleClarification(option)"
            >
              {{ option }}
            </el-button>
          </div>
        </div>

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

/* 澄清卡片 */
.clarification-card {
  background: #fff;
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  padding: 16px;
  margin: 16px 0;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
}

.clarification-header {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #e6a23c;
  font-weight: 500;
  margin-bottom: 12px;
}

.clarification-question {
  color: #303133;
  font-size: 14px;
  line-height: 1.6;
  margin-bottom: 16px;
}

.clarification-options {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
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

.fade-enter-active, .fade-leave-active {
  transition: opacity 0.2s ease;
}
.fade-enter-from, .fade-leave-to {
  opacity: 0;
}
</style>
