import os
import feedparser
import openai
import requests
from datetime import datetime

# Environment variables
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Feeds to fetch 
FEEDS = [
    "https://cryptojoblist.com/jobs.rss",
    "https://remotive.com/remote-jobs/blockchain.rss",
    "https://rss.app/feeds/gE9CSXedtEJIRnpS.xml"
]

KEYWORDS = ["web3", "blockchain", "crypto", "defi", "nft", "smart contract"]
POSTED_FILE = "posted.txt"


def load_posted():
    if not os.path.exists(POSTED_FILE):
        return set()
    with open(POSTED_FILE, "r") as f:
        return set(line.strip() for line in f)


def save_posted(ids):
    with open(POSTED_FILE, "w") as f:
        f.write("\n".join(ids))


def call_openai_short_summary(title, link, summary):
    openai.api_key = OPENAI_API_KEY
    prompt = f"Format this job posting for Telegram (no emoji, clean text):\nTitle: {title}\nSummary: {summary}\nLink: {link}\nHashtag: #XCROO"
    response = openai.ChatCompletion.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=150
    )
    return response.choices[0].message.content.strip()


def send_to_telegram(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {"chat_id": CHAT_ID, "text": text}
    requests.post(url, data=data)


def main():
    posted = load_posted()
    new_posted = set(posted)
    for feed_url in FEEDS:
        feed = feedparser.parse(feed_url)
        for entry in feed.entries[:5]:
            if entry.link in posted:
                continue
            text = f"{entry.title} {entry.summary}".lower()
            if any(k in text for k in KEYWORDS):
                message = call_openai_short_summary(entry.title, entry.link, entry.summary)
                send_to_telegram(message)
                new_posted.add(entry.link)
    save_posted(new_posted)


if __name__ == "__main__":
    main()
