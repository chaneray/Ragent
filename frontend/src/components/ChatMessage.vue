<script setup lang="ts">
import { computed } from 'vue'
import MarkdownIt from 'markdown-it'
import { WarningFilled, RefreshRight } from '@element-plus/icons-vue'

const props = defineProps<{
  role: 'user' | 'assistant'
  content: string
  citations?: string | null
  streaming?: boolean
  isError?: boolean
}>()

const emit = defineEmits<{
  retry: []
}>()

const isUser = computed(() => props.role === 'user')
const md = new MarkdownIt({ html: true, breaks: true })

function renderMarkdown(text: string): string {
  return md.render(text) || text
}

// 从错误消息中提取原因
const errorDetail = computed(() => {
  if (!props.isError) return ''
  return props.content.replace(/^对话出错[：:]\s*/, '')
})
</script>

<template>
  <div class="message-row" :class="{ 'user-row': isUser, 'assistant-row': !isUser }">
    <div class="avatar" :class="isUser ? 'user-avatar' : 'ai-avatar'">
      {{ isUser ? 'U' : 'AI' }}
    </div>
    <div class="bubble" :class="{
      'user-bubble': isUser,
      'assistant-bubble': !isUser,
      'error-bubble': isError,
    }">
      <!-- 用户消息：纯文本 -->
      <div v-if="isUser" class="text">{{ content }}</div>
      <!-- 错误气泡 -->
      <div v-else-if="isError" class="error-content">
        <el-icon class="error-icon"><WarningFilled /></el-icon>
        <span class="error-text">出错了，{{ errorDetail }}</span>
        <button class="error-retry" @click="emit('retry')">
          <el-icon><RefreshRight /></el-icon>
        </button>
      </div>
      <!-- AI 消息：流式中纯文本 + 光标，流结束后 Markdown 渲染 -->
      <div v-else-if="streaming" class="text streaming">{{ content }}</div>
      <div v-else class="markdown-body" v-html="renderMarkdown(content)"></div>
    </div>
  </div>
</template>

<style scoped>
.message-row {
  display: flex;
  gap: 12px;
  margin-bottom: 20px;
  max-width: 800px;
}
.user-row { flex-direction: row-reverse; margin-left: auto; }
.assistant-row { margin-right: auto; }
.avatar {
  width: 36px; height: 36px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font-size: 14px; font-weight: 700; flex-shrink: 0;
}
.user-avatar { background: #409eff; color: #fff; }
.ai-avatar { background: #67c23a; color: #fff; }
.bubble {
  padding: 12px 16px; border-radius: 12px; line-height: 1.6;
  max-width: 85%; font-size: 14px;
}
.user-bubble { background: #ecf5ff; color: #303133; }
.assistant-bubble { background: #fff; border: 1px solid #e4e7ed; color: #303133; }
.text { white-space: pre-wrap; word-break: break-word; }

/* ── 错误气泡 ── */
.error-bubble {
  background: #f7f7f8;
  border: 1px solid #e8e8e8;
  color: #303133;
  animation: error-enter 0.2s ease-out;
}
@keyframes error-enter {
  from { opacity: 0; transform: translateY(4px); }
  to { opacity: 1; transform: translateY(0); }
}

.error-content {
  display: flex;
  align-items: center;
  gap: 8px;
}

.error-icon {
  color: #e6a23c;
  font-size: 16px;
  flex-shrink: 0;
}

.error-text {
  font-size: 14px;
  color: #606266;
  flex: 1;
}

.error-retry {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: #909399;
  cursor: pointer;
  transition: all 0.15s ease;
  flex-shrink: 0;
}

.error-retry:hover {
  background: #ebeef5;
  color: #409eff;
}

.error-retry:active {
  transform: scale(0.9);
}

/* ── 流式闪烁光标 ── */
.streaming::after {
  content: '▌';
  animation: blink 1s step-end infinite;
  color: #409eff;
  margin-left: 1px;
}
@keyframes blink { 50% { opacity: 0; } }

/* ── Markdown 渲染 ── */
.markdown-body { word-break: break-word; }
.markdown-body :deep(p) { margin: 0 0 8px; }
.markdown-body :deep(h1), .markdown-body :deep(h2), .markdown-body :deep(h3),
.markdown-body :deep(h4), .markdown-body :deep(h5), .markdown-body :deep(h6) {
  margin: 16px 0 8px; font-weight: 600;
}
.markdown-body :deep(h1) { font-size: 1.5em; }
.markdown-body :deep(h2) { font-size: 1.3em; }
.markdown-body :deep(h3) { font-size: 1.1em; }
.markdown-body :deep(ul), .markdown-body :deep(ol) { margin: 8px 0; padding-left: 24px; }
.markdown-body :deep(li) { margin: 4px 0; }
.markdown-body :deep(pre) { background: #f5f7fa; padding: 12px; border-radius: 8px; overflow-x: auto; margin: 8px 0; }
.markdown-body :deep(code) { font-size: 13px; }
.markdown-body :deep(table) { border-collapse: collapse; width: 100%; margin: 8px 0; }
.markdown-body :deep(th), .markdown-body :deep(td) { border: 1px solid #e4e7ed; padding: 6px 10px; text-align: left; }
.markdown-body :deep(th) { background: #f5f7fa; }
.markdown-body :deep(blockquote) { border-left: 4px solid #409eff; padding-left: 12px; margin: 8px 0; color: #606266; }
</style>
