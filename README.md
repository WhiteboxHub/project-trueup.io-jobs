# TrueUp Job Extraction Engine

Scrapes your personalized [TrueUp.io](https://trueup.io) My Jobs feed, groups listings by ATS, and ingests them to your backend API.

## Project structure

```text
Trup_jobs_engine/
├── config/
│   ├── settings.py          # .env (browser, API auth)
│   ├── trueup.json          # date filter (local, gitignored)
│   └── trueup.example.json
├── core/
│   ├── auth_service.py      # API token for Step 3
│   ├── browser.py           # Chrome / undetected-chromedriver
│   ├── human_behavior.py
│   ├── logger.py
│   ├── proxy_manager.py
│   └── safe_actions.py
├── scripts/
│   ├── trueup_step2_combine_by_ats.py
│   └── trueup_step3_ingest_to_api.py
├── strategies/custom/trueup.py
├── run_trueup.py            # Step 1
├── requirements.txt
└── .env
```

## Setup

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

`.env`:

```dotenv
CHROME_USER_DATA_DIR=./chrome_profile
HEADLESS=false
TRUEUP_EMAIL=your@email.com
TRUEUP_PASSWORD=your_password
AUTH_URL=https://api.example.com/api/login
AUTH_USERNAME=...
AUTH_PASSWORD=...
```

Optional `config/trueup.json`:

```json
{ "date_posted": "Past week" }
```

## Pipeline

### Step 1 — Scrape My Jobs

Login → Jobs nav → Past week → click each job link → save ATS URLs.

```bash
python run_trueup.py
```

Output: `output_jobs.json`

### Step 2 — Group by ATS

```bash
python scripts/trueup_step2_combine_by_ats.py
```

Output: `trueup_by_ats.json`

### Step 3 — Ingest to API

```bash
python scripts/trueup_step3_ingest_to_api.py
```

## Troubleshooting

- **OTP:** Run with `HEADLESS=false` and enter the code when prompted (60s wait).
- **Pagination:** Step 1 clicks **Show more** until the button disappears (~245 jobs on a full feed).
- **Profile locations:** US + Bay Area come from your TrueUp profile, not the scraper.

## License

MIT
