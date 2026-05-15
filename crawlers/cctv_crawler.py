"""CCTV News Crawler - fetches news from央视网 API"""
import sys
import os
import json
import re
from datetime import datetime
from typing import List, Dict, Optional

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import USER_AGENT, MAX_ARTICLES_PER_SOURCE


# CCTV category API endpoints
CCTV_CATEGORIES = {
    "china": {
        "name": "央视·国内",
        "category": "china",
        "url": "https://news.cctv.com/2019/07/gaiban/cmsdatainterface/page/china_{page}.jsonp",
    },
    "world": {
        "name": "央视·国际",
        "category": "international",
        "url": "https://news.cctv.com/2019/07/gaiban/cmsdatainterface/page/world_{page}.jsonp",
    },
    "tech": {
        "name": "央视·科技",
        "category": "tech",
        "url": "https://news.cctv.com/2019/07/gaiban/cmsdatainterface/page/tech_{page}.jsonp",
    },
    "society": {
        "name": "央视·社会",
        "category": "local",
        "url": "https://news.cctv.com/2019/07/gaiban/cmsdatainterface/page/society_{page}.jsonp",
    },
}


def fetch_cctv_category(cat_key: str, pages: int = 2) -> List[Dict]:
    """Fetch articles from a CCTV category API"""
    cat_info = CCTV_CATEGORIES[cat_key]
    articles = []

    for page in range(1, pages + 1):
        url = cat_info["url"].format(page=page)
        try:
            resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=10)
            resp.raise_for_status()
            resp.encoding = 'utf-8'  # Force UTF-8 encoding

            # Parse JSONP: category({...})
            match = re.search(r'\{.*\}', resp.text, re.DOTALL)
            if not match:
                continue

            data = json.loads(match.group())
            article_list = data.get("data", {}).get("list", [])

            for item in article_list:
                title = item.get("title", "").strip()
                article_url = item.get("url", "").strip()
                if not title or not article_url:
                    continue

                articles.append({
                    "title": title,
                    "url": article_url,
                    "source": cat_info["name"],
                    "category": cat_info["category"],
                    "summary": item.get("brief", "").strip(),
                    "image_url": item.get("image", "").strip(),
                    "published_at": item.get("focus_date", ""),
                })

        except Exception as e:
            print(f"  ⚠ Error fetching {cat_key} page {page}: {e}")

    return articles[:MAX_ARTICLES_PER_SOURCE]


def fetch_article_content(url: str) -> Optional[str]:
    """Fetch full article text from a CCTV article page"""
    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=10)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        # Remove scripts and styles
        for tag in soup(["script", "style", "nav", "header", "footer"]):
            tag.decompose()

        # Try to find article content div
        content_div = soup.find("div", {"id": "content_area"})
        if not content_div:
            content_div = soup.find("div", class_=re.compile(r"content|article|body"))

        if content_div:
            paragraphs = content_div.find_all("p")
            text = "\n".join(p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 10)
            return text[:3000]

        # Fallback: extract all text
        text = soup.get_text(separator="\n", strip=True)
        return text[:3000]

    except Exception as e:
        print(f"  ⚠ Failed to fetch article: {e}")
        return None


def crawl_all_cctv() -> List[Dict]:
    """Crawl all CCTV categories"""
    all_articles = []
    for cat_key in CCTV_CATEGORIES:
        print(f"  → {CCTV_CATEGORIES[cat_key]['name']}...", end=" ", flush=True)
        articles = fetch_cctv_category(cat_key, pages=2)
        all_articles.extend(articles)
        print(f"{len(articles)} articles")

    # Deduplicate by URL
    seen = set()
    unique = []
    for art in all_articles:
        if art["url"] not in seen:
            seen.add(art["url"])
            unique.append(art)

    print(f"\n  Total: {len(unique)} unique articles")
    return unique


def save_to_db(articles: List[Dict], db) -> int:
    """Save articles to database, skip duplicates"""
    from models import NewsArticle

    new_count = 0
    for art in articles:
        existing = db.query(NewsArticle).filter(NewsArticle.url == art["url"]).first()
        if existing:
            continue

        article = NewsArticle(
            title=art["title"],
            url=art["url"],
            source=art["source"],
            category=art["category"],
            summary=art.get("summary", ""),
            image_url=art.get("image_url", ""),
            published_at=_parse_date(art.get("published_at")),
        )
        db.add(article)
        new_count += 1

    db.commit()
    return new_count


def _parse_date(date_str: str) -> Optional[datetime]:
    """Parse date string from CCTV API"""
    if not date_str:
        return None
    for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"]:
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except ValueError:
            continue
    return None


if __name__ == "__main__":
    print("=== CCTV News Crawler ===")

    # Init DB
    from database import init_db, SessionLocal
    from models import NewsSource
    from config import RSS_SOURCES

    init_db()
    db = SessionLocal()

    # Ensure sources exist
    for cat_key, cat_info in CCTV_CATEGORIES.items():
        existing = db.query(NewsSource).filter(NewsSource.name == cat_info["name"]).first()
        if not existing:
            db.add(NewsSource(
                name=cat_info["name"],
                feed_url=cat_info["url"],
                source_type="api",
                lang="zh",
                default_category=cat_info["category"],
            ))
    db.commit()

    # Crawl
    articles = crawl_all_cctv()

    # Save
    new_count = save_to_db(articles, db)

    # Update source counts
    from models import NewsArticle as _NA
    for cat_key, cat_info in CCTV_CATEGORIES.items():
        source = db.query(NewsSource).filter(NewsSource.name == cat_info["name"]).first()
        if source:
            source.article_count = db.query(_NA).filter(
                _NA.source == cat_info["name"]
            ).count()
            source.last_crawled_at = datetime.now()
    db.commit()

    # Stats
    from models import NewsArticle
    total = db.query(NewsArticle).count()
    cats = {}
    for a in db.query(NewsArticle).all():
        cats[a.category] = cats.get(a.category, 0) + 1

    db.close()

    print(f"\nDone! {new_count} new articles. Total: {total}")
    for k, v in cats.items():
        print(f"  {k}: {v}")
