"""Node phòng vệ trích dẫn (Citation Guard) chạy runtime trước khi gửi câu trả lời.

Logic kiểm định:
  - Trích xuất cặp (Điều số, Tên văn bản) từ CẢ answer lẫn retrieved_docs.
  - Chỉ flag hallucination khi LLM trích dẫn một cặp (Điều, Luật) KHÔNG xuất hiện
    trong bất kỳ tài liệu đã truy hồi nào (cả trực tiếp lẫn viện dẫn chéo nội bộ).
  - Không còn whitelist hardcode — mọi trích dẫn hợp lệ trong context đều được chấp nhận.
"""
from __future__ import annotations

import logging
import re
from typing import Dict, List, Set, Tuple
from src.agent.state import LegalAgentState

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Chuẩn hóa tên văn bản pháp luật
# ---------------------------------------------------------------------------

# Từ khóa định danh loại văn bản — dùng để "nhóm" các cách viết khác nhau
_LAW_TYPE_ALIASES: Dict[str, str] = {
    # Bộ luật
    "bộ luật hình sự": "blhs",
    "blhs": "blhs",
    "luật hình sự": "blhs",
    # Bộ luật dân sự
    "bộ luật dân sự": "blds",
    "blds": "blds",
    "luật dân sự": "blds",
    # Luật lao động
    "bộ luật lao động": "bllđ",
    "bllđ": "bllđ",
    "luật lao động": "bllđ",
    # Luật xử lý vi phạm hành chính
    "luật xử lý vi phạm hành chính": "lxlvphc",
    "lxlvphc": "lxlvphc",
    "luật xlvphc": "lxlvphc",
    "xử lý vi phạm hành chính": "lxlvphc",
}


def _normalize_law_name(raw: str) -> str:
    """Chuẩn hóa tên văn bản về dạng viết tắt hoặc lowercase để so sánh."""
    s = raw.strip().lower()
    for alias, canonical in _LAW_TYPE_ALIASES.items():
        if alias in s:
            return canonical
    # Nếu không khớp alias, chuẩn hóa bằng cách giữ phần số hiệu (vd: 100/2019/nđ-cp)
    num_match = re.search(r"\d+[/\-]\d+", s)
    return num_match.group() if num_match else s


# ---------------------------------------------------------------------------
# Trích xuất cặp (Điều, Văn bản) từ văn bản
# ---------------------------------------------------------------------------

# Pattern: "Điều 5 Nghị định 100/2019/NĐ-CP" hoặc "theo Điều 67 Luật Xử lý vi phạm..."
_ARTICLE_WITH_LAW = re.compile(
    r"Điều\s+(\d+[a-zA-Z]?)"                  # Số điều (có thể kèm chữ: 15a)
    r"(?:\s+(?:của\s+|theo\s+|trong\s+)?)?"   # từ nối tùy chọn
    r"((?:Bộ\s+)?(?:luật|nghị\s+định|thông\s+tư|pháp\s+lệnh|quyết\s+định)"
    r"(?:\s+[^\n,;\.]{0,60}?))?",             # Tên văn bản tùy chọn (tối đa 60 ký tự)
    re.IGNORECASE,
)

# Pattern đơn giản: chỉ "Điều N" không kèm tên luật
_ARTICLE_ONLY = re.compile(r"Điều\s+(\d+[a-zA-Z]?)", re.IGNORECASE)


def is_negated_article(text: str, start_pos: int, end_pos: int) -> bool:
    """Kiểm tra xem điều luật có nằm trong ngữ cảnh đính chính phủ định (không tồn tại/không phải/không quy định)."""
    window_before = text[max(0, start_pos - 60):start_pos].lower()
    window_after = text[end_pos:min(len(text), end_pos + 60)].lower()
    negation_patterns = [
        "không có", "không tồn tại", "chưa có", "không quy định",
        "hoàn toàn không", "không hề có", "không tìm thấy",
        "không phải", "không đúng", "chứ không phải", "thay vì",
    ]
    if any(neg in window_before for neg in negation_patterns):
        return True
    if any(neg in window_after for neg in ["không tồn tại", "không có", "không tìm thấy", "không phải", "không đúng"]):
        return True
    return False


def extract_article_law_pairs(text: str) -> Set[Tuple[str, str]]:
    """Trích xuất tập hợp cặp (điều_chuẩn, tên_luật_chuẩn) từ văn bản.

    Ví dụ:
      "Điều 5 Nghị định 100/2019/NĐ-CP"  → {("Điều 5", "100/2019")}
      "theo Điều 67 Luật Xử lý vi phạm"  → {("Điều 67", "lxlvphc")}
      "Điều 888"                          → {("Điều 888", "")}   ← không rõ luật
    """
    pairs: Set[Tuple[str, str]] = set()
    for m in _ARTICLE_WITH_LAW.finditer(text):
        if is_negated_article(text, m.start(), m.end()):
            continue
        art_num = m.group(1)
        law_raw = (m.group(2) or "").strip()
        pairs.add((f"Điều {art_num}", _normalize_law_name(law_raw)))
    return pairs


def extract_article_numbers(text: str) -> Set[str]:
    """Trích xuất chỉ số điều (không kèm tên luật) — dùng để build context_articles."""
    return {f"Điều {m}" for m in _ARTICLE_ONLY.findall(text)}


# ---------------------------------------------------------------------------
# Logic xây dựng tập điều luật hợp lệ từ context
# ---------------------------------------------------------------------------

def _build_allowed_articles(retrieved_docs: List[Dict]) -> Tuple[Set[str], Set[str]]:
    """Xây dựng:
      - allowed_article_nums : tập số điều (vd "Điều 5") xuất hiện trong context
      - allowed_law_names    : tập tên luật chuẩn hóa trong context

    Nguồn gốc:
      1. Trường `article` của từng doc (điều luật chính)
      2. Tất cả "Điều X" được viện dẫn chéo BÊN TRONG nội dung văn bản
      3. Trường `law_name` của từng doc
    """
    allowed_nums: Set[str] = set()
    allowed_laws: Set[str] = set()

    for doc in retrieved_docs:
        # (1) Điều luật chính của doc
        art_field = doc.get("article", "")
        num_match = re.search(r"\d+[a-zA-Z]?", art_field)
        if num_match:
            allowed_nums.add(f"Điều {num_match.group()}")

        # (2) Viện dẫn chéo bên trong nội dung
        doc_text = (
            (doc.get("content") or "")
            + " "
            + (doc.get("focused_content") or "")
            + " "
            + (doc.get("article_title") or "")
        )
        allowed_nums |= extract_article_numbers(doc_text)

        # (3) Tên văn bản gốc
        law_name = doc.get("law_name", "")
        if law_name:
            allowed_laws.add(_normalize_law_name(law_name))

    return allowed_nums, allowed_laws


# ---------------------------------------------------------------------------
# Node chính
# ---------------------------------------------------------------------------

async def citation_guard_node(state: LegalAgentState) -> LegalAgentState:
    """Đối chiếu rule-based các Điều luật trích dẫn với context đã truy hồi.

    Chiến lược kiểm định (không còn whitelist cứng):
      1. Nếu số điều LLM nêu có trong tập điều viện dẫn từ context → PASS.
      2. Nếu số điều không có trong context NHƯNG tên luật kèm theo cũng KHÔNG thuộc
         domain đã truy hồi → FLAG là hallucination.
      3. Nếu số điều không có nhưng tên luật hợp lệ (cùng domain) → PASS với cảnh báo
         nhẹ (guard_status="warning" mà không trigger self-correct loop).
    """
    # Bỏ qua nhánh smalltalk / out_of_scope
    if state.get("intent") in ["smalltalk", "out_of_scope"]:
        return {**state, "guard_status": "passed"}

    answer = state.get("answer", "")
    retrieved_docs = state.get("retrieved_docs", [])

    if not answer or not retrieved_docs:
        return {**state, "guard_status": "passed", "hallucinated_articles": []}

    # ── Bước 1: Xây dựng tập điều luật và văn bản hợp lệ từ context ──────
    allowed_nums, allowed_laws = _build_allowed_articles(retrieved_docs)

    logger.debug(
        f"[CitationGuard] Context hợp lệ: {len(allowed_nums)} điều, "
        f"{len(allowed_laws)} văn bản: {allowed_laws}"
    )

    # ── Bước 2: Trích xuất (Điều, Luật) từ câu trả lời LLM ───────────────
    answer_pairs = extract_article_law_pairs(answer)
    answer_article_nums = {pair[0] for pair in answer_pairs}

    # ── Bước 3: Phân biệt True Hallucination vs Out-of-Context Reference ──
    hallucinated: Set[str] = set()
    out_of_context: Set[str] = set()

    for art_num, law_name_norm in answer_pairs:
        art_in_context = art_num in allowed_nums

        if art_in_context:
            # Số điều xuất hiện trong context (hoặc viện dẫn chéo trong nội dung) → PASS hoàn toàn
            continue

        # Trích xuất số nguyên của điều để kiểm tra tính khả thi
        art_int = None
        m = re.search(r"\d+", art_num)
        if m:
            try:
                art_int = int(m.group())
            except ValueError:
                pass

        # Kiểm tra nếu số điều phi thực tế (hệ thống pháp luật VN không có văn bản nào > 700 điều)
        if art_int is not None and (art_int <= 0 or art_int > 700):
            hallucinated.add(f"{art_num} (số điều phi thực tế)")
            logger.warning(f"[CitationGuard] Phát hiện số điều phi thực tế: {art_num}")
            continue

        # Nếu văn bản đã có trong context, nhưng LLM trích dẫn số điều vượt quá max điều của văn bản đó
        if law_name_norm and law_name_norm in allowed_laws:
            max_article_num = _get_max_article_num(allowed_nums)
            if art_int is not None and art_int > max(max_article_num + 30, 150):
                hallucinated.add(f"{art_num} thuộc {law_name_norm} (vượt quá phạm vi văn bản)")
                logger.warning(
                    f"[CitationGuard] {art_num} vượt quá số điều dự kiến của văn bản {law_name_norm} "
                    f"(max context={max_article_num}) -> True Hallucination."
                )
                continue

        # Nếu tên luật có định dạng QPPL chuẩn (nghị định, bộ luật, luật có số hiệu hoặc tên ngành hợp lệ)
        is_plausible_law = bool(
            re.search(r"\d+[/\-]\d+", law_name_norm)  # Có số hiệu văn bản (vd: 100/2019, 123/2021)
            or any(alias in law_name_norm for alias in ["blhs", "blds", "bllđ", "lxlvphc"])
            or bool(re.search(r"\b(luật|bộ luật|nghị định|thông tư|pháp lệnh)\b", law_name_norm, re.IGNORECASE))
        )

        if is_plausible_law and art_int is not None and art_int <= 500:
            # Đây là viện dẫn ngoài ngữ cảnh (Out-of-Context Reference) của một đạo luật thực tế
            out_of_context.add(f"{art_num} ({law_name_norm})")
            logger.info(
                f"[CitationGuard] Viện dẫn ngoài context nhưng hợp lệ về mặt thể thức: "
                f"{art_num} ({law_name_norm}) -> Out-of-Context Reference."
            )
        elif not law_name_norm:
            # Không rõ luật nhưng số điều nhỏ thông thường (ví dụ: "Khoản 1 Điều 3")
            if art_int is not None and art_int <= 100:
                out_of_context.add(art_num)
            else:
                hallucinated.add(art_num)
        else:
            # Tên luật lạ lẫm, không theo thể thức văn bản QPPL
            hallucinated.add(f"{art_num} ({law_name_norm})")

    # ── Bước 4: Xử lý kết quả kiểm định ──────────────────────────────────
    if not hallucinated:
        if out_of_context:
            logger.info(
                f"[CitationGuard] Chấp nhận câu trả lời với {len(out_of_context)} viện dẫn bổ sung ngoài context: "
                f"{out_of_context}. guard_status=warning"
            )
            return {
                **state,
                "guard_status": "warning",
                "hallucinated_articles": [],
                "out_of_context_articles": list(out_of_context),
            }

        logger.info("[CitationGuard] Tất cả trích dẫn hoàn toàn khớp với context. guard_status=passed")
        return {
            **state,
            "guard_status": "passed",
            "hallucinated_articles": [],
            "out_of_context_articles": [],
        }

    # Nếu phát hiện True Hallucination, chỉ retry nếu còn lượt
    retry_count = state.get("retry_count", 0)

    if retry_count < 2:
        logger.info(
            f"[CitationGuard] Phát hiện {len(hallucinated)} ảo giác thực sự: {hallucinated}. "
            f"Kích hoạt Self-Correction (lần {retry_count + 1})."
        )
        return {
            **state,
            "guard_status": "retry",
            "hallucinated_articles": list(hallucinated),
            "out_of_context_articles": list(out_of_context),
        }

    # Đã hết lượt retry: gắn disclaimer cảnh báo rõ ràng
    warning_header = (
        f"> [!WARNING]\n"
        f"> **Lưu ý kiểm tra đối chiếu**: Hệ thống nhận thấy câu trả lời có chứa trích dẫn "
        f"**{', '.join(sorted(hallucinated))}** chưa được xác thực trong cơ sở dữ liệu pháp luật trích lục. "
        f"Vui lòng đối chiếu văn bản gốc trước khi áp dụng.\n\n"
    )
    guarded_answer = warning_header + answer
    history = list(state.get("history") or [])
    if history and history[-1].get("role") == "assistant":
        history[-1]["content"] = guarded_answer

    return {
        **state,
        "answer": guarded_answer,
        "history": history,
        "guard_status": "violation",
        "hallucinated_articles": list(hallucinated),
        "out_of_context_articles": list(out_of_context),
    }


def _get_max_article_num(allowed_nums: Set[str]) -> int:
    """Lấy số điều lớn nhất trong context để làm ngưỡng tham chiếu."""
    max_num = 0
    for art in allowed_nums:
        m = re.search(r"\d+", art)
        if m:
            try:
                max_num = max(max_num, int(m.group()))
            except ValueError:
                pass
    return max_num
