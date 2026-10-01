"""Backward-compatible shim for src.retrieval.populate_legal_registry.

Script đã được chuyển về `db.seeds.populate_legal_registry`.
"""
from db.seeds.populate_legal_registry import *  # noqa: F401, F403
from db.seeds.populate_legal_registry import populate_registry  # Explicit export
