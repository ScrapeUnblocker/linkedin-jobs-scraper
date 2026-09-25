# linkedin-jobs-scraper

[![CI](https://github.com/ScrapeUnblocker/linkedin-jobs-scraper/actions/workflows/ci.yml/badge.svg)](https://github.com/ScrapeUnblocker/linkedin-jobs-scraper/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

**Scrape public LinkedIn job listings into clean, typed JSON or CSV, with no login, cookies or blocks to deal with.**

Search LinkedIn Jobs by keywords and location, apply the same filters as the
LinkedIn UI (date posted, remote / hybrid / on-site, job type, experience level),
and get back a list of jobs: job ID, title, company and company page, location,
posting date, benefits / hiring badge and job URL. Add `--details` to also pull
each posting's full description, seniority level, employment type, job function,
industries, applicant count and the employer-provided pay range, parsed into
numbers.

> **Powered by [ScrapeUnblocker](https://scrapeunblocker.com/?utm_source=github&utm_medium=integration&utm_campaign=example-repos).**
> Every page is fetched through the [`getPageSource` API](https://docs.scrapeunblocker.com/?utm_source=github&utm_medium=integration&utm_campaign=example-repos),
> which handles LinkedIn's rate limiting and bot checks and returns the page HTML.
> This library only has to parse it.

## Features

- 🔎 **Keyword + location search.** Use any keywords and any place LinkedIn knows
  ("United States", "Berlin", "Texas, United States"), or a LinkedIn `geoId`.
- 🎛️ **LinkedIn's own filters.** Date posted (`24h` / `week` / `month`), workplace
  (`onsite` / `remote` / `hybrid`), job type, experience level, sort by relevance
  or date, and distance.
- 🔗 **Paste a browser URL.** Build a search in the LinkedIn UI, copy the URL and
  pass it with `--url`. All `f_*` filters carry over and tracking parameters are
  dropped.
- 📄 **Full job details (optional).** Get the description, seniority level,
  employment type, job function, industries, applicant count and the base pay
  range, parsed into `salary_min` / `salary_max` / `salary_period` /
  `salary_currency`.
- 📚 **Multi-page collection.** Pages through results 10 at a time and stops by
  itself at the last page or at LinkedIn's roughly 1,000-results-per-search cap.
- ♻️ **Dedupe.** Jobs are de-duplicated by LinkedIn job ID across pages.
- 🧱 **Clean, typed output.** A `Job` dataclass with stable fields, tracking
  parameters stripped from URLs, and export to JSON or CSV in one call.
- 🔁 **Resilient.** Retries with backoff on transient upstream errors. One posting
  that fails to load never sinks the whole run.
- 🖥️ **CLI + library.** Run `linkedin-jobs` from the shell or import it in Python.

## Install

```bash
pip install .
# or, for development:
pip install -e ".[dev]"
```

Set your ScrapeUnblocker API key (grab one from your
[dashboard](https://scrapeunblocker.com/?utm_source=github&utm_medium=integration&utm_campaign=example-repos)):

```bash
cp .env.example .env          # then edit it, or just export the variable:
export SCRAPEUNBLOCKER_KEY=your_key_here
```

## CLI usage

```bash
# 20 Python developer jobs in the US, pretty-printed JSON to stdout
linkedin-jobs "python developer" -l "United States" --limit 20 --pretty

# Remote data engineering jobs posted this week, newest first, 3 pages
linkedin-jobs "data engineer" -l "United States" --workplace remote --posted week \
  --sort recent --pages 3

# Entry-level and associate full-time roles in Berlin, with full job details
linkedin-jobs "software engineer" -l "Berlin, Germany" --experience entry,associate \
  --job-type full-time --details --country DE --limit 10 --pretty

# Any search built in the LinkedIn UI: paste its URL
linkedin-jobs --url "https://www.linkedin.com/jobs/search/?keywords=registered%20nurse&location=Texas&f_TPR=r86400"

# Export to CSV
linkedin-jobs "product manager" -l "London" --pages 5 --format csv --output pm_jobs.csv
```

```
usage: linkedin-jobs [-h] [-l LOCATION] [--url URL]
                     [--posted {24h,month,week}] [--workplace LIST]
                     [--job-type LIST] [--experience LIST]
                     [--sort {recent,relevant}] [--distance MILES]
                     [--geo-id GEO_ID] [-p PAGES] [-n LIMIT] [-d] [-c ISO]
                     [-f {json,csv}] [-o PATH] [--pretty] [-v] [--version]
                     [keywords]
```

| Filter         | Values                                                                              |
| -------------- | ----------------------------------------------------------------------------------- |
| `--posted`     | `24h`, `week`, `month`                                                              |
| `--workplace`  | `onsite`, `remote`, `hybrid` (comma-separated)                                      |
| `--job-type`   | `full-time`, `part-time`, `contract`, `temporary`, `internship`, `volunteer`, `other` |
| `--experience` | `internship`, `entry`, `associate`, `mid-senior`, `director`, `executive`           |
| `--sort`       | `relevant` (LinkedIn default), `recent`                                             |

Each results page is one request (10 jobs). `--details` adds one request per job,
so keep `--limit` small while you explore. `-v` logs progress to stderr.

## Library usage

```python
from linkedin_jobs import LinkedInJobsScraper, to_csv

scraper = LinkedInJobsScraper()  # reads SCRAPEUNBLOCKER_KEY

jobs = scraper.search(
    "data engineer",
    "United States",
    posted_within="week",
    workplace=["remote", "hybrid"],
    experience=["mid-senior"],
    sort="recent",
    pages=3,
)
for job in jobs[:5]:
    print(f"{job.title} @ {job.company} ({job.location}) - {job.posted_ago}")

to_csv(jobs, "data_engineer_jobs.csv")

# Full details for search results (one request per job)...
scraper.enrich(jobs[:5])

# ...or for a single posting, by ID or URL
job = scraper.get_job("https://www.linkedin.com/jobs/view/4453093350/")
print(job.salary_min, job.salary_max, job.salary_period, job.employment_type)
```

The HTML parsers are plain functions (`parse_search_page`, `parse_job_page`,
`parse_salary`), so you can reuse them on pages you fetch some other way.

## Example output

One job from `linkedin-jobs "software engineer" -l "New York, NY" --posted week --details`
(description and logo URL shortened):

```json
[
  {
    "job_id": "4453093350",
    "title": "Software Engineer III (Java)",
    "company": "JPMorganChase",
    "company_url": "https://www.linkedin.com/company/jpmorganchase",
    "location": "New York, NY",
    "posted_date": "2026-09-24",
    "posted_ago": "15 hours ago",
    "is_new": true,
    "benefits": "Actively Hiring",
    "salary": "$137,750.00/yr - $185,000.00/yr",
    "url": "https://www.linkedin.com/jobs/view/software-engineer-iii-java-at-jpmorganchase-4453093350",
    "logo_url": "https://media.licdn.com/dms/image/v2/.../jpmorganchase_logo?...",
    "seniority_level": "Not Applicable",
    "employment_type": "Full-time",
    "job_function": "Engineering and Information Technology",
    "industries": "Financial Services",
    "applicants": "Over 200 applicants",
    "applicant_count": null,
    "salary_min": 137750.0,
    "salary_max": 185000.0,
    "salary_period": "year",
    "salary_currency": "USD",
    "description": "Job Description\nWe have an exciting and rewarding opportunity for you to take your software engineering career to the next level. ..."
  }
]
```

A few notes on the data:

- Without `--details`, the posting-only fields (`seniority_level` through
  `description`) are `null`.
- `applicant_count` is only set when LinkedIn shows an exact number
  ("67 applicants"). Fuzzy captions like "Over 200 applicants" are kept in
  `applicants` as text.
- Salary fields are only filled when the employer publishes a pay range.
- For very narrow searches LinkedIn pads the results with loosely related jobs,
  just like it does in the browser.

## Project layout

```
src/linkedin_jobs/
  __init__.py      package exports + version
  scraper.py       Job model, LinkedInJobsScraper, URL builder, HTML parsers, JSON/CSV export
  cli.py           argparse command-line interface (the `linkedin-jobs` command)
examples/          runnable scripts (search → JSON, remote jobs → CSV, salary report)
tests/             offline unit tests (SDK mocked, fixture HTML; no API credit spent)
```

## Development

```bash
make install       # editable install with dev deps
make lint          # ruff check
make format        # ruff format
make test          # pytest (offline; the SDK is mocked)
make run           # run the search → JSON example (needs SCRAPEUNBLOCKER_KEY)
```

The test suite mocks the ScrapeUnblocker client and parses fixture HTML, so
`make test` runs fully offline and spends no API credits.

## Links

- 🌐 [ScrapeUnblocker](https://scrapeunblocker.com/?utm_source=github&utm_medium=integration&utm_campaign=example-repos)
- 📚 [Documentation](https://docs.scrapeunblocker.com/?utm_source=github&utm_medium=integration&utm_campaign=example-repos)
- 🐍 [Python SDK](https://docs.scrapeunblocker.com/sdks/python?utm_source=github&utm_medium=integration&utm_campaign=example-repos)

## Legal

For research and educational use. This tool reads only the public job listings
LinkedIn shows to logged-out visitors. It does not log in and does not collect
member profiles. Respect LinkedIn's Terms of Service, `robots.txt` and applicable
laws (including data-protection laws) when scraping. This project is not
affiliated with or endorsed by LinkedIn.

## License

MIT, see [LICENSE](LICENSE). Copyright (c) 2026 ScrapeUnblocker.
