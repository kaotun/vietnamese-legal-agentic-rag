"""Node phân rã và tiền xử lý truy vấn pháp lý (Decomposition & HyDE Node)."""
from __future__ import annotations

import logging
from typing import Any, Dict
from src.agent.llm_client import LLMClient
from src.agent.state import LegalAgentState
from src.retrieval.hyde import HydeGenerator
from src.retrieval.query_decomposer import QueryDecomposer
from src.retrieval.spell_corrector import SpellCorrector

logger = logging.getLogger(__name__)


async def decompose_node(state: LegalAgentState, llm: LLMClient) -> Dict[str, Any]:
    """Sửa lỗi chính tả, nhận diện đa hành vi vi phạm và tạo văn bản giả định HyDE."""
    query = state["query"]
    history = list(state.get("history") or [])
    logger.info(f"[DecomposeNode] Bắt đầu tiền xử lý câu hỏi: '{query}'")

    # 1. Sửa lỗi chính tả và chuẩn hóa văn bản
    spell_corrector = SpellCorrector(llm=llm)
    corrected_query, was_corrected = await spell_corrector.correct(query)
    if was_corrected:
        logger.info(f"[DecomposeNode] Đã sửa lỗi chính tả: '{query}' -> '{corrected_query}'")
        query = corrected_query

    # 2. Phân rã câu hỏi đa hành vi
    decomposer = QueryDecomposer(llm=llm)
    decomp_result = await decomposer.decompose(query, history=history)

    is_multi = decomp_result.get("is_multi_violation", False)
    standalone_query = decomp_result.get("standalone_query", query)
    sub_queries = decomp_result.get("sub_queries", [query])

    logger.info(f"[DecomposeNode] is_multi={is_multi}, sub_queries={sub_queries}")

    # 3. Tạo giả định pháp lý (HyDE) cho truy vấn đơn lẻ
    hypothetical_passage = None
    if not (is_multi and len(sub_queries) > 1):
        hyde_gen = HydeGenerator(llm=llm)
        hypothetical_passage = await hyde_gen.generate_hypothetical_passage(standalone_query)
        logger.info("[DecomposeNode] Đã tạo đoạn văn bản giả định HyDE.")

    return {
        "query": query,
        "standalone_query": standalone_query,
        "sub_queries": sub_queries,
        "is_multi_violation": is_multi,
        "hypothetical_passage": hypothetical_passage,
        "retry_count": 0,
        "docs_grade": None,
        "correction_feedback": None,
        "hallucinated_articles": [],
    }
