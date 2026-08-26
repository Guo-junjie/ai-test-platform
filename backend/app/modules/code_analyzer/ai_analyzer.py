"""
AI 语义分析增强器

使用 LLM (通过 ModelRouter) 对代码项目进行深度语义分析：
1. 为每个 API 生成业务逻辑分析（批量，限制并发数）
2. 划分业务模块
3. 分析模块依赖关系
4. 标注风险区域

返回标准化的 ai_analysis 对象，作为后续用例生成和环境适配的输入。
"""

import asyncio
import json
import re
from pathlib import Path
from typing import Any

from app.modules.ai.model_router import ModelNotConfiguredError, get_model_router
from app.utils.logger import get_logger

logger = get_logger(__name__)

# AI 分析的 API 数量上限（避免过多 API 调用）
_MAX_AI_ANALYSIS_APIS = 20
# 并发调用 AI 的最大并发数
_MAX_CONCURRENT_AI_CALLS = 5
# 单个 API 代码片段读取的最大字符数
_CODE_SNIPPET_MAX_CHARS = 2000

# 规则化分析扫描的源码扩展名
_RULE_SCAN_EXT = {
    ".py", ".java", ".kt", ".go", ".js", ".jsx", ".ts", ".tsx", ".php", ".vue",
}
_RULE_SKIP_DIRS = {
    "node_modules", ".git", "__pycache__", ".venv", "venv",
    "env", ".idea", ".vscode", "dist", "build", "target",
}

# 风险规则：(标签, 正则, 严重级别)。用于无 AI 模型时的规则化兜底分析。
_RISK_RULES: list[tuple[str, "re.Pattern[str]", str]] = [
    ("动态执行 eval/exec", re.compile(r"\b(?:eval|exec)\s*\("), "high"),
    (
        "命令注入风险",
        re.compile(r"(?:os\.system|subprocess|os\.popen|child_process|execSync|shell_exec|system\()"),
        "high",
    ),
    (
        "SQL 拼接（注入风险）",
        re.compile(r"(?:execute\(|raw\(|cursor\.execute|query\(|SELECT|INSERT|UPDATE|DELETE).*?(?:\%|f[\"\']|\.format|\+)"),
        "high",
    ),
    (
        "硬编码密钥/口令",
        re.compile(r"(?:password|passwd|secret|api_key|apikey|token)\s*=\s*[\"\'][^\"\']{4,}[\"\']"),
        "medium",
    ),
    (
        "不安全反序列化",
        re.compile(r"(?:pickle\.loads|yaml\.load|unserialize|jsonpickle)"),
        "medium",
    ),
    ("裸 except / 空 catch", re.compile(r"except\s*:|catch\s*\([^)]*\)\s*\{\s*\}"), "low"),
    ("调试接口/日志泄露", re.compile(r"(?:/debug|/actuator|print\(|console\.log\()"), "low"),
]


class AICodeAnalyzer:
    """
    使用 LLM 进行深度代码语义分析。

    通过 ModelRouter 调用 AI 模型，分析每个 API 接口的业务逻辑，
    并汇总为业务模块、数据流、风险区域等结构化分析结果。
    """

    def __init__(self) -> None:
        self.router = get_model_router()

    async def analyze_project(
        self,
        project_path: str,
        apis: list[dict[str, Any]],
        stack_info: dict[str, Any],
    ) -> dict[str, Any]:
        """
        对整个项目进行 AI 语义分析。

        流程：
        1. 如果 API 数量 > 20，只取前 20 个做 AI 分析（避免过多 API 调用）
        2. 对每个 API 读取其源文件对应行附近的代码片段
        3. 并发调用 analyze_api()（限制并发数为 5）
        4. 汇总分析结果，按业务域聚合成 business_modules
        5. 分析模块依赖关系
        6. 标注风险区域

        Args:
            project_path: 项目根目录路径。
            apis: APIExtractor.extract() 返回的接口列表。
            stack_info: StackDetector.detect() 返回的技术栈信息。

        Returns:
            包含 business_modules / data_flow / risk_areas / api_analyses 的字典。
        """
        if not apis:
            logger.warning("No APIs to analyze, returning empty analysis")
            return {
                "business_modules": [],
                "data_flow": {},
                "risk_areas": [],
                "api_analyses": [],
            }

        # 限制 AI 分析的 API 数量
        apis_to_analyze = apis[:_MAX_AI_ANALYSIS_APIS]
        if len(apis) > _MAX_AI_ANALYSIS_APIS:
            logger.info(
                f"Too many APIs ({len(apis)}), only analyzing first "
                f"{_MAX_AI_ANALYSIS_APIS} with AI"
            )

        # 读取每个 API 对应的代码片段
        code_snippets = self._read_code_snippets(project_path, apis_to_analyze)

        # 并发调用 AI 分析（限制并发数）
        semaphore = asyncio.Semaphore(_MAX_CONCURRENT_AI_CALLS)

        async def analyze_with_semaphore(
            api: dict[str, Any], snippet: str
        ) -> dict[str, Any]:
            async with semaphore:
                try:
                    return await self.analyze_api(api, snippet)
                except ModelNotConfiguredError:
                    raise
                except Exception as e:
                    logger.warning(
                        f"AI analysis failed for API {api.get('path', 'unknown')}: {e}"
                    )
                    return {
                        "path": api.get("path", ""),
                        "http_method": api.get("http_method", ""),
                        "business_purpose": "Analysis failed",
                        "key_validations": [],
                        "business_rules": [],
                        "expected_responses": [],
                        "dependencies": [],
                        "risk_points": [f"AI analysis error: {str(e)}"],
                    }

        tasks = [
            analyze_with_semaphore(api, snippet)
            for api, snippet in zip(apis_to_analyze, code_snippets)
        ]
        api_analyses = await asyncio.gather(*tasks)

        # 汇总业务模块
        business_modules = self._aggregate_business_modules(api_analyses)

        # 分析模块依赖关系
        data_flow = self._analyze_data_flow(business_modules, api_analyses)

        # 标注风险区域
        risk_areas = self._identify_risk_areas(api_analyses)

        logger.info(
            f"AI analysis completed: {len(api_analyses)} APIs analyzed, "
            f"{len(business_modules)} business modules, "
            f"{len(risk_areas)} risk areas"
        )

        return {
            "business_modules": business_modules,
            "data_flow": data_flow,
            "risk_areas": risk_areas,
            "api_analyses": api_analyses,
        }

    def rule_based_analysis(
        self,
        project_path: str,
        apis: list[dict[str, Any]],
        stack_info: dict[str, Any],
    ) -> dict[str, Any]:
        """
        规则化兜底分析（无 AI 模型可用时使用）。

        不调用 LLM，直接扫描源码做风险模式识别，并按文件聚合业务模块，
        保证即使离线也能返回可用的分析结果。

        Args:
            project_path: 项目根目录路径。
            apis: APIExtractor.extract() 返回的代码单元列表。
            stack_info: StackDetector.detect() 返回的技术栈信息。

        Returns:
            与 analyze_project 同结构的标准化字典。
        """
        root = Path(project_path)

        # 1. 按文件聚合业务模块
        modules_map: dict[str, dict[str, Any]] = {}
        for api in apis:
            file_rel = api.get("file", "unknown")
            module_key = file_rel
            if module_key not in modules_map:
                modules_map[module_key] = {
                    "name": module_key,
                    "apis": [],
                    "description": f"Source file: {module_key}",
                    "api_count": 0,
                }
            modules_map[module_key]["apis"].append({
                "path": api.get("path", ""),
                "http_method": api.get("http_method", ""),
                "business_purpose": api.get("method_name", ""),
            })
            modules_map[module_key]["api_count"] += 1
        business_modules = list(modules_map.values())

        # 2. 扫描源码风险模式
        risk_areas: list[dict[str, Any]] = []
        for file_path in root.rglob("*"):
            if not file_path.is_file():
                continue
            if file_path.suffix.lower() not in _RULE_SCAN_EXT:
                continue
            if any(part in _RULE_SKIP_DIRS for part in file_path.parts):
                continue
            try:
                text = file_path.read_text(encoding="utf-8", errors="ignore")
            except Exception as e:
                logger.debug(f"Failed to read {file_path}: {e}")
                continue

            hits: list[str] = []
            for label, pat, _sev in _RISK_RULES:
                if pat.search(text):
                    hits.append(label)

            if hits:
                severity = "low"
                if any(
                    _sev == "high"
                    for _lbl, _pat, _sev in _RISK_RULES
                    if _lbl in hits
                ):
                    severity = "high"
                elif any(
                    _sev == "medium"
                    for _lbl, _pat, _sev in _RISK_RULES
                    if _lbl in hits
                ):
                    severity = "medium"
                rel_path = str(file_path.relative_to(root))
                # 派生 title/description（前端 Analysis.vue 风险卡 title/description 字段）
                severity_label = {"high": "高危", "medium": "中危", "low": "低危"}[severity]
                risk_areas.append({
                    "path": rel_path,
                    "http_method": "",
                    "risk_points": hits,
                    "severity": severity,
                    "title": f"[{severity_label}] {rel_path} 命中 {len(hits)} 类风险",
                    "description": (
                        "规则化扫描命中以下风险点：" + "、".join(hits) +
                        f"。文件路径：{rel_path}"
                    ),
                })

        # 按严重级别排序（与 analyze_project 一致）
        severity_order = {"high": 0, "medium": 1, "low": 2}
        risk_areas.sort(key=lambda x: severity_order.get(x["severity"], 3))

        logger.info(
            f"Rule-based analysis completed: {len(business_modules)} modules, "
            f"{len(risk_areas)} risk areas (no AI model)"
        )

        return {
            "business_modules": business_modules,
            "data_flow": {
                "nodes": [
                    {"name": m["name"], "api_count": m["api_count"]}
                    for m in business_modules
                ],
                "edges": [],
            },
            "risk_areas": risk_areas,
            "api_analyses": [],
            "offline": True,
        }

    async def analyze_api(
        self, api_info: dict[str, Any], code_snippet: str
    ) -> dict[str, Any]:
        """
        分析单个 API 的业务逻辑。

        调用 LLM 分析 API 的业务目的、关键校验、业务规则、预期响应、
        依赖关系和风险点。

        Args:
            api_info: API 接口信息（包含 path, http_method, params 等）。
            code_snippet: API 对应的源码片段。

        Returns:
            AI 分析结果字典。
        """
        prompt = self._build_analysis_prompt(api_info, code_snippet)

        response = await self.router.call(
            use_case="code_analysis",
            messages=[{"role": "user", "content": prompt}],
        )

        result = self._parse_json_response(response)

        # 确保必要字段存在
        result.setdefault("path", api_info.get("path", ""))
        result.setdefault("http_method", api_info.get("http_method", ""))
        result.setdefault("business_purpose", "Unknown")
        result.setdefault("key_validations", [])
        result.setdefault("business_rules", [])
        result.setdefault("expected_responses", [])
        result.setdefault("dependencies", [])
        result.setdefault("risk_points", [])

        return result

    def _build_analysis_prompt(
        self, api_info: dict[str, Any], code_snippet: str
    ) -> str:
        """
        构建 AI 分析的 prompt。

        Args:
            api_info: API 接口信息。
            code_snippet: 源码片段。

        Returns:
            prompt 字符串。
        """
        params_str = json.dumps(api_info.get("params", []), ensure_ascii=False)
        return f"""分析以下 API 接口的业务逻辑:

接口信息:
- 路径: {api_info.get('path', 'N/A')}
- HTTP 方法: {api_info.get('http_method', 'N/A')}
- 参数: {params_str}
- 是否需要认证: {api_info.get('auth_required', False)}

代码片段:
{code_snippet[:_CODE_SNIPPET_MAX_CHARS]}

请分析并输出 JSON 格式结果，包含以下字段:
{{
    "business_purpose": "该接口的业务目的（一句话描述）",
    "key_validations": ["关键校验逻辑列表"],
    "business_rules": ["业务规则列表"],
    "expected_responses": [
        {{"status": 200, "description": "成功响应描述"}}
    ],
    "dependencies": ["依赖的其他模块或服务"],
    "risk_points": ["潜在风险点列表"]
}}

请只输出 JSON，不要包含其他文字。"""

    def _read_code_snippets(
        self, project_path: str, apis: list[dict[str, Any]]
    ) -> list[str]:
        """
        为每个 API 读取其源文件对应行附近的代码片段。

        Args:
            project_path: 项目根目录路径。
            apis: API 接口列表。

        Returns:
            代码片段字符串列表（与 apis 一一对应）。
        """
        root = Path(project_path)
        snippets: list[str] = []

        for api in apis:
            file_rel = api.get("file", "")
            line_number = api.get("line_number", 1)

            if not file_rel:
                snippets.append("")
                continue

            file_path = root / file_rel
            if not file_path.exists():
                snippets.append("")
                continue

            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
                lines = content.split("\n")

                # 读取目标行前后各 15 行（共约 30 行）
                start = max(0, line_number - 15)
                end = min(len(lines), line_number + 15)
                snippet = "\n".join(lines[start:end])
                snippets.append(snippet)
            except Exception as e:
                logger.debug(f"Failed to read code snippet for {file_rel}: {e}")
                snippets.append("")

        return snippets

    def _aggregate_business_modules(
        self, api_analyses: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """
        将 API 分析结果按业务域聚合成业务模块。

        通过分析 API 路径前缀和 dependencies 字段进行聚类。

        Args:
            api_analyses: AI 分析结果列表。

        Returns:
            业务模块列表，每个模块包含 name / apis / description。
        """
        modules: dict[str, dict[str, Any]] = {}

        for analysis in api_analyses:
            path = analysis.get("path", "")
            # 提取路径前两段作为模块名
            parts = path.strip("/").split("/")
            module_key = "/".join(parts[:2]) if len(parts) >= 2 else (parts[0] if parts else "root")

            if module_key not in modules:
                modules[module_key] = {
                    "name": module_key,
                    "apis": [],
                    "description": f"Business module: {module_key}",
                    "api_count": 0,
                }

            modules[module_key]["apis"].append({
                "path": path,
                "http_method": analysis.get("http_method", ""),
                "business_purpose": analysis.get("business_purpose", ""),
            })
            modules[module_key]["api_count"] += 1

        return list(modules.values())

    def _analyze_data_flow(
        self,
        business_modules: list[dict[str, Any]],
        api_analyses: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        分析模块间的数据流和依赖关系。

        Args:
            business_modules: 业务模块列表。
            api_analyses: API 分析结果列表。

        Returns:
            数据流信息字典，包含 nodes 和 edges。
        """
        # 构建模块名集合
        module_names = {m["name"] for m in business_modules}

        # 从 API 分析的 dependencies 字段提取模块间依赖
        edges: list[dict[str, str]] = []
        edge_set: set[tuple[str, str]] = set()

        for analysis in api_analyses:
            path = analysis.get("path", "")
            parts = path.strip("/").split("/")
            source_module = "/".join(parts[:2]) if len(parts) >= 2 else (parts[0] if parts else "root")

            for dep in analysis.get("dependencies", []):
                dep_lower = str(dep).lower()
                # 检查依赖是否指向某个已知模块
                for target_module in module_names:
                    if target_module in dep_lower and target_module != source_module:
                        edge_key = (source_module, target_module)
                        if edge_key not in edge_set:
                            edge_set.add(edge_key)
                            edges.append({
                                "source": source_module,
                                "target": target_module,
                            })

        return {
            "nodes": [{"name": m["name"], "api_count": m["api_count"]} for m in business_modules],
            "edges": edges,
        }

    def _identify_risk_areas(
        self, api_analyses: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """
        从 API 分析结果中识别风险区域。

        Args:
            api_analyses: API 分析结果列表。

        Returns:
            风险区域列表，每个包含 path / risk_points / severity。
        """
        risk_areas: list[dict[str, Any]] = []

        for analysis in api_analyses:
            risk_points = analysis.get("risk_points", [])
            if not risk_points:
                continue

            # 根据风险点数量和内容推断严重级别
            severity = "low"
            risk_text = " ".join(str(r) for r in risk_points).lower()

            if any(kw in risk_text for kw in ("security", "inject", "auth", "permission", "sql")):
                severity = "high"
            elif any(kw in risk_text for kw in ("data loss", "concurrency", "race", "timeout")):
                severity = "medium"
            elif len(risk_points) > 3:
                severity = "medium"

            severity_label = {"high": "高危", "medium": "中危", "low": "低危"}[severity]
            rel_path = analysis.get("path", "")
            method = analysis.get("http_method", "")
            risk_areas.append({
                "path": rel_path,
                "http_method": method,
                "risk_points": risk_points,
                "severity": severity,
                "title": (
                    f"[{severity_label}] {method.upper()} {rel_path} 命中 {len(risk_points)} 项风险"
                    if method else f"[{severity_label}] {rel_path} 命中 {len(risk_points)} 项风险"
                ),
                "description": (
                    "AI 语义分析识别出以下风险点：" + "、".join(str(r) for r in risk_points) +
                    f"。位置：{method.upper() + ' ' if method else ''}{rel_path}"
                ),
            })

        # 按严重级别排序
        severity_order = {"high": 0, "medium": 1, "low": 2}
        risk_areas.sort(key=lambda x: severity_order.get(x["severity"], 3))

        return risk_areas

    def _parse_json_response(self, response: str) -> dict[str, Any]:
        """
        从 LLM 响应中解析 JSON。

        兼容三种情况：
        1. 直接 JSON 字符串
        2. markdown code block 包裹的 JSON (```json ... ```)
        3. 普通文本中嵌入的 JSON（尝试提取第一个 { ... } 块）

        Args:
            response: LLM 返回的字符串。

        Returns:
            解析后的字典。解析失败返回空字典。
        """
        if not response or not response.strip():
            logger.warning("Empty AI response, returning empty dict")
            return {}

        text = response.strip()

        # 1. 尝试直接解析
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 2. 尝试从 markdown code block 中提取
        code_block_pattern = re.compile(r'```(?:json)?\s*\n?(.*?)\n?```', re.DOTALL)
        match = code_block_pattern.search(text)
        if match:
            try:
                return json.loads(match.group(1).strip())
            except json.JSONDecodeError:
                pass

        # 3. 尝试提取第一个 { ... } 块
        brace_pattern = re.compile(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', re.DOTALL)
        match = brace_pattern.search(text)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass

        logger.warning(
            f"Failed to parse JSON from AI response. "
            f"Response preview: {text[:200]}..."
        )
        return {}
