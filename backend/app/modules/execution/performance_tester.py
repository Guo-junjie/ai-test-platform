"""
性能测试执行器

使用 httpx.AsyncClient 模拟并发压力（编程式实现，不依赖 Locust Web UI）。
阶梯压测：逐步增加并发用户数（10→50→100→200）。
记录 TPS / QPS / P95 / P99 响应时间和瓶颈识别。
"""

import asyncio
import statistics
import time
from typing import Any

import httpx

from app.utils.logger import get_logger

logger = get_logger(__name__)

# 阶梯压测的并发用户数序列
_DEFAULT_CONCURRENCY_LEVELS = [10, 50, 100, 200]
# 每个阶梯持续时间（秒）
_DEFAULT_DURATION_SECONDS = 15


class PerformanceTester:
    """
    性能测试执行器。

    通过阶梯式增加并发请求数，模拟真实负载场景，
    收集 TPS / QPS / P95 / P99 等性能指标。
    """

    async def run_tests(
        self,
        test_cases: list[dict[str, Any]],
        service_url: str,
    ) -> list[dict[str, Any]]:
        """
        执行性能测试。

        对每个性能测试用例执行阶梯压测。

        Args:
            test_cases: 性能测试用例列表。
            service_url: 被测服务的基础 URL。

        Returns:
            性能测试结果列表，每个结果包含：
                total_requests, total_errors, avg_response_time,
                p95, p99, tps, qps, bottlenecks。
        """
        results: list[dict[str, Any]] = []

        async with httpx.AsyncClient(
            base_url=service_url,
            timeout=httpx.Timeout(60.0, connect=10.0),
            verify=False,
        ) as client:
            for case in test_cases:
                result = await self._run_stress_test(client, case)
                results.append(result)

        logger.info(f"Performance tests completed: {len(results)} scenarios")
        return results

    async def _run_stress_test(
        self, client: httpx.AsyncClient, case: dict[str, Any]
    ) -> dict[str, Any]:
        """
        执行单个阶梯压测场景。

        Args:
            client: httpx 异步客户端。
            case: 性能测试用例。

        Returns:
            性能测试结果。
        """
        case_id = case.get("case_id", "unknown")
        case_name = case.get("case_name", "performance_test")
        request_data = case.get("request", {})
        load_config = case.get("load_config", {})

        concurrency_levels = load_config.get(
            "concurrent_users", _DEFAULT_CONCURRENCY_LEVELS
        )
        duration_seconds = load_config.get(
            "duration_seconds", _DEFAULT_DURATION_SECONDS
        )

        method = request_data.get("method", "GET")
        url = request_data.get("url", "/")
        headers = request_data.get("headers", {})
        body = request_data.get("body", {})

        logger.info(
            f"Stress test starting: {case_name}, "
            f"levels={concurrency_levels}, duration={duration_seconds}s"
        )

        all_response_times: list[float] = []
        total_requests = 0
        total_errors = 0

        # 错误熔断阈值：连续全错请求达到此数立即终止（AI 生成的性能用例
        # 可能指向不存在的接口——实测曾无限压测 8.7 万个 404 请求把流水线
        # 卡死在 92% 十几分钟）
        CIRCUIT_BREAK_ERRORS = 100

        for concurrency in concurrency_levels:
            logger.info(f"  Level: {concurrency} concurrent users")

            level_times: list[float] = []
            level_errors = 0
            level_requests = 0
            consecutive_errors = 0

            end_time = time.time() + duration_seconds

            async def send_request() -> tuple[float, bool]:
                start = time.time()
                try:
                    response = await client.request(
                        method=method.upper(),
                        url=url,
                        headers=headers,
                        json=body if body else None,
                    )
                    elapsed = (time.time() - start) * 1000
                    return elapsed, response.status_code >= 400
                except Exception:
                    return (time.time() - start) * 1000, True

            # 受控批次压测：每批 concurrency 个请求并发，完成后立即下一批，
            # 到时即停。旧实现「每 1ms 无限 create_task + 最后 gather」会让
            # 任务按请求速度无限堆积，实际时长与请求失败速度成正比膨胀。
            circuit_broken = False
            while time.time() < end_time:
                batch = [asyncio.create_task(send_request()) for _ in range(concurrency)]
                results = await asyncio.gather(*batch)
                for elapsed, is_error in results:
                    level_times.append(elapsed)
                    level_requests += 1
                    if is_error:
                        level_errors += 1
                        consecutive_errors += 1
                    else:
                        consecutive_errors = 0
                # 熔断：对不存在的接口立即止损
                if level_requests >= CIRCUIT_BREAK_ERRORS and consecutive_errors >= CIRCUIT_BREAK_ERRORS:
                    logger.warning(
                        f"    circuit break: {level_errors}/{level_requests} all errors, "
                        f"target likely broken (url={url})"
                    )
                    circuit_broken = True
                    break

            all_response_times.extend(level_times)
            total_requests += level_requests
            total_errors += level_errors
            if circuit_broken:
                break

            level_tps = level_requests / duration_seconds if duration_seconds > 0 else 0
            logger.info(
                f"    requests={level_requests}, errors={level_errors}, "
                f"tps={level_tps:.1f}"
            )

        # 计算汇总指标
        avg_response_time = (
            statistics.mean(all_response_times) if all_response_times else 0
        )
        p95 = self._percentile(all_response_times, 95)
        p99 = self._percentile(all_response_times, 99)
        total_duration = len(concurrency_levels) * duration_seconds
        tps = total_requests / total_duration if total_duration > 0 else 0
        qps = tps  # QPS = TPS for single-endpoint tests
        error_rate = (total_errors / total_requests * 100) if total_requests > 0 else 0

        # 瓶颈识别
        bottlenecks = self._identify_bottlenecks(
            avg_response_time, p95, p99, error_rate
        )

        result = {
            "case_id": case_id,
            "case_name": case_name,
            "total_requests": total_requests,
            "total_errors": total_errors,
            "avg_response_time": round(avg_response_time, 2),
            "p95": round(p95, 2),
            "p99": round(p99, 2),
            "tps": round(tps, 2),
            "qps": round(qps, 2),
            "error_rate": round(error_rate, 2),
            "bottlenecks": bottlenecks,
        }

        logger.info(
            f"Stress test completed: {case_name}, "
            f"requests={total_requests}, errors={total_errors}, "
            f"avg={avg_response_time:.0f}ms, p95={p95:.0f}ms, "
            f"tps={tps:.1f}, bottlenecks={len(bottlenecks)}"
        )

        return result

    def _percentile(self, data: list[float], percentile: int) -> float:
        """计算百分位数。"""
        if not data:
            return 0.0
        sorted_data = sorted(data)
        index = int(len(sorted_data) * percentile / 100)
        if index >= len(sorted_data):
            index = len(sorted_data) - 1
        return sorted_data[index]

    def _identify_bottlenecks(
        self,
        avg_response_time: float,
        p95: float,
        p99: float,
        error_rate: float,
    ) -> list[str]:
        """识别性能瓶颈。"""
        bottlenecks: list[str] = []

        if avg_response_time > 500:
            bottlenecks.append(
                f"Average response time {avg_response_time:.0f}ms exceeds 500ms threshold"
            )
        if p95 > 1000:
            bottlenecks.append(
                f"P95 response time {p95:.0f}ms exceeds 1000ms threshold"
            )
        if p99 > 2000:
            bottlenecks.append(
                f"P99 response time {p99:.0f}ms exceeds 2000ms threshold"
            )
        if error_rate > 5:
            bottlenecks.append(
                f"Error rate {error_rate:.1f}% exceeds 5% threshold"
            )

        return bottlenecks
