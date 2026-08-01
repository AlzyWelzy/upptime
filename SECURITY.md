# Security Policy

## Scope

This repository contains the uptime monitoring configuration and public status
page for [rajpoot.dev](https://rajpoot.dev) and related services. It holds **no
application source code and no credentials** — all secrets live in GitHub
Actions secrets and are never committed.

## Reporting a vulnerability

Please report security issues privately — do **not** open a public issue.

- Preferred: [GitHub private vulnerability reporting](https://github.com/AlzyWelzy/upptime/security/advisories/new)
- Alternative: email the maintainer via the contact details on [rajpoot.dev](https://rajpoot.dev)

Please include what you found, how to reproduce it, and the impact you believe
it has. Expect an initial response within 72 hours.

## Reporting an outage

Outages are **not** security issues. The monitor opens an issue automatically
when an endpoint fails a check. If you believe something is down that the status
page reports as up, open a regular issue instead.

## Secrets

If you ever find a credential committed to this repository, treat it as
compromised: report it privately using the process above, and it will be
revoked and rotated rather than merely deleted from the working tree — git
history preserves removed files.
