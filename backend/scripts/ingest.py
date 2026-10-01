"""CLI thực thi quy trình Ingestion tài liệu pháp luật vào PostgreSQL & pgvector."""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from src.ingestion.pipeline import LegalDocumentIngestionPipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest legal documents into PostgreSQL & pgvector")
    parser.add_argument("--file", type=Path, required=True, help="Đường dẫn file JSON chứa các điều luật")
    parser.add_argument("--batch-size", type=int, default=32, help="Kích thước batch gọi embedding API")
    parser.add_argument("--skip-embeddings", action="store_true", help="Bỏ qua việc sinh embedding (chỉ nạp text)")
    parser.add_argument("--skip-bm25", action="store_true", help="Bỏ qua việc rebuild BM25 cache")
    args = parser.parse_args()

    if not args.file.exists():
        logger.error(f"Không tìm thấy file: {args.file}")
        sys.exit(1)

    logger.info(f"Đọc dữ liệu từ: {args.file}")
    with open(args.file, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        logger.error("Dữ liệu trong file JSON phải là một danh sách các bản ghi (list of objects)")
        sys.exit(1)

    pipeline = LegalDocumentIngestionPipeline()
    result = await pipeline.ingest_records(
        records=data,
        batch_size=args.batch_size,
        generate_embeddings=not args.skip_embeddings,
        rebuild_bm25_cache=not args.skip_bm25,
    )

    logger.info(f"KẾT QUẢ INGESTION: {result}")


if __name__ == "__main__":
    asyncio.run(main())
