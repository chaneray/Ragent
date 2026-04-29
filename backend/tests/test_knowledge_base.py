"""知识库 API 测试"""
import pytest


class TestKnowledgeBase:
    """知识库 CRUD 测试"""

    @pytest.mark.asyncio
    async def test_create_kb(self, client, auth_headers):
        """创建知识库"""
        import uuid
        name = f"my-kb-{uuid.uuid4().hex[:6]}"
        resp = await client.post(
            "/api/v1/knowledge-bases",
            json={"name": name, "description": "test kb"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == name
        assert data["document_count"] == 0
        assert data["chunk_count"] == 0
        assert "id" in data

    @pytest.mark.asyncio
    async def test_create_duplicate_kb(self, client, auth_headers, test_kb):
        """创建同名知识库应返回 400"""
        resp = await client.post(
            "/api/v1/knowledge-bases",
            json={"name": test_kb["name"], "description": ""},
            headers=auth_headers,
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_list_kb(self, client, auth_headers):
        """列出知识库"""
        resp = await client.get("/api/v1/knowledge-bases", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data
        assert isinstance(data["items"], list)

    @pytest.mark.asyncio
    async def test_get_kb(self, client, auth_headers, test_kb):
        """获取知识库详情"""
        resp = await client.get(
            f"/api/v1/knowledge-bases/{test_kb['id']}", headers=auth_headers
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == test_kb["name"]

    @pytest.mark.asyncio
    async def test_get_kb_not_found(self, client, auth_headers):
        """获取不存在的知识库"""
        resp = await client.get("/api/v1/knowledge-bases/99999", headers=auth_headers)
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_kb(self, client, auth_headers):
        """删除知识库"""
        # 先创建一个
        resp = await client.post(
            "/api/v1/knowledge-bases",
            json={"name": "to-delete", "description": ""},
            headers=auth_headers,
        )
        kb_id = resp.json()["id"]
        # 再删除
        resp = await client.delete(f"/api/v1/knowledge-bases/{kb_id}", headers=auth_headers)
        assert resp.status_code == 200
        # 确认已删除
        resp = await client.get(f"/api/v1/knowledge-bases/{kb_id}", headers=auth_headers)
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_auth_required(self, client):
        """未登录不能访问知识库"""
        resp = await client.get("/api/v1/knowledge-bases")
        assert resp.status_code == 401
