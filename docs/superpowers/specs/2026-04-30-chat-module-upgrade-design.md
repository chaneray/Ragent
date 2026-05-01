# 对话模块升级设计

日期：2026-04-30
状态：已批准
范围：意图识别 + 系统提示词优化 + Agent 规划 + 记忆模块

---

## 背景

当前对话流程是简单的 RAG 链路：问题 → 查询改写 → 检索 → 生成。存在以下不足：
1. 所有问题都走检索流程，闲聊/翻译等无需检索的问题浪费资源
2. 系统提示词固定，不能根据场景调整回答策略
3. 复杂问题无法拆解为多步骤处理
4. 缺少长期记忆，每次对话都是独立的

---

## 优化后总览

```
用户问题
  │
  ▼
意图识别（LLM 分类）
  │
  ├─ knowledge_qa  → RAG 检索 + 生成
  ├─ chitchat       → 直接 LLM 回答
  ├─ summarize      → 检索 + 摘要 prompt
  ├─ compare        → 检索 + 对比 prompt
  └─ complex_task   → Agent 规划（子任务拆解）
  │
  ▼
记忆注入
  ├─ Level 3: 用户画像（长期）
  ├─ Level 2: 主题归纳（中期）
  └─ Level 1: 对话原文（短期，滑动窗口）
  │
  ▼
意图感知的动态 Prompt → LLM 生成 → SSE 输出
```

---

## 模块一：意图识别

### 设计

在 RAG 检索前，用 LLM 对用户问题做意图分类，路由到不同处理链路。

### 意图标签

| 标签 | 说明 | 是否需要知识库 |
|------|------|--------------|
| knowledge_qa | 需要从知识库检索信息来回答的问题 | 是 |
| chitchat | 闲聊、问候、翻译、计算等 | 否 |
| summarize | 要求总结、归纳某主题 | 是 |
| compare | 要求对比两个或多个事物 | 是 |
| complex_task | 需要多步骤推理或拆解的复杂问题 | 由 Agent 决定 |

### Prompt

```python
INTENT_PROMPT = """分析用户问题的意图，返回以下标签之一：
- knowledge_qa: 需要从知识库检索信息来回答的问题
- chitchat: 闲聊、问候、翻译、计算等不需要知识库的问题
- summarize: 要求总结、归纳某主题
- compare: 要求对比两个或多个事物
- complex_task: 需要多步骤推理或拆解的复杂问题

只返回 JSON: {"intent": "标签名"}

用户问题：{question}"""
```

### 容错

分类失败时默认走 `knowledge_qa`（现有链路）。

### 改动文件

- `backend/app/services/rag_service.py` — 新增 `_classify_intent()` 方法，在 `chat_stream` 入口处调用

---

## 模块二：系统提示词优化

### 设计

将固定的 `RAG_PROMPT_TEMPLATE` 替换为意图感知的动态 Prompt 系统。

### 统一 Prompt 结构

```
{system_role}          # 角色定义（根据意图变化）
{memory_context}       # 长期记忆注入（用户画像 + 主题归纳）
{short_term_context}   # 短期记忆（动态滑动窗口的历史对话）
{task_specific}        # 任务特定指令（引用要求/格式要求等）
{context}              # 检索到的知识库内容（如果需要）
{question}             # 用户问题
```

### Prompt 策略矩阵

| 意图 | system_role | task_specific |
|------|-------------|---------------|
| knowledge_qa | 知识库问答助手 | 强调引用来源、不要编造 |
| chitchat | 友好助手 | 自然对话、简洁友好 |
| summarize | 分析助手 | 结构化输出、分点总结 |
| compare | 分析助手 | 表格对比、列出异同、给出结论 |
| complex_task | 推理助手 | 分步骤推理、中间结论标注 |

### 改动文件

- `backend/app/services/prompts.py` — 新增文件，集中管理所有 prompt 模板
- `backend/app/services/rag_service.py` — 替换硬编码的 `RAG_PROMPT_TEMPLATE`

---

## 模块三：Agent 规划模块

### 设计

当意图识别为 `complex_task` 时，进入 Agent 规划模式。

### 流程

```
复杂问题
  │
  ▼
LLM 拆解为子任务列表
  │
  ▼
按顺序执行每个子任务
  ├─ 子任务1：调用工具 → 得到中间结论
  ├─ 子任务2：基于中间结论继续
  └─ ...
  │
  ▼
汇总所有子任务结果 → 生成最终回答
```

### 工具集

| 工具 | 说明 |
|------|------|
| `search_knowledge` | 检索知识库（复用混合检索） |
| `read_document` | 读取指定文档完整内容 |
| `get_chunk_detail` | 查看某个 chunk 详细内容 |

### LLM 输出格式

```json
{"action": "search_knowledge", "input": "产品A性能参数"}
```

执行后将结果反馈给 LLM，循环直到输出最终答案。

### 安全限制

- 最大循环 5 次（防止无限循环）
- 每次检索 top_k=3（控制 token 消耗）
- 超时 30 秒强制结束

### 改动文件

- `backend/app/services/agent_service.py` — 新增 Agent 服务
- `backend/app/services/rag_service.py` — complex_task 意图路由到 Agent

---

## 模块四：层级摘要记忆

### 三层金字塔结构

```
┌─────────────────────────────────────┐
│  Level 3: 用户画像（高度概括）        │  ← 长期，极少更新
│  "Java 开发者，偏好简洁回答"          │
├─────────────────────────────────────┤
│  Level 2: 主题归纳（压缩摘要）        │  ← 中期，定期合并
│  "近一周讨论了 RAG 优化、SSE 解析"    │
├─────────────────────────────────────┤
│  Level 1: 对话原文（滑动窗口）        │  ← 短期，直接保留原始消息
│  最近 N 轮对话的完整内容              │
└─────────────────────────────────────┘
```

### 数据流

```
对话进行中
  │
  ▼
Level 1 = message 表中的原始记录
  │       滑动窗口：按 token 预算动态取最近 N 轮
  │
  ▼
对话结束时
  │
  ├─ LLM 生成本次会话的摘要（200-300字）→ 写入 Level 2
  │
  ▼
Level 2 数量 ≥ 5 时
  │
  └─ 合并 5 条 Level 2 → 1 条 Level 3（更新用户画像）
```

### 短期记忆（Level 1）

复用现有的 `_get_session_history()`，改为基于 token 预算的动态窗口：

```python
token_budget = 2000  # 短期记忆的 token 上限

# 从最近消息开始逐条加入，直到累计 token 超过 budget
```

token 估算：1 中文字 ≈ 2 token

### 中期记忆（Level 2）

- **写入时机**：当会话消息数 ≥ 10 且该会话尚未生成过摘要时，在对话结束后异步生成
- **触发方式**：每次 LLM 回答完成后检查，避免每轮都生成摘要
- **内容**：本次会话的关键讨论点、结论、决策
- **长度**：200-300 字
- **存储**：`user_memory` 表，`level=2`

### 长期记忆（Level 3）

- **写入时机**：Level 2 数量 ≥ 5 时自动合并
- **内容**：用户画像——角色、偏好、技术栈、常见话题
- **更新方式**：合并后替换旧的 Level 3 记录
- **存储**：`user_memory` 表，`level=3`

### 读取与注入

每次对话时读取记忆，按 token 预算分配：

```
总记忆预算 = 1000 tokens

Level 3（用户画像）→ 全量注入（约 100 tokens）
Level 2（主题归纳）→ 最近 3 条（约 300 tokens）
Level 1（对话原文）→ 滑动窗口动态取（约 600 tokens）
```

### Session 模型扩展

在现有 `session` 表新增字段：

```sql
ALTER TABLE session ADD COLUMN summary_generated BOOLEAN DEFAULT FALSE;
```

用于标记该会话是否已生成过 Level 2 摘要，避免重复生成。

### 数据库表：`user_memory`

```sql
CREATE TABLE user_memory (
    id INT PRIMARY KEY AUTO_INCREMENT,
    user_id INT NOT NULL,
    level TINYINT NOT NULL,           -- 2 或 3
    content TEXT NOT NULL,
    source_sessions JSON,             -- 来源会话 ID 列表
    token_count INT DEFAULT 0,
    created_at DATETIME DEFAULT NOW(),
    updated_at DATETIME DEFAULT NOW(),
    FOREIGN KEY (user_id) REFERENCES user(id)
);
```

### 改动文件

- `backend/app/models/memory.py` — 新增 UserMemory ORM 模型
- `backend/app/services/memory_service.py` — 新增记忆服务（读取/写入/合并）
- `backend/app/services/rag_service.py` — 集成记忆读取和写入
- `backend/alembic/versions/` — 新增 user_memory 表迁移

---

## 完整对话流程（优化后）

```
用户发送问题
  │
  ▼
1. 读取记忆
   ├─ Level 3: 用户画像
   ├─ Level 2: 最近 3 条主题归纳
   └─ Level 1: 滑动窗口（token_budget=2000）
  │
  ▼
2. 意图识别（LLM 分类）
  │
  ├─ chitchat ──────────────────────────────────┐
  │                                              ▼
  ├─ knowledge_qa ──→ 查询改写 → 混合检索 →    生成回答
  │                   Reranker                  │
  ├─ summarize ────→ 检索 → 摘要 prompt ────────┤
  │                                              │
  ├─ compare ──────→ 检索 → 对比 prompt ────────┤
  │                                              │
  └─ complex_task ─→ Agent 规划 → 多步执行 ─────┤
                                                 │
                                                 ▼
                                          SSE 流式输出
                                                 │
                                                 ▼
                                     3. 保存消息 + 生成摘要
                                        ├─ 写入 message 表
                                        └─ 生成 Level 2 摘要
                                           └─ Level 2 ≥ 5 → 合并 Level 3
```

---

## 改动文件清单

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `backend/app/services/prompts.py` | 新增 | 集中管理所有 prompt 模板 |
| `backend/app/services/agent_service.py` | 新增 | Agent 规划与执行 |
| `backend/app/services/memory_service.py` | 新增 | 记忆读取/写入/合并 |
| `backend/app/models/memory.py` | 新增 | UserMemory ORM 模型 |
| `backend/app/models/session.py` | 修改 | 新增 summary_generated 字段 |
| `backend/app/services/rag_service.py` | 重写 | 集成意图识别 + 记忆 + 动态 prompt |
| `backend/app/api/v1/chat.py` | 修改 | 对话结束时触发记忆写入 |
| `backend/alembic/versions/` | 新增 | user_memory 表 + session 字段迁移 |

---

## 依赖变化

无新增外部依赖。所有功能基于已有 LLM 调用实现。
