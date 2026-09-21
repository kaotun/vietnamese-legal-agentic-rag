"""Node sinh câu trả lời pháp lý chuẩn cấu trúc 4 phần bằng LLM (Generation Node)."""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List
from src.agent.llm_client import LLMClient
from src.agent.state import LegalAgentState

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Bạn là Chuyên gia Tư vấn Pháp luật Việt Nam chuẩn xác, khách quan và chuyên sâu.
Nhiệm vụ: Giải đáp câu hỏi của người dùng CHI TIẾT, ĐẦY ĐỦ VÀ CHUẨN XÁC dựa trên các đoạn trích Điều luật trong [NGỮ CẢNH PHÁP LÝ].
TUYỆT ĐỐI KHÔNG tự suy diễn, không bịa đặt số Điều hay nội dung luật không có trong ngữ cảnh.

QUY TẮC CẤU TRÚC 4 PHẦN CHUẨN (KHÔNG LẶP LẠI & BÁM SÁT ĐIỀU LUẬT):

### 1. Kết luận
- Viết từ 1 đến 2 câu nhận định trực diện, trả lời thẳng vào câu hỏi của người dùng (tóm tắt quy định/thời hạn/mức xử phạt áp dụng).
- TUYỆT ĐỐI KHÔNG liệt kê danh sách gạch đầu dòng ở Phần 1 (để tránh trùng lặp với Phần 3).

### 2. Căn cứ pháp lý
- Ghi rõ ràng: Điều [số điều] [Tên văn bản luật] áp dụng trực tiếp có trong ngữ cảnh.
- TUYỆT ĐỐI CHỈ trích dẫn các Điều luật có trong [NGỮ CẢNH PHÁP LÝ] của câu hỏi hiện tại.

### 3. Phân tích & Chi tiết áp dụng
- Trình bày ĐẦY ĐỦ, CẶN KẼ theo từng Khoản và từng Điểm (a, b, c, d...) hoặc các mốc quy định/thời hạn/mức chế tài nguyên vẹn như văn bản luật trong ngữ cảnh:
  + Đối với quy định quyền, nghĩa vụ, thời hạn, thủ tục (Dân sự, Lao động, Doanh nghiệp, Đất đai...): Trình bày rõ từng trường hợp, từng đối tượng, điều kiện và thời hạn cụ thể.
  + Đối với vi phạm hành chính hoặc hình sự: Nêu rõ từng khung chế tài, mức phạt tiền hoặc hình phạt tù tương ứng cho từng hành vi vi phạm.
- Mỗi Khoản/nhóm chỉ nêu mức quy định chung một lần ở đầu mục, sau đó liệt kê các điểm con. Không lặp lại cụm từ cố định cho từng gạch đầu dòng.

### 4. Hướng dẫn & Lưu ý thực tiễn
- Nêu rõ hướng dẫn thực tiễn cho người dân hoặc các bên liên quan:
  + Cơ quan có thẩm quyền giải quyết/xử lý.
  + Quyền và nghĩa vụ của các bên, thủ tục cần chuẩn bị, hoặc các tình tiết giảm nhẹ/khắc phục hậu quả (nếu là vi phạm).
  + Lời khuyên pháp lý thiết thực.

NGUYÊN TẮC TRÌNH BÀY TỰ NHIÊN & CHỐNG LẶP:
- TUYỆT ĐỐI KHÔNG sử dụng các nhãn nội bộ như "[TÀI LIỆU 1]", "[TÀI LIỆU 2]", "[NGUỒN 1]" trong câu trả lời. Hãy trích dẫn tự nhiên theo tên Điều luật và văn bản pháp luật thực tế.
- TUYỆT ĐỐI CHỈ trích dẫn các Điều luật có trong [NGỮ CẢNH PHÁP LÝ] của câu hỏi hiện tại.
- TUYỆT ĐỐI KHÔNG lặp lại các gạch đầu dòng có nội dung tương tự nhau. Không liệt kê vô tận các chữ cái (a, b, c... z, aa...). Mỗi hành vi, mỗi chế tài chỉ xuất hiện MỘT LẦN duy nhất trong toàn bộ câu trả lời.

Ở cuối câu trả lời, luôn thêm phần gợi ý (2-3 câu hỏi đào sâu):
[GỢI Ý CÂU HỎI TIẾP THEO]:
- [Câu hỏi liên quan mà người hỏi có thể quan tâm tiếp]
- [Câu hỏi liên quan mà người hỏi có thể quan tâm tiếp]
"""

COMMON_LEGAL_STOPWORDS = {
    "phạt", "tiền", "đồng", "đối", "với", "người", "điều", "khiển", "hành", "vi",
    "sau", "đây", "theo", "quy", "định", "tại", "khoản", "luật", "này", "khi",
    "tham", "gia", "thực", "hiện", "trong", "trường", "hợp", "hoặc", "không",
    "các", "loại", "cho", "của", "được", "bao", "nhiêu", "như", "thế", "nào",
    "một", "những", "có", "thể", "bị", "bởi", "về", "và", "là", "đã", "sẽ",
    "mức", "xử", "chính", "tổng", "hợp", "cùng", "lúc",
}


def extract_relevant_snippet(content: str, target_queries: list[str], max_chars: int = 3500) -> str:
    """Trích xuất thông minh các Khoản và Điểm liên quan dựa trên Smart Windowing."""
    if len(content) <= 3500:
        return content

    clauses = re.split(r"(?:\n|^)(?=\d+\.\s+)", content)
    selected_indices = set()

    for q in target_queries:
        q_clean = q.lower()
        q_words = [w for w in re.findall(r"\b[\w\d_]+\b", q_clean) if len(w) > 1 and w not in COMMON_LEGAL_STOPWORDS]

        best_idx = None
        best_score = -1

        for idx, c in enumerate(clauses):
            c_lower = c.lower()
            sc = 0
            for w in q_words:
                if w in c_lower:
                    sc += 8
            if len(q_clean) > 8 and any(token in c_lower for token in [q_clean[:20], q_clean[-20:]]):
                sc += 15

            if sc > best_score and sc > 12:
                best_score = sc
                best_idx = idx

        if best_idx is not None:
            selected_indices.add(best_idx)

    for idx, c in enumerate(clauses):
        c_lower = c.lower()
        if "trừ điểm giấy phép lái xe" in c_lower or "tước quyền sử dụng" in c_lower:
            for sel_idx in list(selected_indices):
                sel_clause_num = sel_idx + 1
                if f"khoản {sel_clause_num}" in c_lower:
                    selected_indices.add(idx)

    if len(selected_indices) > 4:
        selected_indices = set(sorted(selected_indices)[:4])

    if not selected_indices:
        all_words = []
        for q in target_queries:
            all_words.extend([w for w in re.findall(r"\b[\w\d_]+\b", q.lower()) if len(w) > 1 and w not in COMMON_LEGAL_STOPWORDS])
        scored = []
        for idx, c in enumerate(clauses):
            c_lower = c.lower()
            sc = sum(1 for w in all_words if w in c_lower)
            if sc > 0:
                scored.append((sc, idx))
        scored.sort(key=lambda x: x[0], reverse=True)
        selected_indices = {item[1] for item in scored[:3]}

    formatted_clauses = []
    for idx in sorted(selected_indices):
        c = clauses[idx].strip()
        norm_c = re.sub(r"^(\d+)\.\s*", r"Khoản \1: ", c)
        formatted_clauses.append(norm_c)

    if formatted_clauses:
        result = "\n\n---\n\n".join(formatted_clauses)
        return result[:max_chars]

    return content[:max_chars] + "\n...(còn tiếp)"


def _clean_all_repetition(text: str) -> str:
    """Khử triệt để các chu kỳ lặp nội dung."""
    lines = text.split("\n")
    if len(lines) < 2:
        return text

    def _norm(l: str) -> str:
        s = l.strip().lower()
        while True:
            new_s = re.sub(r'^(?:[\-\*\•\+–—]|\d+[\.\)]|[a-zA-Z]{1,8}[\.\)]|\[\s*[^\]]*\]|[^\w\s]\s*|\([a-zA-Z0-9]+\))\s*', '', s).strip()
            if new_s == s:
                break
            s = new_s
        s = re.sub(r'[;,\.]+$', '', s).strip()
        return s

    norm_lines = [_norm(l) for l in lines]
    result_lines = []
    i = 0
    while i < len(lines):
        matched = False
        for period in range(1, 12):
            if i + 2 * period <= len(lines):
                pattern = norm_lines[i : i + period]
                if all(len(p) > 5 for p in pattern):
                    next_block = norm_lines[i + period : i + 2 * period]
                    if pattern == next_block:
                        k = 2
                        while i + (k + 1) * period <= len(lines):
                            if norm_lines[i + k * period : i + (k + 1) * period] == pattern:
                                k += 1
                            else:
                                break
                        result_lines.extend(lines[i : i + period])
                        i += k * period
                        matched = True
                        break
        if not matched:
            result_lines.append(lines[i])
            i += 1

    final_lines = []
    seen_in_section = set()
    for l in result_lines:
        trimmed = l.strip()
        if trimmed.startswith("#"):
            seen_in_section.clear()
            final_lines.append(l)
            continue

        nl = _norm(l)
        if len(nl) > 10 and (trimmed.startswith("-") or trimmed.startswith("*") or re.match(r"^[a-zA-Z0-9\(\)]+[\.\)]", trimmed)):
            if nl in seen_in_section:
                continue
            seen_in_section.add(nl)
        final_lines.append(l)

    return "\n".join(final_lines)


async def generate_node(state: LegalAgentState, llm: LLMClient) -> Dict[str, Any]:
    """Node tổng hợp tri thức pháp luật và sinh câu trả lời có cấu trúc 4 phần bằng LLM."""
    query = state["query"]
    standalone_query = state.get("standalone_query") or query
    sub_queries = state.get("sub_queries") or [standalone_query]
    is_multi = state.get("is_multi_violation", False)
    history = list(state.get("history") or [])
    retrieved_docs = state.get("retrieved_docs") or []
    correction_feedback = state.get("correction_feedback")

    logger.info(f"[GenerateNode] Bắt đầu sinh câu trả lời cho: '{query}' (Docs: {len(retrieved_docs)})")

    if not retrieved_docs:
        fallback_answer = (
            "### 1. Kết luận\nHiện tại hệ thống chưa tìm thấy văn bản quy phạm pháp luật trực tiếp phù hợp trong cơ sở dữ liệu để giải đáp câu hỏi của bạn.\n\n"
            "### 2. Căn cứ pháp lý\nChưa có căn cứ trích dẫn trực tiếp.\n\n"
            "### 3. Chi tiết áp dụng\nVui lòng cung cấp thêm từ khóa hoặc diễn đạt chi tiết hơn để được tra cứu chính xác.\n\n"
            "### 4. Lưu ý thực tiễn\nBạn nên tham khảo ý kiến luật sư hoặc cơ quan có thẩm quyền đối với các vụ việc cụ thể."
        )
        updated_history = list(history)
        updated_history.append({"role": "user", "content": query})
        updated_history.append({"role": "assistant", "content": fallback_answer})
        return {
            "answer": fallback_answer,
            "citations": [],
            "retrieved_docs": [],
            "history": updated_history,
            "guard_status": "warning",
            "correction_feedback": None,
        }

    # 1. Trích xuất ngữ cảnh và Smart Windowing
    context_blocks = []
    citations = []
    enriched_docs = []
    target_queries = sub_queries if (is_multi and len(sub_queries) > 1) else [standalone_query, query]
    max_docs_for_prompt = 4 if (is_multi and len(sub_queries) > 1) else 2

    for i, doc in enumerate(retrieved_docs[:max_docs_for_prompt], 1):
        law_name = doc.get("law_name", "")
        article = doc.get("article", "")
        title = doc.get("article_title", "")
        raw_content = doc.get("content", "")

        focused_content = extract_relevant_snippet(raw_content, target_queries, max_chars=3500)
        citation_str = f"{article} ({title}) - {law_name}" if title else f"{article} - {law_name}"
        citations.append(citation_str)

        doc_info = dict(doc)
        doc_info["citation"] = citation_str
        doc_info["article_number"] = f"{article}: {title}" if title else article
        doc_info["text"] = raw_content
        doc_info["content"] = raw_content
        doc_info["focused_content"] = focused_content
        enriched_docs.append(doc_info)

        context_blocks.append(
            f"--- [NGUỒN PHÁP LUẬT {i}] ---\n"
            f"Văn bản: {law_name}\n"
            f"Điều luật: {article}: {title}\n"
            f"Nội dung quy định:\n{focused_content}\n"
        )

    # 2. Hỗ trợ đa vi phạm
    multi_violation_hint = ""
    if is_multi:
        multi_violation_hint = (
            "\n[QUY TẮC XỬ PHẠT NHIỀU HÀNH VI CÙNG LÚC]:\n"
            "- Theo Điểm d Khoản 2 Điều 3 và Điều 67 Luật Xử lý vi phạm hành chính: Một người thực hiện nhiều hành vi vi phạm thì bị xử phạt về TỪNG hành vi và TỔNG TIỀN PHẠT ĐƯỢC CỘNG DỒN.\n"
            "- Trong '### 1. Kết luận': TÍNH TỔNG TIỀN PHẠT CỘNG DỒN (Tổng tối thiểu đến Tổng tối đa) và tóm tắt hình phạt bổ sung.\n"
            "- Trong '### 2. Căn cứ pháp lý': Nêu rõ Điều, Khoản từng hành vi và trích dẫn Điều 3, Điều 67 Luật Xử lý vi phạm hành chính.\n"
        )

    # 3. Phản hồi tự sửa sai nếu có từ vòng lặp Self-Correction
    feedback_instruction = ""
    if correction_feedback:
        feedback_instruction = f"\n{correction_feedback}\n"
        logger.info("[GenerateNode] Đang áp dụng phản hồi Self-Correction vào Prompt sinh lời giải.")

    full_context = "\n".join(context_blocks)
    user_prompt = (
        f"[NGỮ CẢNH PHÁP LÝ]:\n{full_context}\n\n"
        f"[CÂU HỎI HIỆN TẠI]:\n{query}\n"
        f"{multi_violation_hint}"
        f"{feedback_instruction}\n"
        f"Hãy giải đáp câu hỏi trên CHI TIẾT, ĐẦY ĐỦ VÀ CHUẨN XÁC theo cấu trúc 4 phần chuẩn:\n"
        f"### 1. Kết luận\n"
        f"(Viết 1-2 câu nhận định trực diện, trả lời thẳng nội dung. TUYỆT ĐỐI KHÔNG liệt kê gạch đầu dòng ở phần này)\n\n"
        f"### 2. Căn cứ pháp lý\n"
        f"(Ghi rõ tên Điều luật và văn bản áp dụng trực tiếp có trong ngữ cảnh trên)\n\n"
        f"### 3. Phân tích & Chi tiết áp dụng\n"
        f"(Trình bày đầy đủ, cặn kẽ theo từng Khoản, Điểm a, b, c, d... hoặc mức chế tài nguyên vẹn như ngữ cảnh)\n\n"
        f"### 4. Hướng dẫn & Lưu ý thực tiễn\n"
        f"(Hướng dẫn cụ thể về cơ quan có thẩm quyền, thủ tục giấy tờ, quyền/nghĩa vụ và các khuyến nghị pháp lý)\n\n"
        f"Ở cuối cùng, thêm danh sách gợi ý:\n"
        f"[GỢI Ý CÂU HỎI TIẾP THEO]:\n- ...\n- ...\n- ..."
    )

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if history:
        is_followup = (
            len(query.split()) <= 4
            or bool(re.search(r"^(thế còn|còn|vậy|nếu|vậy thì|thế thì|có bị|bị phạt|mức phạt|bao nhiêu|như thế nào|thế nào)\b", query, re.I))
        ) and not bool(re.search(r"\b(theo|luật|bộ luật|nghị định|thông tư|điều)\b", query, re.I))

        if is_followup:
            for msg in history[-4:]:
                msg_content = msg.get("content", "").strip()
                if msg.get("role") == "assistant" and len(msg_content) > 250:
                    msg_content = msg_content[:250] + "..."
                messages.append({"role": msg.get("role", "user"), "content": msg_content})

    messages.append({"role": "user", "content": user_prompt})

    # 4. Sinh lời giải qua LLM
    raw_answer = await llm.generate(messages)

    # 5. Phân tách câu hỏi gợi ý và làm sạch câu trả lời
    clean_answer = raw_answer
    followup_questions = []
    followup_match = re.search(r"\[GỢI Ý CÂU HỎI TIẾP THEO\]:\s*([\s\S]*?)$", raw_answer, re.IGNORECASE)
    if followup_match:
        lines = followup_match.group(1).strip().split("\n")
        followup_questions = [
            re.sub(r"^[\-\*\•\d\.\s\t]+", "", line).strip()
            for line in lines
            if line.strip() and len(line.strip()) > 5
        ]
        clean_answer = raw_answer[:followup_match.start()].strip()

    clean_answer = re.sub(
        r'(\n\s*-\s*|\n\s*)\**\[\s*(?:TÀI\s*LIỆU|NGUỒN(?:\s*PHÁP\s*LUẬT)?)\s*\d+\s*\]\**\s*:\s*',
        r'\1',
        clean_answer,
        flags=re.IGNORECASE
    )
    clean_answer = _clean_all_repetition(clean_answer)

    # Bổ sung số Điều cụ thể vào Căn cứ pháp lý nếu cần
    if citations and "### 2. Căn cứ pháp lý" in clean_answer:
        def _enrich_legal_basis(m):
            header = m.group(1)
            body = m.group(2)
            if "Điều" not in body:
                primary_cit = citations[0].split(" - ")[0].strip()
                law_title = citations[0].split(" - ")[1].strip() if " - " in citations[0] else ""
                enriched_line = f"- {primary_cit} {law_title}".strip()
                return f"{header}{enriched_line}\n\n"
            return m.group(0)

        clean_answer = re.sub(
            r'(### 2\. Căn cứ pháp lý\s*\n)([\s\S]*?)(?=\n###|\Z)',
            _enrich_legal_basis,
            clean_answer,
            count=1
        )

    if len(followup_questions) < 2:
        topic = standalone_query.replace("Quy định về ", "").replace("Xử phạt hành vi ", "")
        followup_questions = [
            f"Thủ tục, giấy tờ cần chuẩn bị đối với {topic[:40]}?",
            f"Mức chế tài hoặc quyền lợi cụ thể liên quan đến {topic[:35]}?",
            f"Thời hạn giải quyết và cơ quan có thẩm quyền xử lý?",
        ]

    # Cập nhật lịch sử
    updated_history = list(history)
    updated_history.append({"role": "user", "content": query})
    updated_history.append({"role": "assistant", "content": clean_answer})

    return {
        "answer": clean_answer,
        "citations": citations,
        "retrieved_docs": enriched_docs,
        "history": updated_history,
        "followup_questions": followup_questions[:3],
        "correction_feedback": None,  # Đã tiêu thụ feedback
    }
