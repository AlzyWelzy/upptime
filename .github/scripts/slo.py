#!/usr/bin/env python3
"""Report uptime against service level objectives, with error budgets.

Raw uptime percentages are hard to act on: "99.2%" does not tell you whether
that is fine. An error budget does — it converts the target into an allowance
of downtime and tells you how much is left.

Targets live in slo.yml at the repository root. Anything not listed there uses
the default target.

    python3 .github/scripts/slo.py                  # 30-day window
    python3 .github/scripts/slo.py --window day
    python3 .github/scripts/slo.py --fail-on-breach # non-zero exit if breached
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.exit("pyyaml is required: pip install pyyaml")

REPO_ROOT = Path(__file__).resolve().parents[2]

#: summary.json key per window, and the window length in minutes.
WINDOWS = {
    "day": ("uptimeDay", 24 * 60),
    "week": ("uptimeWeek", 7 * 24 * 60),
    "month": ("uptimeMonth", 30 * 24 * 60),
    "year": ("uptimeYear", 365 * 24 * 60),
    "all": ("uptime", None),
}

DEFAULT_TARGET = 99.0


def load_targets(root: Path) -> tuple[float, dict[str, float]]:
    """Return (default target, per-slug targets) from slo.yml."""
    path = root / "slo.yml"
    if not path.exists():
        return DEFAULT_TARGET, {}
    config = yaml.safe_load(path.read_text()) or {}
    return float(config.get("default", DEFAULT_TARGET)), {
        str(k): float(v) for k, v in (config.get("targets") or {}).items()
    }


def parse_percent(value: str) -> float | None:
    try:
        return float(str(value).rstrip("%"))
    except (ValueError, AttributeError):
        return None


def format_minutes(minutes: float) -> str:
    minutes = abs(minutes)
    if minutes < 60:
        return f"{minutes:.0f}m"
    if minutes < 24 * 60:
        return f"{minutes / 60:.1f}h"
    return f"{minutes / (24 * 60):.1f}d"


def evaluate(summary: list[dict], window: str, default: float, targets: dict[str, float]):
    """Yield one result row per monitor."""
    key, window_minutes = WINDOWS[window]
    for entry in summary:
        slug = entry.get("slug", "?")
        actual = parse_percent(entry.get(key, ""))
        if actual is None:
            continue
        target = targets.get(slug, default)
        # Error budget: the downtime the target permits over this window.
        budget_minutes = consumed = remaining = None
        if window_minutes:
            budget_minutes = window_minutes * (100 - target) / 100
            consumed = window_minutes * (100 - actual) / 100
            remaining = budget_minutes - consumed
        yield {
            "slug": slug,
            "name": entry.get("name", slug),
            "status": entry.get("status", "?"),
            "actual": actual,
            "target": target,
            "met": actual >= target,
            "budget": budget_minutes,
            "consumed": consumed,
            "remaining": remaining,
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--window", choices=sorted(WINDOWS), default="month")
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    parser.add_argument(
        "--fail-on-breach", action="store_true", help="exit non-zero if any SLO is breached"
    )
    args = parser.parse_args(argv)

    summary_path = args.root / "history" / "summary.json"
    if not summary_path.exists():
        print(
            "history/summary.json not found — the pipeline has not produced data yet.\n"
            "See docs/RUNBOOK.md -> 'The pipeline is broken'.",
            file=sys.stderr,
        )
        return 2

    summary = json.loads(summary_path.read_text())
    default, targets = load_targets(args.root)
    rows = list(evaluate(summary, args.window, default, targets))

    if not rows:
        print("no monitors with data")
        return 0

    width = max(len(r["name"]) for r in rows)
    print(f"SLO report — {args.window} window\n")
    print(f"{'monitor':<{width}} {'target':>7} {'actual':>8} {'budget left':>16}   status")
    print("-" * (width + 42))

    breached = 0
    for row in rows:
        if row["remaining"] is None:
            budget = "n/a"
        elif row["remaining"] >= 0:
            budget = f"{format_minutes(row['remaining'])} of {format_minutes(row['budget'])}"
        else:
            budget = f"-{format_minutes(row['remaining'])} OVER"

        verdict = "ok" if row["met"] else "BREACH"
        breached += not row["met"]
        print(
            f"{row['name']:<{width}} {row['target']:>6.2f}% {row['actual']:>7.2f}% "
            f"{budget:>16}   {verdict}"
        )

    print()
    if breached:
        print(f"{breached} of {len(rows)} monitors are below target.")
    else:
        print(f"All {len(rows)} monitors are meeting their objectives.")

    return 1 if (breached and args.fail_on_breach) else 0


if __name__ == "__main__":
    raise SystemExit(main())
