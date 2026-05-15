"""NewsHub - 每月自动清理旧新闻模块

清理策略：
- 保留最近 30 天内的新闻
- 保留已被用户收藏的新闻
- 至少保留最近 100 条新闻
- 级联删除关联的评论、阅读记录、收藏记录
"""
import logging
from datetime import datetime, timedelta
from sqlalchemy import func
from sqlalchemy.orm import Session

from models import NewsArticle, Favorite, ReadHistory, Comment

# 配置日志
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("cleanup")

# 安全保护：绝对底线天数（不可配置，硬编码保护）
ABSOLUTE_MIN_DAYS = 7

# 安全保护：单次删除上限
MAX_DELETE_PER_RUN = 1000

# 安全保护：警告阈值
WARN_THRESHOLD = 500


def cleanup_old_articles(db: Session, keep_days: int = 30, keep_recent: int = 100):
    """
    清理旧新闻

    参数:
        db: SQLAlchemy 数据库会话
        keep_days: 保留最近 N 天的新闻（默认 30 天）
        keep_recent: 至少保留最近 N 条新闻（默认 100 条）

    返回:
        (删除数量, 错误信息)
        成功时错误信息为空字符串
    """
    try:
        # ═══════════════════════════════════════════════
        # 第一步：安全检查 — 强制底线保护
        # ═══════════════════════════════════════════════
        if keep_days < ABSOLUTE_MIN_DAYS:
            logger.warning(f"keep_days={keep_days} 低于绝对底线 {ABSOLUTE_MIN_DAYS} 天，已自动调整为 {ABSOLUTE_MIN_DAYS} 天")
            keep_days = ABSOLUTE_MIN_DAYS

        cutoff_date = datetime.utcnow() - timedelta(days=keep_days)
        logger.info(f"开始清理旧新闻：截止日期 {cutoff_date.strftime('%Y-%m-%d %H:%M:%S')}")

        # ═══════════════════════════════════════════════
        # 第二步：统计当前数据库状态
        # ═══════════════════════════════════════════════
        total_articles = db.query(func.count(NewsArticle.id)).scalar()
        logger.info(f"当前数据库共有 {total_articles} 篇文章")

        # ═══════════════════════════════════════════════
        # 第三步：查询已被收藏的文章 ID 列表（去重）
        # ═══════════════════════════════════════════════
        favorited_ids = [
            row[0] for row in db.query(Favorite.article_id).distinct().all()
        ]
        logger.info(f"被收藏的文章数量: {len(favorited_ids)}")

        # ═══════════════════════════════════════════════
        # 第四步：查询最近 N 条新闻的 ID 列表
        # ═══════════════════════════════════════════════
        recent_ids = [
            row[0] for row in db.query(NewsArticle.id)
            .order_by(NewsArticle.created_at.desc())
            .limit(keep_recent)
            .all()
        ]
        logger.info(f"最近 {keep_recent} 条新闻的 ID 范围: {min(recent_ids) if recent_ids else 'N/A'} ~ {max(recent_ids) if recent_ids else 'N/A'}")

        # ═══════════════════════════════════════════════
        # 第五步：构建删除查询
        # 条件：
        #   1. created_at < cutoff_date（超过保留天数）
        #   2. id NOT IN (收藏列表)
        #   3. id NOT IN (最近N条列表)
        # ═══════════════════════════════════════════════
        # 合并需要排除的 ID 集合
        protected_ids = set(favorited_ids) | set(recent_ids)

        query = db.query(NewsArticle).filter(
            NewsArticle.created_at < cutoff_date
        )

        # 如果有需要排除的 ID，添加 NOT IN 条件
        if protected_ids:
            query = query.filter(NewsArticle.id.notin_(protected_ids))

        # 查询待删除的文章（用于日志记录）
        articles_to_delete = query.all()
        delete_count = len(articles_to_delete)

        if delete_count == 0:
            logger.info("没有需要清理的旧新闻")
            return 0, ""

        # ═══════════════════════════════════════════════
        # 第六步：安全保护 — 检查删除数量
        # ═══════════════════════════════════════════════
        if delete_count > WARN_THRESHOLD:
            logger.warning(f"⚠️ 警告：本次将删除 {delete_count} 条新闻，超过警告阈值 {WARN_THRESHOLD}")

        # 应用单次删除上限
        if delete_count > MAX_DELETE_PER_RUN:
            logger.warning(f"删除数量 {delete_count} 超过上限 {MAX_DELETE_PER_RUN}，将只删除前 {MAX_DELETE_PER_RUN} 条")
            articles_to_delete = articles_to_delete[:MAX_DELETE_PER_RUN]
            delete_count = MAX_DELETE_PER_RUN

        # 记录待删除的文章标题和 ID（用于审计）
        for art in articles_to_delete[:20]:  # 最多记录前 20 条
            logger.info(f"  待删除: [ID={art.id}] {art.title[:50]}...")

        if delete_count > 20:
            logger.info(f"  ... 还有 {delete_count - 20} 条待删除")

        # ═══════════════════════════════════════════════
        # 第七步：级联删除关联数据
        # 顺序：先删关联表，再删主表
        # ═══════════════════════════════════════════════
        article_ids_to_delete = [art.id for art in articles_to_delete]

        # 7.1 删除关联的评论
        comments_deleted = db.query(Comment).filter(
            Comment.article_id.in_(article_ids_to_delete)
        ).delete(synchronize_session=False)
        logger.info(f"  删除关联评论: {comments_deleted} 条")

        # 7.2 删除关联的阅读记录
        history_deleted = db.query(ReadHistory).filter(
            ReadHistory.article_id.in_(article_ids_to_delete)
        ).delete(synchronize_session=False)
        logger.info(f"  删除关联阅读记录: {history_deleted} 条")

        # 7.3 删除关联的收藏记录（虽然按规则不会删已收藏的，但代码要健壮）
        favorites_deleted = db.query(Favorite).filter(
            Favorite.article_id.in_(article_ids_to_delete)
        ).delete(synchronize_session=False)
        logger.info(f"  删除关联收藏记录: {favorites_deleted} 条")

        # 7.4 删除文章主表
        db.query(NewsArticle).filter(
            NewsArticle.id.in_(article_ids_to_delete)
        ).delete(synchronize_session=False)

        # ═══════════════════════════════════════════════
        # 第八步：提交事务
        # ═══════════════════════════════════════════════
        db.commit()

        # 统计剩余文章数
        remaining = db.query(func.count(NewsArticle.id)).scalar()
        logger.info(f"✅ 清理完成：本次删除 {delete_count} 篇旧新闻，剩余 {remaining} 篇")

        return delete_count, ""

    except Exception as e:
        # 回滚事务
        db.rollback()
        error_msg = f"清理旧新闻时发生错误: {str(e)}"
        logger.error(f"❌ {error_msg}")
        return 0, error_msg


def get_cleanup_stats(db: Session, keep_days: int = 30, keep_recent: int = 100):
    """
    获取清理统计信息（不执行删除，只统计）

    返回:
        dict: 包含统计信息的字典
    """
    cutoff_date = datetime.utcnow() - timedelta(days=keep_days)

    # 总文章数
    total = db.query(func.count(NewsArticle.id)).scalar()

    # 被收藏的文章数
    favorited_ids = [
        row[0] for row in db.query(Favorite.article_id).distinct().all()
    ]

    # 最近 N 条文章 ID
    recent_ids = [
        row[0] for row in db.query(NewsArticle.id)
        .order_by(NewsArticle.created_at.desc())
        .limit(keep_recent)
        .all()
    ]

    protected_ids = set(favorited_ids) | set(recent_ids)

    # 可清理的文章数
    deletable = db.query(func.count(NewsArticle.id)).filter(
        NewsArticle.created_at < cutoff_date,
        NewsArticle.id.notin_(protected_ids) if protected_ids else True,
    ).scalar()

    return {
        "total_articles": total,
        "favorited_count": len(favorited_ids),
        "recent_protected": len(recent_ids),
        "deletable_articles": deletable,
        "cutoff_date": cutoff_date.strftime("%Y-%m-%d %H:%M:%S"),
        "keep_days": keep_days,
        "keep_recent": keep_recent,
    }


if __name__ == "__main__":
    """手动执行清理（用于测试）"""
    from database import init_db, SessionLocal

    print("=" * 60)
    print("  NewsHub 旧新闻清理工具")
    print("=" * 60)

    init_db()
    db = SessionLocal()

    # 先显示统计信息
    stats = get_cleanup_stats(db)
    print(f"\n📊 当前统计:")
    print(f"   总文章数:     {stats['total_articles']}")
    print(f"   被收藏文章:   {stats['favorited_count']}")
    print(f"   最近保护:     {stats['recent_protected']} 条")
    print(f"   可清理文章:   {stats['deletable_articles']} 条")
    print(f"   截止日期:     {stats['cutoff_date']}")

    if stats["deletable_articles"] == 0:
        print("\n✅ 没有需要清理的旧新闻")
        db.close()
        exit(0)

    # 确认删除
    confirm = input(f"\n确认删除 {stats['deletable_articles']} 条旧新闻？(yes/no): ")
    if confirm.lower() != "yes":
        print("已取消")
        db.close()
        exit(0)

    # 执行清理
    deleted, error = cleanup_old_articles(db)
    if error:
        print(f"\n❌ 清理失败: {error}")
    else:
        print(f"\n✅ 清理完成，删除 {deleted} 条旧新闻")

    db.close()
