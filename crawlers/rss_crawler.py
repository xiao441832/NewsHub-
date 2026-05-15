"""RSS Crawler - fetches articles from news RSS feeds"""
import sys
import os
import re
from datetime import datetime, timezone
from typing import List, Dict, Optional
from urllib.parse import urlparse

import feedparser
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import RSS_SOURCES, REQUEST_TIMEOUT, USER_AGENT, MAX_ARTICLES_PER_SOURCE
from database import SessionLocal, init_db
from models import NewsArticle, NewsSource


def clean_html(text: str) -> str:
    """Strip HTML tags from text"""
    if not text:
        return ""
    return re.sub(r'<[^>]+>', '', text).strip()


def extract_image(entry) -> Optional[str]:
    """Try to extract image URL from an RSS entry"""
    # media:content
    if hasattr(entry, 'media_content') and entry.media_content:
        for media in entry.media_content:
            if media.get('medium') == 'image' or 'image' in media.get('type', ''):
                return media.get('url')
    # media:thumbnail
    if hasattr(entry, 'media_thumbnail') and entry.media_thumbnail:
        return entry.media_thumbnail[0].get('url')
    # enclosure
    if hasattr(entry, 'enclosures') and entry.enclosures:
        for enc in entry.enclosures:
            if 'image' in enc.get('type', ''):
                return enc.get('href')
    # Parse from content
    if hasattr(entry, 'content') and entry.content:
        match = re.search(r'<img[^>]+src="([^"]+)"', entry.content[0].get('value', ''))
        if match:
            return match.group(1)
    return None


def parse_date(entry) -> Optional[datetime]:
    """Parse published date from entry"""
    for field in ['published_parsed', 'updated_parsed']:
        parsed = getattr(entry, field, None)
        if parsed:
            try:
                return datetime(*parsed[:6], tzinfo=timezone.utc)
            except:
                pass
    return None


def fetch_rss(source: Dict) -> List[Dict]:
    """Fetch articles from a single RSS source"""
    articles = []
    try:
        resp = requests.get(
            source["url"],
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT
        )
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)
    except Exception as e:
        print(f"  ⚠ Bad feed for {source['name']}: {e}")
        return []

    for entry in feed.entries[:MAX_ARTICLES_PER_SOURCE]:
        title = clean_html(getattr(entry, 'title', ''))
        if not title:
            continue

        url = getattr(entry, 'link', '')
        if not url:
            continue

        desc = clean_html(getattr(entry, 'summary', '') or getattr(entry, 'description', ''))
        if len(desc) > 500:
            desc = desc[:500] + "..."

        articles.append({
            "title": title,
            "url": url,
            "source": source["name"],
            "category": source["category"],
            "summary": desc,
            "content": desc,
            "image_url": extract_image(entry),
            "published_at": parse_date(entry),
        })

    return articles


def fetch_cctv_news() -> List[Dict]:
    """Fetch CCTV news by scraping their roll page"""
    articles = []
    try:
        resp = requests.get(
            "https://news.cctv.com/cctvnews_roll/index.shtml",
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT
        )
        resp.raise_for_status()
        # Extract links with titles from the page
        links = re.findall(r'<a[^>]+href="(https?://news\.cctv\.com/[^"]+)"[^>]*>([^<]+)</a>', resp.text)
        seen = set()
        for url, title in links[:20]:
            title = title.strip()
            if len(title) < 5 or url in seen:
                continue
            seen.add(url)
            articles.append({
                "title": title,
                "url": url,
                "source": "央视新闻",
                "category": "china",
                "summary": "",
                "content": "",
                "image_url": None,
                "published_at": datetime.now(timezone.utc),
            })
    except Exception as e:
        print(f"  ⚠ Failed to fetch CCTV: {e}")
    return articles


def crawl_source(source: Dict) -> List[Dict]:
    """Crawl a single source based on its type"""
    if source.get("type") == "web" and "cctv" in source["url"]:
        return fetch_cctv_news()
    return fetch_rss(source)


def save_articles(articles: List[Dict], db) -> int:
    """Save articles to database, skipping duplicates"""
    new_count = 0
    for art_data in articles:
        exists = db.query(NewsArticle).filter(NewsArticle.url == art_data["url"]).first()
        if exists:
            continue

        article = NewsArticle(
            title=art_data["title"],
            url=art_data["url"],
            source=art_data["source"],
            category=art_data["category"],
            summary=art_data["summary"],
            content=art_data["content"],
            image_url=art_data.get("image_url", ""),
            published_at=art_data.get("published_at"),
        )
        db.add(article)
        new_count += 1
    return new_count


def update_source_stats(source_name: str, db):
    """Update source's last crawled time and article count"""
    source = db.query(NewsSource).filter(NewsSource.name == source_name).first()
    if source:
        source.last_crawled_at = datetime.now(timezone.utc)
        source.article_count = db.query(NewsArticle).filter(NewsArticle.source == source_name).count()


def crawl_all():
    """Crawl all enabled sources"""
    init_db()
    db = SessionLocal()

    # Sync sources from config
    for src_cfg in RSS_SOURCES:
        existing = db.query(NewsSource).filter(NewsSource.name == src_cfg["name"]).first()
        if not existing:
            db.add(NewsSource(
                name=src_cfg["name"],
                feed_url=src_cfg["url"],
                source_type=src_cfg.get("type", "rss"),
                lang=src_cfg["lang"],
                default_category=src_cfg["category"],
            ))
    db.commit()

    sources = db.query(NewsSource).filter(NewsSource.enabled == True).all()
    print(f"Crawling {len(sources)} sources...")

    total_new = 0
    for source in sources:
        # Find config for this source
        src_cfg = next((s for s in RSS_SOURCES if s["name"] == source.name), None)
        if not src_cfg:
            continue

        print(f"  → {source.name}...", end=" ", flush=True)
        articles = crawl_source(src_cfg)
        new_count = save_articles(articles, db)
        update_source_stats(source.name, db)
        total_new += new_count
        total = db.query(NewsArticle).filter(NewsArticle.source == source.name).count()
        print(f"{new_count} new / {total} total")

    db.commit()
    db.close()
    print(f"\nDone! {total_new} new articles added.")


if __name__ == "__main__":
    crawl_all()
