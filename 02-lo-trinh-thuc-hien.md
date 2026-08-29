# LegalDoc QA — Lộ trình Thực hiện Dự án

**Phiên bản:** 2.0
**Loại tài liệu:** Kế hoạch triển khai theo giai đoạn (Implementation Roadmap)

---

## Nguyên tắc tổ chức lộ trình

Dự án chia thành **6 phase**, đi từ nền tảng dữ liệu → retrieval → reasoning → memory → đảm bảo chất lượng → hoàn thiện sản phẩm.

**Nguyên tắc xuyên suốt:**
- **Implement-first:** Tự viết từng module từ đầu, chỉ dùng high-level library sau khi đã tự làm được — để thực sự hiểu bên dưới hoạt động thế nào.
- **Measure everything:** Mọi cải tiến đều phải có số liệu trước/sau (Recall@k, latency, hallucination rate).
- **Tuần tự:** Phase sau phụ thuộc vào chất lượng phase trước — retrieval kém thì reasoning không thể tốt, dù prompt có hay đến đâu.

---

## Phase 0 — Chuẩn bị & Thu thập Dữ liệu

**Mục tiêu:** Có đủ dữ liệu, hiểu cấu trúc, sẵn sàng cho Phase 1.

**Kỹ năng luyện:** Thiết kế evaluation dataset, data exploration, ground truth annotation.

### Công việc cần làm

**0.1. Khám phá dữ liệu đã có:**
- Đọc và hiểu cấu trúc từng record trong `vbpl_sample.jsonl`: các trường `markdown`, `structure_json`, `legal_type`, `doc_type`, `num_sections` — đây là nguồn văn bản chính cho toàn bộ dự án.
- Viết notebook data exploration: thống kê phân bố loại văn bản, độ dài trung bình, số điều khoản trên mỗi văn bản.
- Tìm hiểu cấu trúc `retrieval_eval_train.jsonl`: hiểu các trường `question`, `context_list`, `relevant_passage_ids` — đây là ground truth để đánh giá retrieval.

**0.2. Tải thêm dữ liệu (nếu cần):**
- Cập nhật script download để tải thêm văn bản từ `tmquan/vbpl-vn`, tăng số lượng mẫu lên 500–1000.
- Cân nhắc tải dataset án lệ `tmquan/anle-toaan-gov-vn` — chứa vụ án thực tế, phong phú hơn về câu hỏi tình huống cụ thể.

**0.3. Tạo adversarial eval set:**
- Soạn 20–30 câu hỏi "bẫy" để kiểm tra khả năng từ chối của hệ thống, chia 3 loại:
  - *Out-of-scope:* Câu hỏi không liên quan đến bất kỳ nội dung nào trong corpus (vd: giá cả thị trường, thời tiết).
  - *Ambiguous:* Câu hỏi dùng đại từ không rõ ràng, không đủ ngữ cảnh để trả lời chính xác.
  - *Trick:* Hỏi về điều khoản không tồn tại hoặc số hiệu văn bản sai.
- Lưu vào `data/eval/adversarial_eval.jsonl`, mỗi câu kèm nhãn `expected_behavior: "refuse"`.

**Tiêu chí hoàn thành:**
- [x] Hiểu được cấu trúc của cả 3 dataset (vbpl, retrieval_eval, adversarial)
- [x] Có notebook data exploration với thống kê cơ bản
- [x] `adversarial_eval.jsonl` có ít nhất 20 câu hỏi với nhãn rõ ràng

---

## Phase 1 — Xử lý & Cấu trúc hóa Tài liệu (Document Ingestion)

**Mục tiêu:** Biến văn bản pháp luật thô thành dữ liệu có thể tìm kiếm ngữ nghĩa.

**Kỹ năng luyện:** Tokenization, Semantic chunking, Text embeddings, FAISS indexing, Cosine similarity.

### Công việc cần làm

**1.1. Làm sạch dữ liệu & chuẩn hóa metadata:**
- Đọc dữ liệu raw từ `data/raw/laws/vbpl_sample.jsonl`, không ghi đè file raw.
- Loại bỏ văn bản không có `markdown`, nội dung quá ngắn, hoặc lỗi parse nghiêm trọng.
- Deduplicate theo `item_id`, `source_url`, `text_hash`; nếu trùng, giữ bản ghi có metadata đầy đủ hơn.
- Deduplicate bổ sung theo tổ hợp `doc_number + issue_date + issuing_authority + doc_type` để tránh giữ nhiều bản ghi đại diện cho cùng một văn bản.
- Chuẩn hóa các trường phân loại: `doc_type`, `legal_type`, `legal_area`.
- Chuẩn hóa tên cơ quan ban hành `issuing_authority` để gộp các biến thể viết hoa/viết thường hoặc khác cách ghi.
- Chuẩn hóa thời gian ban hành: `issue_date`, `year`; đánh dấu giá trị thiếu hoặc bất thường.
- Gắn các trường kiểm soát hiệu lực: `status`, `is_effective`, `effective_date`, `expiry_date`; nếu chưa xác định được hiệu lực thì đặt `status = "unknown"` và `is_effective = null`.
- Gắn trường `valid_for_index` để quyết định văn bản có được đưa vào RAG index hay không.
- Chính sách index tạm thời: ưu tiên văn bản còn hiệu lực; nếu chưa rõ hiệu lực thì cho phép index nhưng giữ `status = "unknown"`; không index văn bản đã biết hết hiệu lực trừ khi tạo index riêng cho tra cứu lịch sử.
- Nếu có văn bản hợp nhất, ưu tiên đưa văn bản hợp nhất vào index thay cho văn bản gốc đã bị sửa đổi nhiều lần.
- Không dùng `doc_number` làm khóa định danh duy nhất vì số hiệu có thể trùng giữa cơ quan hoặc năm khác nhau.
- Lưu output vào `data/processed/clean_documents.jsonl`, mỗi dòng là một văn bản sạch đã sẵn sàng cho chunking.
- Ghi log thống kê trước/sau: số văn bản raw, số văn bản bị loại, số văn bản trùng, phân bố `doc_type`, phân bố `status`, số văn bản `valid_for_index = true`.

**1.2. Xây dựng Document Extractor:**
- Đọc và parse dữ liệu từ file JSONL (vbpl), file TXT và tùy chọn file PDF.
- Trích xuất các trường quan trọng: nội dung văn bản (`markdown`), tiêu đề, loại văn bản, nguồn gốc.
- Đảm bảo output chuẩn hóa: mỗi tài liệu là một dict với `doc_id`, `text`, `title`, `legal_type`, `source_url`.

**1.3. Xây dựng Semantic Chunker — Module quan trọng nhất Phase 1:**
- Thiết kế chiến lược chunking theo ranh giới điều khoản, không cắt cứng theo số ký tự.
- Dùng biểu thức chính quy (Regex) để nhận diện ranh giới: `Điều X.`, `Chương X`, `Khoản X`.
- Chiến lược cơ bản: cắt tại mỗi "Điều", gộp các Khoản vào cùng Điều tương ứng, tránh chunk quá ngắn (< 100 ký tự) hoặc quá dài (> 2000 ký tự).
- Mỗi chunk đầu ra phải có `chunk_id`, `text`, `doc_id`, `article_ref` (tham chiếu điều khoản gốc).
- Mỗi chunk phải kế thừa metadata pháp lý từ document gốc: `doc_type`, `legal_type`, `doc_number`, `issue_date`, `year`, `status`, `is_effective`, `source_url`.
- Thực nghiệm trong notebook: thử ít nhất 3 chiến lược chunking khác nhau, đo và so sánh số chunk/doc, tỷ lệ chunk có đủ ngữ cảnh.

**1.4. Xây dựng Document Embedder:**
- Tích hợp SentenceTransformer để sinh vector embedding cho từng chunk.
- Hỗ trợ batch encoding để tối ưu tốc độ.
- Build FAISS index từ tập embedding, lưu index xuống disk để tái sử dụng.
- Thực nghiệm so sánh hai embedding model: `keepitreal/vietnamese-sbert` (chuyên tiếng Việt) vs `paraphrase-multilingual-MiniLM-L12-v2` (đa ngôn ngữ nhẹ hơn). Metric so sánh: thời gian encode, kích thước index, chất lượng nearest-neighbor trên 10 câu test thủ công.

**1.5. Xây dựng BM25 Keyword Index:**
- Dùng thư viện `rank-bm25` để xây dựng chỉ mục từ khóa trên toàn bộ corpus chunk.
- Hỗ trợ lưu và load index từ disk.

**1.6. Script chạy toàn bộ pipeline Ingestion:**
- Chạy end-to-end: từ file JSONL thô → clean documents → chunks → FAISS index + BM25 index + Document Store.
- Chỉ chunk và index các văn bản có `valid_for_index = true`.
- Log đầu ra: tổng số chunk, thời gian xử lý, kích thước index.

**Tiêu chí hoàn thành:**
- [ ] Có `data/processed/clean_documents.jsonl` sau bước làm sạch và chuẩn hóa metadata
- [ ] Có chính sách `valid_for_index` để không đưa trực tiếp toàn bộ raw data vào index
- [ ] Deduplicate được văn bản trùng theo ID, URL, hash nội dung và tổ hợp metadata pháp lý
- [ ] Chunk store giữ được metadata hiệu lực và nguồn của document gốc
- [ ] Pipeline ingestion chạy thành công trên toàn bộ `vbpl_sample.jsonl`
- [ ] Tự implement và hiểu cosine similarity từ numpy trước khi dùng FAISS
- [ ] Notebook so sánh 2 embedding model với kết luận rõ ràng
- [ ] Query thử thủ công: "Điều kiện để ký hợp đồng lao động" → kết quả trả về phải liên quan

---

## Phase 2 — Truy xuất Thông tin Nâng cao (Advanced Retrieval)

**Mục tiêu:** Đảm bảo hệ thống tìm đúng điều khoản liên quan, kể cả khi câu hỏi diễn đạt khác cách viết trong văn bản gốc.

**Kỹ năng luyện:** Hybrid search, BM25, Cross-encoder reranking, Recall@k evaluation, Confidence thresholding.

### Công việc cần làm

**2.1. Xây dựng Hybrid Search (Reciprocal Rank Fusion):**
- Kết hợp kết quả từ semantic search (FAISS) và keyword search (BM25) thành một ranked list thống nhất.
- Dùng **Reciprocal Rank Fusion (RRF)**: cộng điểm theo thứ hạng (rank), không theo giá trị điểm tuyệt đối — tránh vấn đề scale không đồng nhất giữa 2 phương pháp.
- Kết quả sau merge là top-20 ứng viên để đưa vào bước rerank.

**2.2. Xây dựng Cross-Encoder Reranker:**
- Dùng cross-encoder (vd: `ms-marco-MiniLM-L-6-v2`) để chấm điểm lại từng cặp (query, chunk) chính xác hơn so với cosine similarity.
- Chọn top 3–5 chunk có điểm cao nhất để đưa vào Reasoning Layer.
- Nếu điểm cao nhất vẫn dưới ngưỡng → đánh dấu "không tìm thấy thông tin liên quan".

**2.3. Xây dựng Retrieval Evaluation:**
- Implement các hàm tính metric: `Recall@k`, `Mean Reciprocal Rank (MRR)`, `Precision@k`.
- Load `retrieval_eval_test.jsonl`, chạy 4 cấu hình và so sánh:

| Cấu hình | Recall@1 | Recall@5 | MRR | Latency |
|---|---|---|---|---|
| Semantic only | ? | ? | ? | ? |
| BM25 only | ? | ? | ? | ? |
| Hybrid (RRF) | ? | ? | ? | ? |
| Hybrid + Rerank | ? | ? | ? | ? |

*Mục tiêu: Hybrid + Rerank đạt Recall@5 ≥ 80%.*

**2.4. Thiết lập Confidence Threshold:**
- Vẽ phân bố (distribution) của rerank scores trên toàn bộ test set.
- Chọn ngưỡng sao cho câu OOD trong `adversarial_eval.jsonl` bị từ chối đúng ≥ 90%.

**Tiêu chí hoàn thành:**
- [ ] Bảng so sánh 4 cấu hình retrieval với số liệu thực tế
- [ ] Hybrid + Rerank đạt Recall@5 ≥ 80%
- [ ] Confidence threshold hoạt động: ≥ 90% câu OOD bị từ chối
- [ ] Notebook phân tích với biểu đồ phân bố điểm và đường threshold

---

## Phase 3 — Suy luận & Giải thích Điều khoản (Reasoning Layer)

**Mục tiêu:** Từ chunks đã retrieve, sinh câu trả lời rõ ràng, có lập luận và trích dẫn nguồn.

**Kỹ năng luyện:** Prompt engineering (zero-shot, few-shot, CoT), Structured output, Streaming API, Grounded citation.

### Công việc cần làm

**3.1. Xây dựng LLM Client (hỗ trợ Streaming):**
- Wrapper gọi OpenAI / Anthropic API, hỗ trợ cả hai chế độ: trả về toàn bộ response và streaming từng token.
- Hỗ trợ gọi có structured output — yêu cầu model trả JSON theo Pydantic schema, validate ngay khi nhận được response.

**3.2. Thực nghiệm Prompt Engineering:**
Với **cùng một câu hỏi** và **cùng chunks retrieval**, thử 4 kiểu prompt và đánh giá thủ công trên 10 câu test:
- **Zero-shot:** Chỉ cung cấp context và câu hỏi, không có ví dụ mẫu.
- **Few-shot:** Kèm 2–3 ví dụ câu hỏi–trả lời mẫu trước câu hỏi thật.
- **Chain-of-Thought:** Yêu cầu model lập luận từng bước: xác định đối tượng điều khoản → quyền/nghĩa vụ → điều kiện áp dụng → tóm tắt ngôn ngữ phổ thông.
- **Structured output:** Yêu cầu trả về JSON với các trường `answer`, `confidence`, `sources`.

Đánh giá thủ công mỗi kiểu theo 3 tiêu chí: clarity (1–5), accuracy (1–5), citation quality (1–5).

**3.3. Xây dựng Grounded Citation — Cơ chế chống hallucination chính:**
- System prompt bắt buộc model chỉ dùng thông tin trong chunks được cung cấp, không dùng kiến thức bên ngoài.
- Mọi điểm trong câu trả lời phải kèm `[Nguồn: chunk_id]`.
- Sau khi nhận response: parse citation, kiểm tra xem `chunk_id` được cite có thực sự nằm trong danh sách chunks đã retrieve không. Nếu không → phát hiện hallucination.

**3.4. Xây dựng Legal Explainer:**
- Module tập trung, nhận vào: câu hỏi, danh sách chunks, lịch sử hội thoại → trả về câu trả lời hoàn chỉnh với citation.
- Assemble prompt đầy đủ: system prompt grounding + chunks context + lịch sử memory + câu hỏi hiện tại.

**3.5. Xây dựng Streaming Endpoint (FastAPI preview):**
- Endpoint `/chat/stream` trả response dạng Server-Sent Events (SSE), token-by-token.
- Cải thiện UX đáng kể so với chờ toàn bộ response.

**Tiêu chí hoàn thành:**
- [ ] Notebook so sánh 4 kiểu prompt với bảng đánh giá thủ công
- [ ] Citation validation phát hiện được khi model cite source không có trong context
- [ ] Streaming endpoint trả token real-time
- [ ] 10 câu hỏi test thủ công: mọi câu trả lời đều có citation hợp lệ

---

## Phase 4 — Hội thoại có Bộ nhớ (Conversational Memory)

**Mục tiêu:** Hệ thống nhớ được ngữ cảnh hội thoại, xử lý được câu hỏi follow-up không cần nhắc lại context.

**Kỹ năng luyện:** Memory patterns (Buffer, Window), Session management, Context window management, Query resolution.

### Công việc cần làm

**4.1. Implement Buffer Memory:**
- Giữ toàn bộ lịch sử hội thoại của session — đơn giản nhất nhưng nhanh vượt context limit khi hội thoại dài.
- Theo dõi tổng số token đang dùng để cảnh báo khi gần ngưỡng.

**4.2. Implement Window Memory:**
- Chỉ giữ k exchanges gần nhất (mặc định k=5) — trade-off giữa nhớ ngữ cảnh và tiết kiệm token.
- So sánh với Buffer Memory trên các kịch bản hội thoại dài để rút ra kết luận về khi nào nên dùng loại nào.

**4.3. Implement Session Store:**
- Quản lý nhiều session người dùng đồng thời, mỗi session có memory riêng và tài liệu đang được hỏi riêng.
- Hỗ trợ tạo mới, lấy, và xóa session.

**4.4. Xử lý Follow-up Queries:**
- Khi câu hỏi chứa đại từ mơ hồ ("điều đó", "quy định trên", "nó"...), dùng LLM để mở rộng thành câu hỏi đầy đủ có ngữ cảnh từ lịch sử hội thoại trước khi đưa vào Retrieval Layer.
- Ví dụ: "Còn điều khoản đó thì sao?" → "Điều 15 về quyền đơn phương chấm dứt hợp đồng áp dụng trong điều kiện nào?"

**4.5. Test hội thoại multi-turn:**
- Thiết kế 5 kịch bản hội thoại 3–5 lượt, kiểm tra follow-up queries được resolve đúng, context window không tràn, câu trả lời sau nhất quán với câu trước.

**Tiêu chí hoàn thành:**
- [ ] Cả 2 chiến lược memory (Buffer, Window) được implement và có thể so sánh
- [ ] Session management hoạt động đồng thời với nhiều session
- [ ] 5 kịch bản hội thoại multi-turn vượt qua

---

## Phase 5 — Đảm bảo Chất lượng & Chống Hallucination (QA Layer)

**Mục tiêu:** Đưa hệ thống đạt độ tin cậy đủ để dùng cho văn bản pháp lý thật.

**Kỹ năng luyện:** Adversarial testing, Hallucination rate measurement, LLM-as-Judge evaluation.

### Công việc cần làm

**5.1. Đo Hallucination Rate:**
- Với mỗi câu trả lời: kiểm tra từng điểm trong response có được hỗ trợ bởi chunks đã cite không.
- Dùng LLM thứ hai (LLM-as-judge) để chấm điểm faithfulness — model không biết câu trả lời được sinh ra như thế nào, chỉ đánh giá dựa trên nguồn.

**5.2. Implement LLM-as-Judge:**
- Dùng một LLM độc lập để chấm điểm câu trả lời theo 3 tiêu chí:
  - **Faithfulness (0–5):** Câu trả lời có bám sát tài liệu gốc không, hay tự bịa?
  - **Relevance (0–5):** Câu trả lời có đúng vào câu hỏi không?
  - **Clarity (0–5):** Câu trả lời có dễ hiểu với người không chuyên pháp lý không?
- Ghi điểm và lý do vào báo cáo.

**5.3. Chạy Full Evaluation Pipeline:**
- Load `retrieval_eval_test.jsonl` → chạy toàn bộ RAG pipeline → thu thập câu trả lời → đo Recall@5, hallucination rate, average faithfulness/relevance/clarity.
- Load `adversarial_eval.jsonl` → đo tỷ lệ câu OOD bị từ chối đúng.

**5.4. Tổng hợp báo cáo chất lượng:**

| Metric | Mục tiêu | Kết quả thực tế |
|---|---|---|
| Recall@5 (retrieval) | ≥ 80% | ? |
| Hallucination rate | ≤ 10% | ? |
| Faithfulness score (avg) | ≥ 4.0/5 | ? |
| OOD rejection rate | ≥ 90% | ? |
| Avg response latency | ≤ 5s | ? |

**5.5. Vòng cải tiến:**
- Phân tích lỗi: hệ thống hay sai ở loại câu hỏi nào, ở bước nào (retrieval hay reasoning)?
- Thực hiện ít nhất 1 vòng cải tiến có đo lường (vd: điều chỉnh threshold, thêm few-shot vào prompt, thay embedding model) và ghi lại số liệu trước/sau.

**Tiêu chí hoàn thành:**
- [ ] Tất cả metric trong bảng được điền với số liệu thực tế
- [ ] Báo cáo có phần error analysis: loại câu hỏi nào hệ thống hay sai
- [ ] Ít nhất 1 vòng cải tiến có số liệu trước/sau rõ ràng
- [ ] Báo cáo lưu vào `evaluation/reports/`

---

## Phase 6 — Hoàn thiện Sản phẩm & Trình bày (Productization)

**Mục tiêu:** Đóng gói thành sản phẩm có thể demo và trình bày chuyên nghiệp trong portfolio/phỏng vấn.

**Kỹ năng luyện:** FastAPI, Streamlit/Gradio, API design, Streaming, Product storytelling.

### Công việc cần làm

**6.1. Build FastAPI Backend:**
- Các endpoint cần có: `/ingest` (upload tài liệu), `/chat` (Q&A thường), `/chat/stream` (Q&A streaming), `/session/{id}` (lấy/xóa lịch sử), `/health` (kiểm tra trạng thái).
- Thiết kế API schema rõ ràng, có validation.

**6.2. Build Chat UI:**
- Dùng Streamlit (đơn giản, phù hợp portfolio):
  - Text input để đặt câu hỏi
  - Hiển thị câu trả lời với citations được highlight
  - Sidebar: chọn tài liệu, xem lịch sử session
  - "Nguồn trích dẫn" dạng expandable dưới mỗi câu trả lời

**6.3. Chuẩn bị Demo Scenarios:**
Chuẩn bị sẵn 3 kịch bản demo có câu hỏi và câu trả lời mong đợi:
- *Demo 1 — Tra cứu đơn giản:* Câu hỏi về một điều khoản cụ thể trong corpus.
- *Demo 2 — Multi-turn:* Hỏi về một điều → hỏi tiếp về điều kiện áp dụng → hỏi về ngoại lệ.
- *Demo 3 — Robustness:* Câu hỏi ngoài phạm vi → hệ thống từ chối đúng cách với giải thích lịch sự.

**6.4. Viết README.md:**
- Mô tả bài toán và tại sao nó quan trọng.
- Sơ đồ kiến trúc hệ thống.
- Kết quả evaluation (copy từ Phase 5 — đây là phần quan trọng nhất).
- Hướng dẫn cài đặt và chạy.
- **Phần "Lessons Learned":** Những khó khăn kỹ thuật đã gặp và cách giải quyết — phần này thường được hỏi nhiều nhất trong phỏng vấn.

**Tiêu chí hoàn thành:**
- [ ] Demo end-to-end chạy được: upload tài liệu → chat → xem citations
- [ ] Streaming hoạt động trên UI
- [ ] README có đầy đủ số liệu evaluation
- [ ] Có thể giải thích bất kỳ quyết định kỹ thuật nào trong phỏng vấn

---

## Tổng quan tiến độ theo Phase

| Phase | Trọng tâm | Kỹ thuật chủ đạo | Milestone |
|---|---|---|---|
| 0 | Chuẩn bị dữ liệu | Data exploration, ground truth design | Có adversarial eval set |
| 1 | Xử lý tài liệu | Tokenization, Embeddings, FAISS, BM25 | Index build thành công |
| 2 | Truy xuất | Hybrid search, Cross-encoder, Recall@k | Recall@5 ≥ 80% |
| 3 | Suy luận | Prompt engineering, CoT, Streaming, Citations | Demo Q&A cơ bản hoạt động |
| 4 | Memory | Buffer/Window memory, Session management | Multi-turn conversation |
| 5 | Đảm bảo chất lượng | Adversarial testing, LLM-as-Judge | Báo cáo eval đầy đủ |
| 6 | Hoàn thiện | FastAPI, Streamlit, Product packaging | Demo end-to-end |

---

## Gợi ý cách tiếp cận

- **Bắt đầu từ notebook, chuyển sang module sau:** Prototype mọi thứ trong `.ipynb` trước, khi logic ổn định mới chuyển thành `.py` module — tránh debug phức tạp khi vừa implement vừa refactor.
- **Phase 5 là phần quan trọng nhất khi trình bày:** Sinh viên thường bỏ qua evaluation, nhưng đây chính là phần phân biệt một đồ án tốt. Số liệu Recall@k, hallucination rate, LLM-as-judge score là những gì nhà tuyển dụng muốn thấy.
- **Luôn giữ số liệu trước/sau mỗi cải tiến:** "Sau khi thêm reranking, Recall@5 tăng từ 62% lên 81%" — câu này có giá trị hơn rất nhiều so với "tôi đã implement reranking".
- **Tự tay implement trước, dùng LangChain/LlamaIndex sau:** Nếu dùng framework ngay từ đầu, bạn sẽ không biết tại sao hệ thống hoạt động (hoặc không hoạt động). Implement thủ công ít nhất 1 lần mỗi component.
