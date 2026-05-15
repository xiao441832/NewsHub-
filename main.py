"""NewsHub - FastAPI 主程序（Cookie 认证 + 服务端渲染）"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime
from typing import Optional
from fastapi import FastAPI, Request, Query, Header, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import joinedload

from database import init_db, SessionLocal
from models import NewsArticle, NewsSource, User, Favorite, ReadHistory, Comment, CrawlLog
from config import CATEGORIES, HOST, PORT, get_source_count, get_all_sources
from auth import create_token, verify_token, hash_password, get_current_user_from_request
from cleanup_old_news import cleanup_old_articles, get_cleanup_stats
from cache import cache, clear_cache

app = FastAPI(title="NewsHub", description="全球新闻聚合")

# 静态文件 + 模板
app.mount("/static", StaticFiles(directory="frontend/static"), name="static")
templates = Jinja2Templates(directory="templates")


@app.on_event("startup")
def startup():
    init_db()
    from scheduler import start_scheduler
    start_scheduler()


# ═══════════════════════════════════════════════════════
# 公共工具函数
# ═══════════════════════════════════════════════════════

def _build_page_context(request: Request, **extra) -> dict:
    """构建所有页面共享的模板上下文 — 自动注入当前用户"""
    user = get_current_user_from_request(request)
    # 检查是否为管理员
    is_admin = False
    if user:
        db = SessionLocal()
        db_user = db.query(User).filter(User.id == user["user_id"]).first()
        is_admin = db_user is not None and db_user.is_admin
        db.close()
    ctx = {
        "request": request,
        "categories": CATEGORIES,
        "user": user,
        "is_admin": is_admin,
    }
    ctx.update(extra)
    return ctx


# 分页参数常量
DEFAULT_PAGE_SIZE = 30
MAX_PAGE_SIZE = 50


def paginate(query, page: int = 1, page_size: int = DEFAULT_PAGE_SIZE):
    """
    通用分页函数

    参数：
        query: SQLAlchemy 查询对象
        page: 当前页码（从 1 开始）
        page_size: 每页数量（上限 50）

    返回：
        (items, total, total_pages) — 分页结果、总数、总页数
    """
    # 参数校验
    page = max(1, page)
    page_size = min(max(1, page_size), MAX_PAGE_SIZE)

    total = query.count()
    total_pages = max(1, (total + page_size - 1) // page_size)

    # 页码越界保护
    if page > total_pages:
        page = total_pages

    items = query.offset((page - 1) * page_size).limit(page_size).all()

    return items, total, total_pages


# ═══════════════════════════════════════════════════════
# 页面路由
# ═══════════════════════════════════════════════════════

@app.get("/", response_class=HTMLResponse)
def index(request: Request, category: str = "", search: str = "", tag: str = "", page: int = 1, page_size: int = DEFAULT_PAGE_SIZE):
    """首页"""
    db = SessionLocal()
    query = db.query(NewsArticle).filter(NewsArticle.is_duplicate == False)

    if category and category in CATEGORIES:
        query = query.filter(NewsArticle.category == category)
    if search:
        query = query.filter(NewsArticle.title.ilike(f"%{search}%"))
    if tag:
        query = query.filter(NewsArticle.tags.ilike(f"%{tag}%"))

    query = query.order_by(NewsArticle.published_at.desc())
    articles, total, total_pages = paginate(query, page, page_size)
    articles_data = [a.to_dict() for a in articles]

    # 分类计数
    category_counts = {}
    for cat in CATEGORIES:
        cnt = db.query(NewsArticle).filter(NewsArticle.category == cat, NewsArticle.is_duplicate == False).count()
        if cnt > 0:
            category_counts[cat] = cnt

    # 来源
    sources = db.query(NewsSource).filter(NewsSource.enabled == True).all()
    sources_data = [{"name": s.name, "count": s.article_count} for s in sources]

    # 标签
    all_articles = db.query(NewsArticle).filter(NewsArticle.is_duplicate == False, NewsArticle.tags != "").all()
    tag_counts = {}
    for a in all_articles:
        for t in (a.tags or "").split(","):
            t = t.strip()
            if t:
                tag_counts[t] = tag_counts.get(t, 0) + 1
    top_tags = sorted(tag_counts.items(), key=lambda x: -x[1])[:20]

    # 最后更新时间
    last = db.query(NewsArticle).order_by(NewsArticle.created_at.desc()).first()
    last_updated = last.created_at.strftime("%Y-%m-%d %H:%M") if last else "N/A"

    db.close()

    ctx = _build_page_context(
        request,
        articles=articles_data,
        category_counts=category_counts,
        current_category=category,
        current_tag=tag,
        search_query=search,
        sources=sources_data,
        top_tags=top_tags,
        total_count=total,
        total_sources=get_source_count(),  # 从 config 动态读取源总数
        page=page,
        total_pages=total_pages,
        last_updated=last_updated,
    )
    return templates.TemplateResponse(request=request, name="index.html", context=ctx)


@app.get("/article/{article_id}", response_class=HTMLResponse)
def article_detail(request: Request, article_id: int):
    """文章详情页"""
    db = SessionLocal()
    article = db.query(NewsArticle).filter(NewsArticle.id == article_id).first()
    if not article:
        db.close()
        return HTMLResponse("<h1>文章不存在</h1>", status_code=404)

    article_data = article.to_dict()
    article_data["content"] = article.content or ""
    article_data["url"] = article.url

    # 自动记录阅读历史（方案 A：打开详情页即记录）
    user = get_current_user_from_request(request)
    if user:
        existing = db.query(ReadHistory).filter(
            ReadHistory.user_id == user["user_id"],
            ReadHistory.article_id == article_id,
        ).first()
        if existing:
            # 已有记录则更新阅读时间
            existing.read_at = datetime.utcnow()
        else:
            # 首次阅读，新增记录
            db.add(ReadHistory(user_id=user["user_id"], article_id=article_id))
        db.commit()

    # 同分类推荐
    related = db.query(NewsArticle).filter(
        NewsArticle.category == article.category,
        NewsArticle.id != article.id,
        NewsArticle.is_duplicate == False,
    ).order_by(NewsArticle.published_at.desc()).limit(10).all()
    related_data = [r.to_dict() for r in related]

    # 评论列表
    comments = (
        db.query(Comment)
        .filter(Comment.article_id == article_id)
        .order_by(Comment.created_at.desc())
        .all()
    )
    comments_data = []
    for c in comments:
        u = db.query(User).filter(User.id == c.user_id).first()
        comments_data.append({
            "id": c.id,
            "content": c.content,
            "username": u.username if u else "匿名",
            "created_at": c.created_at.strftime("%Y-%m-%d %H:%M"),
        })

    db.close()

    ctx = _build_page_context(
        request,
        article=article_data,
        related=related_data,
        comments=comments_data,
    )
    return templates.TemplateResponse(request=request, name="detail.html", context=ctx)


@app.get("/favorites", response_class=HTMLResponse)
def favorites_page(request: Request, page: int = 1, page_size: int = 20):
    """我的收藏页 — 服务端渲染 + 分页"""
    user = get_current_user_from_request(request)
    if not user:
        return RedirectResponse(url="/", status_code=302)

    db = SessionLocal()
    query = (
        db.query(Favorite)
        .filter(Favorite.user_id == user["user_id"])
        .order_by(Favorite.created_at.desc())
    )
    favorites, total, total_pages = paginate(query, page, page_size)

    # 关联查询文章信息（N+1 优化：批量查询）
    article_ids = [fav.article_id for fav in favorites]
    articles_map = {}
    if article_ids:
        articles = db.query(NewsArticle).filter(NewsArticle.id.in_(article_ids)).all()
        articles_map = {a.id: a for a in articles}

    fav_list = []
    for fav in favorites:
        article = articles_map.get(fav.article_id)
        if article:
            fav_list.append({
                "article": article.to_dict(),
                "created_at": fav.created_at.strftime("%Y-%m-%d %H:%M"),
            })
    db.close()

    ctx = _build_page_context(
        request,
        favorites=fav_list,
        page=page,
        total_pages=total_pages,
        total_count=total,
    )
    return templates.TemplateResponse(request=request, name="favorites.html", context=ctx)


@app.get("/history", response_class=HTMLResponse)
def history_page(request: Request, page: int = 1, page_size: int = 20):
    """阅读历史页 — 服务端渲染 + 分页"""
    user = get_current_user_from_request(request)
    if not user:
        return RedirectResponse(url="/", status_code=302)

    db = SessionLocal()
    query = (
        db.query(ReadHistory)
        .filter(ReadHistory.user_id == user["user_id"])
        .order_by(ReadHistory.read_at.desc())
    )
    records, total, total_pages = paginate(query, page, page_size)

    # N+1 优化：批量查询关联文章
    article_ids = [rec.article_id for rec in records]
    articles_map = {}
    if article_ids:
        articles = db.query(NewsArticle).filter(NewsArticle.id.in_(article_ids)).all()
        articles_map = {a.id: a for a in articles}

    history_list = []
    for rec in records:
        article = articles_map.get(rec.article_id)
        if article:
            history_list.append({
                "article": article.to_dict(),
                "read_at": rec.read_at.strftime("%Y-%m-%d %H:%M"),
            })
    db.close()

    ctx = _build_page_context(
        request,
        histories=history_list,
        page=page,
        total_pages=total_pages,
        total_count=total,
    )
    return templates.TemplateResponse(request=request, name="history.html", context=ctx)


# ═══════════════════════════════════════════════════════
# API 路由
# ═══════════════════════════════════════════════════════

@app.get("/api/articles")
def api_articles(category: str = "", search: str = "", tag: str = "", page: int = 1, page_size: int = DEFAULT_PAGE_SIZE):
    """API: 文章列表（分页）"""
    db = SessionLocal()
    query = db.query(NewsArticle).filter(NewsArticle.is_duplicate == False)
    if category:
        query = query.filter(NewsArticle.category == category)
    if search:
        query = query.filter(NewsArticle.title.ilike(f"%{search}%"))
    if tag:
        query = query.filter(NewsArticle.tags.ilike(f"%{tag}%"))
    query = query.order_by(NewsArticle.published_at.desc())
    articles, total, total_pages = paginate(query, page, page_size)
    db.close()
    return {
        "total": total,
        "page": page,
        "page_size": min(page_size, MAX_PAGE_SIZE),
        "total_pages": total_pages,
        "articles": [a.to_dict() for a in articles],
    }


@app.get("/api/tags")
@cache(ttl=600)  # 缓存 10 分钟
def api_tags():
    """API: 标签列表（缓存 10 分钟）"""
    db = SessionLocal()
    all_articles = db.query(NewsArticle).filter(NewsArticle.is_duplicate == False, NewsArticle.tags != "").all()
    tag_counts = {}
    for a in all_articles:
        for t in (a.tags or "").split(","):
            t = t.strip()
            if t:
                tag_counts[t] = tag_counts.get(t, 0) + 1
    db.close()
    tags = sorted(tag_counts.items(), key=lambda x: -x[1])
    return {"tags": [{"name": t, "count": c} for t, c in tags]}


@app.get("/api/stats")
@cache(ttl=120)  # 缓存 2 分钟，确保数据及时更新
def api_stats():
    """API: 统计数据（缓存 2 分钟）"""
    db = SessionLocal()
    total = db.query(NewsArticle).filter(NewsArticle.is_duplicate == False).count()
    # 从 config.py 动态读取新闻源总数，不依赖数据库
    total_sources = get_source_count()
    # 已入库的新闻源数（已爬取过的）
    db_sources = db.query(NewsSource).filter(NewsSource.enabled == True).count()
    by_category = {}
    for cat in CATEGORIES:
        cnt = db.query(NewsArticle).filter(NewsArticle.category == cat, NewsArticle.is_duplicate == False).count()
        if cnt > 0:
            by_category[cat] = cnt
    # 最后更新时间
    last = db.query(NewsArticle).order_by(NewsArticle.created_at.desc()).first()
    last_updated = last.created_at.strftime("%Y-%m-%d %H:%M") if last else "暂无"
    db.close()
    return {
        "total_articles": total,
        "total_sources": total_sources,       # 配置的源总数（50）
        "active_sources": db_sources,          # 已入库的源数（已爬取）
        "last_updated": last_updated,
        "by_category": by_category,
    }


@app.get("/api/ping")
async def ping():
    """API: 健康检查"""
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@app.get("/api/me")
def api_me(request: Request):
    """API: 获取当前登录用户信息"""
    user = get_current_user_from_request(request)
    if not user:
        raise HTTPException(401, "未登录")
    return {"user_id": user["user_id"], "username": user["username"]}


# ═══════════════════════════════════════════════════════
# 认证路由（Cookie 方案）
# ═══════════════════════════════════════════════════════

class RegisterRequest(BaseModel):
    username: str
    password: str

class LoginRequest(BaseModel):
    username: str
    password: str


@app.post("/api/register")
def api_register(req: RegisterRequest):
    """注册 — 成功后设置 Cookie"""
    db = SessionLocal()
    if db.query(User).filter(User.username == req.username).first():
        db.close()
        raise HTTPException(400, "用户名已存在")
    user = User(username=req.username, password_hash=hash_password(req.password))
    db.add(user)
    db.commit()
    token = create_token(user.id, user.username)
    db.close()

    # 构建响应，同时设置 Cookie 和 JSON
    resp = JSONResponse({"success": True, "username": user.username})
    resp.set_cookie(
        key="access_token",
        value=token,
        path="/",
        httponly=False,  # 前端 JS 需要读取（如收藏功能）
        samesite="lax",
        max_age=86400 * 7,
    )
    return resp


@app.post("/api/login")
def api_login(req: LoginRequest):
    """登录 — 成功后设置 Cookie"""
    db = SessionLocal()
    user = db.query(User).filter(User.username == req.username).first()
    if not user or user.password_hash != hash_password(req.password):
        db.close()
        raise HTTPException(401, "用户名或密码错误")
    token = create_token(user.id, user.username)
    db.close()

    # 构建响应，同时设置 Cookie 和 JSON
    resp = JSONResponse({"success": True, "username": user.username})
    resp.set_cookie(
        key="access_token",
        value=token,
        path="/",
        httponly=False,
        samesite="lax",
        max_age=86400 * 7,
    )
    return resp


@app.post("/api/logout")
def api_logout():
    """退出登录 — 清除 Cookie"""
    resp = JSONResponse({"success": True})
    resp.delete_cookie("access_token", path="/")
    return resp


# ═══════════════════════════════════════════════════════
# 收藏 API（支持 Cookie + Header 双重认证）
# ═══════════════════════════════════════════════════════

@app.post("/api/favorites/{article_id}")
def api_add_favorite(article_id: int, request: Request):
    """添加/取消收藏"""
    user = get_current_user_from_request(request)
    if not user:
        raise HTTPException(401, "请先登录")
    db = SessionLocal()
    existing = db.query(Favorite).filter(
        Favorite.user_id == user["user_id"], Favorite.article_id == article_id
    ).first()
    if existing:
        db.delete(existing)
        db.commit()
        db.close()
        return {"action": "removed"}
    fav = Favorite(user_id=user["user_id"], article_id=article_id)
    db.add(fav)
    db.commit()
    db.close()
    return {"action": "added"}


@app.get("/api/favorites")
def api_get_favorites(request: Request):
    """获取收藏列表"""
    user = get_current_user_from_request(request)
    if not user:
        raise HTTPException(401, "请先登录")
    db = SessionLocal()
    favs = db.query(Favorite).filter(Favorite.user_id == user["user_id"]).order_by(Favorite.created_at.desc()).all()
    article_ids = [f.article_id for f in favs]
    articles = db.query(NewsArticle).filter(NewsArticle.id.in_(article_ids)).all() if article_ids else []
    db.close()
    return {"articles": [a.to_dict() for a in articles]}


# ═══════════════════════════════════════════════════════
# 阅读历史 API（支持 Cookie + Header 双重认证）
# ═══════════════════════════════════════════════════════

@app.post("/api/history/{article_id}")
def api_add_history(article_id: int, request: Request):
    """记录阅读历史"""
    user = get_current_user_from_request(request)
    if not user:
        return {"status": "anonymous"}
    db = SessionLocal()
    record = ReadHistory(user_id=user["user_id"], article_id=article_id)
    db.add(record)
    db.commit()
    db.close()
    return {"status": "ok"}


@app.get("/api/history")
def api_get_history(request: Request):
    """获取阅读历史"""
    user = get_current_user_from_request(request)
    if not user:
        raise HTTPException(401, "请先登录")
    db = SessionLocal()
    records = db.query(ReadHistory).filter(
        ReadHistory.user_id == user["user_id"]
    ).order_by(ReadHistory.read_at.desc()).limit(50).all()
    article_ids = [r.article_id for r in records]
    articles = db.query(NewsArticle).filter(NewsArticle.id.in_(article_ids)).all() if article_ids else []
    db.close()
    return {"articles": [a.to_dict() for a in articles]}


@app.delete("/api/history")
def api_clear_history(request: Request):
    """清空全部阅读历史"""
    user = get_current_user_from_request(request)
    if not user:
        raise HTTPException(401, "请先登录")
    db = SessionLocal()
    db.query(ReadHistory).filter(ReadHistory.user_id == user["user_id"]).delete()
    db.commit()
    db.close()
    return {"status": "cleared"}


@app.delete("/api/favorites/{article_id}")
def api_remove_favorite(article_id: int, request: Request):
    """取消收藏"""
    user = get_current_user_from_request(request)
    if not user:
        raise HTTPException(401, "请先登录")
    db = SessionLocal()
    fav = db.query(Favorite).filter(
        Favorite.user_id == user["user_id"],
        Favorite.article_id == article_id,
    ).first()
    if fav:
        db.delete(fav)
        db.commit()
    db.close()
    return {"status": "removed"}


# ═══════════════════════════════════════════════════════
# 评论 API
# ═══════════════════════════════════════════════════════

class CommentRequest(BaseModel):
    content: str


@app.post("/api/articles/{article_id}/comments")
def api_add_comment(article_id: int, req: CommentRequest, request: Request):
    """发表评论（需登录）"""
    user = get_current_user_from_request(request)
    if not user:
        raise HTTPException(401, "请先登录")
    if not req.content.strip():
        raise HTTPException(400, "评论内容不能为空")

    db = SessionLocal()
    comment = Comment(
        article_id=article_id,
        user_id=user["user_id"],
        content=req.content.strip(),
    )
    db.add(comment)
    db.commit()
    result = {
        "id": comment.id,
        "content": comment.content,
        "username": user["username"],
        "created_at": comment.created_at.strftime("%Y-%m-%d %H:%M"),
    }
    db.close()
    return result


@app.get("/api/articles/{article_id}/comments")
def api_get_comments(article_id: int, page: int = 1, page_size: int = 20):
    """获取文章评论列表（公开，分页）"""
    db = SessionLocal()
    query = (
        db.query(Comment)
        .filter(Comment.article_id == article_id)
        .order_by(Comment.created_at.desc())
    )
    comments, total, total_pages = paginate(query, page, page_size)

    # N+1 优化：批量查询用户信息
    user_ids = list(set(c.user_id for c in comments))
    users_map = {}
    if user_ids:
        users = db.query(User).filter(User.id.in_(user_ids)).all()
        users_map = {u.id: u for u in users}

    result = []
    for c in comments:
        u = users_map.get(c.user_id)
        result.append({
            "id": c.id,
            "content": c.content,
            "username": u.username if u else "匿名",
            "created_at": c.created_at.strftime("%Y-%m-%d %H:%M"),
        })
    db.close()
    return {
        "comments": result,
        "total": total,
        "page": page,
        "total_pages": total_pages,
    }


# ═══════════════════════════════════════════════════════
# 管理员 API — 手动清理旧新闻
# ═══════════════════════════════════════════════════════

# 简单的管理员密钥（生产环境应使用更安全的方案）
ADMIN_SECRET = "newshub-admin-2026"


@app.post("/api/admin/cleanup")
def api_admin_cleanup(request: Request, secret: str = Query(...)):
    """
    手动触发清理旧新闻（需管理员密钥）

    参数:
        secret: 管理员密钥（通过 Query 参数传递）

    返回:
        JSON: { "deleted": 数量, "message": "消息" }
    """
    # 验证管理员密钥
    if secret != ADMIN_SECRET:
        raise HTTPException(403, "管理员密钥错误")

    db = SessionLocal()
    try:
        deleted, error = cleanup_old_articles(db)
        if error:
            return JSONResponse(
                status_code=500,
                content={"deleted": 0, "message": f"清理失败: {error}"}
            )
        return {"deleted": deleted, "message": f"清理完成，删除 {deleted} 条旧新闻"}
    finally:
        db.close()


@app.get("/api/admin/cleanup/stats")
def api_admin_cleanup_stats(request: Request, secret: str = Query(...)):
    """
    获取清理统计信息（不执行删除，需管理员密钥）

    返回:
        JSON: 包含统计信息的字典
    """
    # 验证管理员密钥
    if secret != ADMIN_SECRET:
        raise HTTPException(403, "管理员密钥错误")

    db = SessionLocal()
    try:
        stats = get_cleanup_stats(db)
        return stats
    finally:
        db.close()


@app.post("/api/admin/cache/clear")
def api_admin_cache_clear(secret: str = Query(...)):
    """手动清除缓存（需管理员密钥）"""
    if secret != ADMIN_SECRET:
        raise HTTPException(403, "管理员密钥错误")
    clear_cache()
    return {"status": "ok", "message": "缓存已全部清除"}


# ═══════════════════════════════════════════════════════
# 管理员面板页面
# ═══════════════════════════════════════════════════════

def _require_admin(request: Request):
    """校验管理员身份，返回用户信息；非管理员抛 403"""
    user = get_current_user_from_request(request)
    if not user:
        raise HTTPException(401, "请先登录")
    db = SessionLocal()
    db_user = db.query(User).filter(User.id == user["user_id"]).first()
    db.close()
    if not db_user or not db_user.is_admin:
        raise HTTPException(403, "无管理员权限")
    return user


@app.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request):
    """管理员面板 — 爬虫监控（仅管理员）"""
    user = get_current_user_from_request(request)
    if not user:
        return RedirectResponse(url="/", status_code=302)

    # 检查管理员权限
    db_check = SessionLocal()
    db_user = db_check.query(User).filter(User.id == user["user_id"]).first()
    is_admin = db_user and db_user.is_admin
    db_check.close()
    if not is_admin:
        return RedirectResponse(url="/", status_code=302)

    db = SessionLocal()
    try:
        # 获取所有新闻源状态
        sources = db.query(NewsSource).order_by(NewsSource.name).all()
        sources_data = []
        for src in sources:
            # 获取该源最近的爬取日志
            latest_log = db.query(CrawlLog).filter(
                CrawlLog.source_name == src.name
            ).order_by(CrawlLog.crawled_at.desc()).first()

            # 统计该源今日文章数
            from datetime import datetime, timedelta
            today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            today_count = db.query(NewsArticle).filter(
                NewsArticle.source == src.name,
                NewsArticle.created_at >= today
            ).count()

            sources_data.append({
                "name": src.name,
                "type": src.source_type,
                "lang": src.lang,
                "category": src.default_category,
                "enabled": src.enabled,
                "article_count": src.article_count,
                "today_count": today_count,
                "last_crawled_at": src.last_crawled_at.strftime("%Y-%m-%d %H:%M") if src.last_crawled_at else "未爬取",
                "last_status": latest_log.status if latest_log else "unknown",
                "last_error": latest_log.error_message if latest_log and latest_log.error_message else "",
            })

        # 获取最近 50 条爬取日志
        recent_logs = db.query(CrawlLog).order_by(CrawlLog.crawled_at.desc()).limit(50).all()
        logs_data = [{
            "source_name": log.source_name,
            "status": log.status,
            "articles_found": log.articles_found,
            "new_articles": log.new_articles,
            "duration": log.duration_seconds,
            "error": log.error_message or "",
            "crawled_at": log.crawled_at.strftime("%Y-%m-%d %H:%M:%S"),
        } for log in recent_logs]

        # 统计数据
        total_articles = db.query(NewsArticle).count()
        total_sources = db.query(NewsSource).filter(NewsSource.enabled == True).count()
        today_total = db.query(NewsArticle).filter(NewsArticle.created_at >= today).count()

        # 清理统计
        cleanup_stats = get_cleanup_stats(db)

        ctx = _build_page_context(
            request,
            sources=sources_data,
            logs=logs_data,
            total_articles=total_articles,
            total_sources=total_sources,
            today_total=today_total,
            cleanup_stats=cleanup_stats,
        )
        return templates.TemplateResponse(request=request, name="admin.html", context=ctx)
    finally:
        db.close()


@app.post("/api/admin/crawl")
def api_admin_trigger_crawl(request: Request):
    """手动触发爬取（仅管理员）"""
    user = _require_admin(request)

    # 在后台线程中执行爬取
    import threading
    from scheduler import crawl_job
    thread = threading.Thread(target=crawl_job, daemon=True)
    thread.start()
    return {"status": "ok", "message": "爬取任务已启动"}


@app.get("/api/admin/stats")
def api_admin_stats(request: Request):
    """管理员统计数据 API（仅管理员）"""
    user = _require_admin(request)

    db = SessionLocal()
    try:
        from datetime import datetime, timedelta

        # 最近 7 天每天的文章数
        daily_stats = []
        for i in range(6, -1, -1):
            day = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=i)
            next_day = day + timedelta(days=1)
            count = db.query(NewsArticle).filter(
                NewsArticle.created_at >= day,
                NewsArticle.created_at < next_day
            ).count()
            daily_stats.append({
                "date": day.strftime("%m-%d"),
                "count": count
            })

        # 各分类文章数
        category_stats = {}
        for cat_key, cat_name in CATEGORIES.items():
            count = db.query(NewsArticle).filter(NewsArticle.category == cat_key).count()
            if count > 0:
                category_stats[cat_name] = count

        return {
            "daily_stats": daily_stats,
            "category_stats": category_stats,
        }
    finally:
        db.close()


if __name__ == "__main__":
    import uvicorn
    print(f"Starting NewsHub at http://localhost:{PORT}")
    uvicorn.run(app, host=HOST, port=PORT)
