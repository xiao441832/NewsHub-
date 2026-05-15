"""Quick crawl - fast sources only"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from crawlers.rss_crawler import fetch_rss, save_articles
from database import SessionLocal, init_db
from models import NewsSource, NewsArticle
from config import RSS_SOURCES

# Fast, reliable sources only
FAST_NAMES = [
    "TechCrunch", "Hacker News", "The Verge", "36Kr", "Ars Technica", "少数派",
    "BBC News", "Reuters", "CNN", "Al Jazeera",
    "新华社", "环球网",
]

if __name__ == "__main__":
    init_db()
    db = SessionLocal()

    # Sync sources
    for src_cfg in RSS_SOURCES:
        existing = db.query(NewsSource).filter(NewsSource.name == src_cfg["name"]).first()
        if not existing:
            db.add(NewsSource(
                name=src_cfg["name"], feed_url=src_cfg["url"],
                source_type=src_cfg.get("type", "rss"),
                lang=src_cfg["lang"], default_category=src_cfg["category"]
            ))
    db.commit()

    total_new = 0
    for src in RSS_SOURCES:
        if src["name"] not in FAST_NAMES:
            print(f"  ⏭ {src['name']} (skipped - slow)")
            continue

        print(f"  → {src['name']}...", end=" ", flush=True)
        try:
            articles = fetch_rss(src)
            new = save_articles(articles, db)
            db.commit()
            total_new += new
            total = db.query(NewsArticle).filter(NewsArticle.source == src["name"]).count()
            print(f"{new} new / {total} total")
        except Exception as e:
            print(f"ERR: {e}")

    from models import NewsArticle
    total = db.query(NewsArticle).count()
    cats = {}
    for a in db.query(NewsArticle).all():
        cats[a.category] = cats.get(a.category, 0) + 1

    db.close()
    print(f"\nDone! {total_new} new articles. Total: {total}")
    for k, v in cats.items():
        print(f"  {k}: {v}")
