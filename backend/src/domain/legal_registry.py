"""Dịch vụ quản trị và tra cứu Structured Legal Knowledge Base (LKB).

Tự động tải và đồng bộ danh mục văn bản luật chuẩn (legal_documents_registry)
và phân loại ngành luật / nhận diện ngộ nhận (legal_domain_taxonomy) từ PostgreSQL.
Cung cấp tra cứu in-memory siêu tốc (< 1ms) hỗ trợ Agentic RAG và Premise Checker.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

import psycopg2
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)


@dataclass
class LawDocument:
    law_id: str
    official_title: str
    short_title: str
    doc_type: str
    total_articles: int
    max_article_num: int
    article_list: Set[str]
    aliases: List[str]
    validity_status: str
    issue_year: Optional[int] = None
    description: Optional[str] = None


@dataclass
class DomainTaxonomy:
    domain_code: str
    domain_name: str
    governing_law_id: Optional[str]
    governing_law_title: str
    keywords: List[str]
    common_fake_names: List[str]
    explanation_template: str
    default_redirect_query: Optional[str] = None


class LegalRegistryService:
    """Singleton Service tra cứu tri thức pháp luật có cấu trúc (LKB) từ PostgreSQL."""

    _instance: Optional[LegalRegistryService] = None

    def __init__(self, db_url: Optional[str] = None):
        self.db_url = db_url
        self._laws_by_id: Dict[str, LawDocument] = {}
        self._laws_by_alias: Dict[str, LawDocument] = {}
        self._taxonomy_list: List[DomainTaxonomy] = []
        self._fake_names_to_taxonomy: Dict[str, DomainTaxonomy] = {}
        self._all_known_law_names: Set[str] = set()
        self._articles_titles_by_law: Dict[str, Dict[str, str]] = {}
        self._is_loaded = False

    @classmethod
    def get_instance(cls, db_url: Optional[str] = None) -> LegalRegistryService:
        if cls._instance is None:
            cls._instance = cls(db_url)
            cls._instance.load_from_db()
        return cls._instance

    def load_from_db(self, db_url: Optional[str] = None) -> None:
        """Tải toàn bộ Registry, Taxonomy và danh mục tiêu đề Điều luật từ PostgreSQL vào bộ nhớ RAM."""
        target_url = db_url or self.db_url
        if not target_url:
            from src.core.config import get_settings
            target_url = get_settings().legal_assistant.postgres.database_url

        self.db_url = target_url
        try:
            from src.core.database import get_db_pool

            logger.info("[LegalRegistry] Đang kết nối PostgreSQL để nạp Structured Legal Knowledge Base...")
            pool = get_db_pool(target_url)
            with pool.get_cursor(commit=False) as cur:
                # 1. Đọc legal_documents_registry
                cur.execute("""
                    SELECT law_id, official_title, short_title, doc_type,
                           total_articles, max_article_num, article_list,
                           aliases, validity_status, issue_year, description
                    FROM legal_documents_registry;
                """)
                reg_rows = cur.fetchall()

                # 2. Đọc legal_domain_taxonomy
                cur.execute("""
                    SELECT domain_code, domain_name, governing_law_id,
                           governing_law_title, keywords, common_fake_names,
                           explanation_template, default_redirect_query
                    FROM legal_domain_taxonomy;
                """)
                tax_rows = cur.fetchall()

                # 3. Đọc danh mục toàn bộ tiêu đề điều luật từ legal_knowledge_records
                cur.execute("""
                    SELECT law_id, article, article_title
                    FROM legal_knowledge_records
                    WHERE article_title IS NOT NULL AND article_title != '';
                """)
                records_rows = cur.fetchall()

            new_laws_by_id: Dict[str, LawDocument] = {}
            new_laws_by_alias: Dict[str, LawDocument] = {}
            all_names: Set[str] = set()

            for row in reg_rows:
                raw_articles = row.get("article_list")
                if isinstance(raw_articles, str):
                    try:
                        art_list = set(json.loads(raw_articles))
                    except Exception:
                        art_list = set()
                elif isinstance(raw_articles, list):
                    art_list = set(raw_articles)
                else:
                    art_list = set()

                aliases = row.get("aliases") or []

                law_doc = LawDocument(
                    law_id=row["law_id"],
                    official_title=row["official_title"],
                    short_title=row["short_title"],
                    doc_type=row["doc_type"],
                    total_articles=row["total_articles"],
                    max_article_num=row["max_article_num"],
                    article_list=art_list,
                    aliases=aliases,
                    validity_status=row.get("validity_status") or "active",
                    issue_year=row.get("issue_year"),
                    description=row.get("description"),
                )

                new_laws_by_id[law_doc.law_id] = law_doc
                all_names.add(law_doc.official_title.lower())
                all_names.add(law_doc.short_title.lower())

                for alias in aliases:
                    alias_lower = alias.strip().lower()
                    if alias_lower:
                        # Ưu tiên văn bản chính (có nhiều điều luật hơn) nắm giữ alias thông dụng
                        if alias_lower not in new_laws_by_alias or law_doc.total_articles > new_laws_by_alias[alias_lower].total_articles:
                            new_laws_by_alias[alias_lower] = law_doc
                        all_names.add(alias_lower)

            new_taxonomy_list: List[DomainTaxonomy] = []
            new_fake_map: Dict[str, DomainTaxonomy] = {}

            for row in tax_rows:
                tax = DomainTaxonomy(
                    domain_code=row["domain_code"],
                    domain_name=row["domain_name"],
                    governing_law_id=row.get("governing_law_id"),
                    governing_law_title=row["governing_law_title"],
                    keywords=row.get("keywords") or [],
                    common_fake_names=row.get("common_fake_names") or [],
                    explanation_template=row["explanation_template"],
                    default_redirect_query=row.get("default_redirect_query"),
                )
                new_taxonomy_list.append(tax)

                for fake in tax.common_fake_names:
                    fake_lower = fake.strip().lower()
                    if fake_lower:
                        new_fake_map[fake_lower] = tax

            new_articles_titles: Dict[str, Dict[str, str]] = {}
            for r in records_rows:
                lid = r["law_id"]
                art = r["article"].strip()
                title = r["article_title"].strip()
                if lid not in new_articles_titles:
                    new_articles_titles[lid] = {}
                new_articles_titles[lid][art] = title

            # Gán atomic vào state
            self._laws_by_id = new_laws_by_id
            self._laws_by_alias = new_laws_by_alias
            self._taxonomy_list = new_taxonomy_list
            self._fake_names_to_taxonomy = new_fake_map
            self._all_known_law_names = all_names
            self._articles_titles_by_law = new_articles_titles
            self._is_loaded = True

            total_titles = sum(len(d) for d in self._articles_titles_by_law.values())
            logger.info(
                f"[LegalRegistry] Đã nạp thành công LKB: {len(self._laws_by_id)} văn bản pháp luật, "
                f"{len(self._laws_by_alias)} aliases, {len(self._taxonomy_list)} phân loại ngành luật, "
                f"{total_titles} tiêu đề điều luật."
            )
        except Exception as e:
            logger.error(f"[LegalRegistry] Lỗi nạp LKB từ PostgreSQL: {e}", exc_info=True)

    def find_fake_law_or_misconception(self, query: str) -> Optional[Tuple[str, DomainTaxonomy]]:
        """Phát hiện xem câu hỏi có chứa tên luật nhầm lẫn / luật giả định không.
        
        Trả về (tên_luật_bị_nhầm_được_tìm_thấy, DomainTaxonomy).
        """
        if not self._is_loaded:
            self.load_from_db()

        query_lower = query.lower()

        # 1. So khớp trực tiếp danh sách fake_names
        for fake_name, tax in self._fake_names_to_taxonomy.items():
            if fake_name in query_lower:
                return fake_name, tax

        # 2. So khớp regex cho các biến thể kèm năm
        # Ví dụ: "luật bảo vệ người lao động 2023", "luật người lao động 2024"
        for tax in self._taxonomy_list:
            for fake_pattern in tax.common_fake_names:
                pat = re.escape(fake_pattern) + r"(?:\s+\d{4})?"
                m = re.search(pat, query_lower)
                if m:
                    return m.group(0), tax

        return None

    def resolve_law_by_name_or_query(self, text: str) -> Optional[LawDocument]:
        """Tra cứu LawDocument từ đoạn text (tên luật, số hiệu, alias hoặc trích xuất từ câu hỏi)."""
        if not self._is_loaded:
            self.load_from_db()

        text_clean = text.strip().lower()

        # 1. Exact match trong alias
        if text_clean in self._laws_by_alias:
            return self._laws_by_alias[text_clean]

        # 2. Match theo law_id
        if text.strip() in self._laws_by_id:
            return self._laws_by_id[text.strip()]

        # 3. Quét các alias có độ dài giảm dần để ưu tiên match cụm dài nhất
        sorted_aliases = sorted(self._laws_by_alias.keys(), key=len, reverse=True)
        for alias in sorted_aliases:
            if len(alias) >= 4 and alias in text_clean:
                return self._laws_by_alias[alias]

        return None

    def is_known_law(self, name: str) -> bool:
        """Kiểm tra xem tên văn bản có thuộc hệ thống văn bản đã được ghi nhận không."""
        if not self._is_loaded:
            self.load_from_db()

        clean = name.strip().lower()
        if clean in self._all_known_law_names:
            return True

        for known in self._all_known_law_names:
            if len(known) >= 6 and (known in clean or clean in known):
                return True

        return False

    def validate_article(self, law: LawDocument, article_str: str) -> Tuple[bool, Optional[str]]:
        """Kiểm định xem Điều X có tồn tại hợp lệ trong văn bản hay không.
        
        Trả về: (is_valid: bool, error_message: Optional[str])
        """
        m = re.search(r"Điều\s+(\d+[a-zA-Z]?)", article_str, re.IGNORECASE)
        if not m:
            return True, None

        queried_art = f"Điều {m.group(1)}"
        m_num = re.search(r"^(\d+)", m.group(1))
        num_val = int(m_num.group(1)) if m_num else None

        # 1. Vượt quá số điều tối đa của văn bản
        if num_val and law.max_article_num > 0 and num_val > law.max_article_num:
            msg = (
                f"{law.official_title} hiện hành chỉ có tổng cộng {law.max_article_num} Điều "
                f"(từ Điều 1 đến Điều {law.max_article_num}), hoàn toàn KHÔNG CÓ {queried_art}."
            )
            return False, msg

        # 2. Không tồn tại trong danh sách điều thực tế của văn bản
        if law.article_list and queried_art not in law.article_list:
            # Kiểm tra trường hợp biến thể chữ hoa/thường
            matched = any(queried_art.lower() == a.lower() for a in law.article_list)
            if not matched:
                msg = f"{law.official_title} không có {queried_art}."
                return False, msg

        return True, None

    def get_article_title(self, law_id: str, article: str) -> Optional[str]:
        """Lấy tiêu đề thực tế của một điều luật trong văn bản."""
        if not self._is_loaded:
            self.load_from_db()

        art_clean = article.strip()
        # Chuẩn hóa tiền tố 'Điều '
        if not art_clean.lower().startswith("điều"):
            art_clean = f"Điều {art_clean}"

        # Tìm trong law_id chính hoặc các biến thể ID
        titles_map = self._articles_titles_by_law.get(law_id, {})
        if art_clean in titles_map:
            return titles_map[art_clean]

        for k, v in titles_map.items():
            if k.lower() == art_clean.lower():
                return v

        return None

    def find_article_by_topic(self, law_id: str, topic: str) -> Optional[Tuple[str, str]]:
        """Tìm điều luật trong cùng văn bản có tiêu đề khớp với chủ đề/tội danh."""
        if not self._is_loaded:
            self.load_from_db()

        clean_topic = topic.strip().lower()
        clean_topic = re.sub(r"^(?:về|tội|quy\s+định\s+về)\s+", "", clean_topic).strip()
        if len(clean_topic) < 3:
            return None

        titles_map = self._articles_titles_by_law.get(law_id, {})
        
        # 1. Exact match tiêu đề
        for art, title in titles_map.items():
            t_lower = title.lower()
            if clean_topic == t_lower or f"tội {clean_topic}" == t_lower:
                return art, title

        # 2. Substring match
        for art, title in titles_map.items():
            t_lower = title.lower()
            if clean_topic in t_lower:
                return art, title

        return None

    def check_article_topic_mismatch(
        self,
        law: LawDocument,
        queried_art: str,
        query: str,
    ) -> Optional[Dict[str, Any]]:
        """Phát hiện câu hỏi gán ghép sai Điều luật cho một Tội danh hoặc Chủ đề pháp lý.
        
        Ví dụ: "Điều 173 BLHS quy định tội giết người đúng không?"
        -> Điều 173 thực tế là 'Tội trộm cắp tài sản'. Tội giết người là Điều 123.
        """
        actual_title = self.get_article_title(law.law_id, queried_art)
        if not actual_title:
            return None

        actual_title_lower = actual_title.lower()

        # Trích xuất các cụm chủ đề / tội danh tiềm năng từ câu hỏi
        candidate_topics = []

        # Pattern 1: "tội giết người", "tội cướp giật", "tội lừa đảo"...
        for m in re.finditer(r"\b(tội\s+[a-zàáảãạăằắẳẵặâầấẩẫậđèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵ\s]+?)(?=\s+(?:đúng\s+không|phải\s+không|như\s+thế\s+nào|bị\s+phạt|thế\s+nào|là\s+gì|\?|$|\,|\.))", query, re.I):
            candidate_topics.append(m.group(1).strip())

        # Pattern 2: "về làm thêm giờ", "về sa thải", "về ly hôn"...
        for m in re.finditer(r"\b(?:về|quy\s+định\s+về)\s+([a-zàáảãạăằắẳẵặâầấẩẫậđèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵ\s]+?)(?=\s+(?:đúng\s+không|phải\s+không|như\s+thế\s+nào|bị\s+phạt|thế\s+nào|là\s+gì|\?|$|\,|\.))", query, re.I):
            candidate_topics.append(m.group(1).strip())

        # Pattern 3: Quét trực tiếp các tiêu đề khác trong cùng văn bản xuất hiện trong query
        titles_map = self._articles_titles_by_law.get(law.law_id, {})
        for art, title in titles_map.items():
            if art.lower() == queried_art.lower():
                continue
            # Bỏ từ 'Tội' nếu có
            t_core = re.sub(r"^(?:Tội|Về)\s+", "", title, flags=re.I).strip().lower()
            if len(t_core) >= 4 and t_core in query.lower():
                candidate_topics.append(title.lower())

        for topic in candidate_topics:
            core_topic = re.sub(r"^(?:về|tội|quy\s+định\s+về)\s+", "", topic, flags=re.I).strip().lower()
            if len(core_topic) < 3:
                continue

            # Nếu core_topic KHÔNG nằm trong actual_title của điều người dùng hỏi
            if core_topic not in actual_title_lower:
                # Tìm điều luật thực sự quy định topic này
                match_res = self.find_article_by_topic(law.law_id, topic)
                if match_res:
                    correct_art, correct_title = match_res
                    if correct_art.lower() != queried_art.lower():
                        display_name = law.official_title
                        topic_display = topic if topic.startswith("tội") else f"quy định về {topic}"
                        msg = (
                            f"{queried_art} {display_name} quy định về '{actual_title}', "
                            f"KHÔNG PHẢI {topic_display}. "
                            f"Nội dung {topic_display} được quy định tại {correct_art} ({correct_title}) {display_name}."
                        )
                        clean_q = query.replace(queried_art, correct_art).strip()
                        return {
                            "has_false_premise": True,
                            "is_mismatch": True,
                            "queried_article": queried_art,
                            "actual_title": actual_title,
                            "queried_topic": topic,
                            "correct_article": correct_art,
                            "correct_title": correct_title,
                            "law_display": display_name,
                            "message": msg,
                            "cleaned_query": clean_q,
                        }

        return None

    def reload(self) -> None:
        """Tải lại dữ liệu từ PostgreSQL."""
        self.load_from_db()


def get_legal_registry() -> LegalRegistryService:
    """Dependency helper lấy singleton instance của LegalRegistryService."""
    return LegalRegistryService.get_instance()

