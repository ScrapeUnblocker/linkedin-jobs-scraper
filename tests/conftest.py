"""Shared fixtures: offline HTML samples shaped like LinkedIn's public job pages.

The markup mirrors the real LinkedIn guest pages (class names, attributes and
nesting) but every company, job and person in it is fictional.
"""

from __future__ import annotations

import pytest

CARD = """
<li>
 <div class="base-card relative w-full base-card--link base-search-card base-search-card--link
             job-search-card" data-entity-urn="urn:li:jobPosting:{job_id}">
  <a class="base-card__full-link absolute" href="https://www.linkedin.com/jobs/view/{slug}-{job_id}?position=1&amp;pageNum=0&amp;refId=abc&amp;trackingId=xyz">
   <span class="sr-only">{title}</span>
  </a>
  <div class="search-entity-media">
   <img alt="" class="artdeco-entity-image" data-delayed-url="https://media.example.com/logo-{job_id}.png"/>
  </div>
  <div class="base-search-card__info">
   <h3 class="base-search-card__title">
    {title}
   </h3>
   <h4 class="base-search-card__subtitle">
    <a class="hidden-nested-link" href="https://www.linkedin.com/company/{company_slug}?trk=public_jobs">
     {company}
    </a>
   </h4>
   <div class="base-search-card__metadata">
    <span class="job-search-card__location">
     {location}
    </span>
    {extra}
    <time class="{time_class}" datetime="{date}">
     {ago}
    </time>
   </div>
  </div>
 </div>
</li>
"""


def make_card(
    job_id: str,
    title: str = "Python Developer",
    company: str = "Acme Robotics",
    location: str = "Austin, TX",
    date: str = "2026-09-20",
    ago: str = "4 days ago",
    new: bool = False,
    extra: str = "",
) -> str:
    return CARD.format(
        job_id=job_id,
        slug=title.lower().replace(" ", "-"),
        title=title,
        company=company,
        company_slug=company.lower().replace(" ", "-"),
        location=location,
        date=date,
        ago=ago,
        time_class="job-search-card__listdate--new" if new else "job-search-card__listdate",
        extra=extra,
    )


def make_page(ids: list[str]) -> str:
    return "<!DOCTYPE html>" + "".join(make_card(i) for i in ids)


JOB_PAGE = """
<section class="top-card-layout container-lined">
 <div class="top-card-layout__card">
  <a class="topcard__link" href="https://www.linkedin.com/jobs/view/python-developer-at-acme-robotics-4000000001?trk=public_jobs_topcard-title">
   <h2 class="top-card-layout__title topcard__title">
    Python Developer
   </h2>
  </a>
  <h4 class="top-card-layout__second-subline">
   <div class="topcard__flavor-row">
    <span class="topcard__flavor">
     <a class="topcard__org-name-link topcard__flavor--black-link" href="https://www.linkedin.com/company/acme-robotics?trk=public_jobs_topcard-org-name">
      Acme Robotics
     </a>
    </span>
    <span class="topcard__flavor topcard__flavor--bullet">
     Austin, TX
    </span>
   </div>
   <div class="topcard__flavor-row">
    <span class="posted-time-ago__text topcard__flavor--metadata">
     4 days ago
    </span>
    <span class="num-applicants__caption topcard__flavor--metadata topcard__flavor--bullet">
     1,204 applicants
    </span>
   </div>
  </h4>
 </div>
</section>
<section class="core-section-container compensation">
 <div class="compensation__salary-range">
  <h3 class="compensation__heading">Base pay range</h3>
  <div class="salary compensation__salary">
   $70,000.00/yr - $80,000.00/yr
  </div>
 </div>
</section>
<section class="core-section-container description">
 <div class="show-more-less-html__markup show-more-less-html__markup--clamp-after-5">
  <p><strong>About the role</strong></p>
  <p>Build and ship backend services in Python.</p>
  <ul><li>3+ years of Python</li><li>SQL</li></ul>
 </div>
 <ul class="description__job-criteria-list">
  <li class="description__job-criteria-item">
   <h3 class="description__job-criteria-subheader">Seniority level</h3>
   <span class="description__job-criteria-text description__job-criteria-text--criteria">
    Mid-Senior level
   </span>
  </li>
  <li class="description__job-criteria-item">
   <h3 class="description__job-criteria-subheader">Employment type</h3>
   <span class="description__job-criteria-text">Full-time</span>
  </li>
  <li class="description__job-criteria-item">
   <h3 class="description__job-criteria-subheader">Job function</h3>
   <span class="description__job-criteria-text">Engineering and Information Technology</span>
  </li>
  <li class="description__job-criteria-item">
   <h3 class="description__job-criteria-subheader">Industries</h3>
   <span class="description__job-criteria-text">Software Development</span>
  </li>
 </ul>
</section>
"""


class Timeout(Exception):
    """Stand-in for scrapeunblocker.ScrapeTimeoutError."""


class Outage(Exception):
    """Stand-in for scrapeunblocker.UpstreamOutageError."""


class FakeClient:
    """Mimics ``scrapeunblocker.Client.get_page_source``.

    ``responses`` maps a URL substring to an HTML string, an exception
    instance, or a list of those (consumed one per call).
    """

    def __init__(self, responses: dict[str, object]):
        self.responses = {k: (list(v) if isinstance(v, list) else v) for k, v in responses.items()}
        self.calls: list[tuple[str, str | None]] = []

    def get_page_source(self, url: str, proxy_country: str | None = None) -> str:
        self.calls.append((url, proxy_country))
        for needle, value in self.responses.items():
            if needle in url:
                if isinstance(value, list):
                    value = value.pop(0) if len(value) > 1 else value[0]
                if isinstance(value, BaseException):
                    raise value
                return value  # type: ignore[return-value]
        raise AssertionError(f"unexpected URL {url}")


@pytest.fixture
def job_page() -> str:
    return JOB_PAGE
