"""认证 API 测试"""
import pytest


class TestAuth:
    """认证相关测试"""

    @pytest.mark.asyncio
    async def test_register(self, client):
        """注册新用户"""
        import uuid
        uniq = uuid.uuid4().hex[:8]
        resp = await client.post(
            "/api/v1/auth/register",
            json={"username": f"newuser_{uniq}", "email": f"new_{uniq}@test.com", "password": "pass123456"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["username"].startswith("newuser_")
        assert "@test.com" in data["email"]
        assert "id" in data

    @pytest.mark.asyncio
    async def test_register_duplicate(self, client, test_user_data):
        """重复注册应返回 400"""
        resp = await client.post("/api/v1/auth/register", json=test_user_data)
        assert resp.status_code in (200, 400)  # 第一次可能成功，第二次必 400
        resp2 = await client.post("/api/v1/auth/register", json=test_user_data)
        assert resp2.status_code == 400

    @pytest.mark.asyncio
    async def test_login_by_username(self, client, auth_token):
        """用户名登录"""
        assert auth_token is not None
        assert len(auth_token) > 10

    @pytest.mark.asyncio
    async def test_login_by_email(self, client, test_user_data):
        """邮箱登录"""
        resp = await client.post(
            "/api/v1/auth/login",
            json={"account": test_user_data["email"], "password": test_user_data["password"]},
        )
        assert resp.status_code == 200
        assert "access_token" in resp.json()

    @pytest.mark.asyncio
    async def test_login_wrong_password(self, client, test_user_data):
        """错误密码"""
        resp = await client.post(
            "/api/v1/auth/login",
            json={"account": test_user_data["username"], "password": "wrongpassword"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_get_me(self, client, auth_headers):
        """获取当前用户信息"""
        resp = await client.get("/api/v1/auth/me", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "username" in data
        assert "email" in data

    @pytest.mark.asyncio
    async def test_get_me_no_token(self, client):
        """无 Token 获取用户信息"""
        resp = await client.get("/api/v1/auth/me")
        assert resp.status_code in (401, 403)
