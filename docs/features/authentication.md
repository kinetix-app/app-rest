# Authentication

## Current state

Protected API routes use `CurrentUser`, which verifies the configured identity adapter
and resolves an active internal account before feature code runs. The application
supports two adapters:

- **Basic** verifies credentials against `BASIC_AUTH_USERS` and maps them to a synthetic
  `urn:kinetix:dev` identity. The allowlist is empty by default, wrong credentials return
  401 with a Basic challenge, and production rejects Basic mode at startup.
- **Clerk** verifies Bearer session tokens using Clerk's async SDK. Its verifier owns
  signing-key retrieval/cache and signature/time validation, then enforces configured
  issuer and authorized-party/session claim rules. Missing production configuration is a
  startup/configuration error; a temporary verifier outage returns 503.

The default is Basic outside production and Clerk in production. Identity maps to a local
integer user ID; request bodies never choose owner IDs. First use atomically creates the
local user, linked identity and profile; inactive/blocked/deleted users are denied.

## Code and evidence

- `app/core/auth/dependencies.py` selects the adapter and provides `CurrentUser`.
- `app/core/auth/basic.py`, `app/core/auth/clerk.py` and related auth types implement the
  adapters and verifier contract.
- `app/features/accounts/service.py` resolves identities and provisions internal users.
- Unit evidence: `tests/test_authentication.py` and
  `tests/test_basic_authentication.py`.
- Configuration, Clerk setup and local sign-in steps are in the
  [authentication runbook](../authentication.md).

## Remaining gaps

Production Clerk dashboard/provider configuration and native token/session behavior need
their own acceptance evidence. Account linking, deletion synchronization with identity
providers and immediate/all-device revocation are not implemented as account lifecycle
operations. Clerk sign-out on a client does not itself revoke every previously issued JWT.
