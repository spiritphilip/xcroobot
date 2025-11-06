import os
import feedparser
import requests
from bs4 import BeautifulSoup
import openai
import time

# --- Configuration ---
FEEDS = [
    "https://www.remote3.co/api/rss",
    "https://api.cryptojobslist.com/jobs.rss",
    "https://remotive.com/remote-jobs/feed",
    "https://linkedin.com/jobs/search?keywords=&location=Worldwide&geoId=92000000&trk=public_jobs_jobs-search-bar_search-submit"
]

POSTED_FILE = "posted.txt"

# --- Environment Variables (from GitHub Secrets) ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

openai.api_key = OPENAI_API_KEY


# --- Load posted links ---
def load_posted():
    if not os.path.exists(POSTED_FILE):
        return set()
    with open(POSTED_FILE, "r") as f:
        return set(line.strip() for line in f if line.strip())


# --- Save posted links ---
def save_posted(posted):
    with open(POSTED_FILE, "w") as f:
        f.write("\n".join(posted))


# --- Scrape job page for more content ---
def scrape_page(url):
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")

        # Try to find a short meaningful text
        paragraphs = soup.find_all("p")
        text = " ".join(p.get_text().strip() for p in paragraphs[:5])
        return text[:1000] if text else "No detailed description found."
    except Exception:
        return "No detailed description available."


# --- Summarize job using GPT ---
def summarize_with_gpt(title, company, content):
    prompt = f"""
Summarize the job posting below in one short professional paragraph (max 50 words).
Job Title: {title}
Company: {company}
Description: {content}

Then suggest exactly 2 relevant short hashtags (no # sign, just words) fitting the job type or field.
Return as JSON with fields: "summary" and "hashtags".
"""
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
        )
        text = response["choices"][0]["message"]["content"]
        # Extract summary + hashtags manually if not JSON formatted
        summary, hashtags = text, []
        if "{" in text and "}" in text:
            import json
            try:
                parsed = json.loads(text)
                summary = parsed.get("summary", summary)
                hashtags = parsed.get("hashtags", [])
            except Exception:
                pass
        return summary.strip(), hashtags
    except Exception as e:
        print("OpenAI error:", e)
        return "Short job summary unavailable.", []


# --- Send to Telegram ---
def send_to_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": False,
    }
    r = requests.post(url, json=payload)
    if not r.ok:
        print("Telegram error:", r.text)


# --- Format post ---
def format_post(title, link, company, summary, hashtags):
    hashtag_text = " ".join([f"#{tag}" for tag in (['XCROO', 'OnChainTalent', 'Web3Jobs'] + hashtags)])
    msg = f"*XCROO Job Update*\n\n*{company}* is hiring [{title}]({link})\n\n*About:* {summary}\n\n{hashtag_text}"
    return msg


# --- Main loop ---
def main():
    posted = load_posted()
    new_posted = set(posted)

    for feed_url in FEEDS:
        print(f"Fetching {feed_url} ...")
        feed = feedparser.parse(feed_url)
        for entry in feed.entries:
            link = entry.link
            if link in posted:
                continue

            title = entry.title if hasattr(entry, "title") else "Untitled Role"
            company = (
                getattr(entry, "author", None)
                or getattr(entry, "source", None)
                or "Company not specified"
            )

            description = scrape_page(link)
            summary, hashtags = summarize_with_gpt(title, company, description)
            message = format_post(title, link, company, summary, hashtags)
            send_to_telegram(message)
            print(f"Posted: {title}")

            new_posted.add(link)
            time.sleep(3)  # small delay to avoid spam rate-limits

    save_posted(new_posted)
    print("✅ Done!")


if __name__ == "__main__":
    main()


