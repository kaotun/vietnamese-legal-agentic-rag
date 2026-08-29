"""
run_ingestion.py — End-to-end Ingestion Pipeline

Chạy toàn bộ Phase 1 pipeline:
  vbpl_sample.jsonl
      └─► DocumentExtractor  → List[LegalDocument]
          └─► ArticleBoundaryChunker → List[LegalChunk]
              ├─► DocumentEmbedder  → FAISS index (data/processed/)
              └─► BM25Index         → BM25 pickle (data/processed/)

Cách chạy:
  # Chạy toàn bộ corpus
  python scripts/run_ingestion.py

  # Chạy nhanh với 50 văn bản đầu (để test)
  python scripts/run_ingestion.py --limit 50

  # Chỉ build BM25 (bỏ qua embedding, nhanh hơn)
  python scripts/run_ingestion.py --skip-embed

  # Dùng model nhẹ hơn để test
  python scripts/run_ingestion.py --model paraphrase-multilingual-MiniLM-L12-v2
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

# Thêm project root vào sys.path để import src/
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.ingestion.extractor import DocumentExtractor
from src.ingestion.chunker import ArticleBoundaryChunker
from src.ingestion.embedder import DocumentEmbedder, DEFAULT_MODEL, LIGHTWEIGHT_MODEL
from src.retrieval.keyword_search import BM25Index

# ---------------------------------------------------------------------------
# Setup logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("run_ingestion")


# ---------------------------------------------------------------------------
# Hằng số
# ---------------------------------------------------------------------------

JSONL_PATH = PROJECT_ROOT / "data/raw/laws/vbpl_sample.jsonl"
OUTPUT_DIR = PROJECT_ROOT / "data/processed"


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


def run_pipeline(
    jsonl_path: Path,
    output_dir: Path,
    limit: int | None,
    skip_embed: bool,
    model_name: str,
) -> None:
    total_start = time.time()

    logger.info("=" * 60)
    logger.info("LEGAL Q&A — INGESTION PIPELINE")
    logger.info("=" * 60)
    logger.info("Corpus:     %s", jsonl_path)
    logger.info("Output:     %s", output_dir)
    logger.info("Limit:      %s", limit or "all")
    logger.info("Model:      %s", model_name if not skip_embed else "N/A (--skip-embed)")
    logger.info("=" * 60)

    # ----------------------------------------------------------------
    # Step 1: Extract
    # ----------------------------------------------------------------
    logger.info("\n[Step 1/3] Document Extraction...")
    t0 = time.time()
    extractor = DocumentExtractor(jsonl_path)
    documents = extractor.load(limit=limit)
    logger.info(
        "  ✓ Loaded %d documents trong %.1f giây",
        len(documents),
        time.time() - t0,
    )

    if not documents:
        logger.error("Không có document nào được load. Kiểm tra lại đường dẫn file.")
        sys.exit(1)

    # Thống kê nhanh
    avg_len = sum(d.char_len for d in documents) / len(documents)
    doc_types = {}
    for d in documents:
        doc_types[d.doc_type] = doc_types.get(d.doc_type, 0) + 1
    logger.info("  Avg char_len: %.0f ký tự", avg_len)
    logger.info("  Loại văn bản: %s", doc_types)

    # ----------------------------------------------------------------
    # Step 2: Chunk
    # ----------------------------------------------------------------
    logger.info("\n[Step 2/3] Chunking...")
    t0 = time.time()
    chunker = ArticleBoundaryChunker()
    chunks = chunker.chunk_documents(documents)
    chunk_time = time.time() - t0
    logger.info(
        "  ✓ Tạo %d chunks từ %d văn bản trong %.1f giây",
        len(chunks),
        len(documents),
        chunk_time,
    )

    # Thống kê chunk
    avg_chunk_len = sum(c.char_len for c in chunks) / len(chunks)
    short_chunks = sum(1 for c in chunks if c.char_len < 100)
    long_chunks = sum(1 for c in chunks if c.char_len > 2000)
    has_article_ref = sum(1 for c in chunks if c.article_ref)
    logger.info("  Avg chunk length:    %.0f ký tự", avg_chunk_len)
    logger.info("  Chunk có article_ref: %d/%d (%.1f%%)",
                has_article_ref, len(chunks), 100 * has_article_ref / len(chunks))
    logger.info("  Chunk ngắn (<100):   %d", short_chunks)
    logger.info("  Chunk dài (>2000):   %d", long_chunks)

    # ----------------------------------------------------------------
    # Step 3a: Build BM25 Index (nhanh, luôn chạy)
    # ----------------------------------------------------------------
    logger.info("\n[Step 3a/3] Building BM25 Index...")
    t0 = time.time()
    bm25_index = BM25Index()
    bm25_index.build(chunks)
    bm25_path = output_dir / "bm25_index.pkl"
    bm25_index.save(bm25_path)
    logger.info("  ✓ BM25 index saved trong %.1f giây → %s", time.time() - t0, bm25_path)

    # ----------------------------------------------------------------
    # Step 3b: Build FAISS Embedding Index (chậm hơn, có thể skip)
    # ----------------------------------------------------------------
    if skip_embed:
        logger.info("\n[Step 3b/3] Embedding — BỎ QUA (--skip-embed)")
    else:
        logger.info("\n[Step 3b/3] Building FAISS Embedding Index...")
        logger.info("  Model: %s", model_name)
        logger.info("  (Lần đầu chạy sẽ download model, có thể mất vài phút)")
        t0 = time.time()
        embedder = DocumentEmbedder(model_name=model_name)
        embedder.build_index(chunks, output_dir=output_dir)
        logger.info("  ✓ FAISS index saved trong %.1f giây", time.time() - t0)

    # ----------------------------------------------------------------
    # Summary
    # ----------------------------------------------------------------
    total_time = time.time() - total_start
    logger.info("\n" + "=" * 60)
    logger.info("INGESTION HOÀN THÀNH trong %.1f giây", total_time)
    logger.info("  Documents: %d", len(documents))
    logger.info("  Chunks:    %d", len(chunks))
    logger.info("  Output:    %s", output_dir)
    logger.info("=" * 60)

    # ----------------------------------------------------------------
    # Quick sanity check
    # ----------------------------------------------------------------
    logger.info("\n[Sanity Check] Query thử BM25...")
    test_query = "điều kiện để ký hợp đồng lao động"
    results = bm25_index.search(test_query, top_k=3)
    logger.info("  Query: '%s'", test_query)
    if results:
        for chunk_id, score in results:
            chunk = bm25_index.get_chunk(chunk_id)
            if chunk:
                logger.info(
                    "  → [%.3f] %s | %s: %s...",
                    score,
                    chunk_id,
                    chunk.article_ref or "no ref",
                    chunk.text[:80],
                )
    else:
        logger.warning("  Không có kết quả — kiểm tra lại corpus")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Legal Q&A — Ingestion Pipeline (Phase 1)"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Chỉ xử lý N văn bản đầu tiên (dùng để test nhanh)",
    )
    parser.add_argument(
        "--skip-embed",
        action="store_true",
        default=False,
        help="Bỏ qua bước embedding FAISS (chỉ build BM25)",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=DEFAULT_MODEL,
        help=f"SentenceTransformer model (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--input",
        type=str,
        default=str(JSONL_PATH),
        help="Đường dẫn file JSONL đầu vào",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=str(OUTPUT_DIR),
        help="Thư mục lưu index đầu ra",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run_pipeline(
        jsonl_path=Path(args.input),
        output_dir=Path(args.output),
        limit=args.limit,
        skip_embed=args.skip_embed,
        model_name=args.model,
    )
