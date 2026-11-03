# Backend conventions

These rules supplement [AGENTS.md](../AGENTS.md). Use [README.md](../README.md) for commands, configuration, supported versions and current feature coverage; inspect implementation for task status. Follow `.python-version`, `pyproject.toml`, `uv.lock`, Docker/Compose and CI pins rather than duplicating versions here.

## Structure and persistence

- Use FastAPI, SQLAlchemy async with asyncpg, Alembic, Pydantic v2 and typed settings. Features live under `app/features/`; compose business routes under `/api/v1`. Keep routers thin, use-case and transaction logic in services, and reused complex queries in focused modules.
- Define expected use-case exceptions in each feature's `errors.py`, independent of HTTP transport. Services raise domain exceptions; routers translate them to the existing HTTP status and message contracts.
- Keep ORM models and create/update/private/public response schemas distinct. Validate bounds, output visibility, errors and PATCH omission/null semantics in schemas/services.
- Account IDs are generated BIGINTs. Use VARCHAR for enum-like categories and VARCHAR[] for multiple classifications; document intended values in SQL comments and mark unresolved vocabularies as proposed. Do not introduce PostgreSQL ENUM types for them.
- Add manually reviewed Alembic revisions in `migrations/versions/` and import feature models in `migrations/env.py`. Use inline PRIMARY KEY, REFERENCES, NOT NULL and UNIQUE declarations. Avoid named CONSTRAINT clauses and business-rule CHECKs in the schema draft; validate bounds, states and ownership in schemas/services. Preserve existing migrated account constraints until an explicit follow-up migration changes them. Verify clean setup and applicable upgrades.
- Use deterministic nutrition, league and progress calculations with documented precision/rounding, explicit units and timezone-aware events. Separate templates, completed activities and membership; reuse activity references and preserve community-copy provenance.

## Identity and asynchronous resources

- Load settings once in `create_app`; launch Uvicorn with `app.main:create_app --factory`. Inject identity, settings and sessions. Create/dispose pooled resources through application lifespan.
- Use one session per request/use case and a separate session for each concurrent task. Explicitly load relationships required for serialization. Services define successful commit and failure rollback boundaries. Await asynchronous I/O; move blocking computation behind an appropriate execution boundary. Finish database transactions before slow provider calls.
- Delegate signing-key retrieval, caching and signature/time verification to Clerk’s async SDK with backend-only `CLERK_SECRET_KEY`. The local claims model requires session fields and enforces the configured issuer and native-compatible authorized-party policy. Follow the [authentication runbook](authentication.md).
- Protect owned routes with `CurrentUser` from `app/core/auth/dependencies.py`; it validates the selected adapter and resolves an active local integer ID. Derive identity and ownership from authentication, never request-body identities. Authorize resource operations and cover two-account isolation. Account work must define session expiration and logout/revocation.
- Backend `AUTH_MODE` defaults to `basic` outside production and `clerk` in production; the frontend selects its adapter through `EXPO_PUBLIC_AUTH_MODE`. Keep the selected adapters aligned. Backend `BASIC_AUTH_USERS` supplies local accounts; an empty mapping denies all sign-ins. Basic is forbidden in production. Keep provider network calls outside database transactions.
- WebSockets authenticate, check membership, persist actual training changes and define reconnect/resync. Use short per-operation sessions. Choose shared event infrastructure before increasing socket-serving workers.

## Development and packaging

Use uv and the README’s `make setup`, `make dev`, `make migrate` and `make check` commands. Commit dependency manifests and lockfiles together. Compose runs the packaged API, PostgreSQL and Azurite; host development starts `postgres` and `azurite` and uses published ports rather than Compose service names. The README documents the optional local SonarQube profile and external exercise/media seed export; keep local exports and uploaded media untracked.

Add dependency services with consuming features. Use dependency-native health checks, healthy startup conditions and bounded API liveness/readiness; verify failure and recovery. Maintain cached multi-stage builds, compatible Python/OS/runtime paths, a slim non-root runtime and a scoped Docker context. Packaging/configuration verification covers host/container modes, runtime contents, explicit migrations, volume persistence, graceful shutdown and cache reuse as applicable.

Keep secrets in local/environment settings. Exclude credentials, personal-record payloads and query strings from logs. Maintain Git/build ignores for local configuration, generated data, database dumps and personal tool state. Preserve existing development-account data during manual acceptance; use only explicitly test-owned resources for automated destructive cleanup.

## Verification

Run the [standard checks and integration setup](../README.md#checks-and-database-changes) appropriate to the change. Full integration testing starts the dedicated service and supplies its explicit URL. Integration databases must end in `_test`; tests use only test-owned records/tables. Add meaningful permission, calculation, persistence and failure cases alongside their consuming features.

The [CI workflow](../.github/workflows/ci.yml) runs Ruff, the complete isolated pytest suite with healthy PostgreSQL/Azurite services, and SonarCloud analysis using uploaded coverage. SonarCloud scans wait for the project's configured quality gate and fail on a failed gate or timeout. Keep locked synchronization, uv/Python pins, service images and the SonarCloud action aligned with local commands and Compose. Preserve immutable action pins and read-only permissions.

Full-stack acceptance must demonstrate the actual authenticated user flow and persistence through the backend. Infrastructure probes alone do not demonstrate feature delivery. Report executed checks and results accurately, including skipped or unverified behavior. Update the README, these conventions and agent entry instructions when their responsibilities change; avoid repeating command/version inventories across them.
