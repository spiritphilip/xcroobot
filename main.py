#!/usr/bin/env python3
"""
XCROO — tech opportunities bot.
Pulls JOBS, HACKATHONS, GRANTS, BOUNTIES and other tech OFFERS from many
sources and posts fresh (never-before-seen) items to a Telegram channel.

Web3-first, broadened to general tech.

Dedup: every item is keyed by a normalized URL and checked against posted.txt.
posted.txt is committed back to the repo by the GitHub Action after each run,
so a link is NEVER posted twice.

Run locally without posting:  python main.py --dry-run
"""

import os
import sys
import time
import html
import json
import re
from urllib.parse import urlparse, urlunparse, quote

import requests
import feedparser

# =========================
# CONFIGURATION
# =========================
DRY_RUN = "--dry-run" in sys.argv or os.getenv("DRY_RUN") == "1"

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

POSTED_FILE = "posted.txt"
MAX_POSTED = 4000        # keep dedup file from growing forever (keeps newest N)
MAX_PER_RUN = 8          # total items to post per run (avoid flooding)
MAX_PER_CATEGORY = 3     # balance so one category can't dominate a run
MAX_PER_SOURCE = 4       # don't let a single source dominate
SLEEP_BETWEEN = 4        # seconds between Telegram sends
ENTRIES_PER_SOURCE = 12  # how many recent items to consider per source

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
}

CATEGORY_EMOJI = {
    "job": "💼", "hackathon": "🏆", "grant": "💰", "bounty": "🎯", "offer": "🚀",
}
CATEGORY_LABEL = {
    "job": "Job Opening", "hackathon": "Hackathon", "grant": "Grant / Funding",
    "bounty": "Bounty", "offer": "Opportunity",
}
CATEGORY_TAGS = {
    "job":       "#XCROO #Jobs #Web3Jobs #TechJobs",
    "hackathon": "#XCROO #Hackathon #BuildWeb3 #Devpost",
    "grant":     "#XCROO #Grants #Funding #Web3Grants",
    "bounty":    "#XCROO #Bounty #BugBounty #EarnCrypto",
    "offer":     "#XCROO #Opportunity #Web3 #Tech",
}

# Extra hashtags derived from the title (deterministic, no API needed)
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

# Tech relevance filter — applied only to broad sources (strict=True).
# Matched with word boundaries so "ai" won't hit "email", "stem" won't hit "ecosystem".
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

# For noisy Google News feeds: the item title MUST contain one of these words,
# so a category query can't drift into unrelated headlines.
GNEWS_MUST = {
    "job":       ["hiring", "hire", "job", "jobs", "role", "vacanc", "recruit", "career"],
    "hackathon": ["hackathon", "buildathon", "hackfest", "hacker house"],
    "grant":     ["grant", "grants", "funding", "fund", "prize", "fellowship",
                  "scholarship", "accelerator"],
    "bounty":    ["bounty", "bounties", "reward", "payout"],
    "offer":     ["fellowship", "accelerator", "airdrop", "incentive", "program",
                  "cohort", "residency", "apply", "application", "grant"],
}

# Opportunity keywords for broad RSS aggregators (OpportunityDesk etc.) so
# they only yield actual programs/grants, not their blog articles.
OPP_KEYWORDS = [
    "grant", "grants", "fund", "funding", "fellowship", "scholarship", "prize",
    "award", "program", "programme", "call for", "competition", "accelerator",
    "bootcamp", "cohort", "residency", "incubator", "challenge", "fully funded",
]

# =========================
# SOURCES
# =========================
# type: rss | gnews | devpost | dorahacks
# strict=True  -> only keep items that mention a tech term (for broad feeds)

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
    {"cat": "job", "type": "gnews", "name": "Google News",     "url": gnews("web3 OR blockchain developer hiring remote")},

    # ---------- HACKATHONS ----------
    {"cat": "hackathon", "type": "devpost",   "name": "Devpost", "pages": 3},
    {"cat": "hackathon", "type": "dorahacks", "name": "DoraHacks","url": "https://dorahacks.io/api/hackathon/?page=1&size=15"},
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
    """Google News titles look like 'Headline - Publisher' — strip the suffix."""
    if publisher and title.endswith(" - " + publisher):
        return title[: -(len(publisher) + 3)].strip()
    return re.sub(r"\s+-\s+[^-]+$", "", title).strip() if " - " in title else title


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
        # Gate: the headline must actually mention the opportunity type.
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
            items.append({"cat": src["cat"], "title": title,
                          "org": "Devpost", "link": link})
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
    emoji = CATEGORY_EMOJI.get(cat, "📣")
    label = CATEGORY_LABEL.get(cat, "Update")
    org = html.escape((item["org"] or "").strip()[:80]) or "—"
    title = html.escape(item["title"].strip()[:180])
    link = item["link"]
    tags = CATEGORY_TAGS.get(cat, "#XCROO")
    extra = extra_hashtags(item["title"])
    tag_line = (tags + " " + extra).strip()
    return (
        f"{emoji} <b>{label}</b>\n\n"
        f"<b>{org}</b>\n"
        f'<a href="{html.escape(link, quote=True)}">{title}</a>\n\n'
        f"{tag_line}"
    )


def post_to_telegram(message, disable_preview=False):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": disable_preview,
    }
    r = requests.post(url, json=payload, timeout=25)
    ok = r.status_code == 200
    print(f"   {'✅' if ok else '❌'} Telegram {r.status_code}: {r.text[:120]}")
    return ok


# =========================
# MAIN
# =========================

def main():
    if not DRY_RUN and (not TELEGRAM_TOKEN or not CHAT_ID):
        print("❌ Missing TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID. Exiting.")
        sys.exit(1)

    posted_list, posted_set = load_posted()
    print(f"📁 Loaded {len(posted_set)} previously-posted links. DRY_RUN={DRY_RUN}")

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
    print(f"\n🆕 {total_fresh} fresh items across {len(by_cat)} categories")

    # 2) Select a balanced batch: round-robin across categories.
    selection = []
    per_cat_count = {c: 0 for c in by_cat}
    per_source_count = {}
    cats = list(by_cat.keys())
    idx = {c: 0 for c in cats}
    while len(selection) < MAX_PER_RUN:
        progressed = False
        for c in cats:
            if len(selection) >= MAX_PER_RUN:
                break
            if per_cat_count[c] >= MAX_PER_CATEGORY:
                continue
            lst = by_cat[c]
            while idx[c] < len(lst):
                it = lst[idx[c]]
                idx[c] += 1
                sc = per_source_count.get(it["org"], 0)
                if sc >= MAX_PER_SOURCE:
                    continue
                selection.append(it)
                per_cat_count[c] += 1
                per_source_count[it["org"]] = sc + 1
                progressed = True
                break
        if not progressed:
            break

    print(f"📦 Selected {len(selection)} to post "
          f"({', '.join(f'{c}:{per_cat_count[c]}' for c in cats if per_cat_count[c])})\n")

    # 3) Post + record.
    newly = []
    for it in selection:
        msg = build_message(it)
        print(f"→ [{it['cat']}] {it['title'][:65]}")
        disable_preview = "news.google.com" in it["link"]
        if DRY_RUN:
            print(msg + "\n" + "-" * 50)
            newly.append(it["key"])
        else:
            if post_to_telegram(msg, disable_preview=disable_preview):
                newly.append(it["key"])
            time.sleep(SLEEP_BETWEEN)

    if newly:
        save_posted(posted_list + newly)
        print(f"\n💾 Recorded {len(newly)} new links (posted.txt now has "
              f"{min(len(posted_list) + len(newly), MAX_POSTED)}).")
    else:
        print("\n😴 Nothing new to post this cycle.")

    print("✅ Cycle complete.")


if __name__ == "__main__":
    main()
