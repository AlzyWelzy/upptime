"""Tests for the local probe tool.

`make probe` is what you reach for during an incident to tell a real outage
apart from a problem with the monitoring pipeline. It is worth knowing that it
applies the same thresholds the real checks do — a probe that is more lenient
than production reports "healthy" while users see an outage.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / ".github" / "scripts"))

from probe import (
    DEFAULT_CONNECT_TIMEOUT,
    DEFAULT_REQUEST_TIMEOUT,
    probe,
    probe_http,
    select,
    timeouts,
)


class FakeCompleted:
    """Stands in for subprocess.CompletedProcess."""

    def __init__(self, stdout: str = "", returncode: int = 0, stderr: str = ""):
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr


def curl_output(body: str, code: int, seconds: float) -> str:
    """Reproduce curl's output shape: body, then the -w line."""
    return f"{body}\n{code} {seconds}"


@pytest.fixture
def fake_curl(monkeypatch):
    """Capture the curl argv and return a canned response."""
    calls: list[list[str]] = []
    response = {"result": FakeCompleted(curl_output("hello", 200, 0.1))}

    def fake_run(command, **kwargs):
        calls.append(command)
        result = response["result"]
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(subprocess, "run", fake_run)
    return calls, response


# --------------------------------------------------------------------------
# Timeouts
# --------------------------------------------------------------------------


def test_timeouts_default_when_unset():
    assert timeouts({}) == (DEFAULT_CONNECT_TIMEOUT, DEFAULT_REQUEST_TIMEOUT)


def test_timeouts_use_configured_values():
    assert timeouts({"connectTimeout": 5, "requestTimeout": 10}) == (5, 10)


@pytest.mark.parametrize("bad", [0, -1, "10", None, 1.5])
def test_timeouts_reject_nonsense_and_fall_back(bad):
    assert timeouts({"connectTimeout": bad, "requestTimeout": bad}) == (
        DEFAULT_CONNECT_TIMEOUT,
        DEFAULT_REQUEST_TIMEOUT,
    )


def test_probe_http_passes_configured_timeouts_to_curl(fake_curl):
    calls, _ = fake_curl
    probe_http({"url": "https://x.com", "connectTimeout": 5, "requestTimeout": 10})
    command = calls[0]
    assert command[command.index("--connect-timeout") + 1] == "5"
    assert command[command.index("--max-time") + 1] == "10"


def test_probe_http_passes_max_redirects(fake_curl):
    calls, _ = fake_curl
    probe_http({"url": "https://x.com", "maxRedirects": 3})
    assert calls[0][calls[0].index("--max-redirs") + 1] == "3"


def test_probe_http_omits_max_redirects_when_unset(fake_curl):
    calls, _ = fake_curl
    probe_http({"url": "https://x.com"})
    assert "--max-redirs" not in calls[0]


def test_probe_http_reports_the_timeout_it_used(fake_curl):
    _, response = fake_curl
    response["result"] = subprocess.TimeoutExpired(cmd="curl", timeout=20)
    ok, detail = probe_http({"url": "https://x.com", "requestTimeout": 10})
    assert not ok
    assert "10s" in detail


# --------------------------------------------------------------------------
# Verdicts — these must mirror what Upptime itself would decide
# --------------------------------------------------------------------------


def test_healthy_response(fake_curl):
    ok, detail = probe_http({"url": "https://x.com", "expectedStatusCodes": [200]})
    assert ok
    assert detail == "200 in 100ms"


def test_unexpected_status_code_fails(fake_curl):
    _, response = fake_curl
    response["result"] = FakeCompleted(curl_output("hello", 500, 0.1))
    ok, detail = probe_http({"url": "https://x.com", "expectedStatusCodes": [200]})
    assert not ok
    assert "status 500" in detail


def test_response_over_budget_fails(fake_curl):
    _, response = fake_curl
    response["result"] = FakeCompleted(curl_output("hello", 200, 3.0))
    ok, detail = probe_http({"url": "https://x.com", "maxResponseTime": 2000})
    assert not ok
    assert "3000ms over 2000ms budget" in detail


def test_missing_content_assertion_fails(fake_curl):
    """A 200 that does not contain the expected string is still an outage."""
    ok, detail = probe_http(
        {"url": "https://x.com", "__dangerous__body_down_if_text_missing": "Welcome"}
    )
    assert not ok
    assert "missing content assertion" in detail


def test_present_content_assertion_passes(fake_curl):
    ok, _ = probe_http({"url": "https://x.com", "__dangerous__body_down_if_text_missing": "hello"})
    assert ok


def test_all_problems_are_reported_together(fake_curl):
    _, response = fake_curl
    response["result"] = FakeCompleted(curl_output("nope", 503, 4.0))
    ok, detail = probe_http(
        {
            "url": "https://x.com",
            "expectedStatusCodes": [200],
            "maxResponseTime": 2000,
            "__dangerous__body_down_if_text_missing": "hello",
        }
    )
    assert not ok
    assert "status 503" in detail
    assert "budget" in detail
    assert "content assertion" in detail


def test_curl_failure_is_reported(fake_curl):
    _, response = fake_curl
    response["result"] = FakeCompleted("", returncode=6, stderr="curl: (6) Could not resolve host")
    ok, detail = probe_http({"url": "https://x.com"})
    assert not ok
    assert "Could not resolve host" in detail


def test_unparseable_output_is_reported(fake_curl):
    _, response = fake_curl
    response["result"] = FakeCompleted("garbage with no trailing metrics line")
    ok, detail = probe_http({"url": "https://x.com"})
    assert not ok
    assert "unparseable" in detail


def test_runtime_secret_url_is_skipped(fake_curl):
    calls, _ = fake_curl
    ok, detail = probe_http({"url": "$SECRET_URL"})
    assert ok
    assert "skipped" in detail
    assert calls == []  # no request attempted


# --------------------------------------------------------------------------
# Selection
# --------------------------------------------------------------------------

SITES = [
    {"name": "http", "url": "https://x.com"},
    {"name": "tls", "url": "x.com", "check": "ssl"},
    {"name": "ws", "url": "wss://x.com", "check": "ws"},
    {"name": "ping", "url": "x.com", "check": "tcp-ping"},
]


def names(sites: list[dict]) -> list[str]:
    return [s["name"] for s in sites]


def test_select_http_only():
    assert names(select(SITES, want_http=True, want_tls=False)) == ["http"]


def test_select_tls_only():
    assert names(select(SITES, want_http=False, want_tls=True)) == ["tls"]


def test_select_both_preserves_config_order():
    assert names(select(SITES, want_http=True, want_tls=True)) == ["http", "tls"]


def test_select_skips_unsupported_check_types():
    """probe.py cannot run ws or tcp-ping checks; it must not claim they passed."""
    selected = names(select(SITES, want_http=True, want_tls=True))
    assert "ws" not in selected and "ping" not in selected


def test_probe_dispatches_ssl_to_the_tls_checker(monkeypatch):
    monkeypatch.setattr("probe.probe_tls", lambda site: (True, "tls"))
    monkeypatch.setattr("probe.probe_http", lambda site: (True, "http"))
    assert probe({"url": "x.com", "check": "ssl"}) == (True, "tls")
    assert probe({"url": "https://x.com"}) == (True, "http")
