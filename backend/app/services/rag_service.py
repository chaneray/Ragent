import json
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

settings = get_settings()

RAG_PROMPT_TEMPLATE = """你是一个基于知识库的智能问答助手。请根据以下检索到的资料回答用户问题。

如果检索到的资料不足以回答问题，请如实告知，不要编造信息。

检索到的资料：
{context}

对话历史：
{history}

用户问题：{question}

请用中文回答，并引用资料中的相关内容（在引用处标注 [来源: 文档名]）。"""

QUERY_REWRITE_PROMPT = """你是一个查询改写助手。请将用户的口语化问题改写为 2-3 个不同表述方式，使其更适合文档检索。

要求：
1. 保持原始问题的核心意图
2. 用更专业、更书面化的表述
3. 每个改写占一行，不要编号，不要其他内容

用户问题：{question}"""


class RagService:
    """RAG 检索与生成服务"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.llm = create_chat_model()
        self.embeddings = get_embedding_model()
        self.milvus = MilvusClient(host=settings.MILVUS_HOST, port=settings.MILVUS_PORT)

    async def _get_session_history(self, session_id: int, limit: int = 10) -> list[dict]:
        """获取最近的会话历史"""
        result = await self.db.execute(
            select(Message)
            .where(Message.session_id == session_id)
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
        messages = list(reversed(result.scalars().all()))
        return [{"role": m.role, "content": m.content} for m in messages]

    async def _rewrite_query(self, question: str) -> list[str]:
        """用 LLM 改写用户问题，生成多个表述"""
        try:
            prompt = QUERY_REWRITE_PROMPT.format(question=question)
            response = await self.llm.ainvoke(prompt)
            content = response.content if hasattr(response, "content") else str(response)
            queries = [q.strip() for q in content.strip().split("\n") if q.strip()]
            if not queries:
                return [question]
            return [question] + queries[:3]  # 原始问题 + 最多3个改写
        except Exception:
            return [question]

    async def _vector_search(self, query: str, kb_ids: list[str], top_k: int = 10) -> list[LCDocument]:
        """单次向量检索"""
        query_vector = await self.embeddings.aembed_query(query)
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
            except Exception:
                continue

        return all_docs

    async def _bm25_search(self, query: str, kb_ids: list[str], top_k: int = 10) -> list[LCDocument]:
        """BM25 关键词检索"""
        from app.models.document import Chunk
        from app.models.knowledge_base import KnowledgeBase

        all_docs = []

        for kb_id in kb_ids:
            kb_id_int = int(kb_id)
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

        return all_docs

    @staticmethod
    def _rrf_fusion(
        vector_docs: list[LCDocument],
        bm25_docs: list[LCDocument],
        k: int = 60,
        top_k: int = 15,
    ) -> list[LCDocument]:
        """RRF 融合排序

        RRF_score = 1/(k + rank_vector) + 1/(k + rank_bm25)
        """
        # 用内容 hash 去重
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

        # 计算 RRF 分数
        scored = []
        for key, doc in doc_map.items():
            v_rank = vector_ranks.get(key, len(vector_docs) + 100)
            b_rank = bm25_ranks.get(key, len(bm25_docs) + 100)
            rrf_score = 1.0 / (k + v_rank) + 1.0 / (k + b_rank)
            metadata = dict(doc.metadata)
            metadata["rrf_score"] = rrf_score
            scored.append(LCDocument(page_content=doc.page_content, metadata=metadata))

        scored.sort(key=lambda d: d.metadata["rrf_score"], reverse=True)
        return scored[:top_k]

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

    def _format_context(self, docs: list[LCDocument]) -> str:
        """格式化检索结果为上下文文本"""
        parts = []
        for i, doc in enumerate(docs):
            source = doc.metadata.get("kb_name", "未知")
            parts.append("[%d] (来源: %s)\n%s" % (i + 1, source, doc.page_content))
        return "\n\n".join(parts)

    def _format_history(self, history: list[dict]) -> str:
        """格式化会话历史"""
        lines = []
        for msg in history:
            role = "用户" if msg["role"] == "user" else "助手"
            lines.append("%s: %s" % (role, msg["content"]))
        return "\n".join(lines)

    async def chat_stream(
        self,
        question: str,
        session_id: int,
        kb_ids: list[str],
    ) -> AsyncGenerator[str, None]:
        """RAG 流式对话"""
        # 1. 获取会话历史
        history = await self._get_session_history(session_id)
        history_text = self._format_history(history)

        # 2. 查询改写
        queries = await self._rewrite_query(question)

        # 3. 混合检索（BM25 + 向量 + RRF）
        candidates = await self._hybrid_search(queries, kb_ids)

        # 4. Reranker 精排
        docs = await rerank(question, candidates, top_k=settings.RETRIEVAL_TOP_K)

        # 5. 构建 Prompt
        context = self._format_context(docs)
        prompt = RAG_PROMPT_TEMPLATE.format(
            context=context,
            history=history_text,
            question=question,
        )

        # 6. 流式生成
        full_answer = ""
        async for chunk in self.llm.astream(prompt):
            content = chunk.content if hasattr(chunk, "content") else str(chunk)
            full_answer += content
            yield content

        # 7. 保存消息到数据库
        citations = [{"content": d.page_content[:100], "source": d.metadata.get("kb_name", "")} for d in docs[:3]]
        self.db.add(Message(session_id=session_id, role="user", content=question))
        self.db.add(Message(
            session_id=session_id,
            role="assistant",
            content=full_answer,
            citations=json.dumps(citations, ensure_ascii=False),
        ))
        await self.db.commit()
