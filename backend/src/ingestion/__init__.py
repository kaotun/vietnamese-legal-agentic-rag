"""Data Ingestion Package (Crawlers, Converters, Schemas, and Pipeline)."""
from src.ingestion.schema import LegalDocument, ArticleItem
from src.ingestion.converter import convert_raw_records_to_jsonl, extract_articles_from_text
from src.ingestion.pipeline import LegalDocumentIngestionPipeline

__all__ = [
    "LegalDocument",
    "ArticleItem",
    "convert_raw_records_to_jsonl",
    "extract_articles_from_text",
    "LegalDocumentIngestionPipeline",
]
