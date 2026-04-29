<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import { useKnowledgeBaseStore } from '@/stores/knowledgeBase'

const router = useRouter()
const store = useKnowledgeBaseStore()
const dialogVisible = ref(false)
const form = ref({ name: '', description: '' })

onMounted(() => store.fetchList())

async function handleCreate() {
  if (!form.value.name) {
    ElMessage.warning('请输入知识库名称')
    return
  }
  try {
    await store.create(form.value.name, form.value.description)
    ElMessage.success('创建成功')
    dialogVisible.value = false
    form.value = { name: '', description: '' }
  } catch (err: unknown) {
    const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || '创建失败'
    ElMessage.error(msg)
  }
}

async function handleDelete(kb: { id: number; name: string }) {
  try {
    await ElMessageBox.confirm(`确认删除知识库「${kb.name}」？此操作不可恢复。`, '警告', {
      confirmButtonText: '确认删除',
      cancelButtonText: '取消',
      type: 'warning',
    })
    await store.remove(kb.id)
    ElMessage.success('已删除')
  } catch {
    // 取消删除不做任何操作
  }
}
</script>

<template>
  <div>
    <div class="page-header">
      <h2>知识库</h2>
      <el-button type="primary" :icon="Plus" @click="dialogVisible = true">创建知识库</el-button>
    </div>

    <el-row :gutter="20">
      <el-col v-for="kb in store.list" :key="kb.id" :xs="24" :sm="12" :md="8" :lg="6" class="kb-col">
        <el-card shadow="hover" class="kb-card" @click="router.push('/knowledge-bases/' + kb.id)">
          <h3 class="kb-name">{{ kb.name }}</h3>
          <p class="kb-desc">{{ kb.description || '暂无描述' }}</p>
          <div class="kb-stats">
            <span>文档 {{ kb.document_count }}</span>
            <span>片段 {{ kb.chunk_count }}</span>
          </div>
          <el-button
            type="danger"
            size="small"
            class="delete-btn"
            @click.stop="handleDelete(kb)"
          >删除</el-button>
        </el-card>
      </el-col>
      <el-col v-if="store.list.length === 0 && !store.loading" :span="24">
        <el-empty description="还没有知识库，点击上方按钮创建" />
      </el-col>
    </el-row>

    <el-dialog v-model="dialogVisible" title="创建知识库" width="480px">
      <el-form>
        <el-form-item label="名称">
          <el-input v-model="form.name" placeholder="知识库名称" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" :rows="3" placeholder="可选描述" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleCreate">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.kb-col {
  margin-bottom: 20px;
}

.kb-card {
  cursor: pointer;
  position: relative;
}

.kb-card:hover {
  border-color: #409eff;
}

.kb-name {
  margin: 0 0 8px;
  font-size: 16px;
  color: #303133;
}

.kb-desc {
  margin: 0 0 12px;
  font-size: 13px;
  color: #909399;
  min-height: 20px;
}

.kb-stats {
  display: flex;
  gap: 16px;
  font-size: 12px;
  color: #c0c4cc;
}

.delete-btn {
  position: absolute;
  top: 12px;
  right: 12px;
  visibility: hidden;
}

.kb-card:hover .delete-btn {
  visibility: visible;
}
</style>
