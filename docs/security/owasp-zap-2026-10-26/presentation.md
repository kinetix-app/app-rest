# Text for the sprint presentation and document

Use the sprint's actual number and delivery reference when known. Assessment date: **26 October 2026**. The local assessment is completed; delivery correspondence and team review remain pending. The following text deliberately preserves those limits.

## Suggested slide 1 — Scope, method and evidence

**OWASP ZAP analysis — Kinetix**

- Tool: ZAP 2.17.0 in Docker, with the exact scanner image recorded.
- Public baseline: Expo browser preview and FastAPI documentation; traditional crawling and passive analysis.
- Authenticated follow-up: two existing development Basic accounts; 39 GET requests through ZAP.
- Evidence: sanitized HTML/JSON alerts, request results, version context and checksums.
- Scope limit: local development assessment; no active attacks or complete production verification.

| Assessed surface | High | Medium | Low | Informational |
|---|---:|---:|---:|---:|
| Web preview baseline | 0 | 2 | 5 | 2 |
| API documentation baseline | 0 | 3 | 6 | 2 |
| Authenticated API follow-up | 1 | 1 | 1 | 0 |

*Counts represent alert types per assessment; do not sum them as unique vulnerabilities.*

## Suggested slide 2 — Findings, corrections and remaining work

| Relevant result | Current status / reason |
|---|---|
| High: Basic credentials visible in local HTTP traffic | Open in development; deliberately configured proxy observed test credentials. No external compromise demonstrated. Verify HTTPS and release authentication. |
| Medium: Basic Auth, missing CSP/framing protections and Swagger asset integrity | Basic is development-only; other findings remain open pending configuration/asset review. |
| Low: missing response/browser headers and private IP in development bundle | Open or pending release-environment review; no corrections made. |
| Authentication and one sampled ownership check | Both accounts signed in; invalid credentials returned 401; one cross-account food read returned 404. Broader isolation remains unverified. |
| Evolution and completion limits | New authentication alerts came from expanded coverage, not proven regression. Team review, delivery identity and confirming scans remain pending. |

**Corrections made during the assessment: none.** Existing safeguards are not claimed as new fixes.

## Speaker text — approximately one minute

> We performed an OWASP ZAP analysis of Kinetix on 26 October. First, we scanned the web preview and API documentation without authentication. We then extended coverage using two existing development accounts and sent 39 read requests through ZAP. Both accounts authenticated, incorrect credentials were rejected, and one sampled attempt to read another account's food was denied. The authenticated analysis produced one high, one medium and one low alert type. The high alert concerns Basic credentials sent over local HTTP; our deliberately configured proxy could see them, which does not demonstrate an external compromise. Other findings concern browser protection headers and Swagger's external assets. No corrections were made during the assessment, so the relevant items remain open or pending review. We retained sanitized evidence and documented the limits: production authentication, HTTPS, full authorization and the correspondence with the delivered version still need verification.

## Document-ready section

Kinetix includes HTTP/web components, so an OWASP ZAP security analysis is applicable. The analysis was performed on 26 October 2026 with ZAP 2.17.0 in Docker. Initial unauthenticated baseline scans inspected the Expo browser preview and FastAPI documentation using a traditional spider and passive response analysis. An authenticated follow-up inspected 39 explicit GET requests using two existing development Basic Auth accounts. The requests traversed ZAP's proxy, and the passive queue was empty before report export. The assessment did not execute active attacks or modify development records.

The web baseline reported two Medium and five Low alert types; the documentation baseline reported three Medium and six Low alert types. Neither baseline reported High alerts. The authenticated follow-up reported one High alert for credentials visible in Basic Authorization headers over local HTTP, one Medium alert for Basic authentication and one Low alert for missing MIME-sniffing protection. These are scanner classifications, not counts of confirmed exploits. The High alert relates to the intentionally selected development setup; the test proxy was placed in the traffic path. It does not establish an external credential compromise. Other relevant findings concern absent CSP/framing protections, Swagger CDN asset integrity, browser headers and a private address in the development bundle.

Both authenticated accounts returned successful `/me` responses and resolved to distinct identities. Missing or incorrect credentials were rejected with 401. An existing food returned 200 for its owner and 404 for the other account. Further directional isolation checks were skipped where existing resources were unavailable. Across all 39 requests there were no server errors. These sampled results do not establish comprehensive authorization correctness.

No corrections were implemented during this analysis. Development authentication findings remain for contextual team review; header and asset findings remain open pending correction and a confirming rescan. Production authentication/TLS, browser sign-in and full authorization coverage were not assessed. The inspected local revisions and their working-tree state are recorded, but correspondence with the sprint's delivered version has not been confirmed. Team review, remediation ownership and delivery-version confirmation remain required. The authenticated findings reflect expanded coverage and must not be presented as demonstrated regressions. No previous-sprint baseline was available for a supported historical comparison.

Evidence and full results: [security report](report.md), [employed method](method.md), [sanitized authenticated alerts](evidence/authenticated/report.html), [request verification](evidence/authenticated/verification.json).

## What to update for Sprint 2 or 3

Compare alert reference and affected surface with the previous sprint. Show new, persistent and resolved findings with correction evidence and a reason for every unresolved item. Keep common method details linked rather than repeating them. Do not claim remediation until a rescan confirms it, and do not present changed coverage as proof of a regression.
