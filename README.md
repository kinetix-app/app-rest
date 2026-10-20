# Kinetix backend

FastAPI backend for Kinetix, the React Native fitness application. The product connects goals, nutrition and workout/activity records with shared training, social participation, FriendsLeague, reusable community content and AI coaching.

The foundation includes an application factory, typed configuration, SQLAlchemy resources, Alembic tooling, health endpoints, request logging, Compose services, a packaged Docker image and tests. The account feature adds Clerk session validation, local user/identity/profile tables, and protected account APIs. Other feature schemas evolve through the GitHub backlog.

## Start here

Read this guide and [AGENTS.md](AGENTS.md), inspect the implementation and follow the task acceptance criteria. GitHub issues are the task/status source; the GitHub Project is the shared planning view. Repository/Project publication configuration is pending.

The management repository owns product scope, sprint commitments, diagrams and architecture decisions, including ADR-002. This repository owns runtime services, migrations, application packaging and setup instructions. Documentation is in English; relative links stay within this repository.

## Quickstart

Install Docker with Compose v2, uv **0.12.13 or newer**, and Make. Docker/CI keep an exact uv pin for reproducible builds. uv manages Python using `.python-version`.

For a fresh checkout, copy `.env.example` to `.env`; keep any existing local `.env`. Set `POSTGRES_PASSWORD` and configure `BASIC_AUTH_USERS` with your own development email/password before signing in.

```sh
make setup
make dev
```

Open [API docs](http://127.0.0.1:8000/docs). Development uses Basic authentication by default. Clerk testing and production configuration are covered in [authentication setup](docs/authentication.md).

## Stack and structure

Python **3.14.6**, uv **0.12.13 or newer** (Docker/CI pin: 0.12.13), FastAPI, Pydantic v2/settings, SQLAlchemy async with asyncpg, Alembic, Uvicorn, Ruff, pytest and HTTPX. PostgreSQL **18.6** is served by a pinned Compose image. Resolved Python dependency versions are in `uv.lock`; Docker base/tool/service images are pinned by digest.

| Location | Purpose |
|---|---|
| `app/main.py` | Application factory, lifespan and safe request logging |
| `app/core/` | Typed environment settings and logging configuration |
| `app/api/` | Health endpoints and `/api/v1` router composition |
| `app/core/auth/` | Clerk SDK token verification and current-user dependency |
| `app/features/accounts/` | Account models, private schemas, provisioning and profile routes |
| `docs/authentication.md` | Clerk configuration runbook and account/session contract |
| `db-schema.sql`, `docs/data-model.md`, `docs/data-model-review.md` | Product schema draft, pending unified serial-ID change, Sprint 1 review and shared manual/imported exercise fields; Alembic remains the runtime schema authority |
| `app/db/` | ORM metadata, engine and request session dependency |
| `migrations/` | Alembic environment, templates and feature revisions |
| `tests/` | Configuration, health/lifecycle and PostgreSQL integration checks |
| `scripts/` | Local maintenance helpers, including the optional SonarQube scan |
| `Dockerfile`, `compose.yaml` | API image and local dependency/application services |
| `sonar-project.properties` | Shared SonarQube/SonarCloud analysis configuration |

Implement feature packages under `app/features/` as their tasks are delivered. Keep routers thin, use-case logic and transactions in services, and request/private/public response schemas separate from persistence models.

## Authentication setup

Follow [Clerk dashboard and backend setup](docs/authentication.md) to finish configuring Google, Apple and Email OTP, set `CLERK_ISSUER` and backend-only `CLERK_SECRET_KEY`, apply the account migration and exercise the private APIs. The backend validates Clerk session tokens and atomically provisions an internal user UUID on first valid access. `GET /api/v1/me` reads/bootstrap the account; `PATCH /api/v1/me/profile` edits display name/timezone.

With `AUTH_MODE=clerk`, missing Clerk configuration makes protected requests return 503; production startup requires both. Production provider configuration and native session/device demonstrations still need verification; account linking and deletion synchronization remain outstanding under [ACC01](https://github.com/kinetix-app/app-rest/issues/1).

## Development email/password sign-in

The frontend Basic form needs the [DEV01 adapter](https://github.com/kinetix-app/app-rest/issues/7). In the ignored backend `.env`, configure your local credentials (Basic is the default outside production):

```dotenv
APP_ENV=development
BASIC_AUTH_USERS={"your-email@example.test":"choose-your-own-local-password"}
```

Restart the API after changing these settings. Sign in with that exact email/password in the development app. There are no built-in accounts. Valid Basic credentials resolve a synthetic `urn:kinetix:dev` identity through the existing local account/profile service; the database must be running and migrations applied. Wrong credentials return 401 with a Basic challenge. Existing blocked/deleted accounts remain denied.

`AUTH_MODE` defaults to `basic` in development/test and `clerk` in production. Set `AUTH_MODE=clerk` to test Clerk locally: it accepts only Clerk Bearer tokens and never falls back to development credentials. Production rejects `basic` at startup. Basic sign-out clears the app's in-memory header; it creates no Clerk session. Do not put development passwords in the frontend's public environment or commit them.

### Check the running API

After starting the API and applying migrations, use your configured username below.
`curl` prompts for the password so it does not appear in shell history:

```sh
curl -i http://localhost:8000/api/v1/me
curl -i --user 'your-email@example.test' http://localhost:8000/api/v1/me
```

The first request must return **401** with `WWW-Authenticate: Basic`. The second must
return **200** with an active account. Repeat it with a wrong password: it must return
**401**. Repeat with the correct password: the account UUID must stay the same.
A **500** after correct credentials can indicate unapplied migrations; check API logs.

## Development commands

The [Makefile](Makefile) wraps the existing uv and Compose commands. It uses the host API with automatic reload and starts only PostgreSQL in Docker. Run commands from this checkout; `make` is available on macOS/Linux and through WSL or GNU Make on Windows.

| Command | Purpose |
|---|---|
| `make setup` | Install locked development dependencies, start PostgreSQL and apply migrations |
| `make dev` | Ensure PostgreSQL is healthy and start Uvicorn with reload |
| `make migrate` | Apply migrations after pulling schema changes |
| `make check` | Check the lockfile, Ruff lint/format and non-integration tests |
| `make db` | Start PostgreSQL alone |

After first setup, use `make dev` for daily work. Re-run `make setup` when dependencies change, or `make migrate` when migrations change. Stop Uvicorn with Ctrl-C; PostgreSQL keeps its data in a named volume. Stop PostgreSQL with `docker compose stop postgres`.

Without Make, the equivalent API command is:

```sh
uv run --locked --no-build uvicorn app.main:create_app --factory --reload --no-access-log
```

The factory loads and validates one settings object. Database resources are created and disposed during the application lifespan. `/health/live` reports whether the API responds; `/health/ready` checks PostgreSQL with a configured query timeout. Request logs include IDs, route templates, status and duration, excluding query strings and bodies.

### Configuration

`.env.example` documents local values. `.env` is ignored by Git and the Docker build. PostgreSQL initialization settings must match the application credentials.

| Setting | Default/purpose |
|---|---|
| `POSTGRES_USER`, `POSTGRES_DB` | `fitness`; local database role and name |
| `POSTGRES_PASSWORD` | Required local credential unless `DATABASE_URL` supplies the connection |
| `POSTGRES_HOST` | `127.0.0.1` for the host API; Compose sets `postgres` for the API container |
| `POSTGRES_PORT` | `5432` on the host; change for local port conflicts; container connections use 5432 |
| `DATABASE_URL` | Optional complete `postgresql+asyncpg` URL; takes precedence in the host application |
| `API_PORT` | Compose API host port, default 8000 |
| `API_BIND_ADDRESS` | Host interface for the Compose API; default `127.0.0.1`; set to `0.0.0.0` for physical devices on your LAN |
| `CORS_ALLOWED_ORIGINS` | JSON array of browser origins allowed to call the API; defaults to `["http://localhost:8081"]` |
| `AUTH_MODE` | Blank: Basic outside production, Clerk in production; optional `basic` / `clerk` override |
| `BASIC_AUTH_USERS` | JSON object of local usernames/passwords; empty by default, so no Basic account can sign in |
| `APP_ENV` | `development`, `test` or `production`; default development |
| `LOG_LEVEL` | Python application logging level, default INFO |
| `DATABASE_TIMEOUT_SECONDS` | Connection/readiness timeout, default 2; greater than 0 and at most 30 |
| `TEST_POSTGRES_PORT` | Isolated test-service host port, default 55432 |
| `TEST_DATABASE_URL` | Explicit integration-test connection URL, with database name ending in `_test` |
| `SONAR_PORT` | Optional local SonarQube host port, default 9000 |
| `SONAR_TOKEN` | Local SonarQube authentication token; required by `scripts/sonar-scan.sh` |
| `SONAR_CLOUD_TOKEN` | Optional SonarCloud token used by the `sonarqube-issues` skill |
| `SONAR_ORGANIZATION` | SonarCloud organization key used by the `sonarqube-issues` skill; defaults to `kinetix-app` in `.env.example` |

The component settings construct database URLs safely when passwords contain reserved characters. Encode credentials when providing a complete URL. Compose reads the same `.env` through `env_file`, overriding only the database connection to use `postgres:5432`; host `DATABASE_URL` overrides remain local. Keep credentials outside version control.

`API_PORT` controls container publishing. For a different host-run API port, pass Uvicorn `--port`. Development dependency ports bind to loopback. When testing with a physical frontend device, explicitly choose the host API bind address and the device-reachable API URL for that demonstration.

## Run the packaged API

The default Compose services run the API image alongside PostgreSQL:

```sh
docker compose up -d --wait postgres
docker compose run --rm --build api alembic upgrade head
docker compose up -d --build --wait
```

Run migrations before starting application traffic. Stop a host API using the same port before switching modes. The container uses `postgres:5432`, waits for a healthy database, runs as UID 10001 with a read-only filesystem and uses the bundled application. Its readiness probe uses Python's standard library.

The Dockerfile installs locked runtime dependencies once in a cached builder layer, then copies the application and migrations into the slim runtime. Source changes do not rebuild dependencies. Verify cache reuse when changing packaging or dependencies; update image digests together with documented compatibility checks.

## Checks and database changes

```sh
uv lock --check
uv run --locked --no-build ruff check .
uv run --locked --no-build ruff format --check .
uv run --locked --no-build pytest -m 'not integration'
```

Run the complete suite against the dedicated test service:

```sh
docker compose up -d --wait postgres-test
TEST_DATABASE_URL=postgresql+asyncpg://fitness_test:fitness_test_local@127.0.0.1:55432/fitness_test uv run --locked --no-build pytest
```

Use the configured test port in the URL if changed. The test service has its own container, database and volume. Without `TEST_DATABASE_URL`, PostgreSQL tests are explicitly skipped. With it, the suite verifies real readiness, committed data across engine disposal, transaction rollback and Alembic bootstrap/metadata consistency. Integration tests create and remove only test-owned tables.

Add dependencies with `uv add <package>` or `uv add --group dev <package>` and commit `pyproject.toml` together with `uv.lock`. Apply formatting with `uv run --locked --no-build ruff format .`.

For each implemented schema change, import its models into the Alembic environment, then generate and review the candidate revision:

```sh
uv run --locked --no-build alembic revision --autogenerate -m "describe schema change"
uv run --locked --no-build alembic upgrade head
uv run --locked --no-build alembic check
```

Feature revisions belong in `migrations/versions/`. The migration chain includes the account, identity and profile tables. Review constraints, renames, data changes and applicable upgrade paths.

## Local static analysis with SonarQube (optional)

The `sonar` Compose profile runs a local SonarQube Community server for pre-push checks. It uses the embedded database and a named volume, so history survives restarts; it is intended for local development only. The server is pinned by image digest and shares `sonar-project.properties` with the CI analysis.

1. Start the server (first boot takes one to two minutes) and open the UI:

   ```sh
   docker compose --profile sonar up -d sonarqube
   ```

   Open [SonarQube](http://127.0.0.1:9000). The first login is `admin`/`admin`; set a new password when prompted. Create a token under **My Account > Security**, then add it to `.env`:

   ```sh
   SONAR_TOKEN=your-local-token
   ```

2. Run the tests with coverage and scan the project:

   ```sh
   ./scripts/sonar-scan.sh
   ```

   The script waits for the server, runs `pytest` with a `coverage.xml` report, then runs the pinned SonarScanner container against the local server. It waits up to 300 seconds for the submitted background task to succeed, fetches unresolved findings to `/tmp/sonar-issues.json`, then prints completion. A failed, canceled or timed-out task or issue fetch fails the command. Set `SONAR_ISSUES_OUTPUT` to change the issue file path. Open the printed dashboard URL to review issues. Extra arguments are passed to pytest, for example `./scripts/sonar-scan.sh -m integration` after starting the test service.

3. Stop the server while keeping its data:

   ```sh
   docker compose --profile sonar down
   ```

Use a different `SONAR_PORT` in `.env` if 9000 is taken. On native Linux, SonarQube's Elasticsearch needs `vm.max_map_count` of at least 262144; Docker Desktop handles this. Removing the SonarQube volumes deletes all local analysis history.

### Retrieving Sonar issues

Users and the `sonarqube-issues` skill share the standard-library Python extractor in `scripts/`. Choose a source explicitly:

```sh
uv run --locked --no-build python scripts/fetch_sonar_issues.py --source local --output /tmp/sonar-issues.json
uv run --locked --no-build python scripts/fetch_sonar_issues.py --source cloud --pull-request 42 --output /tmp/sonar-pr-issues.json
```

Local extraction needs `SONAR_TOKEN`; Cloud needs `SONAR_CLOUD_TOKEN` and `SONAR_ORGANIZATION`. The extractor reads the repository `.env` directly, without shell execution or environment-variable overrides. Quote values containing whitespace. The project key comes from `sonar-project.properties`. `--root PATH` selects another repository and `--env-file PATH` selects another credentials file (relative to that root). By default the root is the parent of `scripts/`, so invocation works from other directories. Output paths are relative to the caller's working directory. `python3` can also run the script without installing dependencies.

Without `--branch NAME` or `--pull-request NUMBER`, the API queries the server's main branch. Those two options are mutually exclusive and require server support. Run `./scripts/sonar-scan.sh` before extracting findings for the current local checkout. After a manual scanner invocation, `--wait-for-analysis` waits for the task recorded in `.scannerwork/report-task.txt`; `--wait-only` just waits. `--analysis-timeout SECONDS` overrides the 300-second wait limit. A task report represents the submitted scan, not subsequent code edits.

JSON schema version 1 records source, server URL, organization, project key, total and normalized issues; an explicit branch or PR adds its context field. Issues sort by path (case-insensitive then exact), line, rule and key; tags are unique and sorted, and output has no extraction timestamp. The same API data and context produce identical bytes. Findings with different keys remain distinct even when their messages or locations match.

The extractor validates every page and fails on duplicates, changing counts, incomplete pages, invalid responses, authentication errors or more than 10,000 findings. The API has no atomic snapshot, so avoid concurrent analyses or issue edits during retrieval. Errors go to stderr with exit code 2; no partial JSON is emitted and an existing output file is preserved. Only consume output after a successful command. Tokens are never included in JSON. This endpoint retrieves unresolved issues; security hotspots require a separate review.

## CI

The [CI workflow](.github/workflows/ci.yml) runs on every pull request, on pushes to a branch that has an open pull request (the pull-request `synchronize` event) and on pushes to `master`, with three independent checks:

- **Lint and format:** Ruff linting and formatting verification.
- **Tests:** the complete pytest suite with coverage, including integration tests against an isolated, health-checked PostgreSQL service matching the Compose image.
- **SonarCloud:** uploads the analysis and coverage report to SonarCloud. This check is advisory: it reports the quality gate without failing the build.

All jobs install uv 0.12.13, use Python from `.python-version`, cache dependencies and synchronize with `uv sync --locked --group dev --no-build`. `--no-build` stops dependency build scripts from running during synchronization; the project itself is still built. An outdated lockfile fails synchronization. The test job supplies `TEST_DATABASE_URL` for its temporary `fitness_test` database and uploads `coverage.xml`; the SonarCloud job checks out the full history (`fetch-depth: 0`) and downloads that report. Pull-request runs are analyzed in the pull-request context and the source branch is passed explicitly as `sonar.pullrequest.branch`, so each analysis identifies the branch it came from; pushes to `master` update the project's main branch. Actions are pinned to release commits, workflow permissions are read-only and new commits cancel superseded runs for the same PR.

### SonarCloud setup

CI-based analysis needs a SonarCloud project bound to the GitHub repository:

1. Make the repository public (public projects are analyzed for free) and create the SonarCloud organization by linking GitHub. Confirm the organization server region; it cannot be changed later.
2. Import `kinetix-app/app-rest`, then disable **Automatic Analysis** so CI-based analysis with coverage is used.
3. Confirm `sonar.projectKey` in `sonar-project.properties` and the `-Dsonar.organization` value in the workflow match the project; the defaults are `kinetix-backend` and `kinetix-app`.
4. Create a personal access token and store it as the `SONAR_TOKEN` repository secret.

The quality gate is advisory: the job does not set `sonar.qualitygate.wait`, so it stays green while the gate result is visible in SonarCloud. Pull requests from forks do not receive repository secrets, so the SonarCloud job is skipped for fork pull requests; adopt the documented split-workflow pattern before relying on analysis for external contributors.

Run the checks above before requesting review. Keep CI commands, version pins and the PostgreSQL image aligned with local development. Repository branch rules can require **Lint and format** and **Tests** to pass before merging.

## Service health and troubleshooting

```sh
docker compose ps
docker compose logs --tail=100 postgres
docker compose logs --tail=100 api
docker compose down
```

PostgreSQL is checked with `pg_isready`; API readiness queries it using application credentials. Health failures should lead to checking the connection hostname/port, credentials and database logs. Health checks handle startup ordering; readiness reports database failures and recovers after the database returns. A paused PostgreSQL process can delay pooled-connection cleanup beyond `DATABASE_TIMEOUT_SECONDS` (observed past 15 seconds); the container health check has its own external timeout. Stopping/restarting PostgreSQL was verified separately from this paused-process limitation.

Normal shutdown preserves the named data volumes. Existing volumes retain their initialized credentials; changing `.env` does not change an existing database role. Redact sensitive output before sharing diagnostics. Resetting a volume is a deliberate data-deletion operation.

## Development conventions

Use lifespan to create/dispose pooled resources. Scope sessions to requests/use cases; services explicitly commit or roll back, and concurrent tasks use separate sessions. Await async I/O and put heavy computation behind a suitable execution boundary. Load response relationships explicitly.

Derive identity/ownership server-side and authorize every resource operation. Test two-account isolation with owned features. Specify expiration and logout/revocation for account work. Public response schemas expose only their intended fields.

Use grams, kilograms, minutes and kilometres consistently. Define numeric precision/rounding, timezone-aware event instants, user timezone and meal-log dates. Calculate nutrition totals, league scores and progress comparisons deterministically. Separate routine templates, completed activities and shared membership; reuse activity references and preserve community-copy provenance.

WebSocket feature work must authenticate participants, persist authoritative training changes and define reconnection/resynchronization. Use shared event infrastructure before scaling socket-serving processes. The management decisions and feature acceptance criteria define behavior requiring product-owner agreement.

Before handoff, run relevant checks, inspect the changed files, update setup instructions and report actual results and limitations. Foundation checks establish infrastructure behavior; end-to-end feature commitments require their own application demonstrations.
