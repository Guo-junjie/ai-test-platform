"""
代码脱敏器 — 在 AI 处理和展示前移除敏感信息

检测并脱敏：
- API Keys (sk-..., Bearer tokens)
- 密码赋值 (password = "xxx")
- 数据库连接字符串中的密码
- 私钥内容 (-----BEGIN ... PRIVATE KEY-----)
- AWS / Cloud 凭证
- 内网 IP 地址（可选）
- JWT tokens
- 邮箱地址（可选）
"""

import re
from typing import Any

from app.utils.logger import get_logger

logger = get_logger(__name__)


# ==================== 敏感信息正则模式 ====================

SENSITIVE_PATTERNS: list[tuple[str, re.Pattern, str]] = [
    # API Keys: sk-xxxxx, sk_live_xxxxx
    (
        "api_key",
        re.compile(
            r"(sk[-_]?(?:live|test)?[-_]?\w{0,10}[\"']?)([a-zA-Z0-9]{20,})",
            re.IGNORECASE,
        ),
        r"\1****REDACTED****",
    ),
    # Bearer tokens
    (
        "bearer_token",
        re.compile(
            r"(Bearer\s+)([a-zA-Z0-9\-._~+/]+=*)",
            re.IGNORECASE,
        ),
        r"\1****REDACTED****",
    ),
    # Password assignments: password = "xxx", passwd: "xxx"
    (
        "password",
        re.compile(
            r'((?:password|passwd|pwd|secret|api_key|apikey|access_token|auth_token)'
            r'\s*[:=]\s*["\']?)([^"\'\s,;}\)]{4,})',
            re.IGNORECASE,
        ),
        r"\1****REDACTED****",
    ),
    # Database connection strings with passwords
    (
        "db_connection",
        re.compile(
            r"(://[^:]+:)([^@]+)(@)",
            re.IGNORECASE,
        ),
        r"\1****REDACTED****\3",
    ),
    # Private keys (PEM format)
    (
        "private_key",
        re.compile(
            r"(-----BEGIN\s+\w+\s+PRIVATE\s+KEY-----)(.*?)(-----END\s+\w+\s+PRIVATE\s+KEY-----)",
            re.DOTALL,
        ),
        r"\1\n****REDACTED****\n\3",
    ),
    # AWS Access Key ID
    (
        "aws_key_id",
        re.compile(
            r"(AKIA|ASIA)[0-9A-Z]{16}",
        ),
        "****REDACTED_AWS_KEY****",
    ),
    # AWS Secret Access Key (40-char base64)
    (
        "aws_secret",
        re.compile(
            r'((?:aws_secret_access_key|secret_access_key)\s*[:=]\s*["\']?)([a-zA-Z0-9/+=]{40})',
            re.IGNORECASE,
        ),
        r"\1****REDACTED****",
    ),
    # JWT tokens (eyJ...)
    (
        "jwt_token",
        re.compile(
            r"eyJ[a-zA-Z0-9_-]{10,}\.eyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}",
        ),
        "****REDACTED_JWT****",
    ),
    # GitHub tokens (ghp_..., gho_..., ghs_...)
    (
        "github_token",
        re.compile(
            r"gh[pousr]_[a-zA-Z0-9]{36,}",
        ),
        "****REDACTED_GITHUB_TOKEN****",
    ),
]


# 可选脱敏模式（默认不启用，按需开启）
OPTIONAL_PATTERNS: list[tuple[str, re.Pattern, str]] = [
    # 内网 IP
    (
        "internal_ip",
        re.compile(
            r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
            r"|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}"
            r"|192\.168\.\d{1,3}\.\d{1,3})\b"
        ),
        "X.X.X.X",
    ),
    # 邮箱
    (
        "email",
        re.compile(
            r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b"
        ),
        "****@****.***",
    ),
]


class CodeSanitizer:
    """
    代码脱敏器。

    在代码/文本发送给 AI 模型处理或在报告中展示前，
    自动检测并脱敏敏感信息。
    """

    def __init__(
        self,
        enable_optional: bool = False,
        custom_patterns: list[tuple[str, re.Pattern, str]] | None = None,
    ) -> None:
        """
        初始化脱敏器。

        Args:
            enable_optional: 是否启用可选脱敏模式（内网 IP、邮箱）。
            custom_patterns: 自定义脱敏模式列表。
        """
        self.patterns: list[tuple[str, re.Pattern, str]] = list(SENSITIVE_PATTERNS)
        if enable_optional:
            self.patterns.extend(OPTIONAL_PATTERNS)
        if custom_patterns:
            self.patterns.extend(custom_patterns)

    def sanitize(self, text: str) -> str:
        """
        脱敏文本中的敏感信息。

        Args:
            text: 原始文本。

        Returns:
            脱敏后的文本。
        """
        if not text:
            return text

        sanitized = text
        for name, pattern, replacement in self.patterns:
            sanitized = pattern.sub(replacement, sanitized)

        return sanitized

    def sanitize_code(self, code: str, language: str = "") -> str:
        """
        脱敏源代码中的敏感信息。

        与 sanitize() 相同，但保留代码结构和注释。

        Args:
            code: 源代码字符串。
            language: 编程语言（用于特定语言的脱敏规则，当前预留）。

        Returns:
            脱敏后的源代码。
        """
        return self.sanitize(code)

    def sanitize_dict(self, data: dict[str, Any]) -> dict[str, Any]:
        """
        递归脱敏字典中的字符串值。

        Args:
            data: 原始字典。

        Returns:
            脱敏后的字典副本。
        """
        result: dict[str, Any] = {}
        for key, value in data.items():
            if isinstance(value, str):
                result[key] = self.sanitize(value)
            elif isinstance(value, dict):
                result[key] = self.sanitize_dict(value)
            elif isinstance(value, list):
                result[key] = [
                    self.sanitize_dict(item) if isinstance(item, dict)
                    else self.sanitize(item) if isinstance(item, str)
                    else item
                    for item in value
                ]
            else:
                result[key] = value
        return result

    def detect_secrets(self, text: str) -> list[dict[str, Any]]:
        """
        检测文本中的敏感信息（不脱敏，仅报告）。

        Args:
            text: 待检测的文本。

        Returns:
            检测到的敏感信息列表:
            [{"type": str, "start": int, "end": int, "preview": str}]
        """
        if not text:
            return []

        findings: list[dict[str, Any]] = []

        for name, pattern, _ in self.patterns:
            for match in pattern.finditer(text):
                findings.append({
                    "type": name,
                    "start": match.start(),
                    "end": match.end(),
                    "preview": text[max(0, match.start() - 10):match.end() + 10],
                })

        # 按位置排序
        findings.sort(key=lambda x: x["start"])
        return findings

    def has_secrets(self, text: str) -> bool:
        """快速判断文本是否包含敏感信息。"""
        return len(self.detect_secrets(text)) > 0


# ==================== 全局单例 ====================

_global_sanitizer: CodeSanitizer | None = None


def get_sanitizer() -> CodeSanitizer:
    """获取全局 CodeSanitizer 实例（单例）。"""
    global _global_sanitizer
    if _global_sanitizer is None:
        _global_sanitizer = CodeSanitizer()
    return _global_sanitizer


def sanitize_text(text: str) -> str:
    """便捷函数 — 使用全局脱敏器脱敏文本。"""
    return get_sanitizer().sanitize(text)


def sanitize_code(code: str, language: str = "") -> str:
    """便捷函数 — 使用全局脱敏器脱敏代码。"""
    return get_sanitizer().sanitize_code(code, language)
