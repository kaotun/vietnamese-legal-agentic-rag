"""Script nạp dữ liệu pháp luật từ base_data.json vào PostgreSQL cho legal-qa-system."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

# Đảm bảo import được src
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import asyncpg
from src.config import get_settings

DEFAULT_DATASET = BACKEND_DIR / "data" / "base_data.json"
REQUIRED_FIELDS = {
    "id",
    "law_id",
    "law_name",
    "doc_type",
    "article",
    "article_title",
    "content",
    "author",
}


async def create_table_if_not_exists(conn: asyncpg.Connection, table_name: str) -> None:
    """Tạo bảng và các chỉ mục cần thiết, bao gồm pgvector và metadata hiệu lực."""
    query = f"""
    CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
    CREATE EXTENSION IF NOT EXISTS "unaccent";
    CREATE EXTENSION IF NOT EXISTS "pg_trgm";
    CREATE EXTENSION IF NOT EXISTS "vector";

    CREATE TABLE IF NOT EXISTS {table_name} (
        id INTEGER PRIMARY KEY,
        law_id TEXT NOT NULL,
        law_name TEXT NOT NULL,
        doc_type TEXT NOT NULL,
        article TEXT NOT NULL,
        article_title TEXT NOT NULL,
        content TEXT NOT NULL,
        author TEXT NOT NULL,
        validity_status TEXT DEFAULT 'active',
        effective_date DATE,
        expiration_date DATE,
        replacement_law_id TEXT,
        embedding vector(768),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    CREATE INDEX IF NOT EXISTS idx_{table_name}_law_id ON {table_name}(law_id);
    CREATE INDEX IF NOT EXISTS idx_{table_name}_article ON {table_name}(article);
    CREATE INDEX IF NOT EXISTS idx_{table_name}_validity ON {table_name}(validity_status);
    """
    await conn.execute(query)

    # Thử tạo HNSW index nếu pgvector đã sẵn sàng
    try:
        await conn.execute(f"""
        CREATE INDEX IF NOT EXISTS idx_{table_name}_embedding_hnsw
        ON {table_name} USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64);
        """)
    except Exception as e:
        print(f"  [Thông báo] Chưa tạo được HNSW index ({e}). Cột embedding vector vẫn hoạt động bình thường.")


async def insert_records(
    conn: asyncpg.Connection, table_name: str, records: list[dict[str, Any]], batch_size: int = 500
) -> int:
    """Nạp danh sách record vào bảng bằng câu lệnh UPSERT theo batch."""
    upsert_sql = f"""
    INSERT INTO {table_name} (
        id, law_id, law_name, doc_type, article, article_title, content, author,
        validity_status, effective_date, expiration_date, replacement_law_id, updated_at
    )
    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, CURRENT_TIMESTAMP)
    ON CONFLICT (id) DO UPDATE SET
        law_id = EXCLUDED.law_id,
        law_name = EXCLUDED.law_name,
        doc_type = EXCLUDED.doc_type,
        article = EXCLUDED.article,
        article_title = EXCLUDED.article_title,
        content = EXCLUDED.content,
        author = EXCLUDED.author,
        validity_status = EXCLUDED.validity_status,
        effective_date = EXCLUDED.effective_date,
        expiration_date = EXCLUDED.expiration_date,
        replacement_law_id = EXCLUDED.replacement_law_id,
        updated_at = CURRENT_TIMESTAMP;
    """

    total = len(records)
    for i in range(0, total, batch_size):
        batch = records[i : i + batch_size]
        values = [
            (
                int(r["id"]),
                str(r["law_id"]),
                str(r["law_name"]),
                str(r["doc_type"]),
                str(r["article"]),
                str(r["article_title"]),
                str(r["content"]),
                str(r["author"]),
                str(r.get("validity_status", "active")),
                r.get("effective_date"),
                r.get("expiration_date"),
                r.get("replacement_law_id"),
            )
            for r in batch
        ]
        await conn.executemany(upsert_sql, values)
        print(f"  -> Đã nạp {min(i + batch_size, total)}/{total} records...")
    return total


async def main() -> None:
    parser = argparse.ArgumentParser(description="Nạp dữ liệu vào PostgreSQL cho legal-qa-system")
    parser.add_argument("--file", type=Path, default=DEFAULT_DATASET, help="Đường dẫn file JSON")
    parser.add_argument("--batch-size", type=int, default=500, help="Số records mỗi batch")
    parser.add_argument("--truncate", action="store_true", help="Xóa sạch bảng cũ trước khi nạp")
    parser.add_argument(
        "--records-only",
        action="store_true",
        help="Chỉ nạp records điều luật, không tự động nạp registry và applicability rules",
    )
    args = parser.parse_args()

    settings = get_settings()
    db_url = settings.legal_assistant.postgres.database_url
    table_name = "legal_knowledge_records"

    print("=" * 60)
    print("BƯỚC 1/3: Nạp Điều luật vào legal_knowledge_records...")
    print("=" * 60)
    print(f"Đọc dữ liệu từ: {args.file}")
    if not args.file.exists():
        print(f"LỖI: Không tìm thấy file {args.file}")
        return

    records = json.loads(args.file.read_text(encoding="utf-8"))
    print(f"Tổng số bản ghi đọc được: {len(records)}")

    print(f"Kết nối tới PostgreSQL: {db_url}")
    conn = await asyncpg.connect(db_url)
    try:
        await create_table_if_not_exists(conn, table_name)
        if args.truncate:
            print(f"Đang truncate bảng {table_name}...")
            await conn.execute(f"TRUNCATE TABLE {table_name};")

        print(f"Bắt đầu nạp {len(records)} bản ghi vào {table_name}...")
        total_loaded = await insert_records(conn, table_name, records, batch_size=args.batch_size)
        print(f"-> Hoàn tất nạp {total_loaded} điều luật vào PostgreSQL!")
    finally:
        await conn.close()

    if not args.records_only:
        print("\n" + "=" * 60)
        print("BƯỚC 2/3: Khởi tạo Legal Documents Registry & Domain Taxonomy...")
        print("=" * 60)
        try:
            from db.seeds.populate_legal_registry import populate_registry
            populate_registry(db_url)
            print("-> Hoàn tất khởi tạo danh mục Registry & Taxonomy!")
        except Exception as e:
            print(f"CẢNH BÁO: Lỗi khi nạp registry (bỏ qua): {e}")

        print("\n" + "=" * 60)
        print("BƯỚC 3/3: Khởi tạo Legal Applicability Rules (Eligibility Gate)...")
        print("=" * 60)
        try:
            from db.seeds.seed_applicability_rules import migrate_and_seed
            migrate_and_seed()
            print("-> Hoàn tất nạp các quy tắc điều kiện áp dụng pháp luật!")
        except Exception as e:
            print(f"CẢNH BÁO: Lỗi khi nạp rules (bỏ qua): {e}")

        print("\n" + "=" * 60)
        print("HOÀN THÀNH: Toàn bộ 4 bảng tri thức pháp lý đã sẵn sàng hoạt động!")
        print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
