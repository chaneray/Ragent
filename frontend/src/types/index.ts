// 用户
export interface User {
  id: number
  username: string
  email: string
  created_at: string
}

// 知识库
export interface KnowledgeBase {
  id: number
  name: string
  description: string | null
  document_count: number
  chunk_count: number
  created_at: string
}

// 文档
export interface Document {
  id: number
  filename: string
  original_filename: string
  file_type: string
  file_size: number
  status: 'uploaded' | 'parsing' | 'chunking' | 'embedding' | 'indexed' | 'failed'
  chunk_count: number
  error_message: string | null
  created_at: string
}

// 会话
export interface Session {
  id: number
  title: string
  knowledge_base_ids: string | null
  created_at: string
  updated_at: string
}

// 消息
export interface Message {
  id: number
  session_id: number
  role: 'user' | 'assistant'
  content: string
  citations: string | null
  created_at: string
  isError?: boolean
}

// API 统一返回
export interface ApiResponse<T> {
  code: number
  message: string
  data: T
}
