<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { ElMessage } from 'element-plus'

const router = useRouter()
const authStore = useAuthStore()

const form = ref({ username: '', email: '', password: '', confirmPassword: '' })
const loading = ref(false)

async function handleRegister() {
  if (!form.value.username || !form.value.email || !form.value.password) {
    ElMessage.warning('请填写所有字段')
    return
  }
  if (form.value.password !== form.value.confirmPassword) {
    ElMessage.warning('两次输入的密码不一致')
    return
  }
  loading.value = true
  try {
    await authStore.register(form.value.username, form.value.email, form.value.password)
    ElMessage.success('注册成功，请登录')
    router.push('/login')
  } catch (err: unknown) {
    const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || '注册失败'
    ElMessage.error(msg)
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <el-card class="auth-card">
    <h2 class="auth-title">注册 Ragent</h2>
    <el-form @submit.prevent="handleRegister">
      <el-form-item>
        <el-input v-model="form.username" placeholder="用户名" size="large" />
      </el-form-item>
      <el-form-item>
        <el-input v-model="form.email" placeholder="邮箱" size="large" />
      </el-form-item>
      <el-form-item>
        <el-input v-model="form.password" type="password" placeholder="密码" size="large" show-password />
      </el-form-item>
      <el-form-item>
        <el-input v-model="form.confirmPassword" type="password" placeholder="确认密码" size="large" show-password />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" size="large" :loading="loading" class="auth-btn" @click="handleRegister">
          注 册
        </el-button>
      </el-form-item>
    </el-form>
    <div class="auth-link">
      已有账号？<router-link to="/login">立即登录</router-link>
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
