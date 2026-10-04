"""Quy trình nạp và cập nhật dữ liệu văn bản pháp luật chuẩn hóa (Legal Ingestion Pipeline).

Hỗ trợ 5 giai đoạn:
1. Validation & Schema Normalization: Xác thực dữ liệu đầu vào.
2. Validity Assessment: Gán trạng thái hiệu lực (active/expired/partially_expired).
3. Text Enrichment & Search Indexing: Chuẩn hóa từ khóa.
4. Batch Embedding Generation: Sinh vector qua nomic-embed-text (Ollama / OpenAI API).
5. Atomic Database Upsert & BM25 Cache Rebuild: Lưu vào PostgreSQL và tái tạo cache đĩa.
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import asyncpg

from src.core.config import get_settings
from src.retrieval.keyword_store import BM25KeywordStore
from src.retrieval.vector_client import EmbeddingsClient

logger = logging.getLogger(__name__)


REQUIRED_FIELDS = {
    "law_id",
    "law_name",
    "doc_type",
    "article",
    "content",
}


class LegalDocumentIngestionPipeline:
    """Pipeline chuẩn hóa nạp, kiểm định hiệu lực và đánh chỉ mục tri thức pháp lý."""

    def __init__(self, db_url: Optional[str] = None):
        self.settings = get_settings()
        self.db_url = db_url or self.settings.legal_assistant.postgres.database_url
        self.table_name = "legal_knowledge_records"
        self.vector_client = EmbeddingsClient()
        self.keyword_store = BM25KeywordStore()

    def validate_record(self, record: Dict[str, Any], record_idx: int) -> Dict[str, Any]:
        """Xác thực và chuẩn hóa cấu trúc của một bản ghi điều luật."""
        for field in REQUIRED_FIELDS:
            if not record.get(field):
                raise ValueError(f"Bản ghi thứ {record_idx} thiếu trường bắt buộc: '{field}'")

        has_explicit_id = "id" in record and record["id"] is not None
        cleaned = {
            "id": int(record["id"]) if has_explicit_id else None,
            "_needs_auto_id": not has_explicit_id,
            "law_id": str(record.get("law_id", "")).strip(),
            "law_name": str(record.get("law_name", "")).strip(),
            "doc_type": str(record.get("doc_type", "Văn bản QPPL")).strip(),
            "article": str(record.get("article", "")).strip(),
            "article_title": str(record.get("article_title", "")).strip(),
            "content": str(record.get("content", "")).strip(),
            "author": str(record.get("author", "Cơ quan ban hành")).strip(),
            "validity_status": str(record.get("validity_status", "active")).strip().lower(),
            "effective_date": record.get("effective_date"),
            "expiration_date": record.get("expiration_date"),
            "replacement_law_id": record.get("replacement_law_id"),
        }

        # Chuẩn hóa trạng thái hiệu lực
        valid_statuses = {"active", "expired", "partially_expired", "pending"}
        if cleaned["validity_status"] not in valid_statuses:
            cleaned["validity_status"] = "active"

        return cleaned

    def prepare_embedding_text(self, record: Dict[str, Any], max_chars: int = 2500) -> str:
        """Tạo đoạn văn bản tối ưu hóa cho embedding model."""
        law = record.get("law_name", "")
        art = record.get("article", "")
        title = record.get("article_title", "")
        content = record.get("content", "")
        header = f"{art}: {title}" if title else art
        text = f"{law} - {header}\n{content}"
        return text[:max_chars].strip()

    async def ingest_records(
        self,
        records: List[Dict[str, Any]],
        batch_size: int = 32,
        generate_embeddings: bool = True,
        rebuild_bm25_cache: bool = True,
    ) -> Dict[str, Any]:
        """Thực thi toàn bộ quy trình ingestion cho danh sách văn bản."""
        total_input = len(records)
        logger.info(f"[Ingestion] Bắt đầu xử lý {total_input} bản ghi pháp luật...")

        # 1. Validation & Normalization
        valid_records: List[Dict[str, Any]] = []
        for i, r in enumerate(records, 1):
            try:
                norm = self.validate_record(r, i)
                valid_records.append(norm)
            except Exception as e:
                logger.warning(f"[Ingestion] Bỏ qua bản ghi lỗi {i}: {e}")

        logger.info(f"[Ingestion] Đã xác thực thành công {len(valid_records)}/{total_input} bản ghi.")

        # 2. Kết nối CSDL và chuẩn bị ID an toàn
        conn = await asyncpg.connect(self.db_url)
        try:
            # Truy vấn max id hiện có trong database để gán id tự tăng an toàn
            max_existing_id = await conn.fetchval(
                f"SELECT COALESCE(MAX(id), 0) FROM {self.table_name};"
            ) or 0

            assigned_counter = max_existing_id
            for r in valid_records:
                if r.get("_needs_auto_id") or r.get("id") is None:
                    assigned_counter += 1
                    r["id"] = assigned_counter

            # 3. Tạo vector embeddings (nếu bật)
            embeddings_map: Dict[int, List[float]] = {}
            if generate_embeddings:
                logger.info(f"[Ingestion] Đang sinh vector embedding qua {self.vector_client.model}...")
                for b_start in range(0, len(valid_records), batch_size):
                    batch = valid_records[b_start : b_start + batch_size]
                    batch_texts = [self.prepare_embedding_text(r) for r in batch]
                    try:
                        batch_vectors = await self.vector_client.embed_texts(batch_texts)
                        for r, vec in zip(batch, batch_vectors):
                            if vec:
                                embeddings_map[r["id"]] = vec
                    except Exception as e:
                        logger.error(f"[Ingestion] Lỗi khi tạo embeddings cho batch {b_start}: {e}")
                    
                    done = min(b_start + batch_size, len(valid_records))
                    if done % 100 == 0 or done == len(valid_records):
                        logger.info(f"[Ingestion] Đã tạo embeddings: {done}/{len(valid_records)} records...")

            # 4. Lưu dữ liệu vào PostgreSQL (UPSERT)
            upsert_sql = f"""
            INSERT INTO {self.table_name} (
                id, law_id, law_name, doc_type, article, article_title, content, author,
                validity_status, effective_date, expiration_date, replacement_law_id,
                embedding, updated_at
            )
            VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8,
                $9, $10, $11, $12,
                $13::vector, CURRENT_TIMESTAMP
            )
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
                embedding = COALESCE(EXCLUDED.embedding, {self.table_name}.embedding),
                updated_at = CURRENT_TIMESTAMP;
            """

            values = []
            for r in valid_records:
                rid = r["id"]
                vec = embeddings_map.get(rid)
                vec_str = ("[" + ",".join(f"{v:.8f}" for v in vec) + "]") if vec else None
                values.append(
                    (
                        rid,
                        r["law_id"],
                        r["law_name"],
                        r["doc_type"],
                        r["article"],
                        r["article_title"],
                        r["content"],
                        r["author"],
                        r["validity_status"],
                        r["effective_date"],
                        r["expiration_date"],
                        r["replacement_law_id"],
                        vec_str,
                    )
                )

            logger.info(f"[Ingestion] Đang lưu {len(values)} bản ghi vào PostgreSQL...")
            for b_start in range(0, len(values), 500):
                batch_vals = values[b_start : b_start + 500]
                await conn.executemany(upsert_sql, batch_vals)

            logger.info("[Ingestion] Đã lưu hoàn tất vào PostgreSQL.")

            # 5. Cập nhật BM25 Index Cache (nếu bật)
            if rebuild_bm25_cache:
                logger.info("[Ingestion] Đang tái tạo BM25 Keyword Cache trên đĩa...")
                all_rows = await conn.fetch(
                    f"SELECT id, law_id, law_name, doc_type, article, article_title, content, author, validity_status "
                    f"FROM {self.table_name} ORDER BY id ASC;"
                )
                records_for_bm25 = [dict(row) for row in all_rows]
                # Force build mới và lưu đĩa
                self.keyword_store.build_or_load(records_for_bm25)
                logger.info(f"[Ingestion] Đã làm mới BM25 cache cho {len(records_for_bm25)} điều luật.")

        finally:
            await conn.close()

        return {
            "status": "success",
            "total_input": total_input,
            "valid_records": len(valid_records),
            "embeddings_generated": len(embeddings_map),
        }
