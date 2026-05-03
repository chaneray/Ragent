# 意图识别升级设计文档

## 概述

升级当前系统的意图识别模块，从简单的单次 LLM 分类升级为支持置信度评估、上下文感知、槽位提取和主动澄清的企业级意图识别系统。

## 当前实现

**现状**：
- 5 个意图：`knowledge_qa`, `chitchat`, `summarize`, `compare`, `complex_task`
- 单次 LLM 调用，返回 JSON `{"intent": "标签名"}`
- 无置信度评估，无上下文感知
- 分类失败默认回退到 `knowledge_qa`

**问题**：
1. 无法判断分类结果的可靠性
2. 不结合对话历史，无法处理指代消解（如 "那它呢？"）
3. 不提取关键信息，无法优化后续检索
4. 模糊问题直接猜测，用户体验差

## 升级目标

1. **置信度评估**：每次分类返回 0-1 的置信度分数
2. **上下文感知**：结合最近 3-5 轮对话历史进行分类
3. **槽位提取**：同时提取实体、动作、条件等关键信息
4. **主动澄清**：置信度 < 0.7 时，返回澄清问题让用户确认

## 技术方案

### 方案选择：单次 LLM 调用 + Function Calling

**理由**：
- 延迟最低（1 次 LLM 调用）
- 使用 LangChain `.with_structured_output()` 强制结构化输出
- 支持 DashScope / OpenAI / DeepSeek

### 整体架构

```
用户问题 + 对话历史（3-5 轮）
           ↓
   ┌───────────────────┐
   │  单次 LLM 调用      │
   │  (Function Calling) │
   │  - 意图分类         │
   │  - 置信度评估       │
   │  - 槽位提取         │
   └─────────┬─────────┘
             ↓
      ┌──────┴──────┐
      │ 置信度 ≥ 0.7?│
      └──────┬──────┘
        Yes  │  No
        ↓    ↓
     直接返回  触发澄清
```

### 输出格式

```json
{
  "intent": "knowledge_qa",
  "confidence": 0.92,
  "entities": ["Milvus", "向量数据库"],
  "action": "查询配置",
  "conditions": ["生产环境"],
  "needs_clarification": false,
  "clarification_question": ""
}
```

### Prompt 设计

```python
INTENT_CLASSIFY_PROMPT = """你是一个意图分类专家。请分析用户问题，返回 JSON 格式的分类结果。

## 意图类别
- knowledge_qa: 需要从知识库检索信息来回答的问题
- chitchat: 闲聊、问候、简单定义、翻译、计算等不需要知识库的问题
- summarize: 要求总结、归纳某主题
- compare: 要求对比两个或多个事物
- complex_task: 需要多步骤推理、拆解子任务、调用多个工具才能完成的复杂问题

## 判断规则
1. 如果问题模糊或可能属于多个意图，confidence 应低于 0.7
2. confidence < 0.7 时，needs_clarification 设为 true，并生成澄清问题
3. "什么是X"、"X是什么" 属于 chitchat 或 knowledge_qa，不是 complex_task
4. 结合对话历史理解指代关系（如 "它"、"这个"）

## 对话历史
{history}

## 用户问题
{question}

请分析并返回结构化结果。"""
```

### Pydantic 模型

```python
from pydantic import BaseModel, Field
from typing import Optional

class IntentResult(BaseModel):
    """意图识别结果"""
    intent: str = Field(
        description="意图标签",
        enum=["knowledge_qa", "chitchat", "summarize", "compare", "complex_task"]
    )
    confidence: float = Field(
        description="置信度 0.0-1.0",
        ge=0,
        le=1
    )
    entities: list[str] = Field(
        description="提到的关键实体",
        default_factory=list
    )
    action: str = Field(
        description="用户想执行的动作",
        default=""
    )
    conditions: list[str] = Field(
        description="限制条件",
        default_factory=list
    )
    needs_clarification: bool = Field(
        description="是否需要澄清",
        default=False
    )
    clarification_question: str = Field(
        description="澄清问题",
        default=""
    )
```

### 澄清机制

**触发条件**：`confidence < 0.7` 且 `needs_clarification = true`

**SSE 响应格式**：
```json
{
  "event": "clarification",
  "data": {
    "question": "您是想查询 Milvus 的配置方法，还是想了解 Milvus 的性能对比？",
    "options": ["查询配置", "性能对比", "其他"]
  }
}
```

**前端处理**：
1. 收到 `clarification` 事件时，显示澄清问题和选项
2. 用户选择后，将选择结果作为新消息发送
3. 后端收到澄清回复后，直接使用用户选择的意图继续处理

**避免无限澄清**：
- 每个问题最多澄清一次
- 澄清后的回复直接进入处理流程

### 上下文感知

**历史消息获取**：
```python
async def _build_history_context(self, session_id: int, limit: int = 5) -> str:
    """构建最近 N 轮对话历史"""
    messages = await self._get_session_history(session_id, limit=limit * 2)
    if not messages:
        return "无历史对话"
    
    history_lines = []
    for msg in messages[-limit * 2:]:
        role = "用户" if msg["role"] == "user" else "助手"
        content = msg["content"][:200] + "..." if len(msg["content"]) > 200 else msg["content"]
        history_lines.append(f"{role}: {content}")
    
    return "\n".join(history_lines)
```

**Token 控制**：
- 历史消息总 token 控制在 500 以内
- 每条消息截断到 200 字符

### 槽位提取

**用途**：
1. **entities**：可用于优化检索查询
2. **action**：理解用户意图的具体动作
3. **conditions**：限制条件，可用于过滤结果

**示例**：
- 问题："帮我查一下 Milvus 在生产环境的配置"
- 槽位：`entities=["Milvus"]`, `action="查询配置"`, `conditions=["生产环境"]`

## 代码结构

### 新增文件

- `backend/app/services/intent_service.py` - 意图识别服务

### 修改文件

- `backend/app/services/prompts.py` - 新增意图识别 prompt
- `backend/app/services/rag_service.py` - 调用新的意图服务
- `backend/app/api/v1/chat.py` - 支持澄清响应

### IntentService 接口

```python
class IntentService:
    """意图识别服务"""
    
    def __init__(self, llm: BaseChatModel):
        self.llm = llm
        self.structured_llm = llm.with_structured_output(IntentResult)
    
    async def classify(
        self,
        question: str,
        session_id: int,
        db: AsyncSession,
    ) -> IntentResult:
        """意图分类主入口"""
        # 1. 构建上下文
        history = await self._build_history_context(session_id, db)
        
        # 2. 调用 LLM
        prompt = INTENT_CLASSIFY_PROMPT.format(history=history, question=question)
        result = await self.structured_llm.ainvoke(prompt)
        
        # 3. 验证和修正
        return self._validate_result(result)
    
    def _validate_result(self, result: IntentResult) -> IntentResult:
        """验证和修正 LLM 输出"""
        valid_intents = {"knowledge_qa", "chitchat", "summarize", "compare", "complex_task"}
        if result.intent not in valid_intents:
            result.intent = "knowledge_qa"
            result.confidence = 0.5
        return result
```

### RagService 改动

```python
# 原来
intent = await self._classify_intent(question)

# 改为
intent_service = IntentService(self.llm)
intent_result = await intent_service.classify(question, session_id, self.db)

# 处理澄清
if intent_result.needs_clarification and intent_result.confidence < 0.7:
    yield json.dumps({
        "event": "clarification",
        "data": {
            "question": intent_result.clarification_question,
            "options": [...]  # 根据意图生成选项
        }
    })
    return

intent = intent_result.intent
slots = intent_result.slots  # 可用于优化检索
```

## 验证清单

- [ ] 意图分类返回置信度分数
- [ ] 置信度 < 0.7 时触发澄清
- [ ] 澄清问题通过 SSE 事件返回
- [ ] 前端正确显示澄清问题和选项
- [ ] 用户选择后继续正常处理
- [ ] 对话历史正确注入 prompt
- [ ] 槽位信息正确提取
- [ ] 指代消解正常工作（如 "那它呢？"）
- [ ] 分类失败时回退到默认意图
