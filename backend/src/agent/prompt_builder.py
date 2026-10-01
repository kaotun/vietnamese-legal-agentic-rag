# -*- coding: utf-8 -*-
"""Module chuẩn hóa xây dựng Prompt và xử lý hậu kỳ phản hồi pháp lý (Legal Prompt Builder).

Đóng vai trò Single Source of Truth cho cấu trúc 4 phần chuẩn mực, chống ảo giác (Anti-Hallucination),
chống nịnh hót (Anti-Sycophancy), xử lý triệt để tiền đề sai (False Premise),
điều kiện áp dụng theo độ tuổi / thời hiệu / hiệu lực thời gian và xúi giục đa chủ thể.
Được dùng chung giữa LangGraph generate_node và FastAPI SSE streaming endpoint.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Bạn là Chuyên gia Tư vấn Pháp luật Việt Nam chuẩn xác, khách quan và chuyên sâu.
Nhiệm vụ: Giải đáp câu hỏi của người dùng CHI TIẾT, ĐẦY ĐỦ VÀ CHUẨN XÁC dựa trên các đoạn trích điều luật trong [NGỮ CẢNH PHÁP LÝ].
TUYỆT ĐỐI KHÔNG tự suy diễn, không bịa đặt số điều hay nội dung luật không có trong ngữ cảnh.

QUY TẮC CẤU TRÚC 4 PHẦN CHUẨN (KHÔNG LẶP LẠI & BÁM SÁT ĐIỀU LUẬT):

### 1. Kết luận
- Viết từ 1 đến 2 câu nhận định trực diện, trả lời thẳng vào câu hỏi của người dùng (tóm tắt quy định/thời hạn/mức xử phạt áp dụng).
- TUYỆT ĐỐI KHÔNG liệt kê danh sách gạch đầu dòng ở Phần 1 (để tránh trùng lặp với Phần 3).

### 2. Căn cứ pháp lý
- Ghi rõ ràng: Điều [số điều] [Tên văn bản luật] áp dụng trực tiếp có trong ngữ cảnh.
- TUYỆT ĐỐI CHỈ trích dẫn các điều luật có trong [NGỮ CẢNH PHÁP LÝ] của câu hỏi hiện tại.

### 3. Phân tích & Chi tiết áp dụng
- Trình bày ĐẦY ĐỦ, CẶN KẼ theo từng Khoản và từng Điểm (a, b, c, d...) hoặc các mức quy định/thời hạn/mức chế tài nguyên văn như văn bản luật trong ngữ cảnh:
  + Đối với quy định quyền, nghĩa vụ, thời hạn, thủ tục (Dân sự, Lao động, Doanh nghiệp, Đất đai...): Trình bày rõ từng trường hợp, từng đối tượng, điều kiện và thời hạn cụ thể.
  + Đối với vi phạm hành chính hoặc hình sự: Nêu rõ từng khung chế tài, mức phạt tiền hoặc hình phạt tù tương ứng cho từng hành vi vi phạm.
- Mỗi Khoản/nhóm chỉ nêu mức quy định chung một lần ở đầu mục, sau đó liệt kê các điểm con. Không lặp lại cụm từ cố định cho từng gạch đầu dòng.

### 4. Hướng dẫn & Lưu ý thực tiễn
- Nêu rõ hướng dẫn thực tiễn cho người dân hoặc các bên liên quan:
  + Cơ quan có thẩm quyền giải quyết/xử lý.
  + Quyền và nghĩa vụ của các bên, thủ tục cần chuẩn bị, hoặc các tình tiết giảm nhẹ/khắc phục hậu quả (nếu là vi phạm).
  + Lời khuyên pháp lý thiết thực.

NGUYÊN TẮC TRÌNH BÀY TỰ NHIÊN & CHỐNG LẶP:
- TUYỆT ĐỐI KHÔNG sử dụng các nhãn nội bộ như "[TÀI LIỆU 1]", "[TÀI LIỆU 2]", "[NGUỒN 1]" trong câu trả lời. Hãy trích dẫn tự nhiên theo tên điều luật và văn bản pháp luật thực tế.
- TUYỆT ĐỐI CHỈ trích dẫn các điều luật có trong [NGỮ CẢNH PHÁP LÝ] của câu hỏi hiện tại.
- TUYỆT ĐỐI KHÔNG lặp lại các gạch đầu dòng có nội dung tương tự nhau. Không liệt kê vô tận các chữ cái (a, b, c... z, aa...). Mỗi hành vi, mỗi chế tài chỉ xuất hiện MỘT LẦN duy nhất trong toàn bộ câu trả lời.

QUY TẮC ĐÍNH CHÍNH TIỀN ĐỀ SAI & CHỐNG NỊNH HÓT (FALSE PREMISE & ANTI-SYCOPHANCY):
- Trường hợp 1: Viện dẫn Số Điều không tồn tại hoặc Tên luật giả định (ví dụ: "Theo Điều 600 BLHS...", "Luật Bảo vệ người lao động 2023..."):
  + BẮT BUỘC ở ngay câu mở đầu của "### 1. Kết luận", bạn PHẢI đính chính rõ ràng: Khẳng định số điều hoặc tên luật đó hoàn toàn không tồn tại trong hệ thống pháp luật Việt Nam.
  + Sau đó chỉ ra điều luật hoặc văn bản thực tế điều chỉnh vấn đề này và giải đáp theo đúng quy định đó.

- Trường hợp 2: Gán nhầm Số Điều cho Tội danh hoặc Chế độ khác (ví dụ: "Điều 173 BLHS quy định tội giết người đúng không?"):
  + BẮT BUỘC ở ngay câu mở đầu của "### 1. Kết luận", bạn PHẢI BÁC BỎ RÕ RÀNG: "Không đúng. Điều [X] quy định về [Chế độ A], không phải [Chế độ B]. [Chế độ B] được quy định tại Điều [Y]."
  + Căn cứ pháp lý chỉ trích dẫn điều luật đúng (Điều Y) và phân tích theo điều luật đúng.

- Trường hợp 3: Người dùng gài TIỀN ĐỀ SAI VỀ THỜI HẠN / ĐỊNH LƯỢNG / CHẾ ĐỘ PHÁP LÝ (ví dụ: "Theo BLLĐ 2019, người lao động được nghỉ thai sản 12 tháng, công ty tôi chỉ cho 6 tháng có vi phạm không?"):
  + BẮT BUỘC ĐỐI CHIẾU VỚI [NGỮ CẢNH PHÁP LÝ]: Hãy kiểm tra con số/thời hạn thực tế mà văn bản pháp luật quy định (ví dụ: Khoản 1 Điều 139 BLLĐ 2019 quy định thời gian nghỉ thai sản là 06 tháng).
  + BẮT BUỘC PHẢI BÁC BỎ TIỀN ĐỀ SAI NGAY TẠI CÂU ĐẦU TIÊN CỦA "### 1. Kết luận":
    Khẳng định rõ: Tiền đề câu hỏi nêu người lao động được nghỉ thai sản 12 tháng theo luật là KHÔNG CHÍNH XÁC. Theo Khoản 1 Điều 139 Bộ luật Lao động 2019, thời gian nghỉ thai sản theo luật định là 06 tháng. Do đó, việc công ty chỉ cho người lao động nghỉ 06 tháng là HOÀN TOÀN ĐÚNG QUY ĐỊNH PHÁP LUẬT và KHÔNG VI PHẠM.
  + TUYỆT ĐỐI KHÔNG ĐƯỢC THỪA NHẬN một cách mù quáng tiền đề sai của người dùng rồi kết luận công ty/tổ chức vi phạm! Căn cứ pháp lý phải viện dẫn đúng Điều 139 Bộ luật Lao động 2019!

- Trường hợp 4: Người dùng hỏi mức phạt tù đối với người CHƯA ĐỦ TUỔI chịu trách nhiệm hình sự (người dưới 14 tuổi, ví dụ: cháu 12 tuổi, 13 tuổi đánh bạn, trộm cắp...):
  + BẮT BUỘC ĐỐI CHIẾU VỚI [NGỮ CẢNH PHÁP LÝ]: Điều 12 Bộ luật Hình sự 2015 quy định độ tuổi tối thiểu chịu trách nhiệm hình sự tại Việt Nam là từ đủ 14 tuổi trở lên. Người dưới 14 tuổi CHƯA ĐỦ TUỔI chịu trách nhiệm hình sự đối với mọi tội phạm.
  + BẮT BUỘC PHẢI KHẲNG ĐỊNH NGAY TẠI CÂU ĐẦU TIÊN CỦA "### 1. Kết luận":
    Người [X] tuổi HOÀN TOÀN KHÔNG BỊ TRUY CỨU TRÁCH NHIỆM HÌNH SỰ VÀ KHÔNG BỊ PHẠT TÙ!
  + TUYỆT ĐỐI KHÔNG ÁP DỤNG HÌNH PHẠT TÙ của các điều luật cụ thể (như Điều 134, Điều 173...) cho người dưới 14 tuổi!
  + Căn cứ pháp lý: BẮT BUỘC viện dẫn Điều 12 Bộ luật Hình sự 2015 (Tuổi chịu trách nhiệm hình sự) và Điều 586 Bộ luật Dân sự 2015 (Trách nhiệm bồi thường của cha mẹ/người giám hộ).

- Trường hợp 5: Xúi giục người dưới 18 tuổi hoặc đồng phạm đa chủ thể:
  + BẮT BUỘC PHÂN ĐỊNH RÕ TỪNG CHỦ THỂ:
    * Chủ thể là trẻ em dưới 14 tuổi: Không phải chịu trách nhiệm hình sự theo Điều 12 BLHS.
    * Chủ thể người lớn xúi giục, lôi kéo: Bị truy cứu trách nhiệm hình sự với vai trò chủ mưu/xúi giục (Điều 17 BLHS) và phải chịu TÌNH TIẾT TĂNG NẶNG "Xúi giục người dưới 18 tuổi phạm tội" theo điểm m Khoản 1 Điều 52 BLHS.

Ở cuối câu trả lời, luôn thêm phần gợi ý (2-3 câu hỏi đào sâu):
[GỢI Ý CÂU HỎI TIẾP THEO]:
- [Câu hỏi liên quan mà người hỏi có thể quan tâm tiếp]
- [Câu hỏi liên quan mà người hỏi có thể quan tâm tiếp]
"""

COMMON_LEGAL_STOPWORDS = {
    "phạt", "tiền", "đồng", "đối", "với", "người", "điều", "khiến", "hành", "vi",
    "sau", "đây", "theo", "quy", "định", "tại", "khoản", "luật", "này", "khi",
    "tham", "gia", "thực", "hiện", "trong", "trường", "hợp", "hoặc", "không",
    "các", "loại", "cho", "của", "được", "bao", "nhiêu", "như", "thế", "nào",
    "một", "những", "có", "thể", "bị", "bởi", "về", "và", "là", "đã", "sẽ",
    "mức", "xử", "chính", "tổng", "hợp", "cũng", "lúc",
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


def clean_all_repetition(text: str) -> str:
    """Khử triệt để các chu kỳ lặp nội dung."""
    lines = text.split("\n")
    if len(lines) < 2:
        return text

    def _norm(l: str) -> str:
        s = l.strip().lower()
        while True:
            new_s = re.sub(r'^(?:[\-\*•\+◦◉]|\d+[\.\ )]|[a-zA-Z]{1,8}[\.\ )]|\[\s*[^\]]*\]|[^\w\s]\s*|\([a-zA-Z0-9]+\))\s*', '', s).strip()
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
                pattern = norm_lines[i: i + period]
                if all(len(p) > 5 for p in pattern):
                    next_block = norm_lines[i + period: i + 2 * period]
                    if pattern == next_block:
                        k = 2
                        while i + (k + 1) * period <= len(lines):
                            if norm_lines[i + k * period: i + (k + 1) * period] == pattern:
                                k += 1
                            else:
                                break
                        result_lines.extend(lines[i: i + period])
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
        if len(nl) > 10 and (trimmed.startswith("-") or trimmed.startswith("*") or re.match(r"^[a-zA-Z0-9\(\)]+[\.\ )]", trimmed)):
            if nl in seen_in_section:
                continue
            seen_in_section.add(nl)
        final_lines.append(l)

    return "\n".join(final_lines)


class LegalPromptBuilder:
    """Builder tập trung tạo cấu trúc prompt chuẩn cho Legal QA Assistant."""

    @staticmethod
    def build_prompt(
        state: Dict[str, Any],
    ) -> Tuple[List[Dict[str, str]], List[str], List[Dict[str, Any]]]:
        """Tạo messages LLM, danh sách citations và enriched_docs từ state."""
        query = state.get("query", "")
        standalone_query = state.get("standalone_query") or query
        sub_queries = state.get("sub_queries") or [standalone_query]
        is_multi = state.get("is_multi_violation", False)
        history = list(state.get("history") or [])
        retrieved_docs = state.get("retrieved_docs") or []
        correction_feedback = state.get("correction_feedback")

        context_blocks = []
        citations = []
        enriched_docs = []
        target_queries = sub_queries if (is_multi and len(sub_queries) > 1) else [standalone_query, query]
        max_docs_for_prompt = 4

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

        # 1. Multi-violation hint
        multi_violation_hint = ""
        if is_multi:
            multi_violation_hint = (
                "\n[QUY TẮC XỬ PHẠT NHIỀU HÀNH VI CÙNG LÚC]:\n"
                "- Theo điểm d Khoản 2 Điều 3 và Điều 67 Luật Xử lý vi phạm hành chính: Một người thực hiện nhiều hành vi vi phạm thì bị xử phạt về TỪNG hành vi và TỔNG TIỀN PHẠT ĐƯỢC CỘNG DỒN.\n"
                "- Trong '### 1. Kết luận': TÍNH TỔNG TIỀN PHẠT CỘNG DỒN (Tổng tối thiểu đến Tổng tối đa) và tóm tắt hình phạt bổ sung.\n"
                "- Trong '### 2. Căn cứ pháp lý': Nêu rõ Điều, Khoản từng hành vi và trích dẫn Điều 3, Điều 67 Luật Xử lý vi phạm hành chính.\n"
            )

        # 2. Correction feedback (từ Citation Guard retry)
        feedback_instruction = f"\n{correction_feedback}\n" if correction_feedback else ""

        # 3. Premise hint (False Premise & Anti-Sycophancy)
        premise_hint = ""
        premise_correction = state.get("premise_correction")

        if premise_correction and premise_correction.get("has_false_premise"):
            msg = premise_correction.get("message", "")

            if premise_correction.get("is_fake_law"):
                q_law = premise_correction.get("queried_law", "văn bản luật")
                premise_hint = (
                    f"\n[CẢNH BÁO TIỀN ĐỀ SAI TRONG CÂU HỎI]:\n"
                    f"- Người dùng đưa ra giả định/văn bản: '{q_law}'.\n"
                    f"- SỰ THẬT PHÁP LÝ: {msg}\n"
                    f"- YÊU CẦU BẮT BUỘC:\n"
                    f"  1. Ngay tại câu đầu tiên của '### 1. Kết luận', bạn BẮT BUỘC PHẢI KHẲNG ĐỊNH TRỰC DIỆN SỰ THẬT NÀY: {msg}\n"
                    f"     Nếu người dùng hỏi hành vi/công ty có vi phạm không, khẳng định rõ: KHÔNG VI PHẠM.\n"
                    f"  2. Trong '### 2. Căn cứ pháp lý': Trích dẫn văn bản/điều luật thực tế trong [NGỮ CẢNH PHÁP LÝ].\n"
                    f"  3. Trong '### 3. Phân tích': Phân tích chi tiết theo các điều luật thực tế trong [NGỮ CẢNH PHÁP LÝ].\n"
                )
            elif premise_correction.get("is_age_ineligible"):
                age = premise_correction.get("age")
                premise_hint = (
                    f"\n[CẢNH BÁO TIỀN ĐỀ SAI TRONG CÂU HỎI - CHƯA ĐỦ TUỔI CHỊU TRÁCH NHIỆM HÌNH SỰ]:\n"
                    f"- Người dùng đang hỏi mức phạt tù đối với người {age} tuổi.\n"
                    f"- SỰ THẬT PHÁP LÝ: {msg}\n"
                    "- YÊU CẦU BẮT BUỘC:\n"
                    f"  1. Ngay tại câu đầu tiên của '### 1. Kết luận', bạn BẮT BUỘC PHẢI KHẲNG ĐỊNH TRỰC DIỆN:\n"
                    f"     'Người {age} tuổi HOÀN TOÀN KHÔNG BỊ TRUY CỨU TRÁCH NHIỆM HÌNH SỰ VÀ KHÔNG BỊ PHẠT TÙ."
                    " Theo Điều 12 Bộ luật Hình sự 2015, người dưới 14 tuổi chưa đủ tuổi chịu trách nhiệm hình sự đối với mọi tội phạm.'\n"
                    "  2. Trong '### 2. Căn cứ pháp lý': Trích dẫn Điều 12 Bộ luật Hình sự 2015 (Tuổi chịu trách nhiệm hình sự)"
                    " và Điều 586 Bộ luật Dân sự 2015 (Bồi thường thiệt hại do người chưa thành niên gây ra).\n"
                    "  3. Trong '### 3. Phân tích & Chi tiết áp dụng': Phân tích rõ quy định về độ tuổi tại Điều 12 BLHS,"
                    " giải thích rõ vì sao không bị phạt tù; nêu các biện pháp xử lý hành chính/giáo dục thay thế"
                    " (giáo dục tại xã, phường, thị trấn hoặc đưa vào trường giáo dưỡng nếu đủ 12 đến dưới 14 tuổi)"
                    " và trách nhiệm bồi thường thiệt hại của cha mẹ/người giám hộ theo Điều 586 Bộ luật Dân sự.\n"
                    f"  TUYỆT ĐỐI KHÔNG ÁP DỤNG HÌNH PHẠT TÙ CỦA ĐIỀU 134 HAY BẤT KỲ ĐIỀU LUẬT HÌNH SỰ NÀO CHO NGƯỜI {age} TUỔI!\n"
                )
            elif premise_correction.get("is_mismatch"):
                q_art = premise_correction.get("queried_article", "Điều luật")
                act_title = premise_correction.get("actual_title", "")
                corr_art = premise_correction.get("correct_article", "")
                corr_title = premise_correction.get("correct_title", "")
                law_disp = premise_correction.get("law_display", "Bộ luật")
                topic_disp = premise_correction.get("queried_topic", "")
                premise_hint = (
                    f"\n[CẢNH BÁO TIỀN ĐỀ SAI TRONG CÂU HỎI - GÁN NHẦM ĐIỀU CHO TỘI DANH/CHẾ ĐỘ]:\n"
                    f"- Người dùng đang hỏi xem {q_art} có phải quy định về '{topic_disp}' không.\n"
                    f"- SỰ THẬT PHÁP LÝ: {msg}\n"
                    f"- YÊU CẦU BẮT BUỘC:\n"
                    f"  1. Ngay tại câu đầu tiên của '### 1. Kết luận', bạn BẮT BUỘC PHẢI TRẢ LỜI RÕ RÀNG:\n"
                    f"     'Không đúng. {q_art} {law_disp} quy định về {act_title}, KHÔNG PHẢI quy định về {topic_disp}. "
                    f"Tội danh/hành vi này được quy định tại {corr_art} ({corr_title}) {law_disp}.'\n"
                    f"  2. Trong '### 2. Căn cứ pháp lý': CHỈ trích dẫn {corr_art} ({corr_title}) - {law_disp}. "
                    f"TUYỆT ĐỐI KHÔNG trích dẫn {q_art} cho hành vi/tội danh này!\n"
                    f"  3. Trong '### 3. Phân tích & Chi tiết áp dụng': Trình bày chi tiết cấu thành, khung hình phạt và mức phạt của {corr_art} ({corr_title}) dựa trên [NGỮ CẢNH PHÁP LÝ].\n"
                )
            else:
                law_disp = premise_correction.get("law_display", "Văn bản luật")
                q_art = premise_correction.get("queried_article", "Điều luật")
                max_art = premise_correction.get("max_article", "")
                premise_hint = (
                    f"\n[CẢNH BÁO TIỀN ĐỀ SAI TRONG CÂU HỎI - ĐIỀU LUẬT KHÔNG TỒN TẠI]:\n"
                    f"- Người dùng đang hỏi về: '{q_art}' thuộc '{law_disp}'.\n"
                    f"- SỰ THẬT PHÁP LÝ: {msg}\n"
                    f"- YÊU CẦU BẮT BUỘC: Ngay tại câu đầu tiên của '### 1. Kết luận', bạn BẮT BUỘC PHẢI ĐÍNH CHÍNH SỰ THẬT NÀY "
                    f"(khẳng định rõ {law_disp} chỉ có {max_art} điều, hoàn toàn KHÔNG CÓ {q_art}). "
                    f"Sau đó giải thích và hướng dẫn điều luật thực tế quy định hành vi này dựa trên các trích đoạn trong [NGỮ CẢNH PHÁP LÝ]. "
                    f"TUYỆT ĐỐI KHÔNG ghi '{q_art}' vào '### 2. Căn cứ pháp lý' hay '### 3. Phân tích'!\n"
                )

        # 4. Multi-subject & Instigator hint
        multi_subject_hint = ""
        legal_decision = state.get("legal_decision") or {}
        if legal_decision.get("rule_code") == "RULE_CRIMINAL_INSTIGATOR_ADULT_MINOR":
            instigator_desc = legal_decision.get("condition_description", "")
            multi_subject_hint = (
                f"\n[HƯỚNG DẪN XỬ LÝ VỤ ÁN ĐA CHỦ THỂ / XÚI GIỤC NGƯỜI DƯỚI 18 TUỔI]:\n"
                f"- Tình huống: Người lớn xúi giục, lôi kéo người chưa đủ 14 tuổi thực hiện hành vi nguy hiểm cho xã hội.\n"
                f"- {instigator_desc}\n"
                f"- YÊU CẦU TRÌNH BÀY BẮT BUỘC:\n"
                f"  1. Trong '### 1. Kết luận': Tách bạch rõ 2 chủ thể:\n"
                f"     * Trẻ em (dưới 14 tuổi): HOÀN TOÀN KHÔNG BỊ TRUY CỨU TNHS theo Điều 12 BLHS.\n"
                f"     * Người lớn (xúi giục): BỊ TRUY CỨU TRÁCH NHIỆM HÌNH SỰ với vai trò chủ mưu/xúi giục (Điều 17 BLHS) và chịu TÌNH TIẾT TĂNG NẶNG theo điểm m Khoản 1 Điều 52 BLHS.\n"
                f"  2. Trong '### 2. Căn cứ pháp lý': Viện dẫn Điều 12, Điều 17, điểm m Khoản 1 Điều 52 BLHS và điều luật tội danh cụ thể.\n"
            )

        # 5. Temporal validity hint (Hiệu lực thời gian của văn bản)
        temporal_hint = ""
        temporal_warning = legal_decision.get("temporal_warning")
        if temporal_warning:
            temporal_hint = (
                f"\n[LƯU Ý VỀ HIỆU LỰC THỜI GIAN CỦA VĂN BẢN]:\n"
                f"- {temporal_warning}\n"
                f"- Bạn phải làm rõ văn bản áp dụng tại thời điểm xảy ra sự việc, tránh áp dụng hồi tố trái nguyên tắc pháp luật.\n"
            )

        # 6. Fact Ambiguity hint
        ambiguity_hint = ""
        fact_ambiguities = state.get("fact_ambiguities") or []
        if fact_ambiguities:
            ambiguity_hint = (
                f"\n[LƯU Ý VỀ TÍNH XÁC ĐỊNH CỦA DỮ KIỆN (FACT AMBIGUITY)]:\n"
                f"- Cảnh báo: {fact_ambiguities[0]}\n"
                f"- Yêu cầu: Trong Phần 3 (Phân tích) và Phần 4 (Lưu ý thực tiễn), bạn PHẢI lưu ý rõ cho người hỏi rằng "
                f"cần có kết luận giám định tỷ lệ tổn thương cơ thể (%) chính thức hoặc chứng cứ cụ thể để định khung chính xác.\n"
            )

        # 7. Condition hint (Eligibility condition)
        condition_hint = ""
        if state.get("eligibility_status") == "REQUIRE_CONDITION":
            cond_desc = legal_decision.get("condition_description", "")
            condition_hint = (
                f"\n[ĐIỀU KIỆN ÁP DỤNG ĐẶC BIỆT CỦA CHỦ THỂ (ELIGIBILITY CONDITION)]:\n"
                f"- Quy định pháp luật: {cond_desc}\n"
                f"- Yêu cầu: BẮT BUỘC phân định rõ giữa trường hợp bị truy cứu trách nhiệm hình sự (tội rất nghiêm trọng, đặc biệt nghiêm trọng) "
                f"và trường hợp KHÔNG bị truy cứu (tội ít nghiêm trọng, nghiêm trọng) theo Khoản 2 Điều 12 BLHS.\n"
            )

        full_context = "\n".join(context_blocks)
        user_prompt = (
            f"[NGỮ CẢNH PHÁP LÝ]:\n{full_context}\n\n"
            f"[CÂU HỎI HIỆN TẠI]:\n{query}\n"
            f"{multi_violation_hint}"
            f"{premise_hint}"
            f"{multi_subject_hint}"
            f"{temporal_hint}"
            f"{ambiguity_hint}"
            f"{condition_hint}"
            f"{feedback_instruction}\n"
            "Hãy giải đáp câu hỏi trên CHI TIẾT, ĐẦY ĐỦ VÀ CHUẨN XÁC theo cấu trúc 4 phần chuẩn:\n"
            "### 1. Kết luận\n"
            "(Viết 1-2 câu nhận định trực diện, trả lời thẳng nội dung. TUYỆT ĐỐI KHÔNG liệt kê gạch đầu dòng ở phần này)\n\n"
            "### 2. Căn cứ pháp lý\n"
            "(Ghi rõ tên điều luật và văn bản áp dụng trực tiếp có trong ngữ cảnh trên)\n\n"
            "### 3. Phân tích & Chi tiết áp dụng\n"
            "(Trình bày đầy đủ, cặn kẽ theo từng Khoản, Điểm a, b, c, d... hoặc mức chế tài nguyên văn như ngữ cảnh)\n\n"
            "### 4. Hướng dẫn & Lưu ý thực tiễn\n"
            "(Hướng dẫn cụ thể về cơ quan có thẩm quyền, thủ tục giấy tờ, quyền/nghĩa vụ và các khuyến nghị pháp lý)\n\n"
            "Ở cuối cùng, thêm danh sách gợi ý:\n"
            "[GỢI Ý CÂU HỎI TIẾP THEO]:\n- ...\n- ...\n- ..."
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
        return messages, citations, enriched_docs

    @staticmethod
    def extract_followup_and_clean_answer(raw_answer: str) -> Tuple[str, List[str]]:
        """Tách danh sách câu hỏi gợi ý đào sâu và làm sạch nội dung câu trả lời."""
        followup_questions: List[str] = []
        followup_match = re.search(
            r"\[GỢI Ý CÂU HỎI TIẾP THEO\]:\s*([\s\S]*?)$", raw_answer, re.IGNORECASE
        ) or re.search(
            r"\[G[ỢO]I [ÝY] C[ÂA]U H[ỎO]I TI[ẾE]P THEO\]:\s*([\s\S]*?)$", raw_answer, re.IGNORECASE
        )

        if followup_match:
            lines = followup_match.group(1).strip().split("\n")
            followup_questions = [
                re.sub(r"^[\-\*\u2022\d\.\s\t]+", "", line).strip()
                for line in lines if line.strip() and len(line.strip()) > 5
            ][:3]
            clean_answer = raw_answer[:followup_match.start()].strip()
        else:
            clean_answer = raw_answer

        return clean_answer, followup_questions


# Hàm tương thích ngược
def build_generation_prompt(state: Dict[str, Any]) -> Tuple[List[Dict[str, str]], List[str], List[Dict[str, Any]]]:
    return LegalPromptBuilder.build_prompt(state)
