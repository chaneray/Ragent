"""DashScope Reranker 重排服务

使用阿里云百炼 gte-rerank 模型对检索结果精排。
"""

import logging

import httpx
from langchain_core.documents import Document as LCDocument

from app.core.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

DASHSCOPE_RERANK_URL = "https://dashscope.aliyuncs.com/api/v1/services/reranker/text-reranking/text-reranking"


async def rerank(
    query: str,
    docs: list[LCDocument],
    top_k: int = 5,
    timeout: float = 3.0,
) -> list[LCDocument]:
    """对文档列表进行重排序

    Args:
        query: 用户查询
        docs: 候选文档列表
        top_k: 返回前 top_k 个
        timeout: 超时秒数

    Returns:
        重排序后的文档列表，附带 rerank_score
    """
    if not docs:
        return []

    api_key = settings.OPENAI_API_KEY
    if not api_key or "sk-your" in api_key:
        return docs[:top_k]

    documents_text = [doc.page_content for doc in docs]

    payload = {
        "model": "gte-rerank",
        "input": {
            "query": query,
            "documents": documents_text,
        },
        "parameters": {
            "top_n": min(top_k, len(docs)),
            "return_documents": False,
        },
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        logger.info("Rerank 调用: query=%s, docs=%d, top_k=%d", query[:50], len(docs), top_k)
        for i, doc in enumerate(docs):
            logger.debug("[Rerank输入] idx=%d, kb=%s, content=%s", i, doc.metadata.get("kb_name", ""), doc.page_content[:200])
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                DASHSCOPE_RERANK_URL,
                json=payload,
                headers=headers,
                timeout=timeout,
            )
            resp.raise_for_status()
            data = resp.json()

        results = data.get("output", {}).get("results", [])
        reranked = []
        for item in results:
            idx = item["index"]
            score = item["relevance_score"]
            doc = LCDocument(
                page_content=docs[idx].page_content,
                metadata={**docs[idx].metadata, "rerank_score": score},
            )
            reranked.append(doc)
        logger.info("Rerank 完成: 返回 %d 条结果", len(reranked))
        for i, doc in enumerate(reranked):
            logger.debug("[Rerank输出] rank=%d, score=%.4f, kb=%s, content=%s",
                         i, doc.metadata.get("rerank_score", 0), doc.metadata.get("kb_name", ""), doc.page_content[:200])
        return reranked

    except Exception as e:
        # 降级：跳过重排，返回原始顺序
        logger.warning("Rerank 调用失败，降级返回原始顺序: %s", str(e))
        return docs[:top_k]
