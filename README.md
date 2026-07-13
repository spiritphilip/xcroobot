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
3. Up to `MAX_PER_RUN` items are selected, jobs-weighted, then **bundled into
   digest posts** — `BATCH_SIZE` items per message, one message per category
   (e.g. "💼 Job Openings (5)" listing 5 roles, each linking to its application).
   Hashtags on each post are derived from the roles/skills actually in it.
4. The batch posts are dripped across `WINDOW_MINUTES` so the channel isn't flooded.
5. The GitHub Action **commits `posted.txt` back to the repo**, so the dedup memory
   persists across runs (and the regular commits keep the scheduled workflow alive —
   GitHub disables schedules after 60 days of no commits).

## Tuning

Edit the knobs at the top of `main.py` (or override via env / workflow inputs):

- `MAX_PER_RUN` — total items per run (default 100)
- `BATCH_SIZE` — items bundled into one digest post (default 5)
- `CATEGORY_CAP` — per-category cap per run (jobs-weighted: job 60, others 8–12)
- `WINDOW_MINUTES` — spread the batch posts across this many minutes (default 50)
- `ENTRIES_PER_SOURCE` — how many recent items to consider per source (default 30)
- `SOURCES` — add/remove feeds. Types: `rss`, `gnews`, `devpost`, `dorahacks`.
  Add `"strict": True` to tech-filter a broad feed; add `"must": [...]` to require a
  keyword in the title.

## Secrets (GitHub → Settings → Secrets → Actions)

| Secret | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Bot token from @BotFather |
| `TELEGRAM_CHAT_ID`   | Channel ID (e.g. `@yourchannel` or `-100...`) — bot must be an admin |
| `GEMINI_API_KEY`     | Google AI Studio key — powers the one-line AI hook (optional) |
| `UPLOAD_POST_API_KEY`| upload-post.com API key — powers X/Twitter cross-post (optional) |

## X / Twitter cross-post (optional)

Posts a small, **jobs-first** slice to a dedicated X account via
[upload-post.com](https://upload-post.com) (which absorbs X's per-post fee — the
direct X API charges $0.20 per link-post in 2026). X throttles automation to
~20 posts/24h, so the bot caps low.

**To activate:**
1. Have an active upload-post plan (Basic $16/mo covers 5 profiles, unlimited posts).
2. In the upload-post dashboard, create a profile named **`xcroo`** and connect
   your dedicated XCROO X account to it. (To use a different profile name, set the
   `UPLOAD_POST_USER` env in the workflow.)
3. Ensure the `UPLOAD_POST_API_KEY` secret is set.

Tuning (workflow env): `X_DAILY_CAP` (default 15), `X_PER_RUN` (default 1 → one
tweet per hourly run). Dedup is tracked separately in `posted_x.txt`.

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
