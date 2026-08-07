from enum import Enum
from pydantic import BaseModel, Field
from typing import List, Optional

class RiskLevel(str, Enum):
    LOW = "Thấp"
    MEDIUM = "Trung bình"
    HIGH = "Cao"
    CRITICAL = "Nghiêm trọng"

class RiskCategory(str, Enum):
    UNILATERAL_TERMINATION = "Đơn phương chấm dứt hợp đồng"
    UNFAIR_PENALTY = "Phạt vi phạm không cân xứng"
    VAGUE_CONFIDENTIALITY = "Điều khoản bảo mật thiếu rõ ràng"
    UNFAIR_LIABILITY_EXEMPTION = "Miễn trừ trách nhiệm không hợp lý"
    DISPUTE_RESOLUTION_RISK = "Rủi ro giải quyết tranh chấp (Bất lợi về cơ quan tài phán/luật áp dụng)"
    PAYMENT_TERM_RISK = "Rủi ro điều khoản thanh toán (Thời hạn quá dài/Điều kiện mập mờ)"
    OTHER = "Khác"

class RiskItem(BaseModel):
    clause_id: Optional[str] = Field(None, description="Mã hoặc số thứ tự điều khoản chứa rủi ro (vd: Điều 5.1)")
    risk_category: RiskCategory = Field(..., description="Loại rủi ro được phát hiện")
    severity: RiskLevel = Field(..., description="Mức độ nghiêm trọng của rủi ro")
    description: str = Field(..., description="Mô tả ngắn gọn tại sao điều khoản này lại là rủi ro")
    recommendation: str = Field(..., description="Khuyến nghị chỉnh sửa để giảm thiểu rủi ro")
    original_text_snippet: Optional[str] = Field(None, description="Trích đoạn văn bản gốc gây ra rủi ro")

class DocumentRiskReport(BaseModel):
    document_id: str = Field(..., description="ID của tài liệu được quét")
    total_risks_found: int = Field(0, description="Tổng số rủi ro phát hiện được")
    risks: List[RiskItem] = Field(default_factory=list, description="Danh sách chi tiết các rủi ro")

