"""
schemas.py — Data models cho toàn bộ pipeline Legal Q&A

Hai model chính:
- LegalDocument: đầu ra của Extractor, đại diện 1 văn bản pháp luật
- LegalChunk:    đầu ra của Chunker, đại diện 1 đoạn văn bản (đơn vị index)
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from pydantic import BaseModel, Field, model_validator


class LegalDocument(BaseModel):
    """
    Đại diện cho một văn bản pháp luật sau khi được extract từ JSONL.
    Đây là đầu vào của Chunker.
    """

    doc_id: str = Field(description="ID duy nhất của văn bản (item_id từ nguồn)")
    title: str = Field(description="Tiêu đề văn bản")
    doc_type: str = Field(
        default="unknown",
        description="Loại văn bản theo mã (vd: nghi_dinh, luat, thong_tu)",
    )
    legal_type: str = Field(
        default="unknown",
        description="Loại văn bản dạng hiển thị (vd: Nghị định, Luật)",
    )
    legal_area: str = Field(
        default="unknown",
        description="Lĩnh vực pháp lý (vd: lao động, doanh nghiệp)",
    )
    text: str = Field(description="Nội dung văn bản dạng markdown")
    source_url: str = Field(default="", description="URL nguồn gốc văn bản")
    char_len: int = Field(default=0, description="Số ký tự của văn bản")
    num_sections: int = Field(default=0, description="Số điều/mục trong văn bản")
    issue_date: str = Field(default="", description="Ngày ban hành")
    issuing_authority: str = Field(default="", description="Cơ quan ban hành")

    @model_validator(mode="after")
    def compute_char_len(self) -> "LegalDocument":
        """Tự tính char_len nếu chưa có."""
        if self.char_len == 0 and self.text:
            self.char_len = len(self.text)
        return self


class LegalChunk(BaseModel):
    """
    Đại diện cho một đoạn văn bản sau khi chunking.
    Đây là đơn vị được index vào FAISS và BM25.
    """

    chunk_id: str = Field(
        description="ID duy nhất của chunk. Format: {doc_id}_chunk_{index}"
    )
    doc_id: str = Field(description="ID văn bản gốc (tham chiếu ngược về LegalDocument)")
    text: str = Field(description="Nội dung đoạn văn bản")
    article_ref: str = Field(
        default="",
        description="Tham chiếu điều khoản gốc (vd: 'Điều 5', 'Chương II')",
    )
    char_len: int = Field(default=0, description="Số ký tự của chunk")
    chunk_index: int = Field(
        default=0, description="Vị trí của chunk trong văn bản gốc (0-indexed)"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Metadata bổ sung từ văn bản gốc: title, doc_type, legal_type, "
            "source_url, issue_date, issuing_authority"
        ),
    )

    @model_validator(mode="after")
    def compute_char_len(self) -> "LegalChunk":
        """Tự tính char_len nếu chưa có."""
        if self.char_len == 0 and self.text:
            self.char_len = len(self.text)
        return self

    def to_index_text(self) -> str:
        """
        Trả về text dùng để embed/index.
        Nối article_ref vào đầu để giúp retrieval theo tên Điều.
        """
        if self.article_ref:
            return f"{self.article_ref}. {self.text}"
        return self.text
