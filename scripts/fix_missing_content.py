#!/usr/bin/env python3
"""
修复数据库中 content 为空的文章 — 补充抓取正文内容

用法:
    python scripts/fix_missing_content.py              # 处理所有空 content 文章
    python scripts/fix_missing_content.py --limit 50   # 只处理最近 50 篇
    python scripts/fix_missing_content.py --dry-run    # 只统计不修改
"""
import sys
import os
import argparse
import time
from datetime import datetime

# 修复 Windows 控制台编码问题
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import init_db, SessionLocal
from models import NewsArticle
from crawlers.multi_crawler import extract_article_content, extract_summary, fallback_summary
from config import NEWS_SOURCES


def count_missing(db):
    """统计 content 为空的文章数量"""
    total = db.query(NewsArticle).filter(
        NewsArticle.is_duplicate == False
    ).count()

    has_content = db.query(NewsArticle).filter(
        NewsArticle.is_duplicate == False,
        NewsArticle.content != None,
        NewsArticle.content != ""
    ).count()

    missing = db.query(NewsArticle).filter(
        NewsArticle.is_duplicate == False,
        (NewsArticle.content == None) | (NewsArticle.content == "")
    ).count()

    return total, has_content, missing


def fix_missing_content(limit: int = 0, dry_run: bool = False):
    """修复 content 为空的文章"""
    db = SessionLocal()

    # 统计当前状态
    total, has_content, missing = count_missing(db)
    print(f"\n{'='*60}")
    print(f"  NewsHub 正文修复工具")
    print(f"{'='*60}")
    print(f"  📊 数据库统计:")
    print(f"     总文章数:   {total}")
    print(f"     已有正文:   {has_content}")
    print(f"     缺失正文:   {missing}")
    print(f"{'='*60}\n")

    if missing == 0:
        print("  ✅ 所有文章已有正文内容，无需修复！")
        db.close()
        return

    if dry_run:
        print("  🔍 [DRY RUN] 只统计不修改")
        # 按来源分组统计
        from sqlalchemy import func
        stats = db.query(
            NewsArticle.source,
            func.count(NewsArticle.id)
        ).filter(
            NewsArticle.is_duplicate == False,
            (NewsArticle.content == None) | (NewsArticle.content == "")
        ).group_by(NewsArticle.source).all()

        print(f"\n  按来源分布:")
        for source, count in stats:
            print(f"     {source}: {count} 篇")
        db.close()
        return

    # 查询需要修复的文章
    query = db.query(NewsArticle).filter(
        NewsArticle.is_duplicate == False,
        (NewsArticle.content == None) | (NewsArticle.content == "")
    ).order_by(NewsArticle.created_at.desc())

    if limit > 0:
        query = query.limit(limit)

    articles = query.all()
    print(f"  📥 准备处理 {len(articles)} 篇文章...\n")

    # 构建新闻源配置查找表
    source_config_map = {src["name"]: src for src in NEWS_SOURCES}

    success = 0
    fallback = 0
    failed = 0
    start_time = time.time()

    for i, art in enumerate(articles):
        elapsed = time.time() - start_time
        avg_time = elapsed / max(i, 1)
        remaining = avg_time * (len(articles) - i)

        print(f"  [{i+1}/{len(articles)}] {art.title[:45]}...")
        print(f"           来源: {art.source} | 预计剩余: {int(remaining)}秒")

        try:
            src_cfg = source_config_map.get(art.source, None)
            html, plain, page_soup = extract_article_content(
                art.url, art.source, source_config=src_cfg
            )

            if plain and len(plain) > 50:
                # 正文抓取成功
                art.content = html[:50000]
                if not art.summary:
                    art.summary = extract_summary(page_soup, plain, art.title)
                success += 1
                print(f"           ✅ 抓取成功: {len(plain)} 字")
            else:
                # 正文抓取失败，设置兜底摘要
                if not art.summary:
                    art.summary = extract_summary(page_soup, "", art.title)
                art.content = ""
                fallback += 1
                print(f"           ⚠ 抓取失败，已设置兜底摘要")

        except Exception as e:
            failed += 1
            art.content = ""
            if not art.summary:
                art.summary = fallback_summary(art.title)
            print(f"           ❌ 出错: {e}")

        # 每 10 篇提交一次，避免丢失进度
        if (i + 1) % 10 == 0:
            db.commit()
            print(f"\n  💾 已保存进度 ({i+1}/{len(articles)})\n")

    # 最终提交
    db.commit()

    # 统计结果
    elapsed = time.time() - start_time
    total_after, has_content_after, missing_after = count_missing(db)

    print(f"\n{'='*60}")
    print(f"  📊 修复完成!")
    print(f"{'='*60}")
    print(f"  处理文章:   {len(articles)} 篇")
    print(f"  ✅ 成功:    {success} 篇")
    print(f"  ⚠ 兜底:    {fallback} 篇")
    print(f"  ❌ 失败:    {failed} 篇")
    print(f"  ⏱ 耗时:    {int(elapsed)} 秒")
    print(f"\n  修复前: 已有正文 {has_content} 篇, 缺失 {missing} 篇")
    print(f"  修复后: 已有正文 {has_content_after} 篇, 缺失 {missing_after} 篇")
    print(f"{'='*60}\n")

    db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="修复 NewsHub 缺失的新闻正文")
    parser.add_argument("--limit", type=int, default=0,
                        help="限制处理文章数量（0=全部）")
    parser.add_argument("--dry-run", action="store_true",
                        help="只统计不修改")
    args = parser.parse_args()

    init_db()
    fix_missing_content(limit=args.limit, dry_run=args.dry_run)
