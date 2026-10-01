"""Backward-compatible shim for src.retrieval.ingestion.

Module đã được chuyển vào `src.ingestion.pipeline`.
"""
from src.ingestion.pipeline import *  # noqa: F401, F403
from src.ingestion.pipeline import LegalDocumentIngestionPipeline  # Explicit export
