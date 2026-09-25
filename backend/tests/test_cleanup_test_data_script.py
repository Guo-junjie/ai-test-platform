from pathlib import Path

from scripts.cleanup_test_data import (
    PRESERVED_TABLES,
    cleanup_artifact_tree,
    cleanup_targets,
)


def test_cleanup_targets_preserve_models_users_and_migration():
    tables = {
        "users",
        "ai_model_configs",
        "model_routing",
        "alembic_version",
        "projects",
        "test_runs",
        "future_business_table",
    }

    assert cleanup_targets(tables) == [
        "future_business_table",
        "projects",
        "test_runs",
    ]
    assert PRESERVED_TABLES.isdisjoint(cleanup_targets(tables))


def test_cleanup_artifact_tree_preserves_embedding_cache(tmp_path: Path):
    cache = tmp_path / "embedding-cache"
    cache.mkdir()
    (cache / "model.bin").write_bytes(b"model")
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "report.html").write_text("test", encoding="utf-8")
    (tmp_path / "uploads").mkdir()
    (tmp_path / "stray.tmp").write_text("test", encoding="utf-8")

    removed, preserved = cleanup_artifact_tree(tmp_path)

    assert (cache / "model.bin").read_bytes() == b"model"
    assert preserved == ["embedding-cache"]
    assert "stray.tmp" in removed
    assert not (tmp_path / "reports" / "report.html").exists()
    assert (tmp_path / "reports").is_dir()
    assert (tmp_path / "repos").is_dir()
