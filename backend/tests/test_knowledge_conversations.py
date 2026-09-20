"""知识问答持久化会话与多轮上下文回归测试。"""

from unittest.mock import AsyncMock

import pytest

from app.api.knowledge import _conversation_title
from app.models.database import KnowledgeConversation, KnowledgeMessage
from app.modules.knowledge import qa


def test_conversation_title_is_compact_and_bounded():
    assert _conversation_title("  登录接口   怎么测试？ ") == "登录接口 怎么测试？"
    assert len(_conversation_title("问题" * 50)) == 41


def test_conversation_models_define_owner_and_message_sequence():
    assert KnowledgeConversation.__table__.c.user_id.nullable is False
    assert KnowledgeMessage.__table__.c.conversation_id.nullable is False
    assert any(
        constraint.name == "uq_knowledge_message_sequence"
        for constraint in KnowledgeMessage.__table__.constraints
    )


@pytest.mark.asyncio
async def test_follow_up_question_uses_recent_history_for_retrieval_and_model(monkeypatch):
    retrieval = AsyncMock(return_value=[{
        "kb_type": "document",
        "source_ref": "doc:1",
        "source": "登录测试规范",
        "score": 0.9,
        "content": "登录接口需要验证密码错误和账户锁定。",
    }])
    monkeypatch.setattr(qa, "_retrieve_for_qa", retrieval)

    class FakeRouter:
        def __init__(self):
            self.messages = []

        async def call(self, use_case, messages, **kwargs):
            self.messages = messages
            return "应覆盖账户锁定场景 [1]"

    router = FakeRouter()
    monkeypatch.setattr("app.modules.ai.model_router.get_model_router", lambda: router)
    history = [
        {"role": "user", "content": "登录接口需要测试什么？"},
        {"role": "assistant", "content": "需要覆盖认证与异常场景。"},
    ]

    result = await qa.ask_knowledge(
        AsyncMock(),
        "那密码错误呢？",
        project_id=None,
        top_k=5,
        history=history,
    )

    retrieval_query = retrieval.await_args.args[1]
    assert "登录接口需要测试什么" in retrieval_query
    assert "那密码错误呢" in retrieval_query
    assert router.messages[1:3] == history
    assert result["answer"] == "应覆盖账户锁定场景 [1]"
