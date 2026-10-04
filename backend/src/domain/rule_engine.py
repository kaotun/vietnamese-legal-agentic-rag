"""Động cơ thực thi quy tắc pháp lý có cấu trúc (Legal Rule Engine).

Vận hành hoàn toàn Data-Driven dựa trên bảng `legal_applicability_rules` trong PostgreSQL qua DatabasePool.
Hỗ trợ:
1. Thẩm tra Hiệu lực Thời gian (Temporal Validity: incident_year vs effective_from / effective_to).
2. Xử lý kịch bản Đa chủ thể (Multi-Subject: Phân biệt người xúi giục và người thực hành).
3. Chốt chặn điều kiện áp dụng (Eligibility Matrix & Hard Gate).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional

from src.core.database import get_db_pool
from src.domain.fact_extractor import LegalFacts, SubjectInfo

logger = logging.getLogger(__name__)


@dataclass
class RuleEvaluationResult:
    """Kết quả kiểm định điều kiện áp dụng pháp luật của Rule Engine."""
    status: str  # "ALLOWED" | "BLOCKED" | "REQUIRE_CONDITION"
    blocking_factors: List[str] = field(default_factory=list)
    applicable_rules: List[Dict[str, Any]] = field(default_factory=list)
    legal_decision: Optional[Dict[str, Any]] = None
    fact_ambiguities: List[str] = field(default_factory=list)

    @property
    def is_blocked(self) -> bool:
        return self.status == "BLOCKED"

    @property
    def action(self) -> str:
        return self.status

    @property
    def rule_code(self) -> str:
        if self.applicable_rules:
            return self.applicable_rules[0].get("rule_id", "")
        return ""

    @property
    def explanation(self) -> str:
        if self.legal_decision:
            return self.legal_decision.get("primary_conclusion") or "\n".join(self.blocking_factors)
        return "\n".join(self.blocking_factors)

    @property
    def mandatory_citation(self) -> str:
        if self.legal_decision:
            return self.legal_decision.get("governing_law_basis", "")
        return ""

    @property
    def temporal_warning(self) -> Optional[str]:
        if self.legal_decision:
            return self.legal_decision.get("temporal_warning")
        return None


class LegalRuleEngine:
    """Legal Rule Engine kiểm tra tính tương thích và điều kiện áp dụng pháp luật."""

    _instance: Optional[LegalRuleEngine] = None

    def __init__(self):
        self._rules_cache: List[Dict[str, Any]] = []
        self._is_loaded = False

    def evaluate(self, facts: LegalFacts, query: str = "", context_articles: Optional[List[str]] = None) -> RuleEvaluationResult:
        """Alias tương thích cho evaluate_facts."""
        return self.evaluate_facts(facts)

    @classmethod
    def get_instance(cls) -> LegalRuleEngine:
        if cls._instance is None:
            cls._instance = cls()
            cls._instance.load_rules()
        return cls._instance

    def load_rules(self, force_reload: bool = False) -> None:
        """Tải toàn bộ quy tắc pháp lý từ PostgreSQL vào RAM cache qua connection pool."""
        if self._is_loaded and not force_reload:
            return

        try:
            pool = get_db_pool()
            with pool.get_cursor(dict_cursor=True) as cur:
                cur.execute("""
                    SELECT rule_id, rule_name, domain, target_law_id, target_article,
                           condition_schema, effect_type, legal_decision,
                           effective_from, effective_to, version
                    FROM legal_applicability_rules;
                """)
                rows = cur.fetchall()
                self._rules_cache = [dict(r) for r in rows]
                self._is_loaded = True
                logger.info(f"[LegalRuleEngine] Đã nạp thành công {len(self._rules_cache)} quy tắc pháp lý qua Connection Pool.")
        except Exception as e:
            logger.warning(f"[LegalRuleEngine] Không thể nạp quy tắc từ CSDL ({e}). Chuyển sang chế độ built-in rules (offline fallback).")
            self._load_fallback_rules()
            self._is_loaded = True

    def _load_fallback_rules(self) -> None:
        """Nạp các quy tắc pháp luật cốt lõi tích hợp sẵn khi cơ sở dữ liệu ngoại vi chưa sẵn sàng."""
        try:
            from db.seeds.seed_applicability_rules import RULES_DATA
            self._rules_cache = [
                {
                    "rule_id": r[0],
                    "rule_name": r[1],
                    "domain": r[2],
                    "target_law_id": r[3],
                    "target_article": r[4],
                    "condition_schema": r[5],
                    "effect_type": r[6],
                    "legal_decision": r[7],
                    "effective_from": r[8],
                    "effective_to": r[9],
                    "version": r[10],
                }
                for r in RULES_DATA
            ]
        except Exception as err:
            logger.error(f"[LegalRuleEngine] Không thể nạp seed fallback rules: {err}")
            self._rules_cache = []

    def evaluate_facts(self, facts: LegalFacts) -> RuleEvaluationResult:
        """Đánh giá tập hợp sự kiện pháp lý dựa trên các quy tắc trong CSDL và mốc thời gian."""
        if not self._is_loaded:
            self.load_rules()

        fact_ambiguities = list(facts.fact_ambiguities)

        # ── 0. XỬ LÝ ĐẶC THÙ: KỊCH BẢN ĐA CHỦ THỂ (NGƯỜI LỚN XÚI GIỤC TRẺ EM) ──
        if facts.has_instigator and len(facts.subjects) >= 2:
            instigators = [s for s in facts.subjects if s.role == "instigator" and s.age and s.age >= 18]
            minors = [s for s in facts.subjects if s.role == "perpetrator" and s.age and s.age < 18]

            if instigators and minors:
                inst_age = instigators[0].age
                minor_age = minors[0].age
                logger.info(f"[LegalRuleEngine] Nhận diện án đồng phạm/xúi giục: Người lớn ({inst_age} tuổi) xúi giục trẻ em ({minor_age} tuổi).")

                decision = {
                    "applicable": True,
                    "reason": "instigator_adult_minor_liability",
                    "blocking_factors": [],
                    "primary_conclusion": (
                        f"Trong vụ việc này cần phân định trách nhiệm hình sự của hai chủ thể: "
                        f"(1) Người {inst_age} tuổi bị truy cứu trách nhiệm hình sự về tội danh thực hiện với tình tiết tăng nặng; "
                        f"(2) Cháu {minor_age} tuổi {'hoàn toàn không bị truy cứu trách nhiệm hình sự' if minor_age < 14 else 'chỉ chịu trách nhiệm nếu thuộc tội rất nghiêm trọng hoặc đặc biệt nghiêm trọng'}."
                    ),
                    "governing_law_basis": "Điều 17 (Đồng phạm), Điểm m Khoản 1 Điều 52 (Xúi giục người dưới 18 tuổi) và Điều 12 Bộ luật Hình sự 2015.",
                    "analysis_points": [
                        f"Đối với người xúi giục ({inst_age} tuổi): Là người thành niên có đủ năng lực trách nhiệm hình sự. Căn cứ Điều 17 BLHS, người xúi giục là đồng phạm. Đặc biệt, căn cứ Điểm m Khoản 1 Điều 52 BLHS, hành vi 'xúi giục người dưới 18 tuổi phạm tội' là tình tiết tăng nặng trách nhiệm hình sự.",
                        f"Đối với người thực hành ({minor_age} tuổi): Căn cứ Điều 12 BLHS, người dưới 14 tuổi chưa đủ tuổi chịu trách nhiệm hình sự đối với mọi tội phạm. Cháu không bị truy cứu hình sự và không bị phạt tù.",
                        f"Về trách nhiệm dân sự: Căn cứ Điều 586 Bộ luật Dân sự 2015, cha mẹ hoặc người giám hộ của cháu {minor_age} tuổi cùng người xúi giục có trách nhiệm liên đới bồi thường thiệt hại."
                    ],
                    "remedy_laws": [
                        {"law": "Bộ luật Hình sự 2015", "article": "Điều 17", "title": "Đồng phạm", "role": "Xác định vai trò người xúi giục"},
                        {"law": "Bộ luật Hình sự 2015", "article": "Điều 52", "title": "Các tình tiết tăng nặng", "role": "Điểm m: Xúi giục người dưới 18 tuổi phạm tội"},
                        {"law": "Bộ luật Hình sự 2015", "article": "Điều 12", "title": "Tuổi chịu trách nhiệm hình sự", "role": "Miễn trách nhiệm cho người dưới 14 tuổi"},
                        {"law": "Bộ luật Dân sự 2015", "article": "Điều 586", "title": "Bồi thường thiệt hại", "role": "Bồi thường dân sự"}
                    ],
                    "practical_guidance": "Cơ quan tiến hành tố tụng sẽ khởi tố, điều tra đối với người xúi giục; riêng đối với cháu bé dưới 14 tuổi sẽ chuyển hồ sơ sang cơ quan công an địa phương để áp dụng biện pháp giáo dục."
                }
                return RuleEvaluationResult(
                    status="REQUIRE_CONDITION",
                    blocking_factors=[],
                    applicable_rules=[{"rule_id": "RULE_CRIMINAL_INSTIGATOR_ADULT_MINOR"}],
                    legal_decision=decision,
                    fact_ambiguities=fact_ambiguities,
                )

        # ── 1. ĐỐI CHIẾU CÁC QUY TẮC CSDL CÓ KIỂM TRA HIỆU LỰC THỜI GIAN (TEMPORAL VALIDITY) ──
        for rule in self._rules_cache:
            # 1.1 Kiểm tra hiệu lực thời gian của luật so với năm xảy ra sự kiện
            eff_from = rule.get("effective_from")
            if eff_from:
                eff_from_year = eff_from.year if hasattr(eff_from, "year") else int(str(eff_from)[:4])
                if facts.incident_year < eff_from_year:
                    # Sự kiện xảy ra trước ngày văn bản luật có hiệu lực -> không áp dụng hồi tố bất lợi
                    continue

            eff_to = rule.get("effective_to")
            if eff_to:
                eff_to_year = eff_to.year if hasattr(eff_to, "year") else int(str(eff_to)[:4])
                if facts.incident_year > eff_to_year:
                    # Văn bản luật đã hết hiệu lực tại thời điểm xảy ra sự kiện
                    continue

            # 1.2 Kiểm tra Domain tương thích
            rule_domain = rule.get("domain", "")
            effect_type = rule.get("effect_type", "")
            if rule_domain and facts.domain != "general" and rule_domain != facts.domain:
                continue

            cond = rule.get("condition_schema")
            if isinstance(cond, str):
                cond = json.loads(cond)

            cond_facts = cond.get("facts", {})

            # 1.3 Kiểm tra điều kiện tuổi (Age condition)
            target_age = facts.age
            if "age" in cond_facts and target_age is not None:
                age_spec = cond_facts["age"]
                op = age_spec.get("operator")
                val = age_spec.get("value")

                is_condition_met = False
                if op == "<" and target_age < val:
                    is_condition_met = True
                elif op == "<=" and target_age <= val:
                    is_condition_met = True
                elif op == ">" and target_age > val:
                    is_condition_met = True
                elif op == "between":
                    min_val = age_spec.get("min", 0)
                    max_val = age_spec.get("max", 100)
                    if min_val <= target_age <= max_val:
                        is_condition_met = True

                if is_condition_met:
                    decision = rule.get("legal_decision")
                    if isinstance(decision, str):
                        decision = json.loads(decision)

                    if effect_type == "BLOCK":
                        logger.warning(
                            f"[LegalRuleEngine] KÍCH HOẠT HARD GATE: Quy tắc '{rule.get('rule_id')}' "
                            f"chặn hình phạt hình sự đối với đối tượng {target_age} tuổi (Năm sự kiện: {facts.incident_year})."
                        )
                        return RuleEvaluationResult(
                            status="BLOCKED",
                            blocking_factors=decision.get("blocking_factors", ["age"]),
                            applicable_rules=[rule],
                            legal_decision=decision,
                            fact_ambiguities=fact_ambiguities,
                        )

                    elif effect_type == "REQUIRE_CONDITION":
                        return RuleEvaluationResult(
                            status="REQUIRE_CONDITION",
                            blocking_factors=[],
                            applicable_rules=[rule],
                            legal_decision=decision,
                            fact_ambiguities=fact_ambiguities,
                        )

        # Mặc định: Cho phép luồng RAG thông thường
        return RuleEvaluationResult(
            status="ALLOWED",
            blocking_factors=[],
            applicable_rules=[],
            legal_decision=None,
            fact_ambiguities=fact_ambiguities,
        )


def get_rule_engine() -> LegalRuleEngine:
    return LegalRuleEngine.get_instance()
