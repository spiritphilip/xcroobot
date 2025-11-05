import os
import time
import feedparser
import requests
from datetime import datetime
from openai import OpenAI

# ========== CONFIGURATION ==========
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

FEEDS = [
    "https://api.cryptojobslist.com/jobs.rss",     # CryptoJobList
    "https://remotive.com/remote-jobs/feed"  # Remotive Blockchain
]

KEYWORDS = ["web3", "blockchain", "crypto", "defi", "solidity", "nft", "ethereum", "smart contract"]
POSTED_FILE = "posted.txt"

client = OpenAI(api_key=OPENAI_API_KEY)

# ========== HELPERS ==========

def load_posted():
    if not os.path.exists(POSTED_FILE):
        return set()
    with open(POSTED_FILE, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f.readlines())

def save_posted(posted_set):
    with open(POSTED_FILE, "w", encoding="utf-8") as f:
        for url in posted_set:
            f.write(url + "\n")

def fetch_jobs():
    jobs = []
    for feed_url in FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries:
                title = entry.get("title", "")
                summary = entry.get("summary", "")
                link = entry.get("link", "")
                lower = f"{title} {summary}".lower()
                if any(k in lower for k in KEYWORDS):
                    jobs.append({
                        "title": title,
                        "description": summary,
                        "link": link,
                        "company": entry.get("author", "Company"),
                    })
        except Exception as e:
            print(f"Error parsing feed {feed_url}: {e}")
    return jobs

def call_openai_summary(text):
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Summarize job posts cleanly in one sentence for a professional feed."},
                {"role": "user", "content": text}
            ],
            max_tokens=80,
            temperature=0.6
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print("OpenAI API Error:", e)
        return text[:200]

# ========== FORMATTER ==========

def format_for_telegram(job):
    """
    Format each job post in clean Markdown style for Telegram.
    """
    title = job.get("title", "Job Opening").strip()
    company = job.get("company", "A company").strip()
    link = job.get("link", "").strip()
    description = job.get("description", "").strip()

    if len(description) > 300:
        description = description[:300].rstrip() + "..."

    # Markdown-safe escape
    def esc(text):
        return (
            text.replace("_", "\\_")
                .replace("*", "\\*")
                .replace("[", "\\[")
                .replace("`", "\\`")
                .replace("(", "\\(")
                .replace(")", "\\)")
        )

    formatted = (
        f"*XCROO Job Update*\n\n"
        f"{esc(company)} is hiring "
        f"[{esc(title)}]({link})\n\n"
        f"*About:* {esc(description)}\n\n"
        f"#XCROO #OnChainTalent #Web3Jobs #FullStack"
    )
    return formatted

# ========== TELEGRAM POSTING ==========

def send_telegram_message(message: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "MarkdownV2",
        "disable_web_page_preview": True
    }
    r = requests.post(url, json=payload)
    if not r.ok:
        print("Telegram post failed:", r.text)
    else:
        print("Posted to Telegram ✅")

# ========== MAIN EXECUTION ==========

def main():
    print(f"XCROO BOT RUN STARTED: {datetime.utcnow()} UTC")

    posted = load_posted()
    jobs = fetch_jobs()

    new_jobs = [job for job in jobs if job["link"] not in posted]

    print(f"Fetched {len(jobs)} jobs, {len(new_jobs)} new ones.")

    for job in new_jobs:
        desc = call_openai_summary(job["description"])
        job["description"] = desc
        message = format_for_telegram(job)
        send_telegram_message(message)
        posted.add(job["link"])
        time.sleep(5)  # Avoid Telegram rate limit

    save_posted(posted)
    print("XCROO BOT RUN COMPLETE ✅")

if __name__ == "__main__":
    main()

