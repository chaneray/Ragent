# 记忆系统优化设计

## 背景

当前系统采用三层金字塔记忆结构（L1 短期滑动窗口 → L2 会话摘要 → L3 用户画像），整体设计合理，但存在以下问题：

1. Token 预算固定，不区分对话类型
2. L2 摘要是纯文本，信息密度低
3. 触发阈值不够合理（L2 过早触发，L3 过晚触发）
4. Session 删除时没有级联清理关联数据
5. `post_conversation_update` 同步阻塞 SSE 响应关闭

## 优化方案：轻量增强

在现有架构上做最小改动，零外部依赖，解决所有痛点。

---

## 1. 动态 Token 预算分配

### 当前问题

- L1 固定 2000 tokens、L2 固定 3 条 x 300 tokens、L3 固定 100 tokens
- `TOTAL_MEMORY_BUDGET = 1000` 定义了但未生效

### 设计

根据意图识别结果动态分配 token 预算：

```python
BUDGET_PROFILES = {
    "knowledge_qa":  {"l1": 2500, "l2_count": 2, "l2_tokens": 200, "l3": 100},
    "summarize":     {"l1": 2000, "l2_count": 3, "l2_tokens": 300, "l3": 100},
    "compare":       {"l1": 2500, "l2_count": 3, "l2_tokens": 300, "l3": 100},
    "chitchat":      {"l1": 1000, "l2_count": 3, "l2_tokens": 300, "l3": 300},
    "complex_task":  {"l1": 2000, "l2_count": 2, "l2_tokens": 200, "l3": 100},
    "default":       {"l1": 2000, "l2_count": 3, "l2_tokens": 300, "l3": 100},
}
```

**设计要点：**
- 知识问答：给 L1 更多预算（需要更多近期上下文理解检索结果）
- 闲聊：给 L3 更多预算（需要更多用户画像来个性化回复）
- 预算通过 `build_memory_context(intent, ...)` 传入，不再硬编码
- `TOTAL_MEMORY_BUDGET` 改为动态计算：`l1 + l2_count * l2_tokens + l3`

---

## 2. 结构化摘要格式

### 当前问题

- L2 摘要是纯文本 200-300 字，信息密度低
- LLM 难以快速提取关键信息

### 设计

L2 存储纯摘要，采用精简的 JSON 结构化格式：

```json
{
  "topic": "对话主题（一句话）",
  "key_points": ["关键结论1", "关键结论2"],
  "pending": ["未解决的问题"]
}
```

**字段说明：**
- `topic`：不超过 30 字
- `key_points`：最多 3 条，每条不超过 50 字
- `pending`：最多 2 条，如果没有未解决的问题，输出空数组 `[]`

**Prompt 拼接效果：**
```
[近期讨论主题]
- Python 异步编程：推荐使用 asyncio.create_task 替代同步阻塞
- RAG 优化：混合检索（向量+BM25）效果优于纯向量检索
```

**容错处理：** LLM 输出不符合 JSON 格式时，降级为纯文本存储。

---

## 3. 触发阈值优化

### 当前问题

- L2 阈值 10 条消息：对话刚开始就触发摘要，质量不高
- L3 阈值 5 条 L2：初期用户画像缺失
- `summary_generated` 布尔标记不支持增量摘要

### 设计

| 层级 | 当前 | 优化后 | 理由 |
|------|------|--------|------|
| L2 触发 | 消息数 >= 10 | 消息数 >= 20 | 10 轮对话后摘要更有意义 |
| L2 去重 | `summary_generated` 布尔标记 | 记录已摘要的消息 ID 范围 | 支持增量摘要 |
| L3 触发 | L2 >= 5 条 | L2 >= 3 条 | 更早生成用户画像 |

**增量摘要机制：**
- Session 模型新增 `last_summarized_message_id` 字段
- 当会话消息增长到阈值时（如 20、40、60 条），只对新消息（last_summarized_message_id 之后的消息）生成补充摘要
- 每次增量摘要创建一条新的 L2 记录，而非覆盖旧记录
- 读取 L2 时取最近 N 条，自然包含增量摘要

---

## 4. 数据清理

### 当前问题

- Session 删除时没有级联删除 Message
- UserMemory 中的 `source_sessions` 引用变成孤立数据

### 设计

**即时级联删除（SQLAlchemy ORM）：**

```python
# models/session.py
class Session(Base):
    messages = relationship("Message", cascade="all, delete-orphan", ...)
```

删除 Session 时主动清理 UserMemory 中的 `source_sessions` 引用：

```python
# api/v1/session.py - delete_session
async def delete_session(...):
    await db.delete(session)
    # 清理 UserMemory 中的 source_sessions 引用
    memories = await db.execute(
        select(UserMemory).where(UserMemory.user_id == user.id)
    )
    for mem in memories.scalars():
        sources = json.loads(mem.source_sessions or "[]")
        if session_id in sources:
            sources.remove(session_id)
            mem.source_sessions = json.dumps(sources)
    await db.commit()
```

**定期清理孤立数据（API 端点）：**

新增 `POST /api/v1/admin/cleanup` 端点（需 JWT 认证），清理当前用户的：
- `source_sessions` 引用了不存在的 session_id 的 UserMemory
- 超过 90 天未更新的 Level 2 记忆（可配置）

手动触发，不需要定时任务。

---

## 5. 异步记忆更新

### 当前问题

`post_conversation_update` 在 `chat_stream` 中同步执行，LLM 生成摘要会阻塞 SSE 响应关闭。

### 设计

使用 `asyncio.create_task` 在后台执行记忆更新：

```python
# rag_service.py - chat_stream 末尾
async def _safe_post_update(memory_service, session_id, user_id):
    try:
        await memory_service.post_conversation_update(session_id, user_id)
    except Exception as e:
        logger.error(f"后台记忆更新失败: session_id={session_id}, error={e}")

# 调用处
asyncio.create_task(_safe_post_update(memory_service, session_id, user_id))
```

**效果：**
- SSE 流式响应立即关闭，用户感知更快
- 记忆更新在后台执行，不影响主流程
- 异常被捕获并记录日志，不会导致 500 错误

**限制：** 进程重启时未完成的任务会丢失。对记忆更新来说可接受——下次对话会重新触发检查。

---

## 影响的文件

| 文件 | 改动 |
|------|------|
| `backend/app/services/memory_service.py` | 动态预算、结构化摘要、触发阈值、增量摘要 |
| `backend/app/models/session.py` | 新增 `last_summarized_message_id` 字段 |
| `backend/app/models/memory.py` | content 字段存储 JSON |
| `backend/app/services/rag_service.py` | 异步记忆更新、传入意图到 build_memory_context |
| `backend/app/services/prompts.py` | 更新摘要生成 prompt |
| `backend/app/api/v1/session.py` | 级联删除逻辑 |
| `backend/alembic/versions/` | 新增迁移文件 |

## 验证清单

- [ ] 对话结束后 SSE 响应立即关闭，记忆更新在后台执行
- [ ] 不同意图的对话使用不同的 token 预算
- [ ] L2 摘要为 JSON 格式，包含 topic/key_points/pending
- [ ] L2 阈值提升到 20 条消息后才触发
- [ ] L3 在 3 条 L2 后即生成用户画像
- [ ] 删除 Session 时 Message 和 UserMemory 引用被清理
- [ ] 定期清理 API 能清除孤立数据
