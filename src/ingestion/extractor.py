"""
extractor.py — Document Extractor

Nhiệm vụ: Đọc file JSONL chứa văn bản pháp luật → trả về list[LegalDocument].

Luồng:
  vbpl_sample.jsonl
      └─► đọc từng dòng JSON
          └─► validate & map sang LegalDocument
              └─► lọc bỏ document không hợp lệ
                  └─► List[LegalDocument]
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Iterator, List, Optional

from src.common.schemas import LegalDocument

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Hằng số
# ---------------------------------------------------------------------------

# Độ dài tối thiểu để một document được coi là hợp lệ (ký tự)
MIN_TEXT_LENGTH = 50


# ---------------------------------------------------------------------------
# Extractor class
# ---------------------------------------------------------------------------


class DocumentExtractor:
    """
    Đọc văn bản pháp luật từ file JSONL và chuẩn hóa thành LegalDocument.

    Ví dụ sử dụng:
        extractor = DocumentExtractor("data/raw/laws/vbpl_sample.jsonl")
        docs = extractor.load()
        print(f"Đã load {len(docs)} văn bản")
    """

    def __init__(self, jsonl_path: str | Path):
        self.jsonl_path = Path(jsonl_path)
        if not self.jsonl_path.exists():
            raise FileNotFoundError(f"Không tìm thấy file: {self.jsonl_path}")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load(self, limit: Optional[int] = None) -> List[LegalDocument]:
        """
        Đọc toàn bộ file JSONL, trả về list LegalDocument hợp lệ.

        Args:
            limit: Nếu đặt, chỉ đọc tối đa `limit` dòng đầu tiên.
                   Hữu ích khi test nhanh trên tập nhỏ.

        Returns:
            List[LegalDocument] — danh sách văn bản đã được chuẩn hóa
        """
        docs: List[LegalDocument] = []
        total_read = 0
        total_skipped = 0

        for raw in self._iter_jsonl(limit=limit):
            total_read += 1
            doc = self._parse_record(raw)
            if doc is None:
                total_skipped += 1
                continue
            docs.append(doc)

        logger.info(
            "Extractor: đọc %d dòng, load thành công %d văn bản, bỏ qua %d",
            total_read,
            len(docs),
            total_skipped,
        )
        return docs

    def stream(self, limit: Optional[int] = None) -> Iterator[LegalDocument]:
        """
        Generator version của load() — dùng khi corpus quá lớn để load vào RAM.
        Yield từng LegalDocument một.
        """
        for raw in self._iter_jsonl(limit=limit):
            doc = self._parse_record(raw)
            if doc is not None:
                yield doc

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _iter_jsonl(self, limit: Optional[int] = None) -> Iterator[dict]:
        """Đọc file JSONL từng dòng, yield dict thô."""
        with open(self.jsonl_path, encoding="utf-8") as f:
            for i, line in enumerate(f):
                if limit is not None and i >= limit:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as e:
                    logger.warning("Dòng %d không parse được JSON: %s", i + 1, e)

    def _parse_record(self, raw: dict) -> Optional[LegalDocument]:
        """
        Map một dict thô từ JSONL sang LegalDocument.
        Trả về None nếu record không hợp lệ.
        """
        # Lấy nội dung chính — bắt buộc phải có
        raw_md = raw.get("markdown")
        text = (str(raw_md) if isinstance(raw_md, str) else "").strip()
        if len(text) < MIN_TEXT_LENGTH:
            logger.debug(
                "Bỏ qua doc '%s': text quá ngắn (%d ký tự)",
                raw.get("item_id", "?"),
                len(text),
            )
            return None

        # doc_id: ưu tiên item_id, fallback sang doc_name
        doc_id = str(raw.get("item_id") or raw.get("doc_name") or "")
        if not doc_id:
            logger.warning("Bỏ qua 1 record không có item_id và doc_name")
            return None

        try:
            return LegalDocument(
                doc_id=doc_id,
                title=str(raw.get("title", "")).strip() or f"Văn bản {doc_id}",
                doc_type=str(raw.get("doc_type", "unknown")),
                legal_type=str(raw.get("legal_type", "unknown")),
                legal_area=str(raw.get("legal_area", "unknown")),
                text=text,
                source_url=str(raw.get("source_url", "")),
                char_len=int(raw.get("char_len", 0)),
                num_sections=int(raw.get("num_sections", 0)),
                issue_date=str(raw.get("issue_date", "")),
                issuing_authority=str(raw.get("issuing_authority", "")),
            )
        except Exception as e:
            logger.warning("Không tạo được LegalDocument cho doc_id='%s': %s", doc_id, e)
            return None


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------


def load_documents(
    jsonl_path: str | Path,
    limit: Optional[int] = None,
) -> List[LegalDocument]:
    """
    Shortcut để load nhanh không cần khởi tạo class.

    Ví dụ:
        docs = load_documents("data/raw/laws/vbpl_sample.jsonl", limit=100)
    """
    return DocumentExtractor(jsonl_path).load(limit=limit)
