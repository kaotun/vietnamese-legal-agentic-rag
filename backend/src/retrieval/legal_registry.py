"""Backward-compatible shim for src.retrieval.legal_registry.

Module đã được chuyển vào `src.domain.legal_registry`.
"""
from src.domain.legal_registry import *  # noqa: F401, F403
from src.domain.legal_registry import LegalRegistryService, get_legal_registry, LawDocument, DomainTaxonomy  # Explicit exports
