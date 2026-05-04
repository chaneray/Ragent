"""精排服务：DashScope API 优先，CrossEncoder 降级，overlap 兜底"""

import logging
import time
from typing import Optional

from langchain_core.documents import Document as LCDocument

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


# ── DashScope SDK 精排（主策略） ─────────────────────────────

async def _rerank_dashscope(
    query: str,
    docs: list[LCDocument],
    top_k: int,
) -> Optional[list[LCDocument]]:
    """使用阿里云百炼 bge-reranker-v2-m3 模型精排"""
    api_key = settings.DASHSCOPE_API_KEY
    if not api_key:
        logger.info("DASHSCOPE_API_KEY 未配置，跳过 DashScope 精排")
        return None

    logger.info("使用 DashScope 精排，候选 %d 条", len(docs))
    start = time.time()

    try:
        from dashscope.rerank.text_rerank import TextReRank

        resp = TextReRank.call(
            model="bge-reranker-v2-m3",
            query=query,
            documents=[doc.page_content for doc in docs],
            top_n=min(top_k, len(docs)),
            return_documents=True,
            api_key=api_key,
        )

        # 检查响应状态
        if resp.status_code != 200:
            logger.warning("DashScope 精排 API 错误: code=%s, message=%s",
                           resp.code, resp.message)
            return None

        results = resp.output.results
        elapsed = (time.time() - start) * 1000

        reranked = []
        for item in results:
            idx = item.index
            score = item.relevance_score
            doc = LCDocument(
                page_content=docs[idx].page_content,
                metadata={**docs[idx].metadata, "rerank_score": score},
            )
            reranked.append(doc)

        logger.info("DashScope 精排完成，返回 %d 条，耗时 %.0fms", len(reranked), elapsed)
        for i, d in enumerate(reranked):
            logger.info("[DashScope精排] rank=%d, score=%.4f, content=%s",
                        i, d.metadata.get("rerank_score", 0), d.page_content[:100])
        return reranked

    except Exception as e:
        elapsed = (time.time() - start) * 1000
        logger.warning("DashScope 精排失败 (%.0fms): %s，降级到 CrossEncoder", elapsed, str(e))
        return None


# ── CrossEncoder 精排（降级策略） ─────────────────────────────

_cross_encoder = None


def _get_cross_encoder():
    """延迟加载 CrossEncoder 模型"""
    global _cross_encoder
    if _cross_encoder is not None:
        return _cross_encoder

    try:
        from sentence_transformers import CrossEncoder
        model_name = "BAAI/bge-reranker-base"
        logger.info("加载 CrossEncoder 模型: %s", model_name)
        _cross_encoder = CrossEncoder(model_name)
        return _cross_encoder
    except Exception as e:
        logger.warning("CrossEncoder 加载失败: %s", str(e))
        _cross_encoder = None
        return None


async def _rerank_cross_encoder(
    query: str,
    docs: list[LCDocument],
    top_k: int,
) -> Optional[list[LCDocument]]:
    """使用 sentence-transformers CrossEncoder 精排"""
    logger.info("使用 CrossEncoder 精排，候选 %d 条", len(docs))
    start = time.time()

    try:
        model = _get_cross_encoder()
        if model is None:
            return None

        pairs = [(query, doc.page_content) for doc in docs]
        scores = model.predict(pairs)

        scored_docs = []
        for doc, score in zip(docs, scores):
            scored_docs.append(LCDocument(
                page_content=doc.page_content,
                metadata={**doc.metadata, "rerank_score": float(score)},
            ))

        scored_docs.sort(key=lambda d: d.metadata["rerank_score"], reverse=True)
        result = scored_docs[:top_k]

        elapsed = (time.time() - start) * 1000
        logger.info("CrossEncoder 精排完成，返回 %d 条，耗时 %.0fms", len(result), elapsed)
        for i, d in enumerate(result):
            logger.info("[CrossEncoder精排] rank=%d, score=%.4f, content=%s",
                        i, d.metadata.get("rerank_score", 0), d.page_content[:100])
        return result

    except Exception as e:
        elapsed = (time.time() - start) * 1000
        logger.warning("CrossEncoder 精排失败 (%.0fms): %s，降级到 overlap 评分", elapsed, str(e))
        return None


# ── Overlap 评分（最终降级） ──────────────────────────────────

async def _rerank_overlap(
    query: str,
    docs: list[LCDocument],
    top_k: int,
) -> list[LCDocument]:
    """简单文本重叠评分（最终降级方案）"""
    logger.warning("精排降级到 overlap 评分，结果可能不准确，候选 %d 条", len(docs))

    query_chars = set(query)
    scored = []
    for doc in docs:
        doc_chars = set(doc.page_content)
        overlap = len(query_chars & doc_chars) / max(len(query_chars), 1)
        scored.append(LCDocument(
            page_content=doc.page_content,
            metadata={**doc.metadata, "rerank_score": overlap},
        ))

    scored.sort(key=lambda d: d.metadata["rerank_score"], reverse=True)
    return scored[:top_k]


# ── 主入口 ────────────────────────────────────────────────────

async def rerank(
    query: str,
    docs: list[LCDocument],
    top_k: int = 3,
    timeout: float = 10.0,
) -> list[LCDocument]:
    """精排主入口：DashScope → CrossEncoder → overlap

    Args:
        query: 用户查询
        docs: 候选文档列表
        top_k: 返回前 top_k 个
        timeout: 超时秒数（未使用，保留接口兼容）

    Returns:
        重排序后的文档列表，附带 rerank_score
    """
    if not docs:
        logger.info("精排：输入为空，跳过")
        return []

    if len(docs) == 1:
        logger.info("精排：仅 1 条候选，直接返回")
        docs[0].metadata["rerank_score"] = 1.0
        return docs

    logger.info("精排开始：query=%s, 候选 %d 条, top_k=%d", query[:50], len(docs), top_k)

    # 1. DashScope API
    result = await _rerank_dashscope(query, docs, top_k)
    if result is not None:
        return result

    # 2. CrossEncoder
    result = await _rerank_cross_encoder(query, docs, top_k)
    if result is not None:
        return result

    # 3. Overlap 兜底
    return await _rerank_overlap(query, docs, top_k)
