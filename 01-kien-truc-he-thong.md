# LegalDoc QA — Tài liệu Kiến trúc Hệ thống

**Phiên bản:** 1.0
**Loại tài liệu:** Kiến trúc kỹ thuật (Technical Architecture Document)
**Đối tượng:** Đội ngũ phát triển / người thực hiện đồ án

---

## 1. Tổng quan hệ thống

### 1.1. Mục tiêu
LegalDoc QA là hệ thống AI hỗ trợ đọc hiểu, tóm tắt và hỏi-đáp trên tài liệu pháp lý (hợp đồng, điều khoản dịch vụ, văn bản quy phạm). Hệ thống giải quyết 3 bài toán cốt lõi:

1. **Semantic Search theo điều khoản** — cho phép truy vấn ngôn ngữ tự nhiên để tìm đúng điều khoản liên quan trong văn bản dài hàng chục/hàng trăm trang.
2. **Giải thích điều khoản phức tạp** — dịch ngôn ngữ pháp lý (legalese) sang ngôn ngữ phổ thông, có lập luận từng bước (chain-of-thought).
3. **Trích xuất rủi ro có cấu trúc** — quét toàn bộ tài liệu, xác định các điều khoản tiềm ẩn rủi ro và xuất ra bảng có schema rõ ràng.

### 1.2. Phạm vi (Scope)
- **Ngôn ngữ:** tiếng Việt — toàn bộ tài liệu đầu vào, prompt, và câu trả lời đều bằng tiếng Việt. Embedding model và LLM sử dụng phải có năng lực xử lý tiếng Việt tốt (ưu tiên model đa ngôn ngữ đã được kiểm chứng trên tiếng Việt, hoặc embedding model huấn luyện riêng cho tiếng Việt).
- **Trong phạm vi:** văn bản quy phạm pháp luật Việt Nam (Luật, Nghị định, Thông tư), hợp đồng thương mại, điều khoản dịch vụ (ToS), NDA, hợp đồng lao động — văn bản dạng text/PDF có cấu trúc điều khoản.
- **Ngoài phạm vi:** tư vấn pháp lý mang tính ràng buộc, xử lý văn bản viết tay/scan chất lượng thấp (có thể mở rộng qua OCR ở giai đoạn sau), đa ngôn ngữ đồng thời trong 1 tài liệu.

### 1.2.1. Nguồn dữ liệu tham chiếu

Hệ thống được thiết kế để làm việc với dữ liệu pháp lý tiếng Việt, khai thác các nguồn công khai sau:

| Nguồn | Loại dữ liệu | Vai trò trong hệ thống |
|---|---|---|
| Cơ sở dữ liệu Quốc gia về Pháp luật (vbpl.vn — Bộ Tư pháp) | Luật, Nghị định, Thông tư, Quyết định (cấu trúc phân cấp sẵn) | Nguồn chính cho Document Ingestion, dùng luyện/kiểm thử chunking theo điều khoản |
| Bộ dữ liệu câu hỏi–điều khoản liên quan (retrieval QA) | Cặp câu hỏi và ngữ cảnh điều khoản đã gán nhãn | Ground truth để đánh giá độ chính xác của Retrieval Layer |
| Toàn văn Hiến pháp, Bộ luật, Luật (dạng Markdown chuẩn hóa) | Văn bản luật cấp cao | Dữ liệu kiểm thử semantic search trên văn bản dài |
| Hợp đồng thương mại/NDA/lao động mẫu (tự thu thập, đã ẩn danh) | Hợp đồng thực tế dạng mẫu | Dữ liệu chính cho Risk Extraction Pipeline vì gần với use-case thật nhất |

Toàn bộ dữ liệu văn bản pháp luật sử dụng đều thuộc diện công khai theo quy định pháp luật về tiếp cận thông tin; hợp đồng thương mại thu thập thêm bắt buộc phải được ẩn danh hoàn toàn trước khi đưa vào hệ thống.

### 1.3. Nguyên tắc thiết kế cốt lõi
| Nguyên tắc | Ý nghĩa |
|---|---|
| **Grounded-by-design** | Mọi câu trả lời phải trích dẫn được điều khoản gốc — không có câu trả lời "trôi nổi" không nguồn gốc |
| **Fail-safe trên không chắc chắn** | Khi độ tin cậy thấp, hệ thống phải nói "không tìm thấy" thay vì suy diễn |
| **Cấu trúc hóa đầu ra** | Mọi kết quả trích xuất đều theo schema cố định, có thể kiểm chứng bằng validation |
| **Tách bạch retrieval và reasoning** | Tầng tìm kiếm (retrieval) độc lập với tầng suy luận (LLM reasoning) để dễ debug và tối ưu riêng lẻ |

---

## 2. Kiến trúc tổng thể

```
┌──────────────────────────────────────────────────────────────────────┐
│                            CLIENT LAYER                                │
│                  (Web UI: upload, chat, xem bảng rủi ro)               │
└───────────────────────────────┬──────────────────────────────────────┘
                                 │ REST / WebSocket
┌───────────────────────────────▼──────────────────────────────────────┐
│                          APPLICATION LAYER                             │
│  ┌────────────────┐  ┌──────────────────┐  ┌────────────────────┐    │
│  │ Document        │  │ Query Orchestrator│  │ Risk Extraction     │   │
│  │ Ingestion Service│  │  (Router)         │  │ Pipeline            │   │
│  └────────────────┘  └──────────────────┘  └────────────────────┘    │
└───────────────────────────────┬──────────────────────────────────────┘
                                 │
┌───────────────────────────────▼──────────────────────────────────────┐
│                          RETRIEVAL LAYER                                │
│  ┌───────────────┐   ┌────────────────┐   ┌──────────────────────┐   │
│  │ Semantic Search│   │ Keyword Search  │   │ Reranker              │  │
│  │ (FAISS + emb.) │   │ (BM25)          │   │ (Cross-Encoder)        │  │
│  └───────────────┘   └────────────────┘   └──────────────────────┘   │
└───────────────────────────────┬──────────────────────────────────────┘
                                 │
┌───────────────────────────────▼──────────────────────────────────────┐
│                          REASONING LAYER                                │
│  ┌────────────────────┐   ┌───────────────────────────────────────┐  │
│  │ LLM Reasoning Engine │   │ Structured Output Validator (Schema)  │  │
│  │ (CoT prompting)      │   │                                        │  │
│  └────────────────────┘   └───────────────────────────────────────┘  │
└───────────────────────────────┬──────────────────────────────────────┘
                                 │
┌───────────────────────────────▼──────────────────────────────────────┐
│                            DATA LAYER                                  │
│  Vector Store (FAISS)  │  Document Store  │  Metadata & Session DB     │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 3. Chi tiết các thành phần

### 3.1. Document Ingestion Service
Chịu trách nhiệm biến tài liệu thô thành dữ liệu có thể tìm kiếm được.

**Luồng xử lý:**
1. Nhận file đầu vào (PDF/DOCX/TXT)
2. Trích xuất text, giữ lại metadata cấu trúc (số điều khoản, tiêu đề section, số trang)
3. **Chunking theo ranh giới ngữ nghĩa** — không cắt cứng theo số token, mà cắt theo điều khoản/khoản/mục, tránh việc một điều khoản bị chia rời làm mất ngữ cảnh
4. Sinh embedding cho từng chunk
5. Lưu song song: (a) vector vào FAISS, (b) text gốc + metadata vào Document Store, (c) chỉ mục từ khóa vào BM25 index

**Đầu ra:** mỗi chunk được gán một `chunk_id`, liên kết với vị trí gốc trong tài liệu (điều khoản số mấy, trang nào) — đây là điều kiện tiên quyết để làm được "grounded citation" ở bước sau.

### 3.2. Query Orchestrator (Router)
Là "bộ não điều phối", quyết định câu hỏi của người dùng cần luồng xử lý nào:
- **Câu hỏi tra cứu điều khoản cụ thể** → đi qua Retrieval Layer đầy đủ (semantic + keyword + rerank)
- **Câu hỏi giải thích khái niệm chung** → có thể trả lời trực tiếp không cần retrieval (nếu không phụ thuộc tài liệu)
- **Yêu cầu quét toàn bộ rủi ro** → chuyển sang Risk Extraction Pipeline (xử lý toàn văn bản, không chỉ 1 truy vấn)

### 3.3. Retrieval Layer — trái tim kỹ thuật của hệ thống

**Bước 1 — Hybrid Search:**
Kết hợp hai phương pháp bổ trợ nhau:
- *Semantic search (embeddings + FAISS):* tốt cho câu hỏi diễn đạt bằng ý nghĩa, đồng nghĩa
- *Keyword search (BM25):* tốt cho việc bắt chính xác số liệu, tên riêng, mã điều khoản mà embedding có xu hướng bỏ sót

Kết quả từ hai nguồn được hợp nhất (union) trước khi sang bước rerank.

**Bước 2 — Reranking:**
Danh sách ứng viên (thường 20–30 chunk) được đưa qua mô hình cross-encoder để chấm điểm mức độ liên quan chính xác hơn nhiều so với cosine similarity thuần túy. Chỉ top 3–5 chunk có điểm cao nhất được đưa vào bước suy luận — giúp giảm nhiễu và giảm chi phí token.

### 3.4. Reasoning Layer
**Chain-of-Thought Explanation:**
Với các điều khoản phức tạp, hệ thống yêu cầu model lập luận theo trình tự: xác định chủ thể/đối tượng của điều khoản → xác định nghĩa vụ/quyền lợi → xác định điều kiện áp dụng → diễn giải sang ngôn ngữ phổ thông. Cách này giảm việc model "nhảy cóc" đến kết luận sai.

**Structured Output cho trích xuất rủi ro:**
Mỗi rủi ro phát hiện được phải tuân theo schema cố định gồm: vị trí điều khoản, loại rủi ro, mức độ nghiêm trọng, mô tả ngắn gọn, khuyến nghị. Đầu ra được validate bằng schema trước khi trả về client — nếu model trả sai định dạng, hệ thống tự động yêu cầu sinh lại.

**Grounded Citation:**
Mọi câu trả lời đều bắt buộc đính kèm chunk_id / số điều khoản nguồn. Đây là cơ chế chống hallucination quan trọng nhất của toàn hệ thống — nếu không truy được nguồn, câu trả lời bị coi là không hợp lệ.

### 3.5. Data Layer
| Thành phần | Vai trò |
|---|---|
| Vector Store (FAISS) | Lưu embedding của từng chunk, phục vụ semantic search |
| Document Store | Lưu text gốc + metadata cấu trúc, phục vụ truy xuất nguồn khi trích dẫn |
| Metadata & Session DB | Lưu lịch sử hội thoại, phiên làm việc theo từng tài liệu upload |

---

## 4. Luồng hoạt động chi tiết (End-to-End Flow)

### 4.1. Luồng Upload & Xử lý tài liệu
```
Người dùng upload PDF
   → Trích xuất text + giữ cấu trúc điều khoản
   → Chunking theo ranh giới ngữ nghĩa
   → Sinh embedding cho từng chunk
   → Lưu vào FAISS + Document Store + BM25 index
   → Trả về xác nhận "tài liệu đã sẵn sàng để hỏi đáp"
```

### 4.2. Luồng Hỏi-đáp (Query Flow)
```
Người dùng đặt câu hỏi
   → Query Orchestrator phân loại loại câu hỏi
   → Hybrid Search (semantic + BM25) lấy top-N ứng viên
   → Reranker chọn lọc còn top-k chunk liên quan nhất
   → LLM Reasoning Engine sinh câu trả lời theo Chain-of-Thought
   → Đính kèm citation (điều khoản/trang nguồn)
   → Trả kết quả về client
```

### 4.3. Luồng Trích xuất Rủi ro (Risk Scan Flow)
```
Người dùng yêu cầu "quét rủi ro toàn bộ hợp đồng"
   → Hệ thống duyệt tuần tự từng điều khoản (không chỉ 1 truy vấn)
   → Với mỗi điều khoản: LLM đánh giá có rủi ro hay không, theo schema cố định
   → Kết quả được tổng hợp và validate bằng schema
   → Xuất bảng rủi ro có sắp xếp theo mức độ nghiêm trọng
```

---

## 5. Chiến lược chống Hallucination (Trust & Safety Layer)

Đây là phần quan trọng bậc nhất với một sản phẩm liên quan đến pháp lý:

1. **Retrieval-grounded only** — model chỉ được trả lời dựa trên chunk đã retrieve, không được dùng kiến thức "nền" của model về luật (vì có thể sai hoặc không cập nhật)
2. **Citation bắt buộc** — không có citation = không trả lời
3. **Ngưỡng độ tin cậy (confidence threshold)** — nếu điểm rerank của chunk tốt nhất quá thấp, hệ thống trả lời "không tìm thấy điều khoản liên quan" thay vì đoán
4. **Disclaimer rõ ràng** — hệ thống luôn nhắc đây là công cụ hỗ trợ đọc hiểu, không thay thế tư vấn pháp lý chuyên nghiệp

---

## 6. Khả năng mở rộng (Scalability & Future Extensions)

| Hướng mở rộng | Mô tả |
|---|---|
| OCR cho văn bản scan | Thêm tầng tiền xử lý OCR để hỗ trợ hợp đồng dạng ảnh/scan |
| Multi-document comparison | So sánh điều khoản giữa nhiều phiên bản hợp đồng |
| Đa ngôn ngữ | Mở rộng embedding model hỗ trợ tài liệu song ngữ Việt-Anh |
| Fine-tuning theo domain | Fine-tune model nhỏ chuyên biệt cho văn phong pháp lý tiếng Việt |
| Audit log | Ghi log toàn bộ câu hỏi/trả lời phục vụ kiểm toán và cải thiện hệ thống |

---

## 8. Cấu trúc thư mục dự án (Project Structure)

Cấu trúc thư mục được tổ chức theo từng tầng kiến trúc đã mô tả ở trên, tách bạch rõ ingestion, retrieval, reasoning và data — giúp dễ phát triển độc lập từng phần và dễ trình bày khi đưa vào portfolio.

```
vietnamese-legal-rag/
├── README.md
├── requirements.txt / pyproject.toml
├── .env.example
├── .gitignore
│
├── data/
│   ├── raw/                        # Tài liệu gốc chưa xử lý
│   │   ├── laws/                   # Văn bản luật (từ vbpl-vn, UTS_VLC...)
│   │   └── contracts/              # Hợp đồng mẫu đã ẩn danh
│   ├── processed/                  # Sau khi chunking + gán metadata
│   ├── eval/                       # Bộ câu hỏi/đáp mẫu (ground truth)
│   │   ├── retrieval_eval.jsonl
│   │   ├── risk_eval.jsonl
│   │   └── adversarial_eval.jsonl
│   └── schemas/                    # Định nghĩa schema JSON cho risk extraction
│
├── src/
│   ├── ingestion/                  # Phase 1 — Document Ingestion
│   │   ├── extractor.py            # Trích xuất text từ PDF/DOCX
│   │   ├── chunker.py              # Semantic chunking theo điều khoản
│   │   └── embedder.py             # Sinh embedding cho từng chunk
│   │
│   ├── retrieval/                  # Phase 2 — Retrieval Layer
│   │   ├── vector_store.py         # Kết nối FAISS
│   │   ├── keyword_search.py       # BM25 index
│   │   ├── hybrid_search.py        # Hợp nhất semantic + keyword
│   │   └── reranker.py             # Cross-encoder reranking
│   │
│   ├── reasoning/                  # Phase 3 — Reasoning Layer
│   │   ├── prompts/                # Template prompt (CoT, structured output)
│   │   ├── explainer.py            # Giải thích điều khoản
│   │   └── citation.py             # Gắn trích dẫn nguồn (grounded citation)
│   │
│   ├── risk_extraction/            # Phase 4 — Structured Risk Extraction
│   │   ├── extractor.py
│   │   ├── validator.py            # Validate output theo schema
│   │   └── risk_taxonomy.py        # Danh sách loại rủi ro chuẩn hóa
│   │
│   ├── orchestrator/                # Query Orchestrator (Router)
│   │   └── router.py
│   │
│   └── common/                     # Cấu hình, tiện ích dùng chung
│       ├── config.py
│       ├── logger.py
│       └── schemas.py
│
├── evaluation/                     # Phase 5 — QA & Chống Hallucination
│   ├── retrieval_metrics.py        # Recall@k, Precision@k
│   ├── hallucination_check.py
│   ├── llm_as_judge.py
│   └── reports/                    # Kết quả đánh giá theo từng lần chạy
│
├── app/                            # Phase 6 — Productization
│   ├── main.py                     # Điểm khởi chạy backend (FastAPI)
│   ├── api/                        # Định nghĩa endpoint
│   └── ui/                         # Giao diện (Streamlit/Gradio/Web)
│
├── notebooks/                      # Notebook thử nghiệm, phân tích
│   ├── 01_chunking_experiments.ipynb
│   ├── 02_retrieval_evaluation.ipynb
│   └── 03_risk_extraction_analysis.ipynb
│
├── tests/                          # Unit test / integration test
│   ├── test_chunker.py
│   ├── test_retrieval.py
│   └── test_risk_extraction.py
│
└── docs/                           # Tài liệu dự án
    ├── 01-kien-truc-he-thong.md
    ├── 02-lo-trinh-thuc-hien.md
    └── evaluation-report.md
```

### Ghi chú về cách tổ chức

- **`data/raw` tách riêng `laws` và `contracts`** — vì hai loại văn bản có cấu trúc khác nhau (luật theo Điều/Khoản/Điểm, hợp đồng theo Điều khoản/Mục), cần logic chunking riêng cho từng loại.
- **`src/` chia theo tầng kiến trúc**, không chia theo tính năng — giúp bám sát đúng luồng dữ liệu đã mô tả ở phần Kiến trúc tổng thể, dễ debug khi lỗi xảy ra ở tầng nào.
- **`evaluation/` tách biệt khỏi `src/`** — vì đây là phần đo lường chất lượng hệ thống (Phase 5), cần chạy độc lập với hệ thống chính để không lẫn logic đánh giá vào logic sản phẩm.
- **`docs/` chứa chính 2 file tài liệu này** — giữ tài liệu kiến trúc và lộ trình đi cùng source code, thuận tiện khi review hoặc đưa vào portfolio.

---



- **Chunking sai ranh giới** → điều khoản bị cắt rời, mất ngữ cảnh → cần kiểm thử kỹ thuật chunking trên nhiều loại hợp đồng khác nhau
- **Embedding không phân biệt tốt điều khoản gần giống nhau** (vd: điều khoản bồi thường vs điều khoản phạt vi phạm) → cần đánh giá bằng bộ test case thực tế trước khi triển khai
- **Chi phí token cao khi quét toàn bộ tài liệu dài** → cần chiến lược xử lý theo batch/song song để tối ưu thời gian và chi phí
- **Rủi ro pháp lý của chính sản phẩm** → luôn cần disclaimer, không định vị sản phẩm như "tư vấn pháp lý"
