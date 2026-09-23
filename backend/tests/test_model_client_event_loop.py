"""OpenAI 兼容客户端不得跨 Celery 的 asyncio.run 事件循环复用。"""

import asyncio
import sys
import types

from app.modules.ai.model_client import UnifiedModelClient
from app.modules.ai.model_config import ModelConfig, ModelProvider


class _Embedding:
    def __init__(self, values):
        self.embedding = values


class _FakeAsyncOpenAI:
    created = 0
    closed = 0

    def __init__(self, **_kwargs):
        type(self).created += 1
        self.embeddings = self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        type(self).closed += 1

    async def create(self, **_kwargs):
        return types.SimpleNamespace(data=[_Embedding([0.1, 0.2])])


def test_embedding_client_is_recreated_and_closed_for_each_event_loop(monkeypatch):
    _FakeAsyncOpenAI.created = 0
    _FakeAsyncOpenAI.closed = 0
    monkeypatch.setitem(
        sys.modules,
        "openai",
        types.SimpleNamespace(AsyncOpenAI=_FakeAsyncOpenAI),
    )
    client = UnifiedModelClient(ModelConfig(
        config_id="embedding",
        name="本地向量模型",
        provider=ModelProvider.LOCAL,
        api_base_url="http://embedding-service:8080/v1",
        api_key="local",
        model_name="test-embedding",
        capabilities=["embedding"],
    ))

    first = asyncio.run(client.embed(["第一次任务"]))
    second = asyncio.run(client.embed(["第二次任务"]))

    assert first == second == [[0.1, 0.2]]
    assert _FakeAsyncOpenAI.created == 2
    assert _FakeAsyncOpenAI.closed == 2
