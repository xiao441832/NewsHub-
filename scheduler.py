"""NewsHub Scheduler - 持久化定时任务 + 零崩溃爬虫调度

修复要点：
1. 使用 SQLAlchemyJobStore 替代默认 MemoryJobStore，重启不丢失任务
2. 设置 misfire_grace_time=3600，即使错过执行窗口也能补跑
3. 设置 coalesce=True，避免堆积多次执行
4. 设置 max_instances=1，防止重复执行
5. crawl_job 全局 try/except，任何异常都不会中断调度器
"""
import sys
import os

# 修复 Windows 控制台编码问题
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from config import CRAWL_INTERVAL_HOURS, DB_PATH

# 全局调度器实例，供 main.py 调用
_scheduler = None


def get_scheduler():
    """获取全局调度器实例"""
    return _scheduler


def crawl_job():
    """执行一次完整的多源爬取任务（零崩溃设计）"""
    try:
        _do_crawl()
    except Exception as e:
        # 最外层兜底：任何未预期的异常都捕获，绝不让调度器停止
        print(f"\n[Scheduler] ❌ 爬取任务发生未预期异常: {e}")
        import traceback
        traceback.print_exc()


def _do_crawl():
    """实际爬取逻辑（与异常捕获分离，便于测试和手动调用）"""
    from crawlers.multi_crawler import crawl_source, crawl_all_sources, save_to_db, fetch_missing_content
    from database import SessionLocal
    from models import NewsSource, NewsArticle, CrawlLog
    from config import NEWS_SOURCES
    from datetime import datetime
    import time

    print(f"\n[Scheduler] {'='*50}")
    print(f"[Scheduler] 开始爬取任务 — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"[Scheduler] 共 {len(NEWS_SOURCES)} 个新闻源")
    print(f"[Scheduler] {'='*50}")

    db = SessionLocal()

    # 确保所有新闻源都存在于数据库中
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

    # 逐源爬取并记录日志
    total_new = 0
    total_found = 0
    success_count = 0
    error_count = 0
    failed_sources = []
    zero_result_sources = []

    for src in NEWS_SOURCES:
        start_time = time.time()
        # 确保 session 事务干净
        try:
            db.rollback()
        except Exception:
            pass
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

            # 保存到数据库
            new_count = save_to_db(articles, db)
            log_entry.new_articles = new_count
            total_new += new_count
            success_count += 1

            # 更新源统计
            source = db.query(NewsSource).filter(NewsSource.name == src["name"]).first()
            if source:
                source.article_count = db.query(NewsArticle).filter(
                    NewsArticle.source == src["name"]
                ).count()
                source.last_crawled_at = datetime.now()

            # 设置更精确的状态
            if found_count == 0:
                log_entry.status = "empty"
                zero_result_sources.append(src["name"])
                print(f"  🟡 {src['name']}: 发现 0 篇（空结果）")
            elif new_count == 0:
                log_entry.status = "success"
                print(f"  🔵 {src['name']}: 发现 {found_count} 篇，新增 0 篇（全部已存在）")
            else:
                log_entry.status = "success"
                print(f"  ✅ {src['name']}: 发现 {found_count} 篇，新增 {new_count} 篇")

        except Exception as e:
            log_entry.status = "error"
            log_entry.error_message = str(e)[:500]
            error_count += 1
            failed_sources.append((src["name"], str(e)[:100]))
            print(f"  ❌ {src['name']}: {e}")

        finally:
            log_entry.duration_seconds = int(time.time() - start_time)
            db.add(log_entry)

    db.commit()
    db.close()

    # 补充抓取缺失的正文内容
    try:
        fetch_missing_content(limit=15)
    except Exception as e:
        print(f"[Scheduler] 正文补充抓取异常: {e}")

    # 清除缓存，确保数据同步
    try:
        from cache import clear_cache
        clear_cache("api_tags")
        clear_cache("api_stats")
    except Exception as e:
        print(f"[Scheduler] 缓存清除异常: {e}")

    # 打印统计报告
    print(f"\n[Scheduler] {'='*50}")
    print(f"[Scheduler] 爬取完成!")
    print(f"  新闻源总数: {len(NEWS_SOURCES)}")
    print(f"  成功: {success_count} 个")
    print(f"  失败: {error_count} 个")
    print(f"  发现文章: {total_found} 篇")
    print(f"  新增文章: {total_new} 篇")

    if failed_sources:
        print(f"\n  ❌ 失败源详情:")
        for name, err in failed_sources:
            print(f"    - {name}: {err}")

    if zero_result_sources:
        print(f"\n  ⚠ 零结果源（可能选择器失效或被反爬）:")
        for name in zero_result_sources:
            print(f"    - {name}")

    print(f"[Scheduler] {'='*50}\n")

    return {"total_new": total_new, "total_found": total_found, "success": success_count, "error": error_count}


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


def get_scheduler_status():
    """获取调度器状态报告"""
    global _scheduler
    if not _scheduler:
        return {"status": "未启动", "jobs": []}

    jobs = []
    for job in _scheduler.get_jobs():
        jobs.append({
            "id": job.id,
            "name": job.name or job.id,
            "next_run": job.next_run_time.strftime("%Y-%m-%d %H:%M:%S") if job.next_run_time else "无",
            "trigger": str(job.trigger),
        })

    return {
        "status": "运行中" if _scheduler.running else "已停止",
        "jobs": jobs,
    }


def start_scheduler():
    """启动后台调度器（使用 SQLAlchemy 持久化存储）"""
    global _scheduler

    # 使用 SQLAlchemyJobStore 持久化任务，重启不丢失
    jobstores = {
        "default": SQLAlchemyJobStore(url=f"sqlite:///{DB_PATH}")
    }

    job_defaults = {
        "coalesce": True,              # 合并堆积的执行
        "max_instances": 1,            # 同一任务最多1个实例
        "misfire_grace_time": 3600,    # 错过执行窗口1小时内仍可补跑
    }

    _scheduler = BackgroundScheduler(
        jobstores=jobstores,
        job_defaults=job_defaults,
    )

    # 定时爬取任务：每 N 小时执行一次
    _scheduler.add_job(
        crawl_job,
        "interval",
        hours=CRAWL_INTERVAL_HOURS,
        id="news_crawl",
        name="新闻爬取",
        replace_existing=True,
    )

    # 每月清理旧新闻：每月 1 号凌晨 3:00 执行
    _scheduler.add_job(
        cleanup_job,
        CronTrigger(day=1, hour=3, minute=0),
        id="cleanup_old_articles",
        name="每月清理旧新闻",
        replace_existing=True,
    )

    _scheduler.start()

    # 打印任务状态
    for job in _scheduler.get_jobs():
        print(f"[Scheduler] 任务: {job.id} | 下次执行: {job.next_run_time}")

    print(f"[Scheduler] 调度器已启动（持久化存储: SQLAlchemy）")
    print(f"[Scheduler] 爬取间隔: 每 {CRAWL_INTERVAL_HOURS} 小时")

    return _scheduler


if __name__ == "__main__":
    print("Running one-time crawl job...")
    _do_crawl()
