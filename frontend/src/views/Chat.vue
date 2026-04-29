<script setup lang="ts">
import { ref, onMounted, nextTick, computed } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useChatStore } from '@/stores/chat'
import { useKnowledgeBaseStore } from '@/stores/knowledgeBase'
import ChatMessage from '@/components/ChatMessage.vue'
import ChatInput from '@/components/ChatInput.vue'

const route = useRoute()
const chatStore = useChatStore()
const kbStore = useKnowledgeBaseStore()

const messagesEnd = ref<HTMLElement | null>(null)

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

async function handleNewSession() {
  await chatStore.createSession()
}

async function handleSelectSession(sessionId: number) {
  await chatStore.selectSession(sessionId)
}

async function handleDeleteSession(sessionId: number) {
  await chatStore.deleteSession(sessionId)
}

async function scrollToBottom() {
  await nextTick()
  messagesEnd.value?.scrollIntoView({ behavior: 'smooth' })
}

// 流式输出时自动滚动
import { watch } from 'vue'
watch(() => chatStore.currentAnswer, () => scrollToBottom())

onMounted(async () => {
  await Promise.all([chatStore.fetchSessions(), kbStore.fetchList()])
  const sid = route.params.sessionId
  if (sid) {
    await chatStore.selectSession(Number(sid))
  }
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
      <div class="messages-area" v-if="displayedMessages.length">
        <ChatMessage
          v-for="msg in displayedMessages"
          :key="msg.id"
          :role="msg.role"
          :content="msg.content"
          :citations="msg.citations"
        />
        <div ref="messagesEnd" />
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
}

.empty-state {
  flex: 1;
  display: flex;
  justify-content: center;
  align-items: center;
}
</style>
