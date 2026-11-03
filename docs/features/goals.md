# Physical goals and measurements

## Current state

This feature is **persistence only**. `app/features/goals/models.py` maps
`physical_goal` and `body_measurement`; the initial product schema/migration creates the
tables. There is no goals router, service, request/response schema, calculation or API
consumer for these records.

The current model contains a proposed `goal_type` vocabulary (`build_muscle`, `lose_fat`,
`gain_weight`, `maintain_weight`), a numeric `target_value`, dates, and optional completion
time. Measurements store weight, body-fat percentage, muscle mass and circumferences.
The target metric/unit and interpretation of those values are unresolved, so the current
columns do not define usable progress semantics.

Nutrition targets are separate and are implemented under [Nutrition](nutrition.md); they
must not be mistaken for physical-goal tracking.

## Code and evidence

- Persistence metadata: `app/features/goals/models.py`.
- Product schema and review: `db-schema.sql`, [data model](../data-model.md), and
  [data-model review](../data-model-review.md).
- There are no goals route/service/schema tests because no runtime API behavior exists.
- Frontend status: [mobile goals](https://github.com/kinetix-app/app/blob/master/docs/features/goals.md).

## Required before API delivery

Agree target units/metrics, goal progress and completion rules, measurement history
semantics, and any timezone/date behavior. Then define validation, ownership-scoped
operations and deterministic calculations before treating these tables as a delivered
feature.
