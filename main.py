import os, time, random, feedparser, requests
from openai import OpenAI
from bs4 import BeautifulSoup
import re
from urllib.parse import urlparse, urlunparse

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
    return r.status_code == 200


def normalize_url(raw_url):
    """Return a simple canonical url for deduping:
       - normalize scheme to https
       - drop 'www.' prefix
       - drop query and fragment
       - strip trailing slash
    """
    if not raw_url:
        return raw_url
    p = urlparse(raw_url.strip())
    scheme = "https"
    netloc = p.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    path = p.path.rstrip("/")
    canonical = urlunparse((scheme, netloc, path, "", "", ""))
    return canonical


def load_posted():
    if not os.path.exists(POSTED_FILE):
        return set()
    with open(POSTED_FILE, "r", encoding="utf-8") as f:
        # Normalize existing entries as we load them to reduce duplicates from old data
        return set(normalize_url(line.strip()) for line in f if line.strip())


def append_posted_atomic(link):
    """Append a single canonical link to posted.txt immediately (minimizes race window)."""
    canonical = normalize_url(link)
    # Ensure directory exists (if needed) then append and flush to disk
    with open(POSTED_FILE, "a", encoding="utf-8") as f:
        f.write(canonical + "\n")
        f.flush()
        try:
            os.fsync(f.fileno())
        except Exception:
            pass


def save_posted(ids):
    """Write the full set atomically (deterministic order)."""
    tmp = POSTED_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for link in sorted(ids):
            f.write(link + "\n")
    os.replace(tmp, POSTED_FILE)


def make_hashtags_from_model(title, company):
    # Stronger prompt asking for a deterministic response
    prompt = (
        f"Generate exactly two short hashtags (no explanation), for this job:\n"
        f"Title: {title}\nCompany: {company}\n"
        f"Return the two tags only, separated by a single comma. Each tag must be one or two words and do NOT include the '#' character."
    )
    resp = rotate_openai_call(prompt)
    if not resp:
        return ""
    # Remove hashes then extract tokens using regex (words, numbers, +, -, _)
    resp = resp.replace("#", "")
    tokens = []
    if "," in resp:
        tokens = [t.strip() for t in resp.split(",") if t.strip()]
    else:
        tokens = re.findall(r"[A-Za-z0-9_+\-]+(?:\s+[A-Za-z0-9_+\-]+)?", resp)
        tokens = [t.strip() for t in tokens if t.strip()]
    tokens = tokens[:2]
    tokens = [re.sub(r"\s+", "", t) for t in tokens]
    return " ".join(f"#{t}" for t in tokens)

# =========================
# MAIN JOB BOT LOGIC
# =========================

posted = load_posted()

for feed_url in FEEDS:
    print(f"📡 Fetching feed: {feed_url}")
    feed = feedparser.parse(feed_url)

    for entry in feed.entries[:6]:  # process top 6 per feed
        raw_link = getattr(entry, "link", None) or getattr(entry, "id", None) or ""
        canonical_link = normalize_url(raw_link)
        if not canonical_link:
            continue

        if canonical_link in posted:
            # already posted (or canonical duplicate)
            continue

        title = getattr(entry, "title", "").strip()
        company = getattr(entry, "author", "Company not specified").strip()

        # Filter out irrelevant jobs
        if not any(k.lower() in title.lower() for k in KEYWORDS):
            continue

        # Generate 2 relevant hashtags robustly
        hashtags = make_hashtags_from_model(title, company)

        # Final Telegram message
        message = (
            f"*XCROO Job Update*\n\n"
            f"*{company}* is hiring [{title}]({raw_link})\n\n"
            f"#XCROO #OnChainTalent #Web3Jobs {hashtags}"
        )

        success = post_to_telegram(message)

        if success:
            # Mark as posted immediately (append to disk and to in-memory set)
            append_posted_atomic(canonical_link)
            posted.add(canonical_link)

        time.sleep(5)

save_posted(posted)
print("✅ Job posting cycle complete.")
