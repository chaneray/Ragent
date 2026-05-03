import json
import logging
import re
from typing import AsyncGenerator

from langchain_core.documents import Document as LCDocument
from pymilvus import MilvusClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.session import Session, Message
from app.services.llm_factory import create_chat_model
from app.services.embedding_service import get_embedding_model
from app.services import bm25_index
from app.services.reranker_service import rerank
from app.services.prompts import (
    INTENT_PROMPT,
    INTENT_CHITCHAT,
    INTENT_COMPLEX_TASK,
    DEFAULT_INTENT,
    build_prompt,
)
from app.services.memory_service import MemoryService
from app.services.intent_service import IntentService

logger = logging.getLogger(__name__)
settings = get_settings()

QUERY_REWRITE_PROMPT = """你是一个查询改写助手。请将用户的口语化问题改写为 2-3 个不同表述方式，使其更适合文档检索。

要求：
1. 保持原始问题的核心意图
2. 用更专业、更书面化的表述
3. 每个改写占一行，不要编号，不要其他内容

用户问题：{question}"""


class RagService:
    """RAG 检索与生成服务（含意图识别 + 记忆注入）"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.llm = create_chat_model()
        self.embeddings = get_embedding_model()
        self.milvus = MilvusClient(host=settings.MILVUS_HOST, port=settings.MILVUS_PORT)
        self.memory_service = MemoryService(db)
        self.intent_service = IntentService(self.llm)

    # ── 意图识别 ──────────────────────────────────────────────

    async def _classify_intent(self, question: str) -> str:
        """用 LLM 对用户问题做意图分类"""
        try:
            prompt = INTENT_PROMPT.format(question=question)
            logger.debug("[意图识别] Prompt:\n%s", prompt)
            response = await self.llm.ainvoke(prompt)
            content = response.content if hasattr(response, "content") else str(response)
            logger.debug("[意图识别] LLM 返回: %s", content[:500])
            # 提取 JSON
            match = re.search(r'\{[^}]+\}', content)
            if match:
                data = json.loads(match.group())
                intent = data.get("intent", DEFAULT_INTENT)
                valid_intents = {"knowledge_qa", "chitchat", "summarize", "compare", "complex_task"}
                if intent in valid_intents:
                    logger.info("意图识别: intent=%s, question=%s", intent, question[:100])
                    return intent
            logger.info("意图识别: intent=%s (回退默认), question=%s", DEFAULT_INTENT, question[:100])
            return DEFAULT_INTENT
        except Exception as e:
            logger.warning("意图识别失败，使用默认意图: %s", str(e))
            return DEFAULT_INTENT

    # ── 会话历史 ──────────────────────────────────────────────

    async def _get_session_history(self, session_id: int, limit: int = 10) -> list[dict]:
        """获取最近的会话历史（保留兼容）"""
        result = await self.db.execute(
            select(Message)
            .where(Message.session_id == session_id)
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
        messages = list(reversed(result.scalars().all()))
        return [{"role": m.role, "content": m.content} for m in messages]

    # ── 查询改写 ──────────────────────────────────────────────

    async def _rewrite_query(self, question: str) -> list[str]:
        """用 LLM 改写用户问题，生成多个表述"""
        try:
            prompt = QUERY_REWRITE_PROMPT.format(question=question)
            logger.debug("[查询改写] Prompt:\n%s", prompt)
            response = await self.llm.ainvoke(prompt)
            content = response.content if hasattr(response, "content") else str(response)
            logger.debug("[查询改写] LLM 返回: %s", content[:500])
            queries = [q.strip() for q in content.strip().split("\n") if q.strip()]
            if not queries:
                return [question]
            result = [question] + queries[:3]
            logger.info("查询改写: 原始=%s, 改写结果=%s", question[:50], result)
            return result
        except Exception as e:
            logger.warning("查询改写失败，使用原始问题: %s", str(e))
            return [question]

    # 相关性阈值（rerank_score 低于此值视为不相关）
    RELEVANCE_THRESHOLD = 0.3

    # ── 检索相关 ──────────────────────────────────────────────

    async def _vector_search(self, query: str, kb_ids: list[str], top_k: int = 10) -> list[LCDocument]:
        """单次向量检索"""
        # 截断过长查询，避免嵌入 API 报错（DashScope text-embedding-v4 限制 3072 token）
        # 中文 1 字 ≈ 1.5 token，保守限制 1500 字符
        truncated_query = query[:1500]
        try:
            query_vector = await self.embeddings.aembed_query(truncated_query)
        except Exception as e:
            logger.warning("向量嵌入失败: %s", str(e))
            return []
        all_docs = []

        for kb_id in kb_ids:
            from app.models.knowledge_base import KnowledgeBase
            result = await self.db.execute(
                select(KnowledgeBase).where(KnowledgeBase.id == int(kb_id))
            )
            kb = result.scalar_one_or_none()
            if not kb:
                continue

            try:
                search_result = self.milvus.search(
                    collection_name=kb.milvus_collection,
                    data=[query_vector],
                    limit=top_k,
                    output_fields=["text", "document_id"],
                )
                for hits in search_result:
                    for hit in hits:
                        all_docs.append(LCDocument(
                            page_content=hit["entity"]["text"],
                            metadata={
                                "kb_id": kb.id,
                                "kb_name": kb.name,
                                "document_id": hit["entity"].get("document_id", ""),
                                "vector_score": hit["distance"],
                            }
                        ))
                logger.info("知识库 [%s] 向量检索完成，返回 %d 条结果", kb.name, len(search_result[0]) if search_result else 0)
                for i, hit in enumerate(search_result[0] if search_result else []):
                    logger.debug("[向量检索] kb=%s, rank=%d, score=%.4f, content=%s",
                                 kb.name, i, hit["distance"], hit["entity"]["text"][:200])
            except Exception as e:
                logger.warning("知识库 [%s] 向量检索失败: %s", kb.name, str(e))
                continue

        return all_docs

    async def _bm25_search(self, query: str, kb_ids: list[str], top_k: int = 10) -> list[LCDocument]:
        """BM25 关键词检索"""
        from app.models.document import Chunk
        from app.models.knowledge_base import KnowledgeBase

        all_docs = []

        for kb_id in kb_ids:
            kb_id_int = int(kb_id)
            try:
                idx = await bm25_index.ensure_index_loaded(self.db, kb_id_int)
                results = idx.search(query, top_k=top_k)

                for chunk_id, score in results:
                    result = await self.db.execute(
                        select(Chunk.content, Chunk.knowledge_base_id).where(Chunk.id == chunk_id)
                    )
                    row = result.first()
                    if row:
                        kb_result = await self.db.execute(
                            select(KnowledgeBase.name).where(KnowledgeBase.id == kb_id_int)
                        )
                        kb_name = kb_result.scalar() or "未知"
                        all_docs.append(LCDocument(
                            page_content=row[0],
                            metadata={
                                "kb_id": kb_id_int,
                                "kb_name": kb_name,
                                "bm25_score": score,
                            }
                        ))
                        logger.debug("[BM25检索] kb_id=%d, chunk_id=%d, score=%.4f, content=%s",
                                     kb_id_int, chunk_id, score, row[0][:200])
                logger.info("知识库 [%s] BM25 检索完成，返回 %d 条结果", kb_id_int, len(results))
            except Exception as e:
                logger.warning("知识库 [%s] BM25 检索失败: %s", kb_id_int, str(e))

        return all_docs

    @staticmethod
    def _rrf_fusion(
        vector_docs: list[LCDocument],
        bm25_docs: list[LCDocument],
        k: int = 60,
        top_k: int = 15,
    ) -> list[LCDocument]:
        """RRF 融合排序"""
        doc_map: dict[str, LCDocument] = {}
        vector_ranks: dict[str, int] = {}
        bm25_ranks: dict[str, int] = {}

        for rank, doc in enumerate(vector_docs):
            key = doc.page_content[:200]
            doc_map[key] = doc
            vector_ranks[key] = rank

        for rank, doc in enumerate(bm25_docs):
            key = doc.page_content[:200]
            if key not in doc_map:
                doc_map[key] = doc
            bm25_ranks[key] = rank

        scored = []
        for key, doc in doc_map.items():
            v_rank = vector_ranks.get(key, len(vector_docs) + 100)
            b_rank = bm25_ranks.get(key, len(bm25_docs) + 100)
            rrf_score = 1.0 / (k + v_rank) + 1.0 / (k + b_rank)
            metadata = dict(doc.metadata)
            metadata["rrf_score"] = rrf_score
            scored.append(LCDocument(page_content=doc.page_content, metadata=metadata))

        scored.sort(key=lambda d: d.metadata["rrf_score"], reverse=True)
        result = scored[:top_k]
        logger.info("RRF 融合: 向量 %d 条 + BM25 %d 条 -> 融合后 %d 条 (取 top %d)",
                     len(vector_docs), len(bm25_docs), len(scored), top_k)
        for i, d in enumerate(result):
            logger.debug("[RRF融合] rank=%d, rrf_score=%.4f, kb=%s, content=%s",
                         i, d.metadata.get("rrf_score", 0), d.metadata.get("kb_name", ""), d.page_content[:200])
        return result

    async def _hybrid_search(self, queries: list[str], kb_ids: list[str]) -> list[LCDocument]:
        """混合检索：多查询 × 双路召回 + RRF 融合"""
        all_vector_docs = []
        all_bm25_docs = []

        for query in queries:
            vec_docs = await self._vector_search(query, kb_ids, top_k=10)
            all_vector_docs.extend(vec_docs)

            bm25_docs = await self._bm25_search(query, kb_ids, top_k=10)
            all_bm25_docs.extend(bm25_docs)

        return self._rrf_fusion(all_vector_docs, all_bm25_docs, top_k=15)

    # ── 格式化 ────────────────────────────────────────────────

    def _format_context(self, docs: list[LCDocument]) -> str:
        """格式化检索结果为上下文文本"""
        parts = []
        for i, doc in enumerate(docs):
            source = doc.metadata.get("kb_name", "未知")
            parts.append("[%d] (来源: %s)\n%s" % (i + 1, source, doc.page_content))
        return "\n\n".join(parts)

    # ── 主流程 ────────────────────────────────────────────────

    async def chat_stream(
        self,
        question: str,
        session_id: int,
        kb_ids: list[str],
        intent: str = None,
    ) -> AsyncGenerator[str, None]:
        """RAG 流式对话（含意图识别 + 记忆注入）

        Args:
            question: 用户问题
            session_id: 会话 ID
            kb_ids: 知识库 ID 列表
            intent: 可选：用户指定的意图（用于澄清后跳过意图识别）
        """
        # 获取用户 ID
        session_result = await self.db.execute(
            select(Session).where(Session.id == session_id)
        )
        session = session_result.scalar_one_or_none()
        user_id = session.user_id if session else 0

        # 1. 意图识别（如果用户指定了意图，跳过意图识别）
        if intent:
            logger.info("使用用户指定的意图: %s（跳过意图识别）", intent)
            intent_result = None
        else:
            intent_result = await self.intent_service.classify(question, session_id, self.db)
            intent = intent_result.intent

            # 2. 处理澄清
            if intent_result.needs_clarification and intent_result.confidence < 0.7:
                logger.info("触发意图澄清: confidence=%.2f, question=%s", intent_result.confidence, question[:50])
                # 使用 LLM 返回的澄清选项，如果没有则使用默认选项
                options = intent_result.clarification_options if intent_result.clarification_options else [
                    "查询知识库",
                    "闲聊",
                    "总结归纳",
                    "对比分析",
                    "复杂任务",
                ]
                clarification_data = {
                    "event": "clarification",
                    "data": {
                        "question": intent_result.clarification_question or "请明确您的问题意图",
                        "options": options,
                        "original_question": question,
                    },
                }
                yield json.dumps(clarification_data, ensure_ascii=False)
                return

        # 3. 读取记忆
        memory_context = await self.memory_service.build_memory_context(user_id, session_id)
        logger.info("=" * 60)
        logger.info("【记忆系统】用户ID=%d, 会话ID=%d", user_id, session_id)
        logger.info("记忆上下文长度: %d 字符", len(memory_context))
        if memory_context:
            logger.info("记忆内容:\n%s", memory_context)
        else:
            logger.info("记忆内容: 空")
        logger.info("=" * 60)

        # 4. 根据意图路由
        if intent == INTENT_CHITCHAT:
            # 闲聊：不走检索，直接生成
            prompt = build_prompt(
                intent=intent,
                question=question,
                memory_context=memory_context,
            )
            docs = []
        elif intent == INTENT_COMPLEX_TASK:
            # 复杂任务：路由到 Agent
            from app.services.agent_service import AgentService
            agent = AgentService(self.db)
            full_answer = ""
            async for token in agent.execute(question, session_id, kb_ids):
                full_answer += token
                yield token
            # 保存消息
            self.db.add(Message(session_id=session_id, role="user", content=question))
            self.db.add(Message(session_id=session_id, role="assistant", content=full_answer))
            await self.db.commit()
            # 触发记忆更新
            await self.memory_service.post_conversation_update(session_id, user_id)
            return
        else:
            # knowledge_qa / summarize / compare：走检索
            queries = await self._rewrite_query(question)
            logger.info("=" * 60)
            logger.info("【RAG 检索】查询改写结果: %s", queries)
            candidates = await self._hybrid_search(queries, kb_ids)
            logger.info("【RAG 检索】混合检索召回 %d 条候选", len(candidates))
            docs = await rerank(question, candidates, top_k=settings.RETRIEVAL_TOP_K)
            logger.info("【RAG 检索】Rerank 精排完成，返回 %d 条结果", len(docs))
            for i, d in enumerate(docs):
                logger.info("[Rerank] rank=%d, score=%.4f, kb=%s, content=%s",
                             i, d.metadata.get("rerank_score", 0), d.metadata.get("kb_name", ""), d.page_content[:200])
            # 过滤低相关性结果：rerank_score < 阈值则丢弃
            if docs and any("rerank_score" in d.metadata for d in docs):
                before_count = len(docs)
                docs = [d for d in docs if d.metadata.get("rerank_score", 0) >= self.RELEVANCE_THRESHOLD]
                if len(docs) < before_count:
                    logger.info("【RAG 检索】相关性过滤: %d -> %d 条 (阈值 %.2f)", before_count, len(docs), self.RELEVANCE_THRESHOLD)
            logger.info("=" * 60)
            if not docs:
                # 检索无相关结果，回退到闲聊模式，让 LLM 用自身知识回答
                intent = INTENT_CHITCHAT
                prompt = build_prompt(
                    intent=intent,
                    question=question,
                    memory_context=memory_context,
                )
            else:
                context = self._format_context(docs)
                prompt = build_prompt(
                    intent=intent,
                    question=question,
                    context=context,
                    memory_context=memory_context,
                )

        # 5. 流式生成
        logger.info("=" * 60)
        logger.info("【系统提示词】intent=%s, 长度 %d 字符", intent, len(prompt))
        logger.info("完整 Prompt:\n%s", prompt)
        logger.info("=" * 60)
        full_answer = ""
        try:
            async for chunk in self.llm.astream(prompt):
                content = chunk.content if hasattr(chunk, "content") else str(chunk)
                full_answer += content
                yield content
        except Exception as e:
            error_msg = "生成回答时出错: %s" % str(e)[:200]
            logger.error("LLM 生成失败: %s", str(e))
            yield error_msg
            full_answer = error_msg
        logger.info("=" * 60)
        logger.info("【LLM 回复】长度 %d 字符", len(full_answer))
        logger.info("完整回复:\n%s", full_answer)
        logger.info("=" * 60)

        # 6. 保存消息到数据库
        citations = [
            {"content": d.page_content[:100], "source": d.metadata.get("kb_name", "")}
            for d in docs[:3]
        ]
        self.db.add(Message(session_id=session_id, role="user", content=question))
        self.db.add(Message(
            session_id=session_id,
            role="assistant",
            content=full_answer,
            citations=json.dumps(citations, ensure_ascii=False),
        ))
        await self.db.commit()

        # 7. 对话结束后触发记忆更新
        await self.memory_service.post_conversation_update(session_id, user_id)
