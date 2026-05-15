"""Web Crawler - extracts full article text from URLs"""
import re
from typing import Optional
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from config import REQUEST_TIMEOUT, USER_AGENT

# Tags that typically contain article body
CONTENT_TAGS = [
    {"tag": "article"},
    {"tag": "div", "class": re.compile(r"(article|post|content|story|entry)", re.I)},
    {"tag": "div", "id": re.compile(r"(article|post|content|story|entry)", re.I)},
    {"tag": "main"},
]

# Tags to strip (ads, nav, footer, sidebar, etc.)
STRIP_TAGS = [
    "nav", "footer", "header", "aside",
    "script", "style", "noscript", "iframe",
]

STRIP_CLASSES = re.compile(
    r"(sidebar|comment|share|social|related|recommend|ad-|advert|popup|modal)",
    re.I,
)


def extract_article(url: str) -> Optional[str]:
    """Fetch a URL and extract the main article text"""
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
        )
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        # Remove unwanted tags
        for tag_name in STRIP_TAGS:
            for el in soup.find_all(tag_name):
                el.decompose()

        # Remove elements with ad/sidebar-like classes
        for el in soup.find_all(class_=STRIP_CLASSES):
            el.decompose()
        for el in soup.find_all(id=STRIP_CLASSES):
            el.decompose()

        # Try to find the main content container
        content_el = None
        for rule in CONTENT_TAGS:
            if "class" in rule:
                found = soup.find(rule["tag"], class_=rule["class"])
            elif "id" in rule:
                found = soup.find(rule["tag"], id=rule["id"])
            else:
                found = soup.find(rule["tag"])
            if found and len(found.get_text(strip=True)) > 200:
                content_el = found
                break

        # Fallback: use <body>
        if not content_el:
            content_el = soup.body or soup

        # Extract paragraphs
        paragraphs = []
        for p in content_el.find_all(["p", "h2", "h3"]):
            text = p.get_text(strip=True)
            if len(text) > 30:  # skip short fragments
                paragraphs.append(text)

        if not paragraphs:
            # Last resort: all text
            text = content_el.get_text(separator="\n", strip=True)
            return text[:3000]

        return "\n\n".join(paragraphs)[:3000]

    except Exception as e:
        print(f"  ✗ Failed to extract {urlparse(url).netloc}: {e}")
        return None


if __name__ == "__main__":
    # Quick test
    url = "https://techcrunch.com/"
    text = extract_article(url)
    if text:
        print(f"Extracted {len(text)} chars")
        print(text[:500])
    else:
        print("No content extracted")
