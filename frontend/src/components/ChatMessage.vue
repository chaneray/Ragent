<script setup lang="ts">
import { computed } from 'vue'
import MarkdownIt from 'markdown-it'

const props = defineProps<{
  role: 'user' | 'assistant'
  content: string
  citations?: string | null
}>()

const isUser = computed(() => props.role === 'user')
const md = new MarkdownIt({ html: true, breaks: true })

function renderMarkdown(text: string): string {
  return md.render(text) || text
}
</script>

<template>
  <div class="message-row" :class="{ 'user-row': isUser, 'assistant-row': !isUser }">
    <div class="avatar" :class="isUser ? 'user-avatar' : 'ai-avatar'">
      {{ isUser ? 'U' : 'AI' }}
    </div>
    <div class="bubble" :class="isUser ? 'user-bubble' : 'assistant-bubble'">
      <div v-if="isUser" class="text">{{ content }}</div>
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
.markdown-body { word-break: break-word; }
.markdown-body :deep(p) { margin: 0 0 8px; }
.markdown-body :deep(pre) { background: #f5f7fa; padding: 12px; border-radius: 8px; overflow-x: auto; }
.markdown-body :deep(code) { font-size: 13px; }
.markdown-body :deep(table) { border-collapse: collapse; width: 100%; margin: 8px 0; }
.markdown-body :deep(th), .markdown-body :deep(td) { border: 1px solid #e4e7ed; padding: 6px 10px; text-align: left; }
.markdown-body :deep(th) { background: #f5f7fa; }
</style>
