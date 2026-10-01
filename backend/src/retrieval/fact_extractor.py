"""Backward-compatible shim for src.retrieval.fact_extractor.

Module đã được chuyển vào `src.domain.fact_extractor`.
"""
from src.domain.fact_extractor import *  # noqa: F401, F403
from src.domain.fact_extractor import LegalFactExtractor, LegalFacts, SubjectInfo, get_fact_extractor  # Explicit exports
