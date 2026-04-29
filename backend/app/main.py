from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.api.v1.auth import router as auth_router
from app.api.v1.knowledge_base import router as kb_router
from app.api.v1.document import router as doc_router
from app.api.v1.chat import router as chat_router
from app.api.v1.session import router as session_router

settings = get_settings()

# 数据库引擎
engine = create_async_engine(settings.DATABASE_URL, echo=False, pool_size=10, max_overflow=20)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    yield
    await engine.dispose()


app = FastAPI(
    title="Ragent API",
    description="RAG 智能对话平台",
    version="0.1.0",
    lifespan=lifespan,
)

# 注册路由
app.include_router(auth_router)
app.include_router(kb_router)
app.include_router(doc_router)
app.include_router(chat_router)
app.include_router(session_router)

# CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "ok", "service": "ragent"}
