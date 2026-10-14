---
name: sonarqube-issues
description: Retrieve and fix SonarQube or SonarCloud issues for this repository, then verify the results.
---

# Fix Sonar issues

Use the source selected by the user or established in the conversation. Ask local vs Cloud only when neither is specified. Reviewing this skill or its scripts does not require a scan.

## Retrieve

Run from the repository root. Credentials come from `.env`: local needs `SONAR_TOKEN`; Cloud needs `SONAR_CLOUD_TOKEN` and `SONAR_ORGANIZATION`. Never print tokens or `.env` contents.

For local SonarQube, analyze the current checkout first:

```sh
./scripts/sonar-scan.sh
```

The scan runs tests with coverage, waits for SonarQube processing, and saves unresolved findings to `/tmp/sonar-issues.json`. Set `SONAR_ISSUES_OUTPUT` to change the path. Use the repository's required uv version; see [README.md](../../../README.md). If execution is blocked, report the failed command and required access; do not interpret permission errors as a stopped server.

For SonarCloud:

```sh
python3 scripts/fetch_sonar_issues.py --source cloud --output /tmp/sonar-issues.json
```

Select the context matching the checkout: default is the server's main branch; add `--branch NAME` or `--pull-request NUMBER` when needed. Use the same source, project and context for verification.

Use only the shared [Python extractor](../../../scripts/fetch_sonar_issues.py). Consume its JSON only after exit code 0. On pagination or duplicate-key errors, stop and retry after the server is stable. CLI details are in [README.md](../../../README.md#retrieving-sonar-issues).

## Fix and verify

1. Inspect findings in JSON order, referenced code and rule context. Track issue keys; verify paths and stale line numbers against the checkout.
2. Fix applicable findings while preserving user changes and behavior. Do not suppress rules or add exclusions to hide issues. Explain stale or false-positive findings.
3. Run relevant tests and repository checks. For local SonarQube, repeat the scan and extraction; compare issue keys to confirm fixes and detect new findings. Investigate persistent findings before another attempt.
4. Report fixed and remaining findings, validation and blockers. Cloud fixes need a subsequent Cloud analysis before their removal can be confirmed.
