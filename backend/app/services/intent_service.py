"""意图识别服务

使用 Function Calling 进行结构化输出，支持：
- 意图分类
- 置信度评估
- 槽位提取
- 上下文感知
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.session import Message
from app.schemas.intent import IntentResult
from app.services.prompts import INTENT_CLASSIFY_PROMPT

logger = logging.getLogger(__name__)

# 有效意图集合
VALID_INTENTS = {"knowledge_qa", "chitchat", "summarize", "compare", "complex_task"}

# 置信度阈值
CONFIDENCE_THRESHOLD = 0.7


class IntentService:
    """意图识别服务"""

    def __init__(self, llm):
        """初始化意图识别服务

        Args:
            llm: LangChain ChatModel 实例
        """
        self.llm = llm
        self.structured_llm = llm.with_structured_output(IntentResult)

    async def classify(
        self,
        question: str,
        session_id: int,
        db: AsyncSession,
    ) -> IntentResult:
        """意图分类主入口

        Args:
            question: 用户问题
            session_id: 会话 ID
            db: 数据库会话

        Returns:
            IntentResult: 意图识别结果
        """
        logger.info("开始意图识别: question=%s, session_id=%d", question[:50], session_id)

        # 1. 构建上下文
        history = await self._build_history_context(session_id, db)
        logger.debug("对话历史: %s", history[:200])

        # 2. 调用 LLM
        prompt = INTENT_CLASSIFY_PROMPT.format(history=history, question=question)
        try:
            result = await self.structured_llm.ainvoke(prompt)
            logger.info(
                "意图识别完成: intent=%s, confidence=%.2f, needs_clarification=%s",
                result.intent,
                result.confidence,
                result.needs_clarification,
            )
        except Exception as e:
            logger.error("意图识别 LLM 调用失败: %s", str(e))
            return self._get_default_result()

        # 3. 验证和修正
        validated = self._validate_result(result)
        return validated

    async def _build_history_context(
        self,
        session_id: int,
        db: AsyncSession,
        limit: int = 5,
    ) -> str:
        """构建最近 N 轮对话历史

        Args:
            session_id: 会话 ID
            db: 数据库会话
            limit: 最近 N 轮对话

        Returns:
            str: 格式化的对话历史
        """
        try:
            result = await db.execute(
                select(Message)
                .where(Message.session_id == session_id)
                .order_by(Message.created_at.desc())
                .limit(limit * 2)
            )
            messages = list(reversed(result.scalars().all()))
        except Exception as e:
            logger.warning("获取对话历史失败: %s", str(e))
            return "无历史对话"

        if not messages:
            return "无历史对话"

        history_lines = []
        for msg in messages[-limit * 2:]:
            role = "用户" if msg.role == "user" else "助手"
            # 截断过长消息，避免 token 溢出
            content = msg.content[:200] + "..." if len(msg.content) > 200 else msg.content
            history_lines.append(f"{role}: {content}")

        return "\n".join(history_lines)

    def _validate_result(self, result: IntentResult) -> IntentResult:
        """验证和修正 LLM 输出

        Args:
            result: LLM 返回的结果

        Returns:
            IntentResult: 验证后的结果
        """
        # 验证意图标签
        if result.intent not in VALID_INTENTS:
            logger.warning("无效的意图标签: %s，回退到默认", result.intent)
            result.intent = "knowledge_qa"
            result.confidence = 0.5

        # 验证置信度范围
        if not (0 <= result.confidence <= 1):
            logger.warning("置信度超出范围: %.2f", result.confidence)
            result.confidence = max(0, min(1, result.confidence))

        # 低置信度时自动设置澄清
        if result.confidence < CONFIDENCE_THRESHOLD and not result.needs_clarification:
            result.needs_clarification = True
            if not result.clarification_question:
                result.clarification_question = self._generate_clarification(result)

        return result

    def _generate_clarification(self, result: IntentResult) -> str:
        """生成澄清问题

        Args:
            result: 意图识别结果

        Returns:
            str: 澄清问题
        """
        intent_descriptions = {
            "knowledge_qa": "查询知识库",
            "chitchat": "闲聊",
            "summarize": "总结归纳",
            "compare": "对比分析",
            "complex_task": "复杂任务",
        }

        if result.intent in intent_descriptions:
            return f"您的问题似乎是想{intent_descriptions[result.intent]}，对吗？"
        return "请明确您的问题意图，是想查询知识、闲聊、总结还是对比分析？"

    def _get_default_result(self) -> IntentResult:
        """获取默认结果（LLM 调用失败时使用）

        Returns:
            IntentResult: 默认结果
        """
        return IntentResult(
            intent="knowledge_qa",
            confidence=0.5,
            entities=[],
            action="",
            conditions=[],
            needs_clarification=False,
            clarification_question="",
        )
