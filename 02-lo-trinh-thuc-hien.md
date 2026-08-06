# LegalDoc QA — Lộ trình Thực hiện Dự án

**Phiên bản:** 1.0
**Loại tài liệu:** Kế hoạch triển khai theo giai đoạn (Implementation Roadmap)

---

## Nguyên tắc tổ chức lộ trình

Dự án được chia thành **6 phase**, đi từ nền tảng dữ liệu → truy xuất → suy luận → cấu trúc hóa đầu ra → đảm bảo chất lượng → hoàn thiện sản phẩm. Mỗi phase có:
- **Mục tiêu** rõ ràng
- **Đầu vào / Đầu ra** cụ thể
- **Kỹ thuật áp dụng**
- **Tiêu chí hoàn thành (Definition of Done)**

---

## Phase 0 — Chuẩn bị & Thu thập dữ liệu

**Mục tiêu:** Có bộ dữ liệu tài liệu pháp lý tiếng Việt thực tế để làm việc xuyên suốt dự án.

### 0.1. Bộ dữ liệu tiếng Việt có sẵn (dùng làm nguồn chính)

Vì hệ thống làm bằng tiếng Việt, ưu tiên các nguồn sau — chủ yếu là văn bản quy phạm pháp luật (luật, nghị định, thông tư), dùng tốt cho việc luyện chunking theo điều khoản, semantic search và retrieval evaluation:

| Tên bộ dữ liệu | Nội dung | Dùng để |
|---|---|---|
| **vbpl-vn** (Hugging Face: `tmquan/vbpl-vn`) | Toàn bộ văn bản pháp luật từ Cơ sở dữ liệu Quốc gia về Pháp luật (vbpl.vn, Bộ Tư pháp), có cấu trúc phân cấp document → section → paragraph → sentence, chia theo trung ương và địa phương | Nguồn chính cho Phase 1 (ingestion, chunking theo điều khoản) |
| **YuITC/Vietnamese-Legal-Doc-Retrieval-Data** (Hugging Face) | Cặp câu hỏi — điều khoản liên quan (dạng question + context_list), đã có sẵn ground truth | Dùng trực tiếp cho Phase 2 (đánh giá Recall@k của retrieval) |
| **UTS_VLC** (Hugging Face: `undertheseanlp/UTS_VLC`) | Toàn văn Hiến pháp, Bộ luật, Luật do Quốc hội ban hành (1945–nay), định dạng Markdown sạch | Dùng cho semantic search / QA trên văn bản luật gốc |
| **vietnamese-legal-documents-dataset** (GitHub: `duyet/vietnamese-legal-documents-dataset`) | Dữ liệu QA/tóm tắt dạng hội thoại (system/user/assistant), có gắn loại văn bản (Nghị định, Thông tư...) | Dùng làm câu hỏi mẫu cho Phase 3 (giải thích điều khoản) |
| **vbpl-vn-legal-corpus** (Hugging Face: `Monmoonluna/vbpl-vn-legal-corpus`) | Quan hệ trích dẫn/sửa đổi giữa các văn bản luật (CITES, AMEND...) | Dùng mở rộng nếu muốn thêm tính năng tra cứu văn bản liên quan |
| **vietnamese_legal_corpus** (Hugging Face: `th1nhng0/vietnamese_legal_corpus`) | ~6GB văn bản pháp luật thô | Dùng làm corpus dự phòng nếu cần khối lượng lớn để test hiệu năng |

> Toàn bộ các bộ trên đều là văn bản pháp luật công khai, thuộc phạm vi được phép tiếp cận tự do theo quy định pháp luật Việt Nam về công khai văn bản quy phạm pháp luật — an toàn để sử dụng cho mục đích học tập/nghiên cứu.

### 0.2. Hạn chế cần lưu ý và cách bổ sung

Các bộ dữ liệu trên chủ yếu là **văn bản luật** (Luật, Nghị định, Thông tư), không phải **hợp đồng thương mại/NDA/hợp đồng lao động** — trong khi đồ án hướng đến rà soát hợp đồng. Cần bổ sung thêm:
- Mẫu hợp đồng thương mại, NDA, hợp đồng lao động, điều khoản dịch vụ công khai (từ các trang mẫu văn bản pháp lý, website tư vấn doanh nghiệp có đăng mẫu miễn phí)
- Điều khoản dịch vụ (Terms of Service) công khai của các nền tảng số tại Việt Nam — là văn bản công khai, hợp pháp để sử dụng
- Tự soạn 3–5 hợp đồng mẫu (ẩn danh hoàn toàn thông tin cá nhân/doanh nghiệp) mô phỏng các loại hợp đồng phổ biến, để chủ động kiểm soát được độ phức tạp và loại rủi ro cài vào

**Nguyên tắc bắt buộc:** không sử dụng hợp đồng thật có chứa thông tin cá nhân, số liệu tài chính, hoặc thông tin định danh doanh nghiệp chưa được ẩn danh.

### 0.3. Công việc cần thực hiện
- Tải và làm sạch dữ liệu từ các nguồn ở mục 0.1
- Thu thập/soạn bổ sung 5–10 mẫu hợp đồng thương mại theo mục 0.2, phân loại độ phức tạp: ngắn (dưới 5 trang), trung bình (10–20 trang), dài (trên 30 trang)
- Xác định trước một số câu hỏi mẫu và câu trả lời "chuẩn" (ground truth) để dùng làm bộ kiểm thử về sau — có thể tận dụng trực tiếp từ `YuITC/Vietnamese-Legal-Doc-Retrieval-Data`
- Xác định danh sách các loại rủi ro pháp lý phổ biến cần hệ thống nhận diện (vd: điều khoản đơn phương chấm dứt hợp đồng, điều khoản phạt vi phạm không cân xứng, điều khoản bảo mật thiếu rõ ràng...)

**Kỹ thuật/khái niệm áp dụng:** thiết kế bộ dữ liệu đánh giá (evaluation dataset), xác định ground truth, data anonymization.

**Tiêu chí hoàn thành:** có bộ dữ liệu tài liệu (luật + hợp đồng mẫu) + bộ câu hỏi/đáp mẫu + danh sách loại rủi ro, sẵn sàng dùng xuyên suốt các phase sau.

---

## Phase 1 — Xử lý & Cấu trúc hóa Tài liệu (Document Ingestion)

**Mục tiêu:** Biến tài liệu pháp lý thô thành dữ liệu có thể tìm kiếm ngữ nghĩa.

**Công việc cần thực hiện:**
- Trích xuất văn bản từ tài liệu, giữ lại thông tin cấu trúc (số điều khoản, tiêu đề mục, số trang)
- Thiết kế chiến lược chunking theo ranh giới ngữ nghĩa (theo điều khoản/khoản), không chunk cứng theo số ký tự
- Gán metadata cho từng đoạn: vị trí gốc, số điều khoản, loại điều khoản (nếu phân loại được)
- Sinh embedding cho từng đoạn văn bản
- Xây dựng đồng thời hai chỉ mục tìm kiếm: chỉ mục vector (semantic) và chỉ mục từ khóa (BM25)

**Kỹ thuật áp dụng:**
- Semantic chunking (chunking theo ranh giới ý nghĩa thay vì token cố định)
- Text embeddings
- Vector indexing (FAISS)
- Keyword indexing (BM25)

**Tiêu chí hoàn thành:** với bất kỳ tài liệu nào trong bộ dữ liệu Phase 0, hệ thống có thể chunk và index thành công, truy vấn thử bằng một câu hỏi đơn giản trả về đúng đoạn văn bản liên quan.

---

## Phase 2 — Truy xuất Thông tin Nâng cao (Advanced Retrieval)

**Mục tiêu:** Đảm bảo hệ thống tìm đúng điều khoản liên quan với độ chính xác cao, kể cả với câu hỏi diễn đạt khác cách viết trong hợp đồng.

**Công việc cần thực hiện:**
- Triển khai tìm kiếm lai (hybrid search): kết hợp kết quả từ semantic search và keyword search
- Triển khai tầng rerank để chấm điểm lại độ liên quan của các ứng viên trước khi đưa vào bước suy luận
- Thiết lập ngưỡng độ tin cậy: nếu không có ứng viên nào đạt ngưỡng, hệ thống phải trả lời "không tìm thấy" thay vì đoán
- Đánh giá độ chính xác truy xuất bằng bộ câu hỏi mẫu đã chuẩn bị ở Phase 0

**Kỹ thuật áp dụng:**
- Hybrid search (semantic + BM25)
- Reranking bằng cross-encoder
- Confidence thresholding
- Retrieval evaluation (đo lường bằng metric như Recall@k, Precision@k)

**Tiêu chí hoàn thành:** với bộ câu hỏi mẫu, hệ thống truy xuất đúng điều khoản liên quan ở tỷ lệ chấp nhận được (tự đặt mục tiêu, ví dụ ≥ 80% Recall@5); các câu hỏi không liên quan đến tài liệu phải bị từ chối đúng cách.

---

## Phase 3 — Suy luận & Giải thích Điều khoản (Reasoning Layer)

**Mục tiêu:** Từ các đoạn văn bản đã truy xuất, sinh ra câu trả lời dễ hiểu, có lập luận rõ ràng và có trích dẫn nguồn.

**Công việc cần thực hiện:**
- Thiết kế prompt theo phương pháp chain-of-thought: yêu cầu model xác định chủ thể, nghĩa vụ/quyền lợi, điều kiện áp dụng trước khi đưa ra diễn giải cuối cùng
- Thiết kế cơ chế bắt buộc trích dẫn nguồn (grounded citation) trong mọi câu trả lời
- Xử lý trường hợp câu hỏi nằm ngoài phạm vi tài liệu (out-of-context handling)
- So sánh chất lượng giải thích giữa prompt có chain-of-thought và không có, trên cùng bộ điều khoản phức tạp

**Kỹ thuật áp dụng:**
- Chain-of-Thought prompting
- Grounded generation / citation-based answering
- Prompt comparison & evaluation

**Tiêu chí hoàn thành:** với các điều khoản phức tạp trong bộ dữ liệu mẫu, câu trả lời của hệ thống dễ hiểu hơn rõ rệt so với văn bản gốc, và mọi câu trả lời đều có trích dẫn nguồn kiểm chứng được.

---

## Phase 4 — Trích xuất Rủi ro có Cấu trúc (Structured Risk Extraction)

**Mục tiêu:** Quét toàn bộ tài liệu và xuất ra bảng rủi ro có định dạng chuẩn, nhất quán, có thể kiểm tra tự động.

**Công việc cần thực hiện:**
- Thiết kế schema cố định cho mỗi rủi ro được phát hiện: vị trí điều khoản, loại rủi ro, mức độ nghiêm trọng, mô tả, khuyến nghị xử lý
- Thiết kế luồng quét tuần tự/song song qua toàn bộ điều khoản của tài liệu
- Triển khai cơ chế validate đầu ra theo schema; nếu model trả sai định dạng, tự động yêu cầu sinh lại
- Thiết kế cơ chế sắp xếp/ưu tiên hiển thị theo mức độ nghiêm trọng của rủi ro
- Kiểm thử trên danh sách loại rủi ro đã xác định ở Phase 0, đo tỷ lệ phát hiện đúng/sót/nhầm

**Kỹ thuật áp dụng:**
- Structured output generation (JSON schema có ràng buộc)
- Output validation & auto-retry
- Batch document scanning

**Tiêu chí hoàn thành:** hệ thống xuất được bảng rủi ro đầy đủ, đúng schema 100% (sau retry nếu cần), phát hiện được phần lớn các loại rủi ro đã định nghĩa trước trong bộ dữ liệu kiểm thử.

---

## Phase 5 — Đảm bảo Chất lượng & Chống Hallucination (QA & Trust Layer)

**Mục tiêu:** Đưa hệ thống đạt độ tin cậy đủ để dùng cho tài liệu pháp lý thật — đây là phase bắt buộc với sản phẩm thuộc domain nhạy cảm.

**Công việc cần thực hiện:**
- Xây dựng bộ kiểm thử đối kháng (adversarial test set): câu hỏi đánh lừa, câu hỏi ngoài phạm vi tài liệu, câu hỏi mơ hồ
- Đo tỷ lệ hallucination: số câu trả lời không có căn cứ trong tài liệu gốc
- Đánh giá chất lượng câu trả lời bằng phương pháp LLM-as-judge (dùng một model khác chấm điểm câu trả lời) kết hợp với đánh giá thủ công
- Tinh chỉnh ngưỡng độ tin cậy và cơ chế fallback dựa trên kết quả kiểm thử
- Viết disclaimer và giới hạn sử dụng rõ ràng cho sản phẩm

**Kỹ thuật áp dụng:**
- Adversarial testing
- Hallucination rate measurement
- LLM-as-judge evaluation
- Fallback mechanism design

**Tiêu chí hoàn thành:** hệ thống vượt qua bộ kiểm thử đối kháng ở mức chấp nhận được; các câu hỏi ngoài phạm vi đều bị từ chối đúng cách thay vì bịa câu trả lời.

---

## Phase 6 — Hoàn thiện Sản phẩm & Trình bày (Productization)

**Mục tiêu:** Đóng gói toàn bộ hệ thống thành sản phẩm có thể demo và trình bày chuyên nghiệp.

**Công việc cần thực hiện:**
- Ghép nối toàn bộ các phase thành luồng sản phẩm hoàn chỉnh: upload → hỏi đáp → quét rủi ro
- Chuẩn bị bộ demo với 2–3 tài liệu mẫu tiêu biểu (đơn giản, trung bình, phức tạp)
- Chuẩn bị tài liệu trình bày: mô tả bài toán, kiến trúc, kết quả đánh giá (số liệu Recall/Precision, tỷ lệ hallucination), giới hạn của sản phẩm
- Chuẩn bị phần "lessons learned" — những khó khăn kỹ thuật đã gặp và cách giải quyết, đây là phần quan trọng khi trình bày trong phỏng vấn/portfolio

**Kỹ thuật áp dụng:**
- Product packaging & demo storytelling
- Technical documentation

**Tiêu chí hoàn thành:** có một sản phẩm demo chạy được đầu-cuối, kèm tài liệu trình bày đầy đủ số liệu đánh giá, sẵn sàng đưa vào portfolio.

---

## Tổng quan tiến độ theo Phase

| Phase | Trọng tâm | Kỹ thuật chủ đạo |
|---|---|---|
| 0 | Chuẩn bị dữ liệu | Thiết kế evaluation dataset |
| 1 | Xử lý tài liệu | Semantic chunking, embeddings, indexing |
| 2 | Truy xuất | Hybrid search, reranking, confidence threshold |
| 3 | Suy luận | Chain-of-thought, grounded citation |
| 4 | Trích xuất rủi ro | Structured output, schema validation |
| 5 | Đảm bảo chất lượng | Adversarial testing, LLM-as-judge |
| 6 | Hoàn thiện | Productization, trình bày kết quả |

---

## Gợi ý về cách tiếp cận

- Nên đi **tuần tự** qua từng phase vì phase sau phụ thuộc trực tiếp vào chất lượng của phase trước (retrieval kém → reasoning không thể tốt, bất kể prompt viết hay đến đâu)
- Phase 5 (QA & chống hallucination) thường bị bỏ qua trong các đồ án thông thường nhưng lại là phần **phân biệt rõ nhất** một đồ án sinh viên với một sản phẩm đạt chuẩn thực tế — nên đầu tư thời gian tương xứng
- Luôn giữ lại số liệu đánh giá (Recall@k, tỷ lệ hallucination, tỷ lệ đúng schema...) qua từng phase để có thể kể câu chuyện "trước và sau khi cải tiến" khi trình bày sản phẩm
