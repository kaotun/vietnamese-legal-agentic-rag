"""Module chuyển đổi dữ liệu thô sang chuẩn clean_documents.jsonl (Phase 0)."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from src.ingestion.schema import ArticleItem, LegalDocument

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROCESSED_DIR = BACKEND_DIR / "data" / "processed"
PROCESSED_FILE = PROCESSED_DIR / "clean_documents.jsonl"


def extract_articles_from_text(raw_text: str) -> List[ArticleItem]:
    """Tách nội dung văn bản thành các Điều dựa trên quy tắc regex chuẩn."""
    articles: List[ArticleItem] = []
    
    # Regex tìm các tiêu đề Điều: "Điều 1.", "Điều 2 -", "Điều 3:"
    pattern = re.compile(r"(^|\n)(Điều\s+(\d+)[\.:\-\s]+[^\n]+)", re.MULTILINE)
    matches = list(pattern.finditer(raw_text))
    
    if not matches:
        return articles

    for i, match in enumerate(matches):
        full_title = match.group(2).strip()
        art_no = int(match.group(3))
        start_pos = match.end()
        end_pos = matches[i + 1].start() if i + 1 < len(matches) else len(raw_text)
        art_content = raw_text[start_pos:end_pos].strip()

        # Tách các khoản nếu có: "1. ...", "2. ..."
        clause_pattern = re.compile(r"(^|\n)(\d+\.\s+[^\n]+)", re.MULTILINE)
        clauses = [c[1].strip() for c in clause_pattern.findall(art_content)]

        articles.append(
            ArticleItem(
                article_no=art_no,
                article_name=full_title,
                content=art_content,
                clauses=clauses,
            )
        )
    return articles


def convert_raw_records_to_jsonl(
    raw_records: List[Dict[str, Any]], output_path: Path = PROCESSED_FILE
) -> int:
    """Chuyển đổi danh sách record thành clean_documents.jsonl."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    saved_count = 0

    # Nhóm theo luật nếu input là các điều rời rạc (như format base_data.json)
    grouped: Dict[str, Dict[str, Any]] = {}
    for rec in raw_records:
        law_id = str(rec.get("law_id") or rec.get("doc_id") or "doc_default")
        if law_id not in grouped:
            grouped[law_id] = {
                "doc_id": law_id,
                "title": rec.get("law_name") or rec.get("title") or f"Văn bản {law_id}",
                "doc_type": rec.get("doc_type") or "Luật",
                "issuing_authority": rec.get("author") or rec.get("issuing_authority") or "Quốc hội",
                "status": "con_hieu_luc",
                "is_effective": True,
                "valid_for_index": True,
                "articles": [],
                "raw_texts": [],
            }
        
        art_no = rec.get("article")
        if art_no is not None:
            try:
                art_no_int = int(re.search(r"\d+", str(art_no)).group())
            except Exception:
                art_no_int = len(grouped[law_id]["articles"]) + 1

            grouped[law_id]["articles"].append(
                ArticleItem(
                    article_no=art_no_int,
                    article_name=rec.get("article_title") or f"Điều {art_no_int}",
                    content=rec.get("content") or "",
                )
            )
            grouped[law_id]["raw_texts"].append(
                f"### {rec.get('article_title') or f'Điều {art_no_int}'}\n{rec.get('content') or ''}"
            )

    with open(output_path, "w", encoding="utf-8") as out:
        for doc_data in grouped.values():
            full_markdown = f"# {doc_data['title']}\n\n" + "\n\n".join(doc_data["raw_texts"])
            doc = LegalDocument(
                doc_id=doc_data["doc_id"],
                title=doc_data["title"],
                doc_type=doc_data["doc_type"],
                issuing_authority=doc_data["issuing_authority"],
                status=doc_data["status"],
                is_effective=doc_data["is_effective"],
                valid_for_index=doc_data["valid_for_index"],
                markdown=full_markdown,
                articles=doc_data["articles"],
            )
            out.write(doc.model_dump_json() + "\n")
            saved_count += 1

    return saved_count


def generate_seed_legal_corpus(output_path: Path = PROCESSED_FILE) -> int:
    """Tạo bộ văn bản pháp luật mẫu chuẩn chỉ cho đồ án (Luật Doanh nghiệp, Lao động, Đất đai...)."""
    seed_docs = [
        {
            "doc_id": "luat-doanh-nghiep-2020",
            "law_number": "59/2020/QH14",
            "title": "Luật Doanh nghiệp năm 2020",
            "doc_type": "Luật",
            "issuing_authority": "Quốc hội",
            "issued_date": "2020-06-17",
            "effective_date": "2021-01-01",
            "status": "con_hieu_luc",
            "is_effective": True,
            "valid_for_index": True,
            "markdown": """# Luật Doanh nghiệp 2020\n\n## Điều 1. Phạm vi điều chỉnh\nLuật này quy định về việc thành lập, tổ chức quản lý, tổ chức lại, giải thể và hoạt động có liên quan của doanh nghiệp, bao gồm công ty trách nhiệm hữu hạn, công ty cổ phần, công ty hợp danh và doanh nghiệp tư nhân; quy định về nhóm công ty.\n\n## Điều 17. Quyền thành lập, góp vốn, mua cổ phần, mua phần vốn góp và quản lý doanh nghiệp\n1. Tổ chức, cá nhân có quyền thành lập và quản lý doanh nghiệp tại Việt Nam theo quy định của Luật này, trừ trường hợp quy định tại khoản 2 Điều này.\n2. Tổ chức, cá nhân sau đây không có quyền thành lập và quản lý doanh nghiệp tại Việt Nam: Cán bộ, công chức, viên chức theo quy định của Luật Cán bộ, công chức và Luật Viên chức; Sĩ quan, hạ sĩ quan, quân nhân chuyên nghiệp...""",
            "articles": [
                {
                    "article_no": 1,
                    "article_name": "Điều 1. Phạm vi điều chỉnh",
                    "content": "Luật này quy định về việc thành lập, tổ chức quản lý, tổ chức lại, giải thể và hoạt động có liên quan của doanh nghiệp, bao gồm công ty trách nhiệm hữu hạn, công ty cổ phần, công ty hợp danh và doanh nghiệp tư nhân; quy định về nhóm công ty.",
                    "clauses": []
                },
                {
                    "article_no": 17,
                    "article_name": "Điều 17. Quyền thành lập, góp vốn, mua cổ phần, mua phần vốn góp và quản lý doanh nghiệp",
                    "content": "1. Tổ chức, cá nhân có quyền thành lập và quản lý doanh nghiệp tại Việt Nam theo quy định của Luật này, trừ trường hợp quy định tại khoản 2 Điều này.\n2. Tổ chức, cá nhân sau đây không có quyền thành lập và quản lý doanh nghiệp tại Việt Nam: Cán bộ, công chức, viên chức...",
                    "clauses": [
                        "1. Tổ chức, cá nhân có quyền thành lập và quản lý doanh nghiệp...",
                        "2. Tổ chức, cá nhân sau đây không có quyền thành lập và quản lý doanh nghiệp..."
                    ]
                }
            ]
        },
        {
            "doc_id": "bo-luat-lao-dong-2019",
            "law_number": "45/2019/QH14",
            "title": "Bộ luật Lao động năm 2019",
            "doc_type": "Bộ luật",
            "issuing_authority": "Quốc hội",
            "issued_date": "2019-11-20",
            "effective_date": "2021-01-01",
            "status": "con_hieu_luc",
            "is_effective": True,
            "valid_for_index": True,
            "markdown": """# Bộ luật Lao động 2019\n\n## Điều 1. Phạm vi điều chỉnh\nBộ luật Lao động quy định tiêu chuẩn lao động; quyền, nghĩa vụ, trách nhiệm của người lao động, người sử dụng lao động, tổ chức đại diện người lao động tại cơ sở, tổ chức đại diện người sử dụng lao động trong quan hệ lao động và các quan hệ khác liên quan trực tiếp đến quan hệ lao động; quản lý nhà nước về lao động.\n\n## Điều 34. Các trường hợp chấm dứt hợp đồng lao động\n1. Hết hạn hợp đồng lao động, trừ trường hợp quy định tại khoản 4 Điều 137 của Bộ luật này.\n2. Đã hoàn thành công việc theo hợp đồng lao động.\n3. Hai bên thỏa thuận chấm dứt hợp đồng lao động.\n4. Người lao động bị kết án phạt tù nhưng không được hưởng án treo...""",
            "articles": [
                {
                    "article_no": 1,
                    "article_name": "Điều 1. Phạm vi điều chỉnh",
                    "content": "Bộ luật Lao động quy định tiêu chuẩn lao động; quyền, nghĩa vụ, trách nhiệm của người lao động, người sử dụng lao động...",
                    "clauses": []
                },
                {
                    "article_no": 34,
                    "article_name": "Điều 34. Các trường hợp chấm dứt hợp đồng lao động",
                    "content": "1. Hết hạn hợp đồng lao động.\n2. Đã hoàn thành công việc theo hợp đồng lao động.\n3. Hai bên thỏa thuận chấm dứt hợp đồng lao động.",
                    "clauses": [
                        "1. Hết hạn hợp đồng lao động.",
                        "2. Đã hoàn thành công việc theo hợp đồng lao động.",
                        "3. Hai bên thỏa thuận chấm dứt hợp đồng lao động."
                    ]
                }
            ]
        },
        {
            "doc_id": "luat-dat-dai-2024",
            "law_number": "31/2024/QH15",
            "title": "Luật Đất đai năm 2024",
            "doc_type": "Luật",
            "issuing_authority": "Quốc hội",
            "issued_date": "2024-01-18",
            "effective_date": "2024-08-01",
            "status": "con_hieu_luc",
            "is_effective": True,
            "valid_for_index": True,
            "markdown": """# Luật Đất đai 2024\n\n## Điều 1. Phạm vi điều chỉnh\nLuật này quy định về chế độ sở hữu đất đai, quyền hạn và trách nhiệm của Nhà nước đại diện chủ sở hữu toàn dân về đất đai và thống nhất quản lý về đất đai, chế độ quản lý và sử dụng đất đai, quyền và nghĩa vụ của công dân, người sử dụng đất đối với đất đai thuộc lãnh thổ của nước Cộng hòa xã hội chủ nghĩa Việt Nam.\n\n## Điều 4. Người sử dụng đất\nNgười sử dụng đất được Nhà nước giao đất, cho thuê đất, công nhận quyền sử dụng đất; đang sử dụng đất ổn định, đủ điều kiện cấp Giấy chứng nhận quyền sử dụng đất, quyền sở hữu tài sản gắn liền với đất mà chưa được Nhà nước cấp Giấy chứng nhận...""",
            "articles": [
                {
                    "article_no": 1,
                    "article_name": "Điều 1. Phạm vi điều chỉnh",
                    "content": "Luật này quy định về chế độ sở hữu đất đai, quyền hạn và trách nhiệm của Nhà nước đại diện chủ sở hữu toàn dân về đất đai...",
                    "clauses": []
                },
                {
                    "article_no": 4,
                    "article_name": "Điều 4. Người sử dụng đất",
                    "content": "Người sử dụng đất được Nhà nước giao đất, cho thuê đất, công nhận quyền sử dụng đất...",
                    "clauses": []
                }
            ]
        }
    ]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        for doc in seed_docs:
            model = LegalDocument(**doc)
            f.write(model.model_dump_json() + "\n")
    return len(seed_docs)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Chuyển đổi dữ liệu sang clean_documents.jsonl")
    parser.add_argument("--seed", action="store_true", help="Tạo bộ dữ liệu luật mẫu chất lượng cao")
    parser.add_argument("--from-file", type=Path, help="Chuyển đổi từ file JSON thô có sẵn")
    args = parser.parse_args()

    if args.seed:
        count = generate_seed_legal_corpus()
        print(f"Đã tạo thành công {count} văn bản luật chuẩn vào: {PROCESSED_FILE}")
    elif args.from_file:
        data = json.loads(args.from_file.read_text(encoding="utf-8"))
        count = convert_raw_records_to_jsonl(data)
        print(f"Đã chuyển đổi thành công {count} văn bản từ {args.from_file} sang: {PROCESSED_FILE}")
    else:
        print("Vui lòng truyền cờ --seed hoặc --from-file <path>")
