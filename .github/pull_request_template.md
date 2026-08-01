## What does this change?

<!-- Adding a monitor? Changing a threshold? Updating the status page? -->

## Checklist

- [ ] `.upptimerc.yml` changes pass **Validate Config** (runs automatically)
- [ ] New monitors have an explicit `slug` — without one, a later rename orphans the recorded history
- [ ] New HTTP monitors use a full `https://` URL; new `check: ssl` monitors use a **bare hostname**
- [ ] Any content assertion (`__dangerous__body_down_if_text_missing`) was verified against the live response, not assumed
- [ ] New notification secrets are added to the `secrets:` allowlist **and** to repository secrets — the allowlist is exhaustive
- [ ] No workflow in `.github/workflows` was hand-edited except `validate.yml` — the rest are generated from `.upptimerc.yml`

## Notes

<!-- Anything a reviewer should know: expected downtime, DNS changes, cert work -->
