<script setup lang="ts">
import { ref } from 'vue'

const props = defineProps<{
  disabled: boolean
  kbOptions: { id: number; name: string }[]
}>()

const emit = defineEmits<{
  send: [question: string, kbIds: string[]]
}>()

const question = ref('')
const selectedKbIds = ref<string[]>([])
const showKbWarning = ref(false)

function handleSend() {
  if (!question.value.trim()) return
  if (props.disabled) return
  if (selectedKbIds.value.length === 0) {
    showKbWarning.value = true
    setTimeout(() => { showKbWarning.value = false }, 3000)
    return
  }
  showKbWarning.value = false
  emit('send', question.value, selectedKbIds.value)
  question.value = ''
}
</script>

<template>
  <div class="chat-input-wrapper">
    <div class="kb-select-bar" v-if="kbOptions.length === 0">
      <el-alert
        title="暂无可用的知识库，请先上传文档并创建知识库"
        type="warning"
        :closable="false"
        show-icon
        style="margin-bottom: 8px;"
      />
    </div>
    <div class="kb-select-bar" v-else>
      <span class="kb-label">知识库：</span>
      <el-tag
        v-for="kb in kbOptions"
        :key="kb.id"
        :type="selectedKbIds.includes(String(kb.id)) ? 'primary' : 'info'"
        size="small"
        style="cursor: pointer; margin-right: 6px;"
        @click="() => {
          const idx = selectedKbIds.indexOf(String(kb.id))
          if (idx >= 0) selectedKbIds.splice(idx, 1)
          else selectedKbIds.push(String(kb.id))
        }"
      >
        {{ kb.name }}
      </el-tag>
    </div>
    <div v-if="showKbWarning" class="kb-warning">
      <el-alert
        title="请先选择至少一个知识库"
        type="error"
        :closable="false"
        show-icon
      />
    </div>
    <div class="input-area">
      <el-input
        v-model="question"
        type="textarea"
        :rows="2"
        placeholder="输入问题，Enter 发送，Shift+Enter 换行"
        :disabled="disabled"
        @keydown.enter.exact="handleSend"
      />
      <el-button type="primary" :disabled="disabled || !question.trim()" @click="handleSend" class="send-btn">
        {{ disabled ? '思考中...' : '发送' }}
      </el-button>
    </div>
  </div>
</template>

<style scoped>
.chat-input-wrapper {
  border-top: 1px solid #e4e7ed;
  padding: 16px 24px;
  background: #fff;
}
.kb-label {
  font-size: 13px;
  color: #606266;
  line-height: 24px;
  margin-right: 4px;
}
.kb-select-bar {
  margin-bottom: 12px;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px;
}
.kb-warning {
  margin-bottom: 12px;
}
.input-area {
  display: flex;
  gap: 12px;
  align-items: flex-start;
}
.send-btn {
  height: 56px;
  width: 90px;
  flex-shrink: 0;
}
</style>
