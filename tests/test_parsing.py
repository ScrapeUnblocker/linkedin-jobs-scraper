from __future__ import annotations

import pytest
from conftest import make_card, make_page

from linkedin_jobs import (
    LinkedInPageError,
    extract_job_id,
    parse_job_page,
    parse_salary,
    parse_search_page,
)


def test_parse_search_card_fields():
    html = make_card(
        "4000000001",
        title="Senior Data Engineer",
        company="Northwind Analytics",
        location="Denver, CO",
        date="2026-09-23",
        ago="1 day ago",
        extra='<div class="job-posting-benefits"><span class="job-posting-benefits__text">'
        "Medical insurance\n  +3 benefits</span></div>"
        '<span class="job-search-card__salary-info">$150,000 - $180,000</span>',
    )
    [job] = parse_search_page(html)
    assert job.job_id == "4000000001"
    assert job.title == "Senior Data Engineer"
    assert job.company == "Northwind Analytics"
    assert job.company_url == "https://www.linkedin.com/company/northwind-analytics"
    assert job.location == "Denver, CO"
    assert job.posted_date == "2026-09-23"
    assert job.posted_ago == "1 day ago"
    assert job.is_new is False
    assert job.benefits == "Medical insurance +3 benefits"
    assert job.salary == "$150,000 - $180,000"
    # tracking query params are stripped from the job URL
    assert job.url == "https://www.linkedin.com/jobs/view/senior-data-engineer-4000000001"
    assert job.logo_url == "https://media.example.com/logo-4000000001.png"
    # detail-only fields stay empty
    assert job.description is None and job.seniority_level is None


def test_parse_search_new_flag_and_missing_optional_fields():
    [job] = parse_search_page(make_card("4000000002", new=True))
    assert job.is_new is True
    assert job.benefits is None
    assert job.salary is None


def test_parse_search_page_dedupes_and_counts():
    jobs = parse_search_page(make_page(["1000001", "1000002", "1000001"]))
    assert [j.job_id for j in jobs] == ["1000001", "1000002"]


def test_parse_search_falls_back_to_url_for_job_id():
    html = make_card("4000000003").replace('data-entity-urn="urn:li:jobPosting:4000000003"', "")
    [job] = parse_search_page(html)
    assert job.job_id == "4000000003"


def test_parse_search_page_empty():
    assert parse_search_page("") == []
    assert parse_search_page("<html><body>Sign in</body></html>") == []


def test_parse_job_page(job_page):
    details = parse_job_page(job_page)
    assert details["title"] == "Python Developer"
    assert details["company"] == "Acme Robotics"
    assert details["company_url"] == "https://www.linkedin.com/company/acme-robotics"
    assert details["location"] == "Austin, TX"
    assert details["posted_ago"] == "4 days ago"
    assert details["applicants"] == "1,204 applicants"
    assert details["applicant_count"] == 1204
    assert details["salary"] == "$70,000.00/yr - $80,000.00/yr"
    assert details["salary_min"] == 70000.0
    assert details["salary_max"] == 80000.0
    assert details["salary_period"] == "year"
    assert details["salary_currency"] == "USD"
    assert details["seniority_level"] == "Mid-Senior level"
    assert details["employment_type"] == "Full-time"
    assert details["job_function"] == "Engineering and Information Technology"
    assert details["industries"] == "Software Development"
    assert details["description"].startswith("About the role\nBuild and ship")
    assert "3+ years of Python" in details["description"]


def test_parse_job_page_fuzzy_applicants_have_no_count(job_page):
    html = job_page.replace("1,204 applicants", "Over 200 applicants")
    details = parse_job_page(html)
    assert details["applicants"] == "Over 200 applicants"
    assert details["applicant_count"] is None


def test_parse_job_page_rejects_non_posting():
    with pytest.raises(LinkedInPageError):
        parse_job_page("<html><body>Join LinkedIn</body></html>")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("$70,000.00/yr - $80,000.00/yr", (70000.0, 80000.0, "year", "USD")),
        ("$45.50/hr", (45.5, 45.5, "hour", "USD")),
        ("CA$90K/yr - CA$110K/yr", (90000.0, 110000.0, "year", "CAD")),
        ("£4,000/mo - £5,000/mo", (4000.0, 5000.0, "month", "GBP")),
        ("€1.2M/yr", (1200000.0, 1200000.0, "year", "EUR")),
        (None, (None, None, None, None)),
    ],
)
def test_parse_salary(text, expected):
    out = parse_salary(text)
    got = (out["salary_min"], out["salary_max"], out["salary_period"], out["salary_currency"])
    assert got == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("4465102901", "4465102901"),
        (4465102901, "4465102901"),
        ("https://www.linkedin.com/jobs/view/4465102901/", "4465102901"),
        (
            "https://www.linkedin.com/jobs/view/software-engineer-at-acme-4465102901?trk=x",
            "4465102901",
        ),
        ("https://www.linkedin.com/jobs/search?currentJobId=4465102901&keywords=x", "4465102901"),
        ("urn:li:jobPosting:4465102901", "4465102901"),
    ],
)
def test_extract_job_id(value, expected):
    assert extract_job_id(value) == expected


def test_extract_job_id_rejects_garbage():
    with pytest.raises(ValueError):
        extract_job_id("https://www.linkedin.com/company/acme")
