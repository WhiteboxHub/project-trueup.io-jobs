# TrueUp Job Extraction Engine 🚀

An automated job scraping and ingestion pipeline designed to extract AI/ML job listings from [TrueUp.io](https://trueup.io), categorize them by their native Applicant Tracking Systems (ATS), and bulk ingest the cleaned data into your backend API.

---

## 📁 Project Structure

```text
trueup-engine/
├── config/
│   ├── settings.py                  # App settings loaded from .env
│   ├── data_loader.py               # JSON config loader
│   ├── secrets_validator.py         # Credential validation
│   └── trueup.json                  # TrueUp search keywords and filters
├── core/
│   ├── auth_service.py              # API authentication (token management)
│   ├── browser.py                   # Chrome browser service (undetected-chromedriver)
│   ├── captcha_handler.py           # CAPTCHA handling utilities
│   ├── human_behavior.py            # Human-like browser behavior simulation
│   ├── logger.py                    # Logging setup
│   ├── proxy_manager.py             # Proxy configuration
│   └── safe_actions.py              # Safe Selenium click/type actions
├── scripts/
│   ├── trueup_step2_combine_by_ats.py  # Step 2: Group extracted jobs by ATS platform
│   └── trueup_step3_ingest_to_api.py   # Step 3: Clean and ingest data to backend API
├── strategies/
│   └── custom/
│       └── trueup.py                # TrueUp scraping strategy (login, search, pagination, link resolution)
├── run_trueup.py                    # Step 1: Launch the TrueUp scraper
├── requirements.txt                 # Python dependencies
├── .env.us_machine                  # Environment variables for configuration
└── README.md
```

---

## ⚙️ Setup

### 1. Clone the repo
```bash
git clone <your-repo-url>
cd trueup-engine
```

### 2. Create virtual environment
```bash
python -m venv venv
venv\Scripts\activate        # Windows
source venv/bin/activate     # Mac/Linux
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables
Copy or modify `.env.us_machine` (or create a new `.env` file):
```dotenv
# Browser
CHROME_USER_DATA_DIR=./chrome_profile
HEADLESS=false

# TrueUp Credentials
TRUEUP_EMAIL=your_trueup_email@example.com
TRUEUP_PASSWORD=your_trueup_password

# Backend API Authentication
AUTH_URL=https://api.whitebox-learning.com/api/login
API_BASE_URL=https://api.whitebox-learning.com/api
AUTH_USERNAME=your_backend_email@example.com
AUTH_PASSWORD=your_backend_password
```

---

## 🔍 Search Configuration

Edit `config/trueup.json` to define your TrueUp search parameters:

```json
{
    "search_keywords": ["aiml", "ml"],
    "date_posted": "3 Days",
    "location": "Remote",
    "role_types": ["Full Time", "Contract"]
}
```

---

## 🚀 Running the Pipeline

The extraction runs in three distinct phases:

### Step 1: Submitting Searches & Scraping URLs
Executes the TrueUp login flow (handles OTP if prompted), applies your configured search filters, and clicks through job cards to resolve the final ATS destination URLs.
```bash
python run_trueup.py
```
**Output:** `output_jobs.json`

### Step 2: Group by ATS Platform
Reads the raw JSON output and categorizes every extracted job by its underlying ATS tracking system (e.g., Workday, Greenhouse, Lever).
```bash
python scripts/trueup_step2_combine_by_ats.py
```
**Output:** `trueup_by_ats.json`

### Step 3: API Ingestion
Batches the grouped ATS data dynamically and pushes it to your candidate portal / backend database.
```bash
python scripts/trueup_step3_ingest_to_api.py
```
*(This uses `trueup_by_ats.json` as the payload source and standardizes company names based on the ATS URLs).*

---

## 🔧 Supported ATS Detection

The engine natively detects the following platforms from resolved redirect URLs:
Workday · Greenhouse · Lever · SmartRecruiters · iCIMS · Taleo · Ashby · Workable · BambooHR · Oracle Cloud · SAP SuccessFactors · Jobvite · Recruitee · Teamtailor · Personio · Rippling · Paylocity · Breezy · Jazz HR · BrassRing · ADP · and more

---

## 🛠️ Troubleshooting

**Scraper stuck on Login / OTP Prompts?**
- Headless mode (`HEADLESS=false`) is recommended on first run so you can manually enter the email verification code sent by TrueUp. Subsequent runs will use the cached session in `chrome_profile/`.

**Backend Returns "422 Validation Error"?**
- For your API to accept this, ensure your backend's `job_listing` database column enum permits the string `'trueup.io'` as a valid source.

**Empty `output_jobs.json`?**
- The parser may not be finding any search results for your chosen combination of keywords/dates in `trueup.json`. Try broadening the search.

---

## 📄 License

MIT