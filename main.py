import os
import time
import requests
import feedparser
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from openai import OpenAI

# ========= CONFIG =========
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

FEEDS = [
    "https://www.remote3.co/api/rss",
    "https://api.cryptojobslist.com/jobs.rss",
    "https://remotive.com/remote-jobs/feed",
    "https://linkedin.com/jobs/search?keywords=&location=Worldwide&geoId=92000000&trk=public_jobs_jobs-search-bar_search-submit"
]

POSTED_FILE = "posted.txt"
KEYWORDS = ["web3", "blockchain", "crypto", "solidity", "nft", "defi", "ethereum", "rust", "smart contract"]

client = OpenAI(api_key=OPENAI_API_KEY)

# ========= HELPERS =========

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
                published = entry.get("published_parsed")

                # Filter old jobs (older than 5 days)
                if published:
                    published_date = datetime(*published[:6])
                    if datetime.utcnow() - published_date > timedelta(days=5):
                        continue

                lower = f"{title} {summary}".lower()
                if any(k in lower for k in KEYWORDS):
                    jobs.append({
                        "title": title,
                        "description": summary,
                        "link": link,
                        "company": entry.get("author", "Company")
                    })
        except Exception as e:
            print(f"Error fetching from {feed_url}: {e}")
    return jobs

def scrape_job_page(url):
    """Fetch webpage content for better description."""
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code != 200:
            return ""
        soup = BeautifulSoup(resp.text, "html.parser")

        # Try to extract meaningful text
        paragraphs = soup.find_all(["p", "li"])
        text = " ".join([p.get_text(" ", strip=True) for p in paragraphs])
        text = " ".join(text.split())
        return text[:1500]  # limit tokens
    except Exception as e:
        print(f"Scrape failed for {url}: {e}")
        return ""

def call_openai_summary(title, company, description):
    """Use GPT to summarize and generate 2 job-specific hashtags."""
    prompt = f"""
Job Title: {title}
Company: {company}
Job Description: {description}

Create a short, professional 2-sentence summary of the role suitable for a Telegram post.
Then, generate two relevant hashtags (e.g. #FrontendDeveloper #FinTech) that fit this role.
Output in this format:
Summary: <text>
Hashtags: #tag1 #tag2
"""
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=120,
            temperature=0.7,
        )
        content = response.choices[0].message.content.strip()
        summary, hashtags = "", ""
        if "Summary:" in content:
            parts = content.split("Hashtags:")
            summary = parts[0].replace("Summary:", "").strip()
            if len(parts) > 1:
                hashtags = parts[1].strip()
        return summary, hashtags
    except Exception as e:
        print("OpenAI error:", e)
        return description[:200], ""

def escape_md(text):
    """Escape Telegram MarkdownV2 reserved characters."""
    for ch in "_*[]()~`>#+-=|{}.!":
        text = text.replace(ch, f"\\{ch}")
    return text

def format_for_telegram(job, summary, hashtags):
    title = escape_md(job.get("title", "Job Opening"))
    company = escape_md(job.get("company", "Company"))
    link = job.get("link", "").strip()
    about = escape_md(summary)

    base_tags = "#XCROO #OnChainTalent #Web3Jobs"
    all_tags = f"{base_tags} {hashtags}"

    formatted = (
        f"*XCROO Job Update*\n\n"
        f"*{company}* is hiring [{title}]({link})\n\n"
        f"*About:* {about}\n\n"
        f"{all_tags}"
    )
    return formatted

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "MarkdownV2",
        "disable_web_page_preview": True,
    }
    r = requests.post(url, json=payload)
    if not r.ok:
        print("Telegram Error:", r.text)
    else:
        print("✅ Posted successfully")

# ========= MAIN =========

def main():
    print(f"\nXCROO BOT RUN STARTED: {datetime.utcnow()} UTC")
    posted = load_posted()
    jobs = fetch_jobs()
    new_jobs = [job for job in jobs if job["link"] not in posted]
    print(f"Fetched {len(jobs)} total, {len(new_jobs)} new.")

    for job in new_jobs:
        print(f"Processing: {job['title']}")
        scraped_text = scrape_job_page(job["link"]) or job["description"]
        summary, hashtags = call_openai_summary(job["title"], job["company"], scraped_text)
        message = format_for_telegram(job, summary, hashtags)
        send_telegram(message)
        posted.add(job["link"])
        time.sleep(5)

    save_posted(posted)
    print("XCROO BOT RUN COMPLETE ✅")

if __name__ == "__main__":
    main()
