"""Node viết lại và mở rộng truy vấn khi tài liệu chưa đạt yêu cầu (Query Rewriter Node)."""
from __future__ import annotations

import logging
from typing import Any, Dict
from src.agent.llm_client import LLMClient
from src.agent.state import LegalAgentState
from src.retrieval.query_rewriter import QueryRewriter

logger = logging.getLogger(__name__)


async def rewrite_query_node(state: LegalAgentState, llm: LLMClient) -> Dict[str, Any]:
    """Tự động viết lại câu hỏi đời thường thành thuật ngữ pháp lý chuẩn để tìm kiếm lại (CRAG Loop)."""
    query = state.get("standalone_query") or state["query"]
    history = list(state.get("history") or [])
    retry_count = state.get("retry_count", 0) + 1

    logger.info(f"[RewriteQueryNode] Kích hoạt Corrective RAG Loop! Viết lại query (Lần {retry_count}): '{query}'")

    rewriter = QueryRewriter(llm=llm)
    rewritten_query = await rewriter.rewrite(query=query, history=history)

    # Đảm bảo câu hỏi có sự thay đổi
    if not rewritten_query or rewritten_query.strip() == query.strip():
        rewritten_query = f"Quy định pháp luật và xử lý hành vi liên quan đến {query}"

    logger.info(f"[RewriteQueryNode] -> Query mới sau khi viết lại: '{rewritten_query}'")

    return {
        "standalone_query": rewritten_query,
        "sub_queries": [rewritten_query],
        "retry_count": retry_count,
        "hypothetical_passage": None,  # Reset HyDE để tìm kiếm theo query mới
    }
