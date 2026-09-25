"""Collect remote, full-time data engineering jobs from a few searches into one CSV.

Results from every search are merged and de-duplicated by LinkedIn job ID.

Run:
    export SCRAPEUNBLOCKER_KEY=your_key_here
    python examples/remote_jobs_to_csv.py
"""

from linkedin_jobs import LinkedInJobsScraper, to_csv

SEARCHES = ["data engineer", "analytics engineer", "machine learning engineer"]

scraper = LinkedInJobsScraper()
seen: set[str] = set()
jobs = []
for keywords in SEARCHES:
    for job in scraper.search(
        keywords,
        "United States",
        workplace="remote",
        job_types="full-time",
        posted_within="month",
        pages=2,
    ):
        if job.job_id not in seen:
            seen.add(job.job_id)
            jobs.append(job)
    print(f"{keywords!r}: {len(jobs)} unique jobs so far")

to_csv(jobs, "remote_data_jobs.csv")
print(f"Wrote {len(jobs)} jobs to remote_data_jobs.csv")
