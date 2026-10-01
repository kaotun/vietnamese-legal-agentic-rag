# -*- coding: utf-8 -*-
"""Module kiểm định tính xác thực của tiền đề trong câu hỏi người dùng (Query Premise Checker).

Chuyên trách phát hiện các câu hỏi gài, câu hỏi nhầm lẫn hoặc viện dẫn các Điều luật / Văn bản luật không
tồn tại trong hệ thống pháp luật Việt Nam (False Premise / Negative Constraint Detection).

Hoàn toàn vận hành trên Structured Legal Knowledge Base (legal_documents_registry & legal_domain_taxonomy)
trong PostgreSQL, không hardcode danh mục văn bản trong mã nguồn.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from src.domain.legal_registry import get_legal_registry

logger = logging.getLogger(__name__)

# Pattern bóc tách số điều viện dẫn: "Điều 600", "điều 173", "Điều 999a"
ARTICLE_PATTERN = re.compile(r"\b[Đđ]iều\s+(\d+[a-zA-Z]?)\b", re.IGNORECASE)

# Pattern bóc tách tên luật được người dùng viện dẫn:
# "Luật Bảo vệ người lao động 2023", "Bộ luật Lao động 2019", "Nghị định 100/2019/NĐ-CP"
LAW_NAME_PATTERN = re.compile(
    r"\b((?:Bộ\s+)?luật|nghị\s+định|thông\s+tư|pháp\s+lệnh)\s+([A-ZÀÁÂÃÈÉÊÌÍÒÓÔÕÙÚÝĂĐƠƯẠẢẤẦẨẪẮẰẲẴẶẸẺẼẾỀỂỄỆỈỊỌỎỐỒỔỖỘỚỜỞỠỢỤỦỨỪỬỮỰỲỶỸỴ][^\n\?\.\;\,]{2,60}?(?:\s+\d{4})?)(?=\s+(?:quy\s+định|về\b|nói\s+gì|như\s+thế\s+nào|hướng\s+dẫn|cho\s+biết|là\s+gì)|(?:\s*[\,\?\.\:]|$))",
    re.IGNORECASE,
)


def check_query_premise(query: str, records: Optional[List[Dict[str, Any]]] = None) -> Optional[Dict[str, Any]]:
    """Kiểm tra xem câu hỏi có chứa tiền đề sai (False Premise) dựa trên Database-backed Registry:
    1. Viện dẫn độ tuổi chưa đủ năng lực chịu trách nhiệm hình sự (< 14 tuổi bị phạt tù).
    2. Viện dẫn tên Luật/Nghị định không tồn tại hoặc ngộ nhận phổ biến.
    3. Viện dẫn số Điều không tồn tại hoặc gán sai tội danh/chủ đề.
    """
    if not query:
        return None

    # -- KIỂM TRA 0: PHÁT HIỆN TIỀN ĐỀ SAI VỀ ĐỘ TUỔI HÌNH SỰ (AGE INELIGIBLE PREMISE) --
    is_criminal_query = bool(re.search(r"\b(blhs|bộ luật hình sự|hình sự|tội|truy cứu|phạt tù|đi tù|án tù|ngồi tù|tử hình)\b", query, re.I))
    m_age = re.search(r"\b(?:cháu|em|trẻ|học sinh|người|bé)?\s*(\d{1,2})\s*tuổi\b", query, re.I)
    if is_criminal_query and m_age:
        age = int(m_age.group(1))
        if age < 14:
            msg = (
                f"Theo quy định tại Điều 12 Bộ luật Hình sự 2015 (sửa đổi, bổ sung 2017) về Tuổi chịu trách nhiệm hình sự, "
                f"người dưới 14 tuổi (ở đây là {age} tuổi) CHƯA ĐỦ TUỔI CHỊU TRÁCH NHIỆM HÌNH SỰ đối với bất kỳ tội phạm nào. "
                f"Do đó, người {age} tuổi HOÀN TOÀN KHÔNG BỊ TRUY CỨU TRÁCH NHIỆM HÌNH SỰ VÀ KHÔNG BỊ PHẠT TÙ theo Điều 134 hay bất kỳ điều luật hình sự nào khác. "
                f"Tùy tính chất vi phạm, người {age} tuổi có thể bị áp dụng biện pháp giáo dục tại xã/phường hoặc đưa vào trường giáo dưỡng (theo Luật Xử lý vi phạm hành chính), "
                f"đồng thời cha mẹ hoặc người giám hộ có nghĩa vụ bồi thường thiệt hại dân sự (Điều 586 Bộ luật Dân sự 2015)."
            )
            clean_q = f"Điều 12 Bộ luật Hình sự 2015 tuổi chịu trách nhiệm hình sự {age} tuổi {query}"
            logger.warning(f"[PremiseChecker] Phát hiện tiền đề sai (dưới 14 tuổi không chịu TNHS): {age} tuổi trong câu hỏi hình sự.")
            return {
                "has_false_premise": True,
                "is_age_ineligible": True,
                "age": age,
                "law_display": "Điều 12 Bộ luật Hình sự 2015",
                "message": msg,
                "cleaned_query": clean_q,
            }

    registry = get_legal_registry()

    # -- KIỂM TRA 1: PHÁT HIỆN TÊN LUẬT BỊA ĐẶT / NGỘ NHẬN QUA TAXONOMY --
    fake_match = registry.find_fake_law_or_misconception(query)
    if fake_match:
        matched_fake_name, taxonomy = fake_match
        target_name = taxonomy.default_redirect_query or taxonomy.governing_law_title

        # Trích xuất và thay thế cụm từ sai trong câu hỏi để chuyển tiếp sang bộ máy RAG
        pat = re.compile(re.escape(matched_fake_name) + r"(?:\s+\d{4})?", re.IGNORECASE)
        clean_q = pat.sub(target_name, query).strip()

        logger.warning(
            f"[PremiseChecker] Phát hiện văn bản luật ngộ nhận/không tồn tại: '{matched_fake_name}'. "
            f"Văn bản thực tế điều chỉnh: '{taxonomy.governing_law_title}'"
        )
        return {
            "has_false_premise": True,
            "is_fake_law": True,
            "queried_law": matched_fake_name,
            "law_display": taxonomy.governing_law_title,
            "message": taxonomy.explanation_template,
            "cleaned_query": clean_q,
        }

    # -- KIỂM TRA 2: BÓC TÁCH VĂN BẢN VÀ KIỂM TRA VỚI REGISTRY CSDL --
    law_match = LAW_NAME_PATTERN.search(query)
    if law_match:
        full_mentioned_law = law_match.group(0).strip()
        raw_law_name = law_match.group(2).strip()

        # Kiểm tra xem tên văn bản có trong Registry hoặc hệ thống văn bản đã biết không
        is_known = registry.is_known_law(full_mentioned_law) or registry.is_known_law(raw_law_name)

        if not is_known and len(raw_law_name) > 4:
            # Kiểm tra thêm trong records nếu có
            exists_in_records = False
            if records:
                exists_in_records = any(
                    raw_law_name.lower() in r.get("law_name", "").lower()
                    for r in records
                )

            if not exists_in_records:
                msg = f"Trong hệ thống pháp luật Việt Nam hiện hành hoàn toàn KHÔNG CÓ văn bản nào tên là '{full_mentioned_law}'."
                clean_q = query.replace(full_mentioned_law, "").strip()
                clean_q = re.sub(r"\s{2,}", " ", clean_q).strip(" ,:;?")
                logger.warning(f"[PremiseChecker] Phát hiện văn bản không tồn tại trong Registry/CSDL: '{full_mentioned_law}'")
                return {
                    "has_false_premise": True,
                    "is_fake_law": True,
                    "queried_law": full_mentioned_law,
                    "law_display": full_mentioned_law,
                    "message": msg,
                    "cleaned_query": clean_q or query,
                }

    # -- KIỂM TRA 3: PHÁT HIỆN GÁN SAI ĐIỀU LUẬT HOẶC SỐ ĐIỀU KHÔNG TỒN TẠI --
    article_matches = ARTICLE_PATTERN.findall(query)
    if not article_matches:
        return None

    # Tìm văn bản luật tương ứng trong Registry
    law_doc = registry.resolve_law_by_name_or_query(query)

    if law_doc:
        for match in article_matches:
            queried_art = f"Điều {match}"

            # 3.1: Kiểm tra mismatch giữa số điều và chủ đề/tội danh thực tế
            mismatch = registry.check_article_topic_mismatch(law_doc, queried_art, query)
            if mismatch:
                logger.warning(
                    f"[PremiseChecker] Phát hiện tiền đề sai (gán nhầm Điều cho Tội danh/Chủ đề): "
                    f"'{queried_art}' ({mismatch.get('actual_title')}) bị gán cho '{mismatch.get('queried_topic')}'. "
                    f"Điều đúng: '{mismatch.get('correct_article')}' ({mismatch.get('correct_title')})"
                )
                return mismatch

            # 3.2: Kiểm tra số điều có tồn tại hợp lệ trong văn bản không
            is_valid, err_msg = registry.validate_article(law_doc, queried_art)
            if not is_valid:
                clean_q = re.sub(r"(?i)\b(theo\s+)?[Đđ]iều\s+\d+[a-zA-Z]?\b", "", query).strip()
                clean_q = re.sub(r"\s{2,}", " ", clean_q).strip(" ,:;?")
                logger.warning(
                    f"[PremiseChecker] Phát hiện tiền đề sai (số điều không hợp lệ): "
                    f"'{queried_art}' trong '{law_doc.official_title}'. Lý do: {err_msg}"
                )
                return {
                    "has_false_premise": True,
                    "queried_article": queried_art,
                    "law_display": law_doc.official_title,
                    "max_article": law_doc.max_article_num,
                    "message": err_msg or f"{law_doc.official_title} không có {queried_art}.",
                    "cleaned_query": clean_q,
                }

    return None
