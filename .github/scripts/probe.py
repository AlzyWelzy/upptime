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
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.exit("pyyaml is required: pip install pyyaml")

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG = REPO_ROOT / ".upptimerc.yml"

#: Upptime reports a certificate as down once it has less than this left.
TLS_DOWN_THRESHOLD_DAYS = 7

#: Upptime's own defaults, applied when a site does not set them. Matching them
#: matters: probing with a longer timeout than the real check uses reports a
#: slow response where production reports an outage.
DEFAULT_CONNECT_TIMEOUT = 10
DEFAULT_REQUEST_TIMEOUT = 30

#: Grace on top of --max-time before we give up on curl itself, so a wedged
#: subprocess cannot hang the run.
SUBPROCESS_GRACE_SECONDS = 10

#: Monitors are independent, so probe them at once — otherwise a single
#: unreachable host adds its full timeout to every run.
MAX_WORKERS = 8


def load_sites(path: Path = CONFIG) -> list[dict]:
    config = yaml.safe_load(path.read_text())
    return config.get("sites") or []


def timeouts(site: dict) -> tuple[int, int]:
    """Return (connect, request) timeouts in seconds for a monitor."""
    connect = site.get("connectTimeout")
    request = site.get("requestTimeout")
    return (
        connect if isinstance(connect, int) and connect > 0 else DEFAULT_CONNECT_TIMEOUT,
        request if isinstance(request, int) and request > 0 else DEFAULT_REQUEST_TIMEOUT,
    )


def probe_http(site: dict) -> tuple[bool, str]:
    """Return (ok, description) for one HTTP monitor."""
    url = site["url"]
    if url.startswith("$"):
        return True, "skipped (runtime secret)"

    expected = site.get("expectedStatusCodes") or [200]
    budget_ms = site.get("maxResponseTime")
    needle = site.get("__dangerous__body_down_if_text_missing")
    connect_timeout, request_timeout = timeouts(site)

    command = [
        "curl",
        "-sSL",
        "--connect-timeout",
        str(connect_timeout),
        "--max-time",
        str(request_timeout),
        "-w",
        "\n%{http_code} %{time_total}",
    ]
    max_redirects = site.get("maxRedirects")
    if isinstance(max_redirects, int):
        command += ["--max-redirs", str(max_redirects)]
    command.append(url)

    try:
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=request_timeout + SUBPROCESS_GRACE_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return False, f"TIMEOUT (over {request_timeout}s)"

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
    connect_timeout, _ = timeouts(site)
    try:
        with socket.create_connection((host, port), timeout=connect_timeout) as sock:
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


def select(sites: list[dict], want_http: bool, want_tls: bool) -> list[dict]:
    """The monitors this run should probe, in config order."""
    chosen = []
    for site in sites:
        check = site.get("check")
        if (check == "ssl" and want_tls) or (not check and want_http):
            chosen.append(site)
    return chosen


def probe(site: dict) -> tuple[bool, str]:
    return probe_tls(site) if site.get("check") == "ssl" else probe_http(site)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--http", action="store_true", help="only probe HTTP monitors")
    parser.add_argument("--tls", action="store_true", help="only probe TLS certificates")
    parser.add_argument(
        "--jobs", type=int, default=MAX_WORKERS, help=f"parallel probes (default: {MAX_WORKERS})"
    )
    parser.add_argument("--config", type=Path, default=CONFIG, help="path to .upptimerc.yml")
    args = parser.parse_args(argv)

    want_http = args.http or not args.tls
    want_tls = args.tls or not args.http

    sites = select(load_sites(args.config), want_http, want_tls)
    if not sites:
        print("no matching monitors")
        return 0

    # Probes run concurrently but are reported in config order, so two runs are
    # diffable against each other.
    with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        results = list(pool.map(probe, sites))

    width = max(len(str(site["name"])) for site in sites)
    failures = 0
    for site, (ok, detail) in zip(sites, results, strict=True):
        failures += not ok
        print(f"{'ok  ' if ok else 'FAIL'} {site['name']!s:<{width}}  {detail}")

    print(f"\n{failures} of {len(sites)} failing" if failures else f"\nall {len(sites)} healthy")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
