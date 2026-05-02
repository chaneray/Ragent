# CLAUDE.md - Ragent 项目规范

## 项目简介

Ragent 是一个基于 FastAPI + LangChain + Vue3 的 RAG 智能对话平台，支持文档上传、知识库管理和基于知识库的检索增强生成对话。

## 技术栈

- 后端：Python 3.11+, FastAPI, LangChain, SQLAlchemy (MySQL), Milvus, Redis
- 前端：Vue3, Vite, TypeScript, Element Plus, Pinia
- 部署：Docker Compose

## 项目结构规范

- `backend/` — Python 后端代码，使用 FastAPI 异步框架
- `frontend/` — Vue3 前端代码，使用 Vite 构建
- `docker-compose.yml` — 基础设施服务编排
- 每个模块保持单一职责，避免循环依赖

## 后端规范

### API 设计
- RESTful 风格，URL 前缀 `/api/v1/`
- 请求/响应使用 Pydantic Schema 定义在 `schemas/`
- 业务逻辑放在 `services/`，路由处理放在 `api/v1/`
- 数据库模型放在 `models/`，使用 SQLAlchemy ORM
- 依赖注入统一在 `core/deps.py`

### Python 代码规范
- 使用 async/await 异步模式
- 类型注解：所有函数参数和返回值必须有类型注解
- 使用 Pydantic Settings 管理配置
- 环境变量通过 `.env` 文件注入，不硬编码敏感信息
- 异常统一使用 FastAPI HTTPException，错误信息用中文

### 日志规范
- 使用 Python 标准库 `logging`，通过 `logger = logging.getLogger(__name__)` 获取 logger
- 日志配置统一在 `app/core/logging.py`，通过 `setup_logging()` 初始化
- **编写代码时必须在关键位置添加日志**，包括但不限于：
  - 函数入口：记录关键参数（INFO 级别）
  - 外部调用前后：记录请求参数和返回结果摘要（INFO 级别，详细内容用 DEBUG）
  - 条件分支：记录走了哪个分支、为什么（INFO 级别）
  - 异常处理：记录异常信息和降级策略（WARNING/ERROR 级别）
  - 性能关键点：记录耗时（INFO 级别）
- 日志级别策略：DEBUG 用于完整内容，INFO 用于关键节点摘要，WARNING 用于可恢复错误，ERROR 用于严重错误
- 敏感信息（密码、token）不得写入日志

### 数据库
- 使用 Alembic 管理数据库迁移
- 模型继承 SQLAlchemy `Base`，使用 `Mapped` 类型注解
- 表名使用蛇形命名，字段名使用蛇形命名

## 前端规范

### Vue3 组件规范
- 优先使用 `<script setup lang="ts">` 语法
- 使用 Composition API
- 状态管理使用 Pinia
- 路由使用 Vue Router 4
- UI 组件库使用 Element Plus

### TypeScript 规范
- 避免使用 `any` 类型，使用 `unknown` 或具体类型
- 接口定义放在 `types/` 目录
- API 响应类型与后端 Pydantic Schema 对应

### 样式
- 使用 CSS Modules 或 Scoped Styles
- 响应式布局优先

## Git 规范
- 每个 PR 只解决一个问题
- 代码必须有单元测试
- Commit message 使用中文

---

## 开发原则
- 单一职责原则
- 每个PR只解决一个问题
- 代码必须有单元测试
- 注释用中文，代码用英文

## 个人偏好
- 优先使用函数式组件
- 状态管理使用Pinia（Vue3 官方推荐）
- 样式使用CSS Modules
- 避免使用any类型

# 代码风格
- 使用ES模块 (import/export) 语法，而不是CommonJS (require)
- 尽可能使用解构导入 (例如 import { foo } from 'bar')

# 工作流程
- 在完成一系列代码更改后务必进行类型检查
- 为了性能考虑，优先运行单个测试，而不是整个测试套件

# 质量守则（强制）
- **每次宣称任务成功，必须附带证据文件链接**（如类型检查输出、运行截图、测试结果），不得只凭代码写入就宣称成功
- **完成每阶段后自我反问**："真的完成了？有证据吗？"若发现遗漏或未验证，立即修正并补充证据
