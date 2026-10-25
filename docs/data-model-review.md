# Product data model review

Reviewed on 20 October 2026 for [DAT01](https://github.com/kinetix-app/management/issues/11), against the published Sprint 1 increments and the implementation on `feature/dat01-product-data-model`.

## Scope and verdict

[db-schema.sql](../db-schema.sql) is the product schema reference, not a bootstrap script.
The initial product Alembic chain initializes 19 tables. Revision `20261021_01` converts existing
UUID account IDs to generated BIGINTs, preserving identity/profile relationships; revision
`20261021_02` adds nutrition, training and goal tables. SQLAlchemy metadata covers all
tables. These persistence changes do not deliver the proposed feature APIs or business rules.
The review below records remaining product decisions and historical schema assessments.

The draft is a useful starting point for Sprint 1, but does **not yet meet all its requirements**. Its routine/session/set separation and food/meal/day structure fit the selected journeys. Goal semantics, business validation and history behavior still need detailing before feature implementation. The exercise catalogue now has explicit, reusable fields based on Ascend, supporting manual entry and optional imports. The initial migrations now implement persistence; no import service or consuming feature APIs are implemented.

## Confirmed design direction

- Use `BIGSERIAL PRIMARY KEY` for every independently generated local entity ID, including `users.id` and `auth_accounts.id`. All references use `BIGINT` without a sequence/default of their own. `profiles.user_id` is a shared `BIGINT` primary/foreign key: a profile reuses its user ID. Every table therefore has the same underlying PostgreSQL BIGINT key type. Provider IDs and Clerk issuer/subject values remain text because they are external identifiers.
- Use inline `PRIMARY KEY`, `REFERENCES`, `NOT NULL` and `UNIQUE` declarations for data integrity. Avoid named `CONSTRAINT` clauses and business-rule CHECKs. Keep numeric bounds, valid states, ownership and food-or-recipe selection in schemas/services. Identity uniqueness uses unnamed `UNIQUE (issuer, subject)`.
- Use a common exercise table for manually entered exercises and optional provider imports. Reuse Ascend's documented exercise fields as explicit columns; provider metadata is optional for manual entry.
- Track overall user evolution and physical-goal progress through user-owned dated `body_measurement` records. Keep the chosen target in `physical_goal`; intermediate milestone targets are excluded by the owner's decision.
- Remove the sport catalogue and activity-goal table by the owner's decision. Exercise/session activity categories are VARCHAR fields; remaining target requirements need reconciliation with that scope change.
- Keep enum-like fields as VARCHAR with values documented in SQL comments, rather than PostgreSQL enum types.
- Routine exercises use child set rows with the same measurements as session exercises. On routine load, use the latest completed workout results; saved routine values are the fallback.
- Leave the remaining product decisions pending the owner's response.

The account tables retain the migrated status, identity and profile fields, timezone-aware timestamps, identity-owner index and deletion relationships (`RESTRICT` for identities, `CASCADE` for profiles). Passwords, email and first/last names are not local account columns. SQLAlchemy maintains `updated_at`; there is no database trigger.

**Runtime compatibility:** The original [revision 20261013_01](../migrations/versions/20261013_01_accounts.py)
is unchanged. Follow-up revisions migrate its UUIDs through explicit mappings and update
backend contracts to integer IDs. Existing account constraints remain, including issuer/subject
uniqueness and the status CHECK. Stop API traffic during migration and refresh cached client
account IDs. Downgrade generates new UUIDs; recovering original UUIDs requires a backup.
See [migration instructions](../README.md#checks-and-database-changes).

Nullable catalogue/routine owners do not automatically grant public access. Services must derive personal ownership from `CurrentUser` and reject cross-account references and reads.

The complete [Mermaid data model](data-model.md) shows the current tables, fields and foreign-key relationships. Alembic is the runtime authority; schema presence alone does not establish feature behavior.

## Sprint 1 fit and remaining work

| Selected requirement | Draft support | Smallest remaining change or decision |
|---|---|---|
| [Account access](https://github.com/kinetix-app/app-rest/issues/8), [persistence](https://github.com/kinetix-app/app-rest/issues/9), [isolation](https://github.com/kinetix-app/app-rest/issues/10) | Migrated BIGINT accounts and owned persistence tables; feature APIs remain outstanding. | Implement owned feature APIs and two-account persistence/isolation tests. Account/provider completion remains tracked separately. |
| [Selected objective](https://github.com/kinetix-app/app/issues/3) | `physical_goal.goal_type` is unconstrained; every goal requires a numeric target. | Represent build muscle, lose fat, gain weight and maintain weight explicitly. Store the selected objective independently of an optional measurable target; do not equate body weight with muscle/fat progress. |
| [Dated baseline](https://github.com/kinetix-app/app/issues/9), [baseline review](https://github.com/kinetix-app/app/issues/10) | `body_measurement.date` and `weight_kg` support a dated weight observation with a unit. | Validate at least one measurement and bounds. Agree how the baseline is associated with the selected goal; additional measures depend on DEC-01. |
| [Chosen targets](https://github.com/kinetix-app/app/issues/14) | `physical_goal` and `nutrition_goal` hold chosen targets; body measurements record actual progress. The activity-goal table is excluded by the owner's decision. | Define the physical target metric/unit and which goal/target is current. Intermediate milestones and activity goals are excluded by the owner's decision; reconcile the linked requirement's milestone and weekly-session-target scope. No replacement weekly target is assumed. Resolve remaining DEC-01/02 rules. |
| [Saved routines](https://github.com/kinetix-app/app/issues/4), [session start](https://github.com/kinetix-app/app/issues/15) | Ordered exercise references, notes and individually numbered default sets mirror the recorded exercise/set structure. | Require personal routine ownership for the Sprint 1 flow; validate positive positions and uniqueness within a routine in services. Supply at least eight catalogue exercises; save/start a three-exercise example. |
| [Set recording](https://github.com/kinetix-app/app/issues/16), [completion](https://github.com/kinetix-app/app/issues/18), [reopen](https://github.com/kinetix-app/app/issues/19), [history](https://github.com/kinetix-app/app/issues/21), [units](https://github.com/kinetix-app/app/issues/22) | Actual results live in `exercise_set`, separately from routine templates. Completed aggregates have account-scoped client UUIDs and canonical six-decimal kg storage. | Start and record locally, using previous/default measurements as guidance only. Finish atomically persists explicit actual results; normalized fingerprints and uniqueness prevent duplicate retries. Reopen owned completed records using timezone-aware events and requested kg/lb display. Broader measurement formats remain in app#63. |
| [Manual foods](https://github.com/kinetix-app/app/issues/5), [portion logging](https://github.com/kinetix-app/app/issues/23) | Foods have per-100-g values in comments; items have gram quantities and meals belong to a date. | Make manual foods owned/private, document kcal and grams in the API, validate nonnegative nutrients, positive portions and exactly one food-or-recipe source with the matching quantity in services. |
| [Proportional calculation](https://github.com/kinetix-app/app/issues/24), [daily target comparison](https://github.com/kinetix-app/app/issues/25), [separate dates](https://github.com/kinetix-app/app/issues/27) | Day/meal/item joins support totals. | Keep one nutrition day per `(user_id, date)` through service logic that also handles concurrent requests. Agree decimal calculation/rounding and whether changed foods, recipes or targets alter earlier days; the current joins recalculate history from current definitions. |
| [Form](https://github.com/kinetix-app/app-rest/issues/4) and [coach](https://github.com/kinetix-app/app-rest/issues/5) research | No AI tables. | Sufficient for research-only Sprint 1 scope. Keep suggested outputs separate from chosen targets and actual records when delivery is selected. |

Business validation is an implementation requirement, rather than a missing database-constraint requirement. Services must authorize private food/routine references and handle concurrent operations where uniqueness matters. Index owner/date and reference lookup paths only with their consuming queries.

Nutrition calculation is `reference_value * quantity_grams / 100`; 150 g contributes 1.5 times the reference value. `DECIMAL(8,2)` storage alone does not define intermediate precision or when to round a daily total. Use decimal arithmetic and agree rounding with the nutrition implementer. Historical nutrition semantics need a product-owner decision: if past values must remain fixed, capture consumed nutrient values or reference immutable versions. Do not add versioning machinery before that decision.

## Exercise catalogue fields

Reviewed official [V1 exercise detail](https://docs.ascendapi.com/api-reference/exercisedb-v1/exercises/getexercisebyid) and [V2 exercise detail](https://docs.ascendapi.com/api-reference/exercisedb-v2/exercises/getexercisebyid). Ascend provides the field vocabulary for our own exercise catalogue. Exercises can be filled manually, and do not require an Ascend account, download or external ID. The explicit seed importer described in the follow-up below loads the supplied local export without provider downloads.

The `exercise` table exposes the documented V1/V2 exercise fields directly, using snake_case. Array fields retain multiple values and instruction order. Only resolution-to-URL maps use JSONB. There is no whole-exercise JSON payload.

| Ascend field | Local column/type |
|---|---|
| `exerciseId` | Optional `external_id TEXT`; the local primary key remains serial `id`. |
| `name`, `overview` | `name TEXT`, `overview TEXT`. |
| `bodyParts`, `equipments` | `body_parts TEXT[]`, `equipments TEXT[]`. |
| V1 `exerciseTypes`, V2 `exerciseType` | `exercise_types VARCHAR(50)[]`; a V2 singular value becomes a one-element array. |
| `targetMuscles`, `secondaryMuscles` | `target_muscles TEXT[]`, `secondary_muscles TEXT[]`. |
| `instructions`, `exerciseTips` | `instructions TEXT[]`, `exercise_tips TEXT[]`. |
| `variations`, `keywords` | `variations TEXT[]`, `keywords TEXT[]`. |
| V1 `difficulty` | `difficulty VARCHAR(20)`. |
| `relatedExerciseIds` | `related_exercise_ids TEXT[]`, retaining identifiers in the source dataset. |
| `videoUrl`, `imageUrl` | `video_url TEXT`, `image_url TEXT`. |
| `imageUrls`, V1 `gifUrls` | `image_urls JSONB`, `gif_urls JSONB`, preserving resolution keys such as `360p`. |

Local metadata stays small: nullable creator `user_id`, `activity_type VARCHAR(30)`, `source VARCHAR(30)` defaulting to `manual`, optional `external_id` and optional `imported_at`. Manually entered records need a name and activity type; other descriptive/media fields can be filled progressively and validated by services. A creator identifies ownership, not publication status. Routine and session references always use the local numeric `exercise.id`.

`related_exercise_ids` preserves the provider's descriptive relationship field; it is not a foreign-key list of local exercise IDs. Manual entries can leave it empty. A future importer can resolve related provider IDs within the same source when needed, without making import completeness a condition of creating an exercise.

Manual entry remains supported alongside the explicit local catalogue seed command. If importing later, identify rows by `(source, external_id)` and preserve their local IDs when updating metadata. Business logic handles duplicate detection. The [provider policy](https://docs.ascendapi.com/guides/caching) still applies to downloaded information, and imported media links require refresh; manually supplied exercise information has no provider dependency.

Exercise classifications do not determine workout units. The selected gym flow still needs service/UI configuration for kilograms and repetitions. Actual completed sets remain separate from editable catalogue metadata.

## Routine guidance, drafts and performed results

Routine definitions and performed workouts have independent exercise rows with numbered
child sets. `routine_exercise` references `routine_exercise_set`; `session_exercise`
references `exercise_set` and the catalogue exercise. There is no FK or other relation
between template slots and performed exercise rows. A completed `training_session` keeps
its optional owned `routine_id` origin. Template editing cannot alter history.

Guidance uses the current account's latest completed occurrence of each exercise with
at least one recorded set, across routines and blank workouts. Selection orders by finish
time/session ID and then exercise order/entry ID descending. Empty later occurrences,
active sessions and other accounts are excluded. Repeated template exercises share this
exercise-level configuration; missing history falls back to saved defaults. The same
query powers `GET /exercises/{id}/last-configuration`. Guidance is never persisted as an
actual result unless the user records it.

Start saves an owned `session_draft` JSON snapshot; ticking saves confirmed actual values
and exercise layout. Original start instant and routine origin are immutable. Finish
prunes unconfirmed sets from both snapshot and completed result, preserving selected
exercise order and zero-set entries. Plain completion can be empty. Routine update is an
explicit finish decision requiring an owned origin and at least one exercise: it replaces
template selection/order/defaults from confirmed completed contents, keeping the name.
Template update, aggregate creation and draft retirement commit together. Retries freeze
the finish instant and update decision and never reapply template changes.

Revision `20261024_01` widens weight columns to `NUMERIC(12,6)`, adds workout idempotency
and interprets legacy naive training timestamps as UTC. Conversion uses the exact
`0.45359237` kg/lb factor and half-up rounding once at storage precision; display rounds
to two decimals. Historical nullable retry keys remain supported.

Revision `20261025_01` adds owned resumable snapshots with account/client UUID uniqueness
and a partial unique index for one active snapshot/account. Revision `20261025_02` removes
`session_exercise.routine_exercise_id` and `routine_slot_provenance`, cleans legacy draft
JSON references and stores the finish update decision. Workouts, exercises, sets and
session-level routine origins survive upgrade. Downgrade recreates empty metadata and
nullable links; removed associations cannot be reconstructed. Runtime/browser/native
acceptance remains distinct from schema verification.

## Category values

The SQL comments document enum-like vocabularies without creating PostgreSQL ENUM types or CHECK constraints. Services validate the selected values. `activity_type` replaces the sport relationship on exercises and training sessions; it does not replace exercise classifications.

| Field | Documented values |
|---|---|
| `exercise.activity_type`, `training_session.activity_type` | `gym`, `running`, `cycling`, `walking`, from the existing roadmap. Sprint 1 uses `gym`. |
| `physical_goal.goal_type` | `build_muscle`, `lose_fat`, `gain_weight`, `maintain_weight`; metric/unit semantics remain pending DEC-01. |
| `meal.meal_type` | Proposed `breakfast`, `lunch`, `dinner`, `snack`; final categories remain pending. |
| `exercise.exercise_types` | VARCHAR array for multiple provider/manual classifications. Proposed `strength`, `cardio`, `stretching`, `mobility`; final vocabulary remains pending catalogue selection. |
| `users.status` | `active`, `blocked`, `deleted`. |
| `exercise.difficulty` | Proposed `beginner`, `intermediate`, `advanced`; final catalogue vocabulary remains pending. |
| `exercise.source` | `manual`, `ascend_edb_v1`, `ascend_edb_v2`; extend when another source is introduced. |

## Implementation order and later scope

1. The existing account migration remains the base; follow-up serial-ID and product-table migrations are implemented. Apply the full chain before running the integer-ID backend.
2. Settle goal/baseline/target fields (DEC-01/02), then evolve their schemas and implement feature behavior.
3. Implement catalogue and routine/session/set APIs with business validation in services. Populate the catalogue manually using the common exercise fields; add an importer only when needed.
4. Agree nutrition precision/history behavior, then implement owned food/day/meal/item and target APIs. Recipes can follow their selected consuming feature.

Feed/post audiences, Jam membership linked to each participant's own session, league membership/scoring linked to existing workouts, and Market collections retaining item references/creator attribution are absent. They remain conceptual later work, with DEC-04–10 unresolved. Recipes and additional body measures in the draft are not evidence of Sprint 1 delivery. Integrated AI feedback, upload storage and suggestion history can wait for their consuming features and DEC-11/12.

The next review should check these decisions and the selected feature migrations. SQL execution proves structural validity only; it cannot establish ownership, historical behavior, calculations or feature acceptance.

## Verification

Previous runtime checks passed: lockfile, Ruff lint/format, 106 non-integration tests and 11 integration tests. They cover the existing UUID account implementation, not the draft's serial-ID design. Earlier draft checks included now-removed tables and do not describe the current table count.

Before routine/set alignment, the 18-table draft passed isolated PostgreSQL execution. Removed tables and sport references are absent; category fields use VARCHAR (VARCHAR[] for multiple exercise classifications). Manual exercise, linked session/exercise and physical-goal inserts passed. Temporary schemas and records were rolled back. That historical check preceded the initial product migrations.

The earlier 19-table draft passed isolated PostgreSQL verification: routine and session set measurements had matching types, per-set defaults persisted, and a sample copy from the latest completed workout created fresh incomplete sets. Editing or removing a routine slot preserved historical results. Temporary schemas and records were rolled back. That historical SQL example predates the local-workout contract described above; it does not establish runtime acceptance of the revised flow.

## Exercise media seeding follow-up

Issue [#16](https://github.com/kinetix-app/app-rest/issues/16) adds `exercise.image_urls JSONB` for all imported JPEG resolution variants alongside the default `image_url` and `video_url`. A partial unique index on `(source, external_id)` applies only to non-manual global catalogue rows with an external ID; user-owned and manual records remain independent. Migration `20261021_03` implements this change. The explicit local seed command replaces the immediate manual-only catalogue workflow for the supplied export; no provider download runs at startup. See the README for input format, storage configuration and retry semantics.
