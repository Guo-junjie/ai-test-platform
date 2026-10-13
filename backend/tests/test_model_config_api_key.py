"""AI 模型配置密钥保存、脱敏和更新语义测试。"""

from app.api.model_config import (
    UpdateModelConfigRequest,
    _apply_api_key_update,
    _config_to_dict,
)
from app.models.database import AIModelConfig, ModelProvider
from app.utils.crypto import decrypt, encrypt


def _config(api_key: str = "sk-original-123456") -> AIModelConfig:
    return AIModelConfig(
        id="model-1",
        name="测试模型",
        provider=ModelProvider.OPENAI,
        api_base_url="https://example.test/v1",
        api_key_encrypted=encrypt(api_key),
        model_name="test-model",
        capabilities=["chat"],
    )


def test_model_config_response_only_contains_masked_key():
    config = _config()

    payload = _config_to_dict(config)

    assert "api_key" not in payload
    assert "api_key_encrypted" not in payload
    assert payload["api_key_configured"] is True
    assert payload["api_key_masked"].startswith("sk-o")
    assert payload["api_key_masked"].endswith("3456")
    assert "original" not in payload["api_key_masked"]


def test_omitted_api_key_keeps_existing_ciphertext():
    config = _config()
    original_ciphertext = config.api_key_encrypted

    changed = _apply_api_key_update(config, UpdateModelConfigRequest(name="只修改名称"))

    assert changed is False
    assert config.api_key_encrypted == original_ciphertext
    assert decrypt(config.api_key_encrypted) == "sk-original-123456"


def test_null_api_key_keeps_existing_ciphertext():
    config = _config()
    original_ciphertext = config.api_key_encrypted

    changed = _apply_api_key_update(config, UpdateModelConfigRequest(api_key=None))

    assert changed is False
    assert config.api_key_encrypted == original_ciphertext


def test_non_empty_api_key_replaces_existing_key():
    config = _config()

    changed = _apply_api_key_update(config, UpdateModelConfigRequest(api_key="sk-replaced-654321"))

    assert changed is True
    assert decrypt(config.api_key_encrypted) == "sk-replaced-654321"


def test_explicit_empty_api_key_clears_existing_key():
    config = _config()

    changed = _apply_api_key_update(config, UpdateModelConfigRequest(api_key=""))

    assert changed is True
    assert config.api_key_encrypted == ""
    payload = _config_to_dict(config)
    assert payload["api_key_configured"] is False
    assert payload["api_key_masked"] == ""
