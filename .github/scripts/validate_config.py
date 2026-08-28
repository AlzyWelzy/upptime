#!/usr/bin/env python3
"""Validate .upptimerc.yml before it reaches the monitoring workflows.

A bad config does not fail loudly — Upptime runs on a cron, so a typo'd slug or
a malformed URL just means an endpoint silently stops being monitored until
somebody notices. This runs on every pull request so that failure is caught at
review time instead.

The config does not stand alone, so neither does this check. slo.yml's targets
are keyed by monitor slug and applied by string match, and history/, api/ and
graphs/ hold one entry per slug; both drift out of step with `sites` silently.
Those cross-file checks run whenever the config's directory is available.

Exits non-zero and reports every problem found, not just the first.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.exit("pyyaml is required: pip install pyyaml")

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = REPO_ROOT / ".upptimerc.yml"

SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SECRET_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}$)(?!-)[a-z0-9-]{1,63}(?<!-)(\.(?!-)[a-z0-9-]{1,63}(?<!-))+$"
)

#: Check types that speak HTTP and therefore need a scheme on ``url``.
HTTP_CHECKS = frozenset({None, "http"})
#: Check types whose ``url`` is passed straight through as a socket host, so it
#: must be a bare hostname.
HOSTNAME_CHECKS = frozenset({"ssl", "tcp-ping"})
#: Every check type Upptime understands.
KNOWN_CHECKS = frozenset({"http", "tcp-ping", "ws", "ssl"})

#: Keys that only apply to HTTP checks; silently ignored elsewhere.
HTTP_ONLY_KEYS = (
    "expectedStatusCodes",
    "maxResponseTime",
    "maxRedirects",
    "__dangerous__body_down_if_text_missing",
    "__dangerous__body_degraded_if_text_missing",
    "__dangerous__body_down",
    "__dangerous__body_degraded",
)

#: Notification providers are enabled by an explicit "on switch" secret. Having
#: the credentials without the switch is a silent no-op — exactly the kind of
#: thing only discovered during an outage.
ON_SWITCHES = {
    "NOTIFICATION_TELEGRAM": ["NOTIFICATION_TELEGRAM_BOT_KEY", "NOTIFICATION_TELEGRAM_CHAT_ID"],
    "NOTIFICATION_EMAIL_SMTP": ["NOTIFICATION_EMAIL_SMTP_HOST", "NOTIFICATION_EMAIL_SMTP_PASSWORD"],
    "NOTIFICATION_SLACK": ["NOTIFICATION_SLACK_WEBHOOK_URL"],
    "NOTIFICATION_GOTIFY": ["NOTIFICATION_GOTIFY_TOKEN", "NOTIFICATION_GOTIFY_URL"],
}

VALID_SCHEDULE_KEYS = frozenset(
    {"graphs", "responseTime", "staticSite", "summary", "updateTemplate", "updates", "uptime"}
)

#: Kept in step with slo.py, which applies this when slo.yml omits `default`.
DEFAULT_SLO_TARGET = 99.0

#: Directories Upptime writes one entry per monitor slug into.
DATA_DIRS = ("history", "api", "graphs")


@dataclass
class Report:
    """Collected findings. Errors fail the build; warnings do not."""

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    @property
    def ok(self) -> bool:
        return not self.errors


def _check_site_url(report: Report, label: str, url: str, check: str | None) -> None:
    # "$VAR" placeholders are substituted at runtime from secrets; skip them.
    if url.startswith("$"):
        return

    if check in HOSTNAME_CHECKS:
        if "://" in url:
            report.error(
                f"{label}: check '{check}' needs a BARE HOSTNAME, got '{url}' — drop the scheme"
            )
        elif "/" in url:
            report.error(f"{label}: check '{check}' needs a bare hostname, got a path in '{url}'")
        elif not HOSTNAME_RE.match(url):
            report.error(f"{label}: '{url}' is not a valid hostname")
    elif check in HTTP_CHECKS:
        if not url.startswith(("http://", "https://")):
            report.error(
                f"{label}: HTTP check url must start with http:// or https://, got '{url}'"
            )
        elif url.startswith("http://"):
            report.warn(f"{label}: monitored over plaintext http://")


def validate_sites(config: dict, report: Report) -> None:
    sites = config.get("sites")
    if not isinstance(sites, list) or not sites:
        report.error("`sites` must be a non-empty list")
        return

    seen_slugs: dict[str, int] = {}
    seen_names: dict[str, int] = {}
    seen_targets: dict[tuple[str, str], int] = {}

    for index, site in enumerate(sites):
        label = f"sites[{index}]"
        if not isinstance(site, dict):
            report.error(f"{label}: must be a mapping")
            continue

        name = site.get("name")
        url = site.get("url")
        check = site.get("check")
        label = f"{label} ({name or url or '?'})"

        if check is not None and check not in KNOWN_CHECKS:
            report.error(
                f"{label}: unknown check '{check}' (valid: {', '.join(sorted(KNOWN_CHECKS))})"
            )

        if not name:
            report.error(f"{label}: missing `name`")
        elif name in seen_names:
            report.error(f"{label}: duplicate `name` (also sites[{seen_names[name]}])")
        else:
            seen_names[name] = index

        # A slug is optional in Upptime, but relying on the derived value means
        # renaming a monitor silently orphans and prunes its recorded history.
        slug = site.get("slug")
        if not slug:
            report.error(f"{label}: missing explicit `slug` — renaming would orphan its history")
        elif not SLUG_RE.match(str(slug)):
            report.error(f"{label}: slug '{slug}' must be lowercase kebab-case")
        elif slug in seen_slugs:
            report.error(f"{label}: duplicate `slug` '{slug}' (also sites[{seen_slugs[slug]}])")
        else:
            seen_slugs[slug] = index

        if not url:
            report.error(f"{label}: missing `url`")
            continue

        url = str(url)
        _check_site_url(report, label, url, check)

        target = (str(check or "http"), url)
        if target in seen_targets:
            report.warn(
                f"{label}: same {target[0]} target as sites[{seen_targets[target]}] ('{url}')"
            )
        else:
            seen_targets[target] = index

        # Keys that do nothing for non-HTTP checks are worth flagging: they read
        # as protection that isn't actually there.
        if check in HOSTNAME_CHECKS or check == "ws":
            for key in HTTP_ONLY_KEYS:
                if site.get(key) is not None:
                    report.warn(f"{label}: `{key}` is ignored for check '{check}'")

        codes = site.get("expectedStatusCodes")
        if codes is not None:
            if not isinstance(codes, list) or not codes:
                report.error(f"{label}: `expectedStatusCodes` must be a non-empty list")
            elif not all(isinstance(c, int) and 100 <= c <= 599 for c in codes):
                report.error(
                    f"{label}: `expectedStatusCodes` must be integers in 100-599, got {codes}"
                )

        for key in ("maxResponseTime", "connectTimeout", "requestTimeout", "maxRedirects", "port"):
            value = site.get(key)
            if value is not None and (not isinstance(value, int) or value < 0):
                report.error(f"{label}: `{key}` must be a non-negative integer, got {value!r}")

        for key in (
            "__dangerous__body_down_if_text_missing",
            "__dangerous__body_degraded_if_text_missing",
        ):
            value = site.get(key)
            if value is not None and not str(value).strip():
                report.error(f"{label}: `{key}` is empty — it would match every response")

        # connectTimeout/requestTimeout are seconds; maxResponseTime is ms.
        request_timeout = site.get("requestTimeout")
        max_response = site.get("maxResponseTime")
        if (
            isinstance(request_timeout, int)
            and isinstance(max_response, int)
            and max_response > request_timeout * 1000
        ):
            report.warn(
                f"{label}: maxResponseTime ({max_response}ms) exceeds requestTimeout "
                f"({request_timeout}s) — the request aborts before it can be marked degraded"
            )


def validate_secrets(config: dict, report: Report) -> None:
    secrets = config.get("secrets")
    if secrets is None:
        report.warn(
            "no `secrets` allowlist — Upptime falls back to compatibility mode and "
            "exposes every supported provider variable to the workflow"
        )
        return

    if not isinstance(secrets, list):
        report.error("`secrets` must be a list")
        return

    for secret in secrets:
        if not SECRET_RE.match(str(secret)):
            report.error(f"secrets: '{secret}' must be UPPER_SNAKE_CASE")

    if len(set(map(str, secrets))) != len(secrets):
        report.error("secrets: contains duplicate entries")

    declared = set(map(str, secrets))
    for switch, dependents in ON_SWITCHES.items():
        present = [d for d in dependents if d in declared]
        if present and switch not in declared:
            report.error(
                f"secrets: {present} declared without the `{switch}` on switch — "
                f"the provider stays disabled"
            )


def validate_status_website(config: dict, report: Report) -> None:
    site = config.get("status-website")
    if not isinstance(site, dict):
        report.warn("no `status-website` section")
        return

    cname = site.get("cname")
    if cname:
        if "://" in str(cname) or "/" in str(cname):
            report.error(f"status-website.cname must be a bare hostname, got '{cname}'")
        elif not HOSTNAME_RE.match(str(cname)):
            report.error(f"status-website.cname '{cname}' is not a valid hostname")
    elif not site.get("baseUrl"):
        report.error("status-website needs either `cname` or `baseUrl`, or links will 404")

    for index, item in enumerate(site.get("navbar") or []):
        if not isinstance(item, dict) or not item.get("title") or not item.get("href"):
            report.error(f"status-website.navbar[{index}]: needs both `title` and `href`")

    meta_tags = site.get("metaTags") or []
    for index, tag in enumerate(meta_tags):
        if not isinstance(tag, dict) or not tag.get("name") or not tag.get("content"):
            report.error(f"status-website.metaTags[{index}]: needs both `name` and `content`")

    # A stale og:url silently misattributes every social preview.
    if cname:
        for tag in meta_tags:
            if isinstance(tag, dict) and tag.get("name") == "og:url":
                content = str(tag.get("content", ""))
                if str(cname) not in content:
                    report.warn(
                        f"status-website: og:url '{content}' does not match cname '{cname}'"
                    )


def validate_schedule(config: dict, report: Report) -> None:
    schedule = config.get("workflowSchedule")
    if not isinstance(schedule, dict):
        report.error("`workflowSchedule` must be a mapping")
        return

    for key, expr in schedule.items():
        if key not in VALID_SCHEDULE_KEYS:
            report.error(
                f"workflowSchedule.{key}: unknown key "
                f"(valid: {', '.join(sorted(VALID_SCHEDULE_KEYS))})"
            )
        if len(str(expr).split()) != 5:
            report.error(f"workflowSchedule.{key}: '{expr}' is not a 5-field cron expression")


def configured_slugs(config: dict) -> set[str]:
    """Every explicitly-pinned monitor slug in the config."""
    return {
        str(site["slug"])
        for site in config.get("sites") or []
        if isinstance(site, dict) and site.get("slug")
    }


def _check_percent(report: Report, label: str, value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, int | float):
        report.error(f"{label} must be a number, got {value!r}")
        return False
    if not 0 <= value <= 100:
        report.error(f"{label} must be a percentage between 0 and 100, got {value}")
        return False
    return True


def validate_slo(config: dict, report: Report, root: Path) -> None:
    """Cross-check slo.yml against the configured monitors.

    slo.py silently falls back to the default target for any slug it does not
    recognise, so a stale or typo'd entry here fails in the quietest possible
    way: the target you wrote never applies, and the monitor is reported against
    a number nobody chose. Nothing about the output looks wrong.
    """
    path = root / "slo.yml"
    if not path.exists():
        # slo.yml is optional — slo.py has a documented default.
        return

    try:
        slo = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        report.error(f"slo.yml is not valid YAML: {exc}")
        return

    if slo is None:
        slo = {}
    if not isinstance(slo, dict):
        report.error("slo.yml must be a YAML mapping")
        return

    _check_percent(report, "slo.yml: `default`", slo.get("default", DEFAULT_SLO_TARGET))

    targets = slo.get("targets") or {}
    if not isinstance(targets, dict):
        report.error("slo.yml: `targets` must be a mapping of slug to percentage")
        return

    configured = configured_slugs(config)
    for slug, value in targets.items():
        _check_percent(report, f"slo.yml: target `{slug}`", value)
        if str(slug) not in configured:
            report.error(
                f"slo.yml: target `{slug}` matches no monitor in `sites` — it has no effect"
            )

    # Not an error: the default is a legitimate choice. But it should be a
    # deliberate one, and a monitor added without a target gets it by omission.
    for slug in sorted(configured - {str(s) for s in targets}):
        report.warn(f"slo.yml: `{slug}` has no target and falls back to the default")


def validate_data_artifacts(config: dict, report: Report, root: Path) -> None:
    """Flag recorded data belonging to monitors that are no longer configured.

    `update-template` prunes history/, api/ and graphs/ entries for slugs it no
    longer recognises — but only the next time it runs. Until then the status
    page and the README keep rendering the removed monitor's last known state,
    which reads as a live service rather than a deleted one.
    """
    configured = configured_slugs(config)
    if not configured:
        return

    orphans: dict[str, list[str]] = {}
    for name in DATA_DIRS:
        directory = root / name
        if not directory.is_dir():
            continue
        if name == "history":
            found = {path.stem for path in directory.glob("*.yml")}
        else:
            found = {path.name for path in directory.iterdir() if path.is_dir()}
        for slug in found - configured:
            orphans.setdefault(slug, []).append(name)

    for slug, dirs in sorted(orphans.items()):
        report.warn(
            f"'{slug}' has data under {'/, '.join(dirs)}/ but is not in `sites` — "
            f"stale data from a removed monitor"
        )


def validate(config: dict, root: Path | None = None) -> Report:
    """Validate a parsed .upptimerc.yml mapping.

    When ``root`` is given, sibling files are cross-checked too: slo.yml's
    targets and the recorded data under history/, api/ and graphs/.
    """
    report = Report()

    if not isinstance(config, dict):
        report.error("config must be a YAML mapping")
        return report

    for key in ("owner", "repo"):
        if not config.get(key):
            report.error(f"missing required key `{key}`")

    assignees = config.get("assignees")
    if not assignees:
        report.warn("no `assignees` — downtime issues will be unassigned")
    elif not isinstance(assignees, list) or not all(isinstance(a, str) for a in assignees):
        report.error("`assignees` must be a list of GitHub usernames")

    validate_sites(config, report)
    validate_secrets(config, report)
    validate_status_website(config, report)
    validate_schedule(config, report)
    if root is not None:
        validate_slo(config, report, root)
        validate_data_artifacts(config, report, root)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "config", nargs="?", type=Path, default=DEFAULT_CONFIG, help="path to .upptimerc.yml"
    )
    parser.add_argument("--strict", action="store_true", help="treat warnings as errors")
    args = parser.parse_args(argv)

    if not args.config.exists():
        print(f"error: {args.config} not found", file=sys.stderr)
        return 2

    try:
        config = yaml.safe_load(args.config.read_text())
    except yaml.YAMLError as exc:
        print(f"error: {args.config.name} is not valid YAML:\n{exc}", file=sys.stderr)
        return 2

    report = validate(config, root=args.config.parent)

    for message in report.warnings:
        print(f"warning: {message}")
    for message in report.errors:
        print(f"error: {message}")

    site_count = len(config.get("sites") or []) if isinstance(config, dict) else 0
    failed = bool(report.errors) or (args.strict and report.warnings)

    if failed:
        print(
            f"\n{len(report.errors)} error(s), {len(report.warnings)} warning(s) — "
            f"{args.config.name} is invalid"
        )
        return 1

    print(
        f"\n{args.config.name} is valid: {site_count} monitors, {len(report.warnings)} warning(s)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
