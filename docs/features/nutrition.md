# Nutrition

## Current state

Nutrition has protected routes, service operations and PostgreSQL persistence for
nutrition goals, foods, recipes, meal entries and daily summaries. All operations derive
ownership from `CurrentUser`.

| Operation | Route behavior |
| --- | --- |
| Nutrition goal | `GET /api/v1/nutrition-goals/me`, `POST /api/v1/nutrition-goals`, `PATCH /api/v1/nutrition-goals/me` |
| Food | `GET /api/v1/foods` (optional name search), `POST /api/v1/foods`, `GET/PATCH/DELETE /api/v1/foods/{id}` |
| Recipe | `GET/POST /api/v1/recipes`, `DELETE /api/v1/recipes/{id}` |
| Food meal item | `POST /api/v1/nutrition/meal-items`, `DELETE /api/v1/nutrition/meal-items/{id}` |
| Recipe meal item | `POST /api/v1/nutrition/recipe-items` |
| Day summary | `GET /api/v1/nutrition/days/{date}` returns totals and logged items |

Food and recipe records are user-owned. Food search is over the caller's foods; there is
no shared/external food catalogue. Recipe ingredients must reference foods owned by the
same account. Food/recipe deletion is rejected with 409 while referenced by a recipe or
diary item. Day keys are date-only values; the backend does not infer a user's local day
from a timezone or event timestamp.

Nutrient calculations scale per-100-gram food values by gram quantity. Recipe nutrient
totals sum ingredient quantities divided by recipe servings, then scale by servings
logged. Source food values and database fields use `NUMERIC(8, 2)`; service arithmetic
uses `Decimal` values and does not add a separate display-rounding policy.

## Code and evidence

- Routers: `app/features/nutrition/router.py`; API composition: `app/api/router.py`.
- Use cases and transaction boundaries: `app/features/nutrition/service.py`.
- Schemas/errors/models: `schemas.py`, `errors.py` and `models.py` in the feature.
- Integration coverage: `tests/integration/test_nutrition.py` and migration coverage in
  `tests/integration/test_migrations.py`.
- Client behavior: [mobile nutrition](https://github.com/kinetix-app/app/blob/master/docs/features/nutrition.md).

## Remaining gaps

No shared food data provider, barcode lookup, nutrition-goal progress history or physical
goal tracking is implemented. Physical-goal tables have no API; see [Goals](goals.md).
Live cross-account and deployed-client acceptance should be recorded separately from the
integration tests.
