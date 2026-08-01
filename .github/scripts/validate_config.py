#!/usr/bin/env python3
"""Validate .upptimerc.yml before it reaches the monitoring workflows.

A bad config does not fail loudly — Upptime runs on a cron, so a typo'd slug or
a malformed URL just means an endpoint silently stops being monitored until
somebody notices. This runs on every pull request so that failure is caught at
review time instead.

Exits non-zero and prints every problem found (not just the first).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.exit("pyyaml is required: pip install pyyaml")

CONFIG = Path(__file__).resolve().parents[2] / ".upptimerc.yml"

SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SECRET_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
HOSTNAME_RE = re.compile(r"^(?=.{1,253}$)(?!-)[a-z0-9-]{1,63}(?<!-)(\.(?!-)[a-z0-9-]{1,63}(?<!-))+$")

# check types that talk HTTP and therefore need a scheme on `url`
HTTP_CHECKS = {None, "http"}
# check types that take a bare hostname, because the value is passed straight
# through as a socket host
HOSTNAME_CHECKS = {"ssl", "tcp-ping"}

# Notification providers are enabled by an explicit "on switch" secret. Having
# the credentials without the switch is a silent no-op, which is exactly the
# kind of thing that is only discovered during an outage.
ON_SWITCHES = {
    "NOTIFICATION_TELEGRAM": ["NOTIFICATION_TELEGRAM_BOT_KEY", "NOTIFICATION_TELEGRAM_CHAT_ID"],
    "NOTIFICATION_EMAIL_SMTP": ["NOTIFICATION_EMAIL_SMTP_HOST"],
    "NOTIFICATION_SLACK": ["NOTIFICATION_SLACK_WEBHOOK_URL"],
}

errors: list[str] = []
warnings: list[str] = []


def error(msg: str) -> None:
    errors.append(msg)


def warn(msg: str) -> None:
    warnings.append(msg)


def validate_sites(config: dict) -> None:
    sites = config.get("sites")
    if not isinstance(sites, list) or not sites:
        error("`sites` must be a non-empty list")
        return

    seen_slugs: dict[str, int] = {}
    seen_names: dict[str, int] = {}

    for index, site in enumerate(sites):
        label = f"sites[{index}]"
        if not isinstance(site, dict):
            error(f"{label}: must be a mapping")
            continue

        name = site.get("name")
        url = site.get("url")
        check = site.get("check")
        label = f"{label} ({name or url or '?'})"

        if not name:
            error(f"{label}: missing `name`")
        elif name in seen_names:
            error(f"{label}: duplicate `name` (also sites[{seen_names[name]}])")
        else:
            seen_names[name] = index

        # A slug is optional in Upptime, but relying on the derived value means
        # renaming a monitor silently orphans and prunes its recorded history.
        slug = site.get("slug")
        if not slug:
            error(f"{label}: missing explicit `slug` — renaming would orphan its history")
        elif not SLUG_RE.match(str(slug)):
            error(f"{label}: slug '{slug}' must be lowercase kebab-case")
        elif slug in seen_slugs:
            error(f"{label}: duplicate `slug` '{slug}' (also sites[{seen_slugs[slug]}])")
        else:
            seen_slugs[slug] = index

        if not url:
            error(f"{label}: missing `url`")
            continue

        url = str(url)
        if check in HOSTNAME_CHECKS:
            # This one is easy to get wrong and fails only at runtime.
            if "://" in url:
                error(
                    f"{label}: check '{check}' needs a BARE HOSTNAME, got '{url}' "
                    f"— drop the scheme"
                )
            elif "/" in url:
                error(f"{label}: check '{check}' needs a bare hostname, got a path in '{url}'")
            elif not url.startswith("$") and not HOSTNAME_RE.match(url):
                error(f"{label}: '{url}' is not a valid hostname")
        elif check in HTTP_CHECKS:
            if not url.startswith("$") and not url.startswith(("http://", "https://")):
                error(f"{label}: HTTP check url must start with http:// or https://, got '{url}'")
            if url.startswith("http://"):
                warn(f"{label}: monitored over plaintext http://")

        codes = site.get("expectedStatusCodes")
        if codes is not None:
            if not isinstance(codes, list) or not codes:
                error(f"{label}: `expectedStatusCodes` must be a non-empty list")
            elif not all(isinstance(c, int) and 100 <= c <= 599 for c in codes):
                error(f"{label}: `expectedStatusCodes` must be integers in 100-599, got {codes}")

        for key in ("maxResponseTime", "connectTimeout", "requestTimeout", "maxRedirects", "port"):
            value = site.get(key)
            if value is not None and (not isinstance(value, int) or value < 0):
                error(f"{label}: `{key}` must be a non-negative integer, got {value!r}")

        for key in (
            "__dangerous__body_down_if_text_missing",
            "__dangerous__body_degraded_if_text_missing",
        ):
            value = site.get(key)
            if value is not None and not str(value).strip():
                error(f"{label}: `{key}` is empty — it would match every response")

        # connectTimeout/requestTimeout are seconds; maxResponseTime is ms.
        request_timeout = site.get("requestTimeout")
        max_response = site.get("maxResponseTime")
        if isinstance(request_timeout, int) and isinstance(max_response, int):
            if max_response > request_timeout * 1000:
                warn(
                    f"{label}: maxResponseTime ({max_response}ms) exceeds requestTimeout "
                    f"({request_timeout}s) — the request aborts before it can be marked degraded"
                )


def validate_secrets(config: dict) -> None:
    secrets = config.get("secrets")
    if secrets is None:
        warn(
            "no `secrets` allowlist — Upptime falls back to compatibility mode and "
            "exposes every supported provider variable to the workflow"
        )
        return

    if not isinstance(secrets, list):
        error("`secrets` must be a list")
        return

    for secret in secrets:
        if not SECRET_RE.match(str(secret)):
            error(f"secrets: '{secret}' must be UPPER_SNAKE_CASE")

    declared = set(map(str, secrets))
    for switch, dependents in ON_SWITCHES.items():
        present = [d for d in dependents if d in declared]
        if present and switch not in declared:
            error(
                f"secrets: {present} declared without the `{switch}` on switch — "
                f"the provider stays disabled"
            )


def validate_status_website(config: dict) -> None:
    site = config.get("status-website")
    if not isinstance(site, dict):
        warn("no `status-website` section")
        return

    cname = site.get("cname")
    if cname:
        if "://" in str(cname) or "/" in str(cname):
            error(f"status-website.cname must be a bare hostname, got '{cname}'")
        elif not HOSTNAME_RE.match(str(cname)):
            error(f"status-website.cname '{cname}' is not a valid hostname")
    elif not site.get("baseUrl"):
        error("status-website needs either `cname` or `baseUrl`, or links will 404")

    for index, item in enumerate(site.get("navbar") or []):
        if not isinstance(item, dict) or not item.get("title") or not item.get("href"):
            error(f"status-website.navbar[{index}]: needs both `title` and `href`")

    for index, tag in enumerate(site.get("metaTags") or []):
        if not isinstance(tag, dict) or not tag.get("name") or not tag.get("content"):
            error(f"status-website.metaTags[{index}]: needs both `name` and `content`")


def validate_schedule(config: dict) -> None:
    schedule = config.get("workflowSchedule")
    if not isinstance(schedule, dict):
        error("`workflowSchedule` must be a mapping")
        return

    known = {"graphs", "responseTime", "staticSite", "summary", "updateTemplate", "updates", "uptime"}
    for key, expr in schedule.items():
        if key not in known:
            error(f"workflowSchedule.{key}: unknown key (valid: {', '.join(sorted(known))})")
        parts = str(expr).split()
        if len(parts) != 5:
            error(f"workflowSchedule.{key}: '{expr}' is not a 5-field cron expression")


def main() -> int:
    if not CONFIG.exists():
        sys.exit(f"{CONFIG} not found")

    try:
        config = yaml.safe_load(CONFIG.read_text())
    except yaml.YAMLError as exc:
        sys.exit(f"{CONFIG.name} is not valid YAML:\n{exc}")

    if not isinstance(config, dict):
        sys.exit(f"{CONFIG.name} must contain a YAML mapping")

    for key in ("owner", "repo"):
        if not config.get(key):
            error(f"missing required key `{key}`")

    if not config.get("assignees"):
        warn("no `assignees` — downtime issues will be unassigned")

    validate_sites(config)
    validate_secrets(config)
    validate_status_website(config)
    validate_schedule(config)

    for message in warnings:
        print(f"warning: {message}")
    for message in errors:
        print(f"error: {message}")

    site_count = len(config.get("sites") or [])
    if errors:
        print(f"\n{len(errors)} error(s), {len(warnings)} warning(s) — {CONFIG.name} is invalid")
        return 1

    print(f"\n{CONFIG.name} is valid: {site_count} monitors, {len(warnings)} warning(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
