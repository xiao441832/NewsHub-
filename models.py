"""Database models"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey, func
from sqlalchemy.orm import relationship
from database import Base
import re

# 垃圾摘要特征 — 匹配任意一个就认为是无效摘要
_JUNK_SUMMARY_PATTERNS = re.compile(
    r'(主管主办|提供全天候|打造了|成立于|创办于|隶属于|是.*旗下|'
    r'宗旨是|致力于|立足于|面向.*读者|本报.*讯|'
    r'版权所有|未经授权|转载请注明|关注.*公众号|'
    r'免责声明|广告合作|商务合作|联系我们|'
    r'由人民日报社|由新华社|由中央|全媒体|'
    r'集团旗下的|中国最大的|官方网站|'
    r'暂无摘要|暂无内容|无标题|'
    r'点击查看|了解更多|详情请|'
    r'ICP备|京公网安备|网络视听许可证)',
    re.IGNORECASE,
)


def _clean_summary(summary: str, title: str = "") -> str:
    """清洗摘要：过滤垃圾摘要，标题相同时返回空"""
    if not summary:
        return ""
    s = summary.strip()
    # 标题=摘要 → 空
    if title and s == title.strip():
        return ""
    # 垃圾摘要 → 空
    if _JUNK_SUMMARY_PATTERNS.search(s):
        return ""
    # 太短无意义
    if len(s) < 10:
        return ""
    return s


class NewsArticle(Base):
    __tablename__ = "news_articles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(500), nullable=False)
    url = Column(String(1000), unique=True, nullable=False, index=True)
    source = Column(String(100), nullable=False, index=True)
    category = Column(String(50), default="other", index=True)
    tags = Column(Text, default="")              # comma-separated tags
    summary = Column(Text, default="")          # AI generated summary
    content = Column(Text, default="")           # raw article text
    image_url = Column(String(1000), default="")
    published_at = Column(DateTime, nullable=True, index=True)
    created_at = Column(DateTime, default=func.now(), index=True)  # 添加索引用于清理查询
    is_duplicate = Column(Boolean, default=False)

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "url": self.url,
            "source": self.source,
            "category": self.category,
            "tags": self.tags or "",
            "summary": _clean_summary(self.summary or "", self.title or ""),
            "image_url": self.image_url or "",
            "published_at": self.published_at.strftime("%Y-%m-%d %H:%M") if self.published_at else "",
        }


class NewsSource(Base):
    __tablename__ = "news_sources"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), unique=True, nullable=False)
    feed_url = Column(String(1000), nullable=False)
    source_type = Column(String(20), default="rss")  # rss / web
    lang = Column(String(10), default="en")
    default_category = Column(String(50), default="other")
    enabled = Column(Boolean, default=True)
    last_crawled_at = Column(DateTime, nullable=True)
    article_count = Column(Integer, default=0)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    password_hash = Column(String(128), nullable=False)
    is_admin = Column(Boolean, default=False)  # 管理员标识
    created_at = Column(DateTime, default=func.now())


class Favorite(Base):
    __tablename__ = "favorites"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False, index=True)
    article_id = Column(Integer, nullable=False, index=True)
    created_at = Column(DateTime, default=func.now())

    # 复合索引：加速按用户+文章查询
    __table_args__ = (
        {"sqlite_autoincrement": True},
    )


class ReadHistory(Base):
    __tablename__ = "read_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False, index=True)
    article_id = Column(Integer, nullable=False, index=True)
    read_at = Column(DateTime, default=func.now())


class Comment(Base):
    __tablename__ = "comments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    article_id = Column(Integer, ForeignKey("news_articles.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=func.now())

    user = relationship("User")


class CrawlLog(Base):
    """爬虫运行日志"""
    __tablename__ = "crawl_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_name = Column(String(100), nullable=False, index=True)
    status = Column(String(20), nullable=False)  # success / error / timeout
    articles_found = Column(Integer, default=0)
    new_articles = Column(Integer, default=0)
    error_message = Column(Text, default="")
    duration_seconds = Column(Integer, default=0)
    crawled_at = Column(DateTime, default=func.now(), index=True)
