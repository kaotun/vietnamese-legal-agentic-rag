"""Module bóc tách sự kiện pháp lý đa chiều (Legal Fact Extraction & Fact Ambiguity).

Hỗ trợ kiến trúc Two-Tier Fact Extraction:
1. Bóc tách đa chủ thể (Multi-Subject: Kẻ chủ mưu, người thực hành, nạn nhân).
2. Suy luận độ tuổi gián tiếp (Implicit Age: Năm sinh -> Tuổi; Khối lớp -> Tuổi).
3. Bóc tách thời điểm diễn ra sự kiện (Incident Year / Temporal Anchoring).
4. Nhận diện tính mơ hồ của dữ kiện (Fact Ambiguity: "trọng thương" vs tỷ lệ %).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

CURRENT_YEAR = 2026

# Pattern bóc tách độ tuổi trực tiếp: "12 tuổi", "cháu 14 tuổi", "em 15 tuổi", "25 tuổi"
AGE_DIRECT_PATTERN = re.compile(
    r"\b(?:cháu|em|con|bé|học\s+sinh|người|đối\s+tượng|thủ\s+phạm|anh|chị|ông|bà)?\s*(\d{1,2})\s*tuổi\b",
    re.IGNORECASE,
)

# Pattern bóc tách năm sinh: "sinh năm 2013", "sinh năm 2010"
BIRTH_YEAR_PATTERN = re.compile(
    r"\bsinh\s+(?:ngày\s+\d{1,2}[\/\-]\d{1,2}[\/\-])?(?:tháng\s+\d{1,2}[\/\-])?năm\s*(\d{4})\b",
    re.IGNORECASE,
)

# Pattern bóc tách khối lớp học phổ thông: "học sinh lớp 6", "lớp 7", "lớp 9"
GRADE_PATTERN = re.compile(
    r"\b(?:học\s+sinh\s+)?lớp\s*([1-9]|1[0-2])\b",
    re.IGNORECASE,
)

# Pattern bóc tách năm diễn ra sự việc: "xảy ra năm 2024", "vào năm 2023", "năm 2025"
INCIDENT_YEAR_PATTERN = re.compile(
    r"\b(?:xảy\s+ra|diễn\s+ra|vào|thực\s+hiện|phạm\s+tội)?\s*(?:tháng\s+\d{1,2}\s+)?năm\s*(20\d{2}|19\d{2})\b",
    re.IGNORECASE,
)

# Pattern bóc tách tỷ lệ thương tật / tổn thương cơ thể: "35%", "thương tật 61%", "tỷ lệ 11%"
INJURY_PERCENTAGE_PATTERN = re.compile(
    r"(?:tỷ\s+lệ|thương\s+tật|tổn\s+thương|thương\s+tích)?\s*(\d{1,2}(?:\.\d+)?)\s*%",
    re.IGNORECASE,
)

# Mô tả định tính tổn thương
QUALITATIVE_INJURY_PATTERN = re.compile(
    r"\b(trọng\s+thương|thương\s+tích\s+nặng|thương\s+tích\s+nhẹ|chấn\s+thương\s+sọ\s+não|gãy\s+xương|thương\s+tật|tổn\s+hại\s+sức\s+khỏe)\b",
    re.IGNORECASE,
)

# Hành vi vi phạm / Hành vi pháp lý
ACTION_PATTERNS = [
    (r"\b(đánh\s+nhau|đánh|chém|đâm|hành\s+hung|tấn\s+công|gây\s+thương\s+tích)\b", "cố_ý_gây_thương_tích"),
    (r"\b(trộm\s+cắp|trộm|lấy\s+trộm|ăn\s+trộm|móc\s+túi)\b", "trộm_cắp_tài_sản"),
    (r"\b(cướp|cướp\s+giật)\b", "cướp_tài_sản"),
    (r"\b(giết\s+người|giết)\b", "giết_người"),
    (r"\b(lừa\s+đảo|chiếm\s+đoạt)\b", "lừa_đảo_chiếm_đoạt_tài_sản"),
    (r"\b(xúi\s+giục|lôi\s+kéo|thuê|chủ\s+mưu|chỉ\s+đạo)\b", "xúi_giục_đồng_phạm"),
    (r"\b(vượt\s+đèn\s+đỏ|đi\s+ngược\s+chiều|nồng\s+độ\s+cồn|lái\s+xe)\b", "vi_phạm_giao_thông"),
    (r"\b(thử\s+việc|hợp\s+đồng\s+lao\s+động|nghỉ\s+việc|sa\s+thải)\b", "lao_động_việc_làm"),
    (r"\b(nghỉ\s+thai\s+sản|thai\s+sản|sinh\s+con)\b", "chế_độ_thai_sản"),
    (r"\b(thời\s+hiệu\s+khởi\s+kiện|tranh\s+chấp\s+hợp\s+đồng|đòi\s+nợ)\b", "tranh_chấp_dân_sự"),
]

# Pattern yêu cầu thông tin
REQUESTED_INFO_PATTERNS = [
    (r"\b(mấy\s+năm\s+tù|bao\s+nhiêu\s+năm\s+tù|đi\s+tù|phạt\s+tù|án\s+tù|ngồi\s+tù)\b", "mức_hình_phạt_tù"),
    (r"\b(truy\s+cứu\s+hình\s+sự|bị\s+khởi\s+tố|chịu\s+trách\s+nhiệm\s+hình\s+sự|tội\s+gì)\b", "trách_nhiệm_hình_sự"),
    (r"\b(phạt\s+bao\s+nhiêu|mức\s+phạt|phạt\s+tiền|bị\s+phạt\s+thế\s+nào)\b", "mức_xử_phạt"),
    (r"\b(có\s+vi\s+phạm\s+không|vi\s+phạm\s+luật\s+không|đúng\s+hay\s+sai)\b", "tính_hợp_pháp"),
    (r"\b(bồi\s+thường|đền\s+bù|trách\s+nhiệm\s+dân\s+sự)\b", "trách_nhiệm_bồi_thường"),
    (r"\b(còn\s+thời\s+hiệu\s+không|hết\s+thời\s+hiệu|khởi\s+kiện\s+được\s+không)\b", "thời_hiệu_khởi_kiện"),
]


@dataclass
class SubjectInfo:
    """Thông tin về một chủ thể tham gia trong vụ việc pháp lý."""
    label: str
    age: Optional[int] = None
    role: str = "perpetrator"  # "perpetrator" | "instigator" | "victim" | "accomplice"
    is_minor: bool = False
    age_source: str = "direct"  # "direct" | "birth_year" | "grade_level"


@dataclass
class LegalFacts:
    """Tập hợp sự kiện pháp lý chuẩn hóa từ câu hỏi người dùng."""
    raw_query: str
    age: Optional[int] = None  # Tuổi của đối tượng chính được hỏi
    subjects: List[SubjectInfo] = field(default_factory=list)
    incident_year: int = CURRENT_YEAR  # Năm xảy ra sự việc (mặc định hiện tại)
    victim: Optional[str] = None
    action: Optional[str] = None
    action_type: Optional[str] = None
    has_instigator: bool = False  # Có hành vi xúi giục / chủ mưu người khác
    injury_description: Optional[str] = None
    injury_percentage: Optional[float] = None
    legal_references: List[Dict[str, str]] = field(default_factory=list)
    requested_information: Optional[str] = None
    domain: str = "general"
    fact_ambiguities: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "raw_query": self.raw_query,
            "age": self.age,
            "subjects": [s.__dict__ for s in self.subjects],
            "incident_year": self.incident_year,
            "victim": self.victim,
            "action": self.action,
            "action_type": self.action_type,
            "has_instigator": self.has_instigator,
            "injury_description": self.injury_description,
            "injury_percentage": self.injury_percentage,
            "legal_references": self.legal_references,
            "requested_information": self.requested_information,
            "domain": self.domain,
            "fact_ambiguities": self.fact_ambiguities,
        }

    @property
    def is_multi_subject(self) -> bool:
        return len(self.subjects) > 1

    @property
    def has_instigation(self) -> bool:
        return self.has_instigator or any(s.role == "instigator" for s in self.subjects)

    @property
    def subject_age(self) -> Optional[int]:
        return self.age


class LegalFactExtractor:
    """Fact Extractor đa tầng: Hỗ trợ suy luận tuổi gián tiếp, đa chủ thể và mốc thời gian."""

    def extract(self, query: str) -> LegalFacts:
        """Alias cho extract_facts."""
        return self.extract_facts(query)

    def extract_facts(self, query: str) -> LegalFacts:
        if not query:
            return LegalFacts(raw_query="")

        facts = LegalFacts(raw_query=query)

        # 1. Trích xuất năm xảy ra sự việc (Temporal Anchoring) - Loại trừ năm sinh
        clean_for_inc = BIRTH_YEAR_PATTERN.sub("", query)
        inc_match = INCIDENT_YEAR_PATTERN.search(clean_for_inc)
        if inc_match:
            facts.incident_year = int(inc_match.group(1))

        # 2. Bóc tách đa chủ thể & Độ tuổi (Direct / Birth year / Grade level)
        subjects = self._extract_subjects(query, facts.incident_year)
        facts.subjects = subjects

        if subjects:
            # Ưu tiên lấy tuổi của người thực hiện hành vi trực tiếp
            perps = [s for s in subjects if s.role in ("perpetrator", "accomplice")]
            if perps:
                facts.age = perps[0].age
            else:
                facts.age = subjects[0].age

        # 3. Trích xuất tỷ lệ thương tật %
        pct_match = INJURY_PERCENTAGE_PATTERN.search(query)
        if pct_match:
            try:
                facts.injury_percentage = float(pct_match.group(1))
            except ValueError:
                pass

        # 4. Trích xuất mô tả định tính thương tích & Nhận diện Fact Ambiguity
        qual_match = QUALITATIVE_INJURY_PATTERN.search(query)
        if qual_match:
            facts.injury_description = qual_match.group(1).lower()

        if facts.injury_description and facts.injury_percentage is None:
            ambiguity_msg = (
                f"Dữ kiện '{facts.injury_description}' chỉ là mô tả thương tích thực tế định tính, "
                f"chưa có kết luận giám định tỷ lệ tổn thương cơ thể (%) của cơ quan y khoa có thẩm quyền "
                f"để xác định chính xác khung hình phạt của Điều 134 BLHS."
            )
            facts.fact_ambiguities.append(ambiguity_msg)

        # 5. Trích xuất hành vi và phân loại domain
        # 5. Trích xuất hành vi và phân loại domain
        if re.search(r"\b(xúi\s+giục|lôi\s+kéo|thuê|chủ\s+mưu|chỉ\s+đạo)\b", query, re.I):
            facts.has_instigator = True

        for pat, act_type in ACTION_PATTERNS:
            m = re.search(pat, query, re.I)
            if m:
                facts.action = m.group(1).lower()
                facts.action_type = act_type
                break

        # 6. Trích xuất thông tin người dùng đang hỏi
        for pat, req_type in REQUESTED_INFO_PATTERNS:
            if re.search(pat, query, re.I):
                facts.requested_information = req_type
                break

        # 7. Trích xuất viện dẫn điều luật
        art_matches = re.finditer(r"\bĐiều\s+(\d+[a-zA-Z]?)\b", query, re.IGNORECASE)
        for m in art_matches:
            art_num = m.group(1)
            law_name = "Văn bản chưa xác định"
            if re.search(r"\b(blhs|bộ luật hình sự|hình sự)\b", query, re.I):
                law_name = "Bộ luật Hình sự"
            elif re.search(r"\b(blld|bộ luật lao động|lao động)\b", query, re.I):
                law_name = "Bộ luật Lao động"
            elif re.search(r"\b(blds|bộ luật dân sự|dân sự)\b", query, re.I):
                law_name = "Bộ luật Dân sự"
            elif re.search(r"\b(nghị định 100|giao thông)\b", query, re.I):
                law_name = "Nghị định 100/2019/NĐ-CP"

            facts.legal_references.append({
                "article": f"Điều {art_num}",
                "article_number": art_num,
                "document": law_name,
            })

        # 8. Xác định lĩnh vực pháp luật (Domain)
        if (
            re.search(r"\b(blhs|hình sự|tội|án tù|phạt tù|truy cứu|giết|đánh|chém|cướp|trộm|xúi giục)\b", query, re.I)
            or (facts.action_type in ("cố_ý_gây_thương_tích", "trộm_cắp_tài_sản", "cướp_tài_sản", "giết_người", "xúi_giục_đồng_phạm"))
        ):
            facts.domain = "criminal"
        elif re.search(r"\b(bllđ|lao động|tiền lương|thử việc|sa thải|nghỉ phép|thai sản|tuổi lao động)\b", query, re.I):
            facts.domain = "labor"
        elif re.search(r"\b(blds|dân sự|thừa kế|bồi thường thiệt hại|hợp đồng|đặt cọc|thời hiệu khởi kiện)\b", query, re.I):
            facts.domain = "civil"
        elif re.search(r"\b(giao thông|đèn đỏ|nồng độ cồn|tước bằng|giấy phép lái xe)\b", query, re.I):
            facts.domain = "traffic"

        logger.info(
            f"[FactExtractor] Trích xuất: age={facts.age}, domain={facts.domain}, "
            f"year={facts.incident_year}, subjects={len(facts.subjects)}, "
            f"ambiguities={len(facts.fact_ambiguities)}"
        )
        return facts

    def _extract_subjects(self, query: str, incident_year: int) -> List[SubjectInfo]:
        """Bóc tách danh sách các chủ thể kèm tuổi trực tiếp hoặc suy luận gián tiếp."""
        subjects: List[SubjectInfo] = []

        # 1. Bóc tách tuổi trực tiếp qua cụm từ "X tuổi"
        for m in re.finditer(r"(?:(anh|chị|ông|bà|cháu|em|con|bé|học\s+sinh|người)(?:\s+([A-ZÀ-Ỹa-zà-ỹ]+))?)?\s*\b(\d{1,2})\s*tuổi\b", query, re.I):
            role_hint = (m.group(1) or "").lower()
            name_hint = (m.group(2) or "").strip()
            age_val = int(m.group(3))

            role = "perpetrator"
            if role_hint in ("anh", "chị", "ông", "bà") and ("xúi giục" in query.lower() or "thuê" in query.lower()):
                role = "instigator"
            elif role_hint in ("cháu", "em", "con", "bé") and "xúi giục" in query.lower():
                role = "perpetrator"

            subj = SubjectInfo(
                label=f"{role_hint} {name_hint}".strip() or f"Người {age_val} tuổi",
                age=age_val,
                role=role,
                is_minor=age_val < 18,
                age_source="direct",
            )
            subjects.append(subj)

        # 2. Bóc tách qua năm sinh nếu chưa có hoặc có thêm người sinh năm X
        for m in BIRTH_YEAR_PATTERN.finditer(query):
            b_year = int(m.group(1))
            calc_age = incident_year - b_year
            if 0 < calc_age <= 100:
                # Kiểm tra xem đã có chủ thể này chưa
                if not any(s.age == calc_age for s in subjects):
                    subj = SubjectInfo(
                        label=f"Người sinh năm {b_year} ({calc_age} tuổi)",
                        age=calc_age,
                        role="perpetrator",
                        is_minor=calc_age < 18,
                        age_source="birth_year",
                    )
                    subjects.append(subj)

        # 3. Bóc tách qua khối lớp học phổ thông
        for m in GRADE_PATTERN.finditer(query):
            grade_num = int(m.group(1))
            est_age = 5 + grade_num  # Lớp 1 -> 6 tuổi, Lớp 6 -> 11 tuổi, Lớp 7 -> 12 tuổi, Lớp 9 -> 14 tuổi
            if not subjects:
                subj = SubjectInfo(
                    label=f"Học sinh lớp {grade_num} (~{est_age} tuổi)",
                    age=est_age,
                    role="perpetrator",
                    is_minor=est_age < 18,
                    age_source="grade_level",
                )
                subjects.append(subj)

        return subjects


_extractor_instance: Optional[LegalFactExtractor] = None


def get_fact_extractor() -> LegalFactExtractor:
    global _extractor_instance
    if _extractor_instance is None:
        _extractor_instance = LegalFactExtractor()
    return _extractor_instance
