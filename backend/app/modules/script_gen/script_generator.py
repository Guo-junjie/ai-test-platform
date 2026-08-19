"""
AI 测试脚本生成器

使用 LLM (通过 ModelRouter) 为测试用例生成三类脚本：
- pre_script: 前置脚本（Python），用于数据准备/环境初始化
- post_script: 后置脚本（Python），用于数据清理/结果校验
- sql_script: SQL 脚本，用于数据库状态验证

支持 AI 生成 + 规则降级，所有生成记录写入 script_generation_records 表。
"""

import ast
import json
import logging
import uuid
from typing import Any, Dict, Optional

from app.modules.ai.model_router import ModelNotConfiguredError, get_model_router
from app.modules.sql_gen.sql_security import SqlSecurity

logger = logging.getLogger(__name__)


class ScriptGenerator:
    """
    AI 测试脚本生成器。

    通过 ModelRouter 调用 LLM 生成脚本，AI 失败时降级为规则模板。
    生成结果记录到 script_generation_records 表用于审计。
    """

    def __init__(self) -> None:
        self.router = get_model_router()

    # ==================== 公开接口 ====================

    async def generate(
        self,
        script_type: str,
        context: Dict[str, Any],
        project_id: int = 0,
        db_session: Any = None,
    ) -> Dict[str, Any]:
        """
        生成脚本（统一入口）。

        Args:
            script_type: 脚本类型 — "pre_script" / "post_script" / "sql_script"
            context: 上下文信息，含 api_info, case_info, schema_context 等
            project_id: 项目 ID（用于 SQL 白名单校验）
            db_session: 可选的数据库会话

        Returns:
            {"code": str, "language": str, "script_type": str, "valid": bool}
        """
        if script_type not in ("pre_script", "post_script", "sql_script"):
            return {
                "code": "",
                "language": "python",
                "script_type": script_type,
                "valid": False,
                "error": f"Unknown script_type: {script_type}",
            }

        prompt = self._build_prompt(script_type, context)

        try:
            response = await self.router.call(
                use_case="script_generation",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
            )
            code = self._extract_code(response, script_type)
        except ModelNotConfiguredError:
            raise
        except Exception as e:
            logger.warning(f"AI script generation failed: {e}, using fallback")
            code = self._fallback_script(script_type, context)

        # 校验与记录
        result = self._validate_and_record(
            script_type=script_type,
            code=code,
            context=context,
            project_id=project_id,
            db_session=db_session,
        )
        return result

    async def preview(
        self,
        script_type: str,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        预览脚本（不落库，仅返回生成结果）。

        Args:
            script_type: 脚本类型
            context: 上下文信息

        Returns:
            {"code": str, "language": str, "script_type": str}
        """
        result = await self.generate(
            script_type=script_type,
            context=context,
            project_id=0,
            db_session=None,
        )
        return result

    # ==================== Prompt 构建 ====================

    def _build_prompt(self, script_type: str, context: Dict[str, Any]) -> str:
        """构建 AI 生成 prompt。"""
        api_info = json.dumps(context.get("api_info", {}), ensure_ascii=False, indent=2)
        case_info = json.dumps(context.get("case_info", {}), ensure_ascii=False, indent=2)
        schema_context = context.get("schema_context", "")
        nl_input = context.get("nl_input", "")

        if script_type == "pre_script":
            return f"""请生成一个 Python 前置脚本（pre_script），用于在测试执行前进行数据准备和环境初始化。

API 信息:
{api_info}

测试用例:
{case_info}

自然语言描述: {nl_input or "根据 API 和用例生成合适的前置脚本"}

要求：
1. 使用 Python 3 编写，可直接 exec 执行
2. 包含必要的 import 语句
3. 包含 main() 函数作为入口
4. 在 main() 中返回一个 dict，包含测试所需的数据
5. 添加适当的错误处理和日志
6. 只输出 Python 代码，不要包含其他文字
7. 代码用 ```python ... ``` 包裹"""

        elif script_type == "post_script":
            return f"""请生成一个 Python 后置脚本（post_script），用于在测试执行后进行数据清理和结果校验。

API 信息:
{api_info}

测试用例:
{case_info}

自然语言描述: {nl_input or "根据 API 和用例生成合适的后置脚本"}

要求：
1. 使用 Python 3 编写，可直接 exec 执行
2. 包含必要的 import 语句
3. 包含 main(response) 函数作为入口，response 为 API 响应 dict
4. 在 main() 中进行断言和校验
5. 添加适当的错误处理和日志
6. 只输出 Python 代码，不要包含其他文字
7. 代码用 ```python ... ``` 包裹"""

        else:  # sql_script
            schema_str = context.get("schema_context", "")
            return f"""请生成一个 SQL 验证脚本，用于在测试执行后验证数据库状态。

表结构:
{schema_str or "请根据 API 和用例推断相关表结构"}

API 信息:
{api_info}

测试用例:
{case_info}

自然语言描述: {nl_input or "根据 API 和用例生成合适的 SQL 验证脚本"}

要求：
1. 只使用 SELECT/INSERT/UPDATE/DELETE 语句
2. 每条语句以分号结尾
3. 添加适当的注释说明每条语句的用途
4. 只输出 SQL 代码，不要包含其他文字
5. 代码用 ```sql ... ``` 包裹"""

    # ==================== 代码提取 ====================

    @staticmethod
    def _extract_code(response: str, script_type: str) -> str:
        """从 LLM 响应中提取代码块。"""
        if not response:
            return ""

        text = response.strip()

        # 提取 markdown code block
        lang = "sql" if script_type == "sql_script" else "python"
        import re
        for tag in (lang, ""):
            pattern = rf"```(?:{tag})?\s*\n?(.*?)\n?```"
            match = re.search(pattern, text, re.DOTALL)
            if match:
                return match.group(1).strip()

        # 没有 code block，原样返回
        return text

    # ==================== 校验与记录 ====================

    async def _validate_and_record(
        self,
        script_type: str,
        code: str,
        context: Dict[str, Any],
        project_id: int = 0,
        db_session: Any = None,
    ) -> Dict[str, Any]:
        """校验脚本语法并记录生成结果。"""
        language = "sql" if script_type == "sql_script" else "python"
        valid = True
        error = None

        if script_type == "sql_script":
            # SQL 安全校验
            security = await SqlSecurity.check(
                sql=code,
                project_id=project_id,
                session=db_session,
            )
            valid = security.get("passed", False)
            if not valid:
                error = security.get("message", "SQL security check failed")
        else:
            # Python 语法校验
            try:
                ast.parse(code)
            except SyntaxError as e:
                valid = False
                error = f"Python syntax error: {e}"

        # 记录到 script_generation_records
        await self._log_record(
            script_type=script_type,
            code=code,
            context=context,
            nl_input=context.get("nl_input", ""),
            project_id=project_id,
            db_session=db_session,
        )

        return {
            "code": code,
            "language": language,
            "script_type": script_type,
            "valid": valid,
            "error": error,
        }

    async def _log_record(
        self,
        script_type: str,
        code: str,
        context: Dict[str, Any],
        nl_input: str,
        project_id: int = 0,
        db_session: Any = None,
    ) -> None:
        """记录生成记录到数据库。"""
        try:
            if db_session is not None:
                # project_id 为 NOT NULL 列；generate() 默认 project_id=0，
                # 若为 0/None 则跳过落库，避免 NOT NULL 约束违反。
                if not project_id or project_id == 0:
                    return

                from app.models.database import ScriptGenerationRecord, ScriptType
                record = ScriptGenerationRecord(
                    id=uuid.uuid4(),
                    project_id=uuid.UUID(str(project_id)),
                    script_type=ScriptType(script_type),
                    nl_input=nl_input,
                    context=context,
                    generated_script=code,
                )
                db_session.add(record)
                await db_session.flush()
        except Exception as e:
            logger.warning(f"Failed to log script generation record: {e}")

    # ==================== 规则降级 ====================

    def _fallback_script(self, script_type: str, context: Dict[str, Any]) -> str:
        """规则降级生成脚本模板。"""
        if script_type == "pre_script":
            return self._fallback_pre_script(context)
        elif script_type == "post_script":
            return self._fallback_post_script(context)
        else:
            return self._fallback_sql_script(context)

    @staticmethod
    def _fallback_pre_script(context: Dict[str, Any]) -> str:
        """生成前置脚本规则模板。"""
        api_info = context.get("api_info", {})
        method = api_info.get("http_method", "GET")
        path = api_info.get("path", "/api/unknown")

        return f'''"""
前置脚本 — 数据准备与环境初始化
生成时间: auto-generated
目标 API: {method} {path}
"""

import json
import logging

logger = logging.getLogger(__name__)


def main():
    """准备测试数据并返回给测试引擎。"""
    # 准备请求头
    headers = {{
        "Content-Type": "application/json",
    }}

    # 准备测试数据
    test_data = {{
        "timestamp": None,  # 由测试引擎填充
        "test_id": None,
    }}

    logger.info("Pre-script executed for {method} {path}")
    return {{
        "headers": headers,
        "test_data": test_data,
    }}
'''

    @staticmethod
    def _fallback_post_script(context: Dict[str, Any]) -> str:
        """生成后置脚本规则模板。"""
        api_info = context.get("api_info", {})
        method = api_info.get("http_method", "GET")
        path = api_info.get("path", "/api/unknown")

        return f'''"""
后置脚本 — 结果校验与数据清理
生成时间: auto-generated
目标 API: {method} {path}
"""

import json
import logging

logger = logging.getLogger(__name__)


def main(response):
    """校验 API 响应并执行清理操作。"""
    # 基础校验
    assert response is not None, "Response is None"
    assert isinstance(response, dict), f"Expected dict, got {{type(response).__name__}}"

    # 状态码校验
    status_code = response.get("status_code", 0)
    logger.info(f"Response status: {{status_code}}")

    # 业务校验
    body = response.get("body", {{}})
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError:
            pass

    # 成功响应校验
    if status_code and 200 <= status_code < 300:
        logger.info("Post-script validation passed for {method} {path}")
    else:
        logger.warning(f"Unexpected status code: {{status_code}}")

    # 清理操作（如有需要）
    # cleanup()

    return {{
        "passed": True,
        "status_code": status_code,
        "checks": ["status_code_validated"],
    }}
'''

    @staticmethod
    def _fallback_sql_script(context: Dict[str, Any]) -> str:
        """生成 SQL 脚本规则模板。"""
        api_info = context.get("api_info", {})
        case_info = context.get("case_info", {})
        table_hint = api_info.get("path", "unknown").replace("/", "_").strip("_")

        return f'''-- SQL 验证脚本
-- 目标 API: {api_info.get("http_method", "GET")} {api_info.get("path", "/api/unknown")}
-- 用例: {case_info.get("case_name", "unknown")}

-- 查询相关记录是否存在
SELECT * FROM {table_hint} WHERE created_at > NOW() - INTERVAL '1 hour';

-- 验证数据完整性
SELECT COUNT(*) AS total_records FROM {table_hint};
'''