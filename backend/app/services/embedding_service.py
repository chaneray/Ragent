from app.core.config import get_settings
from langchain_core.embeddings import Embeddings

settings = get_settings()


class FakeEmbeddings(Embeddings):
    """测试用虚拟嵌入，返回指定维度的零向量"""

    def __init__(self, dimension: int = 1024):
        self.dimension = dimension

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * self.dimension for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        return [0.0] * self.dimension


def get_embedding_model() -> Embeddings:
    """根据配置获取嵌入模型"""
    provider = settings.EMBEDDING_PROVIDER
    model = settings.EMBEDDING_MODEL

    # 未配置有效 API Key 时使用虚拟嵌入（本地测试）
    if not settings.OPENAI_API_KEY or "sk-your" in settings.OPENAI_API_KEY:
        dim = 1024 if model in ("text-embedding-v4", "text-embedding-v3") else 1536
        return FakeEmbeddings(dimension=dim)

    if provider == "dashscope":
        # 阿里云百炼平台（DashScope SDK）
        from langchain_community.embeddings import DashScopeEmbeddings
        return DashScopeEmbeddings(
            model=model,
            dashscope_api_key=settings.OPENAI_API_KEY,
        )
    elif provider == "openai":
        from langchain_openai import OpenAIEmbeddings
        if settings.OPENAI_BASE_URL:
            return OpenAIEmbeddings(model=model, base_url=settings.OPENAI_BASE_URL, api_key=settings.OPENAI_API_KEY)
        return OpenAIEmbeddings(model=model, api_key=settings.OPENAI_API_KEY)
    else:
        from langchain_openai import OpenAIEmbeddings
        return OpenAIEmbeddings(model=model, api_key=settings.OPENAI_API_KEY)
