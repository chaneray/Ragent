"""层级摘要记忆服务

三层金字塔结构：
- Level 1: 对话原文（短期，滑动窗口，token_budget 按意图动态分配）
- Level 2: 会话摘要（中期，会话级，关联 session_id）
- Level 3: 用户画像（长期，用户级，关联 user_id）
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

# ── 动态 Token 预算配置 ────────────────────────────────────────

# 意图 → 预算配置映射
BUDGET_PROFILES = {
    "knowledge_qa":  {"l1": 2500, "l2_count": 2, "l2_tokens": 200, "l3": 100},
    "summarize":     {"l1": 2000, "l2_count": 3, "l2_tokens": 300, "l3": 100},
    "compare":       {"l1": 2500, "l2_count": 3, "l2_tokens": 300, "l3": 100},
    "chitchat":      {"l1": 1000, "l2_count": 3, "l2_tokens": 300, "l3": 300},
    "complex_task":  {"l1": 2000, "l2_count": 2, "l2_tokens": 200, "l3": 100},
    "default":       {"l1": 2000, "l2_count": 3, "l2_tokens": 300, "l3": 100},
}

# 增量摘要触发阈值（消息数）
SUMMARY_THRESHOLDS = [20, 40, 60, 80, 100]

# L3 source_sessions 最大数量
MAX_SOURCE_SESSIONS = 20

# ── 提示词 ─────────────────────────────────────────────────────

# L2 结构化摘要提示词
SUMMARY_PROMPT = """请将以下对话总结为结构化摘要，严格按 JSON 格式输出：
要求：
1. 提取核心信息，忽略寒暄
2. 保留具体的技术术语、数值、结论
3. topic 不超过 30 字
4. key_points 最多 3 条，每条不超过 50 字
5. pending 最多 2 条，如果没有未解决的问题，输出空数组 []

对话内容：
{conversation}

请直接输出 JSON，不要加标题或前缀。格式如下：
{{"topic": "...", "key_points": ["..."], "pending": []}}"""

# L3 用户画像合并提示词
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


def get_budget_for_intent(intent: str) -> dict:
    """根据意图获取动态预算配置"""
    return BUDGET_PROFILES.get(intent, BUDGET_PROFILES["default"])


class MemoryService:
    """层级摘要记忆服务"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.llm = create_chat_model()

    # ── Level 1: 短期记忆（滑动窗口） ──────────────────────────

    async def get_short_term_memory(
        self, session_id: int, token_budget: int = 2000
    ) -> list[dict]:
        """获取短期记忆：基于 token 预算的滑动窗口，含配对校验"""
        result = await self.db.execute(
            select(Message)
            .where(Message.session_id == session_id)
            .order_by(Message.id.desc())
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

        # 配对校验：第一条必须是 user 消息，避免孤立的 assistant 回复
        while window and window[0]["role"] != "user":
            window.pop(0)

        return window

    # ── Level 2: 中期记忆（会话摘要） ──────────────────────────

    async def get_level2_memories(
        self, user_id: int, limit: int = 3, session_id: int = None
    ) -> list[UserMemory]:
        """获取最近的 Level 2 记忆

        Args:
            user_id: 用户 ID
            limit: 返回条数
            session_id: 如果指定，只返回该会话的 L2；否则返回该用户所有 L2
        """
        query = select(UserMemory).where(UserMemory.user_id == user_id, UserMemory.level == 2)
        if session_id is not None:
            query = query.where(UserMemory.session_id == session_id)
        query = query.order_by(UserMemory.created_at.desc()).limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def should_generate_summary(self, session_id: int) -> bool:
        """判断是否需要生成摘要：消息数达到下一个阈值且尚未生成"""
        result = await self.db.execute(
            select(Session).where(Session.id == session_id)
        )
        session = result.scalar_one_or_none()
        if not session:
            return False

        # 获取消息总数
        count_result = await self.db.execute(
            select(func.count()).select_from(Message).where(Message.session_id == session_id)
        )
        msg_count = count_result.scalar() or 0

        # 获取已摘要的最后一条消息 ID
        last_summarized_id = session.last_summarized_message_id or 0

        # 统计已摘要的消息数量（ID <= last_summarized_id）
        if last_summarized_id > 0:
            summarized_result = await self.db.execute(
                select(func.count()).select_from(Message).where(
                    Message.session_id == session_id,
                    Message.id <= last_summarized_id,
                )
            )
            summarized_count = summarized_result.scalar() or 0
        else:
            summarized_count = 0

        # 检查是否达到下一个阈值
        for threshold in SUMMARY_THRESHOLDS:
            if msg_count >= threshold and summarized_count < threshold:
                logger.info("触发增量摘要: session_id=%d, msg_count=%d, summarized_count=%d, threshold=%d",
                            session_id, msg_count, summarized_count, threshold)
                return True

        return False

    async def generate_session_summary(self, session_id: int, user_id: int) -> Optional[UserMemory]:
        """生成会话摘要（Level 2 记忆）—— 增量版本"""
        # 获取 session 信息
        session_result = await self.db.execute(
            select(Session).where(Session.id == session_id)
        )
        session = session_result.scalar_one_or_none()
        if not session:
            return None

        last_summarized_id = session.last_summarized_message_id or 0

        # 获取增量消息（last_summarized_id 之后的消息）
        query = select(Message).where(
            Message.session_id == session_id,
            Message.id > last_summarized_id,
        ).order_by(Message.id.asc())
        result = await self.db.execute(query)
        messages = list(result.scalars().all())
        if not messages:
            logger.info("无增量消息，跳过摘要: session_id=%d", session_id)
            return None

        # 格式化对话内容
        conversation = "\n".join(
            "%s: %s" % ("用户" if m.role == "user" else "助手", m.content)
            for m in messages
        )

        # 限制对话长度避免 token 溢出
        if estimate_tokens(conversation) > 8000:
            conversation = conversation[:8000] + "\n...(对话过长，已截断)"

        # LLM 生成结构化摘要
        try:
            prompt = SUMMARY_PROMPT.format(conversation=conversation)
            logger.debug("[摘要生成] Prompt:\n%s", prompt[:500])
            response = await self.llm.ainvoke(prompt)
            summary = response.content if hasattr(response, "content") else str(response)
            summary = summary.strip()
            logger.info("会话摘要生成完成: session_id=%d, 长度=%d", session_id, len(summary))

            # 尝试解析 JSON，失败则降级为纯文本
            try:
                parsed = json.loads(summary)
                summary = json.dumps(parsed, ensure_ascii=False)
            except json.JSONDecodeError:
                logger.warning("摘要 JSON 解析失败，降级为纯文本: session_id=%d", session_id)

        except Exception as e:
            logger.error("会话摘要生成失败: session_id=%d, error=%s", session_id, str(e))
            return None

        # 写入 Level 2 记忆（关联 session_id）
        memory = UserMemory(
            user_id=user_id,
            session_id=session_id,
            level=2,
            content=summary,
            source_sessions=[session_id],
            token_count=estimate_tokens(summary),
        )
        self.db.add(memory)

        # 更新已摘要的最后一条消息 ID
        last_message_id = messages[-1].id
        session.last_summarized_message_id = last_message_id
        logger.info("更新 last_summarized_message_id: session_id=%d, id=%d", session_id, last_message_id)

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
        """检查 Level 2 数量，达到 3 条时合并为 Level 3"""
        result = await self.db.execute(
            select(UserMemory)
            .where(UserMemory.user_id == user_id, UserMemory.level == 2)
            .order_by(UserMemory.created_at.desc())
        )
        level2_list = list(result.scalars().all())

        if len(level2_list) < 3:
            return None

        logger.info("Level3 合并触发: user_id=%d, l2_count=%d", user_id, len(level2_list))

        # 取最近 3 条 Level 2
        to_merge = level2_list[:3]
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
            new_sessions = [sid for m in to_merge for sid in (m.source_sessions or [])]
            existing.source_sessions = (
                existing.source_sessions or []
            ) + new_sessions
            # 裁剪 source_sessions，保留最近 MAX_SOURCE_SESSIONS 个
            existing.source_sessions = existing.source_sessions[-MAX_SOURCE_SESSIONS:]
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

    async def build_memory_context(self, user_id: int, session_id: int, intent: str = None) -> str:
        """构建记忆上下文文本，注入到 prompt 中

        Args:
            user_id: 用户 ID
            session_id: 会话 ID
            intent: 意图类型，用于动态分配 token 预算
        """
        # 获取动态预算
        budget = get_budget_for_intent(intent)
        logger.info("动态预算分配: intent=%s, budget=%s", intent, budget)

        parts = []

        # Level 3: 用户画像
        l3 = await self.get_level3_memory(user_id)
        if l3:
            parts.append("[用户画像]\n%s" % l3.content)
            logger.info("【L3 用户画像】\n%s", l3.content)
        else:
            logger.info("【L3 用户画像】无")

        # Level 2: 最近的主题归纳（会话级别）
        l2_list = await self.get_level2_memories(user_id, limit=budget["l2_count"], session_id=session_id)
        if l2_list:
            l2_text = "\n".join("- %s" % m.content for m in l2_list)
            parts.append("[近期讨论主题]\n%s" % l2_text)
            logger.info("【L2 会话摘要】%d 条:", len(l2_list))
            for i, m in enumerate(l2_list):
                logger.info("  L2[%d]: %s", i, m.content)
        else:
            logger.info("【L2 会话摘要】无")

        # Level 1: 短期记忆（当前会话）
        l1 = await self.get_short_term_memory(session_id, token_budget=budget["l1"])
        if l1:
            l1_text = "\n".join(
                "%s: %s" % ("用户" if m["role"] == "user" else "助手", m["content"])
                for m in l1
            )
            parts.append("[近期对话]\n%s" % l1_text)
            logger.info("【L1 短期记忆】%d 条:", len(l1))
            for m in l1:
                logger.info("  L1[%s]: %s", m["role"], m["content"][:200])
        else:
            logger.info("【L1 短期记忆】无")

        logger.info("【记忆汇总】user_id=%d, L3=%s, L2=%d条, L1=%d条",
                     user_id, "有" if l3 else "无", len(l2_list), len(l1))
        return "\n\n".join(parts) if parts else ""

    # ── 对话结束后的记忆更新流程 ────────────────────────────────

    async def post_conversation_update(self, session_id: int, user_id: int) -> None:
        """对话结束后更新记忆：生成 Level 2 → 检查是否合并 Level 3"""
        if await self.should_generate_summary(session_id):
            await self.generate_session_summary(session_id, user_id)
            await self.check_and_merge_level3(user_id)

    # ── 数据清理 ──────────────────────────────────────────────

    async def cleanup_orphan_memories(self, user_id: int) -> int:
        """清理孤立的 L2 记忆（session_id 引用了不存在的 session）

        Returns:
            清理的记录数
        """
        # 获取用户所有 L2 记忆
        result = await self.db.execute(
            select(UserMemory)
            .where(UserMemory.user_id == user_id, UserMemory.level == 2)
        )
        l2_memories = list(result.scalars().all())

        # 获取所有存在的 session_id
        session_result = await self.db.execute(
            select(Session.id).where(Session.user_id == user_id)
        )
        existing_session_ids = set(row[0] for row in session_result.all())

        # 删除孤立记录
        cleaned = 0
        for mem in l2_memories:
            if mem.session_id and mem.session_id not in existing_session_ids:
                await self.db.delete(mem)
                cleaned += 1

        if cleaned > 0:
            await self.db.commit()
            logger.info("清理孤立 L2 记忆: user_id=%d, 清理 %d 条", user_id, cleaned)

        return cleaned
