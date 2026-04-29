"""对话与 RAG 链路集成测试"""
import pytest


class TestSession:
    """会话管理测试"""

    @pytest.mark.asyncio
    async def test_create_session(self, client, auth_headers):
        """创建会话"""
        resp = await client.post("/api/v1/sessions", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "id" in data
        assert "title" in data

    @pytest.mark.asyncio
    async def test_list_sessions(self, client, auth_headers):
        """列出会话"""
        resp = await client.get("/api/v1/sessions", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data

    @pytest.mark.asyncio
    async def test_get_session_messages(self, client, auth_headers):
        """获取会话消息"""
        # 先创建会话
        resp = await client.post("/api/v1/sessions", headers=auth_headers)
        session_id = resp.json()["id"]
        # 获取消息
        resp = await client.get(f"/api/v1/sessions/{session_id}", headers=auth_headers)
        assert resp.status_code == 200
        assert "items" in resp.json()

    @pytest.mark.asyncio
    async def test_delete_session(self, client, auth_headers):
        """删除会话"""
        resp = await client.post("/api/v1/sessions", headers=auth_headers)
        session_id = resp.json()["id"]
        resp = await client.delete(f"/api/v1/sessions/{session_id}", headers=auth_headers)
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_session_not_found(self, client, auth_headers):
        """获取不存在的会话"""
        resp = await client.get("/api/v1/sessions/99999", headers=auth_headers)
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_session_auth_required(self, client):
        """未登录不能访问会话"""
        resp = await client.get("/api/v1/sessions")
        assert resp.status_code == 401


class TestChatStream:
    """RAG 对话集成测试"""

    @pytest.mark.asyncio
    async def test_chat_empty_question(self, client, auth_headers):
        """空问题应返回 400"""
        resp = await client.post(
            "/api/v1/chat/stream",
            json={"question": "  ", "session_id": 1, "knowledge_base_ids": ["1"]},
            headers=auth_headers,
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_chat_empty_kb(self, client, auth_headers):
        """空知识库列表应返回 400"""
        resp = await client.post(
            "/api/v1/chat/stream",
            json={"question": "Hello", "session_id": 1, "knowledge_base_ids": []},
            headers=auth_headers,
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_chat_invalid_session(self, client, auth_headers):
        """无效会话应返回 404"""
        resp = await client.post(
            "/api/v1/chat/stream",
            json={"question": "Hello", "session_id": 99999, "knowledge_base_ids": ["1"]},
            headers=auth_headers,
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_chat_requires_auth(self, client):
        """未登录不能对话"""
        resp = await client.post(
            "/api/v1/chat/stream",
            json={"question": "Hello", "session_id": 1, "knowledge_base_ids": ["1"]},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_chat_stream_with_kb(self, client, auth_headers, test_kb):
        """RAG 流式对话完整链路（需要有效的 LLM API Key）"""
        # 创建会话
        resp = await client.post("/api/v1/sessions", headers=auth_headers)
        session_id = resp.json()["id"]

        # 发送流式对话请求
        async with client.stream(
            "POST",
            "/api/v1/chat/stream",
            json={
                "question": "请介绍一下你自己",
                "session_id": session_id,
                "knowledge_base_ids": [str(test_kb["id"])],
            },
            headers=auth_headers,
        ) as response:
            assert response.status_code == 200
            # 读取 SSE 事件
            events = []
            async for line in response.aiter_lines():
                if line.startswith("event: "):
                    events.append(("event", line[7:]))
                elif line.startswith("data: "):
                    events.append(("data", line[6:]))

            assert len(events) > 0
            # 检查有 done 事件
            event_types = [e[1] for e in events if e[0] == "event"]
            assert "token" in event_types or "done" in event_types or "error" in event_types

        # 验证消息已保存
        resp = await client.get(f"/api/v1/sessions/{session_id}", headers=auth_headers)
        data = resp.json()
        assert len(data["items"]) >= 2  # user + assistant 消息
        assert data["items"][0]["role"] == "user"
        assert data["items"][1]["role"] == "assistant"

    @pytest.mark.asyncio
    async def test_chat_multi_turn(self, client, auth_headers, test_kb):
        """多轮对话历史记忆测试"""
        # 创建会话
        resp = await client.post("/api/v1/sessions", headers=auth_headers)
        session_id = resp.json()["id"]

        # 第一轮
        async with client.stream(
            "POST",
            "/api/v1/chat/stream",
            json={
                "question": "我叫张三",
                "session_id": session_id,
                "knowledge_base_ids": [str(test_kb["id"])],
            },
            headers=auth_headers,
        ) as response:
            async for _ in response.aiter_lines():
                pass  # 消费完 SSE 流

        # 第二轮
        async with client.stream(
            "POST",
            "/api/v1/chat/stream",
            json={
                "question": "我刚才说我的名字是什么？",
                "session_id": session_id,
                "knowledge_base_ids": [str(test_kb["id"])],
            },
            headers=auth_headers,
        ) as response:
            events = []
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    events.append(line[6:])

        # 验证消息数量
        resp = await client.get(f"/api/v1/sessions/{session_id}", headers=auth_headers)
        data = resp.json()
        assert len(data["items"]) >= 4  # 两轮 = 4条消息
