# Training

## Current state

Training is implemented across catalogue, routine templates, completed sessions,
resumable session drafts and exercise/media seeding. Protected routes use the authenticated
account as owner. Performed exercises reference catalogue exercises and keep a
session-level routine origin; they are independent of mutable routine slots.

- **Catalogue:** paginated exercise search by name, body part or legacy muscle group;
  separate body-part/muscle-group lists; full exercise detail on demand.
- **Routines:** owned list/detail/create/PATCH with exercise order, planned sets, optional
  notes and private cover images. Summaries include exercise count and latest completed time.
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

## Routine notes and covers (app#94)

`POST /api/v1/routines` and `PATCH /api/v1/routines/{id}` accept optional `notes`
(up to 1000 characters, whitespace trimmed). Notes reuse the existing description column;
omitting notes during PATCH preserves them, and explicit null clears them. Existing name
and exercise null restrictions remain. Existing longer descriptions are readable without truncation.

List/detail/save responses include nullable `notes`, integer `exercise_count`, nullable
aware `last_performed_at`, `activity_type: "gym"`, and nullable `image_url`. Counts include
routine exercise slots, including repeated exercises. Last performed is the latest completed
`ended_at` for this account and source routine; drafts and other accounts are excluded.

`POST /api/v1/routines/{id}/picture` accepts multipart `file`; `DELETE` removes the
cover and `GET` returns its JPEG bytes. Upload and delete return the full updated routine.
The image URL is an authenticated relative API path with an opaque replacement revision;
clients must attach their normal credentials. Responses use `Cache-Control: private, no-store`.
Covers share the configured private image container (`AZURE_STORAGE_PROFILE_CONTAINER`)
with profile images, under isolated `routines/{user}/{routine}/` object prefixes. Public
containers are rejected. No storage keys, blob names or permanent public URLs are exposed.

Limits match profile images: JPEG/PNG/WebP up to 5 MiB, bounded multipart body, decoded
images up to 16MP, normalized orientation, maximum 1024px and metadata stripping.
Invalid images return 422, unsupported types 415, oversized payloads 413, missing/foreign
resources 404 and unavailable storage 503. Provider operations run outside database
transactions. Failed replacements retain the previous reference and clean up new objects;
old-object cleanup is best effort after commit. Removing a cover is idempotent and works
without storage configuration. Apply migration `20261103_01` before running this version;
it adds only a nullable cover reference and preserves existing templates/history.

### Atomic multipart creation

The app creates a routine with one `POST /api/v1/routines` multipart request. Field
`content` is the JSON-encoded routine DTO (`name`, optional `notes`, `exercises` and
planned sets); optional `file` is its cover. Legacy `application/json` creation remains
supported. Both return 201 and the complete routine, including its linked cover URL.

All content, exercise visibility and image validation must succeed before creation.
A selected cover is normalized and uploaded before the database transaction creates
the complete routine and child rows. A short earlier transaction reserves only a
sequence ID for the private object prefix; it inserts no routine. Provider I/O runs
outside database transactions. Storage failures leave no routine; database failures
roll back every new row and attempt to delete the staged image. Sequence gaps are
expected on failed creation. No-image requests do not require configured storage.
Existing PATCH and standalone picture endpoints retain their separate edit semantics.

Routine content is bounded at 16 MiB UTF-8, sufficient for all 500 exercise slots
with 100 planned sets each. Images retain their separate 5 MiB cap; the entire request
is bounded at 21 MiB plus a 64 KiB multipart envelope, including chunked requests.
Duplicate/unknown fields and invalid content return 422; content/image/request size
violations return 413. The generated OpenAPI documents both accepted media types.


### Deleting a routine

`DELETE /api/v1/routines/{id}` returns 204 for the authenticated owner, including a
retry after deletion. Unknown or foreign IDs return 404. An active resumable workout
using that routine returns 409: finish or discard it first, including workouts started
on another device. Failure leaves the routine and its cover reference unchanged.

Deletion sets a timezone-aware `deleted_at` timestamp and clears the private cover
reference in one transaction. Active list/detail/edit/picture and new workout-source
operations exclude deleted routines. Completed sessions, exercise results and their
original routine IDs are retained. Historical reads and exact completion retries stay
valid. Routine/template rows remain for provenance; there is no restore API.

Deletion takes the same account lock as draft save/finish/discard before the routine
write lock. Source validation holds the routine shared lock, preventing a draft/session
from validating a deleted origin during a concurrent deletion. Provider cleanup happens
after commit and is best effort: unavailable storage does not prevent deletion, and
failed cleanup leaves an inaccessible, unreferenced object rather than exposing the
retired cover. Picture reads/uploads check routine availability before storage readiness.

Migration `20261103_02` adds only a nullable timestamp. Existing routines, covers and
completed history are preserved and remain active. Downgrading removes the deletion
marker and therefore makes previously deleted routines visible again; it never removes
completed training references.

`GET /api/v1/exercises/{id}/history` requires authentication and returns only the caller's completed sessions containing a selectable exercise. Results use `limit` (1–100, default 20), `offset` and `weight_unit` (`kg` or `lb`), ordered by completion time and session ID descending. Each item contains the session timestamps, routine name (or `Workout`), exercise activity type and the matching performed sets in exercise/set order; repeated occurrences are grouped. Unselectable exercises return 404.

### Exercise evolution

Implemented for [app#20 — exercise history graphs](https://github.com/kinetix-app/app/issues/20).

`GET /api/v1/exercises/{exercise_id}/evolution` requires authentication and the same catalogue visibility as exercise history. Optional `weight_unit=kg|lb` and `distance_unit=km|mi` default to kg and km. It returns every daily aggregate in ascending UTC completion-date order; it does not persist derived values. Only completed sets from completed workouts owned by the caller and matching the exact exercise identity contribute. An exercise without recorded sets returns an empty `days` list.

Gym days report the highest positive recorded weight and repetitions independently, the sum of positive weight × positive repetitions, and the highest eligible Epley estimate (recorded weight for one rep, weight × (1 + reps / 30) for 2–10 reps). `volume_partial` indicates at least one completed set was excluded from volume because its weight or reps was missing or invalid. Estimates and volume use recorded loads, which may not represent total load for bodyweight or assisted exercises. Cardio days report the greatest recorded distance and duration independently. Incompatible or unavailable metrics are null. Values are compared and summed before conversion; weight-based values are rounded to one decimal and distance to two, using ROUND_HALF_UP. History remains the source for individual sets and provenance.
