# Kinetix — OWASP ZAP security report

**Scan date:** 26 October 2026. **Publication:** 27 October 2026. **Status:** local passive assessments completed; team review and current-delivery confirmation pending.

## Applicability and scope

The project exposes an HTTP API, interactive Swagger web documentation and an Expo browser preview, so the OWASP ZAP analysis section applies. Android/iOS remain the documented client delivery targets; complete web-client support is not committed.

Three assessments were performed with **ZAP 2.17.0**: an unauthenticated baseline of the Expo development server, an unauthenticated baseline of API documentation, and a follow-up inspecting authenticated API reads. [Method and commands](method.md) describe how each was run. This branch publishes those results; it does not claim a new scan of the branch itself.

| Assessment | Surface | Authentication and technique | High | Medium | Low | Informational |
|---|---|---|---:|---:|---:|---:|
| Web baseline | Expo preview, port 8081 | Unauthenticated; traditional spider and passive checks | 0 | 2 | 5 | 2 |
| Documentation baseline | FastAPI `/docs`, port 8000 | Unauthenticated; traditional spider and passive checks | 0 | 3 | 6 | 2 |
| API follow-up | Temporary development API, port 8002 | Two Basic accounts; 39 explicit GET requests through ZAP; passive checks | **1** | **1** | **1** | 0 |

Counts are distinct alert references per assessment, not confirmed exploits or vulnerable endpoints. An alert can appear in more than one assessment; do not sum the columns into a count of unique vulnerabilities. The baseline scripts reported 5 web and 7 documentation warning rule groups with exit code 2; rule groups are different from alert-reference and severity counts. Informational entries are observations rather than vulnerabilities.

## Findings, corrections and unresolved status

| ZAP finding | Severity | Observed surface | Interpretation and proposed correction | Correction made / current status / reason |
|---|---|---|---|---|
| `10105-1` Authentication Credentials Captured | High | Authenticated API | Basic Authorization headers were visible to the deliberately configured proxy on local HTTP. Basic encoding provides no encryption. Use HTTPS and the intended release authentication; keep development access restricted. This does not demonstrate external interception or compromise. | **None; open in development.** HTTP and Basic were intentionally selected for this assessment. Production code prohibits Basic; deployed authentication and HTTPS remain unverified. |
| `10105-2` Weak Authentication Method | Medium | Authenticated API | The service advertises Basic Auth. Retain the production prohibition and verify the deployed Clerk configuration. | **None; development triage pending team review.** Basic is the requested development mode; this does not justify globally suppressing the rule. |
| `10038-1` CSP Header Not Set | Medium | Web preview and documentation | Define and test a Content Security Policy compatible with the delivered application and Swagger resources. | **None; open.** Hosting policy and compatibility have not been changed or verified. |
| `10020-1` Missing Anti-clickjacking Header | Medium | Web preview and documentation | Apply CSP `frame-ancestors` and compatible `X-Frame-Options` where framing is unnecessary. | **None; open.** Application/hosting configuration and a confirming rescan are needed. |
| `90003` Sub Resource Integrity Attribute Missing | Medium | Documentation | Swagger's CDN CSS/JavaScript lack integrity attributes. Review production documentation exposure; self-host pinned assets or use verified integrity metadata. | **None; open.** Documentation exposure and asset-delivery policy remain for review. |
| `10021` X-Content-Type-Options Header Missing | Low | Documentation and authenticated API | Set `X-Content-Type-Options: nosniff` consistently, including error responses. | **None; open.** Observed in both relevant assessments; no fix or post-fix rescan performed. |
| `10017` Cross-Domain JavaScript Source File Inclusion | Low | Documentation | Swagger loads external CDN JavaScript. Review trust, pinning, integrity and CSP together; the alert does not prove compromised code. | **None; review pending.** External-asset policy was not changed. |
| `90004-1`, `90004-2`, `90004-3` Missing/invalid CORP, COEP and COOP headers | Low | Web preview and documentation | Review browser isolation against media and identity flows before enforcing headers. | **None; review pending.** Release compatibility was not assessed. |
| `10063-1` Permissions Policy Header Not Set | Low | Web preview and documentation | Define browser capability permissions compatible with camera and other required features. | **None; review pending.** Required release capabilities need validation. |
| `2` Private IP Disclosure | Low | Expo development JavaScript bundle | A private network address was present in the development bundle. Use a release bundle and rescan; the address is redacted in published evidence. | **None; unresolved in preview.** Production applicability is unverified. |

**Corrections made: none.** The task produced analysis and reporting. Existing protections are not presented as fixes resulting from ZAP. Team acceptance, owners and remediation deadlines have not been recorded.

Informational observations were `10109` Modern Web Application, `10049-3` Storable and Cacheable Content on the documentation surface, and `10049-1` Non-Storable Content on the preview. Cache observations on public documentation do not establish exposure of private data.

## Authentication and sampled authorization results

| Check | Observed result | Conclusion and limit |
|---|---|---|
| Two existing accounts call `/api/v1/me` | 200 for both; different account IDs | Authentication succeeded for both; identifiers omitted from publication. |
| No credentials and wrong password per account | Three 401 responses | Negative authentication checks passed for the tested requests. |
| Existing Account 1 food read by owner and Account 2 | Owner: 200; other account: 404 | One sampled cross-account food read was correctly denied. |
| Additional food/routine/session isolation | Five directional checks skipped because no existing resource was available | Full isolation coverage is not established; no records were created to fill gaps. |
| Invalid exercise pagination | 422 for both accounts | Input-boundary rejection observed. |
| All 39 follow-up requests | 30 × 200; 3 × 401; 4 × 404; 2 × 422; no 5xx | Optional missing resources explain the other 404s. This is a bounded read-only sample. |

[Verification evidence](evidence/authenticated/verification.json) records route templates, status codes and skipped cases without account identities or payloads. Both accounts already existed and were active before requests were made, avoiding first-login provisioning. The passive queue reached zero before export.

## Version identity and evolution

| Assessment | Backend HEAD | Frontend HEAD | Working-tree state |
|---|---|---|---|
| Initial baselines | `032d4129e5472fa54d0d8a61a9400e3a6f2072bb` | `73db14efc31410289160dba1d3d06885f5f89dcf` | Both contained uncommitted changes. |
| Authenticated follow-up | `03183b5f42b3f8645231e55221a6e6206309d7ba` | `86d9629d5f9ba2e2138af443cd07fccbb61b3dac` | Both marked dirty; frontend was not rescanned. |

These identify local scan context, not immutable release builds. The sprint number and delivery reference were not supplied. **The mandatory requirement to analyse the current delivered version is not yet confirmed.** Match this evidence to the delivered source/configuration or rerun against the release build.

The follow-up expanded coverage and used a later working revision. Its authentication findings are newly observed through expanded traffic; they are not demonstrated regressions. No fix is claimed. No prior-sprint ZAP report was found in inspected local documentation. For Sprints 2 and 3, compare alert reference plus affected surface with the preceding sprint and present new, persistent and resolved items; count a correction only after a confirming rescan.

## Coverage limits and evidence

The assessments did not execute active attacks, writes, uploads, destructive operations, complete object-level authorization, browser sign-in, native-client analysis, Clerk validation or production TLS testing. The follow-up used API requests rather than a signed-in browser; it did not comprehensively exercise all OpenAPI operations. No service/data modifications were made as remediation.

| Evidence | Published files |
|---|---|
| Web baseline | [HTML extract](evidence/web/report.html), [JSON metadata](evidence/web/report.json), [scanner summary](evidence/web/scan.log), [scope](evidence/web/scope.json) |
| Documentation baseline | [HTML extract](evidence/api/report.html), [JSON metadata](evidence/api/report.json), [scanner summary](evidence/api/scan.log), [scope](evidence/api/scope.json) |
| Authenticated API | [HTML extract](evidence/authenticated/report.html), [JSON metadata](evidence/authenticated/report.json), [request verification](evidence/authenticated/verification.json), [scope](evidence/authenticated/scope.json) |
| Publication integrity | [Sanitization provenance](evidence/provenance.json), [checksums](SHA256SUMS) |

Published HTML is regenerated from sanitized ZAP metadata, not an untouched native export. Credentials, personal bodies, dynamic evidence, query strings and concrete resource IDs are excluded. Alert classifications and counts are preserved.

[Presentation and document text](presentation.md) provides wording ready to adapt without implying completed remediation or production assurance.
