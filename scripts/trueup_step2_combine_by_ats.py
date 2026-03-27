#!/usr/bin/env python3
"""
TrueUp Step 2: Combine enriched jobs (from Step 1) into a single JSON grouped by ATS platform.

Reads `output_jobs.json` (job_id, title, trueup_url, ats_url) and writes
`trueup_by_ats.json` with platforms as keys and flat entries.
"""

import argparse
import json
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import re

ATS_PLATFORM_PATTERNS = [
    (r"lever\.co|jobs\.lever\.", "lever"),
    (r"greenhouse\.io|boards\.greenhouse|jobs\.greenhouse|job-boards\.greenhouse", "greenhouse"),
    (r"sapsf\.com|successfactors\.com", "successfactors"),
    (r"workday\.com|myworkdayjobs\.com|wd\d+\.myworkdayjobs\.com", "workday"),
    (r"adp\.com|workforcenow\.adp\.com", "adp"),
    (r"ashhq\.by|ashhqby", "ashhqby"),
    (r"smartrecruiters\.com", "smartrecruiters"),
    (r"icims\.com", "icims"),
    (r"jobvite\.com", "jobvite"),
    (r"taleo\.net|taleocdn", "taleo"),
    (r"apply\.workable\.com|workable\.com", "workable"),
    (r"bamboohr\.com", "bamboohr"),
    (r"paycom\.com", "paycom"),
    (r"paychex\.com|myapps\.paychex\.com", "paychex"),
    (r"ultipro\.com", "ultipro"),
    (r"linkedin\.com/jobs", "linkedin"),
    (r"indeed\.com", "indeed"),
    (r"ashbyhq\.com", "ashby"),
    (r"recruitee\.com", "recruitee"),
    (r"teamtailor\.com", "teamtailor"),
    (r"personio\.com", "personio"),
    (r"oraclecloud\.com", "oraclecloud"),
    (r"applytojob\.com", "applytojob"),
    (r"brassring\.com", "brassring"),
    (r"rippling\.com", "rippling"),
    (r"paylocity\.com", "paylocity"),
    (r"breezy\.hr", "breezy"),
    (r"jazz\.co", "jazz"),
    (r"pinpointrecruitment\.com", "pinpoint"),
    (r"dover\.com", "dover"),
    (r"phenompeople\.com", "phenom"),
    (r"careers\.google\.com/jobs|careers\.google\.com/intl", "google"),
    (r"jobs\.apple\.com", "apple"),
    (r"microsoft\.com/.*careers", "microsoft"),
    (r"workdayjobs\.com", "workday"),
]

def detect_ats_platform(url: str) -> str | None:
    if not url:
        return None
    url_lower = url.lower()
    for pattern, platform in ATS_PLATFORM_PATTERNS:
        if re.search(pattern, url_lower):
            return platform
    return None

def categorize_jobs_by_ats(jobs: list[dict]) -> dict[str, list[dict]]:
    """Group jobs using the hiring_cafe ATS regex patterns."""
    by_platform = {}
    for j in jobs:
        ats_url = j.get("ats_url")
        platform = detect_ats_platform(ats_url) or "unknown"
        if platform not in by_platform:
            by_platform[platform] = []
        by_platform[platform].append(j)
    return by_platform


def main():
    parser = argparse.ArgumentParser(description="Combine TrueUp jobs into by_ats file")
    parser.add_argument(
        "--input", type=str, default="output_jobs.json",
        help="Input JSON from TrueUp Step 1 (default: output_jobs.json)"
    )
    parser.add_argument(
        "--output", type=str, default="trueup_by_ats.json",
        help="Output by_ats JSON (default: trueup_by_ats.json)"
    )
    args = parser.parse_args()

    # If running from scripts run at root
    if not os.path.exists(args.input) and os.path.exists(os.path.join("..", args.input)):
        args.input = os.path.join("..", args.input)
        args.output = os.path.join("..", args.output)

    if not os.path.isfile(args.input):
        print(f"Error: input file not found: {args.input}", file=sys.stderr)
        return 1

    with open(args.input, "r", encoding="utf-8") as f:
        data = json.load(f)

    jobs = data.get("jobs") if isinstance(data, dict) else data
    if not jobs:
        print("No jobs in input.", file=sys.stderr)
        by_ats = {}
    else:
        by_ats = categorize_jobs_by_ats(jobs)

    # Output format
    by_ats_flat = {}
    for platform, entries in by_ats.items():
        by_ats_flat[platform] = [
            {
                "job_id": e.get("job_id"),
                "title": e.get("title"),
                "job_posting_url": e.get("trueup_url"),
                "ats_url": e.get("ats_url"),
                "source_keyword": e.get("source_keyword"),
                "scraped_at": e.get("scraped_at")
            }
            for e in entries
        ]

    payload = {
        "source": "trueup.io",
        "categorized_by": "ats_platform",
        "platforms": sorted(by_ats_flat.keys()),
        "by_ats": by_ats_flat,
    }

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    print("\n" + "=" * 60)
    print(f"✅ TrueUp Step 2 complete: grouped by ATS written to {args.output}")
    print(f"   Platforms: {', '.join(sorted(by_ats_flat.keys()))}")
    for platform in sorted(by_ats_flat.keys()):
        print(f"   {platform}: {len(by_ats_flat[platform])} jobs")
    print("=" * 60)
    return 0

if __name__ == "__main__":
    sys.exit(main())
