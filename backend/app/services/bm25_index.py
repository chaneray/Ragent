"""BM25 关键词检索索引

使用字符级分词（中文逐字 + 英文按词），不依赖 jieba。
对 BM25 关键词匹配场景足够用。
"""

import re
from rank_bm25 import BM25Okapi
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Chunk


def tokenize(text: str) -> list[str]:
    """中文逐字 + 英文按词 + 去标点"""
    text = text.lower()
    tokens = []
    # 英文单词
    for word in re.findall(r"[a-z0-9]+", text):
        tokens.append(word)
    # 中文字符（去掉标点）
    for ch in text:
        if "一" <= ch <= "鿿":
            tokens.append(ch)
    return tokens


class BM25Index:
    """单个知识库的 BM25 索引"""

    def __init__(self):
        self._corpus: list[str] = []
        self._chunk_ids: list[int] = []
        self._bm25: BM25Okapi | None = None

    @property
    def is_loaded(self) -> bool:
        return self._bm25 is not None

    def build(self, chunk_ids: list[int], texts: list[str]) -> None:
        """从 chunk 数据构建索引"""
        self._chunk_ids = chunk_ids
        self._corpus = texts
        tokenized = [tokenize(t) for t in texts]
        self._bm25 = BM25Okapi(tokenized)

    def search(self, query: str, top_k: int = 10) -> list[tuple[int, float]]:
        """检索，返回 (chunk_id, score) 列表"""
        if not self._bm25 or not self._corpus:
            return []
        tokens = tokenize(query)
        scores = self._bm25.get_scores(tokens)
        # 取 top_k
        ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)[:top_k]
        return [(self._chunk_ids[i], float(s)) for i, s in ranked if s > 0]


# 全局索引缓存：kb_id -> BM25Index
_indexes: dict[int, BM25Index] = {}


def get_index(kb_id: int) -> BM25Index:
    """获取知识库的 BM25 索引（不存在则创建空索引）"""
    if kb_id not in _indexes:
        _indexes[kb_id] = BM25Index()
    return _indexes[kb_id]


async def ensure_index_loaded(db: AsyncSession, kb_id: int) -> BM25Index:
    """确保索引已加载，未加载则从数据库构建"""
    idx = get_index(kb_id)
    if idx.is_loaded:
        return idx

    result = await db.execute(
        select(Chunk.id, Chunk.content).where(Chunk.knowledge_base_id == kb_id)
    )
    rows = result.all()
    if rows:
        chunk_ids = [r[0] for r in rows]
        texts = [r[1] for r in rows]
        idx.build(chunk_ids, texts)
    return idx


def rebuild_index(kb_id: int, chunk_ids: list[int], texts: list[str]) -> None:
    """重建指定知识库的 BM25 索引"""
    idx = BM25Index()
    idx.build(chunk_ids, texts)
    _indexes[kb_id] = idx


def invalidate_index(kb_id: int) -> None:
    """使索引失效，下次检索时重新加载"""
    _indexes.pop(kb_id, None)
