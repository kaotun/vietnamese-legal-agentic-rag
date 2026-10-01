"""Script tự động khởi tạo và đồng bộ Structured Legal Knowledge Base (LKB) trong PostgreSQL.

Bao gồm:
1. Đăng ký toàn bộ danh mục văn bản luật chuẩn (legal_documents_registry) từ 13.744 điều luật thực tế.
2. Thiết lập bảng phân loại ngành luật & phát hiện ngộ nhận / luật giả định (legal_domain_taxonomy).
"""
from __future__ import annotations

import json
import logging
import re
import sys
from typing import Any, Dict, List, Set

import psycopg2
from psycopg2.extras import execute_batch

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("populate_legal_registry")

# SQL DDL
CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS legal_documents_registry (
    law_id TEXT PRIMARY KEY,
    official_title TEXT NOT NULL,
    short_title TEXT NOT NULL,
    doc_type TEXT NOT NULL,
    total_articles INTEGER NOT NULL DEFAULT 0,
    max_article_num INTEGER NOT NULL DEFAULT 0,
    article_list JSONB NOT NULL DEFAULT '[]'::jsonb,
    aliases TEXT[] NOT NULL DEFAULT '{}',
    validity_status TEXT DEFAULT 'active',
    issue_year INTEGER,
    description TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_legal_registry_short_title ON legal_documents_registry(short_title);
CREATE INDEX IF NOT EXISTS idx_legal_registry_aliases ON legal_documents_registry USING gin(aliases);
CREATE INDEX IF NOT EXISTS idx_legal_registry_doc_type ON legal_documents_registry(doc_type);

CREATE TABLE IF NOT EXISTS legal_domain_taxonomy (
    id SERIAL PRIMARY KEY,
    domain_code TEXT NOT NULL UNIQUE,
    domain_name TEXT NOT NULL,
    governing_law_id TEXT,
    governing_law_title TEXT NOT NULL,
    keywords TEXT[] NOT NULL DEFAULT '{}',
    common_fake_names TEXT[] NOT NULL DEFAULT '{}',
    explanation_template TEXT NOT NULL,
    default_redirect_query TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_taxonomy_keywords ON legal_domain_taxonomy USING gin(keywords);
CREATE INDEX IF NOT EXISTS idx_taxonomy_fake_names ON legal_domain_taxonomy USING gin(common_fake_names);
"""

# Taxonomy định nghĩa các lĩnh vực pháp lý trọng yếu & các luật bịa đặt/nhầm lẫn thông dụng
TAXONOMY_SEEDS = [
    {
        "domain_code": "labor_employment",
        "domain_name": "Lao động & Quan hệ việc làm",
        "governing_law_id": "45/2019/QH14",
        "governing_law_title": "Bộ luật Lao động 2019",
        "keywords": [
            "lao động", "việc làm", "người lao động", "làm thêm giờ", "tăng ca",
            "thử việc", "hợp đồng lao động", "sa thải", "nghỉ phép", "tiền lương"
        ],
        "common_fake_names": [
            "luật bảo vệ người lao động",
            "luật bảo vệ người lao động 2023",
            "luật người lao động",
            "luật quyền người lao động",
            "luật tăng ca",
            "luật làm thêm giờ",
            "luật làm thêm giờ 2023"
        ],
        "explanation_template": "Trong hệ thống pháp luật Việt Nam hoàn toàn KHÔNG CÓ 'Luật Bảo vệ người lao động' hay 'Luật Bảo vệ người lao động 2023'. Các quan hệ lao động, chế độ làm thêm giờ và quyền lợi của người lao động hiện nay được điều chỉnh thống nhất bởi Bộ luật Lao động 2019 (có hiệu lực từ 01/01/2021).",
        "default_redirect_query": "Bộ luật Lao động 2019"
    },
    {
        "domain_code": "maternity_leave",
        "domain_name": "Chế độ nghỉ thai sản của người lao động",
        "governing_law_id": "45/2019/QH14",
        "governing_law_title": "Bộ luật Lao động 2019 và Luật Bảo hiểm xã hội",
        "keywords": [
            "thai sản", "nghỉ thai sản", "sinh con", "thời gian thai sản", "chế độ thai sản"
        ],
        "common_fake_names": [
            "nghỉ thai sản 12 tháng",
            "nghỉ thai sản 1 năm",
            "thai sản 12 tháng",
            "luật thai sản 12 tháng",
            "nghỉ thai sản 9 tháng"
        ],
        "explanation_template": "Theo quy định tại Khoản 1 Điều 139 Bộ luật Lao động 2019 và Điều 34 Luật Bảo hiểm xã hội, thời gian lao động nữ được nghỉ thai sản trước và sau khi sinh con là 06 tháng (chứ KHÔNG PHẢI 12 tháng như câu hỏi nêu). Do đó, việc công ty cho người lao động nghỉ thai sản 06 tháng là HOÀN TOÀN ĐÚNG QUY ĐỊNH PHÁP LUẬT và KHÔNG VI PHẠM.",
        "default_redirect_query": "Điều 139 Bộ luật Lao động thời gian nghỉ thai sản"
    },
    {
        "domain_code": "traffic_safety",
        "domain_name": "Trật tự, An toàn giao thông đường bộ & Xử phạt",
        "governing_law_id": "100/2019/NĐ-CP",
        "governing_law_title": "Nghị định 100/2019/NĐ-CP (sửa đổi, bổ sung bởi Nghị định 123/2021/NĐ-CP) và Luật Giao thông đường bộ",
        "keywords": [
            "giao thông", "xử phạt giao thông", "vi phạm giao thông", "nồng độ cồn",
            "bằng lái xe", "vượt đèn đỏ", "chạy quá tốc độ", "mũ bảo hiểm"
        ],
        "common_fake_names": [
            "luật xử phạt giao thông",
            "luật phạt giao thông",
            "luật nồng độ cồn",
            "luật giao thông 2024",
            "luật xử phạt vi phạm giao thông"
        ],
        "explanation_template": "Trong hệ thống pháp luật Việt Nam không có 'Luật Xử phạt giao thông' hay 'Luật Nồng độ cồn'. Quy định xử phạt vi phạm hành chính lĩnh vực giao thông đường bộ được quy định tại Nghị định 100/2019/NĐ-CP (sửa đổi bởi Nghị định 123/2021/NĐ-CP) cùng Luật Giao thông đường bộ và Luật Phòng, chống tác hại của rượu, bia.",
        "default_redirect_query": "Nghị định 100/2019/NĐ-CP giao thông đường bộ"
    },
    {
        "domain_code": "unemployment_insurance",
        "domain_name": "Bảo hiểm thất nghiệp",
        "governing_law_id": "38/2013/QH13",
        "governing_law_title": "Luật Việc làm 2013",
        "keywords": [
            "thất nghiệp", "trợ cấp thất nghiệp", "bảo hiểm thất nghiệp", "chính sách việc làm"
        ],
        "common_fake_names": [
            "luật bảo hiểm thất nghiệp",
            "luật trợ cấp thất nghiệp"
        ],
        "explanation_template": "Trong hệ thống pháp luật Việt Nam không có văn bản độc lập tên là 'Luật Bảo hiểm thất nghiệp'. Chế độ và điều kiện hưởng bảo hiểm thất nghiệp được quy định tại Luật Việc làm 2013 và các văn bản hướng dẫn thi hành.",
        "default_redirect_query": "Luật Việc làm 2013 bảo hiểm thất nghiệp"
    },
    {
        "domain_code": "criminal_justice",
        "domain_name": "Hình sự & Trách nhiệm hình sự",
        "governing_law_id": "100/2015/QH13",
        "governing_law_title": "Bộ luật Hình sự 2015 (sửa đổi, bổ sung 2017)",
        "keywords": [
            "hình sự", "tội phạm", "án phạt", "phạt tù", "trộm cắp", "lừa đảo",
            "tham nhũng", "giết người", "tội danh", "khởi tố"
        ],
        "common_fake_names": [
            "luật trộm cắp",
            "luật xử tội phạm",
            "luật án phạt"
        ],
        "explanation_template": "Tội phạm và hình phạt được quy định duy nhất và thống nhất trong Bộ luật Hình sự 2015 (sửa đổi, bổ sung 2017).",
        "default_redirect_query": "Bộ luật Hình sự 2015"
    },
    {
        "domain_code": "civil_relations",
        "domain_name": "Dân sự & Nghĩa vụ hợp đồng",
        "governing_law_id": "91/2015/QH13",
        "governing_law_title": "Bộ luật Dân sự 2015",
        "keywords": [
            "dân sự", "hợp đồng dân sự", "bồi thường thiệt hại", "thừa kế", "di chúc",
            "quyền tài sản", "ủy quyền", "vay mượn tiền"
        ],
        "common_fake_names": [
            "luật thừa kế",
            "luật cho vay tiền",
            "luật bồi thường dân sự"
        ],
        "explanation_template": "Các quan hệ tài sản, thừa kế, hợp đồng và bồi thường thiệt hại ngoài hợp đồng được điều chỉnh bởi Bộ luật Dân sự 2015.",
        "default_redirect_query": "Bộ luật Dân sự 2015"
    },
    {
        "domain_code": "land_property",
        "domain_name": "Đất đai & Bất động sản",
        "governing_law_id": "31/2024/QH15",
        "governing_law_title": "Luật Đất đai 2024",
        "keywords": [
            "đất đai", "sổ đỏ", "sổ hồng", "chuyển nhượng đất", "thu hồi đất",
            "bồi thường giải tỏa", "quy hoạch đất", "tranh chấp đất đai"
        ],
        "common_fake_names": [
            "luật sổ đỏ",
            "luật sổ hồng",
            "luật bồi thường đất đai",
            "luật giải tỏa đất"
        ],
        "explanation_template": "Chế độ sở hữu, quản lý và sử dụng đất đai được quy định thống nhất tại Luật Đất đai (Luật Đất đai 2024).",
        "default_redirect_query": "Luật Đất đai 2024"
    },
    {
        "domain_code": "marriage_family",
        "domain_name": "Hôn nhân và Gia đình",
        "governing_law_id": "52/2014/QH13",
        "governing_law_title": "Luật Hôn nhân và Gia đình 2014",
        "keywords": [
            "hôn nhân", "gia đình", "ly hôn", "kết hôn", "chia tài sản ly hôn",
            "nuôi con", "cấp dưỡng", "bạo lực gia đình"
        ],
        "common_fake_names": [
            "luật ly hôn",
            "luật chia tài sản vợ chồng",
            "luật quyền nuôi con"
        ],
        "explanation_template": "Quan hệ hôn nhân, quyền và nghĩa vụ vợ chồng, cha mẹ và con, thủ tục ly hôn được điều chỉnh bởi Luật Hôn nhân và Gia đình 2014.",
        "default_redirect_query": "Luật Hôn nhân và Gia đình 2014"
    },
    {
        "domain_code": "administrative_violations",
        "domain_name": "Xử lý vi phạm hành chính",
        "governing_law_id": "15/2012/QH13",
        "governing_law_title": "Luật Xử lý vi phạm hành chính 2012 (sửa đổi, bổ sung 2020)",
        "keywords": [
            "xử phạt hành chính", "vi phạm hành chính", "biên bản xử phạt", "thẩm quyền xử phạt",
            "tịch thu tang vật", "tước quyền sử dụng giấy phép"
        ],
        "common_fake_names": [
            "luật xử phạt hành chính",
            "luật tiền phạt"
        ],
        "explanation_template": "Nguyên tắc, thẩm quyền và hình thức xử phạt vi phạm hành chính được quy định tại Luật Xử lý vi phạm hành chính 2012 (sửa đổi 2020).",
        "default_redirect_query": "Luật Xử lý vi phạm hành chính"
    },
]


def clean_law_title(title: str) -> str:
    """Loại bỏ các tiền tố trùng lặp do OCR / crawler gộp."""
    cleaned = title.strip()
    # "Bộ luật Luật Thương mại" -> "Luật Thương mại"
    cleaned = re.sub(r"^Bộ\s+luật\s+Luật\s+", "Luật ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^Bộ\s+luật\s+Bộ\s+luật\s+", "Bộ luật ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    # Chữ hoa đầu dòng
    if cleaned:
        cleaned = cleaned[0].upper() + cleaned[1:]
    return cleaned


def generate_aliases(law_id: str, title: str, doc_type: str, issue_year: int | None) -> List[str]:
    """Sinh danh sách alias phong phú để tra cứu siêu tốc."""
    aliases: Set[str] = set()
    title_lower = title.lower()
    clean_t = clean_law_title(title).lower()

    aliases.add(clean_t)
    aliases.add(title_lower)
    if law_id:
        aliases.add(law_id.lower())

    # Trích xuất tên ngắn gọn (bỏ số hiệu năm nếu có)
    # Ví dụ: "Bộ luật hình sự 2015" -> "bộ luật hình sự", "blhs"
    short = re.sub(r"\s+\d{4}(?:/qh\d+)?.*$", "", clean_t).strip()
    if short:
        aliases.add(short)

    if issue_year and short:
        aliases.add(f"{short} {issue_year}")

    # Alias viết tắt thông dụng
    known_acronyms = {
        "bộ luật hình sự": ["blhs", "hình sự", "luật hình sự"],
        "bộ luật dân sự": ["blds", "dân sự", "luật dân sự"],
        "bộ luật lao động": ["bllđ", "lao động", "luật lao động"],
        "bộ luật tố tụng hình sự": ["bltths", "tố tụng hình sự"],
        "bộ luật tố tụng dân sự": ["blttds", "tố tụng dân sự"],
        "luật đất đai": ["lđđ", "đất đai"],
        "luật doanh nghiệp": ["ldn", "doanh nghiệp"],
        "luật hôn nhân và gia đình": ["hôn nhân gia đình", "hôn nhân và gia đình", "hn&gđ"],
        "luật xử lý vi phạm hành chính": ["xlvphc", "xử lý vi phạm hành chính"],
        "luật thương mại": ["thương mại"],
        "luật bảo hiểm xã hội": ["bhxh", "bảo hiểm xã hội"],
        "luật bảo hiểm y tế": ["bhyt", "bảo hiểm y tế"],
        "luật an toàn, vệ sinh lao động": ["atvslđ", "an toàn vệ sinh lao động"],
        "luật việc làm": ["việc làm"],
        "luật giao thông đường bộ": ["gtđb", "giao thông đường bộ"],
        "nghị định 100/2019/nđ-cp": ["nghị định 100", "nđ 100", "nghị định 100/2019", "nd 100"],
    }

    for base_name, acrs in known_acronyms.items():
        if base_name in clean_t:
            for acr in acrs:
                aliases.add(acr)
                if issue_year:
                    aliases.add(f"{acr} {issue_year}")

    return sorted(list(aliases))


def populate_registry(db_url: str):
    """Quét dữ liệu thực tế và lưu vào registry."""
    conn = psycopg2.connect(db_url)
    cur = conn.cursor()

    logger.info("1. Tạo các bảng nếu chưa có...")
    cur.execute(CREATE_TABLES_SQL)
    conn.commit()

    logger.info("2. Quét dữ liệu từ legal_knowledge_records...")
    cur.execute("""
        SELECT law_id, law_name, doc_type,
               array_agg(DISTINCT article) as articles
        FROM legal_knowledge_records
        GROUP BY law_id, law_name, doc_type
        ORDER BY count(*) DESC;
    """)
    rows = cur.fetchall()
    logger.info(f"-> Tìm thấy {len(rows)} văn bản quy phạm pháp luật trong kho tri thức.")

    # Phát hiện các law_id bị trùng lặp nhiều tên
    law_id_counts: Dict[str, int] = {}
    for r in rows:
        lid = r[0]
        law_id_counts[lid] = law_id_counts.get(lid, 0) + 1

    registry_records = []
    for law_id, raw_law_name, doc_type, articles in rows:
        clean_name = clean_law_title(raw_law_name)
        is_amending = bool(re.search(r"sửa\s+đổi,\s+bổ\s+sung", clean_name, re.IGNORECASE))

        actual_law_id = law_id
        # Nếu trùng law_id nhưng tên là luật sửa đổi bổ sung, tạo ID riêng để không ghi đè luật chính
        if law_id_counts.get(law_id, 0) > 1 and is_amending:
            actual_law_id = f"{law_id}_SD"

        # Trích xuất danh sách số điều và max article number
        art_set = set(articles or [])
        num_list = []
        for art in art_set:
            m = re.search(r"Điều\s+(\d+)", art, re.IGNORECASE)
            if m:
                num_list.append(int(m.group(1)))

        max_art = max(num_list) if num_list else len(art_set)
        total_art = len(art_set)

        # Trích xuất năm ban hành
        m_year = re.search(r"\b(19\d{2}|20\d{2})\b", law_id) or re.search(r"\b(19\d{2}|20\d{2})\b", raw_law_name)
        issue_year = int(m_year.group(1)) if m_year else None

        short_title = re.sub(r"\s+\d{4}.*$", "", clean_name).strip()

        # Không gán alias viết tắt của văn bản chính (BLHS, BLDS, LĐĐ...) cho luật sửa đổi bổ sung
        if is_amending:
            aliases = [clean_name.lower(), raw_law_name.lower(), actual_law_id.lower()]
        else:
            aliases = generate_aliases(actual_law_id, clean_name, doc_type, issue_year)

        registry_records.append((
            actual_law_id,
            clean_name,
            short_title,
            doc_type or "luat",
            total_art,
            max_art,
            json.dumps(sorted(list(art_set)), ensure_ascii=False),
            aliases,
            "active",
            issue_year,
            f"Văn bản quy phạm pháp luật gồm {total_art} điều (Điều lớn nhất: Điều {max_art})."
        ))

    logger.info(f"3. Nạp {len(registry_records)} bản ghi vào legal_documents_registry...")
    upsert_sql = """
    INSERT INTO legal_documents_registry (
        law_id, official_title, short_title, doc_type,
        total_articles, max_article_num, article_list,
        aliases, validity_status, issue_year, description, updated_at
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
    ON CONFLICT (law_id) DO UPDATE SET
        official_title = EXCLUDED.official_title,
        short_title = EXCLUDED.short_title,
        total_articles = EXCLUDED.total_articles,
        max_article_num = EXCLUDED.max_article_num,
        article_list = EXCLUDED.article_list,
        aliases = EXCLUDED.aliases,
        updated_at = CURRENT_TIMESTAMP;
    """
    execute_batch(cur, upsert_sql, registry_records, page_size=100)
    conn.commit()
    logger.info("-> Đã nạp thành công legal_documents_registry.")

    logger.info("4. Nạp dữ liệu vào legal_domain_taxonomy...")
    taxonomy_records = []
    for item in TAXONOMY_SEEDS:
        taxonomy_records.append((
            item["domain_code"],
            item["domain_name"],
            item.get("governing_law_id"),
            item["governing_law_title"],
            item["keywords"],
            item["common_fake_names"],
            item["explanation_template"],
            item["default_redirect_query"],
        ))

    upsert_taxonomy_sql = """
    INSERT INTO legal_domain_taxonomy (
        domain_code, domain_name, governing_law_id, governing_law_title,
        keywords, common_fake_names, explanation_template, default_redirect_query
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (domain_code) DO UPDATE SET
        domain_name = EXCLUDED.domain_name,
        governing_law_id = EXCLUDED.governing_law_id,
        governing_law_title = EXCLUDED.governing_law_title,
        keywords = EXCLUDED.keywords,
        common_fake_names = EXCLUDED.common_fake_names,
        explanation_template = EXCLUDED.explanation_template,
        default_redirect_query = EXCLUDED.default_redirect_query;
    """
    execute_batch(cur, upsert_taxonomy_sql, taxonomy_records, page_size=50)
    conn.commit()
    logger.info(f"-> Đã nạp thành công {len(taxonomy_records)} danh mục legal_domain_taxonomy.")

    # In kiểm tra
    cur.execute("SELECT count(*) FROM legal_documents_registry;")
    logger.info(f"Tổng số văn bản trong legal_documents_registry: {cur.fetchone()[0]}")
    cur.execute("SELECT count(*) FROM legal_domain_taxonomy;")
    logger.info(f"Tổng số danh mục trong legal_domain_taxonomy: {cur.fetchone()[0]}")

    conn.close()
    logger.info("Hoàn tất thiết lập Structured Legal Knowledge Base!")


if __name__ == "__main__":
    import os
    current_dir = os.path.dirname(os.path.abspath(__file__))
    backend_root = os.path.dirname(current_dir)
    if backend_root not in sys.path:
        sys.path.insert(0, backend_root)

    sys.stdout.reconfigure(encoding="utf-8")
    from src.config import get_settings
    settings = get_settings()
    populate_registry(settings.legal_assistant.postgres.database_url)
