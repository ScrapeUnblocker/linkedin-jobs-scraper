from __future__ import annotations

import csv
import json
from urllib.parse import parse_qs, urlsplit

import pytest
from conftest import FakeClient, Outage, Timeout, make_page

from linkedin_jobs import (
    Job,
    LinkedInJobsScraper,
    LinkedInPageError,
    build_search_url,
    search_url_from_linkedin,
    to_csv,
    to_json,
)
from linkedin_jobs.scraper import JOB_POSTING_URL, MAX_START, SEARCH_URL


def ids(start: int, n: int) -> list[str]:
    return [str(5_000_000 + i) for i in range(start, start + n)]


def scraper_for(client: FakeClient, **kw) -> LinkedInJobsScraper:
    kw.setdefault("transient_errors", (Timeout, Outage))
    kw.setdefault("end_of_results_errors", (Timeout,))
    return LinkedInJobsScraper(client=client, sleep=lambda _s: None, **kw)


def query(url: str) -> dict[str, list[str]]:
    return parse_qs(urlsplit(url).query)


# --------------------------------------------------------------------------- #
# URL building
# --------------------------------------------------------------------------- #


def test_build_search_url_with_filters():
    url = build_search_url(
        "python developer",
        "United States",
        posted_within="week",
        workplace=["remote", "hybrid"],
        job_types="full-time",
        experience=["entry", "associate"],
        sort="recent",
        distance=25,
        start=20,
    )
    assert url.startswith(SEARCH_URL + "?")
    q = query(url)
    assert q["keywords"] == ["python developer"]
    assert q["location"] == ["United States"]
    assert q["f_TPR"] == ["r604800"]
    assert q["f_WT"] == ["2,3"]
    assert q["f_JT"] == ["F"]
    assert q["f_E"] == ["2,3"]
    assert q["sortBy"] == ["DD"]
    assert q["distance"] == ["25"]
    assert q["start"] == ["20"]


def test_build_search_url_minimal():
    q = query(build_search_url("nurse"))
    assert q == {"keywords": ["nurse"], "start": ["0"]}


@pytest.mark.parametrize(
    "kwargs",
    [
        {"posted_within": "year"},
        {"workplace": "moon"},
        {"job_types": ["full-time", "gig"]},
        {"experience": "guru"},
        {"sort": "salary"},
    ],
)
def test_build_search_url_rejects_unknown_filters(kwargs):
    with pytest.raises(ValueError):
        build_search_url("x", **kwargs)


def test_search_url_from_linkedin_keeps_filters_drops_tracking():
    browser = (
        "https://www.linkedin.com/jobs/search/?currentJobId=123&f_TPR=r86400&f_WT=2"
        "&geoId=103644278&keywords=data%20engineer&origin=JOB_SEARCH_PAGE&refresh=true&start=50"
    )
    q = query(search_url_from_linkedin(browser, start=10))
    assert q == {
        "f_TPR": ["r86400"],
        "f_WT": ["2"],
        "geoId": ["103644278"],
        "keywords": ["data engineer"],
        "start": ["10"],
    }


def test_search_url_from_linkedin_requires_search_params():
    with pytest.raises(ValueError):
        search_url_from_linkedin("https://www.linkedin.com/feed/")


# --------------------------------------------------------------------------- #
# Search + pagination
# --------------------------------------------------------------------------- #


def test_search_paginates_until_short_page():
    client = FakeClient(
        {
            "start=0": make_page(ids(0, 10)),
            "start=10": make_page(ids(10, 10)),
            "start=20": make_page(ids(20, 4)),  # short page = last page
        }
    )
    jobs = scraper_for(client).search("python", "Texas", pages=10)
    assert len(jobs) == 24
    assert len(client.calls) == 3
    assert all(pc == "US" for _url, pc in client.calls)


def test_search_respects_pages_and_limit():
    client = FakeClient({"start=0": make_page(ids(0, 10)), "start=10": make_page(ids(10, 10))})
    assert len(scraper_for(client).search("python", pages=1)) == 10
    assert len(client.calls) == 1

    client = FakeClient({"start=0": make_page(ids(0, 10)), "start=10": make_page(ids(10, 10))})
    jobs = scraper_for(client).search("python", pages=5, limit=13)
    assert len(jobs) == 13
    assert len(client.calls) == 2


def test_search_dedupes_overlapping_pages_and_stops_when_nothing_new():
    client = FakeClient(
        {
            "start=0": make_page(ids(0, 10)),
            "start=10": make_page(ids(5, 10)),  # 5 repeats, 5 new
            "start=20": make_page(ids(5, 10)),  # nothing new -> stop
            "start=30": make_page(ids(30, 10)),
        }
    )
    jobs = scraper_for(client).search("python", pages=10)
    assert len(jobs) == 15
    assert len({j.job_id for j in jobs}) == 15
    assert len(client.calls) == 3


def test_search_stops_at_linkedin_result_cap():
    client = FakeClient({"start=": make_page(ids(0, 10))})
    # identical pages would stop on "nothing new" - so feed fresh IDs per call
    counter = iter(range(0, 10_000, 10))

    def fresh(url, proxy_country=None):
        client.calls.append((url, proxy_country))
        return make_page(ids(next(counter), 10))

    client.get_page_source = fresh  # type: ignore[method-assign]
    jobs = scraper_for(client).search("python", pages=500)
    assert len(jobs) == MAX_START
    assert len(client.calls) == MAX_START // 10


def test_search_timeout_on_follow_up_page_means_end_of_results():
    client = FakeClient({"start=0": make_page(ids(0, 10)), "start=10": Timeout("read timed out")})
    jobs = scraper_for(client).search("python", pages=5)
    assert len(jobs) == 10
    assert len(client.calls) == 2  # the follow-up timeout is not retried


def test_search_timeout_on_first_page_is_retried_then_raised():
    client = FakeClient({"start=0": Timeout("read timed out")})
    with pytest.raises(Timeout):
        scraper_for(client, retries=2).search("python")
    assert len(client.calls) == 3


def test_search_retries_transient_errors():
    client = FakeClient({"start=0": [Outage("503"), make_page(ids(0, 3))]})
    sleeps: list[float] = []
    scraper = LinkedInJobsScraper(
        client=client,
        transient_errors=(Timeout, Outage),
        end_of_results_errors=(Timeout,),
        backoff=1.5,
        sleep=sleeps.append,
    )
    assert len(scraper.search("python")) == 3
    assert sleeps == [1.5]


def test_search_non_results_first_page_raises():
    client = FakeClient({"start=0": "<html><body>Sign in to see more jobs</body></html>"})
    with pytest.raises(LinkedInPageError):
        scraper_for(client).search("python")


def test_search_requires_something_to_search():
    with pytest.raises(ValueError):
        scraper_for(FakeClient({})).search()


def test_search_with_browser_url():
    client = FakeClient({"keywords=nurse": make_page(ids(0, 2))})
    jobs = scraper_for(client).search(
        search_url="https://www.linkedin.com/jobs/search?keywords=nurse&location=Texas"
    )
    assert len(jobs) == 2
    assert query(client.calls[0][0])["location"] == ["Texas"]


# --------------------------------------------------------------------------- #
# Job details
# --------------------------------------------------------------------------- #


def test_get_job_by_url(job_page):
    client = FakeClient({"jobPosting/4000000001": job_page})
    job = scraper_for(client).get_job(
        "https://www.linkedin.com/jobs/view/python-developer-at-acme-robotics-4000000001?trk=x"
    )
    assert client.calls[0][0] == JOB_POSTING_URL.format(job_id="4000000001")
    assert job.job_id == "4000000001"
    assert job.url == "https://www.linkedin.com/jobs/view/4000000001/"
    assert job.title == "Python Developer"
    assert job.salary_min == 70000.0
    assert job.employment_type == "Full-time"


def test_search_with_details_enriches_and_tolerates_failures(job_page):
    page = make_page(["4000000001", "4000000002"])
    client = FakeClient(
        {
            "start=0": page,
            "jobPosting/4000000001": job_page,
            "jobPosting/4000000002": "<html>Join LinkedIn</html>",  # not a posting
        }
    )
    jobs = scraper_for(client).search("python", details=True)
    good, bad = jobs
    assert good.seniority_level == "Mid-Senior level"
    assert good.applicant_count == 1204
    assert good.description and "Python" in good.description
    # card fields survive, and the card URL is kept over the bare detail URL
    assert good.posted_date == "2026-09-20"
    assert good.url.endswith("-4000000001")
    # the failed posting keeps its search-card data
    assert bad.title == "Python Developer" and bad.description is None


# --------------------------------------------------------------------------- #
# Export
# --------------------------------------------------------------------------- #


def test_to_json_and_csv(tmp_path):
    jobs = [Job(job_id="1", title="Engineer, Backend", company="Zoë & Co", is_new=True)]
    data = json.loads(to_json(jobs))
    assert data[0]["title"] == "Engineer, Backend"
    assert data[0]["company"] == "Zoë & Co"

    path = tmp_path / "jobs.csv"
    to_csv(jobs, str(path))
    with open(path, encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert rows[0]["job_id"] == "1"
    assert rows[0]["title"] == "Engineer, Backend"
    assert list(rows[0])[:3] == ["job_id", "title", "company"]
