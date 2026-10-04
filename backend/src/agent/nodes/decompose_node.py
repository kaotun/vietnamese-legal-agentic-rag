"""Node phân rã và tiền xử lý truy vấn pháp lý (Decomposition & HyDE Node)."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from src.agent.llm_client import LLMClient
from src.domain.premise_checker import check_query_premise
from src.agent.state import LegalAgentState
from src.retrieval.hyde import HydeGenerator
from src.nlp.query_decomposer import QueryDecomposer
from src.nlp.spell_corrector import SpellCorrector

logger = logging.getLogger(__name__)


async def decompose_node(
    state: LegalAgentState,
    llm: LLMClient,
    *,
    spell_corrector: Optional[SpellCorrector] = None,
    query_decomposer: Optional[QueryDecomposer] = None,
    hyde_generator: Optional[HydeGenerator] = None,
    records: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Sửa lỗi chính tả, nhận diện đa hành vi vi phạm và tạo văn bản giả định HyDE.

    Nhận các instance tùy chọn (spell_corrector, query_decomposer, hyde_generator) từ caller.
    Nếu không được truyền vào, tạo mới tại chỗ (backward-compatible với test/standalone use).
    Khi chạy trong production (thông qua LegalAgent._build_graph), các instance này được
    khởi tạo 1 lần trong LegalAgent.__init__() và tái sử dụng cho mọi request.
    """
    query = state["query"]
    history = list(state.get("history") or [])
    logger.info(f"[DecomposeNode] Bắt đầu tiền xử lý câu hỏi: '{query}'")

    # Dùng instance được inject, hoặc fallback tạo mới nếu cần (standalone / test)
    _spell_corrector = spell_corrector or SpellCorrector(llm=llm)
    _decomposer = query_decomposer or QueryDecomposer(llm=llm)
    _hyde_gen = hyde_generator or HydeGenerator(llm=llm)

    # 1. Sửa lỗi chính tả và chuẩn hóa văn bản
    corrected_query, was_corrected = await _spell_corrector.correct(query)
    if was_corrected:
        logger.info(f"[DecomposeNode] Đã sửa lỗi chính tả: '{query}' -> '{corrected_query}'")
        query = corrected_query

    # 2. Phân rã câu hỏi đa hành vi
    decomp_result = await _decomposer.decompose(query, history=history)

    is_multi = decomp_result.get("is_multi_violation", False)
    standalone_query = decomp_result.get("standalone_query", query)
    sub_queries = decomp_result.get("sub_queries", [query])

    logger.info(f"[DecomposeNode] is_multi={is_multi}, sub_queries={sub_queries}")

    # 3. Tạo giả định pháp lý (HyDE) cho truy vấn đơn lẻ
    hypothetical_passage = None
    if not (is_multi and len(sub_queries) > 1):
        hypothetical_passage = await _hyde_gen.generate_hypothetical_passage(standalone_query)
        logger.info("[DecomposeNode] Đã tạo đoạn văn bản giả định HyDE.")

    # 4. Kiểm định tiền đề pháp lý trong câu hỏi (False Premise Check)
    premise_correction = check_query_premise(query, records=records)
    if premise_correction:
        logger.warning(f"[DecomposeNode] Phát hiện tiền đề sai trong câu hỏi: {premise_correction}")
        if premise_correction.get("cleaned_query"):
            clean_q = premise_correction["cleaned_query"]
            standalone_query = clean_q
            sub_queries = [clean_q]
            logger.info(f"[DecomposeNode] Tối ưu hóa truy vấn tìm kiếm (loại bỏ số điều sai): '{clean_q}'")

    return {
        "query": query,
        "standalone_query": standalone_query,
        "sub_queries": sub_queries,
        "is_multi_violation": is_multi,
        "hypothetical_passage": hypothetical_passage,
        "premise_correction": premise_correction,
        "retry_count": 0,
        "docs_grade": None,
        "correction_feedback": None,
        "hallucinated_articles": [],
    }
