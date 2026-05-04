"""用户记忆模型 — 层级摘要记忆"""

from datetime import datetime
from typing import Optional

from sqlalchemy import Integer, Text, ForeignKey, JSON, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class UserMemory(Base):
    __tablename__ = "user_memory"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("user.id"), nullable=False)
    session_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("session.id"), nullable=True)  # L2 关联会话
    level: Mapped[int] = mapped_column(Integer, nullable=False)  # 2=会话摘要, 3=用户画像
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source_sessions: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # L3 专用：来源会话列表
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
