# Contributing

## Setup

```bash
make install          # creates .venv from requirements-dev.txt
make check            # lint + tests + config validation, same as CI
```

Optionally install the pre-commit hooks so mistakes are caught before they are
committed rather than in CI:

```bash
pip install pre-commit && pre-commit install
```

## Adding a monitor

Add an entry under `sites:` in [`.upptimerc.yml`](./.upptimerc.yml):

```yaml
- name: example.com
  slug: example-com
  url: https://example.com
  maxResponseTime: 3000
  expectedStatusCodes:
    - 200
  __dangerous__body_down_if_text_missing: "Example Domain"
  maxRedirects: 3
  connectTimeout: 10 # seconds
  requestTimeout: 30 # seconds
```

Then verify it actually works before opening a PR:

```bash
make validate         # schema, slugs, URL form, cron, secrets
make http             # probes the real endpoint from your machine
```

Rules that are easy to get wrong:

- **Always set `slug` explicitly.** Without it the slug is derived from `name`,
  so a later rename orphans the recorded history and `update-template` prunes it.
- **Verify the content assertion against the live response.** Never guess a
  string. `make http` fails loudly if it is absent.
- **`check: ssl` takes a bare hostname**, not a URL — the value is passed
  straight through as a socket host. `make validate` catches this.

## Adding a notification channel

Two steps, and skipping either fails silently:

1. Add the secret names to the `secrets:` allowlist in `.upptimerc.yml`. The
   list is exhaustive — anything missing is invisible to the workflow.
2. Add the secrets themselves under Settings → Secrets and variables → Actions,
   **including the provider's on-switch** (`NOTIFICATION_TELEGRAM`,
   `NOTIFICATION_EMAIL_SMTP`, …). Credentials without the switch do nothing.

## Editing workflows

Only [`.github/workflows/validate.yml`](.github/workflows/validate.yml) is safe
to hand-edit. The other eight are generated from `.upptimerc.yml` and are
deleted and rewritten by `update-template`. See
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

Third-party actions in `validate.yml` are pinned to a **commit SHA** with the
version in a trailing comment. Tags are mutable; pin new actions the same way:

```bash
curl -s https://api.github.com/repos/OWNER/REPO/git/ref/tags/v1 | jq -r .object.sha
```

## Before opening a PR

`make check` must pass. CI runs lint, formatting, the test suite, and config
validation on every PR that touches config, scripts, or tests.

Changes to the validator need a test. The suite lives in
[`tests/test_validate_config.py`](tests/test_validate_config.py) and includes a
case asserting this repository's real config stays valid.

## Operations

For what to do when something is actually down, see
[docs/RUNBOOK.md](docs/RUNBOOK.md).
