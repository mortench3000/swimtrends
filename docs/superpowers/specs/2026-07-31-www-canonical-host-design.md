# `www` Canonical Host — Design Spec

- **Date:** 2026-07-31
- **Status:** Approved (design)
- **Follow-up to:** [`2026-07-30-search-indexable-pages-design.md`](2026-07-30-search-indexable-pages-design.md)
  (deferred there because it needs a certificate replacement, which is unrelated
  risk on an SEO PR)

## Context & goal

`www.swimtrends.dk` **does not resolve** — `curl` returns nothing, DNS has no
record. Only the apex is aliased (`swimtrends_web_stack.py`, A + AAAA). Anyone who
types, links, or shares the `www` form reaches a dead site, which is a plausible
way early word-of-mouth links died silently while the site was unindexed.

Goal: `www.swimtrends.dk` resolves and **301-redirects to the apex**, so there is
exactly one canonical host.

## Decisions

**Redirect, not a second copy.** Serving identical content on both hosts is
duplicate content. Every page already carries a `rel=canonical` pointing at the
apex, so Google would consolidate anyway — but a 301 is unambiguous, and it is
what a human sharing a `www` link expects.

**The redirect goes in the existing CloudFront Function**, not a second
distribution or an S3 redirect bucket. The function already runs on viewer-request
for every request; the redirect is ~8 lines and needs no new infrastructure.

Because the function now does two things, it is renamed
`append_index.js` → `viewer_request.js` (construct id `AppendIndex` →
`ViewerRequest`). That replaces the CloudFront Function resource — CloudFormation
creates the new one, repoints the distribution, deletes the old, with no downtime.
Accepted for a name that will still be accurate in six months.

**Query strings are dropped on redirect.** Reconstructing `event.request.querystring`
into a query string is fiddly, and no Swimtrends URL carries parameters — only
inbound `utm_*` tags would be affected, which nothing here consumes. Marked with a
`ponytail:` comment naming the upgrade path.

## The certificate replacement (the actual risk)

`swimtrends_cert_stack.py` issues a cert for `swimtrends.dk` with **no SANs**. A
CloudFront distribution may only serve an alias its viewer certificate covers, so
`www` requires `subject_alternative_names=["www.swimtrends.dk"]` — and adding a SAN
**replaces** the ACM certificate.

Sequence CloudFormation runs, and why it is safe:

1. New cert requested in **us-east-1** (`SwimtrendsCertStack`), DNS-validated —
   `CertificateValidation.from_dns(zone)` writes the new `_xxx` CNAME into the
   existing hosted zone automatically. Validation is typically a few minutes.
2. `SwimtrendsWebStack` updates the distribution to the new cert and adds the
   `www` alias. CloudFront updates are atomic; the old cert keeps serving until
   the update completes.
3. The old certificate is deleted only after nothing references it.

Failure mode: if validation stalls, the cert stack rolls back and the web stack is
never updated — the site keeps serving on the existing cert. **The live site cannot
end up without a valid certificate**, which is what makes this safe to run.

Deploy order is forced by the cross-region reference: cert stack, then web stack.
CDK does this itself when both are named on one `deploy` command.

## Affected files

| File | Change |
| --- | --- |
| `swimtrends-app/swimtrends_app/swimtrends_cert_stack.py` | add `subject_alternative_names=["www.swimtrends.dk"]` |
| `swimtrends-app/swimtrends_app/swimtrends_web_stack.py` | `domain_names=[DOMAIN, WWW]`; A + AAAA alias records for `www`; rename the function construct |
| `swimtrends-app/cloudfront/append_index.js` | **renamed** to `viewer_request.js`, plus the host check and 301 |
| `swimtrends-app/tests/unit/test_cert_stack.py` | assert the SAN |
| `swimtrends-app/tests/unit/test_web_stack.py` | aliases contain both hosts; Route53 record count 2 → **4**; extend the node-driven table with redirect cases |

No web/ changes: `seo.js` already emits apex-absolute canonicals, and the SPA is
served the same either way.

## Verification

1. `cd swimtrends-app && .venv/bin/python -m pytest tests/unit`.
2. `cdk diff` — expect the new cert, the distribution's `Aliases` + certificate
   reference, 2 new record sets, and the function swap. Nothing else.
3. Post-deploy:
   - `curl -sSI https://www.swimtrends.dk/DM-L/12486` → **301** with
     `location: https://swimtrends.dk/DM-L/12486` (path preserved).
   - `curl -sSI https://swimtrends.dk/DM-L/12486` → still **200**, 2585 bytes.
   - `dig +short www.swimtrends.dk` → resolves.
   - TLS valid on both hosts (`curl` fails loudly if not).
4. The Google Search Console TXT record at the apex must survive — it is not CDK
   managed, but confirm with `dig +short TXT swimtrends.dk` afterwards.
