from pymilvus import MilvusClient

from app.core.config import get_settings

settings = get_settings()
# text-embedding-v4 (DashScope) = 1024; text-embedding-3-small (OpenAI) = 1536
VECTOR_DIM = 1024 if settings.EMBEDDING_PROVIDER == "dashscope" else 1536


def get_milvus_client() -> MilvusClient:
    """获取 Milvus 客户端"""
    return MilvusClient(host=settings.MILVUS_HOST, port=settings.MILVUS_PORT)


def create_collection(collection_name: str) -> None:
    """创建知识库对应的 Milvus Collection"""
    client = get_milvus_client()
    if client.has_collection(collection_name):
        return

    client.create_collection(
        collection_name=collection_name,
        dimension=VECTOR_DIM,
        primary_field_name="id",
        vector_field_name="vector",
        auto_id=True,
        enable_dynamic_field=True,
        metric_type="IP",  # 内积相似度
    )


def drop_collection(collection_name: str) -> None:
    """删除 Milvus Collection"""
    client = get_milvus_client()
    if client.has_collection(collection_name):
        client.drop_collection(collection_name)


def collection_exists(collection_name: str) -> bool:
    """检查 Collection 是否存在"""
    client = get_milvus_client()
    return client.has_collection(collection_name)
