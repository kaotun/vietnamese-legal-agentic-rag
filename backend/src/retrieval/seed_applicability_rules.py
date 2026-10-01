"""Backward-compatible shim for src.retrieval.seed_applicability_rules.

Script đã được chuyển về `db.seeds.seed_applicability_rules`.
"""
from db.seeds.seed_applicability_rules import *  # noqa: F401, F403
from db.seeds.seed_applicability_rules import migrate_and_seed  # Explicit export
