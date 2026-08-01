"""Tests for the SLO / error-budget report."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / ".github" / "scripts"))

from slo import evaluate, format_minutes, load_targets, main, parse_percent


def entry(slug="a", uptime="100.00%", **kw):
    base = {
        "slug": slug,
        "name": slug,
        "status": "up",
        "uptime": uptime,
        "uptimeDay": uptime,
        "uptimeWeek": uptime,
        "uptimeMonth": uptime,
        "uptimeYear": uptime,
        "time": 100,
    }
    base.update(kw)
    return base


@pytest.mark.parametrize(
    ("value", "expected"), [("100.00%", 100.0), ("42.54%", 42.54), ("99%", 99.0), ("0.00%", 0.0)]
)
def test_parse_percent(value, expected):
    assert parse_percent(value) == expected


@pytest.mark.parametrize("value", ["", "n/a", None])
def test_parse_percent_rejects_junk(value):
    assert parse_percent(value) is None


@pytest.mark.parametrize(
    ("minutes", "expected"), [(30, "30m"), (90, "1.5h"), (2880, "2.0d"), (-43, "43m")]
)
def test_format_minutes(minutes, expected):
    assert format_minutes(minutes) == expected


def test_meeting_target_has_full_budget():
    (row,) = evaluate([entry(uptime="100.00%")], "month", 99.0, {})
    assert row["met"]
    # 30 days at 99% permits 432 minutes of downtime; none consumed.
    assert row["budget"] == pytest.approx(432.0)
    assert row["consumed"] == pytest.approx(0.0)
    assert row["remaining"] == pytest.approx(432.0)


def test_breaching_target_reports_negative_budget():
    (row,) = evaluate([entry(uptime="98.00%")], "month", 99.0, {})
    assert not row["met"]
    assert row["remaining"] < 0


def test_exactly_on_target_is_met():
    """A boundary that decides whether you get paged — pin it down."""
    (row,) = evaluate([entry(uptime="99.00%")], "month", 99.0, {})
    assert row["met"]
    assert row["remaining"] == pytest.approx(0.0, abs=1e-9)


def test_per_slug_target_overrides_default():
    (row,) = evaluate([entry(slug="critical", uptime="99.50%")], "month", 99.0, {"critical": 99.9})
    assert row["target"] == 99.9
    assert not row["met"]


def test_all_window_has_no_budget():
    """'all' has no fixed length, so an error budget is undefined for it."""
    (row,) = evaluate([entry()], "all", 99.0, {})
    assert row["budget"] is None and row["remaining"] is None


def test_entries_without_data_are_skipped():
    assert list(evaluate([entry(uptimeMonth="")], "month", 99.0, {})) == []


@pytest.mark.parametrize("window", ["day", "week", "month", "year"])
def test_budget_scales_with_window(window):
    (row,) = evaluate([entry(uptime="100.00%")], window, 99.0, {})
    assert row["budget"] > 0


def test_load_targets_defaults_when_absent(tmp_path):
    assert load_targets(tmp_path) == (99.0, {})


def test_load_targets_reads_file(tmp_path):
    (tmp_path / "slo.yml").write_text(yaml.safe_dump({"default": 95.0, "targets": {"a": 99.95}}))
    default, targets = load_targets(tmp_path)
    assert default == 95.0
    assert targets == {"a": 99.95}


def test_repository_slo_file_is_valid():
    """Every target in slo.yml must map to a real monitor."""
    default, targets = load_targets(REPO_ROOT)
    assert 0 <= default <= 100
    config = yaml.safe_load((REPO_ROOT / ".upptimerc.yml").read_text())
    slugs = {s["slug"] for s in config["sites"]}
    unknown = set(targets) - slugs
    assert not unknown, f"slo.yml targets unknown monitors: {unknown}"
    for slug, target in targets.items():
        assert 0 <= target <= 100, f"{slug} target out of range"


def build_summary(tmp_path, uptime="100.00%"):
    (tmp_path / "history").mkdir(parents=True)
    (tmp_path / "history" / "summary.json").write_text(json.dumps([entry(uptime=uptime)]))
    return tmp_path


def test_cli_missing_summary_returns_2(tmp_path):
    assert main(["--root", str(tmp_path)]) == 2


def test_cli_healthy_returns_0(tmp_path):
    assert main(["--root", str(build_summary(tmp_path))]) == 0


def test_cli_breach_only_fails_when_asked(tmp_path):
    root = build_summary(tmp_path, uptime="10.00%")
    assert main(["--root", str(root)]) == 0
    assert main(["--root", str(root), "--fail-on-breach"]) == 1


def test_cli_runs_against_real_repository_data():
    if not (REPO_ROOT / "history" / "summary.json").exists():
        pytest.skip("pipeline has not produced data yet")
    assert main(["--root", str(REPO_ROOT)]) == 0
