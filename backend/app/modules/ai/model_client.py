"""
统一 AI 模型客户端
支持任意 OpenAI 兼容 API（OpenAI 官方、Azure OpenAI、私有 vLLM/Ollama、国产模型等），
也支持非兼容的自定义 HTTP API 和 Anthropic Claude API。
"""

import json
import httpx
from loguru import logger
from typing import Optional

from app.modules.ai.model_config import ModelConfig, ModelProvider


class UnifiedModelClient:
    """统一 AI 模型客户端"""

    def __init__(self, config: ModelConfig):
        self.config = config
        self._client = None

        if config.provider == ModelProvider.OPENAI:
            try:
                from openai import AsyncOpenAI
                self._client = AsyncOpenAI(
                    api_key=config.api_key,
                    base_url=config.api_base_url,
                    timeout=config.timeout,
                    max_retries=config.max_retries,
                )
            except ImportError:
                logger.warning("openai package not installed, using httpx fallback")

    async def chat(
        self,
        messages: list[dict],
        response_format_json: bool = False,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        """统一的对话接口"""
        temp = temperature if temperature is not None else self.config.temperature
        max_tok = max_tokens or self.config.max_tokens

        if self.config.provider == ModelProvider.OPENAI:
            return await self._call_openai(messages, temp, max_tok, response_format_json)
        elif self.config.provider == ModelProvider.ANTHROPIC:
            return await self._call_anthropic(messages, temp, max_tok)
        elif self.config.provider == ModelProvider.CUSTOM:
            return await self._call_custom_api(messages, temp, max_tok)
        else:
            raise ValueError(f"Unsupported provider: {self.config.provider}")

    async def _call_openai(
        self, messages: list[dict], temp: float, max_tok: int, json_mode: bool
    ) -> str:
        """调用 OpenAI 兼容 API"""
        if self._client:
            kwargs = {
                "model": self.config.model_name,
                "messages": messages,
                "temperature": temp,
                "max_tokens": max_tok,
            }
            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}

            response = await self._client.chat.completions.create(**kwargs)
            return response.choices[0].message.content
        else:
            # httpx fallback
            return await self._call_openai_httpx(messages, temp, max_tok, json_mode)

    async def _call_openai_httpx(
        self, messages: list[dict], temp: float, max_tok: int, json_mode: bool
    ) -> str:
        """使用 httpx 调用 OpenAI 兼容 API（无需 openai 包）"""
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.config.model_name,
            "messages": messages,
            "temperature": temp,
            "max_tokens": max_tok,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        url = f"{self.config.api_base_url.rstrip('/')}/chat/completions"
        async with httpx.AsyncClient(timeout=self.config.timeout) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]

    async def _call_anthropic(self, messages: list[dict], temp: float, max_tok: int) -> str:
        """调用 Anthropic Claude API"""
        system_msg = ""
        user_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system_msg += msg["content"] + "\n"
            else:
                user_messages.append(msg)

        headers = {
            "x-api-key": self.config.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.config.model_name,
            "messages": user_messages,
            "max_tokens": max_tok,
            "temperature": temp,
        }
        if system_msg:
            payload["system"] = system_msg.strip()

        url = f"{self.config.api_base_url.rstrip('/')}/v1/messages"
        async with httpx.AsyncClient(timeout=self.config.timeout) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
            return data["content"][0]["text"]

    async def _call_custom_api(self, messages: list[dict], temp: float, max_tok: int) -> str:
        """调用自定义 HTTP API（非 OpenAI 兼容格式）"""
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.config.model_name,
            "messages": messages,
            "temperature": temp,
            "max_tokens": max_tok,
        }

        async with httpx.AsyncClient(timeout=self.config.timeout) as client:
            response = await client.post(
                self.config.api_base_url, json=payload, headers=headers
            )
            response.raise_for_status()
            data = response.json()
            # 尝试多种常见响应格式
            if "choices" in data:
                return data["choices"][0]["message"]["content"]
            elif "content" in data:
                return data["content"][0]["text"] if isinstance(data["content"], list) else data["content"]
            elif "output" in data:
                return data["output"]
            else:
                return json.dumps(data)
