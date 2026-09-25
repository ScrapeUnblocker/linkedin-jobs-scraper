from __future__ import annotations

import json

import pytest

from linkedin_jobs import Job, cli


def test_parser_defaults():
    args = cli.build_parser().parse_args(["python developer"])
    assert args.keywords == "python developer"
    assert args.location is None
    assert args.pages == 1
    assert args.limit is None
    assert args.details is False
    assert args.country == "US"
    assert args.format == "json"


def test_parser_filters():
    args = cli.build_parser().parse_args(
        [
            "data engineer",
            "-l",
            "Berlin",
            "--posted",
            "week",
            "--workplace",
            "remote, hybrid",
            "--job-type",
            "full-time,contract",
            "--experience",
            "mid-senior",
            "--sort",
            "recent",
            "--distance",
            "25",
            "-p",
            "3",
            "-n",
            "40",
            "-d",
            "-c",
            "DE",
        ]
    )
    assert args.location == "Berlin"
    assert args.posted_within == "week"
    assert args.workplace == ["remote", "hybrid"]
    assert args.job_types == ["full-time", "contract"]
    assert args.experience == ["mid-senior"]
    assert args.sort == "recent"
    assert args.distance == 25
    assert (args.pages, args.limit, args.details, args.country) == (3, 40, True, "DE")


@pytest.mark.parametrize(
    "argv",
    [
        ["x", "--workplace", "moon"],
        ["x", "--job-type", "full-time,gig"],
        ["x", "--posted", "year"],
        ["x", "--sort", "salary"],
    ],
)
def test_parser_rejects_bad_filters(argv):
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(argv)


def test_main_requires_a_search(capsys):
    with pytest.raises(SystemExit):
        cli.main([])
    assert "give search keywords" in capsys.readouterr().err


def test_main_csv_requires_output(capsys):
    with pytest.raises(SystemExit):
        cli.main(["python", "--format", "csv"])
    assert "--output" in capsys.readouterr().err


class StubScraper:
    last_kwargs: dict = {}

    def search(self, keywords=None, location=None, **kwargs):
        StubScraper.last_kwargs = {"keywords": keywords, "location": location, **kwargs}
        return [Job(job_id="42", title="Python Developer", company="Acme Robotics")]


def test_main_json_to_stdout(monkeypatch, capsys):
    monkeypatch.setattr(cli, "LinkedInJobsScraper", StubScraper)
    assert cli.main(["python", "-l", "Texas", "--workplace", "remote", "-n", "5"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out[0]["job_id"] == "42"
    kw = StubScraper.last_kwargs
    assert kw["keywords"] == "python" and kw["location"] == "Texas"
    assert kw["workplace"] == ["remote"] and kw["limit"] == 5
    assert kw["proxy_country"] == "US"


def test_main_csv_to_file(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "LinkedInJobsScraper", StubScraper)
    path = tmp_path / "jobs.csv"
    url = "https://www.linkedin.com/jobs/search?keywords=x"
    assert cli.main(["--url", url, "-f", "csv", "-o", str(path)]) == 0
    assert "Wrote 1 jobs" in capsys.readouterr().err
    assert path.read_text(encoding="utf-8").splitlines()[0].startswith("job_id,title,company")
    assert StubScraper.last_kwargs["search_url"].endswith("keywords=x")
