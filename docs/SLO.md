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

[`slo.yml`](../slo.yml) is authoritative — this table describes the *tiers*, so
that it stays true as monitors are added. Run `make slo` for the live per-monitor
numbers.

| Tier                        | Target | Downtime allowed / 30 days |
| --------------------------- | ------ | -------------------------- |
| Primary site (apex and www) | 99.9%  | ~43 minutes                |
| ScoreFit                    | 99.5%  | ~3.6 hours                 |
| Blog                        | 99%    | ~7.2 hours                 |
| Vanity redirect domains     | 99%    | ~7.2 hours                 |
| TLS certificates            | 100%   | none — see below           |
| Not-yet-launched domains    | 0%     | none at present — see below |

Anything without an explicit entry uses the `default` in `slo.yml` (99%).
`validate_config.py` fails the build on a target whose slug matches no monitor,
and warns about a monitor with no target — so the two files cannot drift apart
without CI saying so.

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
- **Not-yet-launched domains sit at 0%.** A monitor that is red by design would
  otherwise be the loudest entry in every report and train you to ignore the
  report. There are none at present — `pacestreak.com` launched on 2026-08-28
  and now carries a real 99% target.

## Caveats on the numbers

- Uptime is computed from Upptime's check history. Checks run from GitHub's
  US-based runners, so a region-specific outage may not register.
- GitHub throttles scheduled workflows on public repositories — the `*/5` cron
  is a ceiling, not a promise. Coarser sampling means short outages can be
  missed entirely, so treat these figures as *approximate*, biased optimistic.
- Percentages cover only the period with recorded history. A window longer than
  the data will read better than reality.

Follow up a breach with a [postmortem](../.github/ISSUE_TEMPLATE/postmortem.md).
