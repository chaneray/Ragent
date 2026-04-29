<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { UploadFilled } from '@element-plus/icons-vue'
import { useKnowledgeBaseStore } from '@/stores/knowledgeBase'
import { uploadDocumentApi } from '@/api/document'

const kbStore = useKnowledgeBaseStore()
const selectedKbId = ref<number | null>(null)
const uploading = ref(false)
const uploadFile = ref<File | null>(null)

onMounted(() => kbStore.fetchList())

function handleFileChange(file: File) {
  uploadFile.value = file
  return false
}

async function handleUpload() {
  if (!selectedKbId.value) {
    ElMessage.warning('请先选择知识库')
    return
  }
  if (!uploadFile.value) {
    ElMessage.warning('请选择文件')
    return
  }
  uploading.value = true
  try {
    const res = await uploadDocumentApi(selectedKbId.value, uploadFile.value)
    ElMessage.success('上传成功，文档已进入入库流程')
    uploadFile.value = null
  } catch (err: unknown) {
    const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || '上传失败'
    ElMessage.error(msg)
  } finally {
    uploading.value = false
  }
}
</script>

<template>
  <el-card>
    <h2>文档上传</h2>
    <el-form label-width="120px">
      <el-form-item label="目标知识库">
        <el-select v-model="selectedKbId" placeholder="选择知识库" style="width: 100%">
          <el-option
            v-for="kb in kbStore.list"
            :key="kb.id"
            :label="kb.name"
            :value="kb.id"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="选择文件">
        <el-upload
          drag
          :auto-upload="false"
          :show-file-list="true"
          :on-change="(u: any) => handleFileChange(u.raw)"
          accept=".pdf,.docx,.txt,.md"
          :limit="1"
        >
          <el-icon class="el-icon--upload" :size="48"><UploadFilled /></el-icon>
          <div class="el-upload__text">拖拽文件到此处，或<em>点击选择</em></div>
          <template #tip>
            <div class="el-upload__tip">支持 PDF / DOCX / TXT / MD 格式</div>
          </template>
        </el-upload>
      </el-form-item>
      <el-form-item>
        <el-button type="primary" :loading="uploading" :disabled="!selectedKbId || !uploadFile" @click="handleUpload">
          开始上传
        </el-button>
      </el-form-item>
    </el-form>
  </el-card>
</template>
