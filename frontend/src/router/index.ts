import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'Login',
      component: () => import('@/views/Login.vue'),
      meta: { guest: true },
    },
    {
      path: '/register',
      name: 'Register',
      component: () => import('@/views/Register.vue'),
      meta: { guest: true },
    },
    {
      path: '/',
      redirect: '/chat',
    },
    {
      path: '/chat',
      name: 'Chat',
      component: () => import('@/views/Chat.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/chat/:sessionId',
      name: 'ChatSession',
      component: () => import('@/views/Chat.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/knowledge-bases',
      name: 'KnowledgeBaseList',
      component: () => import('@/views/KnowledgeBase/List.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/knowledge-bases/:id',
      name: 'KnowledgeBaseDetail',
      component: () => import('@/views/KnowledgeBase/Detail.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/upload',
      name: 'Upload',
      component: () => import('@/views/Upload.vue'),
      meta: { requiresAuth: true },
    },
  ],
})

router.beforeEach((to, _from, next) => {
  const authStore = useAuthStore()
  if (to.meta.requiresAuth && !authStore.token) {
    next('/login')
  } else if (to.meta.guest && authStore.token) {
    next('/chat')
  } else {
    next()
  }
})

export default router
