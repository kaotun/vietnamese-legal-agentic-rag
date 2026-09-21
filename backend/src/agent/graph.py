"""Định nghĩa StateGraph hoàn chỉnh cho Legal Assistant Agent bằng LangGraph (Agentic RAG)."""
from __future__ import annotations

import logging
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, START, END

from src.agent.llm_client import LLMClient
from src.agent.nodes.citation_guard_node import citation_guard_node
from src.agent.nodes.decompose_node import decompose_node
from src.agent.nodes.generate_node import generate_node
from src.agent.nodes.grade_documents_node import grade_documents_node
from src.agent.nodes.intent_router import intent_router_node
from src.agent.nodes.out_of_scope_node import out_of_scope_node
from src.agent.nodes.retrieve_node import retrieve_node
from src.agent.nodes.rewrite_query_node import rewrite_query_node
from src.agent.nodes.self_correct_node import self_correct_node
from src.agent.nodes.smalltalk_node import smalltalk_node
from src.agent.state import LegalAgentState
from src.agent.session_manager import SessionManager
from src.retrieval.hybrid_retriever import HybridLegalRetriever

logger = logging.getLogger(__name__)


def route_intent(state: LegalAgentState) -> str:
    """Conditional edge định tuyến theo ý định (Intent Router)."""
    intent = state.get("intent", "legal_query")
    if intent == "smalltalk":
        return "smalltalk_node"
    elif intent == "out_of_scope":
        return "out_of_scope_node"
    return "decompose_node"


def route_documents_grade(state: LegalAgentState) -> str:
    """Conditional edge đánh giá tài liệu (Corrective RAG - CRAG Loop)."""
    grade = state.get("docs_grade", "relevant")
    retry_count = state.get("retry_count", 0)
    if grade == "irrelevant" and retry_count < 2:
        logger.info(f"[GraphRouter] Tài liệu chưa tối ưu (Lần {retry_count + 1}). Chuyển sang rewrite_query_node để tìm lại.")
        return "rewrite_query_node"
    return "generate_node"


def route_citation_guard(state: LegalAgentState) -> str:
    """Conditional edge kiểm định căn cứ pháp lý và chống ảo giác (Self-RAG Loop)."""
    status = state.get("guard_status", "passed")
    retry_count = state.get("retry_count", 0)
    if status == "retry" and retry_count < 2:
        logger.info(f"[GraphRouter] Phát hiện trích dẫn sai (Lần {retry_count + 1}). Chuyển sang self_correct_node để sinh lại.")
        return "self_correct_node"
    return END


class LegalAgent:
    """Agent hỏi đáp pháp luật Việt Nam quản lý bởi LangGraph theo kiến trúc Agentic RAG (Self-RAG & CRAG)."""

    def __init__(
        self,
        retriever: HybridLegalRetriever | None = None,
        llm: LLMClient | None = None,
        checkpointer: MemorySaver | None = None,
        session_manager: SessionManager | None = None,
    ):
        self.retriever = retriever or HybridLegalRetriever()
        self.llm = llm or LLMClient()
        self.checkpointer = checkpointer if checkpointer is not None else MemorySaver()
        self.session_manager = session_manager or SessionManager()
        self.workflow = self._build_graph()
        self.app = self.workflow.compile(checkpointer=self.checkpointer)

    def _build_graph(self) -> StateGraph:
        graph = StateGraph(LegalAgentState)

        # 1. Khai báo các Nodes của hệ thống Agentic RAG
        async def _intent_node(state: LegalAgentState):
            return await intent_router_node(state, self.llm)

        async def _smalltalk_node(state: LegalAgentState):
            return await smalltalk_node(state, self.llm)

        async def _out_of_scope_node(state: LegalAgentState):
            return await out_of_scope_node(state)

        async def _decompose_node(state: LegalAgentState):
            return await decompose_node(state, self.llm)

        async def _retrieve_node(state: LegalAgentState):
            return await retrieve_node(state, self.retriever)

        async def _grade_docs_node(state: LegalAgentState):
            return await grade_documents_node(state)

        async def _rewrite_query_node(state: LegalAgentState):
            return await rewrite_query_node(state, self.llm)

        async def _generate_node(state: LegalAgentState):
            return await generate_node(state, self.llm)

        async def _guard_node(state: LegalAgentState):
            return await citation_guard_node(state)

        async def _self_correct_node(state: LegalAgentState):
            return await self_correct_node(state)

        # Thêm Nodes vào đồ thị
        graph.add_node("intent_router", _intent_node)
        graph.add_node("smalltalk_node", _smalltalk_node)
        graph.add_node("out_of_scope_node", _out_of_scope_node)
        graph.add_node("decompose_node", _decompose_node)
        graph.add_node("retrieve_node", _retrieve_node)
        graph.add_node("grade_documents_node", _grade_docs_node)
        graph.add_node("rewrite_query_node", _rewrite_query_node)
        graph.add_node("generate_node", _generate_node)
        graph.add_node("citation_guard_node", _guard_node)
        graph.add_node("self_correct_node", _self_correct_node)

        # 2. Xây dựng các Cạnh và Vòng lặp phản hồi (Edges & Feedback Loops)
        # Entry point
        graph.add_edge(START, "intent_router")

        # Rẽ nhánh theo ý định
        graph.add_conditional_edges(
            "intent_router",
            route_intent,
            {
                "smalltalk_node": "smalltalk_node",
                "out_of_scope_node": "out_of_scope_node",
                "decompose_node": "decompose_node",
            },
        )
        graph.add_edge("smalltalk_node", END)
        graph.add_edge("out_of_scope_node", END)

        # Luồng RAG cốt lõi
        graph.add_edge("decompose_node", "retrieve_node")
        graph.add_edge("retrieve_node", "grade_documents_node")

        # VÒNG LẶP 1: Corrective RAG (CRAG)
        graph.add_conditional_edges(
            "grade_documents_node",
            route_documents_grade,
            {
                "rewrite_query_node": "rewrite_query_node",
                "generate_node": "generate_node",
            },
        )
        graph.add_edge("rewrite_query_node", "retrieve_node")  # Loop back để truy hồi lại

        # Luồng sinh câu trả lời và kiểm định
        graph.add_edge("generate_node", "citation_guard_node")

        # VÒNG LẶP 2: Self-Correction (Self-RAG)
        graph.add_conditional_edges(
            "citation_guard_node",
            route_citation_guard,
            {
                "self_correct_node": "self_correct_node",
                END: END,
            },
        )
        graph.add_edge("self_correct_node", "generate_node")  # Loop back để LLM sinh lại

        return graph

    async def invoke(
        self,
        query: str,
        session_id: str = "default",
        history: list[dict] | None = None
    ) -> LegalAgentState:
        """Thực thi toàn bộ luồng Agentic RAG cho câu hỏi có hỗ trợ trí nhớ phiên hội thoại."""
        config = {"configurable": {"thread_id": session_id}}

        initial_state: dict = {
            "query": query,
            "session_id": session_id,
            "intent": "",
            "retrieved_docs": [],
            "answer": "",
            "citations": [],
            "guard_status": "passed",
            "retry_count": 0,
            "docs_grade": None,
            "hallucinated_articles": [],
            "correction_feedback": None,
            "hypothetical_passage": None,
            "error": None,
        }

        if history is not None:
            initial_state["history"] = history
        else:
            try:
                current_state = await self.app.aget_state(config)
                if not current_state or not current_state.values.get("history"):
                    persisted = self.session_manager.get_session(session_id)
                    if persisted and persisted.get("messages"):
                        initial_state["history"] = [
                            {"role": m["role"], "content": m["content"]}
                            for m in persisted["messages"]
                        ]
            except Exception as e:
                logger.debug(f"Không thể kiểm tra state trước đó: {e}")

        final_state = await self.app.ainvoke(initial_state, config=config)

        # Tự động lưu lượt hỏi - đáp mới vào SessionManager
        try:
            self.session_manager.save_turn(
                session_id=session_id,
                user_query=query,
                assistant_answer=final_state.get("answer", ""),
                intent=final_state.get("intent", "legal_query"),
                citations=final_state.get("citations", []),
                standalone_query=final_state.get("standalone_query"),
                followup_questions=final_state.get("followup_questions", []),
                retrieved_docs=final_state.get("retrieved_docs", []),
            )
        except Exception as e:
            logger.error(f"Lỗi khi lưu turn vào session_manager: {e}")

        return final_state
