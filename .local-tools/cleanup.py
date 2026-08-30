import sys
sys.path.insert(0, "/app")
import asyncio

# FK 顺序清理项目相关测试数据；保留：users / ai_model_configs / model_routing / audit_logs / kb_runtime_config / kb_rebuild_state
TABLES_IN_ORDER = [
    "scheduled_task_runs", "scheduled_tasks",
    "coverage_reports", "test_reports", "ai_analysis_results",
    "test_results", "test_cases", "defects", "test_runs",
    "test_case_assets", "scenarios",
    "doc_reviews", "api_endpoints", "interface_docs", "requirement_docs",
    "script_generation_records", "database_connections",
    "ai_analysis_results",
    "knowledge_chunks", "knowledge_documents", "knowledge_feedback", "knowledge_terms",
    "notifications", "change_requests",
    "projects",
]

async def main():
    from sqlalchemy import text
    from app.utils.database import AsyncSessionLocal
    async with AsyncSessionLocal() as s:
        for t in TABLES_IN_ORDER:
            r = await s.execute(text(f"DELETE FROM {t}"))
            print(f"{t}: deleted {r.rowcount}")
        await s.commit()
        # 重置重建状态机（知识库）
        await s.execute(text("DELETE FROM kb_rebuild_state"))
        await s.commit()
    print("CLEANUP DONE (users/model config/audit preserved)")

asyncio.run(main())
