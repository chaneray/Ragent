from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse
from pydantic import BaseModel

from app.core.deps import get_db, get_current_user
from app.models.user import User
from app.models.session import Session
from app.models.knowledge_base import KnowledgeBase
from app.services.rag_service import RagService

router = APIRouter(prefix="/api/v1/chat", tags=["对话"])


class ChatRequest(BaseModel):
    question: str
    session_id: int
    knowledge_base_ids: list[str]


@router.post("/stream")
async def chat_stream(
    req: ChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """RAG 流式对话（SSE）"""
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="请输入问题")

    # 验证会话归属
    session_result = await db.execute(
        select(Session).where(Session.id == req.session_id, Session.user_id == current_user.id)
    )
    session = session_result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在或不属于当前用户")

    # 验证知识库归属（闲聊模式可不选知识库）
    for kb_id in req.knowledge_base_ids:
        kb_result = await db.execute(
            select(KnowledgeBase).where(KnowledgeBase.id == int(kb_id), KnowledgeBase.user_id == current_user.id)
        )
        if not kb_result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="知识库 %s 不存在或不属于当前用户" % kb_id)

    rag = RagService(db)

    async def event_generator():
        try:
            async for token in rag.chat_stream(
                question=req.question,
                session_id=req.session_id,
                kb_ids=req.knowledge_base_ids,
            ):
                yield {"event": "token", "data": token}
            yield {"event": "done", "data": ""}
        except Exception as e:
            yield {"event": "error", "data": str(e)}

    return EventSourceResponse(event_generator())
