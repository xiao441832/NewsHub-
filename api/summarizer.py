"""AI Summarizer - generates Chinese summaries and auto-classifies articles using MiMo API"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from openai import OpenAI
from config import MIMO_API_BASE, MIMO_API_KEY, MIMO_MODEL, CATEGORIES

client = OpenAI(base_url=MIMO_API_BASE, api_key=MIMO_API_KEY)


VALID_CATEGORIES = {"china", "international", "finance", "tech", "military", "sports", "society", "local", "other"}


def classify_by_source(source: str, title: str) -> str:
    """Classify based on source name (most reliable method)"""
    source_lower = source.lower()
    title_lower = title.lower()

    # 国内媒体
    china_sources = ["央视", "新华社", "新华", "人民日报", "中新网", "中国新闻", "环球网", "澎湃", "央视新闻"]
    for s in china_sources:
        if s in source:
            return "china"

    # 地方媒体
    local_sources = ["南方都市", "新京报", "封面新闻", "界面", "南方周末", "钱江晚报", "扬子晚报"]
    for s in local_sources:
        if s in source:
            return "local"

    # 国外媒体（英文来源）
    intl_sources = ["BBC", "Reuters", "CNN", "Al Jazeera", "AP", "NYT", "Guardian", "France24"]
    for s in intl_sources:
        if s.lower() in source_lower:
            return "international"

    # 科技媒体
    tech_sources = ["TechCrunch", "Hacker News", "The Verge", "36Kr", "Ars Technica", "少数派", "sspai"]
    for s in tech_sources:
        if s.lower() in source_lower:
            return "tech"

    # 财经媒体
    finance_sources = ["经济", "财经", "证券", "stock", "finance", "bloomberg", "wsj"]
    for s in finance_sources:
        if s in source_lower or s in title_lower:
            return "finance"

    # 军事
    military_sources = ["军事", "国防", "military", "defense", "武器", "导弹"]
    for s in military_sources:
        if s in source_lower or s in title_lower:
            return "military"

    # 体育
    sports_sources = ["体育", "sport", "足球", "篮球", "NBA", "CBA", "奥运", "世界杯"]
    for s in sports_sources:
        if s in source_lower or s in title_lower:
            return "sports"

    # 根据关键词判断
    china_keywords = ["中国", "国内", "政府", "中央", "总书记", "国务院", "两会", "党员", "习近平"]
    intl_keywords = ["global", "world", "international", "us", "europe", "war", "nato", "UN", "美国", "欧洲", "俄罗斯"]

    for kw in china_keywords:
        if kw in title_lower:
            return "china"
    for kw in intl_keywords:
        if kw in title_lower:
            return "international"

    return "other"


def summarize(title: str, content: str) -> str:
    """Generate Chinese summary using MiMo"""
    text = (content or title)[:1500]
    prompt = f"用中文写一句话新闻摘要（不超过60字）：\n标题：{title}\n内容：{text}"

    try:
        resp = client.chat.completions.create(
            model=MIMO_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=150,
        )
        summary = (resp.choices[0].message.content or "").strip()
        if summary and len(summary) > 5:
            return summary[:120]
    except Exception as e:
        print(f"  ⚠ Summarize error: {e}")

    return title[:80]


def extract_tags(title: str, content: str = "") -> str:
    """Extract keyword tags from title and content. Falls back to MiMo if few matches."""
    text = (title or "") + " " + (content or "")[:500]

    tag_keywords = {
        "AI": ["AI", "人工智能", "ChatGPT", "GPT", "大模型", "LLM", "深度学习", "机器学习", "Gemini", "Claude"],
        "中美关系": ["中美", "美国", "白宫", "华盛顿", "贸易战", "关税"],
        "股市": ["股市", "A股", "港股", "美股", "纳斯达克", "上证", "深证", "涨停", "跌停"],
        "房地产": ["房价", "楼市", "房地产", "房贷", "限购", "土地"],
        "芯片": ["芯片", "半导体", "台积电", "英伟达", "NVIDIA", "光刻机"],
        "新能源": ["新能源", "电动车", "电池", "充电", "光伏", "风电", "特斯拉", "比亚迪"],
        "俄乌": ["俄罗斯", "乌克兰", "普京", "泽连斯基", "北约", "NATO"],
        "中东": ["以色列", "巴勒斯坦", "哈马斯", "伊朗", "中东", "加沙"],
        "太空": ["太空", "航天", "火箭", "卫星", "空间站", "NASA", "SpaceX"],
        "5G/通信": ["5G", "6G", "通信", "华为", "中兴"],
        "互联网": ["互联网", "腾讯", "阿里", "字节", "百度", "美团", "京东", "拼多多"],
        "健康": ["健康", "医疗", "新冠", "疫苗", "医院", "药物"],
    }

    tags = []
    for tag, keywords in tag_keywords.items():
        for kw in keywords:
            if kw.lower() in text.lower():
                tags.append(tag)
                break

    # If keyword matching found fewer than 2 tags, try MiMo
    if len(tags) < 2:
        try:
            ai_tags = _extract_tags_ai(title, content)
            for t in ai_tags:
                if t not in tags:
                    tags.append(t)
        except Exception:
            pass

    return ",".join(tags[:5])


def _extract_tags_ai(title: str, content: str = "") -> list:
    """Use MiMo to extract tags from article."""
    text = (title or "")[:200]
    prompt = f"从以下新闻标题中提取2-4个关键词标签，用逗号分隔，不要解释：\n{text}"
    try:
        resp = client.chat.completions.create(
            model=MIMO_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=60,
        )
        result = (resp.choices[0].message.content or "").strip()
        tags = [t.strip() for t in result.replace("，", ",").split(",") if t.strip() and len(t.strip()) < 10]
        return tags[:4]
    except Exception:
        return []


def summarize_and_classify(title: str, content: str, source: str = "") -> dict:
    """Summarize + classify an article"""
    summary = summarize(title, content)
    category = classify_by_source(source, title)
    tags = extract_tags(title, content)
    return {"summary": summary, "category": category, "tags": tags}


def process_pending(limit: int = 50):
    """Find articles without Chinese summaries and process them"""
    from database import SessionLocal
    from models import NewsArticle

    db = SessionLocal()
    all_articles = db.query(NewsArticle).filter(
        NewsArticle.is_duplicate == False,
    ).all()

    articles = []
    for art in all_articles:
        has_chinese = any(0x4e00 <= ord(c) <= 0x9fff for c in (art.summary or ""))
        if not has_chinese:
            articles.append(art)
        if len(articles) >= limit:
            break

    if not articles:
        print("  No articles need processing.")
        db.close()
        return

    print(f"  Processing {len(articles)} articles...")
    processed = 0
    for art in articles:
        result = summarize_and_classify(art.title, art.content or "", art.source)
        art.summary = result["summary"]
        art.category = result["category"]
        if result.get("tags"):
            art.tags = result["tags"]
        processed += 1
        print(f"  [{processed}/{len(articles)}] {art.title[:35]}... → {result['category']}")

    db.commit()
    db.close()
    print(f"  Done! {processed} articles processed.")


def reclassify_all():
    """Re-classify all articles based on new category system"""
    from database import SessionLocal
    from models import NewsArticle

    db = SessionLocal()
    articles = db.query(NewsArticle).filter(NewsArticle.is_duplicate == False).all()
    print(f"  Reclassifying {len(articles)} articles...")

    for art in articles:
        new_cat = classify_by_source(art.source, art.title)
        if new_cat != art.category:
            art.category = new_cat

    db.commit()
    db.close()
    print("  Done!")


if __name__ == "__main__":
    print("=== AI Summary & Classification ===")
    process_pending(limit=100)
