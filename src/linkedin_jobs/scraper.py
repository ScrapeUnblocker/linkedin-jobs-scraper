"""Core scraping logic for linkedin-jobs-scraper.

LinkedIn serves its public (logged-out) job search as small HTML fragments: a
search endpoint that returns 10 job cards per page, and a job-posting endpoint
that returns the full posting. Both are fetched through the ScrapeUnblocker
``getPageSource`` API, which handles the blocking, rate limiting and retries,
and returns the page HTML. This module turns that HTML into a clean, stable
:class:`Job` shape with BeautifulSoup.

What the two pages give you:

* **search cards** - job ID, title, company + company page, location, posting
  date (ISO) and relative age, a "new" flag, the benefits / hiring badge
  ("Actively Hiring", "Be an early applicant", "Medical insurance +3 benefits"),
  the salary when the card shows one, logo and the job URL.
* **job posting** (``details=True``) - adds the full description, seniority
  level, employment type, job function, industries, the applicant count and the
  employer-provided base pay range (parsed into min / max / period / currency).

Paging uses LinkedIn's ``start`` offset. LinkedIn stops serving public results
at roughly 1,000 per search, and asking for a page past the last result returns
an empty response that surfaces as a timeout - so the pager stops on a short
page, on a page with no new jobs, at the 1,000 cap, and treats a timeout on a
follow-up page as the end of the results.
"""

from __future__ import annotations

import csv
import json
import logging
import re
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict, dataclass, fields
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

# LinkedIn's public (logged-out) job endpoints.
SEARCH_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
JOB_POSTING_URL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"
PUBLIC_JOB_URL = "https://www.linkedin.com/jobs/view/{job_id}/"

# Cards per search page, and the offset past which LinkedIn serves no more
# public results for a search.
PAGE_SIZE = 10
MAX_START = 1000

# Search filters -> LinkedIn query-string values. Multi-select filters are sent
# comma-separated, exactly as the LinkedIn jobs UI does.
POSTED_WITHIN: dict[str, str] = {"24h": "r86400", "week": "r604800", "month": "r2592000"}
WORKPLACE: dict[str, str] = {"onsite": "1", "remote": "2", "hybrid": "3"}
JOB_TYPES: dict[str, str] = {
    "full-time": "F",
    "part-time": "P",
    "contract": "C",
    "temporary": "T",
    "internship": "I",
    "volunteer": "V",
    "other": "O",
}
EXPERIENCE: dict[str, str] = {
    "internship": "1",
    "entry": "2",
    "associate": "3",
    "mid-senior": "4",
    "director": "5",
    "executive": "6",
}
SORT: dict[str, str] = {"relevant": "R", "recent": "DD"}

# Query-string keys carried over when you paste a LinkedIn jobs search URL.
_SEARCH_PARAMS = ("keywords", "location", "geoId", "distance", "sortBy", "f_")

# "Seniority level" etc. on the job posting -> Job attribute.
_CRITERIA: dict[str, str] = {
    "seniority level": "seniority_level",
    "employment type": "employment_type",
    "job function": "job_function",
    "industries": "industries",
}

# Currency prefixes LinkedIn uses in pay ranges. Longest first so "CA$" wins
# over "$".
_CURRENCY_PREFIXES: tuple[tuple[str, str], ...] = (
    ("CA$", "CAD"),
    ("A$", "AUD"),
    ("NZ$", "NZD"),
    ("HK$", "HKD"),
    ("S$", "SGD"),
    ("MX$", "MXN"),
    ("R$", "BRL"),
    ("$", "USD"),
    ("€", "EUR"),
    ("£", "GBP"),
    ("₹", "INR"),
    ("¥", "JPY"),
    ("CHF", "CHF"),
)

_PERIODS: dict[str, str] = {
    "yr": "year",
    "year": "year",
    "mo": "month",
    "month": "month",
    "wk": "week",
    "week": "week",
    "day": "day",
    "hr": "hour",
    "hour": "hour",
}

_JOB_ID_URN = re.compile(r"jobPosting:(\d+)")
_JOB_ID_URL = re.compile(r"(\d{6,})/?$")
_AMOUNT = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*([KkMm])?(?![\w])")
_PERIOD = re.compile(r"/\s*([A-Za-z]+)")
_EXACT_APPLICANTS = re.compile(r"^(\d[\d,]*)\s+applicants?$", re.IGNORECASE)


class LinkedInPageError(RuntimeError):
    """The fetched page is not the LinkedIn page we expected (e.g. a sign-in wall)."""


def _transient_errors() -> tuple[type[BaseException], ...]:
    """Best-effort tuple of ScrapeUnblocker exceptions worth retrying.

    Imported lazily so the package is usable (and unit-testable) even when the
    ``scrapeunblocker`` SDK is not installed.
    """
    try:
        from scrapeunblocker import (  # type: ignore
            BrowserTimeoutError,
            RateLimitError,
            ScrapeTimeoutError,
            ServerError,
            UpstreamOutageError,
        )
        from scrapeunblocker import (
            ConnectionError as SUConnectionError,
        )
    except Exception:  # pragma: no cover - depends on SDK availability
        return ()
    return (
        UpstreamOutageError,
        RateLimitError,
        ScrapeTimeoutError,
        BrowserTimeoutError,
        ServerError,
        SUConnectionError,
    )


def _timeout_errors() -> tuple[type[BaseException], ...]:
    """ScrapeUnblocker timeouts - on a follow-up search page they mean "no more results"."""
    try:
        from scrapeunblocker import BrowserTimeoutError, ScrapeTimeoutError  # type: ignore
    except Exception:  # pragma: no cover - depends on SDK availability
        return ()
    return (ScrapeTimeoutError, BrowserTimeoutError)


@dataclass
class Job:
    """One LinkedIn job posting.

    The first block comes from the search card and is filled for every job.
    The second block is only filled when the posting itself is fetched
    (``details=True`` / :meth:`LinkedInJobsScraper.get_job`).
    """

    job_id: str | None = None
    title: str | None = None
    company: str | None = None
    company_url: str | None = None
    location: str | None = None
    posted_date: str | None = None
    posted_ago: str | None = None
    is_new: bool = False
    benefits: str | None = None
    salary: str | None = None
    url: str | None = None
    logo_url: str | None = None
    # --- job posting details ---
    seniority_level: str | None = None
    employment_type: str | None = None
    job_function: str | None = None
    industries: str | None = None
    applicants: str | None = None
    applicant_count: int | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    salary_period: str | None = None
    salary_currency: str | None = None
    description: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# Column order used for CSV export and dict serialization.
FIELDNAMES: tuple[str, ...] = tuple(f.name for f in fields(Job))


# --------------------------------------------------------------------------- #
# URL helpers
# --------------------------------------------------------------------------- #


def _codes(values: str | Iterable[str] | None, table: dict[str, str], name: str) -> str | None:
    """Map friendly filter names (``"remote"``) to LinkedIn codes (``"2"``), comma-joined."""
    if not values:
        return None
    if isinstance(values, str):
        values = [values]
    out: list[str] = []
    for value in values:
        key = str(value).strip().lower()
        if key not in table:
            raise ValueError(f"unknown {name} {value!r}; choose from {sorted(table)}")
        if table[key] not in out:
            out.append(table[key])
    return ",".join(out)


def build_search_url(
    keywords: str | None = None,
    location: str | None = None,
    *,
    posted_within: str | None = None,
    workplace: str | Iterable[str] | None = None,
    job_types: str | Iterable[str] | None = None,
    experience: str | Iterable[str] | None = None,
    sort: str | None = None,
    distance: int | None = None,
    geo_id: str | int | None = None,
    start: int = 0,
) -> str:
    """Build a public LinkedIn job-search URL for one results page.

    Args:
        keywords: Free-text search, e.g. ``"python developer"``.
        location: Place name as typed in LinkedIn, e.g. ``"Berlin, Germany"``.
        posted_within: ``"24h"``, ``"week"`` or ``"month"``.
        workplace: One or more of ``onsite`` / ``remote`` / ``hybrid``.
        job_types: One or more of :data:`JOB_TYPES`.
        experience: One or more of :data:`EXPERIENCE`.
        sort: ``"relevant"`` (LinkedIn default) or ``"recent"``.
        distance: Radius in miles around ``location``.
        geo_id: LinkedIn geo ID (from a LinkedIn search URL), overrides fuzzy
            location matching.
        start: Result offset (0, 10, 20, ...).
    """
    params: list[tuple[str, str]] = []
    if keywords:
        params.append(("keywords", keywords))
    if location:
        params.append(("location", location))
    if geo_id:
        params.append(("geoId", str(geo_id)))
    if distance is not None:
        params.append(("distance", str(int(distance))))
    if posted_within:
        if posted_within not in POSTED_WITHIN:
            raise ValueError(
                f"unknown posted_within {posted_within!r}; choose from {sorted(POSTED_WITHIN)}"
            )
        params.append(("f_TPR", POSTED_WITHIN[posted_within]))
    for key, values, table, name in (
        ("f_WT", workplace, WORKPLACE, "workplace"),
        ("f_JT", job_types, JOB_TYPES, "job type"),
        ("f_E", experience, EXPERIENCE, "experience level"),
    ):
        codes = _codes(values, table, name)
        if codes:
            params.append((key, codes))
    if sort:
        if sort not in SORT:
            raise ValueError(f"unknown sort {sort!r}; choose from {sorted(SORT)}")
        params.append(("sortBy", SORT[sort]))
    params.append(("start", str(max(0, int(start)))))
    return f"{SEARCH_URL}?{urlencode(params)}"


def search_url_from_linkedin(url: str, *, start: int = 0) -> str:
    """Convert a LinkedIn jobs search URL copied from the browser into a page URL.

    Keeps the search and filter parameters (``keywords``, ``location``,
    ``geoId``, ``distance``, ``sortBy`` and every ``f_*`` filter) and drops the
    tracking ones, so any search you can build in the LinkedIn UI can be scraped
    as-is.
    """
    query = parse_qsl(urlsplit(url).query, keep_blank_values=False)
    params = [(k, v) for k, v in query if k.startswith(_SEARCH_PARAMS) and k != "start"]
    if not params:
        raise ValueError(f"no LinkedIn search parameters found in {url!r}")
    params.append(("start", str(max(0, int(start)))))
    return f"{SEARCH_URL}?{urlencode(params)}"


def extract_job_id(value: str | int) -> str:
    """Return the numeric job ID from an ID, a ``/jobs/view/...`` URL or a ``currentJobId`` URL."""
    text = str(value).strip()
    if text.isdigit():
        return text
    parts = urlsplit(text)
    for key, val in parse_qsl(parts.query):
        if key == "currentJobId" and val.isdigit():
            return val
    match = _JOB_ID_URL.search(parts.path) or _JOB_ID_URN.search(text)
    if not match:
        raise ValueError(f"could not find a LinkedIn job ID in {value!r}")
    return match.group(1)


def _strip_query(url: str | None) -> str | None:
    """Drop the query string and fragment (LinkedIn tracking params) from a URL."""
    if not url:
        return None
    parts = urlsplit(url.strip())
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", "")) or None


# --------------------------------------------------------------------------- #
# HTML parsing
# --------------------------------------------------------------------------- #


def _text(node: Any) -> str | None:
    """Whitespace-normalized text of a node, or ``None`` when missing/empty."""
    if node is None:
        return None
    text = " ".join(node.get_text(" ", strip=True).split())
    return text or None


def parse_search_page(html: str) -> list[Job]:
    """Parse one page of LinkedIn job-search results into :class:`Job` objects."""
    soup = BeautifulSoup(html or "", "html.parser")
    jobs: list[Job] = []
    seen: set[str] = set()
    for card in soup.select("div.base-search-card, a.base-search-card, div.job-search-card"):
        link = card if card.name == "a" else card.select_one("a.base-card__full-link, a[href]")
        url = _strip_query(link.get("href")) if link is not None else None

        job_id = None
        urn = _JOB_ID_URN.search(card.get("data-entity-urn") or "")
        if urn:
            job_id = urn.group(1)
        elif url:
            try:
                job_id = extract_job_id(url)
            except ValueError:
                job_id = None
        if job_id is None or job_id in seen:
            continue
        seen.add(job_id)

        company_link = card.select_one(".base-search-card__subtitle a")
        posted = card.select_one("time")
        logo = card.select_one("img")
        logo_url = None
        if logo is not None:
            logo_url = logo.get("data-delayed-url") or logo.get("src")
            if logo_url and logo_url.startswith("data:"):
                logo_url = None

        jobs.append(
            Job(
                job_id=job_id,
                title=_text(card.select_one(".base-search-card__title")),
                company=_text(card.select_one(".base-search-card__subtitle")),
                company_url=_strip_query(company_link.get("href")) if company_link else None,
                location=_text(card.select_one(".job-search-card__location")),
                posted_date=(posted.get("datetime") or None) if posted is not None else None,
                posted_ago=_text(posted),
                is_new=posted is not None
                and "job-search-card__listdate--new" in (posted.get("class") or []),
                benefits=_text(
                    card.select_one(".job-posting-benefits__text, .result-benefits__text")
                ),
                salary=_text(card.select_one(".job-search-card__salary-info")),
                url=url or PUBLIC_JOB_URL.format(job_id=job_id),
                logo_url=logo_url,
            )
        )
    return jobs


def parse_salary(text: str | None) -> dict[str, Any]:
    """Split a LinkedIn pay range into numbers.

    ``"$70,000.00/yr - $80,000.00/yr"`` ->
    ``{"salary_min": 70000.0, "salary_max": 80000.0, "salary_period": "year",
    "salary_currency": "USD"}``. Unknown parts come back as ``None``.
    """
    out: dict[str, Any] = {
        "salary_min": None,
        "salary_max": None,
        "salary_period": None,
        "salary_currency": None,
    }
    if not text:
        return out
    amounts: list[float] = []
    for number, suffix in _AMOUNT.findall(text):
        value = float(number.replace(",", ""))
        if suffix:
            value *= 1_000 if suffix.lower() == "k" else 1_000_000
        amounts.append(value)
    if amounts:
        out["salary_min"] = min(amounts)
        out["salary_max"] = max(amounts)
    period = _PERIOD.search(text)
    if period:
        out["salary_period"] = _PERIODS.get(period.group(1).lower())
    stripped = text.strip()
    for prefix, code in _CURRENCY_PREFIXES:
        if stripped.startswith(prefix):
            out["salary_currency"] = code
            break
    return out


def parse_job_page(html: str) -> dict[str, Any]:
    """Parse a LinkedIn job posting into a dict of :class:`Job` fields.

    Raises:
        LinkedInPageError: the HTML has no job title, i.e. it is not a posting.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    title = _text(soup.select_one(".top-card-layout__title, .topcard__title"))
    if not title:
        raise LinkedInPageError("no job title found - the page is not a LinkedIn job posting")

    company_link = soup.select_one("a.topcard__org-name-link")
    first_row = soup.select_one(".topcard__flavor-row")
    location = _text(first_row.select_one(".topcard__flavor--bullet")) if first_row else None
    applicants = _text(soup.select_one(".num-applicants__caption, .num-applicants__figure"))
    exact = _EXACT_APPLICANTS.match(applicants or "")
    salary = _text(soup.select_one(".compensation__salary"))

    out: dict[str, Any] = {
        "title": title,
        "company": _text(company_link) or _text(soup.select_one(".topcard__org-name")),
        "company_url": _strip_query(company_link.get("href")) if company_link else None,
        "location": location,
        "posted_ago": _text(soup.select_one(".posted-time-ago__text")),
        "applicants": applicants,
        "applicant_count": int(exact.group(1).replace(",", "")) if exact else None,
        "salary": salary,
    }
    out.update(parse_salary(salary))

    for item in soup.select("li.description__job-criteria-item"):
        label = (_text(item.select_one(".description__job-criteria-subheader")) or "").lower()
        attr = _CRITERIA.get(label)
        if attr:
            out[attr] = _text(item.select_one(".description__job-criteria-text"))

    body = soup.select_one(".show-more-less-html__markup, .description__text")
    if body is not None:
        out["description"] = body.get_text("\n", strip=True) or None
    return out


def merge_details(job: Job, details: dict[str, Any]) -> Job:
    """Fill ``job`` with posting details; non-empty detail values win over card values."""
    for key, value in details.items():
        if value is not None and hasattr(job, key):
            setattr(job, key, value)
    return job


# --------------------------------------------------------------------------- #
# Scraper
# --------------------------------------------------------------------------- #


class LinkedInJobsScraper:
    """Scrape public LinkedIn job listings via ScrapeUnblocker.

    Args:
        api_key: ScrapeUnblocker key. If omitted, the SDK reads
            ``SCRAPEUNBLOCKER_KEY`` from the environment.
        client: A pre-built client (or any object exposing
            ``get_page_source(url, proxy_country=...)``). Mainly for testing.
        retries: Extra attempts on transient upstream errors.
        backoff: Base seconds for linear backoff between retries.
        timeout: Per-request timeout passed to the SDK client.
        transient_errors: Exception classes treated as retryable. Defaults to
            the ScrapeUnblocker transient set.
        end_of_results_errors: Exception classes that, on a follow-up search
            page, mean LinkedIn has no more results. Defaults to the
            ScrapeUnblocker timeout errors.
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        client: Any | None = None,
        retries: int = 2,
        backoff: float = 2.0,
        timeout: float = 90.0,
        transient_errors: Sequence[type[BaseException]] | None = None,
        end_of_results_errors: Sequence[type[BaseException]] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if client is None:
            from scrapeunblocker import Client  # local import: optional dep

            client = Client(api_key=api_key, timeout=timeout)
        self._client = client
        self.retries = max(0, int(retries))
        self.backoff = float(backoff)
        self._transient = (
            tuple(transient_errors) if transient_errors is not None else _transient_errors()
        )
        self._end_errors = (
            tuple(end_of_results_errors) if end_of_results_errors is not None else _timeout_errors()
        )
        self._sleep = sleep

    def _fetch(
        self,
        url: str,
        proxy_country: str | None,
        *,
        no_retry: tuple[type[BaseException], ...] = (),
    ) -> str:
        attempt = 0
        while True:
            try:
                html = self._client.get_page_source(url, proxy_country=proxy_country)
                return html if isinstance(html, str) else str(html or "")
            except self._transient as exc:
                if isinstance(exc, no_retry) or attempt >= self.retries:
                    raise
                attempt += 1
                self._sleep(self.backoff * attempt)

    def search(
        self,
        keywords: str | None = None,
        location: str | None = None,
        *,
        posted_within: str | None = None,
        workplace: str | Iterable[str] | None = None,
        job_types: str | Iterable[str] | None = None,
        experience: str | Iterable[str] | None = None,
        sort: str | None = None,
        distance: int | None = None,
        geo_id: str | int | None = None,
        search_url: str | None = None,
        pages: int = 1,
        limit: int | None = None,
        details: bool = False,
        proxy_country: str | None = "US",
    ) -> list[Job]:
        """Search LinkedIn jobs and return de-duplicated :class:`Job` results.

        Args:
            keywords, location, posted_within, workplace, job_types, experience,
            sort, distance, geo_id: Search filters - see :func:`build_search_url`.
            search_url: A LinkedIn jobs search URL copied from the browser. When
                given, it replaces the filter arguments above.
            pages: Max result pages to collect (10 jobs per page).
            limit: Stop once this many unique jobs are collected.
            details: Also fetch every job posting for the description,
                seniority, employment type, job function, industries, applicant
                count and pay range. Costs one extra request per job.
            proxy_country: ISO-3166 country to route through (default ``"US"``).
        """
        if not (keywords or location or geo_id or search_url):
            raise ValueError("give keywords, a location, a geo_id or a search_url")

        def page_url(start: int) -> str:
            if search_url:
                return search_url_from_linkedin(search_url, start=start)
            return build_search_url(
                keywords,
                location,
                posted_within=posted_within,
                workplace=workplace,
                job_types=job_types,
                experience=experience,
                sort=sort,
                distance=distance,
                geo_id=geo_id,
                start=start,
            )

        seen: set[str] = set()
        jobs: list[Job] = []
        start = 0
        for page in range(max(1, pages)):
            if start >= MAX_START:
                break
            url = page_url(start)
            if page == 0:
                html = self._fetch(url, proxy_country)
            else:
                try:
                    html = self._fetch(url, proxy_country, no_retry=self._end_errors)
                except self._end_errors:
                    log.info("no response at results offset %d - end of results", start)
                    break

            cards = parse_search_page(html)
            if page == 0 and not cards and html.strip():
                raise LinkedInPageError(
                    "no job cards found on the first results page - LinkedIn returned "
                    "something other than a results list (try again, or a different "
                    "proxy_country)"
                )

            fresh = 0
            for job in cards:
                if job.job_id in seen:
                    continue
                seen.add(job.job_id)  # type: ignore[arg-type]
                jobs.append(job)
                fresh += 1
                if limit is not None and len(jobs) >= limit:
                    break
            log.info(
                "page %d: %d cards, %d kept (%d total)", page + 1, len(cards), fresh, len(jobs)
            )
            if limit is not None and len(jobs) >= limit:
                break
            if len(cards) < PAGE_SIZE or fresh == 0:
                break
            start += len(cards)

        if details:
            self.enrich(jobs, proxy_country=proxy_country)
        return jobs

    def get_job(self, job: str | int, *, proxy_country: str | None = "US") -> Job:
        """Fetch one job posting by ID or URL and return it as a :class:`Job`."""
        job_id = extract_job_id(job)
        html = self._fetch(JOB_POSTING_URL.format(job_id=job_id), proxy_country)
        result = Job(job_id=job_id, url=PUBLIC_JOB_URL.format(job_id=job_id))
        return merge_details(result, parse_job_page(html))

    def enrich(self, jobs: Sequence[Job], *, proxy_country: str | None = "US") -> list[Job]:
        """Fill search results with their posting details, in place.

        A posting that cannot be fetched or parsed is logged and left with its
        search-card data, so one bad posting never sinks the whole run.
        """
        for n, job in enumerate(jobs, 1):
            if not job.job_id:
                continue
            log.info("details %d/%d: job %s", n, len(jobs), job.job_id)
            try:
                html = self._fetch(JOB_POSTING_URL.format(job_id=job.job_id), proxy_country)
                merge_details(job, parse_job_page(html))
            except (LinkedInPageError, *self._transient) as exc:
                log.warning("could not fetch details for job %s: %s", job.job_id, exc)
        return list(jobs)


# --------------------------------------------------------------------------- #
# Export
# --------------------------------------------------------------------------- #


def jobs_to_dicts(jobs: Sequence[Job]) -> list[dict[str, Any]]:
    return [j.to_dict() for j in jobs]


def to_json(jobs: Sequence[Job], *, indent: int | None = 2) -> str:
    return json.dumps(jobs_to_dicts(jobs), indent=indent, ensure_ascii=False)


def to_csv(jobs: Sequence[Job], path: str) -> None:
    """Write ``jobs`` to a CSV file at ``path``."""
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(FIELDNAMES))
        writer.writeheader()
        for job in jobs:
            writer.writerow(job.to_dict())
