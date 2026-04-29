"""测试配置与共享 Fixture"""
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from app.main import app


@pytest.fixture(scope="session")
def event_loop():
    """创建 session 级别的事件循环"""
    import asyncio
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """HTTP 测试客户端"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def test_user_data():
    """测试用户数据"""
    return {"username": "testuser_pytest", "email": "pytest@test.com", "password": "test123456"}


@pytest_asyncio.fixture
async def auth_token(client: AsyncClient, test_user_data: dict) -> str:
    """获取测试用户的 JWT Token（自动注册+登录）"""
    await client.post("/api/v1/auth/register", json=test_user_data)
    resp = await client.post(
        "/api/v1/auth/login",
        json={"account": test_user_data["username"], "password": test_user_data["password"]},
    )
    data = resp.json()
    return data["access_token"]


@pytest_asyncio.fixture
async def auth_headers(auth_token: str) -> dict:
    """带认证的请求头"""
    return {"Authorization": f"Bearer {auth_token}"}


@pytest_asyncio.fixture
async def test_kb(client: AsyncClient, auth_headers: dict) -> dict:
    """创建测试知识库并返回数据"""
    import uuid
    name = f"pytest-kb-{uuid.uuid4().hex[:6]}"
    resp = await client.post(
        "/api/v1/knowledge-bases",
        json={"name": name, "description": "pytest knowledge base"},
        headers=auth_headers,
    )
    data = resp.json()
    return data
