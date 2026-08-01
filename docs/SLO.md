# Service Level Objectives

Targets live in [`slo.yml`](../slo.yml). Run `make slo` for the current report.

## Why error budgets

"99.2% uptime" doesn't tell you whether to act. An error budget converts the
target into a concrete allowance of downtime and reports how much is left:

```text
monitor                           target   actual      budget left   status
rajpoot.dev                       99.90%  100.00%       43m of 43m   ok
blog.rajpoot.dev                  99.00%  100.00%     7.2h of 7.2h   ok
```

Budget remaining is the number worth watching. Plenty left means you can take
risks — deploy on a Friday, do the migration. Nearly exhausted means stop
shipping and spend the time on reliability instead.

## Current targets

| Monitor                | Target  | Downtime allowed / 30 days |
| ---------------------- | ------- | -------------------------- |
| `rajpoot.dev`          | 99.9%   | ~43 minutes                |
| `www.rajpoot.dev`      | 99.9%   | ~43 minutes                |
| `scorefit.net`         | 99.5%   | ~3.6 hours                 |
| `blog.rajpoot.dev`     | 99%     | ~7.2 hours                 |
| `pacestreak.net`       | 0%      | not launched — see below   |
| All TLS certificates   | 100%    | none                       |

Everything unlisted uses the `default` in `slo.yml` (99%).

## Choosing a target

Two failure modes, and the second is the common one:

- **Too low** — you never act, and the objective is decorative.
- **Too high** — every blip is a breach, you learn to ignore breaches, and the
  objective is decorative again. 100% is not a target, it is a wish; it leaves
  no budget for deploys, dependency outages, or DNS.

A target you are not willing to be woken up for is not an objective. Set the
number where you would genuinely change behaviour, and revise it when you find
you're ignoring it.

Two deliberate exceptions here:

- **TLS certificates are 100%.** They are binary — a valid certificate or a
  browser interstitial for every visitor. There is no meaningful partial
  credit, so there is no budget to spend.
- **`pacestreak.net` is 0%.** The domain has no DNS records yet, so the monitor
  is permanently down by design. A realistic target would make it the loudest
  entry in every report and train you to ignore the report. Raise it to a real
  number when the domain goes live.

## Caveats on the numbers

- Uptime is computed from Upptime's check history. Checks run from GitHub's
  US-based runners, so a region-specific outage may not register.
- GitHub throttles scheduled workflows on public repositories — the `*/5` cron
  is a ceiling, not a promise. Coarser sampling means short outages can be
  missed entirely, so treat these figures as *approximate*, biased optimistic.
- Percentages cover only the period with recorded history. A window longer than
  the data will read better than reality.

Follow up a breach with a [postmortem](../.github/ISSUE_TEMPLATE/postmortem.md).
