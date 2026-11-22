# Kinetix backend

Nutrition goal previews now use a deterministic Mifflin–St Jeor estimate before
explicit goal acceptance. See [recommendation policy and scientific sources](docs/nutrition-recommendations.md).

The [onboarding contract](docs/onboarding.md) separates a complete profile and selected objective from an optional manual nutrition target.
[Body progress](docs/features/goals.md) provides dated measurements and a private weight target for the selected objective.

FastAPI backend for Kinetix, the React Native fitness application. The product connects goals, nutrition and workout/activity records with shared training, social participation, FriendsLeague, reusable community content and AI coaching.

The foundation includes an application factory, typed configuration, SQLAlchemy resources, Alembic tooling, health endpoints, request logging, Compose services, Azure Blob Storage resources, an exercise/media seed command, a packaged Docker image and tests. The account feature adds Clerk session validation, local user/identity/profile tables, and protected account APIs. Nutrition, training and goal tables are initialized from `db-schema.sql`. The training API supports owned routine creation, reading and editing, plus exercise catalogue browsing. Nutrition provides personal food create/read/update/delete operations. Training adds atomic completed-workout submission and private history; meal logging and goal APIs remain backlog work.

## Start here

Read this guide and [AGENTS.md](AGENTS.md), inspect the implementation and follow the task acceptance criteria. GitHub issues are the task/status source; the GitHub Project is the shared planning view. Repository/Project publication configuration is pending.

The management repository owns product scope, sprint commitments, diagrams and architecture decisions, including ADR-002. This repository owns runtime services, migrations, application packaging and setup instructions. Documentation is in English; relative links stay within this repository.

## Quickstart

Install Docker with Compose v2, uv **0.12.13 or newer**, and Make. Docker/CI keep an exact uv pin for reproducible builds. uv manages Python using `.python-version`.

For a fresh checkout, copy `.env.example` to `.env`. If you already have a local `.env`, copy in the new connection-string settings and keep your existing credentials. Set your local PostgreSQL password in `POSTGRES_PASSWORD` and both database URLs. Configure `BASIC_AUTH_USERS` before signing in. For hosted environments, see the [production deployment guide](docs/deployment.md).

```sh
make setup
make dev
```

Open [API docs](http://127.0.0.1:8000/docs). Development uses Basic authentication by default. Clerk testing and production configuration are covered in [authentication setup](docs/authentication.md).

## Stack and structure

Python **3.14.6**, uv **0.12.13 or newer** (Docker/CI pin: 0.12.13), FastAPI, Pydantic v2/settings, SQLAlchemy async with Psycopg 3, Alembic, Uvicorn, Ruff, pytest and HTTPX. PostgreSQL **18.6** is served by a pinned Compose image. Resolved Python dependency versions are in `uv.lock`; Docker base/tool/service images are pinned by digest.

| Location | Purpose |
|---|---|
| `app/main.py` | Application factory, lifespan and safe request logging |
| `app/core/` | Typed environment settings and logging configuration |
| `app/api/` | Health endpoints and `/api/v1` router composition |
| `app/core/auth/` | Clerk SDK token verification and current-user dependency |
| `app/features/accounts/` | Account models, private schemas, provisioning and profile routes |
| `app/features/training/` | Routine/exercise APIs, training persistence and exercise/media seeding |
| `app/features/posts/` | Workout posts feed, private post images, likes and comments |
| `app/features/social/` | Mutual friendships, friend requests and people search |
| `docs/authentication.md` | Clerk configuration runbook and account/session contract |
| `db-schema.sql`, `docs/data-model.md`, `docs/data-model-review.md` | Product schema reference, data-model diagram and Sprint 1 review; Alembic remains the runtime schema authority |
| `app/db/` | ORM metadata, engine and request session dependency |
| `migrations/` | Alembic environment, templates and feature revisions |
| `tests/` | Configuration, health/lifecycle and PostgreSQL integration checks |
| `scripts/` | Local maintenance helpers, including the optional SonarQube scan |
| `Dockerfile`, `compose.yaml` | API image and local dependency/application services |
| `sonar-project.properties` | Shared SonarQube/SonarCloud analysis configuration |

Implement feature packages under `app/features/` as their tasks are delivered. Keep routers thin, use-case logic and transactions in services, and request/private/public response schemas separate from persistence models.

## Authentication setup

Follow [Clerk dashboard and backend setup](docs/authentication.md) to finish configuring Google, Apple and Email OTP, set `CLERK_ISSUER` and backend-only `CLERK_SECRET_KEY`, apply the account migration and exercise the private APIs. The backend validates Clerk session tokens and atomically provisions an internal generated integer ID on first valid access. `GET /api/v1/me` reads/bootstrap the account; `PATCH /api/v1/me/profile` edits display name/timezone.

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
**401**. Repeat with the correct password: the account ID must stay the same.
A **500** after correct credentials can indicate unapplied migrations; check API logs.

## Development commands

The [Makefile](Makefile) wraps the existing uv and Compose commands. It uses the host API with automatic reload and starts PostgreSQL and Azurite in Docker. Run commands from this checkout; `make` is available on macOS/Linux and through WSL or GNU Make on Windows.

| Command | Purpose |
|---|---|
| `make setup` | Install locked development dependencies, start PostgreSQL and apply migrations |
| `make dev` | Ensure PostgreSQL and Azurite are healthy and start Uvicorn with reload |
| `make migrate` | Apply migrations and synchronize the shared food catalogue |
| `make check` | Check the lockfile, Ruff lint/format and non-integration tests |
| `make db` | Start PostgreSQL alone |
| `make storage` | Start the local Azurite blob service |
| `make seed-exercises DATASET=../exercices` | Validate and import the external exercise/media export |

After first setup, use `make dev` for daily work. Re-run `make setup` when dependencies change, or `make migrate` when migrations change. Stop Uvicorn with Ctrl-C; PostgreSQL keeps its data in a named volume. Stop local dependencies with `docker compose stop postgres azurite`.

Without Make, the equivalent API command is:

```sh
uv run --locked --no-build uvicorn app.main:create_app --factory --reload --no-access-log
```

The factory loads and validates one settings object. Database resources are created and disposed during the application lifespan. `/health/live` reports whether the API responds; `/health/ready` checks PostgreSQL and, when configured, the authenticated blob storage account, each within `DATABASE_TIMEOUT_SECONDS`. Liveness stays independent of both services. Request logs include IDs, route templates, status and duration, excluding query strings and bodies.

### Configuration

`.env.example` documents local values. `.env` is ignored by Git and the Docker build. PostgreSQL initialization settings must match the application credentials.

| Setting | Default/purpose |
|---|---|
| `POSTGRES_USER`, `POSTGRES_DB`, `POSTGRES_PASSWORD` | Initialize the local PostgreSQL container |
| `POSTGRES_PORT` | Local PostgreSQL published port, default 5432 |
| `DATABASE_URL` | Required PostgreSQL URI for the host API and Alembic |
| `DATABASE_COMPOSE_URL` | PostgreSQL URI for the local Compose API and Alembic, using `postgres:5432` |
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

Percent-encode reserved characters in URI credentials. Keep both development URIs aligned with the local PostgreSQL credentials. If you change the host port, update `DATABASE_URL` too. Compose maps `DATABASE_COMPOSE_URL` into the API container as `DATABASE_URL`.

`API_PORT` controls container publishing. For a different host-run API port, pass Uvicorn `--port`. Development dependency ports bind to loopback. When testing with a physical frontend device, explicitly choose the host API bind address and the device-reachable API URL for that demonstration.

## Run the packaged API

The default Compose services run the API image alongside PostgreSQL and Azurite:

```sh
docker compose up -d --wait postgres azurite
docker compose run --rm --build api alembic upgrade head
docker compose up -d --build --wait
```

Run migrations before starting application traffic. Stop a host API using the same port before switching modes. The container uses `postgres:5432`, waits for healthy PostgreSQL and Azurite services, runs as UID 10001 with a read-only filesystem and uses the bundled application. Its readiness probe uses Python's standard library.

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
TEST_DATABASE_URL=postgresql://fitness_test:fitness_test_local@127.0.0.1:55432/fitness_test uv run --locked --no-build pytest
```

Use the configured test port in the URL if changed. The test service has its own container, database and volume. Without `TEST_DATABASE_URL`, PostgreSQL tests are explicitly skipped. With it, the suite verifies real readiness, committed data across engine disposal, transaction rollback and Alembic bootstrap/metadata consistency. Integration tests create and remove only test-owned tables.

Add dependencies with `uv add <package>` or `uv add --group dev <package>` and commit `pyproject.toml` together with `uv.lock`. Apply formatting with `uv run --locked --no-build ruff format .`.

For each implemented schema change, import its models into the Alembic environment, then generate and review the candidate revision:

```sh
uv run --locked --no-build alembic revision --autogenerate -m "describe schema change"
uv run --locked --no-build alembic upgrade head
uv run --locked --no-build alembic check
```

Feature revisions belong in `migrations/versions/`. The migration chain creates all 30 tables from `db-schema.sql`, with SQLAlchemy metadata in
`app/features/accounts/`, `nutrition/`, `training/`, `goals/`, `posts/` and `leagues/`. Goals currently define persistence tables only. Nutrition provides personal food operations, and training implements routine/exercise APIs and completed-workout submission/history; ongoing recording uses owned resumable draft snapshots. Meal logging remains future feature work.

Revision `20261102_01` adds posts, attached files, likes, comments, leagues, memberships,
rounds and per-user round scores. These are persistence models only; social/league APIs
and business rules remain separate work. Its downgrade drops these eight tables and
their data while retaining existing account, nutrition, training and goal tables.

Existing account constraints remain in place, including the user-status CHECK.

Revision `20261021_01` converts existing account UUIDs to generated BIGINT IDs while
preserving identities, statuses, timestamps and profile relationships. Stop API traffic,
back up an existing database and deploy the integer-ID backend together with
`make migrate`. `/api/v1/me` now returns a JSON integer `id`; clients must refresh any
cached UUID account IDs. Revision `20261021_02` then creates the nutrition, training
and goal tables. Fresh databases run the same complete chain.

Downgrading below `20261021_02` drops the product tables and their data. Downgrading
`20261021_01` preserves account data and relationships but generates new UUIDs;
restoring the original UUID values requires the pre-upgrade backup. Review constraints,
renames, data changes and applicable upgrade paths.

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
- **Tests:** the complete pytest suite with coverage, including integration tests against an isolated, health-checked PostgreSQL and Azurite services matching the Compose images.
- **SonarCloud:** uploads the analysis and coverage report to SonarCloud, then waits up to 300 seconds for the quality gate. Both pull-request and main-branch scans fail the job when the project's configured coverage or analysis requirements fail, or when the gate result cannot be obtained before the timeout. Quality gate thresholds are managed in SonarCloud; see the [quality gate analysis parameters](https://docs.sonarsource.com/sonarqube-cloud/analyzing-source-code/analysis-parameters/parameters-not-settable-in-ui).

All jobs install uv 0.12.13, use Python from `.python-version`, cache dependencies and synchronize with `uv sync --locked --group dev --no-build`. `--no-build` stops dependency build scripts from running during synchronization; the project itself is still built. An outdated lockfile fails synchronization. The test job supplies `TEST_DATABASE_URL` for its temporary `fitness_test` database and `TEST_AZURE_STORAGE_ACCOUNT_NAME`/`TEST_AZURE_STORAGE_ACCOUNT_URL`/`TEST_AZURE_STORAGE_ACCOUNT_KEY` for test-owned Azurite containers and uploads `coverage.xml`; the SonarCloud job checks out the full history (`fetch-depth: 0`) and downloads that report. Pull-request runs are analyzed in the pull-request context and the source branch is passed explicitly as `sonar.pullrequest.branch`, so each analysis identifies the branch it came from; pushes to `master` update the project's main branch. Actions are pinned to release commits, workflow permissions are read-only and new commits cancel superseded runs for the same PR.

### SonarCloud setup

The SonarCloud job writes a GitHub Actions summary even after a failed scan, identifying the repository, source branch, source commit, job result and UTC timestamp, with links to SonarCloud results and workflow logs. Each scan also supplies `sonar.links.ci` with the workflow run URL. The job result includes scanner/setup failures as well as quality gate failures; inspect the logs for the specific cause.

CI-based analysis needs a SonarCloud project bound to the GitHub repository:

1. Make the repository public (public projects are analyzed for free) and create the SonarCloud organization by linking GitHub. Confirm the organization server region; it cannot be changed later.
2. Import `kinetix-app/app-rest`, then disable **Automatic Analysis** so CI-based analysis with coverage is used.
3. Confirm `sonar.projectKey` in `sonar-project.properties` and the `-Dsonar.organization` value in the workflow match the project; the defaults are `kinetix-backend` and `kinetix-app`.
4. Create a personal access token and store it as the `SONAR_TOKEN` repository secret.

Both scans set `sonar.qualitygate.wait=true` and `sonar.qualitygate.timeout=300` to enforce the quality gate assigned to the project in SonarCloud. Confirm that this gate includes the required coverage and analysis conditions. Pull requests from forks do not receive repository secrets, so the SonarCloud job is skipped for fork pull requests; adopt the documented split-workflow pattern before relying on analysis for external contributors.

Run the checks above before requesting review. Keep CI commands, version pins and the PostgreSQL image aligned with local development. Repository branch rules can require **Lint and format**, **Tests** and **SonarCloud** to pass before merging.

## Service health and troubleshooting

```sh
docker compose ps
docker compose logs --tail=100 postgres
docker compose logs --tail=100 api
docker compose down
```

PostgreSQL is checked with `pg_isready`; Azurite is checked through its Blob REST endpoint. API readiness authenticates against PostgreSQL and the configured blob account. Health failures should lead to checking the connection hostname/port, credentials and database logs. Health checks handle startup ordering; readiness reports database failures and recovers after the database returns. A paused PostgreSQL process can delay pooled-connection cleanup beyond `DATABASE_TIMEOUT_SECONDS` (observed past 15 seconds); the container health check has its own external timeout. Stopping/restarting PostgreSQL was verified separately from this paused-process limitation.

Normal shutdown preserves the named data volumes. Existing volumes retain their initialized credentials; changing `.env` does not change an existing database role. Redact sensitive output before sharing diagnostics. Resetting a volume is a deliberate data-deletion operation.

## Development conventions

Use lifespan to create/dispose pooled resources. Scope sessions to requests/use cases; services explicitly commit or roll back, and concurrent tasks use separate sessions. Await async I/O and put heavy computation behind a suitable execution boundary. Load response relationships explicitly.

Derive identity/ownership server-side and authorize every resource operation. Test two-account isolation with owned features. Specify expiration and logout/revocation for account work. Public response schemas expose only their intended fields.

Use grams, kilograms, minutes and kilometres consistently. Define numeric precision/rounding, timezone-aware event instants, user timezone and meal-log dates. Calculate nutrition totals, league scores and progress comparisons deterministically. Separate routine templates, completed activities and shared membership; reuse activity references and preserve community-copy provenance.

WebSocket feature work must authenticate participants, persist authoritative training changes and define reconnection/resynchronization. Use shared event infrastructure before scaling socket-serving processes. The management decisions and feature acceptance criteria define behavior requiring product-owner agreement.

Before handoff, run relevant checks, inspect the changed files, update setup instructions and report actual results and limitations. Foundation checks establish infrastructure behavior; end-to-end feature commitments require their own application demonstrations.

## Routine and exercise APIs

The backend increment for [Kinetix-012](https://github.com/kinetix-app/app/issues/4)
provides these authenticated routes. They reuse the configured Basic/Clerk adapter and
active local account; clients never supply an owner ID.

| Method and path | Behavior |
|---|---|
| `GET /api/v1/routines` | List only the current account's routine IDs/names. |
| `GET /api/v1/routines/{id}` | Read an owned routine, its ordered slots and exercise details. |
| `POST /api/v1/routines` | Save a routine and return its detail with status 201. |
| `PATCH /api/v1/routines/{id}` | Change its name and/or replace its ordered exercise selection. |
| `GET /api/v1/exercises` | Browse selectable gym exercises; optionally filter by `body_part`. |
| `GET /api/v1/exercises/body-parts` | Sorted distinct selectable body-part names for filter chips. |
| `GET /api/v1/exercises/muscle-groups` | Legacy target-muscle options. |
| `GET /api/v1/exercises/{id}` | Read a selectable gym exercise, instructions and media URLs. |

List routes accept `limit` (1–100, default 50) and `offset` (nonnegative, default 0).
Responses contain `items`, `limit` and `offset`, ordered by local ID. Continue pagination
until a page has fewer than `limit` items. The repeatable `body_part` exercise filter (up to 30 values, 100
characters each) matches `body_parts` case-insensitively, ignoring surrounding whitespace:
`GET /api/v1/exercises?body_part=CHEST&body_part=BACK`. Multiple values match **any**
selected body part (OR); duplicate/case variants do not duplicate exercises. Omitted/blank filters return all selectable
exercises, including those without body-part metadata. The legacy `muscle_group` filter
still matches target muscles for existing API clients; the application uses body parts.
Exercise lists also accept `name` (up to 200 characters); routine lists accept `name`
(up to 150). Name search is a case-insensitive literal substring, ignoring surrounding
whitespace. `%` and `_` are ordinary characters. Name, body-part selection and legacy muscle filters combine with AND, before pagination.

Exercise lists project only `id`, `name`, `activity_type`, `body_parts`, `target_muscles`,
`equipments` and `image_url` in SQL and in the summary DTO. Instructions, overview and
media variants remain on exercise detail and nested routine detail. Body-part options
come from the full accessible catalogue independently of name search and pagination;
private/non-gym exercises cannot disclose filter options.

Selectable exercises are the explicitly seeded global V2 gym catalogue
(`source=ascend_edb_v2`, external ID and import timestamp present) and the account's own
gym exercises. Another account's exercises and unowned manual records are excluded;
nullable ownership alone does not publish a record. The same policy applies to list,
detail and routine references. Seed at least eight catalogue exercises for the Sprint 1
demonstration using the command below; API startup does not seed data.

Create a routine with `POST /api/v1/routines`:

```json
{
  "name": "Upper body",
  "exercises": [{"exercise_id": 1}, {"exercise_id": 2}, {"exercise_id": 3}]
}
```

Use actual local IDs returned by the catalogue endpoint. Names are trimmed and must
contain 1–150 characters. A selection contains 1–500 exercise entries; one exercise is
valid and repetitions of the same exercise are allowed as distinct slots. Array order
becomes consecutive positions starting at 1. Unknown request fields are rejected.

Routine detail returns `id`, `name` and `exercises`. Each slot contains its own `id`,
`exercise_order`, nested `exercise` details, `notes`, `default_sets`, resolved `sets` and
`sets_source` (`routine` or `latest_session`). Exercise details omit ownership and internal
import identifiers. Media URLs are returned as stored; production delivery authorization
still requires the deployment setup described below.

PATCH omission leaves a field unchanged; explicit `null`, blank names, empty selections
and empty patches are rejected. When replacing the selection, send an existing slot's
`id` to retain it during reordering, alongside its `exercise_id`:

```json
{
  "name": "Upper body revised",
  "exercises": [{"id": 12, "exercise_id": 2}, {"exercise_id": 4}]
}
```

Slot IDs must belong to this routine and appear at most once. An omitted/null slot ID
creates a new slot; existing slots omitted from the replacement are removed. Retaining
a slot with the same exercise preserves its notes/default sets. Changing its exercise
clears incompatible defaults. Selections may include `sets: [{"reps": 8, "weight_kg": "80.00"}]` to save gym defaults.
Set order determines set numbers; repetitions are positive integers and kilograms are
positive decimals (at most two decimal places and 999999.99 kg). Each slot supports
up to 100 sets. Omitting `sets` preserves defaults for a retained exercise; `sets: []`
clears defaults and explicit `null` is rejected. Set changes commit with the routine
transaction. Notes editing and session recording remain separate work.

Loading a routine resolves guidance from the current account's latest completed occurrence
of each exercise with at least one recorded set, across routines and blank workouts.
Ordering is finish time, session ID, exercise position and entry ID descending. Repeated
routine exercises receive the same latest exercise guidance; exercises without history
fall back to saved defaults. Active sessions and other accounts are excluded. Saved
defaults remain separately available in `default_sets`; decimal measurements serialize
as strings. Reads never update defaults or recorded results. Template updates serialize
on the routine row; detail reads hold a shared row lock while loading the template.
Performed exercises have no relationship to routine slots. Removing/replacing a template
slot cannot change historical exercises or sets.

Missing/inaccessible routines and exercises return 404. Invalid fields or unavailable
exercise/slot selections return 422, without disclosing private records. Invalid credentials
return 401, inactive accounts 403, and unavailable authentication 503. Writes commit
atomically or roll back. Routine deletion and exercise authoring remain separate work. Backend routes alone do not complete the integrated session acceptance checks.

## Completed workouts (Kinetix-013/014/016)

The frontend keeps one account-scoped ongoing draft, synchronized through the draft APIs
below. Legacy `POST /api/v1/sessions`
submits the complete workout once, with a client-generated UUID, timezone-aware
`started_at`/`ended_at`, optional `routine_id`, and ordered `exercises` containing
`exercise_id` and actual `sets`. Each set supplies positive integral `reps` and
`weight: {"value": "100.00", "unit": "lb"}`. Weights require decimal text; ownership
always comes from authentication. Array order defines exercise/set order, including
repeated exercises. Supported measurements in this increment are weight/repetitions;
other formats remain deferred to [app#63](https://github.com/kinetix-app/app/issues/63).

Submission validates source access and persists the completed session, entries and sets
in one transaction. The unique `(user_id, client_session_id)` and normalized payload
fingerprint recover concurrent retries and lost responses: first creation returns 201,
identical retries return 200 and the same ID, changed content under the same key returns
409. Retry checks precede current template/catalogue validation so later source changes
do not invalidate a previously persisted workout. Clients must retain the original UUID,
recorded finish instant and frozen payload until success is confirmed.

`GET /api/v1/sessions?limit=50&offset=0&weight_unit=kg` returns
`{items, limit, offset}`, ordered by finish instant descending and ID descending;
limit is 1–100. `GET /api/v1/sessions/{id}?weight_unit=lb` reopens owned actual results.
Both use the same completed-session DTO, including ordered exercises and sets. Another
account's detail returns 404 and its workouts never appear in the caller's history.
The `title` is the source routine's name at completion, or `Training session` for
a standalone workout. Later edits to the routine leave the completed title intact.
Both responses include `total_reps` and `total_volume_kg`, using the same recorded
set totals as the workout posts feed.
Each set exposes canonical `weight_kg` with six decimal places plus explicitly labelled
`weight: {value, unit}` rounded to two display decimals. Routine detail/create/update also
accept `weight_unit=kg|lb`; planned-set inputs accept either legacy `weight_kg` or explicit
`weight`, and reject ambiguous dual fields. Pounds are never returned under `weight_kg`.
Conversion uses exactly 0.45359237 kg/lb and ROUND_HALF_UP once at six-decimal storage
precision; 100 lb persists as 45.359237 kg and displays as 100.00 lb or 45.36 kg.

Revision `20261024_01` expands planned/actual weights to NUMERIC(12,6), adds nullable
legacy-compatible idempotency fields and source-slot ownership provenance, and converts
training event timestamps to timezone-aware values. No previous timezone semantics were
recorded for naive legacy training events: the explicit migration policy interprets them
as UTC using `AT TIME ZONE 'UTC'`, independent of the database connection timezone.
Existing values and historical rows are preserved. Revision `20261025_02` subsequently
removes the source-slot relation and retained-slot table, while keeping session-level
`routine_id` origin, catalogue exercise references and every performed measurement.
Downgrading reduces weight precision to two decimal places and removes idempotency and
retained-slot metadata; review data-loss implications before downgrading.

Empty/partial draft completion persists only confirmed sets, retaining every selected
exercise even when no set was confirmed. An unavailable routine origin returns 422 and
leaves the draft intact. Browser/native acceptance is reported separately from backend
integration verification.

## Workout posts feed

Accounts can write an optional caption and description, attach up to five images and
share a completed workout. A post needs at least one of these. Likes and comments are
attached to the post. The public feed includes PUBLIC posts from active accounts,
visible FRIENDS posts and the caller's own posts. PRIVATE posts are visible only to their author. LEAGUE
visibility and league-penalty posts are reserved for FriendsLeague and are rejected by the
API. A blocked or deleted author's posts disappear from other accounts' feeds. Any
post the caller cannot see returns 404 from every route, including likes, comments and
media.

| Route | Behavior |
|---|---|
| `GET /api/v1/posts?limit=20&before_id=` | Feed, newest first (ID descending). Limit 1–50. Pass the returned `next_before_id` as `before_id` for the next page; it is `null` on the last page. The cursor stays stable while new posts arrive. |
| `POST /api/v1/posts` | `multipart/form-data`: optional `training_session_id`, `caption` (≤160 characters), `description` (≤2200 characters), `visibility` (`PUBLIC` default, `FRIENDS` or `PRIVATE`) and repeated `files` (0–5 JPEG/PNG/WebP images, ≤5 MiB each, ≤25 MiB per request). Trims both text fields. Returns 201 with the post. |
| `GET /api/v1/posts/workout-options?selected_session_id=` | Up to five newest unshared completed workouts owned by the caller. Returns an eligible explicit selection separately, or null. |
| `GET /api/v1/posts/{id}` | One visible post. |
| `GET /api/v1/posts/{id}/workout` | The same title and totals with ordered exercises and recorded sets. Exercise image URLs are returned when the viewer can access the exercise. |
| `GET /api/v1/posts/{id}/workout-template` | A visible workout’s title and ordered selectable exercises with recorded sets. Returns skipped exercise names and 404 for invisible or workout-free posts. |
| `DELETE /api/v1/posts/{id}` | Author only (403 otherwise). Removes the post, its likes, comments and file rows in one transaction, then deletes its blobs. The workout itself is kept and can be shared again. |
| `PUT` / `DELETE /api/v1/posts/{id}/like` | Idempotent like/unlike. Returns `{liked, like_count}`. |
| `GET /api/v1/posts/{id}/comments?limit=50&after_id=` | Oldest first. Limit 1–100. Pass `next_after_id` as `after_id` for the next page. |
| `POST /api/v1/posts/{id}/comments` | JSON `{"comment": "..."}`, 1–1000 characters after trimming. Returns 201. |
| `DELETE /api/v1/posts/{id}/comments/{comment_id}` | The comment author or the post author (403 otherwise). |
| `GET /api/v1/posts/{id}/media/{file_id}` | Authenticated JPEG bytes with `Cache-Control: private, max-age=3600`. |

Each post response contains `author {id, display_name}`, `media [{id, type, order, url}]`,
`like_count`, `comment_count`, `liked_by_me`, `is_mine` and a `workout` summary.
`caption` and `description` are strings and may be empty. Older clients can still
submit `text` without `description` and read `text` as an alias of `description`.
`media[].url` is the authenticated API path above; clients send their normal
Authorization header to load images. The private bucket URL is never returned.

**Workout summary.** Only the caller's own completed workout (`ended_at` set) can be
shared, otherwise 422. A workout can have at most one post (409 on a second share,
enforced by a UNIQUE `post.training_session_id`). The summary returns the saved workout
`title` and computes totals from recorded history on every read: `duration_seconds` (end − start), `exercise_count`, ordered
exercise names, `set_count`, `total_reps` and `total_volume_kg`. Volume is the sum of
`reps × weight_kg` over recorded sets, rounded half-up to 0.01 kg and returned as decimal
text. Completed workouts store only confirmed sets, so every recorded set counts.

**Images.** Uploads are validated and normalized like profile pictures: the declared type
must match the decoded format, images above 16 megapixels are rejected (422), EXIF
orientation is applied, all metadata (including GPS location) is discarded and the
result is re-encoded as JPEG, at most 1440 px on the longest side. Blobs go to the
private `AZURE_STORAGE_POST_CONTAINER` under `posts/{user_id}/{uuid}.jpg`. Normalization
and uploads happen before the database transaction. If an upload or the insert fails,
the service deletes the blobs it uploaded and no post row remains. Text-only posts work
without storage configuration. Uploading or reading images without storage returns 503.

Revision `20261120_01` adds nullable `post.training_session_id` (UNIQUE, references
`training_session`) and indexes on `file.post_id` and `post_comment.post_id`. Existing
posts keep a NULL reference. Downgrading drops the workout link.

Revision `20261122_04` adds empty captions to existing posts and preserves their
legacy text as the description. Existing workouts get the linked routine's current
name when available, with `Training session` as the fallback. Subsequent routine
renames leave the backfilled title intact. Downgrading drops captions and saved titles.

Profile pictures are visible to every signed-in account so people with the same name can
be told apart. `author`, comment authors and every person object carry `has_picture`; when
true, clients load `GET /api/v1/people/{id}/picture` (authenticated JPEG,
`Cache-Control: private, max-age=300`). Missing photos and blocked or deleted accounts
return 404. Pictures are still stored in the private profile container and never exposed
through a public URL.

## Friends

Friendship is mutual: one account sends a request and the other accepts. Each pair has a
single `friendship` row stored with the lower account ID first (`user_low_id`,
`user_high_id`), so duplicate or crossed requests cannot exist. `requester_id` records who
asked, and `status` is `PENDING` or `ACCEPTED`. Requesting someone who already asked you
accepts immediately. Only active accounts that have set a display name can be found,
requested or listed; blocked or deleted accounts disappear from lists and searches.

| Route | Behavior |
|---|---|
| `GET /api/v1/people?q=&limit=20` | Case-insensitive name search (at least 2 characters after trimming, wildcards are literal). Excludes the caller. Each result includes `relationship`: `none`, `outgoing`, `incoming` or `friends`. |
| `GET /api/v1/people/{id}` | `{id, display_name, relationship, friend_count}`; `relationship` is `self` for the caller. 404 for unavailable accounts. |
| `GET /api/v1/friends?limit=50&offset=0` | Accepted friends, ordered by name, with `since`. |
| `GET /api/v1/friends/requests` | `{incoming, outgoing}` pending requests, newest first. |
| `POST /api/v1/friends/requests` | JSON `{"user_id": 2}`. Returns the resulting relationship (`outgoing`, or `friends` when the other person had already asked). Idempotent. 422 for yourself, 404 for unavailable accounts. |
| `POST /api/v1/friends/requests/{id}/accept` | Accepts an incoming request (idempotent once friends). 404 when there is no incoming request. |
| `DELETE /api/v1/friends/{id}` | Unfriends, declines or cancels, whichever applies. Always 204. |

**Friends-only posts.** Posts accept `visibility=FRIENDS`. Such posts are visible to their
author and to the author's accepted friends while the author is active. Unfriending removes
access immediately. `GET /api/v1/posts?scope=friends` limits the feed to the caller's own
posts and their friends' posts; the default `scope=everyone` keeps the public feed.

Revision `20261120_03` adds the `friendship` table (indexed on `user_high_id`; the primary
key covers `user_low_id`) and documents the `FRIENDS` visibility. Downgrading turns
friends-only posts into private posts so they never widen their audience.

## Exercise catalogue and media seeding

[Issue #16](https://github.com/kinetix-app/app-rest/issues/16) adds an explicit seed operation; startup and migrations never download or import exercise data. The external [exercices repository](https://github.com/kinetix-app/exercices) contains an ExerciseDB V2 export: `index.json` maps 200 provider IDs to directories, each containing `data.json`, `video.mp4` and four JPEG variants under `images/` (`360p.jpg`, `480p.jpg`, `720p.jpg`, `1080p.jpg`). The supplied snapshot totals 200 exercises and 1,000 media files. Keep this repository and its media outside the backend Git/build context, and retain its source attribution and usage terms. The seed command reads only local assets, without provider network requests.

### Storage configuration

Copy the storage block from `.env.example` into an existing local `.env`. Azurite uses a fixed, public **emulator-only** account/key declared in Compose and the example environment. It runs blob service only, pins Azurite 3.37.0 by digest, disables access logging/telemetry and persists data in `azurite-data`. The SDK explicitly selects storage API `2026-06-06` supported by this emulator; dependency upgrades must preserve that compatibility.

| Setting | Purpose |
|---|---|
| `AZURE_STORAGE_CONNECTION_STRING` | Backend-only Azure SDK connection string. The example points the host API at Azurite. |
| `AZURE_STORAGE_CONTAINER` | Blob container name, default `exercises` |
| `AZURE_STORAGE_PROFILE_CONTAINER` | Separate private profile image container, default `profile-pictures`; never receives public-read mode |
| `AZURE_STORAGE_POST_CONTAINER` | Separate private post image container, default `post-media`; images are served only through the authenticated posts API |
| `AZURE_STORAGE_MEDIA_BASE_URL` | Client-reachable account/CDN root, without container, credentials, query or SAS; used to build stored media URLs |
| `AZURE_STORAGE_LOCAL_PUBLIC_READ` | Default false; `.env.example` enables blob-only anonymous reads for local demonstration; forbidden in production |
| `AZURE_STORAGE_TIMEOUT_SECONDS` | Per-upload/container operation timeout, default 30 seconds; readiness uses `DATABASE_TIMEOUT_SECONDS` |
| `AZURE_STORAGE_COMPOSE_CONNECTION_STRING` | Connection string for the local Compose API, using the Azurite service endpoint |
| `AZURITE_PORT`, `AZURITE_BIND_ADDRESS` | Host publishing, defaults `10000` / `127.0.0.1` |

Supply the connection string and media base URL together. When both are omitted, the API runs without a storage client and storage-dependent routes return 503. The application manages the client in its lifespan. Readiness checks the account before any containers need to exist.

For real Azure storage, see the [production deployment guide](docs/deployment.md). For local demonstrations, blob-only anonymous reads apply only when creating a new exercise container. Configure an existing private exercise container explicitly before seeding in that mode.

For physical-device demonstrations, set `AZURITE_BIND_ADDRESS=0.0.0.0` on a trusted LAN and use the host's LAN address in `AZURE_STORAGE_MEDIA_BASE_URL`. The backend endpoint stays in its connection string. Changing the media root requires rerunning the seed to refresh stored URLs. If you change `AZURITE_PORT`, update the host connection string and media URL too.

### Validate, migrate and import

From the backend checkout, with the export in the sibling `exercices` directory:

```sh
uv run --locked --no-build python -m app.features.training.seed --dataset ../exercices --validate-only
make seed-exercises DATASET=../exercices
```

The Make command starts PostgreSQL/Azurite and applies migrations before importing. Alternatively, start the dependencies, apply `make migrate`, then invoke `uv run --locked --no-build python -m app.features.training.seed --dataset ../exercices`. Validation alone requires no database or storage configuration.

For the packaged API, mount the export read-only instead of copying media into the image:

```sh
docker compose up -d --wait postgres azurite
docker compose run --rm --build api alembic upgrade head
docker compose run --rm -v "$(cd ../exercices && pwd):/seed:ro" api python -m app.features.training.seed --dataset /seed
docker compose up -d --build --wait api
```

Successful import prints `{"status": "seeded", "exercises": 200, "media": 1000}` for the supplied snapshot. Invalid/incomplete input and storage/database failures exit nonzero, print a redacted diagnostic and never print success. The whole export is validated before remote writes, including index coverage, provider IDs, every expected asset, default-image mapping and unmapped files. Unknown metadata is rejected rather than silently lost. Correct the input or unavailable service and rerun.

Images/videos use immutable names containing their SHA-256 under `ascend_edb_v2/<external-id>/`. Reruns check existing blob identity/content type and reuse matching blobs. All uploads finish before a single short catalogue transaction, so failed uploads never commit new references and failed database writes roll back the entire import. A failed run can leave unreferenced blobs; safe retries reuse them. Changing media can leave older unreferenced blobs; automated deletion is deliberately outside the seed command.

The import retains provider classifications, instructions, tips, variations, related IDs and other supplied descriptive fields. It maps this gym catalogue to `activity_type=gym`, keeping provider `exerciseType` separate in `exercise_types`. `image_url` identifies the provider's default variant, `image_urls` preserves every resolution, and `video_url` points to the uploaded MP4. Source/external ID and timezone-aware `imported_at` preserve provenance. A partial unique index and upsert retain local IDs across reruns/concurrent imports. Manual and user-owned records remain independent, even when they carry the same external ID. The migration fails if pre-existing global imports have duplicate source/external IDs; resolve those records explicitly before retrying it.

### Verify the import

Rerun the command and confirm stable IDs/counts, then restart PostgreSQL/Azurite without removing volumes and inspect the same records/media. Open a stored `image_url` and `video_url` in the intended client; the blob service sets JPEG/MP4 content types and supports video range requests. Stop Azurite and verify readiness becomes 503 while liveness remains 200; restart it and verify recovery. Inspect `exercise` rows with `source='ascend_edb_v2' AND user_id IS NULL`, including `image_urls`, to reconcile all records and variants.

Run the full suite, including real storage upload/readback tests against unique test-owned containers:

```sh
docker compose up -d --wait postgres-test azurite
TEST_DATABASE_URL=postgresql://fitness_test:fitness_test_local@127.0.0.1:55432/fitness_test \
TEST_AZURE_STORAGE_ACCOUNT_NAME=kinetixlocal \
TEST_AZURE_STORAGE_ACCOUNT_URL=http://127.0.0.1:10000/kinetixlocal \
TEST_AZURE_STORAGE_ACCOUNT_KEY=a2luZXRpeC1sb2NhbC1kZXZlbG9wbWVudC1vbmx5LWtleQ== \
uv run --locked --no-build pytest
```

PostgreSQL seed tests use isolated test-owned schemas. Blob integration tests create and delete only uniquely named `test-exercises-*` containers; they skip when the explicit test account name/URL/key are absent. CI supplies both PostgreSQL and Azurite, so these checks run there.


## Resumable workout drafts

`PUT /api/v1/session-drafts/{client_session_id}` saves an owned snapshot with `name`,
`routine_id`, timezone-aware `started_at`, and ordered `exercises`. Exercises include a
UUID `client_id`, `exercise_id` and ordered `sets`; each set includes a UUID `client_id`,
nullable `reps` and `weight`, and `completed`. Confirmed sets require positive repetitions
and an explicit weight measurement. Invalid unconfirmed values are normalized to null.
Unconfirmed values stay outside completed history and exercise guidance. Clients save
on confirmation and invalidate it when editing a value. Identical PUT retries are safe;
existing start times and routine origins are immutable. The response echoes the saved
snapshot, client UUID and `state: "draft"`.

`GET /api/v1/session-drafts` returns the active owned snapshot or JSON null, allowing
resumption after restarting. There is at most one active draft per account; starting
another UUID returns 409. `DELETE /api/v1/session-drafts/{uuid}` discards an owned draft,
returns 204 on retries or inaccessible UUIDs, and never deletes completed workouts.

`POST /api/v1/session-drafts/{uuid}/finish` accepts
`{ "ended_at": "...", "update_routine": false }`. Completion atomically creates the
completed aggregate, prunes every unconfirmed set from the retained snapshot, and retires
the draft. Exercise order and zero-set entries remain; an empty exercise list is allowed
when keeping the routine. Invalid times or unavailable sources return 422 with the draft
intact. Another account cannot read, complete or discard the owner's draft.

When `update_routine` is true, an owned routine origin and nonempty exercise list are
required. The same transaction replaces that routine's exercise selection/order and
default sets from the completed workout while preserving its name. Only confirmed sets
become defaults; zero-set exercises remain selected. With false, the template is unchanged.
The finish time and update decision are frozen: identical retries return the same
completed workout without reapplying template changes; a different time/decision,
editing a completed draft or discarding it returns 409. Mutable draft operations
serialize on the account row.

`GET /api/v1/exercises/{exercise_id}/last-configuration?weight_unit=kg` returns
`{exercise_id, sets}` for a selectable exercise. It selects the account's latest completed
exercise occurrence with at least one set, ordered by finish time/session ID and then
exercise position/entry ID descending. No history returns an empty set list. This lookup
also supplies routine guidance. It never reads another account's history or inserts
guidance as performed values; clients display these values as placeholders only.

Revision `20261025_01` adds draft snapshots. Revision `20261025_02` removes performed
exercise-to-routine-slot links and retained-slot metadata, cleans obsolete slot keys from
old JSON snapshots, and records the finish update decision. Existing workouts, exercises,
sets, catalogue references and session-level routine origins are preserved. Draft input
silently drops old slot keys; legacy `POST /sessions` privately accepts them solely for
pre-migration fingerprint retry compatibility, and never persists a slot association.
Active API schemas and responses omit slot references. Downgrading `20261025_02` cannot
reconstruct removed links; downgrading `20261025_01` removes snapshots/retry pointers but
keeps completed workouts. Browser/native acceptance is verified separately.
