<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useKnowledgeBaseStore } from '@/stores/knowledgeBase'
import { getDocumentsApi, deleteDocumentApi } from '@/api/document'
import type { Document } from '@/types'

const route = useRoute()
const router = useRouter()
const kbStore = useKnowledgeBaseStore()
const kbId = Number(route.params.id)
const loading = ref(true)
const documents = ref<Document[]>([])

const statusMap: Record<string, string> = {
  uploaded: '已上传',
  parsing: '解析中',
  chunking: '分块中',
  embedding: '向量化中',
  indexed: '已索引',
  failed: '失败',
}

async function loadData() {
  try {
    await kbStore.fetchDetail(kbId)
    const res = await getDocumentsApi(kbId)
    documents.value = res.data.items || []
  } catch {
    ElMessage.error('知识库不存在')
    router.push('/knowledge-bases')
  } finally {
    loading.value = false
  }
}

async function handleDelete(docId: number, name: string) {
  try {
    await ElMessageBox.confirm(`确认删除文档「${name}」？`, '警告', {
      confirmButtonText: '确认',
      cancelButtonText: '取消',
      type: 'warning',
    })
    await deleteDocumentApi(docId)
    ElMessage.success('已删除')
    documents.value = documents.value.filter(d => d.id !== docId)
  } catch { /* 取消 */ }
}

onMounted(loadData)
</script>

<template>
  <div v-if="loading">
    <el-skeleton :rows="3" animated />
  </div>
  <div v-else-if="kbStore.current">
    <el-page-header :content="kbStore.current.name" @back="router.push('/knowledge-bases')" />
    <el-card class="detail-card">
      <p class="desc">{{ kbStore.current.description || '暂无描述' }}</p>
      <div class="stats">
        文档 {{ kbStore.current.document_count }} · 片段 {{ kbStore.current.chunk_count }}
      </div>
    </el-card>
    <h3>文档列表</h3>
    <el-table :data="documents" v-if="documents.length" style="width: 100%">
      <el-table-column prop="original_filename" label="文件名" min-width="200" />
      <el-table-column prop="file_type" label="类型" width="80" />
      <el-table-column prop="file_size" label="大小" width="100">
        <template #default="{ row }">
          {{ (row.file_size / 1024).toFixed(1) }} KB
        </template>
      </el-table-column>
      <el-table-column prop="status" label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="row.status === 'indexed' ? 'success' : row.status === 'failed' ? 'danger' : 'warning'" size="small">
            {{ statusMap[row.status] || row.status }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="chunk_count" label="分块数" width="80" />
      <el-table-column label="操作" width="80">
        <template #default="{ row }">
          <el-button text type="danger" size="small" @click="handleDelete(row.id, row.original_filename)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>
    <el-empty v-else description="暂无文档，请上传" />
  </div>
</template>

<style scoped>
.detail-card { margin-top: 16px; margin-bottom: 24px; }
.desc { color: #606266; margin: 0 0 8px; }
.stats { font-size: 12px; color: #c0c4cc; }
</style>
