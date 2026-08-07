"""
测试执行模块 — 接口/性能/集成测试并行执行引擎

包含：
- TestExecutionEngine: 调度引擎，触发 Celery 任务链
- APITester: 接口测试执行器
- PerformanceTester: 性能测试执行器
- IntegrationTester: 集成测试执行器
- AssertionEngine: 断言引擎
- EnvironmentAdapterFactory: 环境适配器工厂
"""

from app.modules.execution.engine import TestExecutionEngine
from app.modules.execution.api_tester import APITester
from app.modules.execution.performance_tester import PerformanceTester
from app.modules.execution.integration_tester import IntegrationTester
from app.modules.execution.assertion_engine import AssertionEngine
from app.modules.execution.env_adapters import EnvironmentAdapterFactory

__all__ = [
    "TestExecutionEngine",
    "APITester",
    "PerformanceTester",
    "IntegrationTester",
    "AssertionEngine",
    "EnvironmentAdapterFactory",
]
