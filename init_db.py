"""Initialize database with tables and default RSS sources"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import init_db, SessionLocal
from models import NewsSource
from config import RSS_SOURCES


def seed_sources():
    """Insert default RSS sources if table is empty"""
    db = SessionLocal()
    count = db.query(NewsSource).count()
    if count == 0:
        for src in RSS_SOURCES:
            db.add(NewsSource(
                name=src["name"],
                feed_url=src["url"],
                lang=src["lang"],
                default_category=src["default_category"],
            ))
        db.commit()
        print(f"  Seeded {len(RSS_SOURCES)} RSS sources")
    else:
        print(f"  {count} sources already exist, skipping")
    db.close()


if __name__ == "__main__":
    print("[1/2] Creating database tables...")
    init_db()
    print("  Done!")
    print("[2/2] Seeding default RSS sources...")
    seed_sources()
    print("\nDatabase initialized at: data/news.db")
