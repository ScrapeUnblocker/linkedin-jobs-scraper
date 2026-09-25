"""linkedin-jobs-scraper - clean LinkedIn job listings via the ScrapeUnblocker API.

Scrape public LinkedIn job search results into clean, typed JSON: job ID,
title, company and company page, location, posting date, benefits / hiring
badge, salary and job URL - and, optionally, the full posting: description,
seniority level, employment type, job function, industries, applicant count
and the employer-provided pay range. Pages are fetched through the
ScrapeUnblocker ``getPageSource`` API, which handles blocking and rate limits,
and parsed locally with BeautifulSoup.

Example:
    >>> from linkedin_jobs import LinkedInJobsScraper
    >>> scraper = LinkedInJobsScraper()                    # reads SCRAPEUNBLOCKER_KEY
    >>> jobs = scraper.search("python developer", "United States",
    ...                       posted_within="week", limit=10)   # doctest: +SKIP
    >>> jobs[0].title, jobs[0].company                     # doctest: +SKIP
    ('Senior Python Engineer', 'Example Corp')
"""

from __future__ import annotations

from .scraper import (
    EXPERIENCE,
    JOB_TYPES,
    POSTED_WITHIN,
    SORT,
    WORKPLACE,
    Job,
    LinkedInJobsScraper,
    LinkedInPageError,
    build_search_url,
    extract_job_id,
    jobs_to_dicts,
    parse_job_page,
    parse_salary,
    parse_search_page,
    search_url_from_linkedin,
    to_csv,
    to_json,
)

__all__ = [
    "LinkedInJobsScraper",
    "Job",
    "LinkedInPageError",
    "build_search_url",
    "search_url_from_linkedin",
    "extract_job_id",
    "parse_search_page",
    "parse_job_page",
    "parse_salary",
    "jobs_to_dicts",
    "to_csv",
    "to_json",
    "POSTED_WITHIN",
    "WORKPLACE",
    "JOB_TYPES",
    "EXPERIENCE",
    "SORT",
]

__version__ = "0.1.0"
