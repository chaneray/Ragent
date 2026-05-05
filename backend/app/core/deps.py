import logging
from typing import AsyncGenerator, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import decode_access_token

logger = logging.getLogger(__name__)

settings = get_settings()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def get_session_factory():
    """获取数据库 session 工厂（用于后台任务创建独立 session）"""
    from app.main import AsyncSessionLocal
    return AsyncSessionLocal


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """数据库会话依赖注入（由 main.py 中的 engine 提供）"""
    from app.main import AsyncSessionLocal
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            logger.warning("数据库事务回滚")
            raise


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
):
    """从 JWT Token 获取当前用户"""
    payload = decode_access_token(token)
    if payload is None:
        logger.warning("认证失败: token 无效或已过期")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="登录凭证无效或已过期",
        )
    user_id: Optional[str] = payload.get("sub")
    if user_id is None:
        logger.warning("认证失败: token 中无 sub 字段")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="登录凭证无效",
        )
    from app.models.user import User
    from sqlalchemy import select

    result = await db.execute(select(User).where(User.id == int(user_id)))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在",
        )
    return user
