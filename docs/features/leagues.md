# FriendsLeague

Selected scope: [app#45](https://github.com/kinetix-app/app/issues/45)–[app#50](https://github.com/kinetix-app/app/issues/50).
All endpoints below require the existing authenticated account under `/api/v1`.

- `GET/POST /leagues`: list owned memberships or create a private league with `name` and immutable IANA `timezone`. Creation atomically adds the creator as admin. List entries additionally include `member_count` and `current_week_position` for the authenticated viewer. Counts include every current member; weekly competition ranks count only exact memberships eligible for the current league-local week. Current daily scores are summed exactly, with shared ranks and zero-score ties at #1; previous weeks never contribute. Legacy leagues without a timezone, or viewers without an exact incorporation timestamp, receive a null weekly position. Listing performs at most two batched reads and does not materialize rounds or close results. Create/detail payloads retain their existing schema.
- `GET/PATCH /leagues/{id}`: members and metadata, or administrator-only name update. Outsiders receive 404; non-admin mutations receive 403.
- `GET/POST/DELETE /leagues/{id}/picture`: member-only private image retrieval and admin-only upload/removal. Images are optional; league summaries/details expose `picture_url` as null or a protected relative path with an opaque replacement revision. Uploads accept JPEG/PNG/WebP up to 5 MiB, decode at most 16 million pixels, orient/resize to at most 1024px and store metadata-free JPEGs in the existing private picture container. Replacements commit the new reference before best-effort removal of the old blob; upload/commit failures retain the previous reference. Removal is idempotent and can unlink the image even when storage is unavailable.
- `GET /leagues/{id}/members/{member_id}/picture`: read an uploaded profile picture only when both requester and target are current members of the league. Uses the account’s existing private image without creating a copy. Outsiders/nonmember targets and missing images return 404; anonymous reads return 401. Private image responses use `Cache-Control: private, no-store`.
- `POST /leagues/{id}/invitations`: administrator-only 48-hour reusable token. Only its SHA-256 hash is persisted. Generating another does not revoke previous tokens.
- `GET /league-invitations/{token}` previews; `POST .../{token}/accept` explicitly confirms joining. Repeated valid acceptance preserves the original role and incorporation timestamp. Invalid/expired tokens return 404/410.
- `GET /leagues/{id}/standings`: current and historical rounds, daily contributions and general totals. Integer points are decimal strings in JSON to retain exactness. Equal totals share a position; zero-point members are included. Only source owners receive session/calculation inputs; other members receive daily points.
- `GET /leagues/{id}/results/pending`: lazily closes expired rounds and returns persisted, oldest-first results without acknowledging them.
- `POST /leagues/{id}/results/{result_id}/acknowledge`: 204, membership-scoped, idempotent, monotonic acknowledgement after actual display. It never acknowledges another member. Crashes or simultaneous devices can repeat a display before acknowledgement.

League details include each member’s display name, role and current `picture_url`. Current/past/general standings and pending-result rows also expose the current picture, without profile measurements or source data. Uploaded member photos use the protected league/member endpoint; existing credential-free HTTPS profile-image URLs remain HTTPS. Replacing/removing a profile photo updates subsequent responses. Persisted results retain their original display names, scores and ranks; picture URLs are enriched at read time rather than frozen into result snapshots. Invitation preview payloads do not disclose pictures.

## Calculation and calendar

`League Score = confirmed gym volume (repetitions × kg) × elapsed hours / profile body weight (kg)`.
The completion transaction snapshots source inputs and formula version once. Pauses count as elapsed time. Missing/nonpositive inputs earn no credit. Decimal arithmetic rounds only the final score to an integer using HALF_UP. Existing completed-workout retries retain their original snapshot and credit. The workout transaction owns commit/rollback.

A source must start at or after exact incorporation. Its start determines the local day in each league timezone; the same source can qualify in several leagues. Only the highest rounded score per member/day contributes; ties use earliest completion, then lowest session ID. A higher score replaces the earlier credit. Completed source and submission must remain within the open source round; closed rounds accept no late submissions or corrections.

Rounds run Monday 00:00 inclusive to next Monday 00:00 exclusive in the immutable league timezone, including DST and all Sunday. The first week is partial from creation. Empty missed weeks are retained. General standings sum all rounds including the current one. Credit, standings materialization and closure serialize on the league row; credit locks leagues in ascending order.

Closure saves standings and all tied minimum-score losers; fewer than two eligible members has no loser. All-zero rounds with at least two members make all lose. New members participate from incorporation. Closure creates no penalty or post and erases no points.

## Persistence and boundaries

Revision `20261117_04` adds only a nullable private league-picture reference; fresh setups and populated upgrades preserve existing leagues, memberships, scoring and results. Downgrading this revision removes the picture reference without removing league/member data.

Revisions `20261117_01`–`20261117_03` add membership metadata/invitations, versioned scoring snapshots/rounds/daily winners and saved results/cursors. Legacy DATE rounds, joined dates and integer totals remain unchanged. Unknown legacy timezone/role/exact joined instant remain null; scoring/results require an explicit calendar migration rather than inferred history (409). They are not silently included in the versioned formula totals.

Penalty configuration/roulette, social posting, editable calendars, dynamic formulas/challenges, leaving, expulsion, transfer and deletion remain outside the selected increment.

Focused tests cover membership permissions, rollback, legacy upgrades, formula precision, DST, replacement/retries/concurrency, standings privacy, stable outcomes and independent acknowledgements. See the [standard checks](../../README.md#checks-and-database-changes) and `tests/integration/test_league_*.py`. Browser/native evidence is recorded separately in the canonical issues.
