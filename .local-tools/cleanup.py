import sys
sys.path.insert(0, "/app")
import asyncio

# 清空项目/知识/审计/报告/缺陷等所有业务数据；保留：
# - users（账号+默认预置）
# - ai_model_configs / model_routing（模型配置）
# - kb_runtime_config（前端开关）
# 删除并重建 kb_rebuild_state（状态机）
TABLES = [
    "scheduled_task_runs", "scheduled_tasks",
    "coverage_reports", "test_reports", "test_results", "test_cases", "defects", "test_runs",
    "test_case_assets", "scenarios",
    "doc_reviews", "api_endpoints", "interface_docs", "requirement_docs",
    "script_generation_records", "database_connections", "ai_analysis_results",
    "knowledge_chunks", "knowledge_documents", "knowledge_feedback", "knowledge_terms",
    "notifications", "change_requests",
    "projects",
]

async def main():
    from sqlalchemy import text
    from app.utils.database import AsyncSessionLocal
    async with AsyncSessionLocal() as s:
        for t in TABLES:
            r = await s.execute(text(f"DELETE FROM {t}"))
            print(f"{t:30s} deleted {r.rowcount}")
        await s.execute(text("DELETE FROM kb_rebuild_state"))
        await s.commit()
    print("CLEANUP DONE (users + AI model configs + model_routing preserved)")

asyncio.run(main())
