"""Telegram notification for breaking news.
Setup:
1. Create a Telegram bot via @BotFather, get the BOT_TOKEN
2. Start a chat with your bot, send any message
3. Visit https://api.telegram.org/bot<TOKEN>/getUpdates to find your CHAT_ID
4. Add to config.py:
   TELEGRAM_BOT_TOKEN = "your_token"
   TELEGRAM_CHAT_ID = "your_chat_id"
"""
import requests

# Fill these in to enable Telegram notifications
TELEGRAM_BOT_TOKEN = ""
TELEGRAM_CHAT_ID = ""

BREAKING_KEYWORDS = [
    "突发", "快讯", "重磅", "紧急", "刚刚",
    "breaking", "urgent", "just in",
]


def is_breaking(title: str) -> bool:
    """Check if an article looks like breaking news."""
    title_lower = title.lower()
    return any(kw in title_lower for kw in BREAKING_KEYWORDS)


def send_telegram(message: str) -> bool:
    """Send a message via Telegram bot."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        resp = requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }, timeout=10)
        return resp.ok
    except Exception as e:
        print(f"  ⚠ Telegram error: {e}")
        return False


def notify_new_article(title: str, source: str, category: str, url: str):
    """Send notification for a new article if it's breaking news."""
    if not is_breaking(title):
        return

    cat_icons = {
        "china": "🇨🇳", "international": "🌍", "finance": "💰",
        "tech": "💻", "military": "🎖️", "sports": "⚽",
        "society": "🏙️", "other": "📋",
    }
    icon = cat_icons.get(category, "📋")

    message = (
        f"🚨 <b>突发新闻</b>\n\n"
        f"{icon} {title}\n\n"
        f"来源: {source}\n"
        f'<a href="{url}">阅读原文</a>'
    )
    send_telegram(message)


def notify_daily_summary(count: int, top_categories: dict):
    """Send a daily summary notification."""
    if not TELEGRAM_BOT_TOKEN:
        return

    lines = [f"📊 <b>NewsHub 日报</b>\n", f"今日新增 {count} 条新闻\n"]
    for cat, cnt in sorted(top_categories.items(), key=lambda x: -x[1])[:5]:
        lines.append(f"  • {cat}: {cnt} 条")

    send_telegram("\n".join(lines))
