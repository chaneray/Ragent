<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { ElMessage } from 'element-plus'

const router = useRouter()
const authStore = useAuthStore()

const form = ref({ account: '', password: '' })
const loading = ref(false)

async function handleLogin() {
  if (!form.value.account || !form.value.password) {
    ElMessage.warning('请输入用户名/邮箱和密码')
    return
  }
  loading.value = true
  try {
    await authStore.login(form.value.account, form.value.password)
    ElMessage.success('登录成功')
    router.push('/chat')
  } catch (err: unknown) {
    const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || '登录失败'
    ElMessage.error(msg)
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <el-card class="auth-card">
    <h2 class="auth-title">登录 Ragent</h2>
    <el-form @submit.prevent="handleLogin">
      <el-form-item>
        <el-input v-model="form.account" placeholder="用户名或邮箱" size="large" />
      </el-form-item>
      <el-form-item>
        <el-input v-model="form.password" type="password" placeholder="密码" size="large" show-password />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" size="large" :loading="loading" class="auth-btn" @click="handleLogin">
          登 录
        </el-button>
      </el-form-item>
    </el-form>
    <div class="auth-link">
      还没有账号？<router-link to="/register">立即注册</router-link>
    </div>
  </el-card>
</template>

<style scoped>
.auth-card {
  width: 400px;
}

.auth-title {
  text-align: center;
  color: #303133;
  margin-bottom: 24px;
}

.auth-btn {
  width: 100%;
}

.auth-link {
  text-align: center;
  font-size: 14px;
  color: #909399;
}
</style>
