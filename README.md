# XCROO — Tech Opportunities Bot

Auto-posts **fresh** tech opportunities to a Telegram channel, every hour, for free
(GitHub Actions). Web3-first, broadened to general tech.

Categories:

| | Category | Sources |
|---|---|---|
| 💼 | **Jobs** | Remote3, CryptoCurrencyJobs, Remotive, RemoteOK, Himalayas, Jobicy, WeWorkRemotely, Google News |
| 🏆 | **Hackathons** | Devpost API, DoraHacks API, Google News |
| 💰 | **Grants / Funding** | OpportunityDesk, OpportunitiesForYouth, Google News (Gitcoin, ecosystem, OSS, AI) |
| 🎯 | **Bounties** | Google News (bug bounties, Immunefi, Gitcoin) |
| 🚀 | **Other offers** | Fellowships, accelerators, airdrops/incentives (Google News) |

## How it works

1. `main.py` pulls recent items from every source in `SOURCES`.
2. Each item is keyed by a **normalized URL** and checked against `posted.txt`.
   Anything already posted is skipped — **no link is ever posted twice.**
3. A balanced batch (max **8/run**, max **3/category**) is posted to Telegram.
4. The GitHub Action **commits `posted.txt` back to the repo**, so the dedup memory
   persists across runs (and the regular commits keep the scheduled workflow alive —
   GitHub disables schedules after 60 days of no commits).

## Tuning

Edit the knobs at the top of `main.py`:

- `MAX_PER_RUN` — total items per run (default 8)
- `MAX_PER_CATEGORY` — cap per category per run (default 3)
- `MAX_PER_SOURCE` — cap per source per run (default 4)
- `ENTRIES_PER_SOURCE` — how many recent items to consider per source (default 12)
- `SOURCES` — add/remove feeds. Types: `rss`, `gnews`, `devpost`, `dorahacks`.
  Add `"strict": True` to tech-filter a broad feed; add `"must": [...]` to require a
  keyword in the title.

## Secrets (GitHub → Settings → Secrets → Actions)

| Secret | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Bot token from @BotFather |
| `TELEGRAM_CHAT_ID`   | Channel ID (e.g. `@yourchannel` or `-100...`) — bot must be an admin |

## Run locally

```bash
pip install -r requirements.txt

# Preview what WOULD be posted, without sending anything:
python main.py --dry-run

# Actually post (needs the two env vars set):
TELEGRAM_BOT_TOKEN=... TELEGRAM_CHAT_ID=... python main.py
```

## Schedule

Runs hourly via `.github/workflows/run-hour.yml`. Trigger manually anytime from the
**Actions** tab → *Run Job Bot* → *Run workflow*.
