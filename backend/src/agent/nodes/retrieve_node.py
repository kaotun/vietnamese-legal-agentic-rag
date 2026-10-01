"""Node truy hồi tài liệu pháp luật lai (Hybrid Retrieval Node: BM25 + Vector + FlashRank)."""
from __future__ import annotations

import logging
from typing import Any, Dict
from src.agent.state import LegalAgentState
from src.retrieval.hybrid_retriever import HybridLegalRetriever

logger = logging.getLogger(__name__)


async def retrieve_node(
    state: LegalAgentState,
    retriever: HybridLegalRetriever,
    top_k: int = 6
) -> Dict[str, Any]:
    """Truy hồi các Điều luật phù hợp nhất từ CSDL qua mô hình kết hợp BM25, Dense Vector và Cross-Encoder."""
    query = state.get("standalone_query") or state["query"]
    sub_queries = state.get("sub_queries") or [query]
    is_multi = state.get("is_multi_violation", False)
    hypothetical_passage = state.get("hypothetical_passage")
    retry_count = state.get("retry_count", 0)

    logger.info(f"[RetrieveNode] Thực thi truy hồi (Lần thử {retry_count + 1}). Query: '{query}'")

    if is_multi and len(sub_queries) > 1:
        retrieved_docs = await retriever.search_multi_queries(
            sub_queries=sub_queries,
            top_k_per_query=3,
            total_top_k=8,
            apply_rerank=True,
        )
    else:
        retrieved_docs = await retriever.search(
            query=query,
            top_k=top_k,
            hypothetical_passage=hypothetical_passage,
            apply_rerank=True,
        )

    logger.info(f"[RetrieveNode] Đã tìm thấy {len(retrieved_docs)} điều luật phù hợp.")

    # ── Tối ưu hóa đặc biệt khi phát hiện tiền đề sai về độ tuổi hình sự (< 14 tuổi) ──
    premise_correction = state.get("premise_correction")
    if premise_correction and premise_correction.get("is_age_ineligible"):
        # 1. Lọc bỏ các điều luật lạc đề (Điều 368, 369 về tội của điều tra viên/thẩm phán gây nhiễu LLM)
        filtered_docs = [
            d for d in retrieved_docs
            if d.get("article") not in ("Điều 368", "Điều 369")
        ]

        # 2. Tìm Điều 12 BLHS (Tuổi chịu TNHS) và Điều 586 BLDS (Bồi thường dân sự) trong kho tri thức
        art12_doc = None
        art586_doc = None
        if hasattr(retriever, "records") and retriever.records:
            for r in retriever.records:
                if not art12_doc and r.get("article") == "Điều 12" and "hình sự" in r.get("law_name", "").lower():
                    art12_doc = dict(r)
                if not art586_doc and r.get("article") == "Điều 586" and "dân sự" in r.get("law_name", "").lower():
                    art586_doc = dict(r)

        # 3. Đưa Điều 12 BLHS lên vị trí ưu tiên số 1
        new_docs = []
        if art12_doc:
            new_docs.append(art12_doc)
        if art586_doc:
            new_docs.append(art586_doc)

        for d in filtered_docs:
            if d.get("article") not in ("Điều 12", "Điều 586"):
                new_docs.append(d)

        retrieved_docs = new_docs[:top_k]
        logger.info(f"[RetrieveNode] Đã ưu tiên nạp Điều 12 BLHS và Điều 586 BLDS cho đối tượng {premise_correction.get('age')} tuổi.")

    return {
        "retrieved_docs": retrieved_docs,
    }
