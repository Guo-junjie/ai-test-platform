"""
质量门禁评估器 — 可配置规则的质量门禁检查

评估维度：
- P0/P1 缺陷数量（必须为 0 或低于阈值）
- API/性能/集成测试通过率
- 质量评分最低值
- 执行时间限制（可选）

不通过时返回违规项列表，用于阻断上线流程并触发告警。
"""

from typing import Any

from app.utils.logger import get_logger

logger = get_logger(__name__)


# ==================== 默认门禁规则 ====================

DEFAULT_GATE_CONFIG: dict[str, Any] = {
    "enabled": True,
    "rules": {
        "max_p0_defects": 0,
        "max_p1_defects": 5,
        "min_api_pass_rate": 90,
        "min_performance_pass_rate": 80,
        "min_integration_pass_rate": 85,
        "min_quality_score": 70,
    },
    "notify_on_fail": True,
    "notify_channels": ["webhook"],
    "block_deployment": True,
}


class QualityGateEvaluator:
    """
    质量门禁评估器。

    根据可配置规则评估测试结果，判定是否通过质量门禁。
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """
        初始化质量门禁评估器。

        Args:
            config: 门禁配置，为 None 时使用默认配置。
        """
        self.config = config or self.get_default_config()

    @staticmethod
    def get_default_config() -> dict[str, Any]:
        """返回默认门禁配置。"""
        import copy
        return copy.deepcopy(DEFAULT_GATE_CONFIG)

    @staticmethod
    def validate_config(config: dict[str, Any]) -> dict[str, Any]:
        """
        验证并规范化门禁配置。

        Args:
            config: 待验证的配置字典。

        Returns:
            规范化后的配置字典。

        Raises:
            ValueError: 配置不合法时抛出。
        """
        if not isinstance(config, dict):
            raise ValueError("Quality gate config must be a dict")

        validated = QualityGateEvaluator.get_default_config()

        if "enabled" in config:
            validated["enabled"] = bool(config["enabled"])

        if "rules" in config and isinstance(config["rules"], dict):
            rules = config["rules"]
            if "max_p0_defects" in rules:
                validated["rules"]["max_p0_defects"] = max(0, int(rules["max_p0_defects"]))
            if "max_p1_defects" in rules:
                validated["rules"]["max_p1_defects"] = max(0, int(rules["max_p1_defects"]))
            if "min_api_pass_rate" in rules:
                validated["rules"]["min_api_pass_rate"] = max(0, min(100, int(rules["min_api_pass_rate"])))
            if "min_performance_pass_rate" in rules:
                validated["rules"]["min_performance_pass_rate"] = max(0, min(100, int(rules["min_performance_pass_rate"])))
            if "min_integration_pass_rate" in rules:
                validated["rules"]["min_integration_pass_rate"] = max(0, min(100, int(rules["min_integration_pass_rate"])))
            if "min_quality_score" in rules:
                validated["rules"]["min_quality_score"] = max(0, min(100, int(rules["min_quality_score"])))

        if "notify_on_fail" in config:
            validated["notify_on_fail"] = bool(config["notify_on_fail"])

        if "notify_channels" in config and isinstance(config["notify_channels"], list):
            validated["notify_channels"] = [
                ch for ch in config["notify_channels"]
                if ch in ("webhook", "email", "dingtalk")
            ]

        if "block_deployment" in config:
            validated["block_deployment"] = bool(config["block_deployment"])

        return validated

    def evaluate(
        self,
        quality_score: int,
        defects: dict[str, Any],
        test_summary: dict[str, Any],
    ) -> dict[str, Any]:
        """
        评估质量门禁。

        Args:
            quality_score: 质量评分 (0-100)。
            defects: 缺陷分析结果，包含 summary.by_severity。
            test_summary: 测试摘要，包含 api/performance/integration 通过率。

        Returns:
            {
                "passed": bool,
                "violations": [{"rule": str, "actual": any, "expected": any, "message": str}],
                "score": int,
                "config": dict,
            }
        """
        if not self.config.get("enabled", True):
            logger.info("Quality gate is disabled, auto-pass")
            return {
                "passed": True,
                "violations": [],
                "score": quality_score,
                "config": self.config,
                "message": "Quality gate is disabled",
            }

        rules = self.config.get("rules", {})
        violations: list[dict[str, Any]] = []

        # 1. P0 缺陷检查
        by_severity = defects.get("summary", {}).get("by_severity", {})
        p0_count = by_severity.get("P0", 0)
        max_p0 = rules.get("max_p0_defects", 0)
        if p0_count > max_p0:
            violations.append({
                "rule": "max_p0_defects",
                "actual": p0_count,
                "expected": f"<= {max_p0}",
                "message": f"P0 缺陷数 {p0_count} 超出门禁阈值 {max_p0}",
            })

        # 2. P1 缺陷检查
        p1_count = by_severity.get("P1", 0)
        max_p1 = rules.get("max_p1_defects", 5)
        if p1_count > max_p1:
            violations.append({
                "rule": "max_p1_defects",
                "actual": p1_count,
                "expected": f"<= {max_p1}",
                "message": f"P1 缺陷数 {p1_count} 超出门禁阈值 {max_p1}",
            })

        # 3. API 通过率检查
        api_summary = test_summary.get("api_summary", {})
        api_total = api_summary.get("total", 0)
        api_passed = api_summary.get("passed", 0)
        if api_total > 0:
            api_pass_rate = round(api_passed / api_total * 100, 1)
            min_api = rules.get("min_api_pass_rate", 90)
            if api_pass_rate < min_api:
                violations.append({
                    "rule": "min_api_pass_rate",
                    "actual": f"{api_pass_rate}%",
                    "expected": f">= {min_api}%",
                    "message": f"API 测试通过率 {api_pass_rate}% 低于门禁要求 {min_api}%",
                })

        # 4. 性能测试通过率检查
        perf_summary = test_summary.get("performance_summary", {})
        perf_total = perf_summary.get("total", 0)
        perf_passed = perf_summary.get("passed", 0)
        if perf_total > 0:
            perf_pass_rate = round(perf_passed / perf_total * 100, 1)
            min_perf = rules.get("min_performance_pass_rate", 80)
            if perf_pass_rate < min_perf:
                violations.append({
                    "rule": "min_performance_pass_rate",
                    "actual": f"{perf_pass_rate}%",
                    "expected": f">= {min_perf}%",
                    "message": f"性能测试通过率 {perf_pass_rate}% 低于门禁要求 {min_perf}%",
                })

        # 5. 集成测试通过率检查
        integ_summary = test_summary.get("integration_summary", {})
        integ_total = integ_summary.get("total", 0)
        integ_passed = integ_summary.get("passed", 0)
        if integ_total > 0:
            integ_pass_rate = round(integ_passed / integ_total * 100, 1)
            min_integ = rules.get("min_integration_pass_rate", 85)
            if integ_pass_rate < min_integ:
                violations.append({
                    "rule": "min_integration_pass_rate",
                    "actual": f"{integ_pass_rate}%",
                    "expected": f">= {min_integ}%",
                    "message": f"集成测试通过率 {integ_pass_rate}% 低于门禁要求 {min_integ}%",
                })

        # 6. 质量评分检查
        min_score = rules.get("min_quality_score", 70)
        if quality_score < min_score:
            violations.append({
                "rule": "min_quality_score",
                "actual": quality_score,
                "expected": f">= {min_score}",
                "message": f"质量评分 {quality_score} 低于门禁要求 {min_score}",
            })

        passed = len(violations) == 0

        result = {
            "passed": passed,
            "violations": violations,
            "score": quality_score,
            "config": self.config,
            "message": "质量门禁通过" if passed else f"质量门禁未通过：{len(violations)} 项违规",
        }

        logger.info(
            f"Quality gate evaluation: passed={passed}, "
            f"score={quality_score}, violations={len(violations)}"
        )

        return result
