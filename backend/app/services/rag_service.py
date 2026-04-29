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

settings = get_settings()
RAG_PROMPT_TEMPLATE = """你是一个基于知识库的智能问答助手。请根据以下检索到的资料回答用户问题。

如果检索到的资料不足以回答问题，请如实告知，不要编造信息。

检索到的资料：
{context}

对话历史：
{history}

用户问题：{question}

请用中文回答，并引用资料中的相关内容（在引用处标注 [来源: 文档名]）。"""


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

    async def _search_knowledge(self, question: str, kb_ids: list[str], top_k: int = 5) -> list[LCDocument]:
        """多知识库向量检索"""
        query_vector = await self.embeddings.aembed_query(question)
        all_docs = []

        for kb_id in kb_ids:
            # 获取知识库的 Milvus collection 名称
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
                                "kb_name": kb.name,
                                "document_id": hit["entity"].get("document_id", ""),
                                "score": hit["distance"],
                            }
                        ))
            except Exception:
                continue

        # 按相关性得分排序并去重
        all_docs.sort(key=lambda d: d.metadata.get("score", 0), reverse=True)
        return all_docs[:top_k]

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

        # 2. 向量检索
        docs = await self._search_knowledge(question, kb_ids)
        context = self._format_context(docs)

        # 3. 构建 Prompt
        prompt = RAG_PROMPT_TEMPLATE.format(
            context=context,
            history=history_text,
            question=question,
        )

        # 4. 流式生成
        full_answer = ""
        async for chunk in self.llm.astream(prompt):
            content = chunk.content if hasattr(chunk, "content") else str(chunk)
            full_answer += content
            yield content

        # 5. 保存消息到数据库
        citations = [{"content": d.page_content[:100], "source": d.metadata.get("kb_name", "")} for d in docs[:3]]
        self.db.add(Message(session_id=session_id, role="user", content=question))
        self.db.add(Message(
            session_id=session_id,
            role="assistant",
            content=full_answer,
            citations=json.dumps(citations, ensure_ascii=False),
        ))
        await self.db.commit()
