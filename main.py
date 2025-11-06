import os
import feedparser
import requests
from bs4 import BeautifulSoup
from openai import OpenAI
from datetime import datetime
import csv

# ====== CONFIG ======
FEEDS = [
     "https://www.remote3.co/api/rss",
    "https://api.cryptojobslist.com/jobs.rss",
    "https://remotive.com/remote-jobs/feed",
    "https://linkedin.com/jobs/search?keywords=&location=Worldwide&geoId=92000000&trk=public_jobs_jobs-search-bar_search-submit"

]

KEYWORDS = ["web3", "design", "marketing", "content", "analyst", "specialist", "frontend", "blockchain", "crypto", "solidity", "data", "defi", "business", "ethereum", "developer", "manager"]
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
OPENAI_KEY = os.getenv("OPENAI_API_KEY")

POSTED_FILE = "posted.txt"
INCOMPLETE_LOG = "incomplete_jobs.csv"

client = OpenAI(api_key=OPENAI_KEY)

# ====== HELPERS ======
def load_posted():
    if not os.path.exists(POSTED_FILE):
        return set()
    with open(POSTED_FILE, "r") as f:
        return set(line.strip() for line in f)

def save_posted(posted):
    with open(POSTED_FILE, "w") as f:
        for p in posted:
            f.write(p + "\n")

def log_incomplete(job):
    """Log incomplete jobs for later review."""
    header = ["date", "title", "link", "company", "summary"]
    exists = os.path.exists(INCOMPLETE_LOG)
    with open(INCOMPLETE_LOG, "a", newline='', encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=header)
        if not exists:
            writer.writeheader()
        writer.writerow({
            "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "title": job.get("title", "N/A"),
            "link": job.get("link", "N/A"),
            "company": job.get("company", "N/A"),
            "summary": job.get("summary", "N/A")
        })

def fetch_job_description(link):
    """Try to scrape job summary or meta description."""
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(link, headers=headers, timeout=8)
        if res.status_code != 200:
            return None
        soup = BeautifulSoup(res.text, "html.parser")
        desc = soup.find("meta", attrs={"name": "description"})
        if desc and desc.get("content"):
            return desc["content"].strip()
        paragraphs = soup.find_all("p")
        if paragraphs:
            return " ".join(p.text.strip() for p in paragraphs[:2])
    except Exception:
        pass
    return None

def call_openai_summary(prompt):
    """Generate concise text using OpenAI."""
    try:
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.6
        )
        return completion.choices[0].message.content.strip()
    except Exception as e:
        print(f"OpenAI error: {e}")
        return None

def extract_company(title):
    """Extract possible company name from job title."""
    parts = title.split(" at ")
    if len(parts) > 1:
        return parts[-1].strip()
    return None

def post_to_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown", "disable_web_page_preview": True}
    r = requests.post(url, data=data)
    return r.status_code == 200

# ====== MAIN LOGIC ======
def main():
    posted = load_posted()
    new_posted = set(posted)

    for feed_url in FEEDS:
        print(f"Fetching feed: {feed_url}")
        feed = feedparser.parse(feed_url)

        for entry in feed.entries:
            link = entry.get("link", "")
            title = entry.get("title", "").strip()
            summary = entry.get("summary", "").strip() if "summary" in entry else ""
            company = entry.get("author", "") or extract_company(title)
            lower_title = title.lower()

            if link in posted:
                continue

            # Filter by keywords
            if not any(k in lower_title for k in KEYWORDS):
                continue

            # Try scraping for better summary
            if not summary:
                scraped = fetch_job_description(link)
                if scraped:
                    summary = scraped

            # AI enrichment if still missing
            if not summary or not company:
                ai_prompt = f"""
You are helping summarize Web3 job posts.
Title: {title}
Company: {company or 'Unknown'}
Link: {link}

If company is missing, infer it if possible. Write a 1-line human summary about what the company is hiring for.
"""
                ai_result = call_openai_summary(ai_prompt)
                if ai_result:
                    summary = ai_result
                    if not company:
                        company_guess = extract_company(ai_result)
                        if company_guess:
                            company = company_guess

            # If still missing key fields, log and skip posting
            if not company or not summary:
                log_incomplete({"title": title, "link": link, "company": company, "summary": summary})
                continue

            # Generate 2 extra hashtags
            tag_prompt = f"Suggest two short, relevant hashtags for this job: {title}, {summary}. Only return hashtags, no explanations."
            tags = call_openai_summary(tag_prompt) or "#Hiring #Blockchain"

            # Build Telegram message
            message = (
                f"*XCROO Job Update*\n\n"
                f"*{company}* is hiring [{title}]({link})\n\n"
                f"*About:* {summary}\n\n"
                f"#XCROO #OnChainTalent #Web3Jobs {tags}"
            )

            if post_to_telegram(message):
                print(f"✅ Posted: {title}")
                new_posted.add(link)
            else:
                print(f"⚠️ Failed to post: {title}")

    save_posted(new_posted)

if __name__ == "__main__":
    main()

