# OWASP ZAP assessment — 26 October 2026

Publication prepared on 27 October 2026. These are results from the earlier local scans; publication does not represent a new scan of this branch.

| Document | Purpose |
|---|---|
| [Security report](report.md) | Scope, severity tables, findings, corrections, unresolved status and coverage limits |
| [Method and reproduction](method.md) | How findings were obtained, scanner commands, authentication and evidence handling |
| [Presentation and document text](presentation.md) | Two suggested slides, speaker text and a report paragraph ready to adapt |
| [Evidence](evidence/) | Sanitized alert metadata, HTML extracts, request verification and scan context |
| [Checksums](SHA256SUMS) | SHA-256 checksums of published documents and evidence |

The authenticated follow-up inspected 39 GET requests with two existing development accounts. Its three alert types were **one High, one Medium and one Low**. The High alert concerns Basic credentials sent over local HTTP; it does not demonstrate an external compromise. No corrections were implemented. Team review and confirmation that the assessed source matches the sprint delivery remain pending.

Credentials, personal response bodies and raw captured traffic are excluded. Evidence counts retain the scanner's classifications; the HTML files are regenerated sanitized extracts. See [provenance](evidence/provenance.json) for the transformation and hashes of the original local JSON artifacts.
