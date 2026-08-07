"""
AES-256 加密/解密工具 — 用于 API Key 等敏感信息加密存储

使用 cryptography 库的 Fernet 对称加密（AES-128-CBC + HMAC-SHA256）。
密钥从配置项 AES_ENCRYPTION_KEY 派生（SHA-256 → 32 字节 → base64 编码）。

提供：
- encrypt(plaintext: str) -> str: 加密明文，返回 base64 密文
- decrypt(ciphertext: str) -> str: 解密密文，返回明文
- encrypt_dict(data: dict) -> dict: 加密字典中的敏感字段
- mask_api_key(api_key: str) -> str: API Key 脱敏显示
"""

import base64
import hashlib
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from loguru import logger

from app.config import settings


# ==================== 密钥派生 ====================

def _derive_fernet_key() -> bytes:
    """
    从配置项 AES_ENCRYPTION_KEY 派生 Fernet 密钥。

    Fernet 要求 32 字节密钥经 base64url 编码。
    使用 SHA-256 对原始配置字符串进行哈希，确保输出固定 32 字节。

    Returns:
        base64 编码的 32 字节 Fernet 密钥。
    """
    raw_key = settings.AES_ENCRYPTION_KEY.encode("utf-8")
    digest = hashlib.sha256(raw_key).digest()
    return base64.urlsafe_b64encode(digest)


# ==================== Fernet 实例（惰性初始化） ====================

_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    """获取 Fernet 实例（单例）。"""
    global _fernet
    if _fernet is None:
        _fernet = Fernet(_derive_fernet_key())
    return _fernet


# ==================== 公开接口 ====================

def encrypt(plaintext: str) -> str:
    """
    加密明文字符串。

    Args:
        plaintext: 待加密的明文。

    Returns:
        base64 编码的密文字符串。

    Raises:
        ValueError: 明文为空时抛出。
    """
    if not plaintext:
        raise ValueError("Plaintext cannot be empty")
    fernet = _get_fernet()
    encrypted = fernet.encrypt(plaintext.encode("utf-8"))
    return encrypted.decode("utf-8")


def decrypt(ciphertext: str) -> str:
    """
    解密密文字符串。

    Args:
        ciphertext: encrypt() 返回的 base64 密文。

    Returns:
        解密后的明文字符串。

    Raises:
        ValueError: 密文为空或无效时抛出。
    """
    if not ciphertext:
        raise ValueError("Ciphertext cannot be empty")
    fernet = _get_fernet()
    try:
        decrypted = fernet.decrypt(ciphertext.encode("utf-8"))
        return decrypted.decode("utf-8")
    except InvalidToken as e:
        logger.error(f"Failed to decrypt ciphertext: invalid token")
        raise ValueError("Invalid ciphertext or wrong encryption key") from e


def encrypt_if_plaintext(value: str) -> str:
    """
    如果值是明文则加密，如果已是密文则原样返回。

    用于 API 更新场景：用户传入明文时加密，传入已有密文时不重复加密。

    Args:
        value: 可能是明文或密文的字符串。

    Returns:
        加密后的密文。
    """
    if not value:
        return value
    # 尝试解密，如果成功说明已经是密文
    try:
        decrypt(value)
        return value
    except (ValueError, InvalidToken):
        # 解密失败，说明是明文，进行加密
        return encrypt(value)


# ==================== 敏感字段处理 ====================

# 需要加密的字段名列表
SENSITIVE_FIELDS = frozenset({
    "api_key",
    "api_key_encrypted",
    "password",
    "secret",
    "token",
    "private_key",
    "access_key",
    "secret_key",
    "github_token",
    "svn_password",
})


def encrypt_dict(data: dict[str, Any]) -> dict[str, Any]:
    """
    加密字典中的敏感字段。

    遍历字典，对字段名匹配 SENSITIVE_FIELDS 的值进行加密。
    递归处理嵌套字典。

    Args:
        data: 原始字典。

    Returns:
        敏感字段已加密的字典副本。
    """
    result: dict[str, Any] = {}
    for key, value in data.items():
        if isinstance(value, dict):
            result[key] = encrypt_dict(value)
        elif isinstance(value, str) and key.lower() in SENSITIVE_FIELDS:
            result[key] = encrypt(value)
        else:
            result[key] = value
    return result


def decrypt_dict(data: dict[str, Any]) -> dict[str, Any]:
    """
    解密字典中的敏感字段。

    Args:
        data: 包含加密字段的字典。

    Returns:
        敏感字段已解密的字典副本。
    """
    result: dict[str, Any] = {}
    for key, value in data.items():
        if isinstance(value, dict):
            result[key] = decrypt_dict(value)
        elif isinstance(value, str) and key.lower() in SENSITIVE_FIELDS:
            try:
                result[key] = decrypt(value)
            except (ValueError, InvalidToken):
                # 解密失败，保留原值
                result[key] = value
        else:
            result[key] = value
    return result


# ==================== 脱敏显示 ====================

def mask_api_key(api_key: str, visible_prefix: int = 4, visible_suffix: int = 4) -> str:
    """
    API Key 脱敏显示，用于 API 返回时隐藏完整密钥。

    示例: "sk-abcdef1234567890" → "sk-a****7890"

    Args:
        api_key: 原始 API Key。
        visible_prefix: 保留前缀字符数。
        visible_suffix: 保留后缀字符数。

    Returns:
        脱敏后的字符串。
    """
    if not api_key:
        return ""
    if len(api_key) <= visible_prefix + visible_suffix:
        return "*" * len(api_key)
    prefix = api_key[:visible_prefix]
    suffix = api_key[-visible_suffix:]
    masked_length = len(api_key) - visible_prefix - visible_suffix
    return f"{prefix}{'*' * masked_length}{suffix}"
