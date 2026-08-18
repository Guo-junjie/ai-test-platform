"""
SQL Security Validator

Uses sqlglot to parse SQL statements and validate against a whitelist
of allowed statement types. Reads whitelist from project quality gate
config, falls back to default whitelist (SELECT/INSERT/UPDATE/DELETE).
"""

import logging
from typing import Any, Dict, List

import sqlglot
from sqlglot import exp
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.utils.database import AsyncSessionLocal

logger = logging.getLogger(__name__)

# Default whitelist of allowed SQL statement types
DEFAULT_SQL_WHITELIST: List[str] = ["SELECT", "INSERT", "UPDATE", "DELETE"]


class SqlSecurity:
    """Validates SQL statements for security and whitelist compliance."""

    @staticmethod
    def _parse_sql(sql: str) -> List[Dict[str, Any]]:
        """
        Parse SQL string into individual statements using sqlglot.

        Args:
            sql: Raw SQL string (may contain multiple statements)

        Returns:
            List of dicts with 'type' and 'table' keys
        """
        statements: List[Dict[str, Any]] = []
        try:
            parsed = sqlglot.parse(sql, read=None)
            for stmt in parsed:
                if stmt is None:
                    continue
                stmt_type = type(stmt).__name__
                # Extract table name if available
                table_name = ""
                for node in stmt.find_all(exp.Table):
                    table_name = node.name
                    break
                statements.append({
                    "type": stmt_type,
                    "table": table_name,
                })
        except Exception as e:
            logger.warning("sqlglot parse error: %s", e)
            # Fallback: try to guess based on first keyword
            upper = sql.strip().upper()
            for kw in ["SELECT", "INSERT", "UPDATE", "DELETE", "CREATE", "DROP", "ALTER"]:
                if upper.startswith(kw):
                    statements.append({"type": kw, "table": ""})
                    break
        return statements

    @staticmethod
    def _get_allowed_types(whitelist: List[str]) -> set:
        """Map whitelist keywords to sqlglot expression class names."""
        type_map = {
            "SELECT": "Select",
            "INSERT": "Insert",
            "UPDATE": "Update",
            "DELETE": "Delete",
            "CREATE": "Create",
            "DROP": "Drop",
            "ALTER": "Alter",
            "TRUNCATE": "Truncate",
            "MERGE": "Merge",
        }
        allowed = set()
        for kw in whitelist:
            mapped = type_map.get(kw.strip().upper(), kw.strip().capitalize())
            allowed.add(mapped)
            allowed.add(kw.strip().upper())
        return allowed

    @staticmethod
    async def _load_whitelist(project_id: int) -> List[str]:
        """
        Load SQL whitelist from project quality gate config.

        Args:
            project_id: Project ID to load config for

        Returns:
            List of allowed SQL statement types (e.g. ['SELECT', 'INSERT'])
        """
        try:
            from app.models.database import Project

            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(Project.quality_gate_config).where(Project.id == project_id)
                )
                row = result.fetchone()
                if row and row[0]:
                    config = row[0] if isinstance(row[0], dict) else {}
                    whitelist = config.get("sql_whitelist", [])
                    if whitelist and isinstance(whitelist, list):
                        return [str(w).strip().upper() for w in whitelist if w]
        except Exception as e:
            logger.warning("Failed to load project whitelist: %s", e)

        return DEFAULT_SQL_WHITELIST

    @classmethod
    async def check(
        cls,
        sql: str,
        project_id: int = 0,
        session: AsyncSession | None = None,
    ) -> Dict[str, Any]:
        """
        Validate SQL against the whitelist.

        Args:
            sql: SQL string to validate
            project_id: Project ID for loading whitelist config
            session: Optional existing DB session

        Returns:
            Dict with keys:
                - passed: bool — whether all statements are allowed
                - statements: list — parsed statement info
                - message: str — human-readable result
        """
        if not sql or not sql.strip():
            return {
                "passed": False,
                "statements": [],
                "message": "SQL is empty",
            }

        statements = cls._parse_sql(sql)

        if not statements:
            return {
                "passed": False,
                "statements": [],
                "message": "Unable to parse SQL — no valid statements found",
            }

        # Load whitelist
        whitelist = DEFAULT_SQL_WHITELIST
        if project_id > 0:
            try:
                whitelist = await cls._load_whitelist(project_id)
            except Exception as e:
                logger.warning("Cannot load whitelist: %s", e)

        allowed_types = cls._get_allowed_types(whitelist)
        violations: List[str] = []

        for stmt in statements:
            stmt_type = stmt["type"]
            if stmt_type not in allowed_types:
                violations.append(stmt_type)

        if violations:
            return {
                "passed": False,
                "statements": statements,
                "message": (
                    f"SQL contains disallowed statement types: {', '.join(violations)}. "
                    f"Allowed: {', '.join(sorted(whitelist))}"
                ),
            }

        return {
            "passed": True,
            "statements": statements,
            "message": "SQL validation passed",
        }