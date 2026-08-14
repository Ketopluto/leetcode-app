# LeetCode Statistics Dashboard

A Flask web app that tracks LeetCode problem-solving stats for a class/cohort of students, with an admin panel for roster management and automated weekly progress reports for the HoD.

**Live app:** https://leetcode-app.vercel.app _(update if the deployment URL changes)_

## Features

- **Leaderboard** — per-student easy/medium/hard/total solved counts, filterable by year and section.
- **Student profiles** — detailed stats, recent submissions, and acceptance rate pulled live from LeetCode.
- **Admin panel** — upload a roster via Excel (`.xlsx`/`.xls`), edit/delete students, view upload history.
- **Weekly reports** — automated summaries of inactive/low-activity students, emailed to the HoD.
- **Resilient stats fetching** — tries multiple third-party LeetCode API mirrors with retries, exponential backoff, and a circuit breaker per source; falls back to last-known DB values if all sources fail.
- **CSV export** of the leaderboard.

## Architecture

```
app/
  main.py          WSGI entry point
  __init__.py      Flask app factory, extensions (DB, cache, CSRF, rate limiter)
  routes.py        All HTTP routes
  models.py        SQLAlchemy models (Student, StudentStats, WeeklyReport, ...)
  leetcode_api.py  Multi-source LeetCode stats fetcher with circuit breaker
  reports.py       Weekly report generation logic
  email_service.py SMTP email sending
  scheduler.py     APScheduler background jobs (non-serverless hosting only)
  config.py        Environment-driven configuration
  logger.py        Centralized logging
  templates/       Server-rendered HTML (no frontend build step)
  static/          CSS/JS assets
```

Stats are cached in-memory (short TTL) and persisted to the database, so pages stay fast even when the upstream LeetCode API mirrors are slow or down.

## Local Setup

Requires Python 3.11+.

```bash
git clone https://github.com/Ketopluto/leetcode-app.git
cd leetcode-app

python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate

pip install -r requirements-dev.txt   # includes runtime deps + pytest
```

Copy `.env.example` to `.env` and fill in at least `SECRET_KEY` and `HOD_PASSWORD` (see the file for how to generate a key). With `FLASK_ENV=development` set, the app will auto-generate throwaway values for local runs if you skip this — but it'll print the generated admin password to the console, so set your own if you want repeatable logins.

```bash
flask --app app.main run --debug
```

App runs at http://127.0.0.1:5000/.

## Running Tests

```bash
pytest
```

## Deployment

**Primary: Vercel** (serverless, config in `vercel.json`). Because Vercel is serverless, the in-process scheduler (`app/scheduler.py`) does not run there — instead, an external cron service (e.g. [cron-job.org](https://cron-job.org)) should call:

- `GET/POST /api/cron/refresh-stats?secret=<CRON_SECRET>` — refreshes a batch of students' stats (designed to run every couple of minutes, batched to fit serverless time limits).
- `GET/POST /api/cron/weekly-reports?secret=<CRON_SECRET>` — generates and emails the weekly report (run once a week).

Set `CRON_SECRET` in the Vercel project's environment variables and use the same value in the cron service URL.

**Alternative: Render** (traditional long-running server, config in `render.yaml`). On Render, `app/scheduler.py` runs in-process via APScheduler, so the cron endpoints above aren't needed — stats refresh and weekly reports happen automatically.

Either way, set the required environment variables (see `.env.example`) in the platform's dashboard — the app will refuse to start in production without `SECRET_KEY` and `HOD_PASSWORD` set.

## Key API Endpoints

| Route | Method | Auth | Purpose |
|---|---|---|---|
| `/` | GET | — | Leaderboard |
| `/student/<register_number>` | GET | — | Student profile |
| `/api/stats` | GET | — | JSON leaderboard data |
| `/download` | GET | — | CSV export |
| `/health` | GET | — | Health check |
| `/admin` | GET | session | Admin dashboard |
| `/admin/login` | POST | rate-limited | HoD login |
| `/admin/upload` | POST | session | Upload roster Excel |
| `/admin/reports` | GET | session | Weekly reports dashboard |
| `/api/cron/refresh-stats` | GET/POST | `CRON_SECRET` | External cron: refresh stats batch |
| `/api/cron/weekly-reports` | GET/POST | `CRON_SECRET` | External cron: generate + email reports |

## Contributing

Issues and PRs are welcome. Please run `pytest` before submitting a PR.

## License

MIT — see [LICENSE](LICENSE).
