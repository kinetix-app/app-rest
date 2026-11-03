# Accounts

## Current state

Account provisioning is part of authentication: the first valid identity request
atomically creates an active `users` row, an issuer/subject mapping and its profile.
Generated internal account IDs are BIGINTs. Duplicate first requests are handled through
the identity uniqueness boundary; inactive accounts are denied.

The protected account routes are:

- `GET /api/v1/me` reads the active account and profile.
- `PATCH /api/v1/me/profile` updates the profile and explicit unit preference; omitted
  fields are preserved. `GET /api/v1/auth/me` also returns derived onboarding state.
- `POST`, `GET` and `DELETE /api/v1/me/profile/picture` upload multipart images to a
  separate private Azure container, serve only the authenticated owner's JPEG, and
  remove the image. See the [profile contract](../onboarding.md) for limits and errors.

Ownership comes from `CurrentUser`; there is no request-body user ID. Profile update
failures roll back at the service boundary.

## Code and evidence

- Routes: `app/features/accounts/router.py`.
- Provisioning/profile operations: `app/features/accounts/service.py`.
- ORM and request/response schemas: `models.py` and `schemas.py` in the same feature.
- Migration history starts at `migrations/versions/20261013_01_accounts.py` and adds
  serial IDs in `20261021_01_serial_account_ids.py`.
- Integration coverage: `tests/integration/test_accounts.py`.

The mobile consumer's implementation is tracked in the
[frontend accounts status](https://github.com/kinetix-app/app/blob/master/docs/features/accounts.md).

## Remaining gaps

Account linking, user-initiated deletion, provider deletion synchronization and an
explicit session-revocation model are not implemented. The profile API is implemented;
the mobile consumer provides guided profile setup and editing.
