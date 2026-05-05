from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel, ConfigDict
from datetime import datetime
from typing import Optional

from app.core.deps import get_db, get_current_user
from app.models.user import User
from app.models.session import Session, Message
from app.models.memory import UserMemory
from app.services.memory_service import MemoryService

router = APIRouter(prefix="/api/v1/sessions", tags=["会话"])


class SessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    knowledge_base_ids: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class SessionListResponse(BaseModel):
    items: list[SessionResponse]
    total: int


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    session_id: int
    role: str
    content: str
    citations: Optional[str] = None
    created_at: datetime


class MessageListResponse(BaseModel):
    items: list[MessageResponse]


@router.post("", response_model=SessionResponse)
async def create_session(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建新会话"""
    session = Session(user_id=current_user.id)
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


@router.get("", response_model=SessionListResponse)
async def list_sessions(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取会话列表"""
    result = await db.execute(
        select(Session)
        .where(Session.user_id == current_user.id)
        .order_by(Session.updated_at.desc())
    )
    items = list(result.scalars().all())
    count = await db.execute(
        select(func.count()).select_from(Session).where(Session.user_id == current_user.id)
    )
    total = count.scalar() or 0
    return SessionListResponse(items=items, total=total)


@router.get("/{session_id}", response_model=MessageListResponse)
async def get_session_messages(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取会话消息历史"""
    # 验证会话归属
    result = await db.execute(
        select(Session).where(Session.id == session_id, Session.user_id == current_user.id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="会话不存在")

    result = await db.execute(
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.id)
    )
    items = list(result.scalars().all())
    return MessageListResponse(items=items)


@router.delete("/{session_id}")
async def delete_session(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除会话（级联删除 Message 和 L2 记忆）"""
    result = await db.execute(
        select(Session).where(Session.id == session_id, Session.user_id == current_user.id)
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")

    # 1. 删除该 Session 的 L2 记忆
    l2_result = await db.execute(
        select(UserMemory)
        .where(UserMemory.level == 2, UserMemory.session_id == session_id)
    )
    for mem in l2_result.scalars():
        await db.delete(mem)

    # 2. 删除 Session（级联删除 Message）
    await db.delete(session)
    await db.commit()
    return {"message": "会话已删除"}


@router.post("/cleanup")
async def cleanup_orphan_memories(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """清理孤立的 L2 记忆（session_id 引用了不存在的 session）"""
    memory_service = MemoryService(db)
    cleaned = await memory_service.cleanup_orphan_memories(current_user.id)
    return {"message": "清理完成", "cleaned": cleaned}
