# Backend feature status

Reviewed against backend routes, services, migrations and tests on 25 October 2026.
These pages report current code behavior, not just schema readiness or planned scope.
Update the relevant page whenever a feature changes.

| Feature | Current state |
| --- | --- |
| [Authentication](authentication.md) | Basic and Clerk request authentication resolve an active internal account; provider/account lifecycle gaps remain. |
| [Accounts](accounts.md) | Lazy account/profile provisioning, account read and profile update APIs are implemented. |
| [Goals](goals.md) | Physical-goal and measurement persistence exists; no service or API exposes it. Nutrition goals are in Nutrition. |
| [Nutrition](nutrition.md) | Owned foods/recipes, nutrition goals, meal logging and daily summaries have API and persistence. |
| Posts and leagues | Persistence only: eight tables, Python category enums and migration `20261102_01`; no social or league API/business rules. |
| [Training](training.md) | Catalogue/routines, completed sessions, idempotency, resumable drafts, history and media seeding are implemented. |

The [backend README](../../README.md) remains the source for setup and runtime commands.
The [data model](../data-model.md), [authentication runbook](../authentication.md) and
[backend conventions](../agent-conventions.md) provide deeper contracts.

## Status terminology

- **Implemented** means route, service and persistence behavior are present in this
  repository. It does not establish client acceptance or production-provider readiness.
- **Partial** means only the listed behavior exists; known gaps are named on the page.
- **Persistence only** means a model/migration exists without a usable API use case.
- **Not implemented** means no runtime behavior exists here, even if it appears in a
  schema draft, product plan or client placeholder.

Tests listed on each page are repository evidence; they are not a claim that a test suite
or live end-to-end flow was run while writing these status notes.
