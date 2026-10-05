# Kinetix backend coding-agent instructions

Read [README.md](README.md), the user's task, its issue/acceptance criteria when available, and any more specific instructions for the files being edited. Inspect implementation and working-tree changes before work; preserve unrelated developer material.

## Context and workflow

The repository contains the initialized FastAPI foundation, configuration, PostgreSQL resources, Alembic environment, health routes, Docker packaging and tests. Product features develop through the GitHub backlog. Verify actual implementation before reporting completion.

GitHub issues are the task/status source and the GitHub Project is the planning view. Publication configuration is pending. Use verified issue references when available and keep reported work factual. The management repository owns product scope, sprint commitments, diagrams and decisions; this repository owns executable services/migrations and runtime onboarding. Documentation is English and links remain within the repository or use verified external URLs.

Kinetix connects personal goals, nutrition and activity tracking with shared training, social participation, FriendsLeague, community content and AI coaching. Resolve routine implementation details within the task. Obtain a product-owner decision for required behavior such as visibility, scoring, progress measures, historical nutrition semantics or session permissions.

## Code conventions

- Use FastAPI, SQLAlchemy async with asyncpg, Alembic, Pydantic v2 and typed settings. Follow the Python pin and uv lockfile.
- Implement feature packages under `app/features/`. Keep routers thin, use-case/transaction logic in services, and reused complex queries in focused modules. Compose business routes under `/api/v1`.
- Keep ORM models and create/update/private/public response schemas distinct. Validate bounds, output visibility, errors and PATCH omission/null behavior.
- Inject identity, settings and sessions. Use application lifespan for pooled resource creation/disposal. One session per request/use case; each concurrent task gets its own session. Load relationships needed for serialization explicitly.
- Services define successful commit and failure rollback boundaries. Await async I/O, move blocking computation behind an appropriate execution boundary, and finish database transactions before slow provider calls.
- Add schema changes through manually reviewed Alembic revisions in `migrations/versions/`, with database constraints and feature model imports in `migrations/env.py`. Verify clean setup and applicable upgrades.
- Derive identity/ownership from authentication, authorize resource operations and cover two-account isolation with owned features. Account work defines session expiration and logout/revocation.
- Use deterministic nutrition/league/progress calculations, documented precision/rounding, explicit units and timezone-aware event handling. Separate templates, completed activities and membership; reuse activity references and preserve community-copy provenance.

## Development and packaging

- Use uv for dependency management and commands. Commit manifest and lockfile changes together. The README is the setup/command reference.
- Compose runs PostgreSQL dependencies; host uv/Uvicorn is the default development mode and the `app` profile runs the packaged API. Use host published ports versus Compose service names correctly.
- An optional `sonar` profile runs a local SonarQube Community server for pre-push analysis through `scripts/sonar-scan.sh`; it uses the embedded database and named volumes and is not part of CI.
- Add dependency services alongside consuming features. Use dependency-native health checks and healthy-startup conditions, with bounded API liveness/readiness behavior and failure/recovery verification.
- Maintain cached multi-stage builds, compatible Python/OS/runtime paths, a slim non-root runtime and an appropriately scoped Docker build context. Verify runtime contents and cache reuse after packaging changes.
- WebSocket work authenticates/checks membership, persists actual training changes and defines reconnect/resync. Choose shared event infrastructure before increasing socket-serving workers. Use short per-operation database sessions.
- Keep configuration secrets in local/environment settings. Keep credentials, personal-record payloads and query strings out of logs. Maintain Git/build ignore rules for local configuration and generated data.

## Verification and handoff

Standard checks:

```sh
uv lock --check
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked pytest -m 'not integration'
```

For the full suite, start the dedicated test service and pass its explicit URL as documented in the README. Integration tests must target a database ending in `_test`, and use only test-owned records/tables. Add meaningful permission, calculation, persistence and failure cases with their consuming features.

The pull-request workflow in `.github/workflows/ci.yml` runs Ruff lint/format checks, the complete pytest suite with an isolated, health-checked PostgreSQL service, and an advisory SonarCloud scan consuming the uploaded coverage report. Keep its uv/Python pins, locked synchronization, database image and SonarCloud action pin aligned with local commands and Compose. Preserve immutable action pins and read-only permissions when editing CI.

For configuration/packaging changes, verify host and container modes, health failure/recovery, explicit migrations, data-volume persistence, graceful shutdown and cache reuse as applicable. Report executed checks, results and unverified behavior accurately; infrastructure probes establish infrastructure evidence, while feature delivery requires its own demonstration.

Keep README.md and this file synchronized with actual conventions, commands and structure. Inspect changed files before handoff. State what changed, why, verification results and remaining decisions. Respect the authorized repository/publication scope and keep local credentials, uploaded media, database dumps and personal tool state outside tracked content.
