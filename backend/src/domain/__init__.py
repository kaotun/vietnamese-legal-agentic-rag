"""Legal Domain Package (Rules, Hierarchy, Registry, Applicability & Fact Extraction)."""
from src.domain.legal_registry import LegalRegistryService, get_legal_registry, LawDocument, DomainTaxonomy
from src.domain.fact_extractor import LegalFactExtractor, LegalFacts, SubjectInfo, get_fact_extractor
from src.domain.rule_engine import LegalRuleEngine, RuleEvaluationResult, get_rule_engine
from src.domain.premise_checker import check_query_premise

__all__ = [
    "LegalRegistryService",
    "get_legal_registry",
    "LawDocument",
    "DomainTaxonomy",
    "LegalFactExtractor",
    "LegalFacts",
    "SubjectInfo",
    "get_fact_extractor",
    "LegalRuleEngine",
    "RuleEvaluationResult",
    "get_rule_engine",
    "check_query_premise",
]
