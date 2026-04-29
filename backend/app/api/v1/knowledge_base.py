import re
import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.deps import get_db, get_current_user
from app.models.user import User
from app.models.knowledge_base import KnowledgeBase
from app.schemas.knowledge_base import (
    CreateKnowledgeBaseRequest,
    KnowledgeBaseResponse,
    KnowledgeBaseListResponse,
)
from app.services.vector_store import create_collection, drop_collection

router = APIRouter(prefix="/api/v1/knowledge-bases", tags=["知识库"])


def _sanitize_collection_name(name: str) -> str:
    """确保 Milvus Collection 名称只包含字母、数字和下划线"""
    return re.sub(r"[^a-zA-Z0-9_]", "_", name)[:200]


@router.post("", response_model=KnowledgeBaseResponse)
async def create_knowledge_base(
    req: CreateKnowledgeBaseRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建知识库（自动创建 Milvus Collection）"""
    # 检查同名知识库
    result = await db.execute(
        select(KnowledgeBase).where(
            KnowledgeBase.name == req.name,
            KnowledgeBase.user_id == current_user.id,
        )
    )
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="同名的知识库已存在")

    # 创建 Milvus Collection
    collection_name = _sanitize_collection_name(f"kb_{current_user.id}_{req.name}_{uuid.uuid4().hex[:8]}")
    try:
        create_collection(collection_name)
    except Exception as e:
        raise HTTPException(status_code=500, detail="创建向量索引失败: %s" % str(e))

    # 写入数据库
    kb = KnowledgeBase(
        name=req.name,
        description=req.description,
        milvus_collection=collection_name,
        user_id=current_user.id,
    )
    db.add(kb)
    await db.commit()
    await db.refresh(kb)
    return kb


@router.get("", response_model=KnowledgeBaseListResponse)
async def list_knowledge_bases(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取知识库列表"""
    result = await db.execute(
        select(KnowledgeBase)
        .where(KnowledgeBase.user_id == current_user.id)
        .order_by(KnowledgeBase.created_at.desc())
    )
    items = list(result.scalars().all())
    count_result = await db.execute(
        select(func.count()).select_from(KnowledgeBase).where(KnowledgeBase.user_id == current_user.id)
    )
    total = count_result.scalar() or 0
    return KnowledgeBaseListResponse(items=items, total=total)


@router.get("/{kb_id}", response_model=KnowledgeBaseResponse)
async def get_knowledge_base(
    kb_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取知识库详情"""
    result = await db.execute(
        select(KnowledgeBase).where(
            KnowledgeBase.id == kb_id,
            KnowledgeBase.user_id == current_user.id,
        )
    )
    kb = result.scalar_one_or_none()
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")
    return kb


@router.delete("/{kb_id}")
async def delete_knowledge_base(
    kb_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除知识库（含 Milvus Collection）"""
    result = await db.execute(
        select(KnowledgeBase).where(
            KnowledgeBase.id == kb_id,
            KnowledgeBase.user_id == current_user.id,
        )
    )
    kb = result.scalar_one_or_none()
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")

    # 删除 Milvus Collection
    try:
        drop_collection(kb.milvus_collection)
    except Exception as e:
        raise HTTPException(status_code=500, detail="删除向量索引失败: %s" % str(e))

    await db.delete(kb)
    await db.commit()
    return {"message": "知识库已删除"}
