import os, time, random, feedparser, requests
from openai import OpenAI
from bs4 import BeautifulSoup

# =========================
# CONFIGURATION
# =========================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Multiple OpenAI keys (comma-separated in GitHub Secrets)
OPENAI_KEYS = os.getenv("OPENAI_API_KEYS", "").split(",")
MODEL = "gpt-4o-mini"

# Updated Feeds
FEEDS = [
    "https://www.remote3.co/api/rss",
    "https://www.workable.com/boards/workable.xml",
    "https://api.cryptojobslist.com/jobs.rss",
    "https://remotive.com/remote-jobs/feed",
]

# Broadened keywords to capture diverse roles
KEYWORDS = [
    "web3", "design", "marketing", "content", "analyst", "specialist",
    "frontend", "blockchain", "crypto", "solidity", "data", "defi",
    "business", "ethereum", "developer", "manager"
]

POSTED_FILE = "posted.txt"
HEADERS = {"User-Agent": "Mozilla/5.0"}

# =========================
# HELPER FUNCTIONS
# =========================

def rotate_openai_call(prompt):
    """Try multiple OpenAI keys for redundancy and failover"""
    for key in OPENAI_KEYS:
        try:
            client = OpenAI(api_key=key.strip())
            response = client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=100,
                temperature=0.7,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            print(f"⚠️ Key {key[:8]} failed → {e}")
            continue
    return "Summary unavailable due to API limits."

def post_to_telegram(message):
    """Send formatted message to Telegram"""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"}
    r = requests.post(url, json=payload)
    print("✅ Telegram:", r.status_code, r.text[:120])

def load_posted():
    if not os.path.exists(POSTED_FILE):
        return set()
    with open(POSTED_FILE, "r") as f:
        return set(line.strip() for line in f if line.strip())

def save_posted(ids):
    with open(POSTED_FILE, "w") as f:
        f.write("\n".join(ids))

# =========================
# MAIN JOB BOT LOGIC
# =========================

posted = load_posted()

for feed_url in FEEDS:
    print(f"📡 Fetching feed: {feed_url}")
    feed = feedparser.parse(feed_url)

    for entry in feed.entries[:6]:  # process top 6 per feed
        if entry.link in posted:
            continue

        title = entry.title
        link = entry.link
        company = getattr(entry, "author", "Company not specified").strip()

        # Filter out irrelevant jobs
        if not any(k.lower() in title.lower() for k in KEYWORDS):
            continue

        # Generate 2 relevant hashtags
        hashtags_prompt = f"Generate two relevant short hashtags for this job: '{title}' by {company}. Keep them one or two words."
        hashtags = rotate_openai_call(hashtags_prompt)
        hashtags = hashtags.replace("#", "").replace(" ", "")
        hashtags = " ".join([f"#{h}" for h in hashtags.split()[:2]])

        # Final Telegram message without 'About' section
        message = (
            f"*XCROO Job Update*\n\n"
            f"*{company}* is hiring [{title}]({link})\n\n"
            f"#XCROO #OnChainTalent #Web3Jobs {hashtags}"
        )

        post_to_telegram(message)
        posted.add(entry.link)
        time.sleep(5)

save_posted(posted)
print("✅ Job posting cycle complete.")
