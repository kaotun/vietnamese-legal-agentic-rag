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
    return {
        "retrieved_docs": retrieved_docs,
    }
