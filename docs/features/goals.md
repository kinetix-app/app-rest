# Body measurements and weight targets

Profile → Progress records private date-only measurements. A check-in can contain
any combination of height (cm), weight and muscle mass (kg), body-fat percentage,
and waist, chest, arm and thigh circumferences (cm). The API stores decimals in
canonical units. Height, circumference and percentage retain two decimal places.
Weight and muscle mass retain six. The app displays measurements using the account
preference. The profile timezone defines today, with UTC as the fallback.

- `GET /api/v1/me/body-measurements` returns `{ "items": [...] }` ordered by date and
  ID, oldest first. Each item has a date, ID and nullable canonical decimal string
  fields. On same-date check-ins the chart uses the latest observation for the
  selected metric, with all entries available in history.
- `POST /api/v1/me/body-measurements` accepts a client UUID `request_id`, a
  `YYYY-MM-DD` date on or before today and at least one measurement. A replay with
  the same UUID and values returns the existing measurement. A changed payload
  with the same UUID returns 409. Omitted or null metrics remain absent.
- Height and weight are synced independently to the profile from the latest
  dated value. Direct profile updates log changed values for the profile's
  current date. Explicit clears remove the current profile value and keep
  history. An older backfill leaves newer profile values in place. Existing
  completed league scores keep the weight recorded in their scoring snapshot.

`GET /api/v1/me/physical-target` returns the current `objective` and a nullable
`target` with `weight_kg` and optional `target_date`. `PUT` accepts the expected
`objective`, a weight in kg and an optional `YYYY-MM-DD` target date. A stale
objective returns 409. Each objective has its own user-selected weight target.
Measurements, nutrition targets, and goal expectations are managed separately.

Revision `20261121_01` preserves earlier observations, profiles, and targets.
Legacy targets retain their unspecified metric. Review the migration before
downgrading, since the downgrade rejects data it cannot represent.
