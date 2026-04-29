import { defineStore } from 'pinia'
import { ref } from 'vue'
import {
  getKnowledgeBasesApi,
  createKnowledgeBaseApi,
  getKnowledgeBaseApi,
  deleteKnowledgeBaseApi,
} from '@/api/knowledgeBase'
import type { KnowledgeBase } from '@/types'

export const useKnowledgeBaseStore = defineStore('knowledgeBase', () => {
  const list = ref<KnowledgeBase[]>([])
  const current = ref<KnowledgeBase | null>(null)
  const loading = ref(false)
  const total = ref(0)

  async function fetchList() {
    loading.value = true
    try {
      const res = await getKnowledgeBasesApi()
      list.value = res.data.items || []
      total.value = res.data.total || 0
    } finally {
      loading.value = false
    }
  }

  async function create(name: string, description: string) {
    const res = await createKnowledgeBaseApi(name, description)
    await fetchList()
    return res.data
  }

  async function fetchDetail(id: number) {
    const res = await getKnowledgeBaseApi(id)
    current.value = res.data
    return res.data
  }

  async function remove(id: number) {
    await deleteKnowledgeBaseApi(id)
    await fetchList()
  }

  return { list, current, loading, total, fetchList, create, fetchDetail, remove }
})
