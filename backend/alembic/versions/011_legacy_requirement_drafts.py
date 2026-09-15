"""将历史需求生成的空 URL/伪造 200 断言用例降回手工草稿。"""

from alembic import op

revision = "011"
down_revision = "010"


def upgrade() -> None:
    # 原始载荷保存在 legacy_request_data，避免丢失旧操作步骤和追溯信息。
    op.execute("""
        UPDATE test_case_assets
        SET execution_kind = 'manual',
            status = 'draft'::caseassetstatus,
            review_state = 'draft',
            expected_result = jsonb_build_object('text', COALESCE(request_data->>'expected', '')),
            request_data = jsonb_build_object(
                'steps', COALESCE(request_data->'steps', '[]'::jsonb),
                'related_requirement', COALESCE(request_data->>'related_requirement', ''),
                'requirement_doc_id', request_data->>'requirement_doc_id',
                'legacy_request_data', request_data
            )
        WHERE source::text IN ('requirement', 'REQUIREMENT')
          AND request_data ? 'requirement_doc_id'
          AND COALESCE(request_data->>'url', '') = ''
    """)


def downgrade() -> None:
    # 不恢复无法执行且会误判成功的旧格式；原始载荷保留在 legacy_request_data。
    pass
