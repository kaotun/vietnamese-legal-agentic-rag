-- Khởi tạo extensions cho PostgreSQL trong legal-qa-system
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "unaccent";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";
CREATE EXTENSION IF NOT EXISTS "vector";

-- Bảng lưu trữ tri thức văn bản quy phạm pháp luật
CREATE TABLE IF NOT EXISTS legal_knowledge_records (
    id INTEGER PRIMARY KEY,
    law_id TEXT NOT NULL,
    law_name TEXT NOT NULL,
    doc_type TEXT NOT NULL,
    article TEXT NOT NULL,
    article_title TEXT NOT NULL,
    content TEXT NOT NULL,
    author TEXT NOT NULL,
    validity_status TEXT DEFAULT 'active', -- 'active' (còn hiệu lực), 'expired' (hết hiệu lực), 'partially_expired' (hết hiệu lực 1 phần)
    effective_date DATE,
    expiration_date DATE,
    replacement_law_id TEXT,
    embedding vector(768),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- Chỉ mục tối ưu hóa tìm kiếm từ khóa và tra cứu
CREATE INDEX IF NOT EXISTS idx_legal_records_law_id ON legal_knowledge_records(law_id);
CREATE INDEX IF NOT EXISTS idx_legal_records_article ON legal_knowledge_records(article);
CREATE INDEX IF NOT EXISTS idx_legal_records_validity ON legal_knowledge_records(validity_status);

-- Chỉ mục HNSW cho vector similarity search
CREATE INDEX IF NOT EXISTS idx_legal_records_embedding_hnsw
ON legal_knowledge_records USING hnsw (embedding vector_cosine_ops);

-- Bảng đăng ký danh mục văn bản quy phạm pháp luật chuẩn (Legal Documents Registry)
CREATE TABLE IF NOT EXISTS legal_documents_registry (
    law_id TEXT PRIMARY KEY,
    official_title TEXT NOT NULL,
    short_title TEXT NOT NULL,
    doc_type TEXT NOT NULL,
    total_articles INTEGER NOT NULL DEFAULT 0,
    max_article_num INTEGER NOT NULL DEFAULT 0,
    article_list JSONB NOT NULL DEFAULT '[]'::jsonb,
    aliases TEXT[] NOT NULL DEFAULT '{}',
    validity_status TEXT DEFAULT 'active',
    issue_year INTEGER,
    description TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_legal_registry_short_title ON legal_documents_registry(short_title);
CREATE INDEX IF NOT EXISTS idx_legal_registry_aliases ON legal_documents_registry USING gin(aliases);
CREATE INDEX IF NOT EXISTS idx_legal_registry_doc_type ON legal_documents_registry(doc_type);

-- Bảng phân loại ngành luật, định tuyến chủ đề và nhận diện ngộ nhận/tên luật sai (Legal Domain Taxonomy)
CREATE TABLE IF NOT EXISTS legal_domain_taxonomy (
    id SERIAL PRIMARY KEY,
    domain_code TEXT NOT NULL UNIQUE,
    domain_name TEXT NOT NULL,
    governing_law_id TEXT,
    governing_law_title TEXT NOT NULL,
    keywords TEXT[] NOT NULL DEFAULT '{}',
    common_fake_names TEXT[] NOT NULL DEFAULT '{}',
    explanation_template TEXT NOT NULL,
    default_redirect_query TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_taxonomy_keywords ON legal_domain_taxonomy USING gin(keywords);
CREATE INDEX IF NOT EXISTS idx_taxonomy_fake_names ON legal_domain_taxonomy USING gin(common_fake_names);

-- Bảng quy tắc điều kiện áp dụng pháp luật (Legal Applicability Rules & Eligibility Gate)
-- Đảm bảo Rule Engine vận hành hoàn toàn Data-Driven trên CSDL, không hardcode luật vào logic code.
CREATE TABLE IF NOT EXISTS legal_applicability_rules (
    rule_id TEXT PRIMARY KEY,
    rule_name TEXT NOT NULL,
    domain TEXT NOT NULL,                  -- 'criminal', 'civil', 'labor', 'administrative', etc.
    target_law_id TEXT NOT NULL,           -- 'BLHS_2015', 'BLLD_2019', 'BLDS_2015', etc.
    target_article TEXT NOT NULL,          -- 'Điều 12', 'Điều 134', 'Điều 586', etc.
    condition_schema JSONB NOT NULL,       -- Điều kiện kiểm tra có cấu trúc (ví dụ: {"age": {"operator": "<", "value": 14}})
    effect_type TEXT NOT NULL,             -- 'BLOCK', 'REQUIRE_CONDITION', 'SUBSTITUTE_LIABILITY', 'LIMIT_THRESHOLD'
    legal_decision JSONB NOT NULL,         -- Kết luận pháp lý chính thức và danh mục văn bản thay thế
    effective_from DATE DEFAULT '2018-01-01',
    effective_to DATE,
    version TEXT DEFAULT '1.0',
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_applicability_rules_domain ON legal_applicability_rules(domain);
CREATE INDEX IF NOT EXISTS idx_applicability_rules_law_id ON legal_applicability_rules(target_law_id);
CREATE INDEX IF NOT EXISTS idx_applicability_rules_effect ON legal_applicability_rules(effect_type);
