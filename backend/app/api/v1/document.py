import os
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.deps import get_db, get_current_user
from app.core.config import get_settings
from app.models.user import User
from app.models.knowledge_base import KnowledgeBase
from app.models.document import Document, DocumentStatus
from app.schemas.document import DocumentResponse, DocumentListResponse
from app.services.document_loader import save_uploaded_file
from app.services.ingestion import IngestionService

router = APIRouter(prefix="/api/v1/documents", tags=["文档"])
settings = get_settings()
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}


@router.post("/upload", response_model=DocumentResponse)
async def upload_document(
    file: UploadFile = File(...),
    knowledge_base_id: int = Form(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """上传文档并触发入库流水线"""
    # 校验文件类型
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="不支持的文件类型，仅支持 PDF/DOCX/TXT/MD")

    # 校验知识库归属
    result = await db.execute(
        select(KnowledgeBase).where(
            KnowledgeBase.id == knowledge_base_id,
            KnowledgeBase.user_id == current_user.id,
        )
    )
    kb = result.scalar_one_or_none()
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")

    # 保存文件
    content = await file.read()
    if len(content) > settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024:
        raise HTTPException(status_code=400, detail="文件大小超过限制（%dMB）" % settings.MAX_UPLOAD_SIZE_MB)

    file_path = save_uploaded_file(knowledge_base_id, current_user.id, file.filename or "unnamed", content)

    # 创建文档记录
    doc = Document(
        filename=os.path.basename(file_path),
        original_filename=file.filename or "unnamed",
        file_path=file_path,
        file_type=ext[1:],
        file_size=len(content),
        status=DocumentStatus.UPLOADED,
        knowledge_base_id=knowledge_base_id,
        user_id=current_user.id,
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)

    # 异步触发入库（当前同步执行，后期可改为后台任务）
    try:
        service = IngestionService(db)
        await service.process_document(doc.id)
    except Exception as e:
        raise HTTPException(status_code=500, detail="文档处理失败: %s" % str(e))

    return doc


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    knowledge_base_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取知识库下的文档列表"""
    result = await db.execute(
        select(Document).where(
            Document.knowledge_base_id == knowledge_base_id,
            Document.user_id == current_user.id,
        ).order_by(Document.created_at.desc())
    )
    items = list(result.scalars().all())
    count_result = await db.execute(
        select(func.count()).select_from(Document).where(
            Document.knowledge_base_id == knowledge_base_id,
            Document.user_id == current_user.id,
        )
    )
    total = count_result.scalar() or 0
    return DocumentListResponse(items=items, total=total)


@router.delete("/{document_id}")
async def delete_document(
    document_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除文档"""
    result = await db.execute(
        select(Document).where(
            Document.id == document_id,
            Document.user_id == current_user.id,
        )
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")

    # 删除本地文件
    try:
        if os.path.exists(doc.file_path):
            os.remove(doc.file_path)
    except OSError:
        pass

    await db.delete(doc)
    await db.commit()
    return {"message": "文档已删除"}
