from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class CreateKnowledgeBaseRequest(BaseModel):
    name: str
    description: str = ""


class KnowledgeBaseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: Optional[str] = None
    document_count: int = 0
    chunk_count: int = 0
    created_at: datetime


class KnowledgeBaseListResponse(BaseModel):
    items: list[KnowledgeBaseResponse]
    total: int
