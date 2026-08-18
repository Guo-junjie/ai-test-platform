"""
能力4 — 接口检索器（EndpointRetriever）。

对自然语言输入做轻量分词，按 method/path/summary 对同项目下的 api_endpoints
做模糊匹配（ILIKE），计算 match_score 并返回按分数降序的候选接口列表。

MVP 不做 AI 重排，纯规则匹配以保证确定性与零额外 LLM 开销。
"""

import re

from sqlalchemy import or_, select

from app.models.database import ApiEndpoint
from app.utils.logger import get_logger

logger = get_logger(__name__)

# 中文停用词（降低噪声匹配）
_STOPWORDS = {
    "的", "了", "和", "与", "或", "对", "在", "是", "我", "你", "他", "她", "它",
    "这", "那", "一个", "进行", "需要", "使用", "以及", "然后", "之后", "首先",
    "接着", "并", "再", "通过", "调用", "接口", "场景", "测试", "流程", "功能",
    "系统", "用户", "数据", "请求", "返回", "一个", "实现", "完成", "操作", "验证",
}

_CJK_RE = re.compile(r"[\u4e00-\u9fff]+")


def _tokenize(text: str) -> list[str]:
    """分词：按非字母数字（含中英文标点）切分，去停用词，并对 CJK 串补 bigram。"""
    if not text:
        return []
    raw = re.split(
        r"[\s,，。、；;:：!！?？()（）\[\]{}<>/\\|\"'`~@#$%^&*\-_=+]+", text.lower()
    )
    tokens: list[str] = []
    for tok in raw:
        tok = tok.strip()
        if not tok or len(tok) < 2 or tok in _STOPWORDS:
            continue
        tokens.append(tok)
        # CJK 串补 bigram，提升「用户登录」->「登录」的召回
        for seg in _CJK_RE.findall(tok):
            if len(seg) >= 2:
                for i in range(len(seg) - 1):
                    bigram = seg[i : i + 2]
                    if bigram not in _STOPWORDS:
                        tokens.append(bigram)

    # 去重保序
    seen: set[str] = set()
    result: list[str] = []
    for t in tokens:
        if t not in seen:
            seen.add(t)
            result.append(t)
    return result


def _score(cand: dict, tokens: list[str]) -> int:
    """根据命中 token 数计算匹配分（method > path > summary）。"""
    method = (cand.get("method") or "").lower()
    path = (cand.get("path") or "").lower()
    summary = (cand.get("summary") or "").lower()
    score = 0
    for t in tokens:
        tl = t.lower()
        if tl == method:
            score += 5
        if tl and tl in path:
            score += 3
        if tl and tl in summary:
            score += 2
    return score


def _endpoint_to_dict(ep: "ApiEndpoint") -> dict:
    """把 ApiEndpoint 行转为候选字典。"""
    return {
        "id": str(ep.id),
        "method": ep.method,
        "path": ep.path,
        "summary": ep.summary or "",
        "auth_required": bool(ep.auth_required),
    }


class EndpointRetriever:
    """从 api_endpoints 中检索与场景描述最相关的候选接口。"""

    async def search(
        self,
        nl_input: str,
        project_id,  # UUID
        db,
        limit: int = 20,
    ) -> list[dict]:
        """
        检索候选接口。

        Args:
            nl_input: 用户自然语言场景描述。
            project_id: 项目 UUID。
            db: 异步数据库会话。
            limit: 返回候选数量上限。

        Returns:
            候选接口字典列表，按 match_score 降序；每项含
            id / method / path / summary / match_score。
        """
        tokens = _tokenize(nl_input)

        q = select(ApiEndpoint).where(ApiEndpoint.project_id == project_id)
        if tokens:
            conds = []
            for t in tokens:
                like = f"%{t}%"
                conds.append(ApiEndpoint.path.ilike(like))
                conds.append(ApiEndpoint.summary.ilike(like))
                conds.append(ApiEndpoint.method.ilike(like))
            q = q.where(or_(*conds))

        rows = (await db.execute(q.order_by(ApiEndpoint.path))).scalars().all()
        candidates = [_endpoint_to_dict(e) for e in rows]

        if tokens:
            for c in candidates:
                c["match_score"] = _score(c, tokens)
            candidates.sort(key=lambda c: c["match_score"], reverse=True)
        else:
            for c in candidates:
                c["match_score"] = 0

        return candidates[:limit]
