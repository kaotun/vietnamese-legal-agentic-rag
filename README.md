# HỆ THỐNG TRỢ LÝ HỎI ĐÁP PHÁP LUẬT VIỆT NAM (LEGAL QA SYSTEM)

> Trợ lý AI tra cứu, phân tích và giải đáp pháp luật Việt Nam dựa trên kiến trúc Agentic RAG đa vòng lặp, tích hợp động cơ quy tắc pháp lý (Legal Rule Engine) và khung thẩm định 4 lớp, có khả năng triển khai hoàn toàn cục bộ (Local Edge / On-Premise).

[![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-05998b?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![LangGraph](https://img.shields.io/badge/LangGraph-12_Nodes_Workflow-f26522?logo=langchain&logoColor=white)](https://www.langchain.com/langgraph)
[![React](https://img.shields.io/badge/React-Vite-61DAFB?logo=react&logoColor=black)](https://vitejs.dev/)
[![VectorDB](https://img.shields.io/badge/VectorDB-pgvector_HNSW-800080?logo=postgresql&logoColor=white)](https://github.com/pgvector/pgvector)
[![RuleEngine](https://img.shields.io/badge/Rule_Engine-Data--Driven_PostgreSQL-0ea5e9?logo=postgresql&logoColor=white)](backend/docker/postgres/init.sql)
[![LLM](https://img.shields.io/badge/LLM-Qwen_2.5_(Ollama)-000000?logo=ollama&logoColor=white)](https://ollama.com/)

---

## 1. NGUYÊN TẮC THIẾT KẾ CỐT LÕI

1. **Phân định "Relevant" và "Applicable":** Tài liệu tương đồng ngữ nghĩa chưa chắc áp dụng được cho chủ thể cụ thể. Hệ thống thiết lập Legal Applicability Gate nhằm chặn sớm các trường hợp loại trừ trách nhiệm (ví dụ: chưa đủ tuổi chịu trách nhiệm hình sự).
2. **Data-Driven Rule Engine:** Các quy tắc về độ tuổi, điều kiện áp dụng, thời hiệu và chế tài được lưu trữ dưới dạng schema JSON trong PostgreSQL (`legal_applicability_rules`), cho phép cập nhật luật mà không sửa mã nguồn.
3. **Phát hiện dữ kiện định tính (Fact Ambiguity):** Tự động nhận diện các tình tiết chưa đủ căn cứ định khung pháp lý (như "đánh bạn trọng thương" cần kết luận giám định % thương tật chính thức).
4. **Cơ sở tri thức có cấu trúc:** Kho dữ liệu 13.744 điều luật chuẩn hóa, đi kèm danh mục văn bản (Registry) và phân loại ngành luật (Taxonomy) để thẩm tra số hiệu và tên luật.
5. **Trích dẫn có căn cứ (Grounded Citations):** Câu trả lời tuân theo cấu trúc 4 phần chuẩn mực (Kết luận -> Căn cứ pháp lý -> Phân tích áp dụng -> Hướng dẫn thực tiễn), đối chiếu trực tiếp với tài liệu truy hồi qua Citation Guard.
6. **Vận hành cục bộ và bảo mật dữ liệu:** Hỗ trợ suy luận hoàn toàn offline thông qua Ollama (LLM + Embedding), PostgreSQL pgvector và BM25.

---

## 2. KIẾN TRÚC HỆ THỐNG

### Sơ đồ Điều phối Agentic RAG & Legal Rule Engine Gate

```mermaid
flowchart TD
    %% TẦNG GIAO DIỆN & API GATEWAY
    Client["Client / Người dùng (Web UI & Voice AI)"] --> Gateway["API Gateway (FastAPI)"]
    Gateway <--> Sessions[("Session Storage<br/>Multi-Session JSON")]
    Gateway --> START([START])

    %% TẦNG ĐIỀU PHỐI LANGGRAPH
    subgraph LangGraph ["HỆ THỐNG ĐIỀU PHỐI AGENTIC RAG (LANGGRAPH 12 NODES)"]
        START --> Router{"1. Intent Router"}
        Checkpointer[("MemorySaver")] -.-> Router

        Router -->|smalltalk| Smalltalk["2. Smalltalk Node<br/>(Chào hỏi xã giao)"]
        Router -->|out_of_scope| OutScope["3. Out-of-Scope Node<br/>(Từ chối ngoài phạm vi)"]
        Router -->|legal_query| ApplicabilityValidator{"4. Legal Applicability Validator<br/>(Fact Extractor + Rule Engine Gate)"}

        %% CHỐT CHẶN ĐIỀU KIỆN ÁP DỤNG (HARD GATE)
        subgraph HardGate ["CHỐT CHẶN ĐIỀU KIỆN CHỦ THỂ & HIỆU LỰC (HARD GATE)"]
            ApplicabilityValidator -->|BLOCKED<br/>Chưa đủ tuổi / Loại trừ TNHS| Inapplicability["5. Inapplicability Explainer Node<br/>(STOP PUNISHMENT PATH)<br/>Khẳng định không bị phạt tù<br/>Chuyển hướng Dân sự & Giáo dưỡng"]
        end

        %% LUỒNG RAG CHÍNH THỨC
        ApplicabilityValidator -->|ALLOWED / REQUIRE_CONDITION| Decompose["6. Decompose Node<br/>(Sửa chính tả, Tách vi phạm, HyDE)"]

        %% VÒNG LẶP 1: CRAG LOOP
        subgraph Stage_Retrieval ["GIAI ĐOẠN 1: TRUY HỒI & CORRECTIVE RAG (CRAG LOOP)"]
            direction TB
            Decompose --> Retrieve["7. Retrieve Node<br/>(BM25 + pgvector + Rerank)"]
            Retrieve --> GradeDocs{"8. Grade Docs<br/>(Thẩm định tài liệu)"}
            
            GradeDocs -->|Chưa đạt| RewriteQuery["9. Rewrite Query Node<br/>(Mở rộng & Viết lại thuật ngữ)"]
            RewriteQuery -->|Truy hồi lại| Retrieve
        end

        %% VÒNG LẶP 2: SELF-RAG LOOP
        subgraph Stage_Generation ["GIAI ĐOẠN 2: LẬP LUẬN & SELF-CORRECTION (SELF-RAG LOOP)"]
            direction TB
            GradeDocs -->|Đạt chuẩn| Generate["10. Generate Node<br/>(Smart Windowing + LLM 4 phần)"]
            Generate --> CitationGuard{"11. Citation Guard<br/>(Kiểm định trích dẫn)"}
            
            CitationGuard -->|Có ảo giác| SelfCorrect["12. Self-Correct Node<br/>(Phản hồi yêu cầu sửa)"]
            SelfCorrect -->|Sinh lại| Generate
        end

        Inapplicability --> END([END])
        CitationGuard -->|Đạt kiểm tra citation| END
        Smalltalk --> END
        OutScope --> END
    end

    %% TẦNG DỮ LIỆU PHÁP LÝ & CƠ SỞ TRI THỨC CẤU TRÚC
    subgraph Storage ["TẦNG DỮ LIỆU & TRI THỨC PHÁP LÝ (STRUCTURED KNOWLEDGE BASE)"]
        DB_Records[("PostgreSQL 17 (pgvector)<br/>13,744 bản ghi luật")]
        DB_Registry[("Legal Registry & Taxonomy<br/>Registry/taxonomy bổ sung")]
        DB_Rules[("Applicability Rules Base<br/>Quy tắc điều kiện có versioning")]
        BM25Cache[("BM25 Okapi Index<br/>bm25_index_cache.json")]
    end

    ApplicabilityValidator <-->|Đọc Rule Schema & Điều kiện| DB_Rules
    ApplicabilityValidator <-->|Thẩm tra số điều & tên luật| DB_Registry
    Retrieve <-->|Dense Search| DB_Records
    Retrieve <-->|Sparse Search| BM25Cache

    END --> Output["Phản hồi hoàn chỉnh gửi Client<br/>(Cấu trúc 4 phần chuẩn + Giọng nói TTS)"]

    %% STYLING
    classDef clientStyle fill:#0f172a,stroke:#38bdf8,stroke-width:2px,color:#f8fafc;
    classDef graphStyle fill:#1e1b4b,stroke:#818cf8,stroke-width:2px,color:#f8fafc;
    classDef gateStyle fill:#7c2d12,stroke:#f97316,stroke-width:2px,color:#f8fafc;
    classDef ragStyle fill:#14532d,stroke:#4ade80,stroke-width:2px,color:#f8fafc;
    classDef loopStyle fill:#4a044e,stroke:#f472b6,stroke-width:2px,color:#f8fafc;
    classDef dbStyle fill:#1e293b,stroke:#94a3b8,stroke-width:2px,color:#f8fafc;

    class Client,Gateway,Output clientStyle;
    class START,Router,Smalltalk,OutScope,Checkpointer,END graphStyle;
    class ApplicabilityValidator,Inapplicability gateStyle;
    class Decompose,Retrieve,Generate ragStyle;
    class GradeDocs,RewriteQuery,CitationGuard,SelfCorrect loopStyle;
    class DB_Records,DB_Registry,DB_Rules,BM25Cache,Sessions dbStyle;
```

### Tóm tắt Kỹ thuật Backend

1. **Khung thẩm định 4 lớp (4-Layer Validation):**
   - **Lớp 1 (Reference Validator):** Thẩm tra số hiệu Điều và tên Văn bản qua `LegalRegistry` và `PremiseChecker`.
   - **Lớp 2 (Fact Validator & Ambiguity):** Bóc tách chủ thể, độ tuổi, hành vi, tỷ lệ thương tật; phát hiện mô tả định tính thiếu số liệu y tế.
   - **Lớp 3 (Applicability Gate):** Thực thi 8 danh mục quy tắc trong CSDL (`legal_applicability_rules`). Chặn luồng phạt tù đối với người chưa đủ tuổi chịu trách nhiệm hình sự (Điều 12 BLHS) và chuyển sang nhánh giải thích dân sự/giáo dưỡng.
   - **Lớp 4 (Evidence Validator & Citation Guard):** Thẩm định tài liệu truy hồi (CRAG) và kiểm định căn cứ trích dẫn trong câu trả lời (Self-RAG).

2. **LangGraph StateGraph (12 Nodes, 2 Vòng lặp):**
   - **CRAG Loop:** `GradeDocs` -> `RewriteQuery` -> `Retrieve` (tối đa 2 lần) khi tài liệu chưa đạt yêu cầu.
   - **Self-RAG Loop:** `CitationGuard` -> `SelfCorrect` -> `Generate` (tối đa 2 lần) khi phát hiện trích dẫn sai hoặc thiếu căn cứ.

3. **Advanced Hybrid Retrieval Engine:**
   - **Hợp nhất RRF:** Kết hợp Dense Vector (pgvector HNSW) và Sparse Search (BM25 Okapi trên RAM) theo công thức Reciprocal Rank Fusion ($k=60$) để lấy Top 15 ứng viên.
   - **Tái xếp hạng (Reranker):** Smart Fallback kết hợp Cross-Encoder FlashRank (`ms-marco-MiniLM-L-12-v2`) lọc Top 3-5 điều luật chính xác nhất.
   - **Smart Windowing:** Tự động gom thêm các Khoản chế tài bổ sung (tước GPLX, tạm giữ phương tiện) liên quan đến hành vi vi phạm.

---

## 3. TÍNH NĂNG CỐT LÕI

- **Thẩm định nghiệp vụ & Chốt chặn pháp lý:** Tự động suy luận độ tuổi từ năm sinh hoặc lớp học, phân định vai trò đồng phạm (người xúi giục vs. người thực hành), đối chiếu hiệu lực thời gian của văn bản và đính chính các câu hỏi chứa tiền đề sai.
- **Truy hồi lai & Tái xếp hạng:** Kết hợp tìm kiếm ngữ nghĩa và từ khóa qua RRF; sinh văn bản pháp lý giả định (HyDE); tách câu hỏi phức hợp thành các truy vấn đơn lẻ để tìm kiếm toàn diện.
- **Sinh câu trả lời chuẩn mực & Chống ảo giác:** Trình tạo prompt 4 phần (Kết luận, Căn cứ pháp lý, Chi tiết áp dụng, Lưu ý thực tiễn); tích hợp Citation Guard tự động phát hiện số điều bịa đặt và kích hoạt sinh lại có định hướng.
- **Tiện ích giao diện & Vận hành:** Hỗ trợ Streaming SSE thời gian thực; quản lý đa phiên hội thoại; tra cứu nguyên văn điều luật trực tiếp trên giao diện; tích hợp giọng nói Voice AI (Edge-TTS và Local TTS nội bộ).

---

## 4. CẤU TRÚC THƯ MỤC

```
legal-qa-system/
|-- .env.example                # File cấu hình biến môi trường mẫu
|-- config.yaml                 # File cấu hình tập trung duy nhất cho hệ thống
|-- docker-compose.yml          # Kịch bản triển khai toàn bộ hệ thống bằng Docker
|
|-- backend/                    # Mã nguồn máy chủ Backend (FastAPI + LangGraph)
|   |-- Dockerfile              # Dockerfile cho backend
|   |-- requirements.txt        # Danh mục thư viện phụ thuộc Python
|   |-- pyproject.toml          # Cấu hình gói và phụ thuộc chuẩn
|   |-- data/
|   |   |-- base_data.json      # Cơ sở dữ liệu gốc chứa các điều luật
|   |   |-- cache/              # Cache chỉ mục BM25 (bm25_index_cache.json)
|   |   `-- sessions/           # Lưu trữ ngữ cảnh lịch sử các phiên hội thoại
|   |-- db/                     # Quản lý cấu trúc CSDL và dữ liệu mồi (Database & Seeds)
|   |   |-- init.sql            # Khởi tạo CSDL 4 bảng: records, registry, taxonomy, rules
|   |   `-- seeds/              # Dữ liệu mồi tri thức pháp lý
|   |       |-- populate_legal_registry.py # Seed danh mục Registry & Taxonomy
|   |       `-- seed_applicability_rules.py # Seed bộ quy tắc điều kiện áp dụng CSDL
|   |-- docker/
|   |   `-- postgres/
|   |       `-- init.sql        # Init script cho Docker container
|   |-- notebooks/              # Thí nghiệm R&D và benchmark đánh giá
|   |   |-- 00_data_exploration.ipynb
|   |   |-- 01_chunking_experiments.ipynb
|   |   |-- 02_retrieval_evaluation.ipynb
|   |   |-- 03_rag_agent_evaluation.ipynb
|   |   `-- 04_latency_benchmark.ipynb
|   |-- scripts/                # Tiện ích vận hành dòng lệnh (CLI Tools)
|   |   |-- load_postgres.py    # Khởi tạo CSDL & nạp toàn bộ tri thức pháp lý trọn gói (3-trong-1)
|   |   |-- ingest.py           # CLI nạp văn bản mới & sinh vector embedding + BM25 cache
|   |   `-- interactive_chat.py # Giao diện hỏi đáp trực tiếp trên dòng lệnh (CLI)
|   |-- tests/                  # Bộ kiểm thử chuyên biệt hệ thống (14 Automated Tests)
|   |   |-- conftest.py         # Fixture TestClient FastAPI dùng chung
|   |   |-- test_enhanced_legal_pipeline.py # 8 Tests: Fact Extractor, Rule Engine, DB Pool, Prompt Builder
|   |   |-- test_api.py         # 6 Tests: Health check, Voices, Sessions CRUD, Articles Lookup
|   |   `-- test_agentic_rag.py # Kiểm thử các vòng lặp CRAG & Self-RAG
|   `-- src/
|       |-- core/               # Hạ tầng dùng chung (Configuration, Connection Pool)
|       |   |-- config.py       # Bộ nạp cấu hình từ config.yaml & env
|       |   `-- database.py     # Threaded Connection Pool quản lý kết nối PostgreSQL tập trung
|       |-- domain/             # Miền nghiệp vụ pháp lý chuyên sâu (Legal Domain Logic)
|       |   |-- rule_engine.py  # Legal Rule Engine thực thi 8 quy tắc CSDL & Temporal Validity
|       |   |-- legal_registry.py # Tra cứu Structured Legal Knowledge Base & Taxonomy
|       |   |-- fact_extractor.py # Two-Tier Fact Extractor & Fact Ambiguity
|       |   `-- premise_checker.py # Thẩm định tính xác thực tiền đề trong câu hỏi
|       |-- nlp/                # Xử lý ngôn ngữ tự nhiên & Tiền xử lý câu hỏi
|       |   |-- text_normalizer.py # Chuẩn hóa tiếng Việt, dấu thanh và ký tự
|       |   |-- spell_corrector.py # Sửa lỗi chính tả pháp lý
|       |   |-- query_rewriter.py  # Viết lại câu hỏi kèm lịch sử hội thoại (CRAG Loop)
|       |   `-- query_decomposer.py # Tách câu hỏi đa hành vi vi phạm
|       |-- retrieval/          # Tầng tìm kiếm & truy xuất tài liệu (Search & Vector Engine)
|       |   |-- hybrid_retriever.py # Hợp nhất kết quả Dense + Sparse (RRF)
|       |   |-- vector_client.py    # Truy xuất vector qua PostgreSQL pgvector HNSW
|       |   |-- keyword_store.py    # Truy xuất từ khóa qua BM25 Okapi (weighting x2 & reload)
|       |   |-- reranker.py         # Tái xếp hạng tài liệu (Smart Fallback & FlashRank)
|       |   `-- hyde.py             # Sinh văn bản pháp luật giả định (HyDE)
|       |-- ingestion/          # Pipeline chuyển đổi & nạp tài liệu pháp lý
|       |   |-- schema.py       # Pydantic schemas cho văn bản luật
|       |   |-- crawler.py      # Thu thập dữ liệu văn bản pháp luật
|       |   |-- converter.py    # Chuyển đổi định dạng DOCX/PDF sang JSON chuẩn
|       |   `-- pipeline.py     # Pipeline Ingestion & batching embeddings vào pgvector
|       |-- agent/              # Định nghĩa LangGraph Agent & Nodes
|       |   |-- graph.py        # Đồ thị trạng thái chính của hệ thống (12 Nodes)
|       |   |-- state.py        # Định nghĩa LegalAgentState (hỗ trợ facts & eligibility)
|       |   |-- prompt_builder.py # LegalPromptBuilder: Single source of truth prompt & post-processing
|       |   |-- llm_client.py   # Client kết nối Ollama / vLLM
|       |   |-- session_manager.py # Quản lý phiên hội thoại bền vững
|       |   `-- nodes/          # 12 Nút xử lý trong đồ thị Agentic RAG
|       |       |-- intent_router.py            # 1. Phân loại ý định người dùng
|       |       |-- smalltalk_node.py           # 2. Xử lý chào hỏi xã giao
|       |       |-- out_of_scope_node.py        # 3. Xử lý từ chối ngoài phạm vi
|       |       |-- applicability_validator_node.py # 4. Thẩm định điều kiện áp dụng & Hard Gate
|       |       |-- inapplicability_node.py     # 5. Giải thích loại trừ hình phạt & hướng dẫn thay thế
|       |       |-- decompose_node.py           # 6. Sửa chính tả, tách đa vi phạm & HyDE
|       |       |-- retrieve_node.py            # 7. Thực thi truy hồi đa truy vấn
|       |       |-- grade_documents_node.py     # 8. Thẩm định độ phù hợp tài liệu (CRAG)
|       |       |-- rewrite_query_node.py       # 9. Mở rộng & viết lại truy vấn (CRAG Loop)
|       |       |-- generate_node.py            # 10. Sinh câu trả lời chuẩn 4 phần
|       |       |-- citation_guard_node.py      # 11. Kiểm định trích dẫn thực tế
|       |       `-- self_correct_node.py        # 12. Phản hồi tự sửa sai (Self-RAG Loop)
|       |-- api/
|       |   `-- main.py         # Điểm khởi chạy FastAPI, định tuyến REST và SSE Stream
|       `-- services/
|           `-- voice_service.py # Dịch vụ chuyển văn bản thành giọng nói (TTS)
|
`-- frontend/                   # Ứng dụng giao diện người dùng (React + Vite + TypeScript)
    |-- Dockerfile              # Dockerfile đóng gói frontend
    |-- nginx.conf              # Cấu hình Nginx phục vụ production
    |-- index.html              # HTML template chính
    |-- package.json            # Quản lý phụ thuộc Node.js
    |-- vite.config.ts          # Cấu hình Vite bundler & reverse proxy
    `-- src/
        |-- App.tsx             # Component giao diện chính
        |-- main.tsx            # Điểm khởi tạo ứng dụng React
        |-- index.css           # Cấu hình CSS và giao diện
        `-- components/         # Thư mục chứa các component giao diện
            `-- ErrorBoundary.tsx # Bắt lỗi runtime hiển thị an toàn
```

---

## 5. YÊU CẦU MÔI TRƯỜNG

- **Hệ điều hành:** Linux, macOS, hoặc Windows (PowerShell / WSL2)
- **Python:** 3.10 trở lên
- **Node.js:** 18.x trở lên và `npm`
- **PostgreSQL:** Phiên bản 16 hoặc 17 có extension `pgvector`
- **Ollama:** Dịch vụ LLM và Embedding cục bộ

---

## 6. HƯỚNG DẪN CÀI ĐẶT & KHỞI CHẠY

### Bước 1: Khởi động Ollama và tải mô hình

```bash
# Tải mô hình LLM suy luận
ollama pull qwen2.5:3b

# Tải mô hình vector embedding
ollama pull nomic-embed-text
```

### Bước 2: Khởi chạy PostgreSQL (pgvector) qua Docker

```bash
# Tạo file môi trường từ mẫu
cp .env.example .env    # Linux/macOS
copy .env.example .env  # Windows

# Khởi chạy container PostgreSQL (cổng 23432)
docker compose up -d postgres
```

### Bước 3: Nạp dữ liệu pháp luật vào CSDL

```bash
cd backend
python -m venv .venv

# Kích hoạt môi trường ảo:
source .venv/bin/activate       # Linux/macOS
.venv\Scripts\Activate.ps1       # Windows PowerShell

pip install -r requirements.txt

# Nạp 13.744 điều luật và khởi tạo 4 bảng tri thức (trọn gói):
python scripts/load_postgres.py
```

### Bước 4: Khởi chạy Backend (FastAPI)

```bash
python -m uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --reload
```
- Health check: `http://127.0.0.1:8000/health`
- Swagger API Docs: `http://127.0.0.1:8000/docs`

### Bước 5: Khởi chạy Frontend (React + Vite)

Mở terminal mới:
```bash
cd frontend
npm install
npm run dev
```
Truy cập giao diện tại: `http://localhost:3000`

### Tùy chọn: Chạy toàn bộ bằng Docker Compose

```bash
docker compose up --build -d
```
- Frontend UI: `http://localhost:3000`
- Backend API: `http://localhost:8000`
- PostgreSQL: `localhost:23432`

---

## 7. CẤU HÌNH HỆ THỐNG (config.yaml)

| Tham số | Mặc định | Ý nghĩa |
|---|---|---|
| `app.host` / `app.port` | `0.0.0.0:8000` | Địa chỉ mạng và cổng Backend |
| `ui.host` / `ui.port` | `0.0.0.0:3000` | Cổng phát triển Frontend |
| `llm.base_url` | `http://localhost:11434/v1` | Endpoint LLM tương thích OpenAI |
| `llm.default_model` | `qwen2.5:3b` | Mô hình ngôn ngữ lớn |
| `llm.temperature` | `0.1` | Độ ngẫu nhiên suy luận |
| `embeddings.base_url` | `http://localhost:11434/v1` | Endpoint Embedding |
| `embeddings.model` | `nomic-embed-text` | Mô hình trích xuất đặc trưng vector |
| `legal_assistant.chat.streaming` | `true` | Bật stream Server-Sent Events (SSE) |
| `legal_assistant.retrieval.top_k` | `20` | Số lượng tài liệu sơ tuyển ban đầu |
| `legal_assistant.retrieval.rerank_top_k` | `5` | Số tài liệu tinh chọn sau rerank |
| `legal_assistant.retrieval.fusion_method`| `rrf` | Phương pháp hợp nhất: Reciprocal Rank Fusion |
| `legal_assistant.reranker.enabled` | `true` | Kích hoạt bộ tái xếp hạng Reranker |
| `legal_assistant.reranker.engine` | `smart_fallback` | Động cơ: `smart_fallback` \| `flashrank` \| `http` |
| `legal_assistant.reranker.model` | `ms-marco-MiniLM-L-12-v2` | Mô hình Cross-Encoder cho FlashRank/HTTP |
| `legal_assistant.tts.enabled` | `true` | Bật/tắt giọng nói đọc văn bản |
| `legal_assistant.tts.provider` | `edge-tts` | `edge-tts` (online) hoặc `local_http` (nội bộ) |
| `legal_assistant.tts.default_voice` | `vi-VN-HoaiMyNeural` | Giọng đọc mặc định |
| `legal_assistant.postgres.database_url` | `postgresql://...` | Chuỗi kết nối PostgreSQL |

---

## 8. DANH MỤC API ENDPOINTS

| Phương thức | Đường dẫn Endpoint | Chức năng |
|---|---|---|
| `GET` | `/health` | Kiểm tra trạng thái Backend và CSDL |
| `POST` | `/chat` | Gửi câu hỏi pháp lý và nhận câu trả lời đồng bộ |
| `POST` | `/chat/stream` | Hỏi đáp truyền dữ liệu liên tục Server-Sent Events (SSE) |
| `GET` | `/articles/lookup` | Tra cứu nguyên văn điều luật theo số hiệu hoặc trích dẫn |
| `GET` | `/sessions` | Lấy danh sách toàn bộ các phiên hội thoại |
| `POST` | `/sessions` | Khởi tạo phiên hội thoại mới |
| `GET` | `/sessions/{session_id}` | Lấy lại toàn bộ lịch sử tin nhắn của một phiên |
| `PATCH` | `/sessions/{session_id}` | Đổi tên tiêu đề phiên hội thoại |
| `PUT` | `/sessions/{session_id}` | Cập nhật thông tin phiên hội thoại |
| `DELETE` | `/sessions/{session_id}` | Xóa một phiên hội thoại cụ thể |
| `DELETE` | `/sessions` | Xóa tất cả các phiên hội thoại |
| `POST` | `/ingest` | Nạp tài liệu pháp luật mới vào hệ thống qua API |
| `GET` | `/voice/voices` | Danh sách giọng đọc hỗ trợ |
| `POST` | `/voice/tts` | Chuyển văn bản câu trả lời thành file âm thanh MP3 |
| `POST` | `/admin/reload-registry` | Tải lại Legal Registry mà không cần khởi động lại server |

> Token của `/chat/stream` được đệm ở backend và phát ra sau khi Citation Guard hoàn tất thẩm định.

---

## 9. KIỂM THỬ HỆ THỐNG

```bash
# 1. Chạy bộ kiểm thử Fact Extractor, Rule Engine, DB Pool, Prompt Builder (8 tests)
python -m pytest tests/test_enhanced_legal_pipeline.py -v

# 2. Chạy kiểm thử REST API, Health check & Sessions CRUD (6 tests)
python -m pytest tests/test_api.py -v

# 3. Thử nghiệm hỏi đáp trên dòng lệnh (CLI)
python scripts/interactive_chat.py

# 4. Kiểm thử các vòng lặp phản hồi Agentic RAG (Mock CRAG & Self-RAG)
python tests/test_agentic_rag.py

# 5. Khởi chạy bộ Jupyter Notebooks thực nghiệm R&D
jupyter notebook notebooks/
```

---

## 10. KẾT QUẢ THỰC NGHIỆM & BENCHMARK ĐO LƯỜNG

Hệ thống được đo lường định lượng trên cơ sở tri thức 13.744 Điều luật, môi trường máy chủ cục bộ (Ollama `qwen2.5:3b` và PostgreSQL 17 pgvector).

### 1. Năng lực Truy xuất (Retrieval Ablation Study - Notebook 02)
Đo lường trên tập benchmark 20 câu hỏi đa lĩnh vực (Giao thông, Lao động, Doanh nghiệp, Đất đai):

| Chiến lược truy xuất | Recall@1 (%) | Recall@3 (%) | Recall@5 (%) | Recall@10 (%) | MRR | Latency P50 (ms) | Latency P90 (ms) |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **1. BM25 (Lexical Only)** | 60.0% | 70.0% | 70.0% | 85.0% | 0.66 | 127.2 ms | 169.3 ms |
| **2. Dense Vector (Semantic Only)** | 60.0% | 65.0% | 75.0% | 75.0% | 0.65 | 54.9 ms | 98.1 ms |
| **3. Hybrid RRF (Combined Dense + Sparse)** | 35.0% | **85.0%** | **90.0%** | **90.0%** | 0.60 | 190.2 ms | 248.5 ms |
| **4. Hybrid RRF + Expansion (Hệ thống v3)** | 45.0% | 70.0% | 80.0% | **90.0%** | 0.61 | 305.8 ms | 446.3 ms |

> **Nhận xét:** Cơ chế Hybrid RRF đạt độ phủ Recall@5 và Recall@10 ở mức 90.0%, vượt trội so với tìm kiếm đơn lẻ trong việc xử lý ngôn ngữ đời thường sang ngôn ngữ luật định.

### 2. Đánh giá Chất lượng Agentic RAG qua RAGAS Framework (Notebook 03)
Đánh giá trên 15 bài toán phân loại ý định và 10 bài toán pháp lý chuyên sâu có Ground Truth đối chuẩn:

- **Phân loại ý định (Intent Routing - 15 test cases):** Độ chính xác **100.0% (15/15)**, độ trễ trung bình **152.3 ms / truy vấn**.
- **Chỉ số RAGAS & Nghiệp vụ pháp lý cốt lõi (10 Legal QA Test Cases):**

| Thang đo đánh giá | Điểm số thực nghiệm | Ý nghĩa kỹ thuật & Nghiệp vụ |
|---|:---:|---|
| **Citation Precision** | **100.0%** | 100% Điều luật trích dẫn đều có căn cứ thật trong tài liệu đã truy hồi (chống bịa đặt số điều). |
| **Answer Relevancy** | **95.4%** | Mức độ bám sát câu hỏi và giải thích đúng trọng tâm pháp lý. |
| **Faithfulness (Độ trung thực)** | **94.9%** | Mọi lập luận và mức phạt đều căn cứ trên tài liệu gốc, không suy diễn ngoài luật. |
| **Context Recall** | **90.0%** | Tỷ lệ các Điều luật bắt buộc trong Ground Truth được hệ thống bao quát đầy đủ. |
| **Context Precision** | **70.0%** | Mức độ cô đọng của các đoạn văn bản luật đưa vào ngữ cảnh sinh câu trả lời. |
| **4-Part Structure Compliance** | **50.0%** | Tỷ lệ tuân thủ kết cấu 4 phần chuẩn mực (Kết luận -> Căn cứ -> Áp dụng -> Lưu ý). |

### 3. Ma trận Phân vị Độ trễ & Thông lượng (Latency Benchmark - Notebook 04)
Đo lường chi tiết qua 6 bài toán pháp lý tiêu chuẩn chạy thực tế trên máy chủ cục bộ:

| Chặng xử lý | Đơn vị | Mean (TB) | P50 (Median) | P90 | P99 (Max) | Min | Max |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **1. Intent Router** | ms | 325.8 | **173.4** | 651.6 | 1,024.7 | 147.6 | 1,066.1 |
| **2. Query Rewriter** | ms | 624.0 | **608.0** | 874.5 | 945.3 | 379.3 | 953.2 |
| **3. HyDE Passage** | ms | 2,050.2 | **1,940.1** | 2,578.0 | 2,998.4 | 1,606.4 | 3,045.1 |
| **4. Retrieval & Reranker** | ms | 1,988.7 | **2,058.7** | 2,371.8 | 2,404.9 | 1,520.7 | 2,408.6 |
| **5. Smart Windowing** | ms | 6.2 | **5.7** | 12.1 | 13.1 | 0.5 | 13.2 |
| **6. LLM Generation** | ms | 4,102.7 | **3,407.6** | 5,744.3 | 5,856.4 | 3,123.4 | 5,868.8 |
| **7. Citation Guard** | ms | 3.1 | **3.0** | 3.8 | 4.1 | 2.5 | 4.2 |
| **Tổng Pipeline (End-to-End)** | **giây** | **9.10 s** | **9.18 s** | **10.88 s** | **11.08 s** | **6.99 s** | **11.10 s** |
| **Time to First Token (TTFT)** | **giây** | **5.14 s** | **5.29 s** | **6.14 s** | **6.24 s** | **4.00 s** | **6.25 s** |
| **Throughput (Từ/giây)** | **words/s** | **30.00 w/s** | **30.00 w/s** | **32.45 w/s** | **32.85 w/s** | **27.10 w/s** | **32.90 w/s** |
| **Throughput (Token/giây)** | **tokens/s**| **38.90 t/s** | **38.75 t/s** | **42.15 t/s** | **42.64 t/s** | **35.10 t/s** | **42.70 t/s** |

> **Hiệu ứng Steady-State:** Sau khi nạp model (Warm-up), độ trễ Intent Router giảm 84.6% (từ 1.066,1 ms xuống 164,0 ms) và TTFT giảm 20.8% (xuống ~4,0 - 4,9s).

---

## 11. MIỄN TRỪ TRÁCH NHIỆM

> [!WARNING]
> - **Mục đích tham khảo:** Hệ thống được phát triển phục vụ mục đích nghiên cứu, học tập và tra cứu thông tin tham khảo.
> - **Không thay thế tư vấn pháp lý:** Câu trả lời do AI sinh ra không cấu thành ý kiến tư vấn pháp lý chính thức và không có giá trị pháp lý thay thế cơ quan nhà nước có thẩm quyền hoặc luật sư hành nghề.
> - **Đối chiếu văn bản gốc:** Người dùng cần kiểm tra, đối chiếu lại với văn bản quy phạm pháp luật hiện hành mới nhất trước khi đưa ra các quyết định trong thực tế.
> - **Giới hạn trách nhiệm:** Tác giả / Nhóm phát triển không chịu trách nhiệm đối với bất kỳ rủi ro hay thiệt hại nào phát sinh từ việc sử dụng thông tin do hệ thống cung cấp.

---

## 12. BẢN QUYỀN & LIÊN HỆ

Dự án được xây dựng phục vụ mục đích học tập, nghiên cứu và phát triển giải pháp ứng dụng trí tuệ nhân tạo trong lĩnh vực pháp lý tại Việt Nam. Dữ liệu văn bản quy phạm pháp luật được trích xuất từ các nguồn công khai chính thức của Nhà nước.
