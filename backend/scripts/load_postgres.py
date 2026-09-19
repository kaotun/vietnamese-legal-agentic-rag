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
    """Tạo bảng và các chỉ mục cần thiết."""
    query = f"""
    CREATE TABLE IF NOT EXISTS {table_name} (
        id INTEGER PRIMARY KEY,
        law_id TEXT NOT NULL,
        law_name TEXT NOT NULL,
        doc_type TEXT NOT NULL,
        article TEXT NOT NULL,
        article_title TEXT NOT NULL,
        content TEXT NOT NULL,
        author TEXT NOT NULL,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    CREATE INDEX IF NOT EXISTS idx_{table_name}_law_id ON {table_name}(law_id);
    CREATE INDEX IF NOT EXISTS idx_{table_name}_article ON {table_name}(article);
    """
    await conn.execute(query)


async def insert_records(
    conn: asyncpg.Connection, table_name: str, records: list[dict[str, Any]], batch_size: int = 500
) -> int:
    """Nạp danh sách record vào bảng bằng câu lệnh UPSERT theo batch."""
    upsert_sql = f"""
    INSERT INTO {table_name} (id, law_id, law_name, doc_type, article, article_title, content, author)
    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
    ON CONFLICT (id) DO UPDATE SET
        law_id = EXCLUDED.law_id,
        law_name = EXCLUDED.law_name,
        doc_type = EXCLUDED.doc_type,
        article = EXCLUDED.article,
        article_title = EXCLUDED.article_title,
        content = EXCLUDED.content,
        author = EXCLUDED.author;
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
    args = parser.parse_args()

    settings = get_settings()
    db_url = settings.legal_assistant.postgres.database_url
    table_name = "legal_knowledge_records"

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
        print(f"HOÀN THÀNH: Đã nạp thành công {total_loaded} records vào PostgreSQL!")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
