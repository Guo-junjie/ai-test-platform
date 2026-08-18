"""
能力4 — 场景编排器（ScenarioOrchestrator）。

将自然语言场景 + 候选接口喂给 scenario_orchestration 插槽，产出结构化 steps；
AI 失败 / 无 Key / 解析失败一律走规则兜底（按候选顺序线性串联，首步提取 token/id，
后续步以 {{token}}/{{id}} 占位注入）。绝不抛异常中断主流程。
"""

import json
import re

from app.models.database import ApiEndpoint
from app.modules.ai.model_router import get_model_router
from app.utils.logger import get_logger

logger = get_logger(__name__)


class ScenarioOrchestrator:
    """把候选接口编排成有序测试步骤。"""

    async def orchestrate(
        self,
        nl_input: str,
        project_id,  # UUID
        candidate_endpoints: list[dict],
        db,
    ) -> dict:
        """
        编排场景步骤。

        Args:
            nl_input: 用户自然语言场景描述。
            project_id: 项目 UUID（用于反查 endpoint_id）。
            candidate_endpoints: retriever 返回的候选接口列表。
            db: 异步数据库会话。

        Returns:
            ``{"steps": [...], "engine": "ai" | "rule"}``。
        """
        candidates = candidate_endpoints or []
        try:
            router = get_model_router()
            prompt = self._build_prompt(nl_input, candidates)
            resp = await router.call(
                use_case="scenario_orchestration",
                messages=[{"role": "user", "content": prompt}],
                response_format_json=True,
                temperature=0.3,
            )
            parsed = self._parse_json_response(resp)
            steps = parsed.get("steps") if isinstance(parsed, dict) else None
            if steps:
                resolved = await self._resolve_steps(steps, candidates, project_id, db)
                if resolved:
                    logger.info(
                        f"Scenario orchestrated by AI: {len(resolved)} steps "
                        f"(project={project_id})"
                    )
                    return {"steps": resolved, "engine": "ai"}
        except Exception as e:  # noqa: BLE001
            logger.warning(
                f"AI scenario orchestration failed (fallback to rule): {e}"
            )

        # 规则兜底：按候选出现顺序线性串联
        rule_steps = self._rule_fallback(candidates)
        logger.info(
            f"Scenario orchestrated by RULE: {len(rule_steps)} steps "
            f"(project={project_id})"
        )
        return {"steps": rule_steps, "engine": "rule"}

    # ==================== 内部：prompt / 解析 / 校验 ====================

    def _build_prompt(self, nl_input: str, candidates: list[dict]) -> str:
        """构造 scenario_orchestration 的 prompt。"""
        cand_json = json.dumps(
            [
                {
                    "id": c.get("id"),
                    "method": c.get("method"),
                    "path": c.get("path"),
                    "summary": c.get("summary"),
                }
                for c in candidates
            ],
            ensure_ascii=False,
        )
        return f"""你是一个测试场景编排助手。根据用户的自然语言场景描述，从候选接口列表中选择合适的接口，编排成有序的测试步骤。

用户场景描述：
{nl_input}

候选接口列表（JSON）：
{cand_json}

要求：
1. 按业务执行顺序输出 steps 数组，每一步绑定一个候选接口的 id（必须来自候选列表）。
2. 如果某个步骤的 token/数据依赖前一步的响应，请在 extract 中声明提取的变量与 JSONPath，
   在后续步骤的 request 中使用 {{变量名}} 占位符（例如 {{token}}、{{id}}）。
3. depend_on_step 填写该步骤依赖的前置步骤序号（第一步为 null）。
4. 每个 request 给出 headers/body/params 的占位结构。

输出严格 JSON 格式（不要包含任何解释文字）：
{{
    "steps": [
        {{
            "step_order": 1,
            "endpoint_id": "候选接口 id",
            "action_desc": "步骤意图，如：登录获取 token",
            "method": "POST",
            "url": "/api/v1/login",
            "extract": {{"token": "$.data.token", "id": "$.data.id"}},
            "inject": {{"token": "headers.Authorization", "id": "body.id"}},
            "depend_on_step": null,
            "request": {{"headers": {{}}, "body": {{}}, "params": {{}}}}
        }}
    ]
}}"""

    def _parse_json_response(self, response: str) -> dict:
        """从 LLM 响应解析 JSON（兼容裸 JSON / ```json 代码块 / 抽取 {...}）。"""
        if not response or not response.strip():
            return {}
        text = response.strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1).strip())
            except json.JSONDecodeError:
                pass

        m = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass

        logger.warning(f"Failed to parse scenario JSON: {text[:200]}...")
        return {}

    async def _resolve_steps(
        self,
        steps: list,
        candidates: list[dict],
        project_id,
        db,
    ) -> list[dict]:
        """校验并补全每个 step 的 endpoint_id；无法补全则丢弃该步。"""
        resolved: list[dict] = []
        for raw in steps:
            if not isinstance(raw, dict):
                continue
            eid = await self._resolve_endpoint_id(raw, candidates, project_id, db)
            step = {
                "step_order": raw.get("step_order") or (len(resolved) + 1),
                "endpoint_id": str(eid) if eid else None,
                "action_desc": raw.get("action_desc") or "",
                "method": (raw.get("method") or "").upper() or "GET",
                "url": raw.get("url") or raw.get("path") or "",
                "extract": raw.get("extract") or {},
                "inject": raw.get("inject") or {},
                "depend_on_step": raw.get("depend_on_step"),
                "request": raw.get("request") or {"headers": {}, "body": {}, "params": {}},
            }
            resolved.append(step)
        # 重排 step_order，保证连续
        for i, s in enumerate(resolved, start=1):
            s["step_order"] = i
        return resolved

    async def _resolve_endpoint_id(
        self, step: dict, candidates: list[dict], project_id, db
    ):
        """解析 step 的 endpoint_id：优先显式 id，其次 method+path 反查（候选 / DB）。"""
        eid = step.get("endpoint_id")
        if eid and any(str(c.get("id")) == str(eid) for c in candidates):
            return eid

        method = (step.get("method") or "").upper()
        url = (step.get("url") or step.get("path") or "").strip().rstrip("/") or None
        if method and url:
            for c in candidates:
                cpath = (c.get("path") or "").strip().rstrip("/")
                if c.get("method", "").upper() == method and (
                    cpath == url or url in cpath or cpath in url
                ):
                    return c.get("id")
            # DB 反查（同项目内 method+path 精确匹配）
            try:
                row = (
                    await db.execute(
                        select(ApiEndpoint.id).where(
                            ApiEndpoint.project_id == project_id,
                            ApiEndpoint.method == method,
                            ApiEndpoint.path == url,
                        ).limit(1)
                    )
                ).scalar_one_or_none()
                if row:
                    return row
            except Exception as e:  # noqa: BLE001
                logger.warning(f"DB endpoint lookup failed: {e}")
        return None

    def _rule_fallback(self, candidates: list[dict]) -> list[dict]:
        """规则兜底：按候选顺序线性串联，首步提取 token/id，后续步以占位符注入。"""
        steps: list[dict] = []
        prev_order = None
        for i, cand in enumerate(candidates):
            order = i + 1
            step = {
                "step_order": order,
                "endpoint_id": str(cand.get("id")) if cand.get("id") else None,
                "action_desc": cand.get("summary") or f"{cand.get('method')} {cand.get('path')}",
                "method": (cand.get("method") or "GET").upper(),
                "url": cand.get("path") or "/",
                "extract": {},
                "inject": {},
                "depend_on_step": prev_order,
                "request": {"headers": {}, "body": {}, "params": {}},
            }
            if i == 0:
                step["extract"] = {"token": "$.data.token", "id": "$.data.id"}
            else:
                step["request"] = {
                    "headers": {"Authorization": "Bearer {{token}}"},
                    "body": {"id": "{{id}}"},
                    "params": {},
                }
                step["inject"] = {"token": "headers.Authorization", "id": "body.id"}
            steps.append(step)
            prev_order = order
        return steps
