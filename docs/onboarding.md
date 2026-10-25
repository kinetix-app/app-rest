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

`POST /api/v1/me/profile/picture` accepts an authenticated multipart request with one
`file` (JPEG, PNG or WebP, maximum 5 MiB and 16 million pixels). Actual decoded format
must match its declared type. The server applies orientation, reduces images to at most
1024 pixels per side, strips metadata and saves JPEG in the separate private Azure
container configured by `AZURE_STORAGE_PROFILE_CONTAINER` (default `profile-pictures`).
The entire multipart request is bounded to 5 MiB plus 64 KiB framing. Unsupported types
return 415, oversized files 413, invalid images 422, unavailable storage 503. Upload
returns `AccountResponse` with `picture_url: "/api/v1/me/profile/picture"`; storage names
and credentials are never returned. `GET` at that authenticated owned endpoint returns
JPEG with `Cache-Control: private, no-store`, or 404 when no upload exists. `DELETE`
clears an uploaded or legacy photo idempotently and returns `AccountResponse` (200).

The private container remains private even with exercise public-read mode enabled;
an existing public profile container is rejected. Upload/read/deletion occur outside
database transactions. Replacement commits its new reference under an account lock;
failed persistence removes the new upload, and committed replacement/deletion attempts
best-effort cleanup of the previous blob. Cleanup failures can leave unreferenced blobs.
`picture_url` PATCH still accepts legacy HTTPS URLs without credentials or null/empty
to clear, and clears any previous upload reference. Omitted picture fields preserve
uploads. No remote image retrieval occurs. No sex, activity level, date of birth or
additional health field is collected for automatic calculations.

Revision `20261025_05` adds the nullable hidden `picture_blob_name`; it preserves existing
profile fields and legacy URLs. Downgrade clears uploaded endpoint URLs and loses their
references, but preserves legacy HTTPS references; it does not delete Azure objects.

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
