#!/usr/bin/env python3
"""Watchdog for the monitoring pipeline itself.

Upptime tells you when a *service* breaks. Nothing tells you when the *monitor*
breaks — and a monitor that has silently stopped running looks exactly like a
service that is perfectly healthy. This repository has already had a multi-week
outage of that kind: every workflow failed at checkout, no data was written, and
the status page just showed an error.

This checks that the pipeline is actually producing fresh data, and fails the
job (which emails the repository owner) when it is not.

    python3 .github/scripts/check_pipeline_health.py
    python3 .github/scripts/check_pipeline_health.py --max-age-hours 12
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.exit("pyyaml is required: pip install pyyaml")

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Uptime CI is scheduled every 5 minutes, but GitHub throttles `schedule`
#: triggers on public repositories — hourly is normal. This is a generous
#: ceiling chosen to flag a genuinely stalled pipeline, not ordinary throttling.
DEFAULT_MAX_AGE_HOURS = 24


def parse_timestamp(value: str) -> dt.datetime | None:
    try:
        stamp = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=dt.UTC)
    return stamp


def check(root: Path, max_age_hours: int) -> list[str]:
    """Return a list of problems; empty means the pipeline is healthy."""
    problems: list[str] = []

    config_path = root / ".upptimerc.yml"
    if not config_path.exists():
        return [f"{config_path.name} is missing"]

    config = yaml.safe_load(config_path.read_text()) or {}
    sites = config.get("sites") or []
    if not sites:
        return ["no sites configured"]

    now = dt.datetime.now(dt.UTC)
    cutoff = dt.timedelta(hours=max_age_hours)

    summary = root / "history" / "summary.json"
    if not summary.exists():
        problems.append(
            "history/summary.json is missing — the status page cannot render and "
            "will show an error. Summary CI has never successfully committed."
        )

    for site in sites:
        slug = site.get("slug")
        if not slug:
            continue

        history = root / "history" / f"{slug}.yml"
        if not history.exists():
            problems.append(f"history/{slug}.yml is missing — Uptime CI has never recorded it")
            continue

        try:
            record = yaml.safe_load(history.read_text()) or {}
        except yaml.YAMLError as exc:
            problems.append(f"history/{slug}.yml is not valid YAML: {exc}")
            continue

        stamp = parse_timestamp(record.get("lastUpdated", ""))
        if stamp is None:
            problems.append(f"history/{slug}.yml has no readable lastUpdated")
        elif now - stamp > cutoff:
            age = now - stamp
            hours = round(age.total_seconds() / 3600)
            problems.append(
                f"history/{slug}.yml is {hours}h stale (last updated {stamp:%Y-%m-%d %H:%M} UTC) "
                f"— Uptime CI is not committing"
            )

    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--max-age-hours",
        type=int,
        default=DEFAULT_MAX_AGE_HOURS,
        help=f"how stale data may be before failing (default: {DEFAULT_MAX_AGE_HOURS})",
    )
    parser.add_argument("--root", type=Path, default=REPO_ROOT, help="repository root")
    args = parser.parse_args(argv)

    problems = check(args.root, args.max_age_hours)

    if problems:
        print("The monitoring pipeline is not healthy:\n")
        for problem in problems:
            print(f"  - {problem}")
        print(
            "\nThis means monitoring is NOT running, regardless of what the status "
            "page shows.\nSee docs/RUNBOOK.md -> 'The pipeline is broken'."
        )
        return 1

    print(f"Pipeline healthy: all monitors have data newer than {args.max_age_hours}h.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
