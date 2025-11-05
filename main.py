import os
import feedparser
import requests
import openai
import time
import re

# ===== CONFIG =====
FEEDS = [

    "https://api.cryptojobslist.com/jobs.rss",     # CryptoJobList
    "https://remotive.com/remote-jobs/feed"  # Remotive Blockchain
]

KEYWORDS = ["web3", "design", "marketing", "frontend", "blockchain", "crypto", "solidity", "defi", "business", "ethereum", "developer", "manager"]
POSTED_FILE = "posted.txt"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

openai.api_key = OPENAI_API_KEY


# ===== UTILITIES =====
def read_posted():
    if not os.path.exists(POSTED_FILE):
        return set()
    with open(POSTED_FILE, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())


def write_posted(posted):
    with open(POSTED_FILE, "w", encoding="utf-8") as f:
        for url in posted:
            f.write(url + "\n")


def clean_html(raw_html):
    return re.sub(re.compile("<.*?>"), "", raw_html)


# ===== AI SHORT SUMMARY =====
def summarize_with_openai(title, description, link):
    prompt = f"""
Summarize this Web3 job posting in 2 short lines for Telegram.
Keep it clean and professional. No emojis.

Title: {title}
Description: {description}
Link: {link}
"""
    try:
        response = openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=120,
            temperature=0.3,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"[ERROR] OpenAI error: {e}")
        return f"{title}\n{link}"


# ===== TELEGRAM POST =====
def send_to_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "disable_web_page_preview": False,
    }
    try:
        r = requests.post(url, data=payload, timeout=10)
        if r.status_code == 200:
            print(f"[✅] Posted successfully to Telegram.")
        else:
            print(f"[❌] Telegram post failed: {r.status_code} - {r.text}")
    except Exception as e:
        print(f"[ERROR] Telegram error: {e}")


# ===== MAIN JOB FETCHER =====
def main():
    posted = read_posted()
    new_posted = set(posted)

    print(f"\n========== XCROO BOT START ==========")
    print(f"Loaded {len(posted)} previously posted jobs.\n")

    for feed_url in FEEDS:
        print(f"\n[DEBUG] Checking feed: {feed_url}")
        feed = feedparser.parse(feed_url)
        if not feed.entries:
            print("  [!] No entries found in feed.")
            continue

        for entry in feed.entries:
            title = entry.get("title", "")
            summary = clean_html(entry.get("summary", ""))
            link = entry.get("link", "")

            print(f" - Found job: {title}")

            if link in posted:
                continue

            # Keyword filter
            text_blob = f"{title.lower()} {summary.lower()}"
            if not any(keyword in text_blob for keyword in KEYWORDS):
                continue

            print(f"   [MATCH] {title}")

            # Summarize
            message = summarize_with_openai(title, summary, link)
            formatted_message = f"{message}\n\n#xcroo\n\n🔗 {link}"

            # Post to Telegram
            send_to_telegram(formatted_message)

            # Mark as posted
            new_posted.add(link)

            # Respect API limits
            time.sleep(3)

    write_posted(new_posted)
    print("\n========== XCROO BOT END ==========\n")


if __name__ == "__main__":
    main()
