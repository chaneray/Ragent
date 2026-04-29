from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.user import User
from app.core.security import hash_password, verify_password, create_access_token
from app.schemas.auth import RegisterRequest, LoginRequest


class AuthService:
    """认证业务逻辑"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def register(self, req: RegisterRequest) -> User:
        """注册新用户"""
        # 检查用户名是否已存在
        result = await self.db.execute(select(User).where(User.username == req.username))
        if result.scalar_one_or_none():
            raise ValueError("用户名已被占用")

        # 检查邮箱是否已存在
        result = await self.db.execute(select(User).where(User.email == req.email))
        if result.scalar_one_or_none():
            raise ValueError("邮箱已被注册")

        # 创建用户
        user = User(
            username=req.username,
            email=req.email,
            hashed_password=hash_password(req.password),
        )
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)
        return user

    async def login(self, req: LoginRequest) -> str:
        """登录并返回 JWT Token（支持用户名或邮箱）"""
        # 判断输入的是用户名还是邮箱
        is_email = "@" in req.account
        if is_email:
            result = await self.db.execute(select(User).where(User.email == req.account))
        else:
            result = await self.db.execute(select(User).where(User.username == req.account))
        user = result.scalar_one_or_none()

        if not user or not verify_password(req.password, user.hashed_password):
            raise ValueError("用户名/邮箱或密码错误")

        return create_access_token(data={"sub": str(user.id)})

    async def get_user_by_id(self, user_id: int) -> User | None:
        """根据 ID 获取用户"""
        result = await self.db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()
