"""
Script tải dữ liệu pháp lý tiếng Việt từ Hugging Face
------------------------------------------------------
Tải về 2 bộ dữ liệu chính:
  1. tmquan/vbpl-vn         → Văn bản pháp luật (luật, nghị định, thông tư)
  2. YuITC/Vietnamese-Legal-Doc-Retrieval-Data → Bộ câu hỏi-đáp mẫu (Ground Truth cho Retrieval)

Cách dùng:
  python scripts/download_data.py                  # Tải 100 docs (mặc định)
  python scripts/download_data.py --corpus 1000    # Tải 1000 docs
  python scripts/download_data.py --corpus 300 --balanced --append  # Tải 300 Luật+NĐ+TT, append
  python scripts/download_data.py --corpus 1000 --append --skip-eval
"""

import os
import sys
import json
import argparse
import io

# Fix encoding cho Windows (tránh lỗi UnicodeEncodeError với tiếng Việt)
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if sys.stderr.encoding != "utf-8":
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


PROJECT_ROOT  = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA_LAWS_DIR = os.path.join(PROJECT_ROOT, "data", "raw", "laws")
DATA_EVAL_DIR = os.path.join(PROJECT_ROOT, "data", "eval")

os.makedirs(DATA_LAWS_DIR, exist_ok=True)
os.makedirs(DATA_EVAL_DIR, exist_ok=True)


# ============================================================
# Bộ dữ liệu 1: Văn bản pháp luật (tải trực tiếp Parquet)
# ============================================================

# Ánh xạ tên thân thiện → giá trị doc_type trong dataset
DOC_TYPE_ALIASES = {
    "luat":               ["luat"],
    "nghi_dinh":          ["nghi_dinh"],
    "thong_tu":           ["thong_tu", "thong_tu_lien_tich"],
    "quyet_dinh":         ["quyet_dinh"],
    "nghi_quyet":         ["nghi_quyet"],
    "chi_thi":            ["chi_thi"],
    "sac_lenh":           ["sac_lenh"],
    "van_ban_khac":       ["van_ban_khac", "van_ban_hop_nhat"],
}

def download_legal_corpus(
    n_samples: int = 100,
    append: bool = False,
    doc_types: list = None,
):
    """
    Tải văn bản pháp luật từ tmquan/vbpl-vn bằng cách download
    trực tiếp file Parquet từ HuggingFace Hub — tránh mọi lỗi
    tương thích của `datasets` library.
    """
    # Giải nén alias → danh sách giá trị doc_type thực tế
    allowed_types = None
    if doc_types:
        allowed_types = set()
        for alias in doc_types:
            resolved = DOC_TYPE_ALIASES.get(alias, [alias])
            allowed_types.update(resolved)

    print("=" * 60)
    print(f"[1/2] Tải bộ dữ liệu văn bản pháp luật: tmquan/vbpl-vn")
    print(f"      Số lượng mục tiêu : {n_samples}")
    print(f"      Lọc doc_type      : {sorted(allowed_types) if allowed_types else 'Tất cả'}")
    print(f"      Chế độ            : {'Append (bỏ qua doc đã có)' if append else 'Ghi đè toàn bộ'}")
    print("=" * 60)

    try:
        import pandas as pd
        from huggingface_hub import HfFileSystem
    except ImportError as e:
        print(f"❌ Thiếu thư viện: {e}")
        print("   Chạy: pip install pandas huggingface_hub pyarrow")
        return

    output_file = os.path.join(DATA_LAWS_DIR, "vbpl_sample.jsonl")

    # Đọc các doc_id đã có nếu ở chế độ append
    existing_ids = set()
    if append and os.path.exists(output_file):
        with open(output_file, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    doc = json.loads(line)
                    doc_id = doc.get("item_id") or doc.get("doc_id") or doc.get("id")
                    if doc_id:
                        existing_ids.add(str(doc_id))
                except Exception:
                    pass
        print(f"   📂 File cũ có {len(existing_ids)} văn bản, sẽ bỏ qua nếu trùng.")

    # Liệt kê danh sách file Parquet trên HuggingFace Hub
    fs = HfFileSystem()
    parquet_files = fs.glob("datasets/tmquan/vbpl-vn/**/*.parquet")
    if not parquet_files:
        # Thử lại với path khác
        parquet_files = fs.glob("datasets/tmquan/vbpl-vn/*.parquet")

    print(f"   🔍 Tìm thấy {len(parquet_files)} file Parquet trên HuggingFace Hub.")

    write_mode = "a" if (append and existing_ids) else "w"
    new_count  = 0
    skip_count = 0
    done       = False

    with open(output_file, write_mode, encoding="utf-8") as out_f:
        for pq_path in sorted(parquet_files):
            if done:
                break

            print(f"   ⬇️  Đang đọc: {pq_path.split('/')[-1]} ...")
            try:
                with fs.open(pq_path, "rb") as pq_file:
                    df = pd.read_parquet(pq_file)
            except Exception as e:
                print(f"      ⚠️  Bỏ qua file lỗi: {e}")
                continue

            for _, row in df.iterrows():
                if new_count >= n_samples:
                    done = True
                    break

                record = row.to_dict()
                doc_id = str(record.get("item_id") or record.get("doc_id") or record.get("id") or "")

                # Lọc theo doc_type nếu có chỉ định
                if allowed_types:
                    row_type = str(record.get("doc_type") or "").strip().lower()
                    if row_type not in allowed_types:
                        skip_count += 1
                        continue

                if append and doc_id in existing_ids:
                    skip_count += 1
                    continue

                # Serialize an toàn (convert numpy/bytes/etc.)
                serializable = {}
                for k, v in record.items():
                    try:
                        if hasattr(v, "item"):        # numpy scalar
                            v = v.item()
                        elif isinstance(v, bytes):
                            v = v.decode("utf-8", errors="replace")
                        json.dumps(v, ensure_ascii=False)
                        serializable[k] = v
                    except (TypeError, ValueError):
                        serializable[k] = str(v)

                out_f.write(json.dumps(serializable, ensure_ascii=False) + "\n")
                new_count += 1

                if new_count % 100 == 0:
                    print(f"      ✅ Đã lưu: {new_count} văn bản mới...")

    total = len(existing_ids) + new_count
    print(f"\n✅ Hoàn tất!")
    print(f"   Mới thêm : {new_count} văn bản")
    print(f"   Bỏ qua   : {skip_count} văn bản (trùng)")
    print(f"   Tổng cộng: {total} văn bản → {output_file}\n")


# ============================================================
# Bộ dữ liệu 2: Câu hỏi-đáp Ground Truth cho Retrieval
# ============================================================
def download_retrieval_eval():
    """Tải bộ câu hỏi-đáp ground truth (tự động bỏ qua nếu đã có)."""
    print("=" * 60)
    print("[2/2] Tải bộ câu hỏi-đáp: YuITC/Vietnamese-Legal-Doc-Retrieval-Data")
    print("=" * 60)

    train_file = os.path.join(DATA_EVAL_DIR, "retrieval_eval_train.jsonl")
    test_file  = os.path.join(DATA_EVAL_DIR, "retrieval_eval_test.jsonl")
    if os.path.exists(train_file) and os.path.exists(test_file):
        train_mb = os.path.getsize(train_file) / 1024 / 1024
        test_mb  = os.path.getsize(test_file)  / 1024 / 1024
        print(f"   ⏭️  Đã tồn tại — train: {train_mb:.1f} MB, test: {test_mb:.1f} MB. Bỏ qua.\n")
        return

    try:
        from datasets import load_dataset
        dataset = load_dataset("YuITC/Vietnamese-Legal-Doc-Retrieval-Data", trust_remote_code=True)
        for split_name, split_data in dataset.items():
            output_file = os.path.join(DATA_EVAL_DIR, f"retrieval_eval_{split_name}.jsonl")
            with open(output_file, "w", encoding="utf-8") as f:
                for item in split_data:
                    f.write(json.dumps(item, ensure_ascii=False) + "\n")
            print(f"   ✅ Split '{split_name}': {len(split_data)} mẫu → {output_file}")
        print()
    except Exception as e:
        print(f"\n❌ Lỗi: {e}")
        print("   Gợi ý: Thử chạy: huggingface-cli login\n")


# ============================================================
# CHẠY
# ============================================================
# Preset cân bằng: loại văn bản có tính ứng dụng cao trong hỏi đáp pháp luật
BALANCED_TYPES = ["luat", "nghi_dinh", "thong_tu"]

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Tải dữ liệu pháp lý từ HuggingFace",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ví dụ:
  # Tải 300 văn bản gồm Luật + Nghị định + Thông tư (preset cân bằng)
  python scripts/download_data.py --corpus 300 --types luat nghi_dinh thong_tu --append

  # Tải thêm 200 Luật vào corpus hiện có
  python scripts/download_data.py --corpus 200 --types luat --append

  # Tải 1000 văn bản bất kỳ (không lọc) — như cũ
  python scripts/download_data.py --corpus 1000 --append
        """
    )
    parser.add_argument("--corpus",    type=int, default=100,
                        help="Số văn bản mới cần tải (mặc định: 100)")
    parser.add_argument("--append",    action="store_true",
                        help="Thêm vào file cũ, không ghi đè")
    parser.add_argument("--skip-eval", action="store_true",
                        help="Bỏ qua bước tải eval dataset")
    parser.add_argument(
        "--types",
        nargs="+",
        metavar="DOC_TYPE",
        default=None,
        help=(
            "Chỉ tải văn bản thuộc loại được liệt kê. "
            f"Giá trị hợp lệ: {', '.join(DOC_TYPE_ALIASES.keys())}. "
            "Mặc định: tải tất cả loại."
        ),
    )
    parser.add_argument("--balanced",  action="store_true",
                        help=f"Preset cân bằng: tải {BALANCED_TYPES} (bỏ qua --types nếu dùng cờ này)")
    args = parser.parse_args()

    chosen_types = None
    if args.balanced:
        chosen_types = BALANCED_TYPES
        print(f"   ⚖️  Dùng preset cân bằng: {chosen_types}")
    elif args.types:
        chosen_types = args.types

    print("\n🚀 Bắt đầu tải dữ liệu pháp lý tiếng Việt...\n")
    download_legal_corpus(
        n_samples=args.corpus,
        append=args.append,
        doc_types=chosen_types,
    )
    if not args.skip_eval:
        download_retrieval_eval()
    print("🎉 Hoàn tất! Kiểm tra thư mục data/raw/ và data/eval/")
