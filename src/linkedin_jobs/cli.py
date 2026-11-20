"""Command-line interface for linkedin-jobs-scraper.

Examples:
    linkedin-jobs "python developer" -l "United States" --limit 20 --pretty
    linkedin-jobs "data engineer" -l "United States" --workplace remote --posted week
    linkedin-jobs "product manager" -l "London" --experience mid-senior,director --details
    linkedin-jobs --url "https://www.linkedin.com/jobs/search?keywords=nurse&location=Texas"
    linkedin-jobs "devops" -l "Germany" --pages 5 --format csv --output jobs.csv
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Callable, Sequence

from . import __version__
from .scraper import (
    EXPERIENCE,
    JOB_TYPES,
    POSTED_WITHIN,
    SORT,
    WORKPLACE,
    LinkedInJobsScraper,
    to_csv,
    to_json,
)


def comma_list(choices: dict[str, str]) -> Callable[[str], list[str]]:
    """argparse ``type=`` for a comma-separated list restricted to ``choices``."""

    def parse(value: str) -> list[str]:
        items = [v.strip().lower() for v in value.split(",") if v.strip()]
        bad = [v for v in items if v not in choices]
        if bad or not items:
            raise argparse.ArgumentTypeError(
                f"invalid value(s) {', '.join(bad) or repr(value)}; "
                f"choose from {', '.join(sorted(choices))}"
            )
        return items

    return parse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="linkedin-jobs",
        description="Scrape public LinkedIn job listings into clean JSON or CSV via "
        "the ScrapeUnblocker getPageSource API.",
    )
    parser.add_argument(
        "keywords",
        nargs="?",
        default=None,
        help='Search keywords, e.g. "python developer".',
    )
    parser.add_argument("-l", "--location", help='Location, e.g. "United States" or "Berlin".')
    parser.add_argument(
        "--url",
        dest="search_url",
        metavar="URL",
        help="A LinkedIn jobs search URL copied from your browser (overrides the filters).",
    )
    parser.add_argument(
        "--posted",
        dest="posted_within",
        choices=sorted(POSTED_WITHIN),
        help="Only jobs posted within this window.",
    )
    parser.add_argument(
        "--workplace",
        type=comma_list(WORKPLACE),
        metavar="LIST",
        help=f"Comma-separated: {', '.join(WORKPLACE)}.",
    )
    parser.add_argument(
        "--job-type",
        dest="job_types",
        type=comma_list(JOB_TYPES),
        metavar="LIST",
        help=f"Comma-separated: {', '.join(JOB_TYPES)}.",
    )
    parser.add_argument(
        "--experience",
        type=comma_list(EXPERIENCE),
        metavar="LIST",
        help=f"Comma-separated: {', '.join(EXPERIENCE)}.",
    )
    parser.add_argument("--sort", choices=sorted(SORT), help="Order results (default: relevant).")
    parser.add_argument("--distance", type=int, metavar="MILES", help="Radius around --location.")
    parser.add_argument("--geo-id", dest="geo_id", help="LinkedIn geo ID (from a search URL).")
    parser.add_argument(
        "-p",
        "--pages",
        type=int,
        default=1,
        help="Max result pages to collect (10 jobs per page; default: 1).",
    )
    parser.add_argument("-n", "--limit", type=int, default=None, help="Stop after N unique jobs.")
    parser.add_argument(
        "-d",
        "--details",
        action="store_true",
        help="Also fetch each job posting (description, seniority, employment type, "
        "pay range, applicants). One extra request per job.",
    )
    parser.add_argument(
        "-c",
        "--country",
        default="US",
        metavar="ISO",
        help="Proxy country to route through (default: US).",
    )
    parser.add_argument(
        "-f",
        "--format",
        choices=("json", "csv"),
        default="json",
        help="Output format (default: json).",
    )
    parser.add_argument("-o", "--output", metavar="PATH", help="Write to this file, not stdout.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON (indented).")
    parser.add_argument("-v", "--verbose", action="store_true", help="Log progress to stderr.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def _write_output(text: str, output: str | None) -> None:
    if output:
        with open(output, "w", encoding="utf-8") as fh:
            fh.write(text)
    else:
        # Job titles and company names are often non-ASCII; force UTF-8 so
        # printing on a legacy Windows console does not raise.
        try:
            sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass
        print(text)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not (args.keywords or args.location or args.geo_id or args.search_url):
        parser.error("give search keywords, --location, --geo-id or --url")
    if args.format == "csv" and not args.output:
        parser.error("--format csv requires --output PATH")

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    if args.verbose:
        logging.getLogger("linkedin_jobs").setLevel(logging.INFO)

    scraper = LinkedInJobsScraper()
    jobs = scraper.search(
        args.keywords,
        args.location,
        posted_within=args.posted_within,
        workplace=args.workplace,
        job_types=args.job_types,
        experience=args.experience,
        sort=args.sort,
        distance=args.distance,
        geo_id=args.geo_id,
        search_url=args.search_url,
        pages=args.pages,
        limit=args.limit,
        details=args.details,
        proxy_country=args.country,
    )

    if args.format == "csv":
        to_csv(jobs, args.output)
    else:
        _write_output(to_json(jobs, indent=2 if args.pretty else None), args.output)
    if args.output:
        print(f"Wrote {len(jobs)} jobs to {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
