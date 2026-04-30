<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useKnowledgeBaseStore } from '@/stores/knowledgeBase'
import { getDocumentsApi, deleteDocumentApi, getDocumentChunksApi } from '@/api/document'
import type { Document } from '@/types'

interface ChunkItem {
  id: number
  chunk_index: number
  content: string
  metadata: Record<string, unknown>
}

const route = useRoute()
const router = useRouter()
const kbStore = useKnowledgeBaseStore()
const kbId = Number(route.params.id)
const loading = ref(true)
const documents = ref<Document[]>([])

// 分片弹窗
const chunksDialogVisible = ref(false)
const chunksLoading = ref(false)
const chunksData = ref<{ filename: string; chunk_count: number; chunks: ChunkItem[] } | null>(null)
const chunksDocName = ref('')

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

async function handleViewChunks(docId: number, filename: string) {
  chunksDialogVisible.value = true
  chunksLoading.value = true
  chunksDocName.value = filename
  chunksData.value = null
  try {
    const res = await getDocumentChunksApi(docId)
    chunksData.value = res.data
  } catch {
    ElMessage.error('获取分片信息失败')
  } finally {
    chunksLoading.value = false
  }
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
      <el-table-column label="操作" width="160">
        <template #default="{ row }">
          <el-button text type="primary" size="small" @click="handleViewChunks(row.id, row.original_filename)" :disabled="row.status !== 'indexed'">
            查看分片
          </el-button>
          <el-button text type="danger" size="small" @click="handleDelete(row.id, row.original_filename)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>
    <el-empty v-else description="暂无文档，请上传" />
  </div>

  <!-- 分片弹窗 -->
  <el-dialog v-model="chunksDialogVisible" :title="`文档分片 — ${chunksDocName}`" width="70%" top="5vh" destroy-on-close>
    <div v-if="chunksLoading" v-loading="chunksLoading" style="height: 200px;" />
    <div v-else-if="chunksData">
      <p class="chunk-summary">共 {{ chunksData.chunk_count }} 个分片</p>
      <el-scrollbar max-height="60vh">
        <div v-for="chunk in chunksData.chunks" :key="chunk.id" class="chunk-item">
          <div class="chunk-header">
            <el-tag size="small" type="info">#{{ chunk.chunk_index + 1 }}</el-tag>
            <span class="chunk-meta">{{ chunk.content.length }} 字</span>
            <span v-if="chunk.metadata.page" class="chunk-meta">第 {{ chunk.metadata.page }} 页</span>
          </div>
          <div class="chunk-content">{{ chunk.content }}</div>
        </div>
      </el-scrollbar>
    </div>
  </el-dialog>
</template>

<style scoped>
.detail-card { margin-top: 16px; margin-bottom: 24px; }
.desc { color: #606266; margin: 0 0 8px; }
.stats { font-size: 12px; color: #c0c4cc; }
.chunk-summary { margin: 0 0 12px; color: #909399; font-size: 14px; }
.chunk-item {
  border: 1px solid #ebeef5;
  border-radius: 6px;
  padding: 12px;
  margin-bottom: 12px;
  background: #fafafa;
}
.chunk-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}
.chunk-meta { font-size: 12px; color: #c0c4cc; }
.chunk-content {
  font-size: 13px;
  line-height: 1.6;
  color: #303133;
  white-space: pre-wrap;
  word-break: break-all;
}
</style>
