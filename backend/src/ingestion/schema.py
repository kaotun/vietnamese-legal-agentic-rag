"""Định nghĩa schema chuẩn cho tài liệu pháp lý trong pipeline Ingestion (Phase 0)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, List, Optional
from pydantic import BaseModel, Field, ValidationError

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


class ArticleItem(BaseModel):
    """Mô hình đại diện cho một Điều luật."""
    article_no: int = Field(..., description="Số thứ tự Điều (ví dụ: 1, 2, 3)")
    article_name: str = Field(..., description="Tên Điều (ví dụ: 'Điều 1. Phạm vi điều chỉnh')")
    content: str = Field(..., description="Toàn văn nội dung Điều luật")
    clauses: List[str] = Field(default_factory=list, description="Danh sách các Khoản/Điểm nếu bóc tách được")


class LegalDocument(BaseModel):
    """Mô hình tài liệu pháp lý chuẩn cho clean_documents.jsonl."""
    doc_id: str = Field(..., description="Mã định danh văn bản duy nhất (vd: luat-lao-dong-45-2019-qh14)")
    law_number: Optional[str] = Field(None, description="Số hiệu văn bản (vd: 45/2019/QH14)")
    title: str = Field(..., description="Tên đầy đủ của văn bản")
    doc_type: str = Field(..., description="Loại văn bản: Luật, Bộ luật, Nghị định, Thông tư...")
    issuing_authority: Optional[str] = Field(None, description="Cơ quan ban hành (vd: Quốc hội, Chính phủ)")
    issued_date: Optional[str] = Field(None, description="Ngày ban hành (YYYY-MM-DD)")
    effective_date: Optional[str] = Field(None, description="Ngày có hiệu lực (YYYY-MM-DD)")
    status: str = Field(default="con_hieu_luc", description="Tình trạng: con_hieu_luc, het_hieu_luc, chua_xac_dinh")
    is_effective: bool = Field(default=True, description="Văn bản có đang còn hiệu lực hay không")
    valid_for_index: bool = Field(default=True, description="Có dùng để nạp vào Retrieval / Vector search hay không")
    markdown: str = Field(..., description="Toàn văn nội dung dạng Markdown sạch")
    articles: List[ArticleItem] = Field(default_factory=list, description="Danh sách các Điều đã bóc tách")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Metadata bổ sung")


def verify_documents_file(path: Path) -> tuple[int, int, list[str]]:
    """Kiểm tra tính hợp lệ của tệp clean_documents.jsonl.
    
    Returns:
        tuple[valid_count, error_count, error_samples]
    """
    if not path.exists():
        raise FileNotFoundError(f"Không tìm thấy file: {path}")

    valid_count = 0
    error_count = 0
    errors: list[str] = []

    seen_ids = set()

    with open(path, "r", encoding="utf-8") as f:
        for idx, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                doc = LegalDocument.model_validate(data)
                if doc.doc_id in seen_ids:
                    raise ValueError(f"doc_id bị trùng lặp: '{doc.doc_id}'")
                seen_ids.add(doc.doc_id)
                valid_count += 1
            except (json.JSONDecodeError, ValidationError, ValueError) as err:
                error_count += 1
                if len(errors) < 5:
                    errors.append(f"Dòng {idx}: {err}")

    return valid_count, error_count, errors


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Xác thực schema file clean_documents.jsonl")
    parser.add_argument("--verify-file", type=Path, required=True, help="Đường dẫn tới file JSONL cần kiểm tra")
    args = parser.parse_args()

    v_count, e_count, err_samples = verify_documents_file(args.verify_file)
    print(f"--- Kết quả kiểm tra file: {args.verify_file} ---")
    print(f"Hợp lệ: {v_count} văn bản")
    print(f"Lỗi:    {e_count} văn bản")
    if err_samples:
        print("Chi tiết lỗi mẫu:")
        for e in err_samples:
            print(f"  - {e}")
