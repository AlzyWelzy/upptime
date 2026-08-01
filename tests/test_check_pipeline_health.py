"""Tests for the pipeline watchdog.

Includes the exact failure this repository actually hit: every workflow dying at
checkout, so no history was ever written while the status page showed an error.
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / ".github" / "scripts"))

from check_pipeline_health import check, main, parse_timestamp


def build_repo(tmp_path: Path, slugs=("a", "b"), age_hours: float = 0.0, summary: bool = True):
    """Create a miniature repo whose history is `age_hours` old."""
    (tmp_path / "history").mkdir(parents=True)
    (tmp_path / ".upptimerc.yml").write_text(
        yaml.safe_dump(
            {"sites": [{"name": s, "slug": s, "url": f"https://{s}.com"} for s in slugs]}
        )
    )
    stamp = dt.datetime.now(dt.UTC) - dt.timedelta(hours=age_hours)
    for slug in slugs:
        (tmp_path / "history" / f"{slug}.yml").write_text(
            yaml.safe_dump(
                {
                    "url": f"https://{slug}.com",
                    "status": "up",
                    "code": 200,
                    "lastUpdated": stamp.isoformat().replace("+00:00", "Z"),
                }
            )
        )
    if summary:
        (tmp_path / "history" / "summary.json").write_text("[]")
    return tmp_path


def test_fresh_pipeline_is_healthy(tmp_path):
    assert check(build_repo(tmp_path), 24) == []


def test_stale_history_is_flagged(tmp_path):
    problems = check(build_repo(tmp_path, age_hours=48), 24)
    assert len(problems) == 2
    assert all("stale" in p for p in problems)


def test_missing_summary_is_flagged(tmp_path):
    """The exact symptom behind the status page's 'An error occurred'."""
    problems = check(build_repo(tmp_path, summary=False), 24)
    assert any("summary.json is missing" in p for p in problems)


def test_never_ran_pipeline_is_flagged(tmp_path):
    """Today's real failure: workflows died at checkout, so no history exists."""
    (tmp_path / "history").mkdir()
    (tmp_path / ".upptimerc.yml").write_text(
        yaml.safe_dump({"sites": [{"name": "a", "slug": "a", "url": "https://a.com"}]})
    )
    problems = check(tmp_path, 24)
    assert any("summary.json is missing" in p for p in problems)
    assert any("history/a.yml is missing" in p for p in problems)


def test_sites_without_slug_are_skipped(tmp_path):
    repo = build_repo(tmp_path)
    config = yaml.safe_load((repo / ".upptimerc.yml").read_text())
    config["sites"].append({"name": "no slug", "url": "https://x.com"})
    (repo / ".upptimerc.yml").write_text(yaml.safe_dump(config))
    assert check(repo, 24) == []


def test_unreadable_timestamp_is_flagged(tmp_path):
    repo = build_repo(tmp_path, slugs=("a",))
    (repo / "history" / "a.yml").write_text(yaml.safe_dump({"status": "up"}))
    assert any("lastUpdated" in p for p in check(repo, 24))


def test_malformed_history_yaml_is_flagged(tmp_path):
    repo = build_repo(tmp_path, slugs=("a",))
    (repo / "history" / "a.yml").write_text("status: [unclosed\n")
    assert any("not valid YAML" in p for p in check(repo, 24))


def test_missing_config_is_flagged(tmp_path):
    assert any("missing" in p for p in check(tmp_path, 24))


def test_no_sites_is_flagged(tmp_path):
    (tmp_path / ".upptimerc.yml").write_text(yaml.safe_dump({"sites": []}))
    assert any("no sites" in p for p in check(tmp_path, 24))


@pytest.mark.parametrize(
    "value", ["2026-08-01T12:00:00Z", "2026-08-01T12:00:00+00:00", "2026-08-01T12:00:00"]
)
def test_parse_timestamp_accepts_upptime_formats(value):
    parsed = parse_timestamp(value)
    assert parsed is not None and parsed.tzinfo is not None


@pytest.mark.parametrize("value", ["", "not-a-date", None])
def test_parse_timestamp_rejects_junk(value):
    assert parse_timestamp(value) is None


def test_max_age_threshold_is_respected(tmp_path):
    repo = build_repo(tmp_path, age_hours=10)
    assert check(repo, 24) == []
    assert check(repo, 5) != []


def test_cli_exit_codes(tmp_path):
    healthy = build_repo(tmp_path / "ok")
    assert main(["--root", str(healthy)]) == 0
    stale = build_repo(tmp_path / "stale", age_hours=100)
    assert main(["--root", str(stale)]) == 1
