"""Định nghĩa StateGraph hoàn chỉnh cho Legal Assistant Agent bằng LangGraph."""
from __future__ import annotations

import logging
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, START, END

from src.agent.llm_client import LLMClient
from src.agent.nodes.citation_guard_node import citation_guard_node
from src.agent.nodes.intent_router import intent_router_node
from src.agent.nodes.legal_rag_node import legal_rag_node
from src.agent.nodes.out_of_scope_node import out_of_scope_node
from src.agent.nodes.smalltalk_node import smalltalk_node
from src.agent.state import LegalAgentState
from src.agent.session_manager import SessionManager
from src.retrieval.hybrid_retriever import HybridLegalRetriever

logger = logging.getLogger(__name__)


def route_intent(state: LegalAgentState) -> str:
    """Conditional edge định tuyến theo intent đã phân loại."""
    intent = state.get("intent", "legal_query")
    if intent == "smalltalk":
        return "smalltalk_node"
    elif intent == "out_of_scope":
        return "out_of_scope_node"
    return "legal_rag_node"


class LegalAgent:
    """Agent hỏi đáp pháp luật Việt Nam quản lý bởi LangGraph có trí nhớ hội thoại (Conversational Memory)."""

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

        # 1. Thêm các Node
        async def _intent_node(state: LegalAgentState):
            return await intent_router_node(state, self.llm)

        async def _smalltalk_node(state: LegalAgentState):
            return await smalltalk_node(state, self.llm)

        async def _out_of_scope_node(state: LegalAgentState):
            return await out_of_scope_node(state)

        async def _legal_rag_node(state: LegalAgentState):
            return await legal_rag_node(state, self.retriever, self.llm)

        async def _guard_node(state: LegalAgentState):
            return await citation_guard_node(state)

        graph.add_node("intent_router", _intent_node)
        graph.add_node("smalltalk_node", _smalltalk_node)
        graph.add_node("out_of_scope_node", _out_of_scope_node)
        graph.add_node("legal_rag_node", _legal_rag_node)
        graph.add_node("citation_guard_node", _guard_node)

        # 2. Thêm các Edge
        graph.add_edge(START, "intent_router")
        graph.add_conditional_edges(
            "intent_router",
            route_intent,
            {
                "smalltalk_node": "smalltalk_node",
                "out_of_scope_node": "out_of_scope_node",
                "legal_rag_node": "legal_rag_node",
            },
        )
        graph.add_edge("smalltalk_node", END)
        graph.add_edge("out_of_scope_node", END)
        graph.add_edge("legal_rag_node", "citation_guard_node")
        graph.add_edge("citation_guard_node", END)

        return graph

    async def invoke(
        self,
        query: str,
        session_id: str = "default",
        history: list[dict] | None = None
    ) -> LegalAgentState:
        """Thực thi toàn bộ luồng agent cho một câu hỏi có hỗ trợ trí nhớ phiên hội thoại."""
        config = {"configurable": {"thread_id": session_id}}

        initial_state: dict = {
            "query": query,
            "session_id": session_id,
            "intent": "",
            "retrieved_docs": [],
            "answer": "",
            "citations": [],
            "guard_status": "passed",
            "error": None,
        }

        # Nếu client truyền sẵn history từ ngoài vào (stateless mode), ghi đè vào state
        if history is not None:
            initial_state["history"] = history
        else:
            # Nếu trong RAM checkpointer chưa có lịch sử, kiểm tra và nạp từ persistent SessionManager
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
