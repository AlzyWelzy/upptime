# Incident Runbook

What to do when something goes red. Ordered by what is most likely to be
actually wrong, based on failures this repository has already had.

## 0. Is it really down?

The monitors run from GitHub's US-based runners. Before assuming an outage,
check from your own machine:

```bash
make probe        # every monitor: status, latency budget, content assertion, TLS
make http         # HTTP endpoints only
make tls          # certificate expiry only
```

If `make probe` is green but the status page is red, the problem is the
monitoring pipeline, not the service — skip to [The pipeline is broken](#the-pipeline-is-broken).

## 1. A service is genuinely down

1. The monitor opens a GitHub issue automatically and assigns it. That issue is
   the incident record — keep the running commentary in it.
2. Check the response in `history/<slug>.yml`: `status`, `code` and
   `responseTime` are committed on every state change, so `git log` on that file
   is a precise outage timeline.
3. If you know it will be down for a while, open a
   [Scheduled maintenance](../.github/ISSUE_TEMPLATE/maintainance-event.md)
   issue so the status page shows a maintenance window instead of a bare outage.
4. Recovery closes the issue automatically. Don't close it by hand — that
   desynchronises the status page.

### It returns HTTP 200 but is broken

That is exactly what the content assertions exist for. If a monitor is green
while the page is visibly broken, its
`__dangerous__body_down_if_text_missing` string is either absent or too generic.
Pick a string that only appears when the page has genuinely rendered, verify it
against the live response, and confirm with `make http`.

## 2. A TLS certificate is expiring

`check: ssl` monitors flip to **down** when a certificate has **less than 7
days** left. There is no earlier warning tier, so treat this as urgent.

```bash
make tls          # shows exact expiry dates and days remaining
```

For Let's Encrypt (which renews at 30 days), reaching 7 means automatic renewal
has already failed several times. Look at the issuing host's renewal timer, not
at this repository.

## The pipeline is broken

Symptom: the status page shows **"An error occurred in trying to get the latest
status details"**, or the numbers are stale.

The status page fetches `api/` and `history/summary.json` from raw GitHub at
page load. If those files are missing or stale, the page errors even though
every service is fine.

Work down this list:

### Are the data files there?

```bash
curl -sI https://raw.githubusercontent.com/AlzyWelzy/upptime/master/history/summary.json
```

A 404 means Uptime CI has not successfully committed. Continue.

### Is Uptime CI failing?

Actions → Uptime CI. Check *which step* fails — this matters:

| Failing step            | Cause                                                        |
| ----------------------- | ------------------------------------------------------------ |
| `Checkout`              | Token problem. See below — this is the common one.            |
| `Check endpoint status` | A genuine outage, or a malformed config.                      |
| Push/commit at the end  | Workflow permissions are read-only.                           |

### `Checkout` is failing

Every generated workflow checks out with:

```yaml
token: ${{ secrets.GH_PAT || github.token }}
```

If `GH_PAT` is **set but expired or revoked**, that expression still prefers it
over the perfectly good `github.token`, and *every* workflow dies at Checkout at
once. This has happened here before.

Fix: Settings → Secrets and variables → Actions. Either delete `GH_PAT`
entirely (the fallback works) or regenerate it with `repo` + `workflow` scope.
PATs expire — a working setup that breaks on a quiet day is usually this.

### Everything runs but nothing appears

- Settings → Actions → General → Workflow permissions must be **Read and write**.
- Settings → General → Features → **Issues** must be enabled. Forks disable
  issues by default, and Upptime's entire incident model is GitHub issues.

### The page renders but the branding is stale

`gh-pages` is rebuilt by **Static Site CI**, which only runs daily (`0 1 * * *`).
Config changes do not appear until it runs. Trigger it manually rather than
waiting.

### Recovery order

Once the underlying cause is fixed, run these in order via *Run workflow*:

1. **Uptime CI** — writes `history/*.yml`; everything depends on it
2. **Summary CI** — writes `history/summary.json` and the README table
3. **Response Time CI** and **Graphs CI** — populate `api/` and `graphs/`
4. **Static Site CI** — rebuilds and deploys `gh-pages`

## Notifications did not fire

Each provider needs an explicit **on switch** secret in addition to its
credentials — credentials alone are a silent no-op:

- Telegram: `NOTIFICATION_TELEGRAM` **and** `NOTIFICATION_TELEGRAM_BOT_KEY`, `NOTIFICATION_TELEGRAM_CHAT_ID`
- Email: `NOTIFICATION_EMAIL_SMTP` **and** the SMTP host/port/user/password, `NOTIFICATION_EMAIL_FROM`/`_TO`

A secret that is not in the `secrets:` allowlist in `.upptimerc.yml` is invisible
to the workflow even if it exists in repository settings. The allowlist is
exhaustive. `make validate` catches credentials-without-switch.

## Checks stopped running on schedule

GitHub throttles `schedule` triggers on public repositories. A `*/5` cron is a
ceiling, not a promise — hourly is normal in practice. GitHub also disables
scheduled workflows entirely after 60 days of repository inactivity; the daily
commits from the monitor normally prevent that.
