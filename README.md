# Kinetix backend

FastAPI backend for Kinetix, the React Native fitness application. The product connects goals, nutrition and workout/activity records with shared training, social participation, FriendsLeague, reusable community content and AI coaching.

The foundation includes an application factory, typed configuration, SQLAlchemy resources, Alembic tooling, health endpoints, request logging, Compose services, a packaged Docker image and tests. Feature schemas and API contracts evolve through the GitHub backlog.

## Start here

Read this guide and [AGENTS.md](AGENTS.md), inspect the implementation and follow the task acceptance criteria. GitHub issues are the task/status source; the GitHub Project is the shared planning view. Repository/Project publication configuration is pending.

The management repository owns product scope, sprint commitments, diagrams and architecture decisions, including ADR-002. This repository owns runtime services, migrations, application packaging and setup instructions. Documentation is in English; relative links stay within this repository.

## Stack and structure

Python **3.14.6**, uv **0.12.13** (supported local range: 0.12.x), FastAPI, Pydantic v2/settings, SQLAlchemy async with asyncpg, Alembic, Uvicorn, Ruff, pytest and HTTPX. PostgreSQL **18.6** is served by a pinned Compose image. Resolved Python dependency versions are in `uv.lock`; Docker base/tool/service images are pinned by digest.

| Location | Purpose |
|---|---|
| `app/main.py` | Application factory, lifespan and safe request logging |
| `app/core/` | Typed environment settings and logging configuration |
| `app/api/` | Health endpoints and `/api/v1` router composition |
| `app/db/` | ORM metadata, engine and request session dependency |
| `migrations/` | Alembic environment, templates and feature revisions |
| `tests/` | Configuration, health/lifecycle and PostgreSQL integration checks |
| `scripts/` | Local maintenance helpers, including the optional SonarQube scan |
| `Dockerfile`, `compose.yaml` | API image and local dependency/application services |
| `sonar-project.properties` | Shared SonarQube/SonarCloud analysis configuration |

Implement feature packages under `app/features/` as their tasks are delivered. Keep routers thin, use-case logic and transactions in services, and request/private/public response schemas separate from persistence models.

## Develop with Compose dependencies and a host API

Install uv and Docker with Compose v2 supporting `--wait`. Run commands from the backend checkout. uv uses `.python-version` and manages the project's environment.

1. Copy configuration and choose a local development password before starting PostgreSQL:

   ```sh
   cp .env.example .env
   ```

2. Start PostgreSQL, synchronize the locked environment and apply the migration chain:

   ```sh
   docker compose up -d --wait postgres
   uv sync --locked
   uv run --locked alembic upgrade head
   ```

3. Start the development server:

   ```sh
   uv run --locked uvicorn app.main:app --reload --no-access-log
   ```

Open [API docs](http://127.0.0.1:8000/docs). `/health/live` returns 200 when the API responds. `/health/ready` performs a bounded PostgreSQL query and returns 200 or 503. Application request logs include generated request IDs, route templates, status and duration; query strings and bodies are kept out of those logs.

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
| `APP_ENV` | `development`, `test` or `production`; default development |
| `LOG_LEVEL` | Python application logging level, default INFO |
| `DATABASE_TIMEOUT_SECONDS` | Connection/readiness timeout, default 2; greater than 0 and at most 30 |
| `TEST_POSTGRES_PORT` | Isolated test-service host port, default 55432 |
| `TEST_DATABASE_URL` | Explicit integration-test connection URL, with database name ending in `_test` |
| `SONAR_PORT` | Optional local SonarQube host port, default 9000 |
| `SONAR_TOKEN` | Local SonarQube authentication token; required by `scripts/sonar-scan.sh` |

The component settings construct database URLs safely when passwords contain reserved characters. Encode credentials when providing a complete URL. Compose explicitly supplies component settings to its API service; host `DATABASE_URL` overrides remain local. Keep credentials outside version control.

`API_PORT` controls container publishing. For a different host-run API port, pass Uvicorn `--port`. Development dependency ports bind to loopback. When testing with a physical frontend device, explicitly choose the host API bind address and the device-reachable API URL for that demonstration.

## Run the packaged API

The optional Compose `app` profile runs the API image alongside PostgreSQL:

```sh
docker compose up -d --wait postgres
docker compose run --rm --build api alembic upgrade head
docker compose --profile app up -d --build --wait
```

Run migrations before starting application traffic. Stop a host API using the same port before switching modes. The container uses `postgres:5432`, waits for a healthy database, runs as UID 10001 with a read-only filesystem and uses the bundled application. Its readiness probe uses Python's standard library.

The Dockerfile installs runtime dependencies in a cached builder layer before copying application source, then installs the package non-editably. Its slim runtime includes the environment and migration inputs. Verify cache reuse when changing packaging or dependencies; update image digests together with documented compatibility checks.

## Checks and database changes

```sh
uv lock --check
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked pytest -m 'not integration'
```

Run the complete suite against the dedicated test service:

```sh
docker compose up -d --wait postgres-test
TEST_DATABASE_URL=postgresql+asyncpg://fitness_test:fitness_test_local@127.0.0.1:55432/fitness_test uv run --locked pytest
```

Use the configured test port in the URL if changed. The test service has its own container, database and volume. Without `TEST_DATABASE_URL`, PostgreSQL tests are explicitly skipped. With it, the suite verifies real readiness, committed data across engine disposal, transaction rollback and Alembic bootstrap/metadata consistency. Integration tests create and remove only test-owned tables.

Add dependencies with `uv add <package>` or `uv add --group dev <package>` and commit `pyproject.toml` together with `uv.lock`. Apply formatting with `uv run --locked ruff format .`.

For each implemented schema change, import its models into the Alembic environment, then generate and review the candidate revision:

```sh
uv run --locked alembic revision --autogenerate -m "describe schema change"
uv run --locked alembic upgrade head
uv run --locked alembic check
```

Feature revisions belong in `migrations/versions/`. The foundation starts with empty domain metadata; upgrading currently initializes Alembic's version tracking. Add the initial product schema with the first agreed feature. Review constraints, renames, data changes and applicable upgrade paths.

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

   The script waits for the server, runs `pytest` with a `coverage.xml` report, then runs the pinned SonarScanner container against the local server. Open the printed dashboard URL to review issues. Extra arguments are passed to pytest, for example `./scripts/sonar-scan.sh -m integration` after starting the test service.

3. Stop the server while keeping its data:

   ```sh
   docker compose --profile sonar down
   ```

Use a different `SONAR_PORT` in `.env` if 9000 is taken. On native Linux, SonarQube's Elasticsearch needs `vm.max_map_count` of at least 262144; Docker Desktop handles this. Removing the SonarQube volumes deletes all local analysis history.

## Pull-request CI

The [CI workflow](.github/workflows/ci.yml) runs on every pull request and on pushes to `master`, with three independent checks:

- **Lint and format:** Ruff linting and formatting verification.
- **Tests:** the complete pytest suite with coverage, including integration tests against an isolated, health-checked PostgreSQL service matching the Compose image.
- **SonarCloud:** uploads the analysis and coverage report to SonarCloud. This check is advisory: it reports the quality gate without failing the build.

All jobs install uv 0.12.13, use Python from `.python-version`, cache dependencies and synchronize with `uv sync --locked --group dev`. An outdated lockfile fails synchronization. The test job supplies `TEST_DATABASE_URL` for its temporary `fitness_test` database and uploads `coverage.xml`; the SonarCloud job checks out the full history (`fetch-depth: 0`) and downloads that report. Actions are pinned to release commits, workflow permissions are read-only and new commits cancel superseded runs for the same PR.

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
docker compose --profile app logs --tail=100 api
docker compose --profile app down
```

PostgreSQL is checked with `pg_isready`; API readiness queries it using application credentials. Health failures should lead to checking the connection hostname/port, credentials and database logs. Health checks handle startup ordering; the API also returns bounded readiness failures and can reconnect after the database returns.

Normal shutdown preserves the named data volumes. Existing volumes retain their initialized credentials; changing `.env` does not change an existing database role. Redact sensitive output before sharing diagnostics. Resetting a volume is a deliberate data-deletion operation.

## Development conventions

Use lifespan to create/dispose pooled resources. Scope sessions to requests/use cases; services explicitly commit or roll back, and concurrent tasks use separate sessions. Await async I/O and put heavy computation behind a suitable execution boundary. Load response relationships explicitly.

Derive identity/ownership server-side and authorize every resource operation. Test two-account isolation with owned features. Specify expiration and logout/revocation for account work. Public response schemas expose only their intended fields.

Use grams, kilograms, minutes and kilometres consistently. Define numeric precision/rounding, timezone-aware event instants, user timezone and meal-log dates. Calculate nutrition totals, league scores and progress comparisons deterministically. Separate routine templates, completed activities and shared membership; reuse activity references and preserve community-copy provenance.

WebSocket feature work must authenticate participants, persist authoritative training changes and define reconnection/resynchronization. Use shared event infrastructure before scaling socket-serving processes. The management decisions and feature acceptance criteria define behavior requiring product-owner agreement.

Before handoff, run relevant checks, inspect the changed files, update setup instructions and report actual results and limitations. Foundation checks establish infrastructure behavior; end-to-end feature commitments require their own application demonstrations.
