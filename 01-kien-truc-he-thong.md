# LegalDoc QA — Tài liệu Kiến trúc Hệ thống

**Phiên bản:** 2.0
**Loại tài liệu:** Kiến trúc kỹ thuật (Technical Architecture Document)
**Đối tượng:** Đội ngũ phát triển / người thực hiện đồ án

---

## 1. Tổng quan hệ thống

### 1.1. Mục tiêu

**VietLegal QA** là hệ thống hỏi-đáp thông minh trên văn bản pháp luật tiếng Việt, cho phép người dùng đặt câu hỏi bằng ngôn ngữ tự nhiên và nhận câu trả lời có căn cứ, có trích dẫn từ văn bản gốc.

Hệ thống giải quyết **3 bài toán cốt lõi:**

1. **Retrieval-Augmented Generation (RAG)** — Truy xuất đúng điều khoản liên quan rồi mới cho LLM suy luận, không để model "bịa" từ kiến thức nền.
2. **Giải thích điều khoản phức tạp** — Dịch ngôn ngữ pháp lý (legalese) sang ngôn ngữ phổ thông, lập luận từng bước theo Chain-of-Thought.
3. **Hội thoại có bộ nhớ (Conversational Memory)** — Cho phép hỏi tiếp theo ("và điều khoản đó áp dụng khi nào?") mà không mất ngữ cảnh câu hỏi trước.

### 1.2. Phạm vi (Scope)

- **Ngôn ngữ:** Tiếng Việt — toàn bộ văn bản đầu vào, prompt và câu trả lời.
- **Trong phạm vi:** Văn bản quy phạm pháp luật Việt Nam (Luật, Nghị định, Thông tư, Quyết định); hỗ trợ thêm hợp đồng mẫu dạng synthetic cho tính năng phụ (risk hint).
- **Ngoài phạm vi:** Tư vấn pháp lý mang tính ràng buộc; văn bản scan chất lượng thấp; đa ngôn ngữ đồng thời.

### 1.3. Kỹ năng được rèn luyện qua dự án

Đây là mục tiêu học tập quan trọng nhất. Dự án được thiết kế để bạn **tự tay implement** từng kỹ thuật, không dùng framework cao cấp che khuất bên dưới:

| Phase | Kỹ thuật cần học | Ánh xạ đến kiến thức cốt lõi |
|---|---|---|
| Phase 1 — Ingestion | Tokenization, Embeddings, FAISS | Transformer tokenizer, cosine similarity, vector indexing |
| Phase 2 — Retrieval | Hybrid search, BM25, Reranking | Semantic search, keyword matching, cross-encoder |
| Phase 3 — Reasoning | Prompt engineering, Chain-of-Thought, Structured output | Zero-shot / few-shot / CoT, function calling, JSON schema |
| Phase 3 — Citation | Grounded generation | Giới hạn LLM chỉ dùng context đã retrieve |
| Phase 4 — Memory | Conversational memory | LangChain/custom memory buffer, session management |
| Phase 5 — Evaluation | LLM-as-judge, Adversarial testing | Recall@k, hallucination rate, automated evaluation |
| Phase 6 — API | Streaming, FastAPI | OpenAI/Anthropic streaming API, async endpoints |

### 1.4. Nguồn dữ liệu

| Nguồn | Loại dữ liệu | Trạng thái |
|---|---|---|
| `tmquan/vbpl-vn` (HuggingFace) | Văn bản luật có cấu trúc phân cấp | ✅ Đã tải (`data/raw/laws/vbpl_sample.jsonl`) |
| `YuITC/Vietnamese-Legal-Doc-Retrieval-Data` | Cặp câu hỏi–điều khoản (ground truth retrieval) | ✅ Đã tải (`data/eval/retrieval_eval_train/test.jsonl`) |
| Hợp đồng synthetic | 5 hợp đồng mẫu tự soạn (không chứa thông tin thật) | 🔲 Cần tạo |

### 1.5. Nguyên tắc thiết kế cốt lõi

| Nguyên tắc | Ý nghĩa |
|---|---|
| **Grounded-by-design** | Mọi câu trả lời phải trích dẫn được điều khoản nguồn — không trả lời "trôi nổi" |
| **Fail-safe trên không chắc chắn** | Điểm rerank thấp → từ chối trả lời thay vì đoán |
| **Implement-first** | Tự viết từng module trước khi dùng wrapper library — để thực sự hiểu bên trong |
| **Measurable quality** | Mọi cải tiến phải đi kèm metric (Recall@k, hallucination rate) trước/sau |

---

## 2. Kiến trúc tổng thể

```
┌──────────────────────────────────────────────────────────────────────────┐
│                              CLIENT LAYER                                  │
│           Web UI (Streamlit/Gradio): Chat, Upload, Xem nguồn trích dẫn    │
└────────────────────────────────┬─────────────────────────────────────────┘
                                  │ HTTP / WebSocket (streaming)
┌────────────────────────────────▼─────────────────────────────────────────┐
│                           APPLICATION LAYER                                │
│  ┌──────────────────┐  ┌──────────────────────┐  ┌───────────────────┐   │
│  │ Ingestion Service │  │  Query Orchestrator   │  │  Conversation     │   │
│  │ (chunker+embedder)│  │  (Router + Memory)    │  │  Memory Store     │   │
│  └──────────────────┘  └──────────────────────┘  └───────────────────┘   │
└────────────────────────────────┬─────────────────────────────────────────┘
                                  │
┌────────────────────────────────▼─────────────────────────────────────────┐
│                            RETRIEVAL LAYER                                 │
│  ┌────────────────┐   ┌─────────────────┐   ┌──────────────────────────┐ │
│  │ Semantic Search │   │  Keyword Search  │   │  Reranker                │ │
│  │ (FAISS + embed.)│   │  (BM25)          │   │  (Cross-Encoder)         │ │
│  └────────────────┘   └─────────────────┘   └──────────────────────────┘ │
│                    ↘ Hybrid Merge (RRF) ↙                                  │
└────────────────────────────────┬─────────────────────────────────────────┘
                                  │ Top-k chunks + scores
┌────────────────────────────────▼─────────────────────────────────────────┐
│                            REASONING LAYER                                 │
│  ┌──────────────────────────┐   ┌──────────────────────────────────────┐  │
│  │  LLM (OpenAI/Anthropic)  │   │  Output Validator                    │  │
│  │  CoT Prompt + Citations  │   │  (Pydantic schema, retry on fail)    │  │
│  └──────────────────────────┘   └──────────────────────────────────────┘  │
└────────────────────────────────┬─────────────────────────────────────────┘
                                  │
┌────────────────────────────────▼─────────────────────────────────────────┐
│                              DATA LAYER                                    │
│   FAISS Vector Store  │  Document Store (JSON/SQLite)  │  Session DB       │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Chi tiết các thành phần

### 3.1. Document Ingestion Service
*(Kỹ năng luyện: Tokenization, Embeddings, FAISS)*

**Luồng xử lý:**
1. Nhận file đầu vào (JSONL từ `vbpl-vn` hoặc TXT/PDF)
2. Trích xuất text, giữ metadata cấu trúc (`doc_id`, `title`, `legal_type`, số điều khoản)
3. **Semantic chunking theo ranh giới điều khoản** — Regex nhận diện `^Điều \d+\.`, `^Chương [IXV]+` — không cắt cứng theo số token
4. Sinh embedding cho từng chunk bằng embedding model đa ngôn ngữ
5. Lưu song song: vector vào FAISS, text + metadata vào Document Store, từ khóa vào BM25 index

> **Điểm học quan trọng:** Tự implement tokenization → hiểu tại sao chunking theo token cố định thất bại với văn bản pháp lý, và tại sao cần chunking theo ngữ nghĩa.

**Embedding model được dùng:**
- `keepitreal/vietnamese-sbert` — chuyên tiếng Việt
- Hoặc `paraphrase-multilingual-MiniLM-L12-v2` — đa ngôn ngữ nhẹ hơn
- *Thực nghiệm so sánh 2 model → học cách evaluate embedding quality*

### 3.2. Query Orchestrator (Router + Memory)
*(Kỹ năng luyện: Function calling, Conversational memory)*

**Hai nhiệm vụ chính:**

**A. Phân loại câu hỏi (Intent Classification):**
- Câu hỏi tra cứu điều khoản → Retrieval Flow đầy đủ
- Câu hỏi giải thích khái niệm → Retrieval + CoT Explanation
- Câu hỏi follow-up (có "đó", "vậy", "còn...") → Merge với memory trước khi retrieve
- Câu hỏi ngoài phạm vi → Từ chối lịch sự

**B. Conversational Memory:**
```python
# Mỗi session có một memory buffer lưu lịch sử hội thoại
memory = [
    {"role": "user",      "content": "Điều 15 quy định gì?"},
    {"role": "assistant", "content": "Điều 15 quy định...  [Nguồn: doc_123#Điều 15]"},
    {"role": "user",      "content": "Điều đó áp dụng khi nào?"},  # follow-up
]
# Hệ thống tự động đưa context lịch sử vào prompt khi gọi LLM
```

> **Điểm học:** Tự build memory thủ công trước, rồi so sánh với LangChain `ConversationBufferMemory` → hiểu trade-off giữa tự build vs dùng framework.

### 3.3. Retrieval Layer — Trái tim kỹ thuật
*(Kỹ năng luyện: Cosine similarity, Semantic search, BM25, Cross-encoder)*

**Bước 1 — Hybrid Search:**

| Phương pháp | Điểm mạnh | Điểm yếu |
|---|---|---|
| Semantic (FAISS + embedding) | Bắt được đồng nghĩa, ý nghĩa tương đương | Hay miss số điều khoản cụ thể (vd: "Điều 15.2") |
| Keyword (BM25) | Bắt chính xác số hiệu, tên luật, mã văn bản | Không hiểu ngữ nghĩa, miss câu hỏi diễn đạt khác |

Hai kết quả được hợp nhất bằng **Reciprocal Rank Fusion (RRF)** — cộng điểm theo hạng thứ, không theo raw score.

**Bước 2 — Reranking:**
- Lấy top-20 ứng viên từ hybrid search
- Cho qua cross-encoder (`ms-marco-MiniLM-L-6-v2` hoặc tương đương) để chấm điểm chính xác hơn
- Chọn top 3–5 chunk có điểm cao nhất
- Nếu điểm cao nhất < threshold → từ chối trả lời ("không tìm thấy thông tin liên quan")

> **Điểm học:** Tự implement cosine similarity từ numpy trước khi dùng FAISS → cảm nhận được tại sao cần indexing khi corpus lớn.

### 3.4. Reasoning Layer
*(Kỹ năng luyện: Prompt engineering, CoT, Structured output, Grounded citation, Streaming)*

**Prompt Engineering — 4 kỹ thuật được áp dụng:**

```
Zero-shot:     "Dựa vào điều khoản sau, hãy trả lời câu hỏi..."
Few-shot:      Kèm 2–3 ví dụ câu hỏi–trả lời mẫu trong prompt
Chain-of-Thought: "Hãy suy nghĩ từng bước: (1) Điều khoản này quy định về ai?
                   (2) Nghĩa vụ/quyền lợi là gì? (3) Điều kiện áp dụng?
                   (4) Kết luận bằng ngôn ngữ phổ thông."
Structured output: Yêu cầu trả về JSON schema cố định (Pydantic validate)
```

**Streaming Response:**
- Dùng OpenAI streaming API để trả từng token về client ngay khi LLM sinh ra
- Cải thiện UX đáng kể so với chờ toàn bộ response

**Grounded Citation — Cơ chế chống hallucination chính:**
```python
# Prompt bắt buộc model phải trích dẫn nguồn:
SYSTEM_PROMPT = """
Bạn chỉ được trả lời dựa trên các ĐOẠN VĂN BẢN được cung cấp bên dưới.
Mỗi điểm trong câu trả lời PHẢI kèm [Nguồn: <chunk_id>].
Nếu không tìm thấy thông tin trong các đoạn văn bản, hãy trả lời:
"Không tìm thấy thông tin liên quan trong tài liệu được cung cấp."
Tuyệt đối không dùng kiến thức bên ngoài tài liệu.
"""
```

### 3.5. Conversation Memory Store
*(Kỹ năng luyện: Session management, Memory patterns)*

```
Session DB (SQLite / in-memory dict):
├── session_id → [list of messages]        # Full history
├── session_id → [last 5 exchanges]        # Sliding window (tránh vượt context limit)
└── session_id → current_document_id      # Tài liệu đang hỏi
```

**Các chiến lược memory được thực nghiệm:**
- `BufferMemory` — giữ toàn bộ lịch sử (nhanh hết token)
- `WindowMemory` — chỉ giữ k câu cuối (trade-off nhớ vs chi phí)
- `SummaryMemory` — tóm tắt lịch sử cũ (phức tạp hơn, hiệu quả hơn)

### 3.6. Data Layer

| Thành phần | Công nghệ | Vai trò |
|---|---|---|
| Vector Store | FAISS | Lưu embedding, phục vụ ANN search |
| Document Store | JSON files / SQLite | Lưu text gốc + metadata, phục vụ trích dẫn |
| BM25 Index | `rank-bm25` (Python) | Keyword index cho hybrid search |
| Session DB | SQLite / dict in-memory | Lưu lịch sử hội thoại theo session |

---

## 4. Luồng hoạt động chi tiết (End-to-End Flow)

### 4.1. Luồng Ingestion (chạy một lần khi khởi tạo)
```
Tải JSONL từ vbpl-vn
   → Parse từng document, lấy field "markdown" (text đã chuẩn hóa)
   → Regex chunking: cắt theo "Điều X.", "Chương X", "Khoản X"
   → Với mỗi chunk: gọi embedding model → vector float32[]
   → Batch insert vào FAISS index
   → Lưu {chunk_id, text, doc_id, article_ref, metadata} vào Document Store
   → Build BM25 index từ toàn bộ chunk texts
   → Lưu index xuống disk
```

### 4.2. Luồng Hỏi-đáp (mỗi câu hỏi của user)
```
User gõ câu hỏi
   → Memory: lấy lịch sử session hiện tại
   → Query Orchestrator: phân loại intent, expand query nếu là follow-up
   → Hybrid Search:
       ├─ Semantic: embed query → FAISS.search(top 20) → [(chunk_id, score)]
       └─ Keyword:  BM25.get_scores(query) → [(chunk_id, score)]
   → RRF Merge: kết hợp 2 danh sách → ranked list
   → Reranker: cross-encoder.predict(query, chunk_text) → re-scored list
   → Confidence check: top score < threshold? → trả lời "không tìm thấy"
   → LLM Call (streaming):
       ├─ System prompt: grounding instructions + citation requirement
       ├─ Context: top 3-5 chunks (text + chunk_id)
       ├─ Memory: k câu hội thoại gần nhất
       └─ User: câu hỏi hiện tại
   → Stream response về UI token-by-token
   → Lưu Q&A vào session memory
   → Hiển thị citations dưới câu trả lời
```

### 4.3. Luồng Evaluation (chạy định kỳ để đo chất lượng)
```
Load retrieval_eval_test.jsonl (ground truth Q&A pairs)
   → Với mỗi câu hỏi:
       ├─ Chạy Retrieval Layer → lấy top-k chunks
       ├─ Check: ground truth chunk_id có trong top-k không?
       └─ Ghi nhận: hit (True/False), rank của ground truth
   → Tính Recall@1, Recall@5, MRR
   → So sánh: trước/sau khi thêm reranking, thay đổi embedding model...
   → Chạy adversarial_eval.jsonl → đo tỷ lệ câu hỏi OOD bị từ chối đúng
   → Xuất báo cáo markdown vào evaluation/reports/
```

---

## 5. Chiến lược chống Hallucination (Trust Layer)

Đặc biệt quan trọng với domain pháp lý:

1. **Retrieval-grounded only** — Model chỉ dùng chunks đã retrieve, không dùng kiến thức nền
2. **Citation bắt buộc** — Không có `[Nguồn: chunk_id]` = câu trả lời không hợp lệ
3. **Confidence threshold** — Rerank score < threshold → từ chối thay vì đoán
4. **Adversarial test set** — Câu hỏi bẫy (ngoài phạm vi, mơ hồ) → kiểm tra hệ thống có từ chối không
5. **LLM-as-Judge** — Dùng model thứ 2 chấm điểm câu trả lời của model chính (faithfulness, relevance)
6. **Disclaimer** — Mọi response đều kèm nhắc nhở đây là công cụ hỗ trợ, không thay thế tư vấn pháp lý

---

## 6. Cấu trúc thư mục dự án

```
legaldoc-qa-vn/
├── README.md
├── requirements.txt
├── .env.example
├── .gitignore
│
├── data/
│   ├── raw/
│   │   ├── laws/                        # vbpl_sample.jsonl (đã có)
│   │   └── contracts/                   # Hợp đồng synthetic (cần tạo)
│   ├── processed/                       # Chunks sau khi ingestion
│   └── eval/
│       ├── retrieval_eval_train.jsonl   # ✅ Ground truth train
│       ├── retrieval_eval_test.jsonl    # ✅ Ground truth test
│       ├── adversarial_eval.jsonl       # 🔲 Cần tạo
│       └── risk_eval.jsonl              # 🔲 Cần tạo (optional)
│
├── src/
│   ├── ingestion/                       # Phase 1
│   │   ├── extractor.py                 # Parse JSONL, PDF, TXT
│   │   ├── chunker.py                   # Semantic chunking theo điều khoản
│   │   └── embedder.py                  # Sinh embedding, build FAISS index
│   │
│   ├── retrieval/                       # Phase 2
│   │   ├── vector_store.py              # FAISS wrapper
│   │   ├── keyword_search.py            # BM25 index
│   │   ├── hybrid_search.py             # RRF merge
│   │   └── reranker.py                  # Cross-encoder reranking
│   │
│   ├── reasoning/                       # Phase 3
│   │   ├── prompts/
│   │   │   ├── qa_prompt.py             # Zero-shot / Few-shot / CoT templates
│   │   │   └── structured_prompt.py     # Prompt cho structured output
│   │   ├── llm_client.py                # OpenAI / Anthropic API wrapper (streaming)
│   │   ├── explainer.py                 # Giải thích điều khoản (CoT)
│   │   └── citation.py                  # Gắn + validate citations
│   │
│   ├── memory/                          # Phase 4
│   │   ├── buffer_memory.py             # Full history memory
│   │   ├── window_memory.py             # Sliding window memory
│   │   └── session_store.py             # Session management
│   │
│   ├── orchestrator/
│   │   └── router.py                    # Intent classification + flow routing
│   │
│   ├── risk_extraction/                 # Tính năng phụ (optional)
│   │   ├── extractor.py
│   │   ├── validator.py
│   │   └── risk_taxonomy.py
│   │
│   └── common/
│       ├── config.py
│       ├── logger.py
│       └── schemas.py
│
├── evaluation/                          # Phase 5
│   ├── retrieval_metrics.py             # Recall@k, MRR, Precision@k
│   ├── hallucination_check.py           # Citation faithfulness check
│   ├── llm_as_judge.py                  # Automated quality scoring
│   ├── adversarial_runner.py            # Chạy adversarial test set
│   └── reports/                         # Kết quả đánh giá (markdown/JSON)
│
├── app/                                 # Phase 6
│   ├── main.py                          # FastAPI backend
│   ├── api/
│   │   ├── chat.py                      # /chat endpoint (streaming)
│   │   ├── ingest.py                    # /ingest endpoint
│   │   └── eval.py                      # /eval endpoint
│   └── ui/                              # Streamlit / Gradio frontend
│       └── chat_ui.py
│
├── notebooks/
│   ├── 01_chunking_experiments.ipynb    # Thử nghiệm chunking strategies
│   ├── 02_embedding_comparison.ipynb    # So sánh embedding models
│   ├── 03_retrieval_evaluation.ipynb    # Phân tích Recall@k
│   └── 04_prompt_engineering.ipynb      # Thử nghiệm các kiểu prompt
│
├── tests/
│   ├── test_chunker.py
│   ├── test_retrieval.py
│   └── test_memory.py
│
└── scripts/
    ├── download_data.py                 # Tải dataset từ HuggingFace
    ├── build_index.py                   # Build FAISS + BM25 index
    └── generate_adversarial.py          # Tạo adversarial eval set
```

---

## 7. Rủi ro kỹ thuật và cách xử lý

| Rủi ro | Biểu hiện | Cách xử lý |
|---|---|---|
| Chunking cắt sai điều khoản | Câu trả lời thiếu ngữ cảnh | Test chunker trên nhiều loại văn bản, đo số chunk/điều khoản |
| Embedding không phân biệt điều khoản giống nhau | Retrieve sai chunk | Thực nghiệm so sánh 2 embedding model, đo Recall@k |
| Memory vượt context limit | Lỗi API khi hội thoại dài | Implement sliding window + monitor token count |
| Hallucination khi LLM bỏ qua grounding instruction | Citation không có trong context | Adversarial test + LLM-as-judge để phát hiện |
| Chi phí API cao khi eval lớn | Budget hết nhanh | Dùng model rẻ hơn (gpt-4o-mini) cho bulk eval, model mạnh cho demo |
