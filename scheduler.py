"""NewsHub Scheduler - auto-crawl every N hours + monthly cleanup"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from config import CRAWL_INTERVAL_HOURS


def crawl_job():
    """Run multi-source crawl + AI summarization"""
    from crawlers.multi_crawler import crawl_all_sources, save_to_db
    from database import SessionLocal
    from models import NewsSource, NewsArticle, CrawlLog
    from config import NEWS_SOURCES
    from datetime import datetime
    import time

    print("\n[Scheduler] Starting multi-source crawl...")

    db = SessionLocal()

    # Ensure all sources exist
    for src in NEWS_SOURCES:
        existing = db.query(NewsSource).filter(NewsSource.name == src["name"]).first()
        if not existing:
            db.add(NewsSource(
                name=src["name"],
                feed_url=src["url"],
                source_type=src["type"],
                lang=src.get("lang", "zh"),
                default_category=src["category"],
            ))
    db.commit()

    # Crawl each source individually and log results
    from crawlers.multi_crawler import crawl_source
    total_new = 0
    total_found = 0

    for src in NEWS_SOURCES:
        start_time = time.time()
        log_entry = CrawlLog(
            source_name=src["name"],
            status="success",
            articles_found=0,
            new_articles=0,
            error_message="",
            duration_seconds=0,
        )

        try:
            articles = crawl_source(src)
            found_count = len(articles)
            total_found += found_count
            log_entry.articles_found = found_count

            # Save to DB
            new_count = save_to_db(articles, db)
            log_entry.new_articles = new_count
            total_new += new_count

            # Update source stats
            source = db.query(NewsSource).filter(NewsSource.name == src["name"]).first()
            if source:
                source.article_count = db.query(NewsArticle).filter(
                    NewsArticle.source == src["name"]
                ).count()
                source.last_crawled_at = datetime.now()

            print(f"  ✅ {src['name']}: {new_count} new articles")

        except Exception as e:
            log_entry.status = "error"
            log_entry.error_message = str(e)[:500]
            print(f"  ❌ {src['name']}: {e}")

        finally:
            log_entry.duration_seconds = int(time.time() - start_time)
            db.add(log_entry)

    db.commit()

    # Notify breaking news
    try:
        from notifier import notify_new_article
        # Get recently added articles for notification
        recent_articles = db.query(NewsArticle).filter(
            NewsArticle.created_at >= datetime.now()
        ).all()
        for art in recent_articles:
            notify_new_article(art.title, art.source, art.category, art.url)
    except Exception as e:
        print(f"[Scheduler] Notification error: {e}")

    db.close()

    # Fetch missing article content
    try:
        from crawlers.multi_crawler import fetch_missing_content
        fetch_missing_content(limit=15)
    except Exception as e:
        print(f"[Scheduler] Content fetch error: {e}")

    print(f"[Scheduler] Done! {total_new} new articles added from {total_found} found.\n")
    if total_new > 0:
        try:
            from cache import clear_cache
            clear_cache("api_tags")
            clear_cache("api_stats")
        except Exception as e:
            print(f"[Scheduler] Cache clear error: {e}")


def cleanup_job():
    """每月清理旧新闻任务"""
    from database import SessionLocal
    from cleanup_old_news import cleanup_old_articles

    print("\n[Scheduler] 开始执行每月旧新闻清理任务...")

    db = SessionLocal()
    try:
        deleted, error = cleanup_old_articles(db)
        if error:
            print(f"[Scheduler] ❌ 清理失败: {error}")
        else:
            print(f"[Scheduler] ✅ 清理完成，本次删除 {deleted} 条旧新闻")
    except Exception as e:
        print(f"[Scheduler] ❌ 清理任务异常: {e}")
    finally:
        db.close()


def start_scheduler():
    """Start the background scheduler"""
    scheduler = BackgroundScheduler()

    # 定时爬取任务：每 N 小时执行一次
    scheduler.add_job(crawl_job, "interval", hours=CRAWL_INTERVAL_HOURS, id="news_crawl")

    # 每月清理旧新闻：每月 1 号凌晨 3:00 执行
    cleanup_trigger = CronTrigger(day=1, hour=3, minute=0)
    scheduler.add_job(
        cleanup_job,
        cleanup_trigger,
        id="cleanup_old_articles",
        name="每月清理旧新闻",
        replace_existing=True,
    )

    scheduler.start()

    # 打印下次执行时间
    next_crawl = scheduler.get_job("news_crawl").next_run_time
    next_cleanup = scheduler.get_job("cleanup_old_articles").next_run_time
    print(f"[Scheduler] Auto-crawl every {CRAWL_INTERVAL_HOURS} hours")
    print(f"[Scheduler] 下次爬取时间: {next_crawl.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"[Scheduler] 下次清理时间: {next_cleanup.strftime('%Y-%m-%d %H:%M:%S')}")

    return scheduler


if __name__ == "__main__":
    print("Running one-time crawl job...")
    crawl_job()
