"""NewsHub Configuration"""
import os

# === Paths ===
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data", "news.db")

# === MiMo AI API ===
MIMO_API_BASE = "https://token-plan-cn.xiaomimimo.com/v1"
MIMO_API_KEY = "tp-cppn7tdnem4cyr3pdmykhs5ihg0ct2d1w0eb34e2bi5jz2mz"
MIMO_MODEL = "mimo-v2.5-pro"

# === Crawler ===
CRAWL_INTERVAL_HOURS = 4
MAX_ARTICLES_PER_SOURCE = 20
REQUEST_TIMEOUT = 10
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# === Web Server ===
HOST = "0.0.0.0"
PORT = 8080

# === 管理员账号 ===
ADMIN_USERS = ["坤坤"]

# === 分类体系 ===
CATEGORIES = {
    "china": "国内",
    "international": "国际",
    "finance": "财经",
    "tech": "科技",
    "military": "军事",
    "sports": "体育",
    "society": "社会",
    "local": "地方",
    "other": "其他",
}

# === 新闻源配置 ===
# type: "rss" / "json_api" / "web_scrape"
# content_selector: 正文容器的 CSS 选择器（可选，提升正文提取准确率）
NEWS_SOURCES = [
    # ─── 央视网 (JSON API) ───
    {"name": "央视·国内",   "url": "https://news.cctv.com/2019/07/gaiban/cmsdatainterface/page/china_{page}.jsonp", "type": "cctv_json", "lang": "zh", "category": "china", "content_selector": "#text_area"},
    {"name": "央视·国际",   "url": "https://news.cctv.com/2019/07/gaiban/cmsdatainterface/page/world_{page}.jsonp", "type": "cctv_json", "lang": "zh", "category": "international", "content_selector": "#text_area"},
    {"name": "央视·科技",   "url": "https://news.cctv.com/2019/07/gaiban/cmsdatainterface/page/tech_{page}.jsonp", "type": "cctv_json", "lang": "zh", "category": "tech", "content_selector": "#text_area"},
    {"name": "央视·社会",   "url": "https://news.cctv.com/2019/07/gaiban/cmsdatainterface/page/society_{page}.jsonp", "type": "cctv_json", "lang": "zh", "category": "society", "content_selector": "#text_area"},

    # ─── 人民网 (RSS) ───
    {"name": "人民网·时政", "url": "http://www.people.com.cn/rss/politics.xml", "type": "rss", "lang": "zh", "category": "china", "content_selector": ".rm_txt_con"},
    {"name": "人民网·国际", "url": "http://www.people.com.cn/rss/world.xml", "type": "rss", "lang": "zh", "category": "international", "content_selector": ".rm_txt_con"},
    {"name": "人民网·社会", "url": "http://www.people.com.cn/rss/society.xml", "type": "rss", "lang": "zh", "category": "society", "content_selector": ".rm_txt_con"},
    {"name": "人民网·财经", "url": "http://www.people.com.cn/rss/finance.xml", "type": "rss", "lang": "zh", "category": "finance", "content_selector": ".rm_txt_con"},
    {"name": "人民网·军事", "url": "http://www.people.com.cn/rss/military.xml", "type": "rss", "lang": "zh", "category": "military", "content_selector": ".rm_txt_con"},
    {"name": "人民网·体育", "url": "http://www.people.com.cn/rss/sports.xml", "type": "rss", "lang": "zh", "category": "sports", "content_selector": ".rm_txt_con"},

    # ─── 新浪新闻 (JSON API) ───
    {"name": "新浪·国内",   "url": "https://feed.mix.sina.com.cn/api/roll/get?pageid=153&lid=2516&k=&num=30&page=1", "type": "sina_json", "lang": "zh", "category": "china", "content_selector": "#artibody"},
    {"name": "新浪·国际",   "url": "https://feed.mix.sina.com.cn/api/roll/get?pageid=153&lid=2514&k=&num=30&page=1", "type": "sina_json", "lang": "zh", "category": "international", "content_selector": "#artibody"},
    {"name": "新浪·科技",   "url": "https://feed.mix.sina.com.cn/api/roll/get?pageid=153&lid=2515&k=&num=30&page=1", "type": "sina_json", "lang": "zh", "category": "tech", "content_selector": "#artibody"},
    {"name": "新浪·财经",   "url": "https://feed.mix.sina.com.cn/api/roll/get?pageid=153&lid=2517&k=&num=30&page=1", "type": "sina_json", "lang": "zh", "category": "finance", "content_selector": "#artibody"},
    {"name": "新浪·体育",   "url": "https://feed.mix.sina.com.cn/api/roll/get?pageid=153&lid=2512&k=&num=30&page=1", "type": "sina_json", "lang": "zh", "category": "sports", "content_selector": "#artibody"},
    {"name": "新浪·军事",   "url": "https://feed.mix.sina.com.cn/api/roll/get?pageid=153&lid=2518&k=&num=30&page=1", "type": "sina_json", "lang": "zh", "category": "military", "content_selector": "#artibody"},

    # ─── 中国日报 (RSS) ───
    {"name": "中国日报·国际", "url": "https://www.chinadaily.com.cn/rss/world_rss.xml", "type": "rss", "lang": "en", "category": "international", "content_selector": "#Content"},

    # ─── France24 (RSS) ───
    {"name": "France24", "url": "https://www.france24.com/en/rss", "type": "rss", "lang": "en", "category": "international", "content_selector": ".t-content__body"},

    # ─── 36氪 (RSS) ───
    {"name": "36氪",       "url": "https://36kr.com/feed", "type": "rss", "lang": "zh", "category": "tech", "content_selector": ".article-content"},
    {"name": "36氪·快讯",  "url": "https://36kr.com/feed-article", "type": "rss", "lang": "zh", "category": "tech", "content_selector": ".article-content"},

    # ─── 爱范儿 (RSS) ───
    {"name": "爱范儿",     "url": "https://www.ifanr.com/feed", "type": "rss", "lang": "zh", "category": "tech", "content_selector": ".article-content"},

    # ─── IT之家 (RSS) ───
    {"name": "IT之家",     "url": "https://www.ithome.com/rss/", "type": "rss", "lang": "zh", "category": "tech", "content_selector": ".post_content"},

    # ─── 少数派 (RSS) ───
    {"name": "少数派",     "url": "https://sspai.com/feed", "type": "rss", "lang": "zh", "category": "tech", "content_selector": ".article-content"},

    # ─── Solidot (RSS) ───
    {"name": "Solidot",    "url": "https://www.solidot.org/index.rss", "type": "rss", "lang": "zh", "category": "tech", "content_selector": ".p_content"},

    # ─── 华尔街日报 (RSS) ───
    {"name": "华尔街日报", "url": "https://feeds.a.dj.com/rss/RSSWorldNews.xml", "type": "rss", "lang": "en", "category": "international", "content_selector": ".article-content"},

    # ─── Hacker News (RSS) ───
    {"name": "Hacker News","url": "https://hnrss.org/frontpage", "type": "rss", "lang": "en", "category": "tech"},

    # ─── Engadget (RSS) ───
    {"name": "Engadget",   "url": "https://www.engadget.com/rss.xml", "type": "rss", "lang": "en", "category": "tech", "content_selector": ".article-text"},

    # ─── TechCrunch (RSS) ───
    {"name": "TechCrunch", "url": "https://techcrunch.com/feed/", "type": "rss", "lang": "en", "category": "tech", "content_selector": ".article-content"},

    # ─── The Verge (RSS) ───
    {"name": "The Verge",  "url": "https://www.theverge.com/rss/index.xml", "type": "rss", "lang": "en", "category": "tech", "content_selector": ".article-body"},

    # ─── NPR (RSS) ───
    {"name": "NPR",        "url": "https://feeds.npr.org/1001/rss.xml", "type": "rss", "lang": "en", "category": "international", "content_selector": ".storytext"},

    # ─── NHK World (RSS) ───
    {"name": "NHK World",  "url": "https://www3.nhk.or.jp/rss/news/cat0.xml", "type": "rss", "lang": "en", "category": "international", "content_selector": ".content-body"},

    # ─── 韩国先驱报 (RSS) ───
    {"name": "韩国先驱报", "url": "http://www.koreaherald.com/rss/020200000000.xml", "type": "rss", "lang": "en", "category": "international", "content_selector": ".article-body"},

    # ─── 网页抓取源 ───
    {"name": "新华网",     "url": "http://www.news.cn/", "type": "web_scrape", "lang": "zh", "category": "china", "scraper": "xinhua", "content_selector": "#detail"},
    {"name": "环球网",     "url": "https://www.huanqiu.com/", "type": "web_scrape", "lang": "zh", "category": "international", "scraper": "huanqiu", "content_selector": ".article-content"},
    {"name": "光明网",     "url": "https://www.gmw.cn/", "type": "web_scrape", "lang": "zh", "category": "china", "scraper": "gmw", "content_selector": "#articleContent"},
    {"name": "央广网",     "url": "https://www.cnr.cn/", "type": "web_scrape", "lang": "zh", "category": "china", "scraper": "cnr", "content_selector": ".text_con"},
    {"name": "百度新闻",   "url": "https://news.baidu.com/", "type": "web_scrape", "lang": "zh", "category": "other", "scraper": "baidu"},
    {"name": "澎湃新闻",   "url": "https://www.thepaper.cn/", "type": "web_scrape", "lang": "zh", "category": "society", "scraper": "thepaper", "content_selector": ".news_txt"},
    {"name": "CNN",        "url": "https://edition.cnn.com/", "type": "web_scrape", "lang": "en", "category": "international", "scraper": "cnn", "content_selector": ".article__content"},
    {"name": "AP News",    "url": "https://apnews.com/", "type": "web_scrape", "lang": "en", "category": "international", "scraper": "ap", "content_selector": "[data-module='ArticleBody']"},
    {"name": "联合早报",   "url": "https://www.zaobao.com/", "type": "web_scrape", "lang": "zh", "category": "international", "scraper": "zaobao", "content_selector": ".article-body"},
    {"name": "Yahoo Japan", "url": "https://news.yahoo.co.jp/", "type": "web_scrape", "lang": "ja", "category": "international", "scraper": "yahoojp", "content_selector": ".article_body"},

    # ─── 新增网页抓取源 ───
    {"name": "虎嗅",       "url": "https://www.huxiu.com/", "type": "web_scrape", "lang": "zh", "category": "tech", "scraper": "huxiu", "content_selector": ".article-content-wrap"},
    {"name": "界面新闻",   "url": "https://www.jiemian.com/", "type": "web_scrape", "lang": "zh", "category": "finance", "scraper": "jiemian", "content_selector": ".article-content"},
    {"name": "财联社",     "url": "https://www.cls.cn/", "type": "web_scrape", "lang": "zh", "category": "finance", "scraper": "cls", "content_selector": ".detail-content"},
    {"name": "第一财经",   "url": "https://www.yicai.com/", "type": "web_scrape", "lang": "zh", "category": "finance", "scraper": "yicai", "content_selector": ".m-text"},
    {"name": "每经新闻",   "url": "https://www.nbd.com.cn/", "type": "web_scrape", "lang": "zh", "category": "finance", "scraper": "nbd", "content_selector": ".g-article-content"},
    {"name": "证券时报",   "url": "https://www.stcn.com/", "type": "web_scrape", "lang": "zh", "category": "finance", "scraper": "stcn", "content_selector": ".detail-content"},
    {"name": "中国新闻网", "url": "https://www.chinanews.com/", "type": "web_scrape", "lang": "zh", "category": "china", "scraper": "chinanews", "content_selector": ".left_zw"},
    {"name": "凤凰网",     "url": "https://news.ifeng.com/", "type": "web_scrape", "lang": "zh", "category": "international", "scraper": "ifeng", "content_selector": ".text_3uYFO"},
]

# Legacy compatibility
RSS_SOURCES = [s for s in NEWS_SOURCES if s["type"] == "rss"]


def get_all_sources():
    """返回所有配置的新闻源列表（动态读取，不依赖数据库）"""
    return NEWS_SOURCES


def get_source_count():
    """返回配置的新闻源总数"""
    return len(NEWS_SOURCES)
