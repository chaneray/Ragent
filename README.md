# Ragent — RAG 智能对话平台

基于 **FastAPI + LangChain + Vue3** 构建的 RAG 智能对话平台。支持文档上传、知识库管理和基于知识库的检索增强生成对话。

## 技术栈

| 层面 | 技术 |
|------|------|
| LLM | 可配置切换：阿里云百炼 / OpenAI / DeepSeek |
| 向量数据库 | Milvus (Docker) |
| 关系数据库 | MySQL 8.0 + SQLAlchemy |
| 后端框架 | FastAPI + LangChain + sse-starlette |
| 前端框架 | Vue3 + Vite + TypeScript + Element Plus + Pinia |
| 认证 | JWT (用户名/邮箱登录) |
| 部署 | Docker Compose (MySQL + Milvus + etcd + MinIO + Redis) |

## 快速启动

### 环境要求

- Python 3.11+
- Node.js 18+
- Docker & Docker Compose

### 1. 启动基础设施

```bash
docker compose up -d
```

启动 MySQL、Milvus、etcd、MinIO、Redis 5 个服务。

### 2. 配置后端

```bash
cd backend
cp ../.env.example .env
# 编辑 .env，填入你的 LLM API Key（百炼/OpenAI/DeepSeek）
```

关键配置项：

```env
# LLM 提供商: dashscope / openai / deepseek
LLM_PROVIDER=dashscope
LLM_MODEL=qwen-plus
OPENAI_API_KEY=sk-your-api-key

# Embedding 提供商
EMBEDDING_PROVIDER=dashscope
EMBEDDING_MODEL=text-embedding-v4
```

安装依赖：

```bash
pip install -e . -i https://mirrors.aliyun.com/pypi/simple/
```

数据库迁移：

```bash
alembic upgrade head
```

启动后端：

```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
```

访问 Swagger 文档：`http://localhost:8001/docs`

### 3. 启动前端

```bash
cd frontend
npm install
npm run dev
```

访问前端页面：`http://localhost:5173`

## 使用流程

1. **注册/登录** — 输入用户名、邮箱和密码注册，支持用户名或邮箱登录
2. **创建知识库** — 在"知识库"页面创建知识库
3. **上传文档** — 在"上传文档"页面选择知识库并上传文件（支持 PDF/DOCX/TXT/MD）
4. **开始对话** — 在"对话"页面选择知识库，输入问题进行 RAG 对话

## 项目结构

```
Ragent/
├── docker-compose.yml          # 基础设施编排
├── .env.example                # 环境变量模板
├── backend/
│   ├── app/
│   │   ├── main.py             # FastAPI 入口
│   │   ├── core/               # 配置、安全、依赖注入
│   │   ├── api/v1/             # REST API（认证、知识库、文档、对话、会话）
│   │   ├── models/             # SQLAlchemy ORM 模型
│   │   ├── schemas/            # Pydantic 数据模型
│   │   └── services/           # 业务逻辑（LLM、RAG、向量存储、文档处理）
│   ├── tests/                  # 测试
│   └── alembic/                # 数据库迁移
├── frontend/
│   └── src/
│       ├── views/              # 页面（登录、注册、对话、知识库、上传）
│       ├── components/         # 组件（消息气泡、输入框、布局）
│       ├── stores/             # Pinia 状态管理
│       ├── api/                # Axios API 封装
│       └── types/              # TypeScript 类型定义
```

## API 概要

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/auth/register` | 用户注册 |
| POST | `/api/v1/auth/login` | 用户登录 |
| GET | `/api/v1/auth/me` | 当前用户信息 |
| GET | `/api/v1/knowledge-bases` | 知识库列表 |
| POST | `/api/v1/knowledge-bases` | 创建知识库 |
| GET | `/api/v1/knowledge-bases/{id}` | 知识库详情 |
| DELETE | `/api/v1/knowledge-bases/{id}` | 删除知识库 |
| POST | `/api/v1/documents/upload` | 上传文档 |
| GET | `/api/v1/documents` | 文档列表 |
| DELETE | `/api/v1/documents/{id}` | 删除文档 |
| POST | `/api/v1/chat/stream` | SSE 流式对话 |
| POST | `/api/v1/sessions` | 创建会话 |
| GET | `/api/v1/sessions` | 会话列表 |
| GET | `/api/v1/sessions/{id}` | 会话消息 |
| DELETE | `/api/v1/sessions/{id}` | 删除会话 |

## 运行测试

```bash
cd backend
pip install "pytest>=8.0" "pytest-asyncio>=0.23" "httpx>=0.27" -i https://mirrors.aliyun.com/pypi/simple/
python -m pytest tests/ -v
```

## RAG 链路

```
用户问题 → 向量化 → Milvus 检索 (top_k=5) → 拼接上下文 → LLM 流式生成 → SSE 输出
                                                    ↑
                                              会话历史 (最近10轮)
```
