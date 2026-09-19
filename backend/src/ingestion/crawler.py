"""Crawler văn bản quy phạm pháp luật với cơ chế Checkpoint & Stateful Resume."""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
import httpx
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DATA_RAW_DIR = Path(__file__).resolve().parents[2] / "data" / "raw"
CHECKPOINT_FILE = DATA_RAW_DIR / "crawler_checkpoint.json"


class LegalCrawler:
    """Crawler thu thập văn bản pháp luật có cơ chế ghi nhớ tiến trình (resumable)."""

    def __init__(self, raw_dir: Path = DATA_RAW_DIR, checkpoint_path: Path = CHECKPOINT_FILE):
        self.raw_dir = raw_dir
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.checkpoint_path = checkpoint_path
        self.visited_urls: set[str] = set()
        self.pending_urls: list[str] = []
        self._load_checkpoint()

    def _load_checkpoint(self) -> None:
        if self.checkpoint_path.exists():
            try:
                data = json.loads(self.checkpoint_path.read_text(encoding="utf-8"))
                self.visited_urls = set(data.get("visited_urls", []))
                self.pending_urls = data.get("pending_urls", [])
                logger.info(f"Đã phục hồi checkpoint: {len(self.visited_urls)} URL đã cào, {len(self.pending_urls)} URL chờ.")
            except Exception as e:
                logger.warning(f"Lỗi đọc checkpoint, khởi tạo mới: {e}")

    def _save_checkpoint(self) -> None:
        data = {
            "visited_urls": list(self.visited_urls),
            "pending_urls": self.pending_urls,
        }
        self.checkpoint_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def add_target_urls(self, urls: List[str]) -> None:
        """Thêm danh sách URL mục tiêu cần cào."""
        for u in urls:
            u_clean = u.strip()
            if u_clean and u_clean not in self.visited_urls and u_clean not in self.pending_urls:
                self.pending_urls.append(u_clean)
        self._save_checkpoint()

    @staticmethod
    def parse_document_html(html: str, url: str) -> Dict[str, Any]:
        """Bóc tách HTML thành dữ liệu thô dạng cấu trúc."""
        soup = BeautifulSoup(html, "lxml")

        # Loại bỏ script, style, nav, footer
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()

        title = ""
        title_el = soup.find("h1") or soup.find("title")
        if title_el:
            title = title_el.get_text(strip=True)

        content_div = soup.find("div", class_=re.compile(r"(content|document|fulltext|vb-detail)", re.I)) or soup.find("body")
        raw_text = content_div.get_text(separator="\n", strip=True) if content_div else ""

        # Tìm các Điều bằng regex
        articles = []
        pattern = re.compile(r"(Điều\s+\d+[\.:\s][^\n]+)", re.IGNORECASE)
        splits = pattern.split(raw_text)
        
        if len(splits) > 1:
            for i in range(1, len(splits), 2):
                art_header = splits[i].strip()
                art_body = splits[i+1].strip() if i+1 < len(splits) else ""
                match_no = re.search(r"\d+", art_header)
                art_no = int(match_no.group()) if match_no else len(articles) + 1
                articles.append({
                    "article_no": art_no,
                    "article_name": art_header,
                    "content": art_body,
                })

        return {
            "url": url,
            "title": title or "Văn bản không có tiêu đề",
            "raw_text": raw_text,
            "articles": articles,
        }

    async def crawl_one(self, client: httpx.AsyncClient, url: str) -> Optional[Dict[str, Any]]:
        """Cào một URL cụ thể với retry."""
        try:
            resp = await client.get(url, timeout=20.0, follow_redirects=True)
            if resp.status_code == 200:
                doc_data = self.parse_document_html(resp.text, url)
                return doc_data
            else:
                logger.warning(f"Status {resp.status_code} khi tải {url}")
        except Exception as e:
            logger.error(f"Lỗi khi cào {url}: {e}")
        return None

    async def run(self, max_items: int = 50) -> None:
        """Chạy pipeline crawler."""
        logger.info(f"Bắt đầu crawl, số URL chờ xử lý: {len(self.pending_urls)}")
        count = 0

        async with httpx.AsyncClient(headers={"User-Agent": "LegalQABot/1.0"}) as client:
            while self.pending_urls and count < max_items:
                url = self.pending_urls.pop(0)
                if url in self.visited_urls:
                    continue

                logger.info(f"[{count+1}/{max_items}] Đang tải: {url}")
                doc = await self.crawl_one(client, url)
                if doc:
                    file_name = f"doc_{len(self.visited_urls) + 1}.json"
                    (self.raw_dir / file_name).write_text(
                        json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8"
                    )
                    self.visited_urls.add(url)
                    count += 1

                self._save_checkpoint()
                await asyncio.sleep(1.0)  # Rate limiting lịch sự

        logger.info(f"Hoàn thành lượt crawl: đã xử lý {count} văn bản. Đã lưu vào {self.raw_dir}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Chạy Crawler văn bản pháp luật")
    parser.add_argument("--add-url", nargs="+", help="Thêm các URL cần cào vào hàng đợi")
    parser.add_argument("--max", type=int, default=10, help="Số lượng tối đa cần cào")
    args = parser.parse_args()

    crawler = LegalCrawler()
    if args.add_url:
        crawler.add_target_urls(args.add_url)
    asyncio.run(crawler.run(max_items=args.max))
