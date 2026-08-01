#!/usr/bin/env python3
"""Probe every monitored target right now, from this machine.

The GitHub Actions runners check on a cron from US datacenters. This gives you
the same checks from wherever you are, which is the quickest way to tell a real
outage apart from something specific to the runners.

    python3 .github/scripts/probe.py           # everything
    python3 .github/scripts/probe.py --http    # HTTP endpoints only
    python3 .github/scripts/probe.py --tls     # certificates only
"""

from __future__ import annotations

import argparse
import datetime as dt
import socket
import ssl
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.exit("pyyaml is required: pip install pyyaml")

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG = REPO_ROOT / ".upptimerc.yml"

#: Upptime reports a certificate as down once it has less than this left.
TLS_DOWN_THRESHOLD_DAYS = 7


def load_sites() -> list[dict]:
    config = yaml.safe_load(CONFIG.read_text())
    return config.get("sites") or []


def probe_http(site: dict) -> tuple[bool, str]:
    """Return (ok, description) for one HTTP monitor."""
    url = site["url"]
    if url.startswith("$"):
        return True, "skipped (runtime secret)"

    expected = site.get("expectedStatusCodes") or [200]
    budget_ms = site.get("maxResponseTime")
    needle = site.get("__dangerous__body_down_if_text_missing")

    try:
        proc = subprocess.run(
            ["curl", "-sSL", "--max-time", "25", "-w", "\n%{http_code} %{time_total}", url],
            capture_output=True,
            text=True,
            timeout=40,
        )
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"

    if proc.returncode != 0:
        return False, f"curl failed: {proc.stderr.strip().splitlines()[-1:] or proc.returncode}"

    body, _, tail = proc.stdout.rpartition("\n")
    try:
        code_str, time_str = tail.split()
        code, seconds = int(code_str), float(time_str)
    except ValueError:
        return False, f"unparseable curl output: {tail!r}"

    ms = round(seconds * 1000)
    problems = []
    if code not in expected:
        problems.append(f"status {code}, expected {expected}")
    if budget_ms and ms > budget_ms:
        problems.append(f"{ms}ms over {budget_ms}ms budget")
    if needle and needle not in body:
        problems.append(f"missing content assertion {needle!r}")

    if problems:
        return False, "; ".join(problems)
    return True, f"{code} in {ms}ms"


def probe_tls(site: dict) -> tuple[bool, str]:
    """Return (ok, description) for one TLS certificate monitor."""
    host = site["url"]
    port = int(site.get("port") or 443)
    try:
        with socket.create_connection((host, port), timeout=15) as sock:
            context = ssl.create_default_context()
            with context.wrap_socket(sock, server_hostname=host) as tls:
                cert = tls.getpeercert()
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"

    expires = dt.datetime.strptime(cert["notAfter"], "%b %d %H:%M:%S %Y %Z").replace(tzinfo=dt.UTC)
    days = (expires - dt.datetime.now(dt.UTC)).days
    issuer = dict(x[0] for x in cert.get("issuer", ())).get("organizationName", "?")

    if days < TLS_DOWN_THRESHOLD_DAYS:
        return False, f"expires {expires:%Y-%m-%d} in {days}d — Upptime reports this DOWN"
    return True, f"expires {expires:%Y-%m-%d} ({days}d, {issuer})"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--http", action="store_true", help="only probe HTTP monitors")
    parser.add_argument("--tls", action="store_true", help="only probe TLS certificates")
    args = parser.parse_args(argv)

    want_http = args.http or not args.tls
    want_tls = args.tls or not args.http

    failures = 0
    for site in load_sites():
        check = site.get("check")
        if check == "ssl" and want_tls:
            ok, detail = probe_tls(site)
        elif not check and want_http:
            ok, detail = probe_http(site)
        else:
            continue

        failures += not ok
        print(f"{'ok  ' if ok else 'FAIL'} {site['name']:<32} {detail}")

    print(f"\n{failures} failing" if failures else "\nall monitors healthy")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
