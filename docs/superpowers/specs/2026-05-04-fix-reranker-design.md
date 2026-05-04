# 精排修复设计：DashScope API 优先

## 问题

`sentence-transformers` CrossEncoder 模型加载失败，精排静默降级到简单文本重叠评分（overlap），导致排序效果差。

## 方案

调整 `rerank()` 函数优先级：DashScope API → CrossEncoder → overlap 评分。

## 详细设计

### 优先级策略

```
rerank(question, documents, top_k=3)
  ├─ 1. DashScope API（主策略）
  │     - 模型：bge-reranker-v2-m3
  │     - top_n 限制：min(top_n, 50)
  │     - 成功：返回精排结果
  │     - 失败：降级到 CrossEncoder
  │
  ├─ 2. CrossEncoder（降级策略）
  │     - 模型：BAAI/bge-reranker-base
  │     - 成功：返回精排结果
  │     - 失败：降级到 overlap
  │
  └─ 3. overlap 评分（最终降级）
        - 简单文本重叠计算
        - 输出 WARNING 日志
```

### 参数变更

- `RETRIEVAL_TOP_K`：从 5 改为 **3**（精排后返回条数）

### 日志策略

| 位置 | 级别 | 内容 |
|------|------|------|
| DashScope 调用前 | INFO | `使用 DashScope 精排，候选 {n} 条` |
| DashScope 成功 | INFO | `DashScope 精排完成，返回 {n} 条，耗时 {ms}ms` |
| DashScope 失败 | WARNING | `DashScope 精排失败: {error}，降级到 CrossEncoder` |
| CrossEncoder 成功 | INFO | `CrossEncoder 精排完成，返回 {n} 条，耗时 {ms}ms` |
| CrossEncoder 失败 | WARNING | `CrossEncoder 精排失败: {error}，降级到 overlap 评分` |
| overlap 降级 | WARNING | `精排降级到 overlap 评分，结果可能不准确` |

### 边界处理

- 输入为空 → 直接返回空列表
- 输入只有 1 条 → 直接返回（无需精排）
- DashScope `top_n` > 50 → 截断到 50

### 涉及文件

- **修改**：`backend/app/services/reranker_service.py` — 调整优先级、加强日志
- **修改**：`backend/app/core/config.py` — `RETRIEVAL_TOP_K` 改为 3

### 验证

1. 查看后端日志，确认使用 DashScope 精排
2. 发送对话请求，检查 rerank 日志输出
3. 确认精排后返回 3 条结果
