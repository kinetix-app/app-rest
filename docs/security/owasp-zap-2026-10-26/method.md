# Employed method and reproduction

Scans were performed on **26 October 2026**; documentation was prepared for publication on **27 October 2026**. Reproduction requires a running target and the same intended authentication configuration. A new run can produce different results as code, data, rules or configuration change.

## Tool and test design

The scanner was **OWASP ZAP 2.17.0**, using this exact Docker image:

```text
ghcr.io/zaproxy/zaproxy@sha256:030d3df57735dacbb83464854758e674dd9ad01d79d12a129a8e58b1fd384238
```

ZAP's passive scanner inspects traffic without generating active attack payloads. The initial packaged baseline scans used a traditional spider to discover public pages. The authenticated follow-up instead sent explicit API GET requests through ZAP's proxy. Authentication/access checks were scripted request checks; they are distinguished from ZAP's passive alert detection in the [results](report.md).

No SonarQube/static-analysis result is presented as ZAP evidence. ZAP did not establish complete coverage of the OWASP Top 10.

## Initial unauthenticated baselines

The running processes were checked to originate from the frontend/backend workspace directories. Reachability was verified from inside the Docker runtime using `host.docker.internal`. Separate containers and output directories were used for each target; no scanner port was published to the host.

Create separate writable report directories, then run these commands on Docker Desktop. The two commands represent the scans actually performed; the paths below show how to mount equivalent output directories for reproduction.

```sh
mkdir -p /tmp/kinetix-zap-web /tmp/kinetix-zap-api

docker run --rm \
  -v /tmp/kinetix-zap-web:/zap/wrk:rw \
  ghcr.io/zaproxy/zaproxy@sha256:030d3df57735dacbb83464854758e674dd9ad01d79d12a129a8e58b1fd384238 \
  zap-baseline.py -t http://host.docker.internal:8081 \
  -m 1 -T 3 --autooff -r report.html -J report.json -s

docker run --rm \
  -v /tmp/kinetix-zap-api:/zap/wrk:rw \
  ghcr.io/zaproxy/zaproxy@sha256:030d3df57735dacbb83464854758e674dd9ad01d79d12a129a8e58b1fd384238 \
  zap-baseline.py -t http://host.docker.internal:8000/docs \
  -m 1 -T 3 --autooff -r report.html -J report.json -s
```

`-m 1` limits spider duration; `-T 3` configures the packaged wait limit and is not a strict wall-clock bound. `--autooff` selects the legacy packaged execution path. `-r` and `-J` request HTML/JSON exports. Both scans exited **2**, indicating warnings. No explicit rule suppression was configured. The API baseline crawled documentation; it did not import OpenAPI or comprehensively scan authenticated business endpoints. The web baseline did not use an AJAX/browser spider.

## Authenticated API follow-up

1. Inspect backend settings without printing credentials. The `.env` contained two Basic accounts, while the existing API on port 8000 used Clerk.
2. Start a temporary API process from the same backend source with a process-local authentication override:

   ```sh
   AUTH_MODE=basic uv run --locked --no-build uvicorn app.main:create_app \
     --factory --host 127.0.0.1 --port 8002 --no-access-log
   ```

   The executed run used the already installed repository virtualenv's Uvicorn directly; the command above uses the equivalent locked repository wrapper. The `.env` and the port-8000 process were not changed. Other settings came from the existing development configuration.
3. Start ZAP in daemon/proxy mode, with its API bound to container loopback and no published ports:

   ```sh
   docker run -d --rm --name kinetix-zap-auth-report \
     -e JAVA_TOOL_OPTIONS=-Xmx512m \
     ghcr.io/zaproxy/zaproxy@sha256:030d3df57735dacbb83464854758e674dd9ad01d79d12a129a8e58b1fd384238 \
     zap.sh -daemon -host 127.0.0.1 -port 8090 \
     -config api.disablekey=true -config database.recoverylog=false
   ```

   The keyless API was reachable only within this disposable container; do not expose this configuration to other systems.
4. A host-side Python driver read `BASIC_AUTH_USERS` from `.env`, verified that the selected identities already existed and were active using a read-only database query, and passed the two credentials to a container-side request driver over standard input. Credentials were not placed in command arguments or output files. No third-party identity provider received these credentials.
5. The request driver ran inside the ZAP container. It sent requests to `http://host.docker.internal:8002` using a Basic Authorization header and the proxy `http://127.0.0.1:8090`. Redirect following was disabled. The OpenAPI document was read to enumerate GET routes; it was not imported into a packaged API scan that could issue writes.
6. Read parameter-free `/api/v1` GET routes for each authenticated account. Add the current nutrition-day read, available exercise/food detail reads, exercise last-configuration reads, invalid pagination, missing credentials and wrong-password checks. Existing list data supplied resource IDs in memory. Where an existing food was available, repeat its read with the other account; log skipped isolation cases when data was absent. No records were created, edited or deleted.
7. Verify 200 responses and distinct internal account IDs for the two `/me` calls. Record only account aliases, route templates and statuses. Of **39 requests**, 30 returned 200, 3 returned 401, 4 returned 404 and 2 returned 422; none returned 5xx. [The verification file](evidence/authenticated/verification.json) is the exact retained request matrix.
8. Wait for ZAP's `pscan/view/recordsToScan` queue to reach zero, then export its JSON alert report. No active scanner or authenticated browser spider was run. Extract alert metadata without personal payloads or authorization headers. Shut down the temporary API and remove the disposable scanner container after export.

The authenticated Python drivers were temporary assessment tooling, not a committed regression harness. This description records their operation; the branch does not provide a one-command automated replay of those 39 requests. Repeating the checks requires equivalents using available test-owned resources and the same explicit coverage matrix.

## Evidence handling and interpretation

Raw local exports were retained outside tracked content. Publication uses allowlisted ZAP metadata fields and regenerated HTML extracts. Concrete IDs and dates in request paths become route templates; query strings, request/response bodies, headers, dynamic alert evidence and otherinfo are omitted. Private addresses and email-like identifiers are redacted. Authenticated artifacts use Account 1/2 aliases. The number of alert references, their risks and reported instance counts are unchanged.

The High finding resulted from ZAP observing deliberately supplied Basic credentials over local HTTP, not from demonstrating an external compromise. Missing headers were detected from response traffic. The negative authentication and sampled cross-account result came from the explicit requests, not from a claim that passive ZAP scanning proves authorization correctness.

The source hashes in [provenance](evidence/provenance.json) identify original local JSON inputs; [SHA256SUMS](SHA256SUMS) covers the published documents and sanitized evidence. Sanitization removes sensitive details, so public artifacts cannot independently reproduce private payload comparisons. The distinct-account comparison is retained as a boolean verification result.

For a stronger delivery assessment, identify the release build, test authenticated browser navigation, and run active API tests only against an isolated instance with disposable records and a database ending in `_test`. Then rescan corrections and obtain team review. These steps are pending, not results of this assessment.

## Official tool references

- [ZAP baseline behaviour, options and exit codes](https://www.zaproxy.org/docs/docker/baseline-scan/)
- [ZAP API scanning and safe mode](https://www.zaproxy.org/docs/docker/api-scan/)
- [ZAP authentication](https://www.zaproxy.org/docs/desktop/start/features/authentication/)
- [ZAP Automation Framework](https://www.zaproxy.org/docs/automate/automation-framework/)
