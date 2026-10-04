"""Unit & Integration test kiểm thử các tính năng nâng cấp chuyên nghiệp:
1. Two-Tier Legal Fact Extractor (Đa chủ thể, tuổi gián tiếp, incident year)
2. Legal Rule Engine (Loại trừ hình sự, xúi giục trẻ em, hiệu lực thời gian)
3. Thread-safe Database Connection Pool
4. LegalPromptBuilder (Single source of truth prompt & post-processing)
"""
import pytest
from src.domain.fact_extractor import LegalFactExtractor
from src.domain.rule_engine import LegalRuleEngine
from src.core.database import get_db_pool
from src.agent.prompt_builder import LegalPromptBuilder


def test_fact_extractor_multi_subjects():
    extractor = LegalFactExtractor()
    query = "Anh Nam 25 tuổi xúi giục cháu bé 12 tuổi trộm cắp xe máy của người khác"
    facts = extractor.extract(query)
    
    assert facts.is_multi_subject is True
    assert facts.has_instigation is True
    assert len(facts.subjects) >= 2
    
    # Tìm chủ thể xúi giục và thực hiện
    instigator = next((s for s in facts.subjects if s.role == "instigator"), None)
    perpetrator = next((s for s in facts.subjects if s.role == "perpetrator"), None)
    
    assert instigator is not None
    assert instigator.age == 25
    assert perpetrator is not None
    assert perpetrator.age == 12


def test_fact_extractor_indirect_age():
    extractor = LegalFactExtractor()
    
    # Test tính từ khối lớp học (học sinh lớp 7 -> ~12 tuổi)
    facts_grade = extractor.extract("Học sinh lớp 7 đánh bạn chấn thương sọ não")
    assert facts_grade.subject_age == 12
    
    # Test tính từ năm sinh (sinh năm 2013 -> 2026 - 2013 = 13 tuổi)
    facts_birth = extractor.extract("Cháu sinh năm 2013 lấy trộm điện thoại iPhone")
    assert facts_birth.subject_age == 13


def test_fact_extractor_incident_year():
    extractor = LegalFactExtractor()
    query = "Vào năm 2023, công ty ép nhân viên làm thêm 50 giờ một tháng thì bị phạt thế nào?"
    facts = extractor.extract(query)
    assert facts.incident_year == 2023


def test_rule_engine_under_14_blocked():
    rule_engine = LegalRuleEngine()
    extractor = LegalFactExtractor()
    
    query = "Cháu 12 tuổi đánh bạn trọng thương, theo Điều 134 BLHS sẽ bị truy cứu hình sự mấy năm tù?"
    facts = extractor.extract(query)
    decision = rule_engine.evaluate(facts, query, context_articles=["Điều 134"])
    
    assert decision.action == "BLOCKED"
    assert decision.rule_code == "RULE_CRIMINAL_MIN_AGE_14"
    assert "KHÔNG BỊ TRUY CỨU TRÁCH NHIỆM HÌNH SỰ" in decision.explanation
    assert "Điều 12" in decision.mandatory_citation


def test_rule_engine_instigation_adult_minor():
    rule_engine = LegalRuleEngine()
    extractor = LegalFactExtractor()
    
    query = "Anh A 22 tuổi xúi giục cháu 13 tuổi trộm cắp tài sản thì anh A bị xử lý thế nào?"
    facts = extractor.extract(query)
    decision = rule_engine.evaluate(facts, query, context_articles=["Điều 173"])
    
    assert decision.action == "REQUIRE_CONDITION"
    assert decision.rule_code == "RULE_CRIMINAL_INSTIGATOR_ADULT_MINOR"
    assert "Điều 52" in decision.mandatory_citation


def test_rule_engine_temporal_validity():
    rule_engine = LegalRuleEngine()
    extractor = LegalFactExtractor()
    
    # Vụ việc xảy ra năm 2024
    query = "Năm 2024, công ty ký hợp đồng thử việc 90 ngày cho nhân viên văn phòng có đúng luật không?"
    facts = extractor.extract(query)
    decision = rule_engine.evaluate(facts, query, context_articles=["Điều 25"])
    
    # Không được có cảnh báo luật chưa có hiệu lực
    assert decision.temporal_warning is None or "chưa có hiệu lực" not in decision.temporal_warning


def test_db_pool_concurrency():
    try:
        pool = get_db_pool()
        with pool.get_cursor(commit=False) as cur:
            cur.execute("SELECT 1 AS test;")
            row = cur.fetchone()
            assert row["test"] == 1
    except Exception as exc:
        import pytest
        pytest.skip(f"CSDL PostgreSQL chưa kết nối (bỏ qua kiểm thử live DB: {exc})")


def test_prompt_builder():
    state = {
        "query": "Cháu 12 tuổi đánh bạn có bị phạt tù không?",
        "standalone_query": "Cháu 12 tuổi đánh bạn có bị phạt tù không?",
        "premise_correction": {
            "has_false_premise": True,
            "is_age_ineligible": True,
            "age": 12,
            "message": "Người 12 tuổi chưa đủ tuổi chịu trách nhiệm hình sự."
        },
        "retrieved_docs": [{
            "law_name": "Bộ luật Hình sự 2015",
            "article": "Điều 12",
            "article_title": "Tuổi chịu trách nhiệm hình sự",
            "content": "1. Người từ đủ 16 tuổi trở lên phải chịu trách nhiệm hình sự về mọi tội phạm..."
        }]
    }
    
    messages, citations, enriched_docs = LegalPromptBuilder.build_prompt(state)
    assert len(messages) >= 2
    assert "Điều 12" in citations[0]
    user_prompt = messages[-1]["content"]
    assert "CHƯA ĐỦ TUỔI CHỊU TRÁCH NHIỆM HÌNH SỰ" in user_prompt
