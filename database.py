"""Database setup - SQLAlchemy engine + session"""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from config import DB_PATH

# Ensure data directory exists
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

engine = create_engine(f"sqlite:///{DB_PATH}", echo=False)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


def init_db():
    """Create all tables and migrate schema if needed"""
    from models import NewsArticle, NewsSource, User, Favorite, ReadHistory, Comment, CrawlLog  # noqa
    Base.metadata.create_all(bind=engine)

    # Simple migration: add missing columns to existing tables
    _migrate_schema()

    # 创建性能索引
    _create_indexes()

    # 初始化管理员账号
    init_admin_user()


def _migrate_schema():
    """Add columns that may not exist in older databases."""
    import sqlite3
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Check existing columns in news_articles
    cursor.execute("PRAGMA table_info(news_articles)")
    columns = {row[1] for row in cursor.fetchall()}

    if "tags" not in columns:
        cursor.execute("ALTER TABLE news_articles ADD COLUMN tags TEXT DEFAULT ''")
        print("[DB] Added 'tags' column to news_articles")

    # Check existing columns in users
    cursor.execute("PRAGMA table_info(users)")
    user_columns = {row[1] for row in cursor.fetchall()}

    if "is_admin" not in user_columns:
        cursor.execute("ALTER TABLE users ADD COLUMN is_admin BOOLEAN DEFAULT 0")
        print("[DB] Added 'is_admin' column to users")

    conn.commit()
    conn.close()


def init_admin_user():
    """初始化管理员账号（首次运行时将配置中的用户设为管理员）"""
    from config import ADMIN_USERS
    if not ADMIN_USERS:
        return

    import sqlite3
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    for username in ADMIN_USERS:
        cursor.execute("UPDATE users SET is_admin = 1 WHERE username = ?", (username,))
        if cursor.rowcount > 0:
            print(f"[DB] 已将用户 '{username}' 设为管理员")

    conn.commit()
    conn.close()


def _create_indexes():
    """创建性能索引（幂等操作，IF NOT EXISTS）"""
    import sqlite3
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    indexes = [
        # news_articles 表索引
        ("idx_articles_published_at", "news_articles", "(published_at DESC)"),
        ("idx_articles_category_dup", "news_articles", "(category, is_duplicate)"),
        ("idx_articles_source_created", "news_articles", "(source, created_at DESC)"),
        ("idx_articles_created_at", "news_articles", "(created_at DESC)"),

        # favorites 表复合索引
        ("idx_favorites_user_article", "favorites", "(user_id, article_id)"),
        ("idx_favorites_created", "favorites", "(created_at DESC)"),

        # read_history 表复合索引
        ("idx_history_user_read", "read_history", "(user_id, read_at DESC)"),
        ("idx_history_user_article", "read_history", "(user_id, article_id)"),

        # comments 表索引
        ("idx_comments_article_created", "comments", "(article_id, created_at DESC)"),

        # crawl_logs 表索引
        ("idx_crawled_at", "crawl_logs", "(crawled_at DESC)"),
        ("idx_crawl_source", "crawl_logs", "(source_name, crawled_at DESC)"),
    ]

    created = 0
    for idx_name, table, cols in indexes:
        try:
            cursor.execute(f"CREATE INDEX IF NOT EXISTS {idx_name} ON {table} {cols}")
            created += 1
        except Exception as e:
            print(f"[DB] 索引 {idx_name} 创建跳过: {e}")

    conn.commit()
    conn.close()
    print(f"[DB] 索引检查完成（{created} 个索引）")


def get_db():
    """Get a database session (for dependency injection)"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
