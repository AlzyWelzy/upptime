#!/usr/bin/env python3
"""Dispatch the Upptime workflows in the correct order, one at a time.

All eight generated workflows share a single `concurrency` group. Dispatching
them together does not queue them — a newer pending run CANCELS the older one,
so most of them never execute. They must be run strictly in sequence, each
waiting for the previous to finish.

The order matters too: everything downstream reads what Uptime CI writes.

    export GH_TOKEN=ghp_...        # or have `gh auth login` set up
    python3 .github/scripts/dispatch.py            # full recovery sequence
    python3 .github/scripts/dispatch.py uptime     # just one
    python3 .github/scripts/dispatch.py --list

The token needs `actions: write` on the repository.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

OWNER_REPO = "AlzyWelzy/upptime"
API = f"https://api.github.com/repos/{OWNER_REPO}"

#: Recovery order. Each entry is (workflow file, human name).
#: Uptime writes history/*.yml; Summary turns that into summary.json and the
#: README table; Response Time and Graphs build api/ and graphs/; Static Site
#: rebuilds and deploys the page last, so it picks up everything above.
SEQUENCE = [
    ("uptime.yml", "Uptime CI"),
    ("summary.yml", "Summary CI"),
    ("response-time.yml", "Response Time CI"),
    ("graphs.yml", "Graphs CI"),
    ("site.yml", "Static Site CI"),
]

POLL_SECONDS = 15
RUN_TIMEOUT_SECONDS = 900


def get_token() -> str:
    for var in ("GH_TOKEN", "GITHUB_TOKEN"):
        if os.environ.get(var):
            return os.environ[var]
    try:
        out = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=15)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    sys.exit(
        "No credentials. Set GH_TOKEN to a PAT with `actions: write`, "
        "or install gh and run `gh auth login`."
    )


def request(path: str, token: str, method: str = "GET", body: dict | None = None):
    req = urllib.request.Request(
        f"{API}{path}",
        method=method,
        data=json.dumps(body).encode() if body else None,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "upptime-dispatch",
            **({"Content-Type": "application/json"} if body else {}),
        },
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        payload = response.read()
        return json.loads(payload) if payload else {}


def latest_run_id(workflow: str, token: str) -> int | None:
    runs = request(f"/actions/workflows/{workflow}/runs?per_page=1", token)["workflow_runs"]
    return runs[0]["id"] if runs else None


def dispatch_and_wait(workflow: str, name: str, token: str, ref: str) -> bool:
    previous = latest_run_id(workflow, token)
    try:
        request(f"/actions/workflows/{workflow}/dispatches", token, "POST", {"ref": ref})
    except urllib.error.HTTPError as exc:
        print(f"  dispatch failed: HTTP {exc.code} {exc.reason}")
        if exc.code in (403, 404):
            print("  (token likely lacks `actions: write`, or cannot see the repo)")
        return False

    print("  dispatched, waiting…", flush=True)

    deadline = time.monotonic() + RUN_TIMEOUT_SECONDS
    run_id = None
    while time.monotonic() < deadline:
        time.sleep(POLL_SECONDS)
        if run_id is None:
            current = latest_run_id(workflow, token)
            if current and current != previous:
                run_id = current
            continue

        run = request(f"/actions/runs/{run_id}", token)
        if run["status"] == "completed":
            ok = run["conclusion"] == "success"
            print(f"  {run['conclusion'].upper()}  {run['html_url']}")
            if not ok:
                for job in request(f"/actions/runs/{run_id}/jobs", token)["jobs"]:
                    for step in job["steps"]:
                        if step["conclusion"] == "failure":
                            print(f"    failing step: {step['name']}")
            return ok

    print("  timed out waiting for completion")
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("only", nargs="?", help="run a single workflow by short name")
    parser.add_argument("--ref", default="master", help="git ref to run against")
    parser.add_argument("--list", action="store_true", help="list the recovery sequence")
    args = parser.parse_args(argv)

    if args.list:
        for workflow, name in SEQUENCE:
            print(f"  {workflow.removesuffix('.yml'):<16} {name}")
        return 0

    sequence = SEQUENCE
    if args.only:
        wanted = args.only.removesuffix(".yml")
        sequence = [s for s in SEQUENCE if s[0].removesuffix(".yml") == wanted]
        if not sequence:
            print(f"unknown workflow '{args.only}' — try --list")
            return 2

    token = get_token()

    for index, (workflow, name) in enumerate(sequence, 1):
        print(f"[{index}/{len(sequence)}] {name}")
        if not dispatch_and_wait(workflow, name, token, args.ref):
            print(
                f"\n{name} did not succeed — stopping. Later stages read what it "
                f"writes, so continuing would be meaningless.\n"
                f"See docs/RUNBOOK.md -> 'The pipeline is broken'."
            )
            return 1

    print("\nAll workflows succeeded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
