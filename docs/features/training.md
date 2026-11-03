# Training

## Current state

Training is implemented across catalogue, routine templates, completed sessions,
resumable session drafts and exercise/media seeding. Protected routes use the authenticated
account as owner. Performed exercises reference catalogue exercises and keep a
session-level routine origin; they are independent of mutable routine slots.

- **Catalogue:** paginated exercise search by name, body part or legacy muscle group;
  separate body-part/muscle-group lists; full exercise detail on demand.
- **Routines:** owned list/detail/create/PATCH with exercise order and planned sets.
- **Completed sessions:** create and paginated list/detail. Client session UUID and content
  fingerprint make exact retries idempotent; reusing an ID with different content returns
  409. Weight input supports kg/lb and is normalized to canonical kg at six-decimal
  precision using the documented conversion/rounding policy.
- **Drafts:** one active draft per account; GET current, PUT snapshot, DELETE/discard and
  POST finish. Finish atomically creates the completed session, retains confirmed sets,
  freezes retry choices and can optionally update the source routine.
- **Guidance:** last-configuration returns the account's latest completed exercise sets;
  it does not create performed data.
- **Seed:** an explicit local command validates/imports exercise catalogue metadata and
  media to Azure Blob Storage. Startup does not seed or fetch provider data.

The backend documents precise request/response details, migrations, idempotency and draft
semantics in the [routine APIs](../../README.md#routine-and-exercise-apis),
[completed-workout APIs and units](../../README.md#completed-workouts-kinetix-013014016),
[resumable drafts](../../README.md#resumable-workout-drafts), and
[exercise seed guide](../../README.md#exercise-catalogue-and-media-seeding).

## Code and evidence

- Routes: `app/features/training/router.py`.
- Routine/catalogue logic: `service.py`; completed sessions: `sessions.py` and `history.py`;
  resumable snapshots: `drafts.py`; units: `units.py`.
- ORM/schemas/errors and explicit import command are in `app/features/training/`.
- Integration/unit evidence: `tests/integration/test_training.py`,
  `tests/test_training_units.py`, `tests/test_exercise_seed.py`,
  `tests/integration/test_exercise_import_database.py` and migration tests.
- Client state and acceptance limits: [mobile training](https://github.com/kinetix-app/app/blob/master/docs/features/training.md).

## Remaining gaps

There is no training WebSocket/shared live-session service, camera/form-analysis API or
non-gym measurement format flow. Live browser acceptance is separate from the backend
integration suite; native device, provider and multi-device conflict behavior require
their own evidence. Migration downgrades that remove draft/idempotency metadata have
documented data-loss limits; review the README before downgrading.
