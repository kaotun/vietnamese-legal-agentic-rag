"""Node kiểm định điều kiện áp dụng pháp luật và kiểm soát chốt chặn (Legal Applicability Validator Node).

Thực hiện 3 lớp kiểm tra tiền thẩm tra:
1. Reference Validator: Trích xuất và đối chiếu văn bản, điều luật.
2. Fact Validator: Trích xuất độ tuổi, hành vi, tỷ lệ thương tật và phát hiện Fact Ambiguity.
3. Applicability Gate: Kích hoạt Legal Rule Engine từ CSDL để quyết định 'ALLOWED' hay 'BLOCKED'.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from src.agent.state import LegalAgentState
from src.domain.fact_extractor import get_fact_extractor
from src.domain.rule_engine import get_rule_engine

logger = logging.getLogger(__name__)


async def applicability_validator_node(state: LegalAgentState) -> Dict[str, Any]:
    """Kiểm tra điều kiện áp dụng pháp luật trước khi cho phép truy hồi và tính toán hình phạt."""
    query = state.get("standalone_query") or state["query"]
    logger.info(f"[ApplicabilityValidator] Đang phân tích điều kiện áp dụng cho: '{query}'")

    # 1. Bóc tách Legal Facts & Nhận diện Fact Ambiguity
    fact_extractor = get_fact_extractor()
    legal_facts = fact_extractor.extract_facts(query)

    # 2. Đánh giá tính áp dụng qua Legal Rule Engine (Data-driven từ CSDL)
    rule_engine = get_rule_engine()
    eval_result = rule_engine.evaluate_facts(legal_facts)

    logger.info(
        f"[ApplicabilityValidator] Kết quả đánh giá: status={eval_result.status}, "
        f"blocking_factors={eval_result.blocking_factors}"
    )

    return {
        "legal_facts": legal_facts.to_dict(),
        "eligibility_status": eval_result.status,
        "blocking_factors": eval_result.blocking_factors,
        "applicable_rules": eval_result.applicable_rules,
        "fact_ambiguities": eval_result.fact_ambiguities,
        "legal_decision": eval_result.legal_decision,
    }
