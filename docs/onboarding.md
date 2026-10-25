# Profile setup and objective

`GET /api/v1/auth/me` and the compatible `GET /api/v1/me` return the private account,
profile and derived `onboarding` state. First authenticated access provisions only a
minimal account. Existing users with incomplete profiles also receive `required: true`.

The profile is complete when `display_name`, `age`, `height_cm`, `weight_kg` and
`weight_unit` are present. A picture and timezone are optional. Completion also requires
an objective selected through `PUT /api/v1/me/objective`. Numerical nutrition targets
are independent and never gate completion or food logging.

`PATCH /api/v1/me/profile` preserves omitted fields; explicit null clears a field.
Names are trimmed and must contain 1–100 characters. Age is an integer from 1–120.
Height is centimetres, positive through 300 with at most two decimal places. Body mass
is canonical kilograms, positive through 1000 with at most six decimal places. The
unit preference must explicitly be `kg` or `lb`; it has no default. Clients convert
pounds using exactly 0.45359237 kilograms per pound and round canonical kilograms to
six places using round-half-up. The server stores the supplied canonical mass without
inferring it from the preference. Clearing a required field makes setup required again.
These bounds validate representation; they are not health recommendations.

`picture_url` accepts an HTTPS URL without embedded credentials, or null/empty to clear.
It stores a reference only; no upload or remote image retrieval occurs. No sex, activity
level, date of birth or additional health field is collected for automatic calculations.

`GET /api/v1/me/objective` returns `{ "objective": null }` when none is selected.
`PUT` accepts exactly one `objective`: `build_muscle`, `lose_fat`, `gain_weight` or
`maintain_weight`. The selected direction is separate from physical targets and optional
nutrition targets. No physical target, milestone or weekly session target is created.
All operations derive account ownership from authentication, reject client account IDs,
and enforce active-account access. Invalid input returns 422; denied accounts return 403.

Revision `20261025_03` adds nullable profile columns and an owned objective row. Existing
profile, account, food and activity data remain unchanged, with no unit/objective backfill.
Downgrade removes only the new profile fields and selected objective; it loses that setup
data. Apply migrations before starting the updated API.

## Optional manual nutrition target

`POST /api/v1/nutrition-goals` creates an owned target (201, duplicate 409). `GET /api/v1/nutrition-goals/me` returns it or 404 for absence. Existing `PATCH /api/v1/nutrition-goals/me` replaces all four numerical fields (404 if missing); it is not a partial-field patch. Input is `calories` in kcal/day (>0), `protein`, `carbohydrates` and `fats` in g/day (>=0), all with at most two decimal places. Unknown fields, including ownership/context identities, are rejected.

The response adds nullable `objective`, captured from the current selected objective on each explicit target save. Legacy targets retain their amounts and null context; changing an objective never changes a target or observation. Creation/update serialize on the owned User row, alongside objective writes. A missing target does not affect account onboarding completion, food logging or day totals. No suggestions or target-based observations are created.
