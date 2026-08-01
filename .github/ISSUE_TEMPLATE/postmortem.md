---
name: Postmortem
about: Write up an incident after it is resolved
title: "[Postmortem] "
labels: postmortem
assignees: AlzyWelzy
---

<!--
Blameless. The goal is to find the systemic cause, not the person who typed the
command. Link the automated downtime issue this relates to.

Worth writing one whenever an outage was long, surprising, or silent — an
outage nobody noticed is the most important kind to write up.
-->

## Summary

<!-- Two sentences: what broke, for how long, who was affected. -->

## Impact

- **Services affected:**
- **Duration:**
- **Detected by:** <!-- monitor / watchdog / a human noticing / a user report -->

## Timeline

<!-- UTC. `git log history/<slug>.yml` gives exact state-change times. -->

| Time (UTC) | Event |
| ---------- | ----- |
|            |       |

## Root cause

<!-- The systemic reason. Keep asking "why did that happen?" past the first answer. -->

## Detection

<!--
Be honest here — this is usually where the real lesson is.

- How long between breaking and detecting?
- Did monitoring catch it, or did a human?
- If a check was green while the service was broken, why? A content assertion
  that is too generic will do exactly that.
-->

## What went well

## What to change

<!-- Concrete and owned. "Be more careful" is not an action item. -->

- [ ]
