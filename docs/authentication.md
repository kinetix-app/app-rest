# Clerk authentication and account setup (ACC01)

Tracking issue: [kinetix-app/app-rest#1](https://github.com/kinetix-app/app-rest/issues/1). This backend increment implements token validation, first-access account creation, private account reads and profile edits. Clerk dashboard configuration, native sign-in and device/session demonstrations still need completion. Google, Apple and Email OTP all yield Clerk session tokens and use the same API path.

## 1. Configure the development instance

1. Create a Kinetix application in the [Clerk Dashboard](https://dashboard.clerk.com/). Start with the development instance; keep production configuration and accounts separate.
2. Under **User & authentication**, enable email sign-up/sign-in with **email verification codes**. Disable passwords and email verification links before creating pilot users. Disabling passwords does not stop existing password users from using them. Leave other methods outside the agreed initial scope. [Authentication settings](https://clerk.com/docs/guides/configure/auth-strategies/sign-up-sign-in-options)
3. Under **Native applications**, enable the Native API and register the intended applications. Choose stable identifiers before generating provider credentials. The current frontend uses provisional `com.example.kinetix` identifiers and the `kinetix` scheme; coordinate final values in the frontend repository. [Expo quickstart](https://clerk.com/docs/expo/getting-started/quickstart)
4. From **API keys**, copy the public publishable key to the frontend's ignored environment as `EXPO_PUBLIC_CLERK_PUBLISHABLE_KEY=pk_test_...`. Obtain the instance's exact **Frontend API URL** for the backend issuer, for example `https://your-instance.clerk.accounts.dev`.
5. Keep Clerk's ordinary session-token claims unchanged: `iss`, `sub`, `sid`, `exp`, `nbf`, `iat`. The app should call its SDK's ordinary `getToken()` and attach that session token; no custom JWT template is needed for these APIs.

The backend uses Clerk’s Python SDK to fetch signing keys from the Clerk Backend API with `CLERK_SECRET_KEY`. Copy the secret key from the same instance’s **API keys** page into backend configuration only. Never use it in the mobile bundle. No separate JWKS URL or static public key is needed.

## 2. Configure Google

1. In Clerk **SSO connections**, add Google for all users, enable sign-up/sign-in and use custom credentials for native Google integration.
2. Create a Google Cloud project and configure its OAuth consent screen/test users as required by Google.
3. Create a **Web application** OAuth client even for a native app. Add the exact Authorized Redirect URI shown by Clerk. Put the web Client ID and Client Secret into Clerk's Google connection.
4. Create an **Android** client for the chosen package and SHA-1 signing-certificate fingerprint, and an **iOS** client for the chosen Bundle ID when supporting iOS. Register the native apps in Clerk too: Android registration uses SHA-256, while iOS registration needs the App ID prefix/Team ID and Bundle ID. Register the certificates used by each development/release build.
5. Give the frontend developer the public web/iOS/Android client IDs. Follow the current Clerk Expo plugins/native-build instructions; the Google client secret stays in Clerk, never the mobile bundle.

Source: [Clerk native Google setup](https://clerk.com/docs/expo/guides/configure/auth-strategies/sign-in-with-google).

## 3. Configure Apple

1. Establish the Apple Developer account/team and app identifier; enable Sign in with Apple for the intended native app.
2. Register the iOS native application in Clerk with the actual App ID prefix/Team ID and Bundle ID.
3. Add Apple under Clerk **SSO connections** and enable it for sign-up/sign-in.
4. Coordinate the Expo native capability/plugins and development build with the frontend developer. Validate on a physical iOS device.
5. If using browser/hosted Apple sign-in (including an eventual Android flow), configure the additional Apple Services ID, key and callback settings. These are distinct from native iOS setup. Configure Apple Private Relay email sources if sending messages to relay addresses.

Source: [Clerk native Apple setup](https://clerk.com/docs/expo/guides/configure/auth-strategies/sign-in-with-apple). Apple can withhold profile details after initial authorization; nullable local fields are filled through Kinetix profile onboarding.

## 4. Configure and run app-rest

Add these values to the ignored backend `.env` (example only):

```dotenv
CLERK_ISSUER=https://your-instance.clerk.accounts.dev
CLERK_SECRET_KEY=sk_test_...
CLERK_AUTHORIZED_PARTIES=[]
CLERK_CLOCK_SKEW_SECONDS=5
# Only set when the chosen token contract includes this audience:
# CLERK_AUDIENCE=kinetix-api
```

`CLERK_ISSUER` must be an HTTPS origin without credentials, query strings or paths. It is the Clerk instance origin, not the FastAPI URL or the Google issuer. A trailing slash is normalized away. Empty issuer, secret-key and audience values from Compose mean unconfigured. Production requires both issuer and secret key; development/test can run health routes without them but protected bearer requests return 503.

`CLERK_AUTHORIZED_PARTIES` is a JSON list of exact permitted **token `azp` values**, not the API's CORS allowlist. Native session tokens can omit `azp`; those are accepted after all other checks. If `azp` is present it must match the configured list, so `[]` rejects every token with `azp`. During the pilot, inspect only the required claim values locally and set actual permitted origins; never log/share a complete bearer token. For example, a web preview may require `["http://localhost:8081"]` if that exact value is issued. [Clerk verification rules](https://clerk.com/docs/guides/sessions/manual-jwt-verification)

Run from the backend repository using its pinned uv:

```sh
uv sync --locked --no-build
docker compose up -d --wait postgres
uv run --locked --no-build alembic upgrade head
uv run --locked --no-build uvicorn app.main:app --reload --no-access-log
```

Compose's optional `app` profile passes the same Clerk settings into the packaged API. The backend needs outbound HTTPS access to its configured Clerk instance. Migration commands need only the database settings in development; production settings validation still requires the issuer.

If the installed uv is older than the repository's pin, run the pinned version without changing the project requirement:

```sh
uv tool run --from uv==0.12.13 uv sync --project . --locked --no-build
```

For production, create/configure the separate Clerk production instance, satisfy Clerk's domain/DNS requirements, use production provider credentials and publishable key, and set the backend to that instance's issuer. Confirm session limits and email behavior on the chosen plan. [Production setup](https://clerk.com/docs/guides/development/deployment/production)

## 5. API and data contract

```text
Google / Apple / Email OTP -> Clerk session
Expo app -> Authorization: Bearer <Clerk session JWT> -> FastAPI
FastAPI -> verified issuer/subject -> local user UUID -> owned business operations
```

The verifier accepts only RS256 session JWTs with required time/user/session claims, the exact configured issuer and permitted `azp` when present. Pending sessions and machine/API-key credentials are rejected.

`ClerkVerifier.verify()` calls the SDK’s `verify_token_async()` with the backend secret key, optional audience and clock skew. The SDK retrieves signing keys, caches them for five minutes, refreshes after a signature mismatch, verifies the RS256 signature and supplied `exp`/`nbf`/`iat` claims, and returns a dictionary. Its cache is process-wide; run each deployed process against one Clerk instance.

The Python SDK disables issuer verification and does not require time claims. Its `RequestState.to_auth()` creates version-specific auth dataclasses with optional fields; it does not validate their types or presence. A small strict `SessionClaims` model therefore requires the session fields before we compare issuer, status and authorized party and create `VerifiedIdentity`. Authorized-party validation stays here because the SDK’s allowlist rejects missing `azp`, while native tokens may omit it.

See the [Python SDK source](https://github.com/clerk/clerk-sdk-python/tree/main/src/clerk_backend_api/security) and [Python authentication guide](https://clerk.com/articles/how-to-add-authentication-to-a-python-backend). The repository lockfile pins the SDK version used by tests. No application-owned key cache or HTTP client is needed. Key-service failures return 503; invalid tokens return 401. SDK HTTP timeouts/retries and cache refresh behavior apply. No online Clerk session-revocation check occurs.

| Table | Ownership and constraints |
|---|---|
| `users` | Internal UUID; active/blocked/deleted status; UTC-aware timestamps |
| `auth_accounts` | UUID; user FK; unique `(issuer, subject)`; deletion restricted to preserve identity denial |
| `profiles` | One row per user; nullable display name/timezone; timestamps |

Provisioning writes all three records inside one transaction/savepoint, after token validation. Concurrent first requests resolve the same UUID; a losing mapping insert rolls back its provisional user/profile. Existing profiles are never overwritten from provider claims. PostgreSQL's default READ COMMITTED isolation is required for conflict recovery. Multiple methods linked to one Clerk user resolve the same mapping; separate Clerk users are never merged by email.

### GET /api/v1/me

First valid access intentionally creates a minimal local account. Subsequent access reuses it, including after token renewal or email changes. Return:

```json
{
  "id": "<internal-user-uuid>",
  "status": "active",
  "created_at": "<UTC timestamp>",
  "profile": {
    "display_name": null,
    "timezone": null,
    "updated_at": "<UTC timestamp>"
  }
}
```

### PATCH /api/v1/me/profile

```json
{"display_name": "Alice", "timezone": "Europe/Madrid"}
```

Returns the same private account response. Omitted fields stay unchanged; explicit `null` clears a field. Display name is trimmed and limited to 1–100 characters when supplied. Timezone must be a valid IANA identifier. Unknown fields, including a submitted user ID/status, return 422. Empty `{}` is a no-op. The authenticated UUID supplies ownership; users cannot choose another account.

| Status | Meaning |
|---|---|
| 401 + Bearer challenge | Missing, malformed, invalid, expired or untrusted session credential; no provisioning |
| 403 | Local account blocked/deleted; mapping remains denied and is not recreated |
| 422 | Invalid profile input |
| 503 + Retry-After | Unconfigured verifier or trusted key service unavailable; no provisioning |

`CurrentUser` in `app/core/auth/dependencies.py` is the shared dependency for future owned features. No `/register`, password/OTP-handling endpoint or second application token issuer is needed. Health endpoints remain public.

## 6. Complete the native pilot

- [ ] Real email-code sign-up/sign-in, invalid/expired code and resend behavior.
- [ ] Google on agreed native platforms and Apple on iOS; cancellation/error handling.
- [ ] Authenticated `/me` creates one account; repeat access and renewal retain its UUID.
- [ ] Profile PATCH persists after API/app restart; Alice and Bob retain separate profiles.
- [ ] SDK-supported secure session storage, restoration and current-device logout; clear/cancel private cached state when changing accounts.
- [ ] Set verified authorized-party values for each flow; check expected issuer with separate development/production instances.

Logout/renewal live in the frontend Clerk SDK. This backend performs offline token verification: a token from a revoked session may remain accepted until its signed expiry plus the configured clock skew. The acceptable delay, all-device logout and any online revocation checks remain product decisions. Local account status is checked on every protected operation; operational blocking must update `users.status` while retaining the identity mapping. No public status-edit endpoint is exposed.

Account linking/unlinking UI, recovery policy, deletion/anonymization and re-registration policies are pending. There is no deletion API or Clerk webhook in this increment. Before enabling account deletion in the shipped app, implement signed/replay-safe idempotent `user.deleted` synchronization (or equivalent reconciliation), mark the local identity denied, and define treatment of business records. Deletion only in the Clerk dashboard does not immediately synchronize local status. Do not treat ACC01 as complete until its native and lifecycle acceptance cases have evidence.

## 7. Backend verification

```sh
uv lock --check
uv run --locked --no-build ruff check .
uv run --locked --no-build ruff format --check .
docker compose --profile test up -d --wait postgres-test
TEST_DATABASE_URL=postgresql+asyncpg://fitness_test:fitness_test_local@127.0.0.1:55432/fitness_test uv run --locked --no-build pytest
```

Tests use locally generated RSA keys and mock the SDK’s Backend API HTTP transport, isolating its key cache per test; PostgreSQL integration tests exercise real migrations, concurrent provisioning, rollback, account denial, profile persistence and isolation in the dedicated `_test` database. These checks establish backend behavior, not actual Clerk/native integration. Never send real provider credentials or fitness data to test fixtures.
