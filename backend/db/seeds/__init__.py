"""Database Seed Scripts Package."""
from db.seeds.populate_legal_registry import populate_registry
from db.seeds.seed_applicability_rules import migrate_and_seed

__all__ = ["populate_registry", "migrate_and_seed"]
