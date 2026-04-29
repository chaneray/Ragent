from datetime import datetime
from typing import Optional

from sqlalchemy import String, DateTime, Text, Integer, ForeignKey, func, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
import enum

from app.models.base import Base


class DocumentStatus(str, enum.Enum):
    UPLOADED = "uploaded"         # 已上传
    PARSING = "parsing"           # 解析中
    CHUNKING = "chunking"         # 分块中
    EMBEDDING = "embedding"       # 向量化中
    INDEXED = "indexed"           # 已索引
    FAILED = "failed"             # 失败


class Document(Base):
    __tablename__ = "document"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    file_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    file_type: Mapped[str] = mapped_column(String(20), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)  # bytes
    status: Mapped[DocumentStatus] = mapped_column(
        SAEnum(DocumentStatus), default=DocumentStatus.UPLOADED, nullable=False
    )
    knowledge_base_id: Mapped[int] = mapped_column(Integer, ForeignKey("knowledge_base.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("user.id"), nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    knowledge_base = relationship("KnowledgeBase")
    owner = relationship("User")


class Chunk(Base):
    __tablename__ = "chunk"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(Integer, ForeignKey("document.id"), nullable=False)
    knowledge_base_id: Mapped[int] = mapped_column(Integer, ForeignKey("knowledge_base.id"), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON 格式元数据
    milvus_pk: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    document = relationship("Document")
    knowledge_base = relationship("KnowledgeBase")
