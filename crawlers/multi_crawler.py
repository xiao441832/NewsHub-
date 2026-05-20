"""Multi-Source News Crawler - 统一爬虫框架
Supports: RSS, CCTV JSON API, Sina JSON API, Web Scraping
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
import json
import re
import time
from datetime import datetime
from typing import List, Dict, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import USER_AGENT, MAX_ARTICLES_PER_SOURCE, REQUEST_TIMEOUT, REQUEST_TIMEOUT_SCRAPE, NEWS_SOURCES


HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)

# ─── 域名级限速：同域名请求间隔 0.5 秒 ───
import threading
from urllib.parse import urlparse
_domain_locks: Dict[str, float] = {}
_domain_lock = threading.Lock()
_DOMAIN_MIN_INTERVAL = 0.5  # 秒

# 网页抓取时动态切换超时
_scrape_timeout = REQUEST_TIMEOUT


def _domain_rate_limit(url: str):
    """确保同一域名的请求间隔不低于 _DOMAIN_MIN_INTERVAL 秒"""
    domain = urlparse(url).netloc
    with _domain_lock:
        now = time.time()
        last = _domain_locks.get(domain, 0)
        wait = _DOMAIN_MIN_INTERVAL - (now - last)
        if wait > 0:
            time.sleep(wait)
        _domain_locks[domain] = time.time()

# Non-news URL patterns to filter out
_NOISE_PATTERNS = re.compile(
    r'/(about|contact|login|register|signup|privacy|terms|faq|help|feedback|'
    r'advert|ad|tag|topic|sitemap|search|user|profile|settings|download|'
    r'app|weibo|wechat|twitter|facebook|instagram)\b',
    re.IGNORECASE,
)


def _is_valid_article(title: str, url: str) -> bool:
    """Check if a title/URL looks like a real news article."""
    if not title or len(title) < 8:
        return False
    if len(title) > 200:
        return False
    # Filter noise URLs
    if _NOISE_PATTERNS.search(url):
        return False
    # Filter titles that look like nav items
    noise_words = ["首页", "导航", "更多", "登录", "注册", "下载APP", "客户端", "关于我们", "联系", "版权声明"]
    for w in noise_words:
        if title == w:
            return False
    return True


def _get(url: str, timeout: int = None, encoding: str = None) -> Optional[requests.Response]:
    """Safe HTTP GET with retries and exponential backoff"""
    if timeout is None:
        timeout = _scrape_timeout
    _domain_rate_limit(url)
    for attempt in range(3):
        try:
            resp = SESSION.get(url, timeout=timeout, allow_redirects=True)
            if encoding:
                resp.encoding = encoding
            elif resp.encoding and resp.encoding.lower() in ('iso-8859-1', 'latin-1'):
                resp.encoding = 'utf-8'
            resp.raise_for_status()
            return resp
        except Exception as e:
            if attempt < 2:
                wait = 2 ** attempt  # 1s, 2s
                time.sleep(wait)
            else:
                print(f"    ⚠ GET failed (3 attempts): {url[:60]}... {e}")
    return None


# ═══════════════════════════════════════════════
# RSS Feed Parser
# ═══════════════════════════════════════════════

def crawl_rss(source: Dict) -> List[Dict]:
    """Parse RSS/Atom feed — uses XML parser so <link> tags are not self-closed."""
    articles = []
    resp = _get(source["url"])
    if not resp:
        return articles

    # Use lxml XML parser (correctly handles <link>content</link> in RSS).
    # Falls back to html.parser if lxml is not installed.
    try:
        soup = BeautifulSoup(resp.text, "xml")
    except Exception:
        soup = BeautifulSoup(resp.text, "html.parser")

    items = soup.find_all("item") or soup.find_all("entry")

    for item in items[:MAX_ARTICLES_PER_SOURCE]:
        title_tag = item.find("title")
        title = title_tag.get_text(strip=True) if title_tag else ""
        if not title:
            continue

        # Link
        link_tag = item.find("link")
        if link_tag:
            url = link_tag.get("href", "") or link_tag.get_text(strip=True)
        else:
            url = ""

        # Description/summary
        desc = item.find("description") or item.find("summary") or item.find("content")
        summary = ""
        if desc:
            summary_text = desc.get_text(strip=True)
            summary = re.sub(r'<[^>]+>', '', summary_text)[:500]

        # Date
        pub_date = ""
        for date_tag_name in ["pubdate", "published", "updated", "dc:date"]:
            dt = item.find(date_tag_name) or item.find(date_tag_name.replace(":", ":"))
            if dt:
                pub_date = dt.get_text(strip=True)
                break

        # Image
        image_url = ""
        img = item.find("media:thumbnail") or item.find("media:content") or item.find("enclosure")
        if img:
            image_url = img.get("url", "") or img.get("href", "")
        if not image_url:
            img_match = re.search(r'<img[^>]+src=["\']([^"\']+)', str(desc) if desc else "")
            if img_match:
                image_url = img_match.group(1)

        articles.append({
            "title": title,
            "url": url,
            "source": source["name"],
            "category": source["category"],
            "summary": summary,
            "image_url": image_url,
            "published_at": _parse_rss_date(pub_date),
            "lang": source.get("lang", "zh"),
        })

    return articles


def _parse_rss_date(date_str: str) -> Optional[datetime]:
    """Parse various RSS date formats"""
    if not date_str:
        return None
    # Remove timezone abbreviations
    date_str = re.sub(r'\s*\([^)]+\)\s*$', '', date_str.strip())
    date_str = re.sub(r'\s*[A-Z]{2,4}$', '', date_str.strip())

    formats = [
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S %Z",
        "%a, %d %b %Y %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except ValueError:
            continue
    return None


# ═══════════════════════════════════════════════
# CCTV JSON API Parser
# ═══════════════════════════════════════════════

def crawl_cctv_json(source: Dict) -> List[Dict]:
    """Fetch articles from CCTV JSONP API"""
    articles = []
    url_template = source["url"]

    for page in range(1, 3):  # 2 pages
        url = url_template.format(page=page)
        resp = _get(url)
        if not resp:
            continue

        resp.encoding = 'utf-8'
        match = re.search(r'\{.*\}', resp.text, re.DOTALL)
        if not match:
            continue

        try:
            data = json.loads(match.group())
        except json.JSONDecodeError:
            continue

        for item in data.get("data", {}).get("list", []):
            title = item.get("title", "").strip()
            article_url = item.get("url", "").strip()
            if not title or not article_url:
                continue

            articles.append({
                "title": title,
                "url": article_url,
                "source": source["name"],
                "category": source["category"],
                "summary": item.get("brief", "").strip(),
                "image_url": item.get("image", "").strip(),
                "published_at": _parse_rss_date(item.get("focus_date", "")),
                "lang": "zh",
            })

    return articles[:MAX_ARTICLES_PER_SOURCE]


# ═══════════════════════════════════════════════
# Sina News JSON API Parser
# ═══════════════════════════════════════════════

def crawl_sina_json(source: Dict) -> List[Dict]:
    """Fetch articles from Sina News roll API"""
    articles = []
    resp = _get(source["url"])
    if not resp:
        return articles

    try:
        data = resp.json()
    except json.JSONDecodeError:
        return articles

    items = data.get("result", {}).get("data", [])
    for item in items[:MAX_ARTICLES_PER_SOURCE]:
        title = item.get("title", "").strip()
        url = item.get("url", "") or item.get("wapurl", "")
        if not title or not url:
            continue

        # Get image
        image_url = ""
        img = item.get("img", "")
        if img and isinstance(img, str):
            image_url = img
        elif item.get("images"):
            imgs = item["images"]
            if isinstance(imgs, dict):
                image_url = str(imgs.get("u", ""))
            elif isinstance(imgs, list) and len(imgs) > 0:
                first = imgs[0]
                image_url = first.get("u", "") if isinstance(first, dict) else str(first)

        # Timestamp
        ctime = item.get("ctime", "") or item.get("intime", "")
        pub_date = None
        if ctime and ctime.isdigit():
            try:
                pub_date = datetime.fromtimestamp(int(ctime))
            except (ValueError, OSError):
                pass

        articles.append({
            "title": title,
            "url": url,
            "source": source["name"],
            "category": source["category"],
            "summary": item.get("summary", "") or item.get("intro", ""),
            "image_url": image_url,
            "published_at": pub_date,
            "lang": "zh",
        })

    return articles


# ═══════════════════════════════════════════════
# Web Scrapers
# ═══════════════════════════════════════════════

def _scrape_generic(url: str, selectors: Dict) -> List[Dict]:
    """Generic web scraper using CSS selectors
    selectors: {
        "item": "css selector for article items",
        "title": "css selector for title within item",
        "link": "css selector for link within item",
        "summary": "css selector for summary (optional)",
        "image": "css selector for image (optional)",
    }
    """
    resp = _get(url)
    if not resp:
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    # Remove noise
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()

    items = soup.select(selectors["item"])
    results = []
    for item in items[:30]:
        title_el = item.select_one(selectors.get("title", "a"))
        if not title_el:
            continue
        title = title_el.get_text(strip=True)
        if not title or len(title) < 4:
            continue

        # Link
        link_el = item.select_one(selectors.get("link", "a"))
        href = ""
        if link_el:
            href = link_el.get("href", "")
        if not href and title_el.name == "a":
            href = title_el.get("href", "")

        # Make absolute URL
        if href and not href.startswith("http"):
            from urllib.parse import urljoin
            href = urljoin(url, href)

        if not href:
            continue

        # Summary
        summary = ""
        if "summary" in selectors:
            sum_el = item.select_one(selectors["summary"])
            if sum_el:
                summary = sum_el.get_text(strip=True)[:300]

        # Image
        image_url = ""
        if "image" in selectors:
            img_el = item.select_one(selectors["image"])
            if img_el:
                image_url = img_el.get("src", "") or img_el.get("data-src", "")

        results.append({
            "title": title,
            "url": href,
            "summary": summary,
            "image_url": image_url,
        })

    return results


def crawl_xinhua(source: Dict) -> List[Dict]:
    """新华网 - scrape headline links"""
    resp = _get(source["url"])
    if not resp:
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    articles = []
    seen = set()

    for a in soup.find_all("a", href=True):
        title = a.get_text(strip=True)
        href = a["href"]
        if not _is_valid_article(title, href):
            continue
        if not href.startswith("http"):
            from urllib.parse import urljoin
            href = urljoin("http://www.news.cn/", href)
        if href in seen:
            continue
        if any(x in href for x in ['/politics/', '/world/', '/fortune/', '/tech/', '/legal/', '/society/', '/health/']):
            seen.add(href)
            articles.append({
                "title": title, "url": href,
                "source": source["name"], "category": source["category"],
                "summary": "", "image_url": "", "published_at": None, "lang": "zh",
            })
        if len(articles) >= MAX_ARTICLES_PER_SOURCE:
            break

    return articles


def crawl_huanqiu(source: Dict) -> List[Dict]:
    """环球网"""
    resp = _get(source["url"])
    if not resp:
        return []
    resp.encoding = 'utf-8'
    soup = BeautifulSoup(resp.text, "html.parser")
    articles = []
    seen = set()

    for a in soup.find_all("a", href=True):
        title = a.get_text(strip=True)
        href = a["href"]
        if not _is_valid_article(title, href):
            continue
        if not href.startswith("http"):
            from urllib.parse import urljoin
            href = urljoin("https://www.huanqiu.com/", href)
        if href in seen or '/article/' not in href:
            continue
        seen.add(href)
        articles.append({
            "title": title, "url": href,
            "source": source["name"], "category": source["category"],
            "summary": "", "image_url": "", "published_at": None, "lang": "zh",
        })
        if len(articles) >= MAX_ARTICLES_PER_SOURCE:
            break
    return articles


def crawl_gmw(source: Dict) -> List[Dict]:
    """光明网"""
    resp = _get(source["url"])
    if not resp:
        return []
    resp.encoding = 'utf-8'
    soup = BeautifulSoup(resp.text, "html.parser")
    articles = []
    seen = set()

    for a in soup.find_all("a", href=True):
        title = a.get_text(strip=True)
        href = a["href"]
        if not _is_valid_article(title, href):
            continue
        if not href.startswith("http"):
            from urllib.parse import urljoin
            href = urljoin("https://www.gmw.cn/", href)
        if href in seen or 'gmw.cn' not in href:
            continue
        seen.add(href)
        articles.append({
            "title": title, "url": href,
            "source": source["name"], "category": source["category"],
            "summary": "", "image_url": "", "published_at": None, "lang": "zh",
        })
        if len(articles) >= MAX_ARTICLES_PER_SOURCE:
            break
    return articles


def crawl_cnr(source: Dict) -> List[Dict]:
    """央广网"""
    resp = _get(source["url"])
    if not resp:
        return []
    resp.encoding = 'utf-8'
    soup = BeautifulSoup(resp.text, "html.parser")
    articles = []
    seen = set()

    for a in soup.find_all("a", href=True):
        title = a.get_text(strip=True)
        href = a["href"]
        if not _is_valid_article(title, href):
            continue
        if not href.startswith("http"):
            from urllib.parse import urljoin
            href = urljoin("https://www.cnr.cn/", href)
        if href in seen or 'cnr.cn' not in href:
            continue
        seen.add(href)
        articles.append({
            "title": title, "url": href,
            "source": source["name"], "category": source["category"],
            "summary": "", "image_url": "", "published_at": None, "lang": "zh",
        })
        if len(articles) >= MAX_ARTICLES_PER_SOURCE:
            break
    return articles


_BAIDU_NEWS_DOMAINS = [
    "news.qq.com", "news.sina.com", "news.163.com", "news.sohu.com",
    "thepaper.cn", "cctv.com", "chinanews.com", "people.com.cn",
    "xinhuanet.com", "huanqiu.com", "gmw.cn", "cnr.cn", "youth.cn",
    "cankaoxiaoxi.com", "caixin.com", "jiemian.com", "36kr.com",
    "tech.qq.com", "tech.sina.com", "ithome.com",
    "baijiahao.baidu.com", "baijiahao.baidu.com",
    "bjnews.com.cn", "guancha.cn", "yicai.com", "nbd.com.cn",
    "stcn.com", "cls.cn", "ifeng.com",
]


def crawl_baidu(source: Dict) -> List[Dict]:
    """百度新闻 - 聚合搜索，过滤非新闻域名"""
    resp = _get(source["url"])
    if not resp:
        return []
    resp.encoding = 'utf-8'
    soup = BeautifulSoup(resp.text, "html.parser")
    articles = []

    for a in soup.find_all("a", href=True):
        title = a.get_text(strip=True)
        href = a["href"]
        if not _is_valid_article(title, href):
            continue
        if not href.startswith("http"):
            continue
        # Only allow known news domains
        if not any(d in href for d in _BAIDU_NEWS_DOMAINS):
            continue
        articles.append({
            "title": title, "url": href,
            "source": source["name"], "category": source["category"],
            "summary": "", "image_url": "", "published_at": None, "lang": "zh",
        })
        if len(articles) >= MAX_ARTICLES_PER_SOURCE:
            break
    return articles


def crawl_thepaper(source: Dict) -> List[Dict]:
    """澎湃新闻"""
    resp = _get(source["url"])
    if not resp:
        return []
    resp.encoding = 'utf-8'
    soup = BeautifulSoup(resp.text, "html.parser")
    articles = []
    seen = set()

    for a in soup.find_all("a", href=True):
        title = a.get_text(strip=True)
        href = a["href"]
        if not _is_valid_article(title, href):
            continue
        if not href.startswith("http"):
            from urllib.parse import urljoin
            href = urljoin("https://www.thepaper.cn/", href)
        if href in seen or 'thepaper.cn' not in href:
            continue
        seen.add(href)
        articles.append({
            "title": title, "url": href,
            "source": source["name"], "category": source["category"],
            "summary": "", "image_url": "", "published_at": None, "lang": "zh",
        })
        if len(articles) >= MAX_ARTICLES_PER_SOURCE:
            break
    return articles


def crawl_cnn(source: Dict) -> List[Dict]:
    """CNN"""
    resp = _get(source["url"])
    if not resp:
        return []
    soup = BeautifulSoup(resp.text, "html.parser")
    articles = []
    seen = set()

    for a in soup.find_all("a", href=True):
        title = a.get_text(strip=True)
        href = a["href"]
        if not title or len(title) < 10 or len(title) > 200:
            continue
        if href.startswith("/"):
            href = "https://edition.cnn.com" + href
        if not href.startswith("http") or href in seen:
            continue
        if '/videos/' in href or '/gallery/' in href:
            continue
        seen.add(href)
        articles.append({
            "title": title, "url": href,
            "source": source["name"], "category": source["category"],
            "summary": "", "image_url": "", "published_at": None, "lang": "en",
        })
        if len(articles) >= MAX_ARTICLES_PER_SOURCE:
            break
    return articles


def crawl_ap(source: Dict) -> List[Dict]:
    """AP News"""
    resp = _get(source["url"])
    if not resp:
        return []
    soup = BeautifulSoup(resp.text, "html.parser")
    articles = []
    seen = set()

    for a in soup.find_all("a", href=True):
        title = a.get_text(strip=True)
        href = a["href"]
        if not title or len(title) < 10 or len(title) > 200:
            continue
        if href.startswith("/"):
            href = "https://apnews.com" + href
        if not href.startswith("http") or href in seen:
            continue
        if '/article/' not in href:
            continue
        seen.add(href)
        articles.append({
            "title": title, "url": href,
            "source": source["name"], "category": source["category"],
            "summary": "", "image_url": "", "published_at": None, "lang": "en",
        })
        if len(articles) >= MAX_ARTICLES_PER_SOURCE:
            break
    return articles


def crawl_zaobao(source: Dict) -> List[Dict]:
    """联合早报"""
    resp = _get(source["url"])
    if not resp:
        return []
    resp.encoding = 'utf-8'
    soup = BeautifulSoup(resp.text, "html.parser")
    articles = []
    seen = set()

    for a in soup.find_all("a", href=True):
        title = a.get_text(strip=True)
        href = a["href"]
        if not title or len(title) < 6 or len(title) > 100:
            continue
        if href.startswith("/"):
            href = "https://www.zaobao.com" + href
        if not href.startswith("http") or href in seen:
            continue
        if 'zaobao.com' not in href:
            continue
        seen.add(href)
        articles.append({
            "title": title, "url": href,
            "source": source["name"], "category": source["category"],
            "summary": "", "image_url": "", "published_at": None, "lang": "zh",
        })
        if len(articles) >= MAX_ARTICLES_PER_SOURCE:
            break
    return articles


def crawl_yahoojp(source: Dict) -> List[Dict]:
    """Yahoo Japan News"""
    resp = _get(source["url"])
    if not resp:
        return []
    soup = BeautifulSoup(resp.text, "html.parser")
    articles = []
    seen = set()

    for a in soup.find_all("a", href=True):
        title = a.get_text(strip=True)
        href = a["href"]
        if not title or len(title) < 6 or len(title) > 150:
            continue
        if href.startswith("/"):
            href = "https://news.yahoo.co.jp" + href
        if not href.startswith("http") or href in seen:
            continue
        if 'news.yahoo.co.jp' not in href and 'news.line' not in href:
            continue
        seen.add(href)
        articles.append({
            "title": title, "url": href,
            "source": source["name"], "category": source["category"],
            "summary": "", "image_url": "", "published_at": None, "lang": "ja",
        })
        if len(articles) >= MAX_ARTICLES_PER_SOURCE:
            break
    return articles


def crawl_huxiu(source: Dict) -> List[Dict]:
    """虎嗅"""
    resp = _get(source["url"])
    if not resp:
        return []
    resp.encoding = 'utf-8'
    soup = BeautifulSoup(resp.text, "html.parser")
    articles = []
    seen = set()

    for a in soup.find_all("a", href=True):
        title = a.get_text(strip=True)
        href = a["href"]
        if not _is_valid_article(title, href):
            continue
        if not href.startswith("http"):
            from urllib.parse import urljoin
            href = urljoin("https://www.huxiu.com/", href)
        if href in seen or '/article/' not in href:
            continue
        seen.add(href)
        articles.append({
            "title": title, "url": href,
            "source": source["name"], "category": source["category"],
            "summary": "", "image_url": "", "published_at": None, "lang": "zh",
        })
        if len(articles) >= MAX_ARTICLES_PER_SOURCE:
            break
    return articles


def crawl_jiemian(source: Dict) -> List[Dict]:
    """界面新闻"""
    resp = _get(source["url"])
    if not resp:
        return []
    resp.encoding = 'utf-8'
    soup = BeautifulSoup(resp.text, "html.parser")
    articles = []
    seen = set()

    for a in soup.find_all("a", href=True):
        title = a.get_text(strip=True)
        href = a["href"]
        if not _is_valid_article(title, href):
            continue
        if not href.startswith("http"):
            from urllib.parse import urljoin
            href = urljoin("https://www.jiemian.com/", href)
        if href in seen or '/article/' not in href:
            continue
        seen.add(href)
        articles.append({
            "title": title, "url": href,
            "source": source["name"], "category": source["category"],
            "summary": "", "image_url": "", "published_at": None, "lang": "zh",
        })
        if len(articles) >= MAX_ARTICLES_PER_SOURCE:
            break
    return articles


def crawl_cls(source: Dict) -> List[Dict]:
    """财联社"""
    resp = _get(source["url"])
    if not resp:
        return []
    resp.encoding = 'utf-8'
    soup = BeautifulSoup(resp.text, "html.parser")
    articles = []
    seen = set()

    for a in soup.find_all("a", href=True):
        title = a.get_text(strip=True)
        href = a["href"]
        if not _is_valid_article(title, href):
            continue
        if not href.startswith("http"):
            from urllib.parse import urljoin
            href = urljoin("https://www.cls.cn/", href)
        if href in seen or '/detail/' not in href:
            continue
        seen.add(href)
        articles.append({
            "title": title, "url": href,
            "source": source["name"], "category": source["category"],
            "summary": "", "image_url": "", "published_at": None, "lang": "zh",
        })
        if len(articles) >= MAX_ARTICLES_PER_SOURCE:
            break
    return articles


def crawl_yicai(source: Dict) -> List[Dict]:
    """第一财经"""
    resp = _get(source["url"])
    if not resp:
        return []
    resp.encoding = 'utf-8'
    soup = BeautifulSoup(resp.text, "html.parser")
    articles = []
    seen = set()

    for a in soup.find_all("a", href=True):
        title = a.get_text(strip=True)
        href = a["href"]
        if not _is_valid_article(title, href):
            continue
        if not href.startswith("http"):
            from urllib.parse import urljoin
            href = urljoin("https://www.yicai.com/", href)
        if href in seen or '/news/' not in href:
            continue
        seen.add(href)
        articles.append({
            "title": title, "url": href,
            "source": source["name"], "category": source["category"],
            "summary": "", "image_url": "", "published_at": None, "lang": "zh",
        })
        if len(articles) >= MAX_ARTICLES_PER_SOURCE:
            break
    return articles


def crawl_nbd(source: Dict) -> List[Dict]:
    """每经新闻"""
    resp = _get(source["url"])
    if not resp:
        return []
    resp.encoding = 'utf-8'
    soup = BeautifulSoup(resp.text, "html.parser")
    articles = []
    seen = set()

    for a in soup.find_all("a", href=True):
        title = a.get_text(strip=True)
        href = a["href"]
        if not _is_valid_article(title, href):
            continue
        if not href.startswith("http"):
            from urllib.parse import urljoin
            href = urljoin("https://www.nbd.com.cn/", href)
        if href in seen or '/articles/' not in href:
            continue
        seen.add(href)
        articles.append({
            "title": title, "url": href,
            "source": source["name"], "category": source["category"],
            "summary": "", "image_url": "", "published_at": None, "lang": "zh",
        })
        if len(articles) >= MAX_ARTICLES_PER_SOURCE:
            break
    return articles


def crawl_stcn(source: Dict) -> List[Dict]:
    """证券时报"""
    resp = _get(source["url"])
    if not resp:
        return []
    resp.encoding = 'utf-8'
    soup = BeautifulSoup(resp.text, "html.parser")
    articles = []
    seen = set()

    for a in soup.find_all("a", href=True):
        title = a.get_text(strip=True)
        href = a["href"]
        if not _is_valid_article(title, href):
            continue
        if not href.startswith("http"):
            from urllib.parse import urljoin
            href = urljoin("https://www.stcn.com/", href)
        if href in seen or '/detail/' not in href:
            continue
        seen.add(href)
        articles.append({
            "title": title, "url": href,
            "source": source["name"], "category": source["category"],
            "summary": "", "image_url": "", "published_at": None, "lang": "zh",
        })
        if len(articles) >= MAX_ARTICLES_PER_SOURCE:
            break
    return articles


def crawl_chinanews(source: Dict) -> List[Dict]:
    """中国新闻网"""
    resp = _get(source["url"])
    if not resp:
        return []
    resp.encoding = 'utf-8'
    soup = BeautifulSoup(resp.text, "html.parser")
    articles = []
    seen = set()

    for a in soup.find_all("a", href=True):
        title = a.get_text(strip=True)
        href = a["href"]
        if not _is_valid_article(title, href):
            continue
        if not href.startswith("http"):
            from urllib.parse import urljoin
            href = urljoin("https://www.chinanews.com/", href)
        if href in seen or ('/gn/' not in href and '/gj/' not in href and '/sh/' not in href and '/cj/' not in href):
            continue
        seen.add(href)
        articles.append({
            "title": title, "url": href,
            "source": source["name"], "category": source["category"],
            "summary": "", "image_url": "", "published_at": None, "lang": "zh",
        })
        if len(articles) >= MAX_ARTICLES_PER_SOURCE:
            break
    return articles


def crawl_ifeng(source: Dict) -> List[Dict]:
    """凤凰网"""
    resp = _get(source["url"])
    if not resp:
        return []
    resp.encoding = 'utf-8'
    soup = BeautifulSoup(resp.text, "html.parser")
    articles = []
    seen = set()

    for a in soup.find_all("a", href=True):
        title = a.get_text(strip=True)
        href = a["href"]
        if not _is_valid_article(title, href):
            continue
        if not href.startswith("http"):
            from urllib.parse import urljoin
            href = urljoin("https://news.ifeng.com/", href)
        if href in seen or ('/c/' not in href and '/a/' not in href):
            continue
        seen.add(href)
        articles.append({
            "title": title, "url": href,
            "source": source["name"], "category": source["category"],
            "summary": "", "image_url": "", "published_at": None, "lang": "zh",
        })
        if len(articles) >= MAX_ARTICLES_PER_SOURCE:
            break
    return articles


def crawl_guancha(source: Dict) -> List[Dict]:
    """观察者网"""
    resp = _get(source["url"])
    if not resp:
        return []
    resp.encoding = 'utf-8'
    soup = BeautifulSoup(resp.text, "html.parser")
    articles = []
    seen = set()

    for a in soup.find_all("a", href=True):
        title = a.get_text(strip=True)
        href = a["href"]
        if not _is_valid_article(title, href):
            continue
        if not href.startswith("http"):
            from urllib.parse import urljoin
            href = urljoin("https://www.guancha.cn/", href)
        if href in seen or 'guancha.cn' not in href:
            continue
        # Filter out non-article pages
        if '/member/' in href or '/user/' in href or '/special/' in href:
            continue
        seen.add(href)
        articles.append({
            "title": title, "url": href,
            "source": source["name"], "category": source["category"],
            "summary": "", "image_url": "", "published_at": None, "lang": "zh",
        })
        if len(articles) >= MAX_ARTICLES_PER_SOURCE:
            break
    return articles


def crawl_bjnews(source: Dict) -> List[Dict]:
    """新京报"""
    resp = _get(source["url"])
    if not resp:
        return []
    resp.encoding = 'utf-8'
    soup = BeautifulSoup(resp.text, "html.parser")
    articles = []
    seen = set()

    for a in soup.find_all("a", href=True):
        title = a.get_text(strip=True)
        href = a["href"]
        if not _is_valid_article(title, href):
            continue
        if not href.startswith("http"):
            from urllib.parse import urljoin
            href = urljoin("https://www.bjnews.com.cn/", href)
        if href in seen or '/detail/' not in href:
            continue
        seen.add(href)
        articles.append({
            "title": title, "url": href,
            "source": source["name"], "category": source["category"],
            "summary": "", "image_url": "", "published_at": None, "lang": "zh",
        })
        if len(articles) >= MAX_ARTICLES_PER_SOURCE:
            break
    return articles


def crawl_163(source: Dict) -> List[Dict]:
    """网易新闻"""
    resp = _get(source["url"])
    if not resp:
        return []
    resp.encoding = 'utf-8'
    soup = BeautifulSoup(resp.text, "html.parser")
    articles = []
    seen = set()

    for a in soup.find_all("a", href=True):
        title = a.get_text(strip=True)
        href = a["href"]
        if not _is_valid_article(title, href):
            continue
        if not href.startswith("http"):
            continue
        if href in seen:
            continue
        # Only 163.com article pages
        if '163.com' not in href or '/article/' not in href:
            continue
        # Filter noise
        if any(x in href for x in ['mail.163.com', 'reg1.vip', 'dl.html', 'news.163.com/special']):
            continue
        seen.add(href)
        articles.append({
            "title": title, "url": href,
            "source": source["name"], "category": source["category"],
            "summary": "", "image_url": "", "published_at": None, "lang": "zh",
        })
        if len(articles) >= MAX_ARTICLES_PER_SOURCE:
            break
    return articles


def crawl_chinanews_scroll(source: Dict) -> List[Dict]:
    """中新网滚动新闻 (chinanews.com.cn)"""
    resp = _get(source["url"])
    if not resp:
        return []
    resp.encoding = 'utf-8'
    soup = BeautifulSoup(resp.text, "html.parser")
    articles = []
    seen = set()

    for a in soup.find_all("a", href=True):
        title = a.get_text(strip=True)
        href = a["href"]
        if not _is_valid_article(title, href):
            continue
        if not href.startswith("http"):
            from urllib.parse import urljoin
            href = urljoin("https://www.chinanews.com.cn/", href)
        if href in seen or 'chinanews.com.cn' not in href:
            continue
        if '/sitemap' in href or '/about' in href:
            continue
        seen.add(href)
        articles.append({
            "title": title, "url": href,
            "source": source["name"], "category": source["category"],
            "summary": "", "image_url": "", "published_at": None, "lang": "zh",
        })
        if len(articles) >= MAX_ARTICLES_PER_SOURCE:
            break
    return articles


# ═══════════════════════════════════════════════
# Crawler Dispatcher
# ═══════════════════════════════════════════════

SCRAPER_MAP = {
    "xinhua": crawl_xinhua,
    "huanqiu": crawl_huanqiu,
    "gmw": crawl_gmw,
    "cnr": crawl_cnr,
    "baidu": crawl_baidu,
    "thepaper": crawl_thepaper,
    "cnn": crawl_cnn,
    "ap": crawl_ap,
    "zaobao": crawl_zaobao,
    "yahoojp": crawl_yahoojp,
    # 新增源
    "huxiu": crawl_huxiu,
    "jiemian": crawl_jiemian,
    "cls": crawl_cls,
    "yicai": crawl_yicai,
    "nbd": crawl_nbd,
    "stcn": crawl_stcn,
    "chinanews": crawl_chinanews,
    "ifeng": crawl_ifeng,
    # 替代源
    "guancha": crawl_guancha,
    "bjnews": crawl_bjnews,
    "163": crawl_163,
    "chinanews_scroll": crawl_chinanews_scroll,
}

TYPE_MAP = {
    "rss": crawl_rss,
    "cctv_json": crawl_cctv_json,
    "sina_json": crawl_sina_json,
}


def crawl_source(source: Dict) -> List[Dict]:
    """Dispatch to the right crawler for a source"""
    global _scrape_timeout
    src_type = source["type"]

    if src_type in TYPE_MAP:
        return TYPE_MAP[src_type](source)
    elif src_type == "web_scrape":
        scraper_name = source.get("scraper", "")
        if scraper_name in SCRAPER_MAP:
            _scrape_timeout = REQUEST_TIMEOUT_SCRAPE
            try:
                return SCRAPER_MAP[scraper_name](source)
            finally:
                _scrape_timeout = REQUEST_TIMEOUT
        else:
            print(f"    ⚠ No scraper for: {scraper_name}")
            return []
    else:
        print(f"    ⚠ Unknown type: {src_type}")
        return []


def clean_content(raw_html: str, base_url: str = "") -> tuple:
    """
    清洗原始 HTML，移除噪音标签和广告，保留正文格式。
    返回: (清洗后的 HTML 字符串, 纯文本摘要)
    """
    if not raw_html:
        return "", ""

    soup = BeautifulSoup(raw_html, "html.parser")

    # 1. 移除脚本、样式、导航、页脚等噪音标签
    for tag in soup(["script", "style", "nav", "footer", "header", "aside",
                     "iframe", "ins", "video", "audio", "form", "button",
                     "input", "select", "textarea", "noscript", "svg"]):
        tag.decompose()

    # 2. 移除广告和侧边栏相关 class/id
    ad_selectors = [
        ".ad", ".ads", ".advert", ".advertisement", ".ad-wrap", ".ad-container",
        ".sidebar", ".side-bar", ".related", ".recommend", ".recommend-box",
        ".comment", ".comments", "#comments", ".breadcrumb", ".crumb",
        ".share", ".sharing", ".copyright", ".disclaimer",
        ".social", ".follow", ".subscribe", ".newsletter",
        ".popup", ".modal", ".overlay", ".toast",
        "[class*='ad-']", "[class*='_ad']", "[id*='ad-']",
        "[class*='recommend']", "[class*='related']",
    ]
    for sel in ad_selectors:
        for el in soup.select(sel):
            el.decompose()

    # 3. 移除 HTML 注释
    from bs4 import Comment
    for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
        comment.extract()

    # 4. 将相对路径图片 URL 转为绝对路径
    if base_url:
        from urllib.parse import urljoin
        for img in soup.find_all("img"):
            src = img.get("src", "") or img.get("data-src", "")
            if src and not src.startswith("http"):
                img["src"] = urljoin(base_url, src)
            # 移除 tracking pixels 和小图标
            width = img.get("width", "")
            height = img.get("height", "")
            if width and height:
                try:
                    if int(width) < 50 or int(height) < 50:
                        img.decompose()
                        continue
                except (ValueError, TypeError):
                    pass

    # 5. 限制图片数量（最多保留 5 张）
    images = soup.find_all("img")
    if len(images) > 5:
        for img in images[5:]:
            img.decompose()

    # 6. 移除空标签（清理残留）
    for tag in soup.find_all(["p", "div", "span"]):
        if not tag.get_text(strip=True) and not tag.find("img"):
            tag.decompose()

    # 获取清洗后的 HTML
    cleaned_html = str(soup)

    # 提取纯文本用于摘要
    plain_text = soup.get_text("\n", strip=True)
    # 压缩多余空行
    plain_text = re.sub(r'\n{3,}', '\n\n', plain_text)

    return cleaned_html, plain_text


def extract_meta_description(soup) -> str:
    """从 HTML 中提取元描述标签作为摘要（零 AI 成本，90% 新闻网站都有）
    优先级1: og:description（Open Graph 协议，最可靠）
    优先级2: meta description（标准 HTML 标签）
    """
    if not soup:
        return ""

    # 优先级1: og:description
    og = soup.find("meta", attrs={"property": "og:description"})
    if og and og.get("content"):
        desc = og["content"].strip()
        if len(desc) > 10:
            return desc[:300]

    # 优先级2: meta description
    meta = soup.find("meta", attrs={"name": "description"})
    if meta and meta.get("content"):
        desc = meta["content"].strip()
        if len(desc) > 10:
            return desc[:300]

    # 优先级3: twitter:description
    twitter = soup.find("meta", attrs={"name": "twitter:description"})
    if twitter and twitter.get("content"):
        desc = twitter["content"].strip()
        if len(desc) > 10:
            return desc[:300]

    return ""


def extract_first_paragraphs(text: str, max_chars: int = 200) -> str:
    """取正文前 max_chars 字作为摘要，在最后一个完整句子处截断"""
    if not text:
        return ""
    text = text.strip()
    if len(text) <= max_chars:
        return text

    truncated = text[:max_chars]
    # 在最后一个完整句子处截断（中文标点）
    last_period = max(
        truncated.rfind("。"),
        truncated.rfind("！"),
        truncated.rfind("？"),
        truncated.rfind("；"),
    )
    if last_period > 50:
        return truncated[: last_period + 1]
    return truncated + "..."


def fallback_summary(title: str) -> str:
    """最后兜底：用标题生成摘要"""
    if not title:
        return ""
    return f"《{title}》详细报道"


def extract_summary(soup, content_text: str, title: str) -> str:
    """提取摘要（纯爬虫，零 AI 消耗）
    优先级：元描述 → 正文前200字 → 标题兜底
    """
    # 方案A: 元描述标签（最可靠）
    meta_desc = extract_meta_description(soup)
    if meta_desc and len(meta_desc) > 10:
        return meta_desc

    # 方案B: 正文前200字
    first_para = extract_first_paragraphs(content_text, max_chars=200)
    if first_para and len(first_para) > 10:
        return first_para

    # 方案C: 标题兜底
    return fallback_summary(title)


def extract_article_content(url: str, source_name: str = "", source_config: dict = None) -> tuple:
    """
    从文章 URL 提取正文内容，使用多层回退策略。
    返回: (HTML 正文, 纯文本, BeautifulSoup对象)

    策略0: 从 JavaScript 变量中提取（央视网等）
    策略1: 使用 source_config 中的专属 content_selector
    策略2: 使用 <article> 标签
    策略3: 使用常见正文容器 class/id 选择器
    策略4: 提取最长连续文本块（密度检测）
    策略5: 提取所有 <p> 标签拼接
    策略6: 全文提取兜底
    """
    resp = _get(url)
    if not resp:
        return "", "", None

    # 正文最少字数阈值（允许短新闻）
    MIN_TEXT_LEN = 50

    # 保存原始 HTML 用于后续清洗
    raw_html = resp.text
    soup = BeautifulSoup(raw_html, "html.parser")

    # ─── 策略0: 从 JavaScript 变量中提取内容（央视网等）───
    # 必须在移除 script 标签之前执行
    for script in soup.find_all("script"):
        script_text = script.string or ""
        # 央视网: var contentdate = '...'
        if "contentdate" in script_text:
            match = re.search(r"var\s+contentdate\s*=\s*'([^']+)'", script_text)
            if match:
                raw_content = match.group(1)
                # 解码 HTML 实体
                raw_content = raw_content.replace("&ldquo;", "“").replace("&rdquo;", "”")
                raw_content = raw_content.replace("&mdash;", "—").replace("&hellip;", "…")
                raw_content = raw_content.replace("&nbsp;", " ").replace("&amp;", "&")
                raw_content = raw_content.replace("&lt;", "<").replace("&gt;", ">")
                if len(raw_content) > MIN_TEXT_LEN:
                    html, plain = clean_content(raw_content, url)
                    if len(plain) > MIN_TEXT_LEN:
                        return html, plain, soup

    # 先移除明显的噪音标签（不影响正文提取）
    for tag in soup(["script", "style", "nav", "footer", "header", "aside",
                     "iframe", "ins", "noscript"]):
        tag.decompose()

    # 移除广告和侧边栏
    for sel in [".ad", ".ads", ".sidebar", ".recommend", ".related",
                ".comment", ".share", ".breadcrumb", ".copyright"]:
        for el in soup.select(sel):
            el.decompose()

    # ─── 策略1: 使用 source_config 中的专属 content_selector ───
    if source_config and source_config.get("content_selector"):
        custom_sel = source_config["content_selector"]
        el = soup.select_one(custom_sel)
        if el:
            text = el.get_text(strip=True)
            if len(text) > MIN_TEXT_LEN:
                html, plain = clean_content(str(el), url)
                if len(plain) > MIN_TEXT_LEN:
                    return html, plain, soup

    # ─── 策略2: 使用 <article> 标签 ───
    article_tag = soup.find("article")
    if article_tag:
        text = article_tag.get_text(strip=True)
        if len(text) > MIN_TEXT_LEN:
            html, plain = clean_content(str(article_tag), url)
            if len(plain) > MIN_TEXT_LEN:
                return html, plain, soup

    # ─── 策略2: 使用常见正文容器选择器 ───
    content_selectors = [
        # 中文新闻网站专属选择器
        "#text_area",                # 央视网 (cctv.com)
        ".news_content",             # 央视网
        "#article_content",          # 人民网
        ".article_content",          # 人民网
        ".p_content",                # 澎湃新闻
        ".txt_con",                  # 新华网
        ".pages_content",            # 新华网
        ".detail-content",           # 通用详情页
        ".article-content",          # 通用
        ".article-body",             # 通用
        ".content_area",             # 央广网
        ".article-body-content",     # 光明网
        ".article_content_wrap",     # 搜狐
        ".article-box",              # 网易
        ".content-article",          # 腾讯
        ".text_article",             # 中国新闻网
        ".TRS_Editor",               # 人民网 TRS
        ".rich_media_content",       # 微信公众号
        # 英文新闻网站
        "article .story-body",       # CNN
        "[data-module='ArticleBody']",  # AP
        ".post-content",             # WordPress
        ".entry-content",            # WordPress
        # 通用回退
        ".main-content",
        "#content",
        ".content",
        ".post-body",
        ".news-text",
    ]

    for sel in content_selectors:
        el = soup.select_one(sel)
        if el:
            text = el.get_text(strip=True)
            if len(text) > MIN_TEXT_LEN:
                html, plain = clean_content(str(el), url)
                if len(plain) > MIN_TEXT_LEN:
                    return html, plain, soup

    # ─── 策略3: 提取最长连续文本块（密度检测法）───
    best_text = ""
    best_html = ""
    for div in soup.find_all(["div", "section"]):
        text = div.get_text(strip=True)
        if len(text) < MIN_TEXT_LEN:
            continue
        # 检查文本密度：文本长度 / 子标签数量，过滤导航和列表
        tag_count = len(div.find_all())
        if tag_count > 0 and len(text) / tag_count < 10:
            continue
        # 过滤包含过多链接的块（通常是导航）
        link_count = len(div.find_all("a"))
        if link_count > 0 and link_count / max(tag_count, 1) > 0.5:
            continue
        if len(text) > len(best_text):
            best_text = text
            best_html = str(div)

    if best_text and len(best_text) > MIN_TEXT_LEN:
        html, plain = clean_content(best_html, url)
        if len(plain) > MIN_TEXT_LEN:
            return html, plain, soup

    # ─── 策略4: 提取所有 <p> 标签拼接 ───
    paragraphs = soup.find_all("p")
    if paragraphs:
        # 过滤掉过短的段落（可能是按钮文字、版权信息等）
        valid_ps = [p for p in paragraphs if len(p.get_text(strip=True)) > 10]
        if valid_ps:
            # 重建 HTML
            from html import escape
            p_html_parts = []
            p_text_parts = []
            for p in valid_ps[:50]:  # 最多 50 段
                p_text = p.get_text(strip=True)
                # 过滤噪音段落
                skip_words = ["首页", "导航", "登录", "注册", "下载APP", "客户端",
                              "分享到", "责任编辑", "编辑：", "来源：", "【纠错】",
                              "相关阅读", "推荐阅读", "延伸阅读", "精彩推荐",
                              "凡本网", "版权", "举报", "纠错", "点击进入",
                              "关键词", "责任编辑", "原标题"]
                if any(w in p_text for w in skip_words) and len(p_text) < 50:
                    continue
                p_html_parts.append(f"<p>{escape(p_text)}</p>")
                p_text_parts.append(p_text)

            combined_text = "\n".join(p_text_parts)
            combined_html = "\n".join(p_html_parts)
            if len(combined_text) > MIN_TEXT_LEN:
                return combined_html, combined_text, soup

    # ─── 策略5: 全文提取兜底 ───
    all_text = soup.get_text("\n", strip=True)
    # 取中间部分（跳过开头导航和结尾版权）
    lines = [l.strip() for l in all_text.split("\n") if len(l.strip()) > 10]
    if len(lines) > 3:
        # 跳过前 3 行和后 3 行
        middle_lines = lines[3:-3]
        fallback_text = "\n".join(middle_lines)
        if len(fallback_text) > MIN_TEXT_LEN:
            from html import escape
            fallback_html = "\n".join(f"<p>{escape(l)}</p>" for l in middle_lines[:30])
            return fallback_html, fallback_text, soup

    return "", "", soup


# 保留旧函数名作为兼容别名
def fetch_article_content(url: str) -> str:
    """兼容旧接口：返回纯文本正文。"""
    result = extract_article_content(url)
    return result[1] if len(result) > 1 else ""


def crawl_all_sources(sources: List[Dict] = None, parallel: bool = False) -> List[Dict]:
    """Crawl all configured sources"""
    if sources is None:
        sources = NEWS_SOURCES

    all_articles = []
    total_new = 0

    print(f"\n{'='*60}")
    print(f"  NewsHub Multi-Source Crawler")
    print(f"  Sources: {len(sources)}")
    print(f"{'='*60}")

    if parallel:
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {executor.submit(crawl_source, src): src for src in sources}
            for future in as_completed(futures):
                src = futures[future]
                try:
                    articles = future.result()
                    all_articles.extend(articles)
                    print(f"  ✅ {src['name']}: {len(articles)} articles")
                except Exception as e:
                    print(f"  ❌ {src['name']}: {e}")
    else:
        for src in sources:
            try:
                articles = crawl_source(src)
                all_articles.extend(articles)
                print(f"  ✅ {src['name']}: {len(articles)} articles")
            except Exception as e:
                print(f"  ❌ {src['name']}: {e}")

    # Deduplicate by URL
    seen = set()
    unique = []
    for art in all_articles:
        if art["url"] not in seen:
            seen.add(art["url"])
            unique.append(art)

    print(f"\n  Total: {len(unique)} unique articles from {len(sources)} sources")
    return unique


def _normalize_title(title: str) -> str:
    """Normalize title for comparison: remove punctuation and whitespace."""
    import unicodedata
    title = re.sub(r'[\s　]+', '', title)
    title = re.sub(r'[^\w一-鿿]', '', title)
    return title.lower()


def _is_title_duplicate(title: str, existing_titles: list, threshold: float = 0.7) -> bool:
    """Check if title is similar to any existing title."""
    from difflib import SequenceMatcher
    norm = _normalize_title(title)
    if len(norm) < 4:
        return False
    for et in existing_titles:
        ratio = SequenceMatcher(None, norm, et).ratio()
        if ratio > threshold:
            return True
    return False


def save_to_db(articles: List[Dict], db, fetch_content: bool = True) -> int:
    """Save articles to database, skip duplicates (URL + title similarity)
    fetch_content: 是否为新文章抓取正文内容（默认开启）
    纯爬虫方案：正文和摘要均从页面直接提取，零 AI 消耗
    """
    from models import NewsArticle
    from datetime import timedelta

    # 构建新闻源配置查找表（按 name 索引）
    source_config_map = {src["name"]: src for src in NEWS_SOURCES}

    # 确保数据库会话状态正常
    try:
        db.rollback()
    except Exception:
        pass

    # Pre-load recent titles for similarity check
    cutoff = datetime.now() - timedelta(days=2)
    recent = db.query(NewsArticle).filter(NewsArticle.created_at >= cutoff).all()
    existing_titles = [_normalize_title(a.title) for a in recent if a.title]
    existing_urls = {a.url for a in recent}

    new_count = 0
    fetched_count = 0
    for art in articles:
        # URL dedup
        if art["url"] in existing_urls:
            continue

        # Title similarity dedup
        if _is_title_duplicate(art["title"], existing_titles):
            continue

        # Ensure published_at is a datetime or None
        pub = art.get("published_at")
        if isinstance(pub, str):
            pub = _parse_rss_date(pub) if hasattr(_parse_rss_date, '__call__') else None

        # 初始化 content 和 summary
        content_html = ""
        content_text = ""
        summary = ""

        # 获取该新闻源的专属配置（含 content_selector）
        src_cfg = source_config_map.get(art.get("source", ""), None)

        # 抓取正文 + 摘要（纯爬虫，零 AI）
        if fetch_content and art.get("url"):
            try:
                html, plain, page_soup = extract_article_content(
                    art["url"], art.get("source", ""), source_config=src_cfg
                )
                if plain and len(plain) > 50:
                    content_html = html[:50000]
                    content_text = plain
                    fetched_count += 1
                    print(f"    ✅ 正文抓取成功: {len(plain)} 字 - {art['title'][:30]}...")
                else:
                    print(f"    ⚠ 正文抓取为空: {art['title'][:30]}...")

                # 提取摘要（元描述 → 正文前200字 → 标题兜底）
                summary = extract_summary(page_soup, content_text, art["title"])

            except Exception as e:
                print(f"    ❌ 正文抓取失败: {art['title'][:30]}... {e}")
                # 抓取失败时，用标题兜底
                summary = fallback_summary(art["title"])

        # 如果摘要仍为空（未进入 fetch_content 分支），用 RSS 摘要或标题兜底
        if not summary:
            rss_summary = str(art.get("summary", ""))[:300]
            summary = rss_summary if rss_summary else fallback_summary(art["title"])

        # 逐条保存，遇到重复 URL 立即跳过，不影响其他文章
        try:
            article = NewsArticle(
                title=art["title"],
                url=art["url"],
                source=art["source"],
                category=art["category"],
                summary=summary[:500],
                content=content_html,
                image_url=str(art.get("image_url", ""))[:1000],
                published_at=pub,
            )
            db.add(article)
            db.commit()
            existing_urls.add(art["url"])
            existing_titles.append(_normalize_title(art["title"]))
            new_count += 1
        except Exception as e:
            db.rollback()
            # 如果是重复 URL，静默跳过
            if "UNIQUE constraint failed" in str(e) and "url" in str(e):
                existing_urls.add(art["url"])
                continue
            # 其他错误，打印日志但不中断
            print(f"    ⚠ 保存失败: {art['title'][:30]}... {e}")

    if fetched_count > 0:
        print(f"  📝 新增 {new_count} 篇文章，其中 {fetched_count} 篇成功抓取正文")
    return new_count


def fetch_missing_content(limit: int = 20):
    """为 content 为空的文章补充抓取正文（纯爬虫，零 AI 消耗）
    同时补充提取摘要（元描述 → 正文前200字 → 标题兜底）
    """
    from database import SessionLocal
    from models import NewsArticle

    # 构建新闻源配置查找表
    source_config_map = {src["name"]: src for src in NEWS_SOURCES}

    db = SessionLocal()
    articles = db.query(NewsArticle).filter(
        NewsArticle.is_duplicate == False,
        (NewsArticle.content == None) | (NewsArticle.content == "")
    ).order_by(NewsArticle.created_at.desc()).limit(limit).all()

    if not articles:
        print("  ✅ 所有文章已有正文内容")
        db.close()
        return

    print(f"  📥 正在为 {len(articles)} 篇文章补充正文...")
    success = 0
    fallback = 0
    for i, art in enumerate(articles):
        print(f"  [{i+1}/{len(articles)}] {art.title[:40]}...")
        try:
            src_cfg = source_config_map.get(art.source, None)
            html, plain, page_soup = extract_article_content(
                art.url, art.source, source_config=src_cfg
            )
            if plain and len(plain) > 50:
                art.content = html[:50000]
                # 用纯爬虫方式补充摘要
                if not art.summary:
                    art.summary = extract_summary(page_soup, plain, art.title)
                success += 1
                print(f"    ✅ 抓取成功: {len(plain)} 字")
            else:
                # 正文抓取失败，使用兜底方案
                if not art.summary:
                    art.summary = extract_summary(page_soup, "", art.title)
                art.content = ""  # 标记为空（已尝试过）
                fallback += 1
                print(f"    ⚠ 抓取失败，已设置兜底摘要")
        except Exception as e:
            if not art.summary:
                art.summary = fallback_summary(art.title)
            art.content = ""
            fallback += 1
            print(f"    ❌ 抓取出错: {e}")

    db.commit()
    db.close()
    print(f"\n  📊 完成: 成功 {success} 篇, 兜底 {fallback} 篇, 共处理 {len(articles)} 篇")


if __name__ == "__main__":
    print("=== NewsHub Multi-Source Crawler ===")

    from database import init_db, SessionLocal
    from models import NewsSource, NewsArticle

    init_db()
    db = SessionLocal()

    # Ensure all sources exist in DB
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

    # Crawl all
    articles = crawl_all_sources()

    # Save
    new_count = save_to_db(articles, db)

    # Update source stats
    for src in NEWS_SOURCES:
        source = db.query(NewsSource).filter(NewsSource.name == src["name"]).first()
        if source:
            source.article_count = db.query(NewsArticle).filter(
                NewsArticle.source == src["name"]
            ).count()
            source.last_crawled_at = datetime.now()
    db.commit()

    # Stats
    total = db.query(NewsArticle).count()
    cats = {}
    for a in db.query(NewsArticle).all():
        cats[a.category] = cats.get(a.category, 0) + 1

    db.close()

    print(f"\n{'='*60}")
    print(f"  Done! {new_count} new articles. Total in DB: {total}")
    for k, v in sorted(cats.items()):
        print(f"    {k}: {v}")
    print(f"{'='*60}")
