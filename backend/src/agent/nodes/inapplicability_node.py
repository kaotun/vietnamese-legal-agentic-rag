"""Node giải thích lý do không áp dụng và hướng dẫn các chế tài thay thế (Inapplicability Explainer Node).

Được kích hoạt khi Applicability Validator trả về trạng thái 'BLOCKED'.
Chặn hoàn toàn việc tính toán án tù (Stop Punishment Path), sử dụng quyết định pháp lý
đã được kiểm chứng từ Legal Rule Engine và cung cấp hướng xử lý dân sự/hành chính thay thế.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from src.agent.state import LegalAgentState

logger = logging.getLogger(__name__)


async def inapplicability_node(state: LegalAgentState) -> Dict[str, Any]:
    """Tạo lập văn bản tư vấn pháp lý chuẩn 4 phần khi điều kiện chủ thể bị loại trừ (BLOCKED)."""
    query = state["query"]
    history = list(state.get("history") or [])
    decision = state.get("legal_decision") or {}
    facts = state.get("legal_facts") or {}
    ambiguities = state.get("fact_ambiguities") or []

    logger.warning(
        f"[InapplicabilityNode] Kích hoạt nhánh giải thích loại trừ hình phạt cho query: '{query}'. "
        f"Lý do: {decision.get('reason')}"
    )

    conclusion = decision.get(
        "primary_conclusion",
        "Đối tượng trong câu hỏi không thuộc diện áp dụng chế tài hình sự theo quy định pháp luật."
    )
    governing_basis = decision.get("governing_law_basis", "Quy định pháp luật hiện hành.")
    analysis_points = decision.get("analysis_points", [])
    remedy_laws = decision.get("remedy_laws", [])
    guidance = decision.get(
        "practical_guidance",
        "Các bên liên quan cần tham khảo ý kiến luật sư hoặc cơ quan có thẩm quyền để giải quyết thỏa đáng hậu quả dân sự."
    )

    # 1. Xây dựng phần 1: Kết luận trực diện
    sec1 = f"### 1. Kết luận\n{conclusion}\n"

    # 2. Xây dựng phần 2: Căn cứ pháp lý
    basis_lines = []
    citations = []
    enriched_docs = []

    for r in remedy_laws:
        law_name = r.get("law", "")
        article = r.get("article", "")
        title = r.get("title", "")
        role = r.get("role", "")
        cit_str = f"{article} - {law_name}"
        citations.append(cit_str)
        basis_lines.append(f"- **{article} {law_name}** ({title}): {role}.")

        enriched_docs.append({
            "law_name": law_name,
            "article": article,
            "title": title,
            "citation": cit_str,
            "content": f"{article} {law_name} quy định về {title}. {role}.",
        })

    sec2 = "### 2. Căn cứ pháp lý\n" + "\n".join(basis_lines) + "\n"

    # 3. Xây dựng phần 3: Phân tích & Chi tiết áp dụng
    analysis_body = []
    for pt in analysis_points:
        analysis_body.append(f"- {pt}")

    # Bổ sung phân tích Fact Ambiguity nếu có
    if ambiguities:
        analysis_body.append(
            f"- **Lưu ý về tính xác định của dữ kiện (Fact Ambiguity)**: "
            f"{ambiguities[0]}"
        )

    sec3 = "### 3. Phân tích & Chi tiết áp dụng\n" + "\n".join(analysis_body) + "\n"

    # 4. Xây dựng phần 4: Hướng dẫn & Lưu ý thực tiễn
    sec4 = f"### 4. Hướng dẫn & Lưu ý thực tiễn\n{guidance}\n"

    full_answer = f"{sec1}\n{sec2}\n{sec3}\n{sec4}".strip()

    # Tạo câu hỏi gợi ý đào sâu
    age_str = str(facts.get("age", "12"))
    followup_questions = [
        f"Điều kiện đưa người từ đủ 12 đến dưới 14 tuổi vào trường giáo dưỡng theo Luật XLVPHC?",
        f"Trách nhiệm bồi thường thiệt hại của cha mẹ theo Điều 586 Bộ luật Dân sự 2015?",
        f"Các biện pháp xử lý chuyển hướng người chưa thành niên theo Luật Tư pháp người chưa thành niên 2024?",
    ]

    updated_history = list(history)
    updated_history.append({"role": "user", "content": query})
    updated_history.append({"role": "assistant", "content": full_answer})

    return {
        "answer": full_answer,
        "citations": citations,
        "retrieved_docs": enriched_docs,
        "history": updated_history,
        "followup_questions": followup_questions,
        "guard_status": "passed",
        "correction_feedback": None,
    }
