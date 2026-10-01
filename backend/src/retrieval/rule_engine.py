"""Backward-compatible shim for src.retrieval.rule_engine.

Module đã được chuyển vào `src.domain.rule_engine`.
"""
from src.domain.rule_engine import *  # noqa: F401, F403
from src.domain.rule_engine import LegalRuleEngine, RuleEvaluationResult, get_rule_engine  # Explicit exports
