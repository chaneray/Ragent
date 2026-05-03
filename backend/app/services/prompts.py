"""Prompt 模板集中管理

根据意图识别结果，动态组装不同的 prompt。
"""

# ── 意图识别（旧版，保留兼容） ─────────────────────────────────

INTENT_PROMPT = """分析用户问题的意图，返回以下标签之一：
- knowledge_qa: 需要从知识库检索信息来回答的问题
- chitchat: 闲聊、问候、简单定义、翻译、计算等不需要知识库的问题
- summarize: 要求总结、归纳某主题
- compare: 要求对比两个或多个事物
- complex_task: 需要多步骤推理、拆解子任务、调用多个工具才能完成的复杂问题

注意：
- "什么是X"、"X是什么" 这类定义问题属于 chitchat 或 knowledge_qa，不是 complex_task
- complex_task 仅限于需要多步推理和工具调用的复杂任务，如"帮我对比A和B的优缺点并给出建议"

只返回 JSON: {{"intent": "标签名"}}

用户问题：{question}"""

# ── 意图识别（新版，支持置信度 + 槽位提取） ─────────────────────

INTENT_CLASSIFY_PROMPT = """你是一个意图分类专家。请分析用户问题，返回结构化的分类结果。

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
{question}"""

# ── 意图标签常量 ──────────────────────────────────────────────

INTENT_KNOWLEDGE_QA = "knowledge_qa"
INTENT_CHITCHAT = "chitchat"
INTENT_SUMMARIZE = "summarize"
INTENT_COMPARE = "compare"
INTENT_COMPLEX_TASK = "complex_task"

# 默认意图（分类失败时回退）
DEFAULT_INTENT = INTENT_KNOWLEDGE_QA

# ── 角色定义 ──────────────────────────────────────────────────

SYSTEM_ROLES = {
    INTENT_KNOWLEDGE_QA: "你是一个基于知识库的智能问答助手。请根据检索到的资料准确回答用户问题。",
    INTENT_CHITCHAT: "你是一个友好、简洁的 AI 助手。请用自然流畅的方式与用户对话。",
    INTENT_SUMMARIZE: "你是一个专业的分析助手。请对给定内容进行结构化总结。",
    INTENT_COMPARE: "你是一个专业的分析助手。请对给定内容进行对比分析，列出异同并给出结论。",
    INTENT_COMPLEX_TASK: "你是一个擅长推理的助手。请分步骤推理，标注中间结论，最终给出完整答案。",
}

# ── 任务特定指令 ──────────────────────────────────────────────

TASK_INSTRUCTIONS = {
    INTENT_KNOWLEDGE_QA: """要求：
1. 优先根据检索到的资料回答，在引用处标注 [来源: 文档名]
2. 如果资料只部分相关，先引用相关内容，再用自身知识补充说明
3. 如果资料完全不相关或为空，直接用自身知识回答，不要提及"资料不足"或"检索不到"
4. 回答应准确、完整，不要因为检索结果不理想就放弃回答""",

    INTENT_CHITCHAT: """要求：
1. 用简洁友好的方式回答
2. 不需要引用来源
3. 保持自然对话风格""",

    INTENT_SUMMARIZE: """要求：
1. 用结构化的方式输出总结
2. 分点列出关键信息
3. 保留重要数据和结论""",

    INTENT_COMPARE: """要求：
1. 用表格形式对比
2. 列出相同点和不同点
3. 最后给出总结性结论""",

    INTENT_COMPLEX_TASK: """要求：
1. 分步骤推理
2. 每步标注中间结论
3. 最终给出完整答案""",
}

# ── 完整 Prompt 模板 ──────────────────────────────────────────

# 有知识库上下文的 prompt
RAG_PROMPT_TEMPLATE = """{system_role}

{task_specific}

检索到的资料：
{context}

{memory_context}

用户问题：{question}

请用中文回答。"""

# 无知识库上下文的 prompt（闲聊等）
CHAT_PROMPT_TEMPLATE = """{system_role}

{task_specific}

{memory_context}

用户问题：{question}"""


def build_prompt(
    intent: str,
    question: str,
    context: str = "",
    memory_context: str = "",
) -> str:
    """根据意图构建完整的 prompt"""
    system_role = SYSTEM_ROLES.get(intent, SYSTEM_ROLES[DEFAULT_INTENT])
    task_specific = TASK_INSTRUCTIONS.get(intent, TASK_INSTRUCTIONS[DEFAULT_INTENT])

    if intent == INTENT_CHITCHAT:
        return CHAT_PROMPT_TEMPLATE.format(
            system_role=system_role,
            task_specific=task_specific,
            memory_context=memory_context,
            question=question,
        )
    else:
        return RAG_PROMPT_TEMPLATE.format(
            system_role=system_role,
            task_specific=task_specific,
            context=context,
            memory_context=memory_context,
            question=question,
        )
