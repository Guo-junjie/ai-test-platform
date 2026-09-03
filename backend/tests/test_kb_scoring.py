"""知识库检索打分函数测试（余弦相似度 / 关键词打分 / 分词，纯函数无 IO）。"""
from app.modules.knowledge.retriever import _tokenize, cosine, keyword_score


class TestCosine:
    def test_identical_vectors(self):
        assert cosine([1, 0, 1], [1, 0, 1]) == pytest_approx(1.0)

    def test_orthogonal_vectors(self):
        assert cosine([1, 0], [0, 1]) == pytest_approx(0.0)

    def test_dimension_mismatch_returns_zero(self):
        assert cosine([1, 2, 3], [1, 2]) == 0.0

    def test_zero_vector_returns_zero(self):
        assert cosine([0, 0], [1, 2]) == 0.0
        assert cosine([], [1, 2]) == 0.0

    def test_opposite_vectors(self):
        assert cosine([1, 0], [-1, 0]) == pytest_approx(-1.0)


class TestTokenize:
    def test_ascii_words_and_cjk_chars(self):
        tokens = _tokenize("Login API 登录")
        assert "login" in tokens and "api" in tokens
        assert "登" in tokens and "录" in tokens

    def test_lowercase_normalization(self):
        assert "api" in _tokenize("API")

    def test_empty(self):
        assert _tokenize("") == []
        assert _tokenize(None) == []


class TestKeywordScore:
    def test_positive_on_overlap(self):
        assert keyword_score("Trap 丢失", "Trap 丢失重传机制") > 0

    def test_zero_on_no_overlap(self):
        assert keyword_score("量子纠缠", "登录接口规范") == 0.0

    def test_empty_inputs(self):
        assert keyword_score("", "abc") == 0.0
        assert keyword_score("abc", "") == 0.0

    def test_long_content_dilutes_precision(self):
        """同查询：内容越长 precision 越低（BM25-lite 的设计行为）。"""
        short = keyword_score("trap", "trap 说明")
        long = keyword_score("trap", "trap " + "其他内容 " * 100)
        assert short > long > 0


def pytest_approx(x: float) -> float:
    """余弦结果允许 1e-9 浮点误差。"""
    import pytest

    return pytest.approx(x, abs=1e-9)
