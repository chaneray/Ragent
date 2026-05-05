"""意图识别服务

使用 Function Calling 进行结构化输出，支持：
- 意图分类
- 置信度评估
- 槽位提取
- 上下文感知
- 规则引擎预处理（防注入）
"""

import re
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

# 注入模式检测正则
INJECTION_PATTERNS = [
    # 直接设置置信度
    r"置信度\s*[设选]\s*[为成]\s*\d",
    r"confidence\s*[设选]\s*[为成]\s*\d",
    r"[设选]\s*[为成]\s*置信度",
    r"[设选]\s*[为成]\s*confidence",
    # 试图控制输出
    r"返回\s*[特指]\s*[定]",
    r"输出\s*[特指]\s*[定]",
    r"请\s*[将把]\s*.*\s*[设选]\s*[为成]",
    r"你需要\s*[设选]\s*[为成]",
    r"你应该\s*[设选]\s*[为成]",
    r"要求.*[设选]\s*[为成]\s*\d",
    # 暗示/强调置信度高低
    r"置信度\s*非常",
    r"置信度\s*很高",
    r"置信度\s*很高",
    r"置信度\s*极[高低]",
    r"confidence\s*very\s*high",
    r"置信度\s*\d",
    # 试图直接指定意图类别
    r"这是一个.*查询.*知识库",
    r"这是一个.*知识库.*提问",
    r"这是一个.*闲聊",
    r"这是一个.*总结",
    r"这是一个.*对比",
    r"这是.*意图\s*是",
    # 提示注入标记
    r"ignore\s*previous",
    r"忽略.*之前.*指令",
    r"忽略.*上面.*规则",
    r"你是一个.*而不是",
]

# 意图关键词规则
INTENT_RULES = {
    "chitchat": [
        r"你好|hello|hi|嗨|hey",
        r"什么是\w+|是什么|怎么理解",
        r"谢谢|感谢|多谢",
        r"再见|拜拜|bye",
        r"推荐|建议|告诉我",
        r"聊[聊天]|闲聊",
    ],
    "knowledge_qa": [
        r"怎么|如何|怎样",
        r"为什么|原因|原理",
        r"配置|设置|安装",
        r"查询|查找|搜索",
        r"文档|资料|手册",
    ],
    "summarize": [
        r"总结|归纳|概括",
        r"摘要|提炼|梳理",
    ],
    "compare": [
        r"对比|比较|对照",
        r"区别|差异|不同",
        r"优缺点|优势|劣势",
    ],
    "complex_task": [
        r"分析.*并.*",
        r"帮我.*然后.*",
        r"首先.*然后.*最后",
        r"多步|步骤|流程",
    ],
}


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
        logger.info("=" * 60)
        logger.info("【意图识别】开始: question=%s, session_id=%d", question[:50], session_id)

        # 0. 规则引擎预处理：检测注入模式，直接返回，不经过验证和澄清
        if self._detect_injection(question):
            logger.warning("【意图识别】检测到注入模式，使用规则引擎判断")
            result = self._rule_based_classify(question)
            logger.info("【意图识别】规则引擎结果: intent=%s, confidence=%.2f", result.intent, result.confidence)
            logger.info("=" * 60)
            return result

        # 1. 构建上下文
        history = await self._build_history_context(session_id, db)
        logger.info("【意图识别】对话历史:\n%s", history)

        # 2. 调用 LLM
        prompt = INTENT_CLASSIFY_PROMPT.format(history=history, question=question)
        logger.info("【意图识别】完整 Prompt:\n%s", prompt)
        try:
            result = await self.structured_llm.ainvoke(prompt)
            logger.info("【意图识别】LLM 返回结果:")
            logger.info("  intent: %s", result.intent)
            logger.info("  confidence: %.2f", result.confidence)
            logger.info("  entities: %s", result.entities)
            logger.info("  action: %s", result.action)
            logger.info("  conditions: %s", result.conditions)
            logger.info("  needs_clarification: %s", result.needs_clarification)
            logger.info("  clarification_question: %s", result.clarification_question)
            logger.info("  clarification_options: %s", result.clarification_options)
        except Exception as e:
            logger.error("【意图识别】LLM 调用失败: %s", str(e))
            return self._get_default_result()

        # 3. 验证和修正
        validated = self._validate_result(result, question)
        logger.info("【意图识别】最终结果: intent=%s, confidence=%.2f", validated.intent, validated.confidence)
        logger.info("=" * 60)
        return validated

    def _detect_injection(self, question: str) -> bool:
        """检测用户问题是否包含注入模式

        Args:
            question: 用户问题

        Returns:
            bool: 是否检测到注入
        """
        for pattern in INJECTION_PATTERNS:
            match = re.search(pattern, question, re.IGNORECASE)
            if match:
                logger.warning("【注入检测】命中模式: '%s', 匹配内容: '%s', question=%s",
                             pattern, match.group(), question[:80])
                return True
        logger.info("【注入检测】未检测到注入模式, question=%s", question[:80])
        return False

    def _rule_based_classify(self, question: str) -> IntentResult:
        """使用规则引擎进行意图分类

        Args:
            question: 用户问题

        Returns:
            IntentResult: 意图识别结果
        """
        question_lower = question.lower()

        # 计算每个意图的匹配分数
        scores = {}
        for intent, patterns in INTENT_RULES.items():
            score = 0
            for pattern in patterns:
                if re.search(pattern, question_lower):
                    score += 1
            if score > 0:
                scores[intent] = score

        # 选择得分最高的意图
        if scores:
            best_intent = max(scores, key=scores.get)
            # 置信度根据匹配分数计算
            confidence = min(0.6, 0.3 + scores[best_intent] * 0.1)
            logger.info("【规则引擎】匹配结果: %s, 分数: %s, 置信度: %.2f", best_intent, scores, confidence)
        else:
            # 没有匹配到任何规则，默认为 chitchat
            best_intent = "chitchat"
            confidence = 0.5
            logger.info("【规则引擎】无匹配规则，默认: chitchat, 置信度: %.2f", confidence)

        return IntentResult(
            intent=best_intent,
            confidence=confidence,
            entities=[],
            action="rule_based",
            conditions=["检测到注入模式，使用规则引擎"],
            needs_clarification=False,
            clarification_question="",
            clarification_options=[],
        )

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
                .order_by(Message.id.desc())
                .limit(limit * 2)
            )
            messages = list(reversed(result.scalars().all()))
        except Exception as e:
            logger.warning("获取对话历史失败: %s", str(e))
            return "无历史对话"

        if not messages:
            return "无历史对话"

        # 配对校验：第一条必须是 user 消息，避免孤立的 assistant 回复
        selected = messages[-limit * 2:]
        while selected and selected[0].role != "user":
            selected = selected[1:]

        history_lines = []
        for msg in selected:
            role = "用户" if msg.role == "user" else "助手"
            # 截断过长消息，避免 token 溢出
            content = msg.content[:200] + "..." if len(msg.content) > 200 else msg.content
            history_lines.append(f"{role}: {content}")

        return "\n".join(history_lines)

    def _validate_result(self, result: IntentResult, question: str = "") -> IntentResult:
        """验证和修正 LLM 输出

        Args:
            result: LLM 返回的结果
            question: 用户原始问题

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
