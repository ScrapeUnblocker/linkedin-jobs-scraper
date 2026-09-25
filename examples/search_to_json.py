"""Search LinkedIn for Python developer jobs posted this week and save them as JSON.

Run:
    export SCRAPEUNBLOCKER_KEY=your_key_here
    python examples/search_to_json.py
"""

from linkedin_jobs import LinkedInJobsScraper, to_json

scraper = LinkedInJobsScraper()
jobs = scraper.search(
    "python developer",
    "United States",
    posted_within="week",
    sort="recent",
    pages=2,
)

with open("python_jobs.json", "w", encoding="utf-8") as fh:
    fh.write(to_json(jobs))

print(f"Saved {len(jobs)} jobs to python_jobs.json")
for job in jobs[:5]:
    print(f"- {job.title} @ {job.company} ({job.location}) - {job.posted_ago}")
