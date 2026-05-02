"""Agent 规划模块

当意图识别为 complex_task 时，进入 Agent 模式：
1. LLM 拆解为子任务
2. 按顺序执行每个子任务（调用工具）
3. 汇总所有结果生成最终回答

安全限制：
- 最大循环 5 次
- 每次检索 top_k=3
- 超时 30 秒强制结束
"""

import json
import logging
import re
import time
from typing import AsyncGenerator

logger = logging.getLogger(__name__)

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.session import Message
from app.models.document import Chunk
from app.models.knowledge_base import KnowledgeBase
from app.services.llm_factory import create_chat_model
from app.services.embedding_service import get_embedding_model
from app.services import bm25_index
from pymilvus import MilvusClient
from app.core.config import get_settings

settings = get_settings()

MAX_ITERATIONS = 5
TIMEOUT_SECONDS = 30
SEARCH_TOP_K = 3

AGENT_SYSTEM_PROMPT = """你是一个推理助手，擅长分步骤解决复杂问题。

你可以使用以下工具：
- search_knowledge: 在知识库中搜索相关信息，输入为搜索查询
- read_document: 读取指定文档的完整内容，输入为文档 ID
- get_chunk_detail: 查看某个分片的详细内容，输入为分片 ID

当需要使用工具时，返回 JSON 格式：
{{"action": "工具名", "input": "输入内容"}}

当你已经收集到足够的信息，可以直接回答时，返回：
{{"action": "finish", "answer": "你的最终答案"}}

要求：
1. 分步骤推理，每步只用一个工具
2. 基于工具返回的结果继续推理
3. 不要编造信息，如果信息不足请如实说明
4. 最终答案用中文，引用相关内容"""

AGENT_ITERATION_PROMPT = """当前任务：{question}

已收集的信息：
{accumulated_info}

请决定下一步操作。如果信息足够，直接返回最终答案。"""


class AgentService:
    """Agent 规划与执行服务"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.llm = create_chat_model()
        self.embeddings = get_embedding_model()
        self.milvus = MilvusClient(host=settings.MILVUS_HOST, port=settings.MILVUS_PORT)

    async def _execute_tool(self, action: str, tool_input: str, kb_ids: list[str]) -> str:
        """执行单个工具调用"""
        if action == "search_knowledge":
            return await self._tool_search(tool_input, kb_ids)
        elif action == "read_document":
            return await self._tool_read_document(tool_input)
        elif action == "get_chunk_detail":
            return await self._tool_get_chunk(tool_input)
        else:
            return "未知工具: %s" % action

    async def _tool_search(self, query: str, kb_ids: list[str]) -> str:
        """搜索知识库"""
        all_results = []
        truncated_query = query[:3000]
        try:
            query_vector = await self.embeddings.aembed_query(truncated_query)
        except Exception:
            return "嵌入查询失败"

        for kb_id in kb_ids:
            kb_id_int = int(kb_id)
            result = await self.db.execute(
                select(KnowledgeBase).where(KnowledgeBase.id == kb_id_int)
            )
            kb = result.scalar_one_or_none()
            if not kb:
                continue

            # 向量检索
            try:
                search_result = self.milvus.search(
                    collection_name=kb.milvus_collection,
                    data=[query_vector],
                    limit=SEARCH_TOP_K,
                    output_fields=["text", "document_id"],
                )
                for hits in search_result:
                    for hit in hits:
                        all_results.append(
                            "[来源: %s] %s" % (kb.name, hit["entity"]["text"])
                        )
            except Exception:
                pass

            # BM25 检索
            try:
                idx = await bm25_index.ensure_index_loaded(self.db, kb_id_int)
                bm25_results = idx.search(query, top_k=SEARCH_TOP_K)
                for chunk_id, score in bm25_results:
                    chunk_result = await self.db.execute(
                        select(Chunk.content).where(Chunk.id == chunk_id)
                    )
                    content = chunk_result.scalar()
                    if content:
                        all_results.append("[来源: %s, BM25] %s" % (kb.name, content))
            except Exception:
                pass

        if not all_results:
            return "未找到相关信息"
        return "\n---\n".join(all_results[:SEARCH_TOP_K * 2])

    async def _tool_read_document(self, doc_id_str: str) -> str:
        """读取文档完整内容"""
        try:
            doc_id = int(doc_id_str.strip())
        except ValueError:
            return "无效的文档 ID: %s" % doc_id_str

        result = await self.db.execute(
            select(Chunk).where(Chunk.document_id == doc_id).order_by(Chunk.chunk_index)
        )
        chunks = list(result.scalars().all())
        if not chunks:
            return "文档不存在或无内容"
        return "\n\n".join(c.content for c in chunks)

    async def _tool_get_chunk(self, chunk_id_str: str) -> str:
        """获取分片详情"""
        try:
            chunk_id = int(chunk_id_str.strip())
        except ValueError:
            return "无效的分片 ID: %s" % chunk_id_str

        result = await self.db.execute(select(Chunk).where(Chunk.id == chunk_id))
        chunk = result.scalar_one_or_none()
        if not chunk:
            return "分片不存在"
        return chunk.content

    def _parse_action(self, content: str) -> tuple[str, str]:
        """解析 LLM 返回的动作 JSON"""
        # 清洗 LLM 输出：去掉 <thinking> 标签和首尾空白
        cleaned = re.sub(r'<thinking>.*?</thinking>', '', content, flags=re.DOTALL).strip()
        # 去掉常见的 "Done!" 等无意义后缀
        cleaned = re.sub(r'\s*Done!\s*$', '', cleaned).strip()
        try:
            match = re.search(r'\{[^}]+\}', cleaned, re.DOTALL)
            if match:
                data = json.loads(match.group())
                action = data.get("action", "")
                if action == "finish":
                    answer = data.get("answer", "").strip()
                    if answer:
                        return "finish", answer
                    # answer 为空时，尝试从原始内容中提取非 JSON 部分作为答案
                    non_json = re.sub(r'\{[^}]*\}', '', cleaned, flags=re.DOTALL).strip()
                    if non_json and len(non_json) > 10:
                        return "finish", non_json
                    return "finish", ""
                return action, data.get("input", "")
        except Exception:
            pass
        # JSON 解析失败，将整个清洗后内容作为答案
        if cleaned and len(cleaned) > 5:
            return "finish", cleaned
        return "finish", content

    async def execute(
        self,
        question: str,
        session_id: int,
        kb_ids: list[str],
    ) -> AsyncGenerator[str, None]:
        """执行 Agent 循环，流式输出最终答案"""
        logger.info("Agent 模式启动: question=%s, kb_ids=%s", question[:100], kb_ids)
        start_time = time.time()
        accumulated_info = ""

        for iteration in range(MAX_ITERATIONS):
            # 超时检查
            if time.time() - start_time > TIMEOUT_SECONDS:
                yield "\n\n[Agent 超时，已停止推理]"
                break

            # 构建迭代 prompt
            iteration_prompt = AGENT_ITERATION_PROMPT.format(
                question=question,
                accumulated_info=accumulated_info if accumulated_info else "暂无",
            )
            full_prompt = AGENT_SYSTEM_PROMPT + "\n\n" + iteration_prompt
            logger.debug("[Agent 迭代 %d] Prompt:\n%s", iteration + 1, full_prompt[:1000])

            # LLM 决策
            try:
                response = await self.llm.ainvoke(full_prompt)
                content = response.content if hasattr(response, "content") else str(response)
                logger.debug("[Agent 迭代 %d] LLM 返回: %s", iteration + 1, content[:500])
            except Exception as e:
                yield "\n\n[Agent 调用 LLM 失败: %s]" % str(e)
                break

            # 解析动作
            action, action_input = self._parse_action(content)
            logger.info("Agent 迭代 %d: action=%s, input=%s", iteration + 1, action, action_input[:100] if action_input else "")

            if action == "finish":
                # 最终答案
                if action_input:
                    yield action_input
                else:
                    # 答案为空，用 LLM 重新生成
                    fallback = "请直接回答用户的问题，不要使用工具，不要返回 JSON，直接用中文回答：\n%s" % question
                    try:
                        resp = await self.llm.ainvoke(fallback)
                        ans = resp.content if hasattr(resp, "content") else str(resp)
                        yield re.sub(r'<thinking>.*?</thinking>', '', ans, flags=re.DOTALL).strip()
                    except Exception:
                        yield "抱歉，我无法回答这个问题。"
                break

            # 执行工具
            tool_result = await self._execute_tool(action, action_input, kb_ids)
            logger.info("Agent 工具执行完成: tool=%s, result_preview=%s", action, tool_result[:200])
            accumulated_info += "\n\n[第%d步 %s(%s)]\n%s" % (
                iteration + 1, action, action_input, tool_result
            )

        else:
            # 循环耗尽，用已有信息生成回答
            fallback_prompt = "根据以下信息回答问题：\n%s\n\n问题：%s" % (
                accumulated_info, question
            )
            try:
                response = await self.llm.ainvoke(fallback_prompt)
                content = response.content if hasattr(response, "content") else str(response)
                yield content
            except Exception:
                yield "抱歉，推理过程未能得出结论。"

        # 保存消息（Agent 模式下单独保存）
        # 注意：这里不保存，由调用方（rag_service）处理
