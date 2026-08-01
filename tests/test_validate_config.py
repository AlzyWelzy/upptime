"""Tests for the .upptimerc.yml validator.

The validator is the only thing standing between a typo and an endpoint that
silently stops being monitored, so it gets tests of its own — including a check
that the repository's real config passes.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / ".github" / "scripts"))

from validate_config import main, validate


def base_config(**overrides) -> dict:
    """A minimal config that validates cleanly."""
    config = {
        "owner": "AlzyWelzy",
        "repo": "upptime",
        "assignees": ["AlzyWelzy"],
        "sites": [
            {
                "name": "example",
                "slug": "example",
                "url": "https://example.com",
                "expectedStatusCodes": [200],
            }
        ],
        "secrets": ["NOTIFICATION_TELEGRAM", "NOTIFICATION_TELEGRAM_BOT_KEY"],
        "status-website": {"cname": "status.example.com"},
        "workflowSchedule": {"uptime": "*/5 * * * *"},
    }
    config.update(overrides)
    return config


def errors_for(**overrides) -> list[str]:
    return validate(base_config(**overrides)).errors


def only_site(site: dict) -> list[str]:
    return errors_for(sites=[site])


def test_base_config_is_valid():
    report = validate(base_config())
    assert report.ok, report.errors
    assert report.warnings == []


def test_missing_owner_and_repo():
    config = base_config()
    del config["owner"]
    del config["repo"]
    errors = validate(config).errors
    assert any("`owner`" in e for e in errors)
    assert any("`repo`" in e for e in errors)


# --------------------------------------------------------------------------
# Sites
# --------------------------------------------------------------------------


def test_sites_must_be_non_empty():
    assert any("non-empty" in e for e in errors_for(sites=[]))


def test_missing_slug_is_an_error():
    errors = only_site({"name": "x", "url": "https://x.com"})
    assert any("missing explicit `slug`" in e for e in errors)


@pytest.mark.parametrize("slug", ["Bad_Slug", "UPPER", "trailing-", "double--dash", "sp ace"])
def test_bad_slugs_rejected(slug):
    errors = only_site({"name": "x", "slug": slug, "url": "https://x.com"})
    assert any("kebab-case" in e for e in errors)


def test_duplicate_slugs_rejected():
    errors = errors_for(
        sites=[
            {"name": "a", "slug": "dup", "url": "https://a.com"},
            {"name": "b", "slug": "dup", "url": "https://b.com"},
        ]
    )
    assert any("duplicate `slug`" in e for e in errors)


def test_duplicate_names_rejected():
    errors = errors_for(
        sites=[
            {"name": "same", "slug": "a", "url": "https://a.com"},
            {"name": "same", "slug": "b", "url": "https://b.com"},
        ]
    )
    assert any("duplicate `name`" in e for e in errors)


def test_http_check_requires_scheme():
    errors = only_site({"name": "x", "slug": "x", "url": "example.com"})
    assert any("must start with http" in e for e in errors)


def test_ssl_check_rejects_scheme():
    """The single easiest mistake to make: it only fails at runtime otherwise."""
    errors = only_site({"name": "x", "slug": "x", "url": "https://example.com", "check": "ssl"})
    assert any("BARE HOSTNAME" in e for e in errors)


def test_ssl_check_accepts_bare_hostname():
    report = validate(
        base_config(sites=[{"name": "x", "slug": "x", "url": "example.com", "check": "ssl"}])
    )
    assert report.ok, report.errors


def test_ssl_check_rejects_path():
    errors = only_site({"name": "x", "slug": "x", "url": "example.com/health", "check": "ssl"})
    assert any("bare hostname" in e for e in errors)


def test_unknown_check_type_rejected():
    errors = only_site(
        {"name": "x", "slug": "x", "url": "https://x.com", "check": "carrier-pigeon"}
    )
    assert any("unknown check" in e for e in errors)


def test_env_var_url_is_skipped():
    """`$SECRET_URL` is substituted at runtime, so it can't be validated here."""
    report = validate(base_config(sites=[{"name": "x", "slug": "x", "url": "$SECRET_URL"}]))
    assert report.ok, report.errors


@pytest.mark.parametrize("codes", [[999], [99], ["200"], []])
def test_bad_status_codes_rejected(codes):
    errors = only_site(
        {"name": "x", "slug": "x", "url": "https://x.com", "expectedStatusCodes": codes}
    )
    assert errors


def test_empty_content_assertion_rejected():
    """A blank assertion matches every response — protection that isn't there."""
    errors = only_site(
        {
            "name": "x",
            "slug": "x",
            "url": "https://x.com",
            "__dangerous__body_down_if_text_missing": "   ",
        }
    )
    assert any("would match every response" in e for e in errors)


@pytest.mark.parametrize("key", ["maxResponseTime", "connectTimeout", "requestTimeout", "port"])
def test_negative_numeric_keys_rejected(key):
    errors = only_site({"name": "x", "slug": "x", "url": "https://x.com", key: -1})
    assert any(key in e for e in errors)


def test_plaintext_http_warns():
    report = validate(base_config(sites=[{"name": "x", "slug": "x", "url": "http://x.com"}]))
    assert any("plaintext" in w for w in report.warnings)


def test_timeout_shorter_than_response_budget_warns():
    report = validate(
        base_config(
            sites=[
                {
                    "name": "x",
                    "slug": "x",
                    "url": "https://x.com",
                    "maxResponseTime": 60000,
                    "requestTimeout": 30,
                }
            ]
        )
    )
    assert any("aborts before" in w for w in report.warnings)


def test_http_only_keys_on_ssl_check_warn():
    report = validate(
        base_config(
            sites=[
                {
                    "name": "x",
                    "slug": "x",
                    "url": "x.com",
                    "check": "ssl",
                    "maxResponseTime": 2000,
                }
            ]
        )
    )
    assert any("ignored for check 'ssl'" in w for w in report.warnings)


def test_duplicate_target_warns():
    report = validate(
        base_config(
            sites=[
                {"name": "a", "slug": "a", "url": "https://same.com"},
                {"name": "b", "slug": "b", "url": "https://same.com"},
            ]
        )
    )
    assert any("same http target" in w for w in report.warnings)


# --------------------------------------------------------------------------
# Secrets
# --------------------------------------------------------------------------


def test_credentials_without_on_switch_rejected():
    errors = errors_for(secrets=["NOTIFICATION_TELEGRAM_BOT_KEY"])
    assert any("on switch" in e for e in errors)


def test_lowercase_secret_rejected():
    assert any("UPPER_SNAKE_CASE" in e for e in errors_for(secrets=["lowercase"]))


def test_duplicate_secrets_rejected():
    errors = errors_for(secrets=["NOTIFICATION_TELEGRAM", "NOTIFICATION_TELEGRAM"])
    assert any("duplicate" in e for e in errors)


def test_missing_secrets_allowlist_warns():
    config = base_config()
    del config["secrets"]
    assert any("compatibility mode" in w for w in validate(config).warnings)


# --------------------------------------------------------------------------
# Status website
# --------------------------------------------------------------------------


def test_cname_must_be_bare_hostname():
    errors = errors_for(**{"status-website": {"cname": "https://status.example.com/"}})
    assert any("bare hostname" in e for e in errors)


def test_cname_or_baseurl_required():
    errors = errors_for(**{"status-website": {"name": "x"}})
    assert any("cname" in e and "baseUrl" in e for e in errors)


def test_navbar_entry_needs_href():
    errors = errors_for(
        **{"status-website": {"cname": "s.example.com", "navbar": [{"title": "No href"}]}}
    )
    assert any("navbar[0]" in e for e in errors)


def test_og_url_mismatch_warns():
    report = validate(
        base_config(
            **{
                "status-website": {
                    "cname": "status.example.com",
                    "metaTags": [{"name": "og:url", "content": "https://wrong.example.org"}],
                }
            }
        )
    )
    assert any("og:url" in w for w in report.warnings)


# --------------------------------------------------------------------------
# Schedule
# --------------------------------------------------------------------------


def test_bad_cron_rejected():
    assert any("5-field cron" in e for e in errors_for(workflowSchedule={"uptime": "*/5 * * *"}))


def test_unknown_schedule_key_rejected():
    assert any("unknown key" in e for e in errors_for(workflowSchedule={"nope": "0 0 * * *"}))


# --------------------------------------------------------------------------
# The real config, and the CLI
# --------------------------------------------------------------------------


def test_repository_config_is_valid():
    """The config actually shipped in this repo must pass."""
    config = yaml.safe_load((REPO_ROOT / ".upptimerc.yml").read_text())
    report = validate(config)
    assert report.ok, report.errors


def test_cli_accepts_real_config():
    assert main([str(REPO_ROOT / ".upptimerc.yml")]) == 0


def test_cli_missing_file_returns_2(tmp_path):
    assert main([str(tmp_path / "nope.yml")]) == 2


def test_cli_invalid_yaml_returns_2(tmp_path):
    bad = tmp_path / "bad.yml"
    bad.write_text("sites: [unclosed\n")
    assert main([str(bad)]) == 2


def test_cli_invalid_config_returns_1(tmp_path):
    bad = tmp_path / "bad.yml"
    bad.write_text(yaml.safe_dump({"sites": []}))
    assert main([str(bad)]) == 1


def test_cli_strict_mode_fails_on_warnings(tmp_path):
    config = base_config(sites=[{"name": "x", "slug": "x", "url": "http://x.com"}])
    path = tmp_path / "warn.yml"
    path.write_text(yaml.safe_dump(config))
    assert main([str(path)]) == 0
    assert main([str(path), "--strict"]) == 1
