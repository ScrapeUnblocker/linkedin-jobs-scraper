"""Fetch full job postings and print the ones that publish a pay range, highest first.

`details=True` fetches each posting for its description, seniority level,
employment type, industries, applicant count and employer-provided pay range.
That is one extra request per job, so keep `limit` small while exploring.

Run:
    export SCRAPEUNBLOCKER_KEY=your_key_here
    python examples/salary_report.py
"""

from linkedin_jobs import LinkedInJobsScraper

scraper = LinkedInJobsScraper()
jobs = scraper.search(
    "software engineer",
    "New York, NY",
    posted_within="week",
    limit=10,
    details=True,
)

with_pay = sorted(
    (j for j in jobs if j.salary_max is not None),
    key=lambda j: j.salary_max,
    reverse=True,
)

print(f"{len(with_pay)} of {len(jobs)} postings list a pay range\n")
for job in with_pay:
    print(f"{job.salary:<34} {job.title} @ {job.company}")
    print(
        f"{'':<34} {job.seniority_level or '-'} | {job.employment_type or '-'} | "
        f"{job.applicants or '-'}"
    )
