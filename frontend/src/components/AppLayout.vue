<script setup lang="ts">
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { computed } from 'vue'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()

const activeMenu = computed(() => {
  const path = route.path
  if (path.startsWith('/chat')) return '/chat'
  if (path.startsWith('/knowledge-bases')) return '/knowledge-bases'
  if (path.startsWith('/upload')) return '/upload'
  return '/chat'
})

function handleMenuSelect(index: string) {
  router.push(index)
}

function handleLogout() {
  authStore.logout()
  router.push('/login')
}
</script>

<template>
  <el-container class="app-container" v-if="authStore.isLoggedIn">
    <el-header class="app-header">
      <div class="header-left">
        <h1 class="app-title">Ragent</h1>
        <el-menu
          :default-active="activeMenu"
          mode="horizontal"
          @select="handleMenuSelect"
          class="header-menu"
        >
          <el-menu-item index="/chat">对话</el-menu-item>
          <el-menu-item index="/knowledge-bases">知识库</el-menu-item>
          <el-menu-item index="/upload">上传文档</el-menu-item>
        </el-menu>
      </div>
      <div class="header-right">
        <span class="username">{{ authStore.user?.username }}</span>
        <el-button type="danger" text @click="handleLogout">退出</el-button>
      </div>
    </el-header>
    <el-main class="app-main">
      <router-view />
    </el-main>
  </el-container>
  <div v-else class="guest-layout">
    <router-view />
  </div>
</template>

<style scoped>
.app-container {
  min-height: 100vh;
  background: #f5f7fa;
}

.app-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: #fff;
  border-bottom: 1px solid #e4e7ed;
  padding: 0 24px;
  height: 60px;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 32px;
}

.app-title {
  font-size: 20px;
  font-weight: 700;
  color: #409eff;
  margin: 0;
  white-space: nowrap;
}

.header-menu {
  border-bottom: none !important;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.username {
  color: #606266;
  font-size: 14px;
}

.app-main {
  padding: 24px;
  max-width: 1400px;
  margin: 0 auto;
  width: 100%;
}

.guest-layout {
  min-height: 100vh;
  display: flex;
  justify-content: center;
  align-items: center;
  background: #f0f2f5;
}
</style>
