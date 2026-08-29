"""
chunker.py — Article-Boundary Semantic Chunker

Nhiệm vụ: Nhận List[LegalDocument] → trả về List[LegalChunk].

Chiến lược chính: Article-boundary chunking
- Cắt tại ranh giới "Điều X" bằng Regex
- Mỗi chunk = 1 Điều (bao gồm toàn bộ Khoản bên trong)
- Chunk quá ngắn (< MIN_CHUNK_LEN) → gộp với chunk liền kề
- Chunk quá dài (> MAX_CHUNK_LEN) → cắt tại ranh giới câu
- Fallback: tài liệu không có "Điều" → giữ nguyên làm 1 chunk

Cấu trúc điều khoản trong văn bản pháp luật VN:
    Chương I – TIÊU ĐỀ CHƯƠNG
    Điều 1. Tiêu đề điều
      Khoản 1. Nội dung...
      Khoản 2. Nội dung...
        Điểm a) Chi tiết...
    Điều 2. Tiêu đề điều
      ...
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import List, Optional, Tuple

from src.common.schemas import LegalChunk, LegalDocument

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Hằng số & Regex patterns
# ---------------------------------------------------------------------------

# Giới hạn độ dài chunk (ký tự)
MIN_CHUNK_LEN = 100   # Chunk ngắn hơn → gộp với chunk trước
MAX_CHUNK_LEN = 2000  # Chunk dài hơn → cắt tại ranh giới câu

# Pattern nhận diện ranh giới "Điều X"
# Ví dụ khớp: "Điều 1.", "Điều 12:", "Điều 1a.", "ĐIỀU 5."
# Lưu ý: KHÔNG yêu cầu newline trước "Điều" vì nhiều văn bản là 1 dòng dài
ARTICLE_PATTERN = re.compile(
    r"((?:Điều|ĐIỀU)\s+"    # từ khóa "Điều"
    r"\d+[a-z]?"            # số điều, tùy chọn chữ cái (vd: Điều 12a)
    r"\s*[\.:])",            # dấu phân cách sau số (có thể có space trước)
    re.MULTILINE,
)

# Pattern nhận diện "Chương X" để lấy metadata nhóm (không cắt chunk)
CHAPTER_PATTERN = re.compile(
    r"((?:Chương|CHƯƠNG)\s+(?:[IVXLCDM]+|\d+)[\.:\s])",
    re.MULTILINE,
)

# Pattern nhận diện ranh giới câu để cắt chunk dài
SENTENCE_END_PATTERN = re.compile(r"[.!?]\s+")


# ---------------------------------------------------------------------------
# Chunker class
# ---------------------------------------------------------------------------


class ArticleBoundaryChunker:
    """
    Chunker theo ranh giới Điều khoản trong văn bản pháp luật Việt Nam.

    Ví dụ sử dụng:
        chunker = ArticleBoundaryChunker()
        chunks = chunker.chunk_documents(documents)
        print(f"Tạo được {len(chunks)} chunks từ {len(documents)} văn bản")
    """

    def __init__(
        self,
        min_chunk_len: int = MIN_CHUNK_LEN,
        max_chunk_len: int = MAX_CHUNK_LEN,
    ):
        self.min_chunk_len = min_chunk_len
        self.max_chunk_len = max_chunk_len

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def chunk_documents(self, documents: List[LegalDocument]) -> List[LegalChunk]:
        """
        Chunk toàn bộ danh sách văn bản.

        Args:
            documents: List[LegalDocument] từ Extractor

        Returns:
            List[LegalChunk] — tất cả chunks từ tất cả văn bản
        """
        all_chunks: List[LegalChunk] = []
        for doc in documents:
            doc_chunks = self.chunk_document(doc)
            all_chunks.extend(doc_chunks)

        logger.info(
            "Chunker: %d văn bản → %d chunks (avg %.1f chunks/doc)",
            len(documents),
            len(all_chunks),
            len(all_chunks) / len(documents) if documents else 0,
        )
        return all_chunks

    def chunk_document(self, doc: LegalDocument) -> List[LegalChunk]:
        """
        Chunk một văn bản thành danh sách LegalChunk.

        Luồng xử lý:
        1. Tách text tại ranh giới "Điều X"
        2. Lấy article_ref cho mỗi đoạn
        3. Gộp chunk quá ngắn, cắt chunk quá dài
        4. Tạo LegalChunk với metadata đầy đủ
        """
        text = doc.text
        raw_segments = self._split_by_article(text)

        # Nếu không tìm thấy "Điều" nào → giữ nguyên toàn bộ làm 1 chunk
        if len(raw_segments) == 0:
            return self._make_single_chunk(doc)

        # Gộp chunk ngắn, cắt chunk dài
        cleaned_segments = self._normalize_segments(raw_segments)

        # Tạo LegalChunk objects
        chunks: List[LegalChunk] = []
        for idx, (article_ref, segment_text) in enumerate(cleaned_segments):
            chunk_id = f"{doc.doc_id}_chunk_{idx:04d}"
            chunk = LegalChunk(
                chunk_id=chunk_id,
                doc_id=doc.doc_id,
                text=segment_text.strip(),
                article_ref=article_ref,
                chunk_index=idx,
                metadata={
                    "title": doc.title,
                    "doc_type": doc.doc_type,
                    "legal_type": doc.legal_type,
                    "legal_area": doc.legal_area,
                    "source_url": doc.source_url,
                    "issue_date": doc.issue_date,
                    "issuing_authority": doc.issuing_authority,
                },
            )
            chunks.append(chunk)

        logger.debug("Doc '%s': %d chunks", doc.doc_id, len(chunks))
        return chunks

    # ------------------------------------------------------------------
    # Private: splitting logic
    # ------------------------------------------------------------------

    def _split_by_article(self, text: str) -> List[Tuple[str, str]]:
        """
        Tách text tại ranh giới "Điều X".

        Returns:
            List of (article_ref, text_segment)
            - article_ref: "Điều 1", "Điều 2", v.v.
            - text_segment: nội dung của điều đó (bao gồm tên điều)
        """
        matches = list(ARTICLE_PATTERN.finditer(text))
        if not matches:
            return []

        segments: List[Tuple[str, str]] = []

        # Phần text trước Điều đầu tiên (header của văn bản)
        header_text = text[: matches[0].start()].strip()
        if header_text and len(header_text) >= self.min_chunk_len:
            segments.append(("Header", header_text))

        # Xử lý từng Điều
        for i, match in enumerate(matches):
            # Lấy article_ref từ group capture
            article_ref = match.group(1).strip().rstrip(".:")
            # Nội dung từ vị trí match đến đầu match tiếp theo (hoặc cuối văn bản)
            start = match.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            segment_text = text[start:end].strip()
            segments.append((article_ref, segment_text))

        return segments

    def _normalize_segments(
        self, segments: List[Tuple[str, str]]
    ) -> List[Tuple[str, str]]:
        """
        Chuẩn hóa danh sách segment:
        1. Gộp segment quá ngắn vào segment trước
        2. Cắt segment quá dài tại ranh giới câu
        """
        # Bước 1: Gộp chunk quá ngắn
        merged: List[Tuple[str, str]] = []
        for article_ref, text in segments:
            if len(text) < self.min_chunk_len and merged:
                # Gộp vào chunk trước
                prev_ref, prev_text = merged[-1]
                merged[-1] = (prev_ref, prev_text + "\n" + text)
            else:
                merged.append((article_ref, text))

        # Bước 2: Cắt chunk quá dài
        result: List[Tuple[str, str]] = []
        for article_ref, text in merged:
            if len(text) <= self.max_chunk_len:
                result.append((article_ref, text))
            else:
                sub_chunks = self._split_long_chunk(article_ref, text)
                result.extend(sub_chunks)

        return result

    def _split_long_chunk(
        self, article_ref: str, text: str
    ) -> List[Tuple[str, str]]:
        """
        Cắt một chunk quá dài thành nhiều phần tại ranh giới câu.
        Mỗi phần giữ lại article_ref của Điều gốc kèm index phụ.
        """
        sub_chunks: List[Tuple[str, str]] = []
        current_start = 0

        while current_start < len(text):
            # Lấy window max_chunk_len ký tự
            end = min(current_start + self.max_chunk_len, len(text))

            if end < len(text):
                # Tìm điểm cắt hợp lý: dấu kết thúc câu gần nhất (từ cuối về)
                segment = text[current_start:end]
                last_sentence_end = None
                for m in SENTENCE_END_PATTERN.finditer(segment):
                    last_sentence_end = m.end()

                if last_sentence_end is not None:
                    end = current_start + last_sentence_end

            sub_text = text[current_start:end].strip()
            if sub_text:
                sub_ref = (
                    f"{article_ref} (phần {len(sub_chunks) + 1})"
                    if len(sub_chunks) > 0
                    else article_ref
                )
                sub_chunks.append((sub_ref, sub_text))

            current_start = end

        return sub_chunks

    def _make_single_chunk(self, doc: LegalDocument) -> List[LegalChunk]:
        """
        Fallback: tài liệu không có cấu trúc Điều → giữ nguyên làm 1 chunk.
        Áp dụng cho văn bản ngắn, header, thông báo, v.v.
        """
        text = doc.text.strip()
        if not text:
            return []

        # Nếu text dài hơn MAX_CHUNK_LEN, cắt tại ranh giới câu
        segments = self._split_long_chunk("", text)
        chunks = []
        for idx, (_, seg_text) in enumerate(segments):
            chunks.append(
                LegalChunk(
                    chunk_id=f"{doc.doc_id}_chunk_{idx:04d}",
                    doc_id=doc.doc_id,
                    text=seg_text,
                    article_ref="",
                    chunk_index=idx,
                    metadata={
                        "title": doc.title,
                        "doc_type": doc.doc_type,
                        "legal_type": doc.legal_type,
                        "legal_area": doc.legal_area,
                        "source_url": doc.source_url,
                        "issue_date": doc.issue_date,
                        "issuing_authority": doc.issuing_authority,
                    },
                )
            )
        return chunks


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------


def chunk_documents(
    documents: List[LegalDocument],
    min_chunk_len: int = MIN_CHUNK_LEN,
    max_chunk_len: int = MAX_CHUNK_LEN,
) -> List[LegalChunk]:
    """
    Shortcut để chunk nhanh mà không cần khởi tạo class.

    Ví dụ:
        chunks = chunk_documents(documents)
    """
    return ArticleBoundaryChunker(
        min_chunk_len=min_chunk_len,
        max_chunk_len=max_chunk_len,
    ).chunk_documents(documents)
