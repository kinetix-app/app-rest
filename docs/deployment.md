# Production deployment

Run the repository's runtime image with a managed PostgreSQL database and an Azure
Blob Storage account. The image starts Uvicorn on port 8000. Configure HTTPS at the
hosting platform's ingress and route traffic to that port. The checked-in Compose
file is for local development and starts PostgreSQL and Azurite.

## Environment and secrets

Inject these values into the API and catalogue seed jobs using the hosting platform's
secret store. The GitHub migration job only needs database credentials and TLS
configuration. It can use a separate PostgreSQL role with schema-change privileges.

| Secret | Value |
| --- | --- |
| `DATABASE_URL` | PostgreSQL connection URI, for example `postgresql://USER:ENCODED_PASSWORD@DB_HOST:5432/DB_NAME?sslmode=verify-full`. Percent-encode reserved characters in credentials. For `verify-full`, mount the provider's CA bundle and set `PGSSLROOTCERT` to its readable path in the API and catalogue seed jobs. |
| `AZURE_STORAGE_CONNECTION_STRING` | Azure Blob SDK connection string, for example `DefaultEndpointsProtocol=https;AccountName=ACCOUNT;AccountKey=KEY;EndpointSuffix=core.windows.net`. |
| `CLERK_SECRET_KEY` | Backend secret from the production Clerk instance. |

Set the following regular environment variables.

| Setting | Production value |
| --- | --- |
| `APP_ENV` | `production` |
| `CLERK_ISSUER` | HTTPS origin of the production Clerk instance |
| `AZURE_STORAGE_MEDIA_BASE_URL` | HTTPS account or delivery root reachable by the client, before the container name |
| `AZURE_STORAGE_LOCAL_PUBLIC_READ` | `false` |
| `AZURE_STORAGE_CONTAINER` | Exercise catalogue container, defaults to `exercises` |
| `AZURE_STORAGE_PROFILE_CONTAINER` | Private profile, routine and league pictures container, defaults to `profile-pictures` |
| `AZURE_STORAGE_POST_CONTAINER` | Private post media container, defaults to `post-media` |
| `CORS_ALLOWED_ORIGINS` | JSON array of permitted browser origins, when a browser frontend is deployed |

See the [authentication runbook](authentication.md) for Clerk configuration.

For Neon, copy the PostgreSQL connection URI into `DATABASE_URL`, keeping
`sslmode=require&channel_binding=require`. The API and Alembic use Psycopg 3
and pass both parameters to libpq. URLs starting with `postgresql://` work
directly in both Render and the GitHub migration workflow.

## Run production migrations

1. Create a GitHub Actions environment named `production`. Add its `DATABASE_URL`
   secret with a PostgreSQL role that can apply the revisions. For `sslmode=verify-full`,
   add `DATABASE_CA_PEM` containing the provider's PEM CA bundle. The workflow writes
   it to a temporary file and sets `PGSSLROOTCERT`. Configure the environment's
   deployment branch and reviewer rules as appropriate.
2. Once the workflow and release revision are on the default branch, open
   **Actions → Migrate production database → Run workflow**. Run it before routing
   traffic to the new API. The workflow runs `alembic upgrade head` and verifies
   that all head revisions are applied. It serializes production migration runs.
3. The GitHub-hosted runner must be able to reach PostgreSQL. For a private database,
   use a runner with access to that network, or run the same Alembic commands in a
   release job on the hosting platform.

Build the API image from the migrated release revision. Start the API with the
image's default command and check `/health/live` and `/health/ready`. Then verify
authenticated access with a production Clerk session.

## Seed production data

Run one-off jobs from the backend runtime image for the deployed release, after
migrations. Inject the production settings above and run the jobs from a network
that can reach PostgreSQL and Azure Blob Storage.

For the shared food catalogue, run:

```sh
python -m app.features.nutrition.seed
```

For the exercise catalogue, mount the approved exercise export read-only at
`/seed`, including its `index.json` and the image and video files. Validate it
first, then import it:

```sh
python -m app.features.training.seed --dataset /seed --validate-only
python -m app.features.training.seed --dataset /seed
```

The validation step checks the local export without contacting either service.
The import uploads media first, then writes catalogue records in one database
transaction. Reruns reuse matching blobs and update the existing imported rows.
Verify a seeded image and video from the deployed client.

## Blob URLs and client access

The connection string sets the Azure endpoint and authorizes the backend. With
`AccountName=kinetixprod` and `EndpointSuffix=core.windows.net` in an HTTPS
connection string, a blob lives at
`https://kinetixprod.blob.core.windows.net/<container>/<blob-path>`.
An explicit `BlobEndpoint` in the connection string sets the origin instead.
[Azure Blob resource URI reference](https://learn.microsoft.com/en-us/rest/api/storageservices/fileservices/naming-and-referencing-containers--blobs--and-metadata)

For exercise images and videos, PostgreSQL stores
`<AZURE_STORAGE_MEDIA_BASE_URL>/<exercise-container>/<encoded-blob-path>`.
For example, with `AZURE_STORAGE_MEDIA_BASE_URL=https://media.example.com` and the
default exercise container, clients receive
`https://media.example.com/exercises/<encoded-blob-path>`. The seed creates a
private exercise container by default. Configure the delivery endpoint to read
from the private Azure origin and serve those paths before seeding. The stored
URLs carry no SAS token and do not grant direct access to private blobs.
Rerun the import if the delivery root changes.

Post images, profile pictures, routine covers and league pictures live in private
Azure containers. Clients fetch them through authenticated backend API routes.
