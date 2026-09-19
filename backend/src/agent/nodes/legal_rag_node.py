"""Node thực hiện truy hồi văn bản luật và sinh câu trả lời cấu trúc 4 phần (Phase 4)."""
from __future__ import annotations

import logging
import re
from src.agent.llm_client import LLMClient
from src.agent.state import LegalAgentState
from src.retrieval.hybrid_retriever import HybridLegalRetriever
from src.retrieval.hyde import HydeGenerator
from src.retrieval.query_decomposer import QueryDecomposer
from src.retrieval.spell_corrector import SpellCorrector

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
    """Trích xuất thông minh các Khoản và Điểm liên quan dựa trên danh sách Sub-queries chuẩn pháp lý.
    - Nếu nội dung toàn văn điều luật <= 3500 ký tự (bao gồm hầu hết các Điều của Bộ luật Hình sự,
      Luật Đất đai, Luật Hải quan...), GIỮ NGUYÊN TOÀN VĂN để bảo toàn đầy đủ các khung hình phạt
      (Khung 1, 2, 3, 4), hình phạt bổ sung và trách nhiệm pháp nhân thương mại.
    - Với các điều luật đồ sộ > 3500 ký tự (như Điều 5, Điều 6 Nghị định 100/2019/NĐ-CP dài 15.000-20.000 ký tự):
      + Tự động chọn các Khoản vi phạm khớp nhất với hành vi người dùng hỏi.
      + Tự động gom thêm các Khoản quy định hình phạt bổ sung (tước quyền sử dụng GPLX, tịch thu...)
        và trừ điểm GPLX liên quan trực tiếp đến các Khoản vi phạm đã chọn.
    """
    if len(content) <= 3500:
        return content

    # Phân rã văn bản theo từng Khoản (1., 2., 3...)
    clauses = re.split(r"(?:\n|^)(?=\d+\.\s+)", content)
    selected_indices = set()

    # 1. Tìm Khoản phù hợp nhất cho mỗi Sub-query
    for q in target_queries:
        q_clean = q.lower()
        q_words = [w for w in re.findall(r"\b[\w\d_]+\b", q_clean) if len(w) > 1 and w not in COMMON_LEGAL_STOPWORDS]

        best_idx = None
        best_score = -1

        for idx, c in enumerate(clauses):
            c_lower = c.lower()
            sc = 0
            # Điểm cộng cho từ khóa xuất hiện trong Khoản
            for w in q_words:
                if w in c_lower:
                    sc += 8
            # Khớp trực tiếp cả cụm từ khóa chính
            if len(q_clean) > 8 and any(token in c_lower for token in [q_clean[:20], q_clean[-20:]]):
                sc += 15

            if sc > best_score and sc > 12:
                best_score = sc
                best_idx = idx

        if best_idx is not None:
            selected_indices.add(best_idx)

    # 2. Tìm thêm các Khoản quy định hình phạt bổ sung (tước GPLX) hoặc trừ điểm liên quan đến các Khoản đã chọn
    for idx, c in enumerate(clauses):
        c_lower = c.lower()
        if "trừ điểm giấy phép lái xe" in c_lower or "tước quyền sử dụng" in c_lower:
            for sel_idx in list(selected_indices):
                sel_clause_num = sel_idx + 1
                if f"khoản {sel_clause_num}" in c_lower:
                    selected_indices.add(idx)

    # Giới hạn tối đa 4 Khoản liên quan nhất để giữ văn cảnh tập trung, giàu chi tiết
    if len(selected_indices) > 4:
        selected_indices = set(sorted(selected_indices)[:4])

    # Fallback nếu không khớp được khoản nào cụ thể
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


async def legal_rag_node(
    state: LegalAgentState,
    retriever: HybridLegalRetriever,
    llm: LLMClient,
    top_k: int = 6
) -> LegalAgentState:
    """Truy hồi ngữ cảnh đa hành vi (Sub-query Decomposition) và sinh câu trả lời bằng LLM."""
    query = state["query"]
    history = list(state.get("history") or [])
    logger.info(f"Đang xử lý câu hỏi: '{query}' (Lịch sử: {len(history)} tin nhắn)")

    # 0. Sửa lỗi chính tả và chuẩn hóa văn bản đầu vào (Spell Correction Pipeline)
    spell_corrector = SpellCorrector(llm=llm)
    corrected_query, was_corrected = await spell_corrector.correct(query)
    if was_corrected:
        logger.info(f"[LegalRAG] Đã sửa lỗi chính tả: '{query}' -> '{corrected_query}'")
        query = corrected_query

    # 1. Tự động nhận diện và phân rã đa hành vi vi phạm bằng LLM Sub-query Decomposition
    decomposer = QueryDecomposer(llm=llm)
    decomp_result = await decomposer.decompose(query, history=history)

    is_multi = decomp_result.get("is_multi_violation", False)
    standalone_query = decomp_result.get("standalone_query", query)
    sub_queries = decomp_result.get("sub_queries", [query])

    logger.info(f"[LegalRAG] is_multi={is_multi}, sub_queries={sub_queries}")

    # 2. Truy hồi văn bản luật tương ứng
    if is_multi and len(sub_queries) > 1:
        # Chạy tìm kiếm song song cho từng Sub-query để đảm bảo không vi phạm nào bị bỏ sót
        retrieved_docs = await retriever.search_multi_queries(
            sub_queries=sub_queries,
            top_k_per_query=3,
            total_top_k=8,
            apply_rerank=True,
        )
        target_queries_for_snippets = sub_queries
    else:
        # Truy hồi đơn lẻ kết hợp HyDE
        hyde_gen = HydeGenerator(llm=llm)
        hypothetical_passage = await hyde_gen.generate_hypothetical_passage(standalone_query)
        retrieved_docs = await retriever.search(
            query=standalone_query,
            top_k=top_k,
            hypothetical_passage=hypothetical_passage,
            apply_rerank=True,
        )
        target_queries_for_snippets = [standalone_query, query]

    if not retrieved_docs:
        fallback_answer = (
            "### 1. Kết luận\nHiện tại hệ thống chưa tìm thấy văn bản quy phạm pháp luật trực tiếp phù hợp trong cơ sở dữ liệu để giải đáp câu hỏi của bạn.\n\n"
            "### 2. Căn cứ pháp lý\nChưa có căn cứ trích dẫn trực tiếp.\n\n"
            "### 3. Chi tiết áp dụng\nVui lòng cung cấp thêm từ khóa cụ thể để được tra cứu chính xác hơn.\n\n"
            "### 4. Lưu ý thực tiễn\nBạn nên tham khảo ý kiến chuyên gia pháp lý đối với các vụ việc cụ thể."
        )
        updated_history = list(history)
        updated_history.append({"role": "user", "content": query})
        updated_history.append({"role": "assistant", "content": fallback_answer})
        return {
            **state,
            "standalone_query": standalone_query,
            "is_multi_violation": is_multi,
            "sub_queries": sub_queries,
            "history": updated_history,
            "retrieved_docs": [],
            "answer": fallback_answer,
            "citations": [],
            "guard_status": "warning",
        }

    # 3. Xây dựng ngữ cảnh pháp lý thông minh (Smart Windowing)
    context_blocks = []
    citations = []
    enriched_docs = []
    # Chọn số lượng văn bản tối ưu: 2 văn bản cho câu hỏi đơn lẻ, tối đa 4 cho đa hành vi để đảm bảo văn cảnh tập trung tuyệt đối
    max_docs_for_prompt = 4 if (is_multi and len(sub_queries) > 1) else 2
    for i, doc in enumerate(retrieved_docs[:max_docs_for_prompt], 1):
        law_name = doc.get("law_name", "")
        article = doc.get("article", "")
        title = doc.get("article_title", "")
        raw_content = doc.get("content", "")

        # Trích xuất đoạn trích dựa trên các Sub-queries (giữ nguyên toàn văn nếu điều luật <= 3500 ký tự)
        focused_content = extract_relevant_snippet(raw_content, target_queries_for_snippets, max_chars=3500)

        citation_str = f"{article} ({title}) - {law_name}" if title else f"{article} - {law_name}"
        citations.append(citation_str)

        # Enriched doc để frontend Inspector hiển thị đầy đủ toàn văn và chuẩn xác
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

    # 4. Chỉ dẫn suy luận nếu phát hiện vi phạm đa hành vi
    multi_violation_hint = ""
    if is_multi:
        multi_violation_hint = (
            "\n[QUY TẮC XỬ PHẠT NHIỀU HÀNH VI CÙNG LÚC]:\n"
            "- Theo Điểm d Khoản 2 Điều 3 và Điều 67 Luật Xử lý vi phạm hành chính: Một người thực hiện nhiều hành vi vi phạm hành chính thì bị xử phạt về TỪNG hành vi vi phạm, và TỔNG SỐ TIỀN PHẠT ĐƯỢC CỘNG DỒN.\n"
            "- Trong '### 1. Kết luận': Nêu rõ người vi phạm sẽ bị xử phạt về từng lỗi, TÍNH TỔNG TIỀN PHẠT CỘNG DỒN (Tổng tối thiểu đến Tổng tối đa) và tóm tắt hình phạt bổ sung (tước GPLX/trừ điểm).\n"
            "- Trong '### 2. Căn cứ pháp lý': Nêu rõ Điều, Khoản của từng hành vi và trích dẫn Điều 3, Điều 67 Luật Xử lý vi phạm hành chính.\n"
            "- Trong '### 3. Chi tiết áp dụng': Phân tích chi tiết mức phạt của từng lỗi và ghi rõ phép cộng tổng mức phạt phải nộp.\n"
            "- Trong '### 4. Hướng dẫn & Lưu ý thực tiễn': Nêu rõ quy trình CSGT sẽ lập 01 Biên bản vi phạm hành chính và ban hành 01 Quyết định xử phạt chung cho tất cả các lỗi.\n"
        )

    full_context = "\n".join(context_blocks)
    user_prompt = (
        f"[NGỮ CẢNH PHÁP LÝ]:\n{full_context}\n\n"
        f"[CÂU HỎI HIỆN TẠI]:\n{query}\n"
        f"{multi_violation_hint}\n"
        f"Hãy giải đáp câu hỏi trên một cách CHI TIẾT, ĐẦY ĐỦ VÀ CHUẨN XÁC theo đúng cấu trúc 4 phần chuẩn:\n"
        f"- TUYỆT ĐỐI KHÔNG dùng nhãn nội bộ như '[TÀI LIỆU 1]', '[NGUỒN 1]'. Trích dẫn tự nhiên theo tên Điều luật.\n"
        f"- TUYỆT ĐỐI KHÔNG lặp lại cùng một danh mục quy định ở nhiều mục.\n\n"
        f"### 1. Kết luận\n"
        f"(Viết 1-2 câu nhận định trực diện, trả lời thẳng vào nội dung người dùng hỏi. TUYỆT ĐỐI KHÔNG liệt kê danh sách gạch đầu dòng ở phần này)\n\n"
        f"### 2. Căn cứ pháp lý\n"
        f"(Ghi rõ tên Điều luật và văn bản pháp luật áp dụng trực tiếp có trong ngữ cảnh trên)\n\n"
        f"### 3. Phân tích & Chi tiết áp dụng\n"
        f"(Trình bày đầy đủ, cặn kẽ theo từng Khoản và từng Điểm a, b, c, d... hoặc từng mốc thời hạn/mức chế tài nguyên vẹn như văn bản luật được cung cấp)\n\n"
        f"### 4. Hướng dẫn & Lưu ý thực tiễn\n"
        f"(Hướng dẫn cụ thể về cơ quan có thẩm quyền xử lý, thủ tục giấy tờ, quyền lợi/nghĩa vụ của các bên và các khuyến nghị pháp lý)\n\n"
        f"Ở cuối cùng, thêm danh sách gợi ý:\n"
        f"[GỢI Ý CÂU HỎI TIẾP THEO]:\n- ...\n- ...\n- ..."
    )

    # 5. Xây dựng prompt có gắn kết lịch sử đối thoại (Multi-turn Context)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if history:
        # Nhận diện câu hỏi nối tiếp/tỉnh lược
        is_followup = (
            len(query.split()) <= 4
            or bool(re.search(r"^(thế còn|còn|vậy|nếu|vậy thì|thế thì|có bị|bị phạt|mức phạt|bao nhiêu|như thế nào|thế nào)\b", query, re.I))
        ) and not bool(re.search(r"\b(theo|luật|bộ luật|nghị định|thông tư|điều)\b", query, re.I))

        # Chỉ đưa lịch sử vào nếu thực sự là câu hỏi nối tiếp của chủ đề trước
        if is_followup:
            for msg in history[-4:]:
                msg_content = msg.get("content", "").strip()
                if msg.get("role") == "assistant" and len(msg_content) > 250:
                    msg_content = msg_content[:250] + "..."
                messages.append({"role": msg.get("role", "user"), "content": msg_content})

    messages.append({"role": "user", "content": user_prompt})

    # 6. Gọi LLM sinh câu trả lời
    raw_answer = await llm.generate(messages)

    # Phân tách câu hỏi gợi ý tiếp theo từ raw_answer
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

    # Hậu xử lý: Tự động dọn dẹp triệt để các tiền tố thô [TÀI LIỆU x]: nếu LLM vẫn vô tình sinh ra
    clean_answer = re.sub(
        r'(\n\s*-\s*|\n\s*)\**\[\s*(?:TÀI\s*LIỆU|NGUỒN(?:\s*PHÁP\s*LUẬT)?)\s*\d+\s*\]\**\s*:\s*',
        r'\1',
        clean_answer,
        flags=re.IGNORECASE
    )
    # Chống vòng lặp liệt kê số Điều luật nếu LLM vô tình lặp số (ví dụ: Điều 189, Điều 190...)
    def _truncate_article_loop(match):
        items = re.findall(r"Điều\s+\d+", match.group(0))
        if len(items) > 3:
            return ", ".join(items[:3]) + " và các điều khoản liên quan"
        return match.group(0)

    clean_answer = re.sub(r"(?:Điều\s+\d+(?:,\s*|\s+và\s+)){3,}Điều\s+\d+", _truncate_article_loop, clean_answer)

    # Chống vòng lặp lặp đi lặp lại một cụm từ dài trên 20 ký tự nếu LLM bị kẹt token
    clean_answer = re.sub(r'(.{20,}?)(?:\s*,\s*\1){2,}', r'\1', clean_answer)

    # Khử triệt để các chu kỳ lặp vô tận (A-B-A-B, A-A-A, A-B-C-A-B-C...) bất chấp chữ cái đầu dòng (g, h, i, j...)
    def _clean_all_repetition(text: str) -> str:
        lines = text.split("\n")
        if len(lines) < 2:
            return text

        def _norm(l: str) -> str:
            s = l.strip().lower()
            # Bóc tách triệt để mọi dạng tiền tố: gạch đầu dòng, số thứ tự, chữ cái, nhãn như [ ], \], ^]...
            while True:
                new_s = re.sub(r'^(?:[\-\*\•\+–—]|\d+[\.\)]|[a-zA-Z]{1,8}[\.\)]|\[\s*[^\]]*\]|[^\w\s]\s*|\([a-zA-Z0-9]+\))\s*', '', s).strip()
                if new_s == s:
                    break
                s = new_s
            s = re.sub(r'[;,\.]+$', '', s).strip()
            return s

        # Bước 1: Thu gọn chu kỳ lặp chuỗi khối (Block cycle collapsing)
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

        # Bước 2: Khử trùng lặp nội dung gạch đầu dòng trong cùng một phân mục (Semantic list deduplication)
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

    clean_answer = _clean_all_repetition(clean_answer)

    # Bổ sung số Điều cụ thể vào Căn cứ pháp lý nếu LLM chỉ ghi tên luật mà quên số Điều
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

    # Fallback thông minh nếu không trích xuất được đủ câu
    if len(followup_questions) < 2:
        topic = standalone_query.replace("Quy định về ", "").replace("Xử phạt hành vi ", "")
        followup_questions = [
            f"Thủ tục, giấy tờ cần chuẩn bị đối với {topic[:40]}?",
            f"Mức chế tài hoặc quyền lợi cụ thể liên quan đến {topic[:35]}?",
            f"Thời hạn giải quyết và cơ quan có thẩm quyền xử lý?",
        ]

    # 7. Cập nhật lịch sử hội thoại (chỉ lưu câu trả lời sạch)
    updated_history = list(history)
    updated_history.append({"role": "user", "content": query})
    updated_history.append({"role": "assistant", "content": clean_answer})

    return {
        **state,
        "standalone_query": standalone_query,
        "is_multi_violation": is_multi,
        "sub_queries": sub_queries,
        "history": updated_history,
        "retrieved_docs": enriched_docs,
        "answer": clean_answer,
        "citations": citations,
        "followup_questions": followup_questions[:3],
    }
