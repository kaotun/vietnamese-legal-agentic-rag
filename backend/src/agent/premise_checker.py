"""Backward-compatible shim for src.agent.premise_checker.

Module đã được chuyển vào `src.domain.premise_checker`.
"""
from src.domain.premise_checker import *  # noqa: F401, F403
from src.domain.premise_checker import check_query_premise  # Explicit export
