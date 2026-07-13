#!/usr/bin/env python3
"""
XCROO — tech opportunities bot.
Pulls JOBS, HACKATHONS, GRANTS, BOUNTIES and other tech OFFERS from many
sources and posts fresh (never-before-seen) items to a Telegram channel.

Web3-first, broadened to general tech.

Volume + pacing: gathers ALL fresh items each run, balances across categories
(jobs favored), shuffles them into a RANDOM queue, then drips them out spaced
across the run window instead of dumping them all at once.

Dedup: every item is keyed by a normalized URL and checked against posted.txt.
posted.txt is committed back to the repo by the GitHub Action after each run,
so a link is NEVER posted twice.

Optional AI: if GEMINI_API_KEY is set, gemini-2.5-flash adds a short hook line
to each post (fully graceful — the bot works fine without it).

Run locally without posting:  python main.py --dry-run
"""

import os
import sys
import time
import html
import re
import random
from datetime import datetime, timezone
from urllib.parse import urlparse, urlunparse, quote

import requests
import feedparser

# =========================
# CONFIGURATION
# =========================
DRY_RUN = "--dry-run" in sys.argv or os.getenv("DRY_RUN") == "1"

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Optional AI (Gemini) — graceful if missing.
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# Optional X/Twitter cross-post via upload-post.com — graceful if missing.
# Posts a small curated (jobs-first) slice to a DEDICATED X account (a separate
# upload-post profile). X throttles automation to ~20 posts/24h, so we cap low.
UPLOAD_POST_API_KEY = os.getenv("UPLOAD_POST_API_KEY", "").strip()
UPLOAD_POST_USER = os.getenv("UPLOAD_POST_USER", "xcroo")  # upload-post profile name
POSTED_X_FILE = "posted_x.txt"
X_DAILY_CAP = int(os.getenv("X_DAILY_CAP", "15"))          # max tweets per UTC day
X_PER_RUN = int(os.getenv("X_PER_RUN", "1"))               # tweets per hourly run

POSTED_FILE = "posted.txt"
MAX_POSTED = 8000            # keep dedup file from growing forever (keeps newest N)

# ---- Volume + pacing (env-overridable so the workflow can tune per run) ----
MAX_PER_RUN = int(os.getenv("MAX_PER_RUN", "100"))         # total items per run
WINDOW_MINUTES = float(os.getenv("WINDOW_MINUTES", "50"))  # spread posts over this
MIN_GAP = 6                  # min seconds between posts (Telegram-friendly)
MAX_GAP = 120                # max seconds between posts
ENTRIES_PER_SOURCE = int(os.getenv("ENTRIES_PER_SOURCE", "30"))

# Per-category caps per run — jobs get the biggest share (this is a job channel).
# Cap sum (105) is >= MAX_PER_RUN so a full 100 can be filled, jobs-weighted.
CATEGORY_CAP = {"job": 45, "hackathon": 18, "grant": 18, "bounty": 12, "offer": 12}
CATEGORY_ORDER = ["job", "hackathon", "grant", "bounty", "offer"]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
}

# emoji, label, "lead" verb phrase
CATEGORY_META = {
    "job":       ("💼", "Job Update",      "is hiring"),
    "hackathon": ("🏆", "Hackathon Alert", "Build & win"),
    "grant":     ("💰", "Grant & Funding", "Funding is open"),
    "bounty":    ("🎯", "Bounty",          "Earn rewards"),
    "offer":     ("🚀", "Opportunity",     "Now open"),
}
CATEGORY_TAGS = {
    "job":       "#XCROO #Web3Jobs #TechJobs #Hiring #RemoteJobs",
    "hackathon": "#XCROO #Hackathon #BuildWeb3 #Devpost #Hackers",
    "grant":     "#XCROO #Grants #Funding #Web3Grants #BuildersFund",
    "bounty":    "#XCROO #Bounty #BugBounty #EarnCrypto #Web3",
    "offer":     "#XCROO #Opportunity #Web3 #Tech #Fellowship",
}

# Compact X/Twitter templates (280-char budget, link counts as ~23).
X_LEAD = {
    "job": "💼 {org} is hiring:", "hackathon": "🏆 Hackathon:",
    "grant": "💰 Grant:", "bounty": "🎯 Bounty:", "offer": "🚀 Opportunity:",
}
X_TAGS = {
    "job": "#Web3Jobs #XCROO", "hackathon": "#Hackathon #XCROO",
    "grant": "#Grants #XCROO", "bounty": "#Bounty #XCROO", "offer": "#Opportunity #XCROO",
}

# Extra hashtags derived from the title (word-boundary matched).
KEYWORD_TAGS = {
    "solidity": "#Solidity", "rust": "#Rust", "python": "#Python",
    "react": "#React", "frontend": "#Frontend", "backend": "#Backend",
    "fullstack": "#FullStack", "full-stack": "#FullStack", "devops": "#DevOps",
    "smart contract": "#SmartContracts", "defi": "#DeFi", "nft": "#NFT",
    "ethereum": "#Ethereum", "solana": "#Solana", "bitcoin": "#Bitcoin",
    "zk": "#ZK", "ai": "#AI", "machine learning": "#ML", "data": "#Data",
    "design": "#Design", "marketing": "#Marketing", "community": "#Community",
    "security": "#Security", "audit": "#Audit", "blockchain": "#Blockchain",
    "web3": "#Web3", "crypto": "#Crypto",
}

# Tech relevance filter (word boundaries) — applied only to broad sources.
TECH_TERMS = [
    "web3", "crypto", "cryptocurrency", "blockchain", "bitcoin", "ethereum",
    "solana", "defi", "nft", "dao", "token", "smart contract", "developer",
    "developers", "engineer", "engineering", "software", "programming",
    "coding", "coder", "tech", "technology", "startup", "startups", "ai",
    "ml", "machine learning", "data", "cloud", "devops", "cyber",
    "cybersecurity", "hackathon", "open source", "open-source", "saas",
    "fintech", "innovation", "stem", "computer", "digital", "app", "apps",
    "developer tools", "protocol", "on-chain",
]
_TECH_RE = re.compile(
    r"\b(" + "|".join(re.escape(t) for t in TECH_TERMS) + r")\b", re.IGNORECASE
)

# For noisy Google News feeds: the item title MUST contain one of these words.
GNEWS_MUST = {
    "job":       ["hiring", "hire", "job", "jobs", "role", "vacanc", "recruit", "career"],
    "hackathon": ["hackathon", "buildathon", "hackfest", "hacker house"],
    "grant":     ["grant", "grants", "funding", "fund", "prize", "fellowship",
                  "scholarship", "accelerator"],
    "bounty":    ["bounty", "bounties", "reward", "payout"],
    "offer":     ["fellowship", "accelerator", "airdrop", "incentive", "program",
                  "cohort", "residency", "apply", "application", "grant"],
}

# Opportunity keywords for broad RSS aggregators (OpportunityDesk etc.).
OPP_KEYWORDS = [
    "grant", "grants", "fund", "funding", "fellowship", "scholarship", "prize",
    "award", "program", "programme", "call for", "competition", "accelerator",
    "bootcamp", "cohort", "residency", "incubator", "challenge", "fully funded",
]

# =========================
# SOURCES
# =========================
# type: rss | gnews | devpost | dorahacks
# strict=True -> only keep tech items ; must=[...] -> require keyword in title


def gnews(query):
    return f"https://news.google.com/rss/search?q={quote(query)}&hl=en-US&gl=US&ceid=US:en"


SOURCES = [
    # ---------- JOBS ----------
    {"cat": "job", "type": "rss", "name": "Remote3",           "url": "https://www.remote3.co/api/rss"},
    {"cat": "job", "type": "rss", "name": "CryptoCurrencyJobs","url": "https://cryptocurrencyjobs.co/index.xml"},
    {"cat": "job", "type": "rss", "name": "Remotive",          "url": "https://remotive.com/remote-jobs/feed", "strict": True},
    {"cat": "job", "type": "rss", "name": "RemoteOK",          "url": "https://remoteok.com/rss", "strict": True},
    {"cat": "job", "type": "rss", "name": "Himalayas",         "url": "https://himalayas.app/jobs/rss", "strict": True},
    {"cat": "job", "type": "rss", "name": "Jobicy",            "url": "https://jobicy.com/?feed=job_feed", "strict": True},
    {"cat": "job", "type": "rss", "name": "WeWorkRemotely",    "url": "https://weworkremotely.com/categories/remote-programming-jobs.rss"},
    {"cat": "job", "type": "rss", "name": "WeWorkRemotely",    "url": "https://weworkremotely.com/categories/remote-full-stack-programming-jobs.rss"},
    {"cat": "job", "type": "rss", "name": "WeWorkRemotely",    "url": "https://weworkremotely.com/categories/remote-back-end-programming-jobs.rss"},
    {"cat": "job", "type": "rss", "name": "WeWorkRemotely",    "url": "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss"},
    {"cat": "job", "type": "rss", "name": "Jobspresso",        "url": "https://jobspresso.co/?feed=job_feed", "strict": True},
    {"cat": "job", "type": "gnews", "name": "Google News",     "url": gnews("web3 OR blockchain developer hiring remote")},

    # ---------- HACKATHONS ----------
    {"cat": "hackathon", "type": "devpost",   "name": "Devpost", "pages": 4},
    {"cat": "hackathon", "type": "dorahacks", "name": "DoraHacks","url": "https://dorahacks.io/api/hackathon/?page=1&size=20"},
    {"cat": "hackathon", "type": "gnews", "name": "Google News", "url": gnews("crypto OR web3 hackathon register 2026")},
    {"cat": "hackathon", "type": "gnews", "name": "Google News", "url": gnews("ETHGlobal OR blockchain hackathon prize pool")},
    {"cat": "hackathon", "type": "gnews", "name": "Google News", "url": gnews("AI hackathon 2026 registration open")},

    # ---------- GRANTS ----------
    {"cat": "grant", "type": "rss", "name": "OpportunityDesk",     "url": "https://opportunitydesk.org/feed/", "strict": True, "must": OPP_KEYWORDS},
    {"cat": "grant", "type": "rss", "name": "OpportunitiesForYouth","url": "https://www.opportunitiesforyouth.org/feed/", "strict": True, "must": OPP_KEYWORDS},
    {"cat": "grant", "type": "gnews", "name": "Google News", "url": gnews("web3 OR crypto grant program developers apply")},
    {"cat": "grant", "type": "gnews", "name": "Google News", "url": gnews("Gitcoin grants round open")},
    {"cat": "grant", "type": "gnews", "name": "Google News", "url": gnews("open source software grant funding developers")},
    {"cat": "grant", "type": "gnews", "name": "Google News", "url": gnews("AI OR tech startup grant program apply 2026")},

    # ---------- BOUNTIES ----------
    {"cat": "bounty", "type": "gnews", "name": "Google News", "url": gnews("web3 OR crypto bug bounty program launch rewards")},
    {"cat": "bounty", "type": "gnews", "name": "Google News", "url": gnews("smart contract audit bounty Immunefi")},
    {"cat": "bounty", "type": "gnews", "name": "Google News", "url": gnews("Gitcoin bounty developers earn")},

    # ---------- OTHER TECH OFFERS ----------
    {"cat": "offer", "type": "gnews", "name": "Google News", "url": gnews("developer fellowship program apply 2026")},
    {"cat": "offer", "type": "gnews", "name": "Google News", "url": gnews("crypto OR web3 accelerator program applications open")},
    {"cat": "offer", "type": "gnews", "name": "Google News", "url": gnews("testnet incentive OR airdrop program developers")},
]

# =========================
# DEDUP HELPERS
# =========================


def norm_url(url):
    """Normalize a URL so trivial variations map to the same dedup key."""
    try:
        p = urlparse(url.strip())
        host = (p.netloc or "").lower()
        if host.startswith("www."):
            host = host[4:]
        path = p.path.rstrip("/") or "/"
        return urlunparse((p.scheme or "https", host, path, "", "", ""))
    except Exception:
        return url.strip()


def load_posted():
    if not os.path.exists(POSTED_FILE):
        return [], set()
    with open(POSTED_FILE, "r", encoding="utf-8") as f:
        items = [line.strip() for line in f if line.strip()]
    return items, set(items)


def save_posted(items):
    trimmed = items[-MAX_POSTED:]
    with open(POSTED_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(trimmed) + "\n")


# =========================
# CONTENT HELPERS
# =========================


def is_tech_relevant(text):
    return bool(_TECH_RE.search(text or ""))


_KW_PATTERNS = [
    (re.compile(r"\b" + re.escape(kw) + r"\b", re.IGNORECASE), tag)
    for kw, tag in KEYWORD_TAGS.items()
]


def extra_hashtags(title):
    tags = []
    for pat, tag in _KW_PATTERNS:
        if pat.search(title) and tag not in tags:
            tags.append(tag)
        if len(tags) >= 2:
            break
    return " ".join(tags)


def clean_gnews_title(title, publisher):
    if publisher and title.endswith(" - " + publisher):
        return title[: -(len(publisher) + 3)].strip()
    return re.sub(r"\s+-\s+[^-]+$", "", title).strip() if " - " in title else title


def ai_hook(item):
    """Optional short hook via Gemini. Returns '' on any problem."""
    if not GEMINI_API_KEY:
        return ""
    try:
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
               f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}")
        prompt = (
            f"Write ONE short punchy hook (6-11 words) to introduce this "
            f"{item['cat']} update on 'XCROO', a Web3 & tech opportunities "
            f"Telegram channel. Be energetic. No emojis, no hashtags, no quotes, "
            f"no preamble — just the hook.\n"
            f"Title: {item['title']}\nOrg/source: {item['org']}"
        )
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.9,
                "maxOutputTokens": 40,
                "thinkingConfig": {"thinkingBudget": 0},
            },
        }
        r = requests.post(url, json=payload, timeout=15)
        if r.status_code != 200:
            return ""
        text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        hook = text.strip().split("\n")[0]
        hook = hook.replace("*", "").replace("`", "").replace('"', "").strip()
        hook = hook.strip("-–—: ").strip()
        return hook[:90]
    except Exception:
        return ""


# =========================
# SOURCE FETCHERS  -> list of {cat, title, org, link}
# =========================


def fetch_rss(src):
    items = []
    r = requests.get(src["url"], headers=HEADERS, timeout=25)
    d = feedparser.parse(r.content)
    for e in d.entries[:ENTRIES_PER_SOURCE]:
        title = getattr(e, "title", "").strip()
        link = getattr(e, "link", "").strip()
        if not title or not link:
            continue
        org = getattr(e, "author", "") or getattr(e, "publisher", "") or src["name"]
        summary = getattr(e, "summary", "")
        if src.get("strict") and not is_tech_relevant(title + " " + summary):
            continue
        must = src.get("must")
        if must and not any(w in title.lower() for w in must):
            continue
        items.append({"cat": src["cat"], "title": title, "org": org.strip(), "link": link})
    return items


def fetch_gnews(src):
    items = []
    r = requests.get(src["url"], headers=HEADERS, timeout=25)
    d = feedparser.parse(r.content)
    for e in d.entries[:ENTRIES_PER_SOURCE]:
        raw_title = getattr(e, "title", "").strip()
        link = getattr(e, "link", "").strip()
        if not raw_title or not link:
            continue
        publisher = ""
        src_obj = getattr(e, "source", None)
        if src_obj is not None:
            publisher = getattr(src_obj, "title", "") or (src_obj.get("title", "") if hasattr(src_obj, "get") else "")
        title = clean_gnews_title(raw_title, publisher)
        must = GNEWS_MUST.get(src["cat"])
        if must and not any(w in title.lower() for w in must):
            continue
        items.append({"cat": src["cat"], "title": title, "org": publisher or "News", "link": link})
    return items


def fetch_devpost(src):
    items = []
    for pg in range(1, src.get("pages", 1) + 1):
        url = f"https://devpost.com/api/hackathons?status[]=open&page={pg}&order_by=recently-added"
        r = requests.get(url, headers=HEADERS, timeout=25)
        for h in r.json().get("hackathons", []):
            title = (h.get("title") or "").strip()
            link = (h.get("url") or "").strip()
            if not title or not link:
                continue
            items.append({"cat": src["cat"], "title": title, "org": "Devpost", "link": link})
    return items


def fetch_dorahacks(src):
    items = []
    r = requests.get(src["url"], headers=HEADERS, timeout=25)
    for h in r.json().get("results", []):
        title = (h.get("name") or h.get("title") or "").strip()
        slug = h.get("slug") or h.get("id") or h.get("uuid") or ""
        link = h.get("url") or (f"https://dorahacks.io/hackathon/{slug}" if slug else "")
        if not title or not link:
            continue
        items.append({"cat": src["cat"], "title": title, "org": "DoraHacks", "link": link})
    return items


FETCHERS = {
    "rss": fetch_rss, "gnews": fetch_gnews,
    "devpost": fetch_devpost, "dorahacks": fetch_dorahacks,
}


# =========================
# TELEGRAM
# =========================


def build_message(item):
    cat = item["cat"]
    emoji, label, _lead = CATEGORY_META.get(cat, ("📣", "Update", ""))
    org = html.escape((item["org"] or "").strip()[:80])
    title = html.escape(item["title"].strip()[:200])
    link = html.escape(item["link"], quote=True)
    tags = (CATEGORY_TAGS.get(cat, "#XCROO") + " " + extra_hashtags(item["title"])).strip()

    lines = [f"{emoji} <b>XCROO • {label}</b>"]
    hook = item.get("hook")
    if hook:
        lines.append(f"<i>{html.escape(hook)}</i>")
    lines.append("")

    if cat == "job":
        who = f"<b>{org}</b> " if org else ""
        lines.append(f"🏢 {who}is hiring")
        lines.append(f"👉 <a href=\"{link}\">{title}</a>")
    else:
        lines.append(f"👉 <a href=\"{link}\">{title}</a>")
        if org and org.lower() not in ("news", ""):
            lines.append(f"<i>via {org}</i>")

    lines.append("")
    lines.append(tags)
    lines.append("")
    lines.append("⚡ <b>Powered by XCROO</b> — Web3 &amp; Tech Opportunities")
    return "\n".join(lines)


def post_to_telegram(message, disable_preview=True):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": disable_preview,
    }
    r = requests.post(url, json=payload, timeout=25)
    if r.status_code == 429:
        retry = 5
        try:
            retry = int(r.json().get("parameters", {}).get("retry_after", 5))
        except Exception:
            pass
        print(f"   ⏳ Rate limited, waiting {retry + 1}s")
        time.sleep(retry + 1)
        r = requests.post(url, json=payload, timeout=25)
    ok = r.status_code == 200
    print(f"   {'✅' if ok else '❌'} Telegram {r.status_code}: {r.text[:110]}")
    return ok


# =========================
# X / TWITTER (via upload-post.com)
# =========================


def _utc_today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def load_posted_x():
    """Returns (rows, keyset, today_count). Rows are 'YYYY-MM-DD\\tkey'."""
    if not os.path.exists(POSTED_X_FILE):
        return [], set(), 0
    rows, keys, today = [], set(), _utc_today()
    today_count = 0
    with open(POSTED_X_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            dt, _, key = line.partition("\t")
            rows.append(line)
            keys.add(key or dt)
            if dt == today:
                today_count += 1
    return rows, keys, today_count


def save_posted_x(rows):
    with open(POSTED_X_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(rows[-MAX_POSTED:]) + "\n")


def build_x_message(item):
    cat = item["cat"]
    lead = X_LEAD.get(cat, "📣").format(org=(item["org"] or "").strip()[:40])
    tags = X_TAGS.get(cat, "#XCROO")
    link = item["link"]
    LINK_LEN = 23  # X wraps every URL to a 23-char t.co link
    fixed = len(lead) + 1 + 2 + LINK_LEN + 2 + len(tags)  # "lead " \n\n link \n\n tags
    room = max(12, 278 - fixed)
    title = item["title"].strip()
    if len(title) > room:
        title = title[: room - 1].rstrip() + "…"
    return f"{lead} {title}\n\n{link}\n\n{tags}"


def post_to_x(message):
    url = "https://api.upload-post.com/api/upload_text"
    headers = {"Authorization": f"Apikey {UPLOAD_POST_API_KEY}"}
    data = {"user": UPLOAD_POST_USER, "platform[]": "x", "title": message}
    try:
        r = requests.post(url, headers=headers, data=data, timeout=30)
        j = r.json()
        ok = bool(j.get("success")) and bool(j.get("results", {}).get("x", {}).get("success"))
        info = j.get("results", {}).get("x", j)
    except Exception as ex:
        ok, info = False, f"{type(ex).__name__} {str(ex)[:100]}"
    print(f"   {'🐦✅' if ok else '🐦❌'} X: {str(info)[:130]}")
    return ok


def crosspost_to_x(by_cat):
    """Post a small jobs-first slice to the dedicated X account."""
    if not UPLOAD_POST_API_KEY:
        return
    rows, keys, today_count = load_posted_x()
    remaining = min(X_PER_RUN, max(0, X_DAILY_CAP - today_count))
    if remaining <= 0:
        print(f"🐦 X: daily cap reached ({today_count}/{X_DAILY_CAP})\n")
        return
    # Jobs first, then the rest — only items still fresh this run.
    pool = [it for c in CATEGORY_ORDER for it in by_cat.get(c, []) if it["key"] not in keys]
    posted = 0
    for it in pool:
        if posted >= remaining:
            break
        msg = build_x_message(it)
        print(f"🐦 → [{it['cat']}] {it['title'][:55]}")
        if DRY_RUN:
            print("      " + msg.replace("\n", "\n      "))
            posted += 1
            continue
        if post_to_x(msg):
            rows.append(f"{_utc_today()}\t{it['key']}")
            posted += 1
            save_posted_x(rows)
            time.sleep(3)
    print(f"🐦 X: posted {posted} this run ({today_count + posted}/{X_DAILY_CAP} today)\n")


# =========================
# SELECTION
# =========================


def select_batch(by_cat):
    """Round-robin across categories (respecting caps) up to MAX_PER_RUN,
    then shuffle into a random posting order."""
    idx = {c: 0 for c in CATEGORY_ORDER}
    taken = {c: 0 for c in CATEGORY_ORDER}
    chosen = []
    while len(chosen) < MAX_PER_RUN:
        progressed = False
        for c in CATEGORY_ORDER:
            if len(chosen) >= MAX_PER_RUN:
                break
            if taken[c] >= CATEGORY_CAP.get(c, 0):
                continue
            lst = by_cat.get(c, [])
            if idx[c] < len(lst):
                chosen.append(lst[idx[c]])
                idx[c] += 1
                taken[c] += 1
                progressed = True
        if not progressed:
            break
    random.shuffle(chosen)
    return chosen, taken


# =========================
# MAIN
# =========================


def main():
    if not DRY_RUN and (not TELEGRAM_TOKEN or not CHAT_ID):
        print("❌ Missing TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID. Exiting.")
        sys.exit(1)

    posted_list, posted_set = load_posted()
    print(f"📁 Loaded {len(posted_set)} previously-posted links. "
          f"DRY_RUN={DRY_RUN} MAX_PER_RUN={MAX_PER_RUN} WINDOW={WINDOW_MINUTES}m "
          f"AI={'on' if GEMINI_API_KEY else 'off'}")

    # 1) Collect candidates from every source (fault-isolated).
    by_cat = {}
    seen_this_run = set()
    for src in SOURCES:
        try:
            items = FETCHERS[src["type"]](src)
        except Exception as ex:
            print(f"⚠️  Source failed [{src['cat']}/{src.get('name')}]: {type(ex).__name__} {str(ex)[:70]}")
            continue
        fresh = 0
        for it in items:
            key = norm_url(it["link"])
            it["key"] = key
            if key in posted_set or key in seen_this_run:
                continue
            seen_this_run.add(key)
            by_cat.setdefault(it["cat"], []).append(it)
            fresh += 1
        print(f"📡 {src['cat']:9s} {src.get('name'):18s} -> {len(items):3d} items, {fresh} fresh")

    total_fresh = sum(len(v) for v in by_cat.values())
    print(f"\n🆕 {total_fresh} fresh items available across {len(by_cat)} categories")

    # 2) Cross-post a small jobs-first slice to X/Twitter (quick, before the drip).
    crosspost_to_x(by_cat)

    # 3) Select a balanced, shuffled batch for Telegram.
    selection, taken = select_batch(by_cat)
    print(f"📦 Queuing {len(selection)} to post this run "
          f"({', '.join(f'{c}:{taken[c]}' for c in CATEGORY_ORDER if taken.get(c))})")

    # 4) Pace: spread Telegram posts across the run window with randomized gaps.
    n = len(selection)
    base_gap = (WINDOW_MINUTES * 60 / n) if n else 0
    print(f"⏱️  ~{base_gap:.0f}s average gap between posts\n")

    newly = []
    for i, it in enumerate(selection):
        it["hook"] = ai_hook(it) if not DRY_RUN else ""
        msg = build_message(it)
        print(f"→ [{it['cat']}] {it['title'][:60]}")
        if DRY_RUN:
            print(msg + "\n" + "-" * 55)
            newly.append(it["key"])
            continue
        if post_to_telegram(msg):
            newly.append(it["key"])
            save_posted(posted_list + newly)   # persist after each post
        if i < n - 1:
            gap = base_gap * random.uniform(0.6, 1.4)
            gap = max(MIN_GAP, min(MAX_GAP, gap))
            time.sleep(gap)

    if newly and DRY_RUN:
        pass  # don't write posted.txt in dry-run
    elif newly:
        save_posted(posted_list + newly)
        print(f"\n💾 Recorded {len(newly)} new links "
              f"(posted.txt now ~{min(len(posted_list) + len(newly), MAX_POSTED)}).")
    else:
        print("\n😴 Nothing new to post this cycle.")

    print("✅ Cycle complete.")


if __name__ == "__main__":
    main()
