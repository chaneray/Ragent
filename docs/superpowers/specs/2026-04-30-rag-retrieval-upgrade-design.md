# RAG 检索质量升级设计

日期：2026-04-30
状态：已批准
范围：后端 RAG 流程优化 + 前端文档分片管理

---

## 背景

当前 RAG 流程存在三个核心问题：
1. **语义鸿沟**：用户口语化提问，文档是专业术语，向量检索匹配不上
2. **分块不合理**：固定 1000 字硬切，可能切断句子，缺少完整上下文
3. **噪声过多**：检索到不相关段落，影响 LLM 回答质量

约束条件：最小依赖，优先使用已有 DashScope 服务。

---

## 优化方案总览

```
当前：  问题 → 向量检索 top_5 → LLM
优化后：问题 → 查询改写 → BM25+向量双路召回 top_15 → Reranker 精排 top_5 → LLM

入库端：固定字数切分 → 层级递进分块（段落→句子→短语）+ 上下文重叠
```

新增依赖：仅 `rank-bm25`（纯 Python，约 50KB），Reranker 用已有 DashScope API。

---

## 模块一：层级递进分块

### 设计

替换现有的 `RecursiveCharacterTextSplitter`，改为自定义 `SemanticChunker`。

切分逻辑（按语义粒度从大到小逐级切分）：

```
文档
  │
  ├─ 按段落(\n\n)切分
  │   ├─ 段落 ≤ chunk_size → 直接作为 chunk
  │   └─ 段落 > chunk_size → 按句子(。！？.!?)切分
  │       ├─ 句子组 ≤ chunk_size → 合并为 chunk
  │       └─ 单句 > chunk_size → 按短语(，；,;)切分
```

### 参数

| 参数 | 值 | 说明 |
|------|---|------|
| chunk_size | 1000 | 保持现有值 |
| chunk_overlap | 150 | 每个 chunk 末尾附带下一个 chunk 的前 150 字 |

### 上下文重叠

```
chunk_1: [段落A内容 ............ | 段落B前150字]
chunk_2: [段落B内容 ............ | 段落C前150字]
chunk_3: [段落C内容 ............ ]
```

重叠内容取自下一个 chunk 的开头，保证检索到一个 chunk 时能"看到"后续内容，避免语义断裂。

### 改动文件

- `backend/app/services/document_loader.py` — 新增 `SemanticChunker` 类，替换 `split_documents()` 实现

### 元数据增强

每个 chunk 保留以下 metadata：
- `source_file`：来源文件名
- `chunk_index`：在文档中的序号
- `page`：页码（PDF）
- `char_count`：字符数

---

## 模块二：查询改写

### 设计

检索前用 LLM 对用户问题做改写，生成 2-3 个不同表述的查询，弥合语义鸿沟。

```
用户原始问题："这个东西怎么装？"
        │
        ▼ LLM 改写
  ┌─────────────────────────────┐
  │ Q1: "产品安装步骤是什么？"     │  ← 保持原意
  │ Q2: "安装部署指南"            │  ← 专业术语版
  │ Q3: "如何进行系统安装和配置？"  │  ← 扩展表述
  └─────────────────────────────┘
        │
        ▼ 三个查询分别检索，结果合并去重
```

### 容错

- 改写失败（超时/异常）→ 降级为原始问题直接检索
- 改写结果缓存到 Redis（相同问题不重复调用 LLM），TTL 1 小时

### 性能开销

- 首次：LLM 改写约 200-500ms
- 缓存命中：0ms

### 改动文件

- `backend/app/services/rag_service.py` — 新增 `_rewrite_query()` 方法
- `backend/app/services/cache_service.py` — 新增 Redis 缓存封装（可选，可直接用内存 dict 替代）

---

## 模块三：混合检索（BM25 + 向量）

### 设计

双路召回：BM25 关键词检索 + 向量语义检索，取并集后用 RRF 融合排序。

```
用户问题（改写后的多个查询）
        │
   ┌────┴────┐
   ▼         ▼
 BM25      向量检索
 关键词     语义相似
   │         │
 top_k=10  top_k=10
   │         │
   └────┬────┘
        ▼
    合并去重（按 chunk 内容 hash）
        ▼
    RRF 融合排序
        │
        ▼
      top_k=15
```

### RRF 融合算法

```
RRF_score = 1/(k + rank_bm25) + 1/(k + rank_vector)
```

k=60（业界标准值），无需调参。如果一个 chunk 只在一路中出现，另一路 rank 设为无穷大。

### BM25 索引

- 每个知识库维护一份 BM25 索引（内存中）
- 索引内容：chunk 文本分词后的 token 列表
- 中文分词：使用 jieba（新增依赖，纯 Python）
- 知识库创建/文档上传时重建索引
- 首次检索时懒加载：从 MySQL 读取该知识库的所有 chunk 构建 BM25 索引，缓存在内存中
- 后续检索命中内存缓存，不再重复构建

### 改动文件

- `backend/app/services/rag_service.py` — 新增 `_bm25_search()` 和 `_hybrid_search()` 方法
- `backend/app/services/bm25_index.py` — 新增 BM25 索引管理类
- 新增依赖：`rank-bm25`、`jieba`

---

## 模块四：Reranker 重排

### 设计

混合检索召回 top_k=15 个候选 chunk，用 DashScope `gte-rerank` 模型精排，取 top_k=5 送入 LLM。

```
混合检索输出 top_k=15
        │
        ▼
  DashScope gte-rerank
  对每个 (query, chunk) 打精排分
        │
        ▼
  取 top_k=5 送入 LLM
  （score 附带在 metadata 中，前端可展示）
```

### 容错

- Reranker API 调用失败（超时/限流）→ 降级跳过，直接用混合检索结果
- 超时阈值：3 秒

### 性能开销

- Reranker API 约 100-300ms（15 个候选）
- 比 LLM 生成（1-5 秒）快得多，不构成瓶颈

### 改动文件

- `backend/app/services/reranker_service.py` — 新增 Reranker 服务封装
- `backend/app/services/rag_service.py` — 集成 Reranker 到检索流程

---

## 模块五：文档分片管理

### 设计

当前文档上传后只能看到状态（已索引/解析中），看不到实际分了哪些 chunk。新增文档详情页，展示该文档的所有 chunk 内容。

### 前端

在知识库详情页，点击某个文档 → 弹窗显示该文档的所有 chunk 列表：

```
┌─────────────────────────────────────────────┐
│ 文档：产品手册.pdf   状态：已索引   分片：12  │
├─────────────────────────────────────────────┤
│ [1] 第一章 产品概述                           │
│     本产品是一款基于 RAG 技术的智能问答系统...  │
│     来源：第1页 | 328字                        │
├─────────────────────────────────────────────┤
│ [2] 第一章 产品概述（续）                      │
│     系统支持多种文档格式上传...                  │
│     来源：第1页 | 256字                        │
├─────────────────────────────────────────────┤
│ [3] 第二章 功能说明                           │
│     ...                                      │
└─────────────────────────────────────────────┘
```

### 后端 API

```
GET /api/v1/documents/{id}/chunks
```

响应：
```json
{
  "document_id": 1,
  "filename": "产品手册.pdf",
  "chunk_count": 12,
  "chunks": [
    {
      "id": 1,
      "chunk_index": 0,
      "content": "第一章 产品概述\n本产品是一款...",
      "metadata": {
        "source_file": "产品手册.pdf",
        "page": 1,
        "char_count": 328
      }
    }
  ]
}
```

### 改动文件

- `backend/app/api/v1/document.py` — 新增 `GET /documents/{id}/chunks` 接口
- `frontend/src/views/KnowledgeBase/Detail.vue` — 新增 chunk 列表弹窗组件
- `frontend/src/api/document.ts` — 新增 `getDocumentChunks()` API 调用

---

## 完整数据流

### 入库流程（优化后）

```
文档上传
  → SemanticChunker 层级分块（段落→句子→短语 + 150字重叠）
  → Embedding 向量化
  → 写入 Milvus（向量）
  → 更新 BM25 索引（关键词）
  → 写入 Chunk 记录到 MySQL
```

### 检索流程（优化后）

```
用户问题
  → LLM 查询改写（2-3个表述，Redis 缓存）
  → 对每个改写查询：
      ├─ BM25 检索 top_10
      └─ 向量检索 top_10
  → 合并去重
  → RRF 融合排序 → top_15
  → DashScope Reranker 精排 → top_5
  → 拼接上下文 + 会话历史
  → LLM 流式生成
  → SSE 输出
```

---

## 新增依赖

| 包 | 用途 | 类型 |
|---|------|------|
| `rank-bm25` | BM25 关键词检索 | 纯 Python，约 50KB |
| `jieba` | 中文分词（BM25 索引构建） | 纯 Python，新增依赖 |

---

## 改动文件清单

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `backend/app/services/document_loader.py` | 重写 | 新增 SemanticChunker |
| `backend/app/services/rag_service.py` | 重写 | 集成查询改写 + 混合检索 + Reranker |
| `backend/app/services/bm25_index.py` | 新增 | BM25 索引管理 |
| `backend/app/services/reranker_service.py` | 新增 | DashScope Reranker 封装 |
| `backend/app/api/v1/document.py` | 修改 | 新增 chunks 查询接口 |
| `backend/app/core/config.py` | 修改 | 新增 Reranker 相关配置项 |
| `backend/pyproject.toml` | 修改 | 新增 rank-bm25, jieba 依赖 |
| `frontend/src/views/KnowledgeBase/Detail.vue` | 修改 | 新增 chunk 列表弹窗 |
| `frontend/src/api/document.ts` | 修改 | 新增 getDocumentChunks API |

---

## 容错与降级策略

| 场景 | 降级行为 |
|------|---------|
| 查询改写失败 | 用原始问题直接检索 |
| Redis 不可用 | 跳过缓存，每次重新改写 |
| BM25 索引未加载 | 跳过 BM25，只用向量检索 |
| Reranker API 超时 | 跳过重排，用混合检索原始排序 |
| 向量检索失败 | 只用 BM25 结果 |

所有降级对用户透明，不影响可用性。
