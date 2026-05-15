"""Manual crawl - run this to fetch new articles immediately"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from crawlers.rss_crawler import crawl_all
from api.summarizer import process_pending

if __name__ == "__main__":
    print("=== Manual Crawl ===")
    crawl_all()
    print("\n=== AI Summary ===")
    process_pending(limit=100)
    print("\nAll done!")
