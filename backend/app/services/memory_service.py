"""层级摘要记忆服务

三层金字塔结构：
- Level 1: 对话原文（短期，滑动窗口，token_budget=2000）
- Level 2: 主题归纳（中期，会话摘要）
- Level 3: 用户画像（长期，高度概括）
"""

import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.memory import UserMemory
from app.models.session import Session, Message
from app.services.llm_factory import create_chat_model

# token 预算常量
TOKEN_BUDGET_L1 = 2000  # 短期记忆 token 上限
TOKEN_BUDGET_L2 = 300   # 中期记忆 token 上限（最近 3 条）
TOKEN_BUDGET_L3 = 100   # 长期记忆 token 上限
TOTAL_MEMORY_BUDGET = 1000  # 总记忆预算

# 摘要生成 prompt
SUMMARY_PROMPT = """请用 200-300 字总结以下对话的关键讨论点、结论和决策。
要求：
1. 提取核心信息，忽略寒暄
2. 保留具体的技术术语、数值、结论
3. 用简洁的中文表述

对话内容：
{conversation}

请直接输出摘要内容，不要加标题或前缀。"""

# 用户画像合并 prompt
PROFILE_MERGE_PROMPT = """请根据以下多条会话摘要，生成一份用户画像。
要求：
1. 提取用户的角色、技术栈、偏好、常见话题
2. 用简洁的中文表述，控制在 100 字以内
3. 如果已有旧画像，请合并更新，保留仍有效的信息

已有画像：
{existing_profile}

近期会话摘要：
{summaries}

请直接输出更新后的用户画像，不要加标题或前缀。"""


def estimate_tokens(text: str) -> int:
    """粗略估算 token 数：1 中文字 ≈ 2 token，1 英文词 ≈ 1.5 token"""
    cn_chars = sum(1 for ch in text if "一" <= ch <= "鿿")
    other_len = len(text) - cn_chars
    return cn_chars * 2 + max(1, other_len // 4)


class MemoryService:
    """层级摘要记忆服务"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.llm = create_chat_model()

    # ── Level 1: 短期记忆（滑动窗口） ──────────────────────────

    async def get_short_term_memory(
        self, session_id: int, token_budget: int = TOKEN_BUDGET_L1
    ) -> list[dict]:
        """获取短期记忆：基于 token 预算的滑动窗口"""
        result = await self.db.execute(
            select(Message)
            .where(Message.session_id == session_id)
            .order_by(Message.created_at.desc())
        )
        messages = list(reversed(result.scalars().all()))

        window = []
        total_tokens = 0
        # 从最近消息开始逐条加入，直到超过 budget
        for msg in reversed(messages):
            msg_tokens = estimate_tokens(msg.content)
            if total_tokens + msg_tokens > token_budget:
                break
            window.insert(0, {"role": msg.role, "content": msg.content})
            total_tokens += msg_tokens

        return window

    # ── Level 2: 中期记忆（会话摘要） ──────────────────────────

    async def get_level2_memories(
        self, user_id: int, limit: int = 3
    ) -> list[UserMemory]:
        """获取最近的 Level 2 记忆"""
        result = await self.db.execute(
            select(UserMemory)
            .where(UserMemory.user_id == user_id, UserMemory.level == 2)
            .order_by(UserMemory.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def should_generate_summary(self, session_id: int) -> bool:
        """判断是否需要生成摘要：消息数 ≥ 10 且未生成过"""
        result = await self.db.execute(
            select(Session).where(Session.id == session_id)
        )
        session = result.scalar_one_or_none()
        if not session or session.summary_generated:
            return False

        count_result = await self.db.execute(
            select(func.count()).select_from(Message).where(Message.session_id == session_id)
        )
        msg_count = count_result.scalar() or 0
        return msg_count >= 10

    async def generate_session_summary(self, session_id: int, user_id: int) -> Optional[UserMemory]:
        """生成会话摘要（Level 2 记忆）"""
        # 获取完整对话
        result = await self.db.execute(
            select(Message)
            .where(Message.session_id == session_id)
            .order_by(Message.created_at.asc())
        )
        messages = list(result.scalars().all())
        if not messages:
            return None

        # 格式化对话内容
        conversation = "\n".join(
            "%s: %s" % ("用户" if m.role == "user" else "助手", m.content)
            for m in messages
        )

        # 限制对话长度避免 token 溢出
        if estimate_tokens(conversation) > 8000:
            conversation = conversation[:8000] + "\n...(对话过长，已截断)"

        # LLM 生成摘要
        try:
            prompt = SUMMARY_PROMPT.format(conversation=conversation)
            logger.debug("[摘要生成] Prompt:\n%s", prompt[:500])
            response = await self.llm.ainvoke(prompt)
            summary = response.content if hasattr(response, "content") else str(response)
            logger.debug("[摘要生成] LLM 返回: %s", summary[:500])
            summary = summary.strip()
            logger.info("会话摘要生成完成: session_id=%d, 长度=%d", session_id, len(summary))
        except Exception as e:
            logger.error("会话摘要生成失败: session_id=%d, error=%s", session_id, str(e))
            return None

        # 写入 Level 2 记忆
        memory = UserMemory(
            user_id=user_id,
            level=2,
            content=summary,
            source_sessions=[session_id],
            token_count=estimate_tokens(summary),
        )
        self.db.add(memory)

        # 标记会话已生成摘要
        session_result = await self.db.execute(
            select(Session).where(Session.id == session_id)
        )
        session = session_result.scalar_one_or_none()
        if session:
            session.summary_generated = True

        await self.db.commit()
        await self.db.refresh(memory)
        return memory

    # ── Level 3: 长期记忆（用户画像） ──────────────────────────

    async def get_level3_memory(self, user_id: int) -> Optional[UserMemory]:
        """获取用户画像"""
        result = await self.db.execute(
            select(UserMemory)
            .where(UserMemory.user_id == user_id, UserMemory.level == 3)
            .order_by(UserMemory.updated_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def check_and_merge_level3(self, user_id: int) -> Optional[UserMemory]:
        """检查 Level 2 数量，达到 5 条时合并为 Level 3"""
        result = await self.db.execute(
            select(UserMemory)
            .where(UserMemory.user_id == user_id, UserMemory.level == 2)
            .order_by(UserMemory.created_at.desc())
        )
        level2_list = list(result.scalars().all())

        if len(level2_list) < 5:
            return None

        logger.info("Level3 合并触发: user_id=%d, l2_count=%d", user_id, len(level2_list))

        # 取最近 5 条 Level 2
        to_merge = level2_list[:5]
        summaries = "\n---\n".join(m.content for m in to_merge)

        # 获取已有画像
        existing = await self.get_level3_memory(user_id)
        existing_profile = existing.content if existing else "暂无"

        # LLM 合并画像
        try:
            prompt = PROFILE_MERGE_PROMPT.format(
                existing_profile=existing_profile,
                summaries=summaries,
            )
            logger.debug("[画像合并] Prompt:\n%s", prompt[:500])
            response = await self.llm.ainvoke(prompt)
            profile = response.content if hasattr(response, "content") else str(response)
            logger.debug("[画像合并] LLM 返回: %s", profile[:500])
            profile = profile.strip()
        except Exception:
            return None

        # 更新或创建 Level 3
        if existing:
            existing.content = profile
            existing.token_count = estimate_tokens(profile)
            existing.source_sessions = (
                existing.source_sessions or []
            ) + [sid for m in to_merge for sid in (m.source_sessions or [])]
            await self.db.commit()
            return existing
        else:
            memory = UserMemory(
                user_id=user_id,
                level=3,
                content=profile,
                source_sessions=[sid for m in to_merge for sid in (m.source_sessions or [])],
                token_count=estimate_tokens(profile),
            )
            self.db.add(memory)
            await self.db.commit()
            await self.db.refresh(memory)
            return memory

    # ── 记忆注入 ──────────────────────────────────────────────

    async def build_memory_context(self, user_id: int, session_id: int) -> str:
        """构建记忆上下文文本，注入到 prompt 中"""
        parts = []

        # Level 3: 用户画像
        l3 = await self.get_level3_memory(user_id)
        if l3:
            parts.append("[用户画像]\n%s" % l3.content)
            logger.debug("L3 用户画像: %s", l3.content)
        else:
            logger.debug("L3 用户画像: 无")

        # Level 2: 最近的主题归纳
        l2_list = await self.get_level2_memories(user_id, limit=3)
        if l2_list:
            l2_text = "\n".join("- %s" % m.content for m in l2_list)
            parts.append("[近期讨论主题]\n%s" % l2_text)
            for i, m in enumerate(l2_list):
                logger.debug("L2 会话摘要[%d]: %s", i, m.content)
        else:
            logger.debug("L2 会话摘要: 无")

        # Level 1: 短期记忆
        l1 = await self.get_short_term_memory(session_id)
        if l1:
            l1_text = "\n".join(
                "%s: %s" % ("用户" if m["role"] == "user" else "助手", m["content"])
                for m in l1
            )
            parts.append("[近期对话]\n%s" % l1_text)
            for m in l1:
                logger.debug("L1 短期记忆 [%s]: %s", m["role"], m["content"][:200])
        else:
            logger.debug("L1 短期记忆: 无")

        logger.info("记忆查询: user_id=%d, l3=%s, l2=%d条, l1=%d条",
                     user_id, "有" if l3 else "无", len(l2_list), len(l1))
        return "\n\n".join(parts) if parts else ""

    # ── 对话结束后的记忆更新流程 ────────────────────────────────

    async def post_conversation_update(self, session_id: int, user_id: int) -> None:
        """对话结束后更新记忆：生成 Level 2 → 检查是否合并 Level 3"""
        if await self.should_generate_summary(session_id):
            await self.generate_session_summary(session_id, user_id)
            await self.check_and_merge_level3(user_id)
