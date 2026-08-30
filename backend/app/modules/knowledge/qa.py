"""知识问答（RAG Chat）— 检索 → 编号引用上下文 → LLM 带引用回答。

核心原则（新设计文档原则三/四）：
- AI 不直接相信向量搜索：多类型检索合并 + 项目过滤 + 分数排序
- AI 输出必须有来源：上下文编号 [n]，要求模型引用；回答随附 sources 明细
- 无证据拒答：零命中不调 LLM，直接礼貌拒答（比编造安全）
"""
import time
from typing import Any

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.knowledge.retriever import (
    _source_label,
    retrieve_chunks,
    search_terms,
)

# 参与问答的知识类型（term 走专用检索，其余走向量/关键词检索）
_QA_KB_TYPES = ("document", "defect", "case", "doc")

# 最低相关度阈值：低于此分的切片视为无证据（噪声），不进入 LLM 上下文。
# 余弦 0.05 以下的"命中"基本无关，只会浪费 token 并干扰模型（实测"量子纠缠"
# 这类无关问题也能捞出 0.02 分的噪声，导致白调一次 LLM）。
_QA_MIN_SCORE = 0.05
# 术语兜底最多带 2 条（术语映射便宜且常有价值，但不喧宾夺主）
_QA_MAX_TERMS = 2

_REFUSAL = (
    "根据当前知识库没有找到与问题相关的可靠资料，无法给出有依据的回答。\n\n"
    "建议：\n"
    "1. 换一种问法（换关键词）重试；\n"
    "2. 若属于新业务，请先在「知识库RAG → 知识文档」上传相关测试规范或经验文档；\n"
    "3. 也可以在「检索预览」中先确认知识库是否已收录相关内容。"
)

_SYSTEM_PROMPT = """你是企业级软件测试智能助手，仅依据提供的知识回答问题。

要求：
1. 优先且仅使用提供的知识作答，不得编造知识库不存在的信息。
2. 事实性结论必须标注来源编号，格式为 [n]（n 为知识条目编号）。
3. 如果证据不足，明确说明"知识库中证据不足"，并给出还需要什么资料的建议。
4. 回答用简体中文，结构化分点，简洁但完整。"""

_USER_PROMPT_TEMPLATE = """知识库检索结果（已按相关度排序）：

{context}

用户问题：{question}

请基于以上知识回答。事实性结论标注来源编号 [n]；若以上知识不足以回答，请明确说明。"""


async def _retrieve_for_qa(
    db: AsyncSession,
    question: str,
    project_id: str | None,
    top_k: int,
) -> list[dict[str, Any]]:
    """跨类型检索合并：document/defect/case/doc 走切片检索，term 走术语检索。

    返回统一结构 [{index, kb_type, source_ref, source, score, content}]，
    按分数降序截断 top_k（term 无分数，排在有分命中之后）。
    """
    hits: list[dict[str, Any]] = []
    # 探测检索模式：语义模式下用 0.05 的余弦阈值滤噪声；关键词模式打分是
    # precision×recall 乘积、量级小得多，阈值降为 0.001 防止误杀真命中
    from app.modules.knowledge.embedder import embed_query

    semantic_mode = (await embed_query(question)) is not None
    min_score = _QA_MIN_SCORE if semantic_mode else 0.001
    for kb_type in _QA_KB_TYPES:
        for h in await retrieve_chunks(
            db, question, kb_type, top_k=top_k, project_id=project_id
        ):
            hits.append(
                {
                    "kb_type": kb_type,
                    "source_ref": h.chunk.source_ref,
                    "source": _source_label(h.chunk),
                    "score": round(h.score, 4),
                    "content": h.chunk.content,
                }
            )
    hits.sort(key=lambda x: x["score"], reverse=True)
    # 丢弃低于阈值的噪声命中（无证据时上层走拒答，不调 LLM）
    hits = [h for h in hits if h["score"] >= min_score][:top_k]

    terms = await search_terms(db, question, top_k=_QA_MAX_TERMS)
    for t in terms:
        hits.append(
            {
                "kb_type": "term",
                "source_ref": f"term:{t.id}",
                "source": t.term,
                "score": 0.0,
                "content": f"{t.term}：{t.technical_meaning}",
            }
        )
    return hits


def _build_context(hits: list[dict[str, Any]]) -> str:
    """命中切片 → 编号上下文（[n] 类型·来源 | 内容）。编号已由 ask_knowledge 统一写入。"""
    lines = []
    for h in hits:
        lines.append(f"[{h['index']}] {h['kb_type']}·{h['source'] or '未知来源'}\n{h['content']}")
    return "\n\n".join(lines)


async def ask_knowledge(
    db: AsyncSession,
    question: str,
    project_id: str | None = None,
    top_k: int = 5,
) -> dict[str, Any]:
    """知识问答主入口。

    Returns:
        {"answer": str, "sources": [...], "refused": bool, "elapsed_ms": int}

    Raises:
        ModelNotConfiguredError: 命中知识但未配置对话模型（全局处理器转 409 引导配置）。
    """
    if not question or not question.strip():
        return {"answer": "请输入问题。", "sources": [], "refused": True, "elapsed_ms": 0}

    start = time.monotonic()
    hits = await _retrieve_for_qa(db, question.strip(), project_id, top_k)
    # 统一编号（引用标记 [n] 的 n）；sources 与上下文构建都依赖它
    for i, h in enumerate(hits, start=1):
        h["index"] = i

    sources = [
        {
            "index": h["index"],
            "kb_type": h["kb_type"],
            "source_ref": h["source_ref"],
            "source": h["source"],
            "score": h["score"],
            "content": h["content"][:300],
        }
        for h in hits
    ]

    # 无证据拒答：零命中不调 LLM
    if not hits:
        logger.info(f"[KB QA] zero hits, refuse to answer: {question[:50]}")
        return {
            "answer": _REFUSAL,
            "sources": [],
            "refused": True,
            "elapsed_ms": round((time.monotonic() - start) * 1000),
        }

    from app.modules.ai.model_router import get_model_router

    prompt = _USER_PROMPT_TEMPLATE.format(
        context=_build_context(hits), question=question.strip()
    )
    router = get_model_router()
    answer = await router.call(
        use_case="report_analysis",
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
    )

    elapsed = round((time.monotonic() - start) * 1000)
    logger.info(
        f"[KB QA] answered: q={question[:50]!r} hits={len(hits)} "
        f"elapsed={elapsed}ms answer_len={len(answer or '')}"
    )
    return {
        "answer": (answer or "").strip(),
        "sources": sources,
        "refused": False,
        "elapsed_ms": elapsed,
    }
