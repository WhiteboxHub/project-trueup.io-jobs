#!/usr/bin/env python3
"""
TrueUp Step 3: Ingest to API.

Cleans TrueUp job postings and sends them to the candidate portal backend.
Reuses the battle-tested robust cleaning from the hiring.cafe scripts.
"""

import json
import os
import sys
import requests
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT))

from core.logger import logger
from core.auth_service import auth_service

import urllib.parse
import re

def _extract_company_from_url(url: str) -> str:
    """Fallback utility to guess company name from an ATS url slug."""
    if not url: return ""
    m = re.search(r'(?:jobs\.lever\.co/|boards\.greenhouse\.io/|jobs\.ashbyhq\.com/jobs/)([\w-]+)', url)
    if m: return m.group(1).replace('-', ' ').title()
    try:
        parsed = urllib.parse.urlparse(url)
        path = [p for p in parsed.path.split('/') if p and p not in ("jobs", "careers", "apply")]
        return path[0].replace('-', ' ').title() if path else parsed.netloc.split('.')[0].title()
    except Exception:
        return ""

def _is_junk_company(name: str) -> bool:
    if not name: return True
    junk = ['jobs', 'careers', 'apply', 'career', 'unknown', 'lever', 'greenhouse', 'ashby']
    return name.lower() in junk


def _resolve_trueup_company(job: dict) -> str:
    """
    Since TrueUp card extraction currently only yields title and URL,
    the absolute best way to get the company name is parsing the ATS URL slug!
    (e.g., jobs.lever.co/stripe -> Stripe)
    """
    ats_url = job.get('ats_url') or ''
    url_company = _extract_company_from_url(ats_url)
    if url_company and not _is_junk_company(url_company):
        return url_company
    
    # Fallback to the title's content (often "Title at Company")
    title = job.get('title', '')
    if ' at ' in title:
        candidate = title.split(' at ')[-1].strip()
        if not _is_junk_company(candidate):
            return candidate

    return "Unknown Company"


def ingest_to_api(json_path):
    if not os.path.exists(json_path):
        logger.error(f"File not found: {json_path}")
        return

    token = auth_service.get_access_token()
    if not token:
        logger.error("Failed to obtain authentication token. Check .env AUTH settings.")
        return

    api_base_url = auth_service.auth_url.replace('/login', '').replace('/api/login', '')
    if '/api' not in api_base_url:
        api_base_url += '/api'
    positions_url = f"{api_base_url}/positions/bulk"

    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    processed_count = 0
    batch_data = []

    try:
        by_ats = data.get('by_ats', {})
        for platform, jobs in by_ats.items():
            logger.info(f"Processing {len(jobs)} jobs for platform: {platform}")

            for job in jobs:
                job_id   = job.get('job_id')
                ats_url  = job.get('ats_url')
                
                title = (job.get('title') or 'Unknown Title').split(' at ')[0].strip()[:255]
                company_name = _resolve_trueup_company(job)
                
                # TrueUp specific tagging
                keyword = job.get('source_keyword', '')

                job_listing = {
                    "title":           title.lower() if title else title,
                    "company_name":    company_name.lower() if company_name else company_name,
                    # We leave locations blank to be filled by the portal or manual review later,
                    # since TrueUp HTML parsing didn't extract location perfectly yet.
                    "location":        None,
                    "city":            None,
                    "state":           None,
                    "country":         None,
                    "position_type":   "full_time", 
                    "employment_mode": "onsite", 
                    "source":          "trueup.io",
                    "source_uid":      job_id,
                    "job_url":         ats_url or job.get('job_posting_url'),
                    "description":     f"Keyword match: {keyword}" if keyword else None,
                    "status":          "open",
                }
                batch_data.append(job_listing)

                if len(batch_data) >= 50:
                    _send_batch(positions_url, token, batch_data)
                    processed_count += len(batch_data)
                    batch_data = []

        if batch_data:
            _send_batch(positions_url, token, batch_data)
            processed_count += len(batch_data)

    except Exception as e:
        logger.error(f"Fatal error during ingestion: {e}")

    logger.info(f"Finished. Total TrueUp jobs sent to API: {processed_count}")


def _send_batch(url, token, batch):
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    try:
        response = requests.post(url, json={"positions": batch}, headers=headers, timeout=30)
        response.raise_for_status()
        res = response.json()
        logger.info(
            f"Batch success: {res.get('inserted', 0)} inserted, "
            f"{res.get('skipped', 0)} duplicates"
        )
    except requests.exceptions.HTTPError as e:
        error_details = ""
        try:
            error_details = e.response.text
        except:
            pass
        logger.error(f"Failed to send batch to API: {e} | Details: {error_details}")
    except Exception as e:
        logger.error(f"Failed to send batch to API: {e}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Ingest grouped TrueUp data into the website API.")
    parser.add_argument(
        "--input",
        help="Path to the by_ats JSON file",
        default=str(ROOT / "trueup_by_ats.json"),
    )
    args = parser.parse_args()
    
    # Correct relative paths if run directly in scripts folder
    if not os.path.exists(args.input) and os.path.exists(os.path.join("..", args.input)):
        args.input = os.path.join("..", args.input)

    ingest_to_api(args.input)
