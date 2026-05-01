from datetime import datetime
from typing import Optional

from sqlalchemy import String, DateTime, Text, Integer, Boolean, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Session(Base):
    __tablename__ = "session"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(200), default="新对话")
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("user.id"), nullable=False)
    knowledge_base_ids: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    summary_generated: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    owner = relationship("User")
    messages: Mapped[list["Message"]] = relationship("Message", back_populates="session", order_by="Message.created_at")


class Message(Base):
    __tablename__ = "message"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(Integer, ForeignKey("session.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # user / assistant
    content: Mapped[str] = mapped_column(Text, nullable=False)
    citations: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON 格式引用来源
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    session = relationship("Session", back_populates="messages")
