import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.models.database import Defect, DefectType, DefectSeverity
from app.modules.report.generator import persist_defects_to_db, CATEGORY_TO_DEFECT_TYPE


@pytest.mark.asyncio
async def test_persist_defects_to_db_mapping():
    run_id = uuid.uuid4()
    proj_id = uuid.uuid4()
    case_id = uuid.uuid4()

    mock_session = AsyncMock()
    # Mock existing query (empty)
    mock_existing_result = MagicMock()
    mock_existing_result.scalars.return_value.all.return_value = []
    
    # Mock valid cases query (contains case_id)
    mock_valid_cases = MagicMock()
    mock_valid_cases.scalars.return_value.all.return_value = [case_id]

    # Return results in order
    mock_session.execute.side_effect = [
        mock_existing_result,
        mock_valid_cases,
    ]

    defects_data = {
        "defects": [
            {
                "title": "API响应500错误",
                "category": "program_bug",
                "severity": "P1",
                "case_id": str(case_id),
                "root_cause": "空指针异常",
                "fix_suggestion": "增加非空校验",
                "reproduction_steps": ["1. 请求/api/test", "2. 返回500"],
            },
            {
                "title": "接口响应超时",
                "category": "performance_issue",
                "severity": "P2",
                "case_id": "invalid-uuid",
                "root_cause": "慢查询",
                "fix_suggestion": "增加数据库索引",
                "reproduction_steps": "单步复现",
            }
        ],
        "summary": {"total": 2}
    }

    count = await persist_defects_to_db(
        test_run_id=run_id,
        defects_data=defects_data,
        project_id=proj_id,
        session=mock_session,
    )

    assert count == 2
    assert mock_session.add.call_count == 2

    first_call_defect = mock_session.add.call_args_list[0][0][0]
    assert isinstance(first_call_defect, Defect)
    assert first_call_defect.title == "API响应500错误"
    assert first_call_defect.defect_type == DefectType.PROGRAM
    assert first_call_defect.severity == DefectSeverity.P1
    assert first_call_defect.test_case_id == case_id
    assert first_call_defect.test_run_id == run_id
    assert first_call_defect.project_id == proj_id
    assert first_call_defect.status == "open"
    assert first_call_defect.is_resolved is False

    second_call_defect = mock_session.add.call_args_list[1][0][0]
    assert second_call_defect.defect_type == DefectType.PERFORMANCE
    assert second_call_defect.severity == DefectSeverity.P2
    assert second_call_defect.test_case_id is None  # invalid uuid safely handled
    assert second_call_defect.reproduce_steps == ["单步复现"]
