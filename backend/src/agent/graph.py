"""Định nghĩa StateGraph hoàn chỉnh cho Legal Assistant Agent bằng LangGraph (Agentic RAG)."""
from __future__ import annotations

import logging
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, START, END

from src.agent.llm_client import LLMClient
from src.agent.nodes.applicability_validator_node import applicability_validator_node
from src.agent.nodes.inapplicability_node import inapplicability_node
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
from src.retrieval.hyde import HydeGenerator
from src.nlp.query_decomposer import QueryDecomposer
from src.nlp.spell_corrector import SpellCorrector

logger = logging.getLogger(__name__)


def route_intent(state: LegalAgentState) -> str:
    """Conditional edge định tuyến theo ý định (Intent Router)."""
    intent = state.get("intent", "legal_query")
    if intent == "smalltalk":
        return "smalltalk_node"
    elif intent == "out_of_scope":
        return "out_of_scope_node"
    return "applicability_validator_node"


def route_applicability(state: LegalAgentState) -> str:
    """Conditional edge kiểm định điều kiện áp dụng pháp luật (Eligibility Hard Gate)."""
    status = state.get("eligibility_status", "ALLOWED")
    if status == "BLOCKED":
        logger.warning(
            "[GraphRouter] Điều kiện áp dụng bị CHẶN (BLOCKED). Chuyển sang inapplicability_node để hướng dẫn chế tài thay thế."
        )
        return "inapplicability_node"
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

        # ── Cache các helper stateless — khởi tạo 1 lần, dùng mãi ──────────
        # Các class này nhận llm nhưng không giữ state request → an toàn để share
        self.spell_corrector = SpellCorrector(llm=self.llm)
        self.query_decomposer = QueryDecomposer(llm=self.llm)
        self.hyde_generator = HydeGenerator(llm=self.llm)

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

        async def _applicability_node(state: LegalAgentState):
            return await applicability_validator_node(state)

        async def _inapplicability_node(state: LegalAgentState):
            return await inapplicability_node(state)

        async def _decompose_node(state: LegalAgentState):
            return await decompose_node(
                state,
                self.llm,
                spell_corrector=self.spell_corrector,
                query_decomposer=self.query_decomposer,
                hyde_generator=self.hyde_generator,
                records=self.retriever.records,
            )

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
        graph.add_node("applicability_validator_node", _applicability_node)
        graph.add_node("inapplicability_node", _inapplicability_node)
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
                "applicability_validator_node": "applicability_validator_node",
            },
        )
        graph.add_edge("smalltalk_node", END)
        graph.add_edge("out_of_scope_node", END)

        # Chốt chặn điều kiện áp dụng pháp luật (Hard Gate)
        graph.add_conditional_edges(
            "applicability_validator_node",
            route_applicability,
            {
                "inapplicability_node": "inapplicability_node",
                "decompose_node": "decompose_node",
            },
        )
        # Nhánh bị chặn kết thúc trực tiếp (bảo toàn 100% quyết định pháp lý từ Rule Engine, không loop qua RAG/Guard)
        graph.add_edge("inapplicability_node", END)

        # Luồng RAG cốt lõi (chỉ thực hiện khi qua được Applicability Gate)
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
            "legal_facts": None,
            "eligibility_status": "ALLOWED",
            "blocking_factors": [],
            "applicable_rules": [],
            "fact_ambiguities": [],
            "legal_decision": None,
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

    async def invoke_for_stream(
        self,
        query: str,
        session_id: str = "default",
        history: list[dict] | None = None,
        on_progress: Any = None,
    ) -> LegalAgentState:
        """Chạy toàn bộ pipeline RAG (Intent → Applicability Gate → Decompose → Retrieve → CRAG loop) nhưng
        KHÔNG chạy GenerateNode — trả về context state để caller tự stream generate.

        Hỗ trợ on_progress callback để phát tín hiệu SSE tiến trình thật 100% về UI.
        """
        from src.agent.nodes.intent_router import intent_router_node
        from src.agent.nodes.grade_documents_node import grade_documents_node
        from src.agent.nodes.rewrite_query_node import rewrite_query_node

        # Chuẩn bị state ban đầu
        state: dict = {
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
            "legal_facts": None,
            "eligibility_status": "ALLOWED",
            "blocking_factors": [],
            "applicable_rules": [],
            "fact_ambiguities": [],
            "legal_decision": None,
            "error": None,
        }

        if history is not None:
            state["history"] = history
        else:
            try:
                persisted = self.session_manager.get_session(session_id)
                if persisted and persisted.get("messages"):
                    state["history"] = [
                        {"role": m["role"], "content": m["content"]}
                        for m in persisted["messages"]
                    ]
                else:
                    state["history"] = []
            except Exception:
                state["history"] = []

        # ── Node 1: Intent Router ──────────────────────────────────────────
        if on_progress:
            await on_progress({
                "stage": 0,
                "percent": 15,
                "message": "Đang phân tích câu hỏi & xác định ý định pháp lý...",
            })

        state.update(await intent_router_node(state, self.llm))
        intent = state.get("intent", "legal_query")

        # Non-legal intents: Xử lý phản hồi trực tiếp, không cần tốn tài nguyên truy hồi RAG
        if intent == "smalltalk":
            if on_progress:
                await on_progress({
                    "stage": 0,
                    "percent": 50,
                    "message": "Nhận diện câu hỏi chào hỏi xã giao...",
                })
            from src.agent.nodes.smalltalk_node import smalltalk_node
            state.update(await smalltalk_node(state, self.llm))
            return state
        elif intent == "out_of_scope":
            if on_progress:
                await on_progress({
                    "stage": 0,
                    "percent": 50,
                    "message": "Nhận diện câu hỏi ngoài phạm vi nghiệp vụ pháp lý...",
                })
            from src.agent.nodes.out_of_scope_node import out_of_scope_node
            state.update(await out_of_scope_node(state))
            return state

        if on_progress:
            await on_progress({
                "stage": 0,
                "percent": 30,
                "message": "Đã xác định ý định: Tra cứu quy định pháp luật Việt Nam",
            })

        # ── Node 1.5: Applicability Validator (Legal Rule Engine Gate) ───
        if on_progress:
            await on_progress({
                "stage": 0,
                "percent": 35,
                "message": "Đang kiểm định điều kiện chủ thể & quy tắc áp dụng pháp luật (Rule Engine)...",
            })

        state.update(await applicability_validator_node(state))
        if state.get("eligibility_status") == "BLOCKED":
            if on_progress:
                await on_progress({
                    "stage": 1,
                    "percent": 75,
                    "message": "Phát hiện điều kiện loại trừ trách nhiệm hình sự (Điều 12 BLHS) - Chuyển sang tư vấn chế tài thay thế...",
                })
            state.update(await inapplicability_node(state))
            if on_progress:
                await on_progress({
                    "stage": 2,
                    "percent": 100,
                    "message": "Đã hoàn tất thẩm tra quy tắc pháp lý và biên soạn giải pháp thay thế.",
                })
            return state

        # ── Node 2: Decompose (spell-correct, HyDE, sub-queries) ──────────
        if on_progress:
            await on_progress({
                "stage": 1,
                "percent": 45,
                "message": "Đang mở rộng thuật ngữ & sinh giả định pháp lý (HyDE)...",
            })

        state.update(await decompose_node(
            state,
            self.llm,
            spell_corrector=self.spell_corrector,
            query_decomposer=self.query_decomposer,
            hyde_generator=self.hyde_generator,
            records=self.retriever.records,
        ))

        # ── Node 3–4: Retrieve + CRAG loop (tối đa 2 lần) ─────────────────
        if on_progress:
            await on_progress({
                "stage": 1,
                "percent": 65,
                "message": "Đang quét 13.744 điều luật qua BM25 và pgvector (HNSW)...",
            })

        max_crag_retries = 2
        for attempt in range(max_crag_retries + 1):
            state.update(await retrieve_node(state, self.retriever))

            if on_progress:
                docs_count = len(state.get("retrieved_docs") or [])
                await on_progress({
                    "stage": 2,
                    "percent": 78,
                    "message": f"Đã truy hồi {docs_count} tài liệu ứng viên. Đang tái xếp hạng (Cross-Encoder)...",
                })

            state.update(await grade_documents_node(state))

            if state.get("docs_grade") == "relevant" or attempt >= max_crag_retries:
                break

            # Docs chưa đủ tốt → rewrite và thử lại
            logger.info(f"[Stream] CRAG loop lần {attempt + 1}: rewrite query và retrieve lại.")
            if on_progress:
                await on_progress({
                    "stage": 2,
                    "percent": 72,
                    "message": f"Độ khớp chưa tối ưu, đang viết lại truy vấn (CRAG lần {attempt + 1})...",
                })
            state.update(await rewrite_query_node(state, self.llm))
            state["retry_count"] = attempt + 1

        if on_progress:
            docs_count = len(state.get("retrieved_docs") or [])
            await on_progress({
                "stage": 2,
                "percent": 88,
                "message": f"Đã chọn lọc {docs_count} điều luật có độ tin cậy cao nhất.",
            })

        return state
