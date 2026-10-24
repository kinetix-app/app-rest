-- Product schema reference for DAT01; this file is not an Alembic migration.
-- Revisions 20261021_01 and 20261021_02 initialize this BIGINT-based schema.
-- Existing account constraints from 20261013_01 are retained, including the status CHECK.
-- Apply migrations through `make migrate`, not by loading this draft into the app DB.
-- Sprint 1 assessment and AscendAPI import proposal: docs/data-model-review.md.

-- Local entity IDs use BIGSERIAL primary keys (PostgreSQL BIGINT plus a sequence).
-- References use BIGINT without their own sequence, including profiles.user_id.
-- Profiles reuse the user primary key to keep the one-profile-per-user relationship.
-- Credentials/session validation belong to the configured authentication adapter.
-- updated_at is maintained by SQLAlchemy on updates; there is no database trigger.
CREATE TABLE users (
    id BIGSERIAL PRIMARY KEY,
    -- Values: active, blocked, deleted.
    status VARCHAR(16) NOT NULL DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE auth_accounts (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    issuer VARCHAR(512) NOT NULL,
    subject VARCHAR(255) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (issuer, subject)
);

CREATE INDEX ix_auth_accounts_user_id ON auth_accounts (user_id);

CREATE TABLE profiles (
    user_id BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    display_name VARCHAR(100),
    timezone VARCHAR(100),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Feature persistence tables below are migrated; APIs/business rules remain feature work.
-- Business rules (bounds, valid states and ownership) belong in services.
-- Inline PRIMARY KEY, REFERENCES, NOT NULL and UNIQUE declarations define integrity.
-- No named CONSTRAINT clauses or business-rule CHECKs; validate business rules in services.
-- Enum-like categories use VARCHAR (or VARCHAR[] for multiple values), not PostgreSQL ENUMs.
-- Comments document values; proposed vocabularies remain pending product decisions.
-- Nullable catalogue owners need explicit visibility rules before feature delivery.

-- Nutrition section
-- Manages foods, recipes, and daily meal tracking.
-- Foods store nutritional values per 100g and can be used in multiple recipes.
-- Recipes contain ingredients with specific quantities and serving counts.
-- Each nutrition_day contains meals (breakfast, lunch, dinner, etc.).
-- Each meal contains individual foods or recipes with their consumed quantities.
-- Nutritional totals for meals and days are calculated using JOINs and SUMs,
-- based on food values, ingredient quantities, and recipe servings.

-- Food table
CREATE TABLE food (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(id),
    name VARCHAR(150) NOT NULL,
    brand VARCHAR(100),
    calories DECIMAL(8,2) NOT NULL,
    protein DECIMAL(8,2) NOT NULL,
    carbohydrates DECIMAL(8,2) NOT NULL,
    fats DECIMAL(8,2) NOT NULL,
    barcode VARCHAR(50)
);

-- Recipes with their declared serving count.
CREATE TABLE recipe (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(id),
    name VARCHAR(150) NOT NULL,
    description TEXT,
    instructions TEXT,
    servings INTEGER NOT NULL DEFAULT 1
);

-- Recipe ingredients and their quantities in grams.
CREATE TABLE recipe_ingredient (
    id BIGSERIAL PRIMARY KEY,
    recipe_id BIGINT NOT NULL REFERENCES recipe(id),
    food_id BIGINT NOT NULL REFERENCES food(id),
    quantity_grams DECIMAL(8,2) NOT NULL
);

-- A user's local calendar date for nutrition logging.
CREATE TABLE nutrition_day (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id),
    date DATE NOT NULL
);

-- Meals belonging to a nutrition day.
CREATE TABLE meal (
    id BIGSERIAL PRIMARY KEY,
    nutrition_day_id BIGINT NOT NULL REFERENCES nutrition_day(id),
    -- Proposed values: breakfast, lunch, dinner, snack; final meal categories pending.
    meal_type VARCHAR(30) NOT NULL
);

-- Items in a meal, can be either a food or a recipe, but not both
CREATE TABLE meal_item (
    id BIGSERIAL PRIMARY KEY,
    meal_id BIGINT NOT NULL REFERENCES meal(id),
    food_id BIGINT REFERENCES food(id),
    recipe_id BIGINT REFERENCES recipe(id),
    quantity_grams DECIMAL(8,2),
    servings DECIMAL(8,2)
);

-- Chosen daily calorie and macronutrient targets.
CREATE TABLE nutrition_goal (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL UNIQUE REFERENCES users(id),
    calories DECIMAL(8,2) NOT NULL,
    protein DECIMAL(8,2) NOT NULL,
    carbohydrates DECIMAL(8,2) NOT NULL,
    fats DECIMAL(8,2) NOT NULL
);

-- Shared exercise structure for manual entry and optional Ascend imports.
-- Fields follow Ascend exercise details, using this schema's snake_case convention.
-- https://docs.ascendapi.com/api-reference/exercisedb-v2/exercises/getexercisebyid
-- https://docs.ascendapi.com/api-reference/exercisedb-v1/exercises/getexercisebyid
-- V2 exerciseType maps to one entry in exercise_types; V1 provides an array.
-- Only media resolution maps use JSONB; all other exercise fields are explicit.
-- external_id is optional: manually entered exercises need no provider identifier.
-- related_exercise_ids retains source identifiers, not local routine/session IDs.
-- Business validation and duplicate detection belong to services.
CREATE TABLE exercise (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(id),
    -- Values: gym, running, cycling, walking. Sprint 1 uses gym.
    activity_type VARCHAR(30) NOT NULL,
    name TEXT NOT NULL,
    overview TEXT,
    body_parts TEXT[],
    equipments TEXT[],
    -- Provider/manual classification, distinct from activity_type.
    -- Proposed values: strength, cardio, stretching, mobility; catalogue vocabulary pending.
    exercise_types VARCHAR(50)[],
    target_muscles TEXT[],
    secondary_muscles TEXT[],
    instructions TEXT[],
    exercise_tips TEXT[],
    variations TEXT[],
    keywords TEXT[],
    -- Proposed values: beginner, intermediate, advanced; catalogue vocabulary pending.
    difficulty VARCHAR(20),
    related_exercise_ids TEXT[],
    video_url TEXT,
    image_url TEXT,

    gif_urls JSONB,
    -- Values: manual, ascend_edb_v1, ascend_edb_v2; extend when another source is added.
    source VARCHAR(30) NOT NULL DEFAULT 'manual',
    external_id TEXT,
    imported_at TIMESTAMP WITH TIME ZONE,
    image_urls JSONB
);

-- Training routines, created by users or generated by AI
CREATE TABLE routine (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(id),
    name VARCHAR(150) NOT NULL,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Routine exercises mirror session_exercise: exercise reference, order, notes and child sets.
CREATE TABLE routine_exercise (
    id BIGSERIAL PRIMARY KEY,
    routine_id BIGINT NOT NULL REFERENCES routine(id),
    exercise_id BIGINT NOT NULL REFERENCES exercise(id),
    exercise_order INTEGER NOT NULL,
    notes TEXT
);

-- Saved defaults for the first workout, or routine slots absent from the previous workout.
-- Same numbered measurements as exercise_set; completion belongs only to performed sets.
-- The number of sets is the child-row count, not an aggregate sets column.
CREATE TABLE routine_exercise_set (
    id BIGSERIAL PRIMARY KEY,
    routine_exercise_id BIGINT NOT NULL REFERENCES routine_exercise(id),
    set_number INTEGER NOT NULL,
    reps INTEGER,
    weight_kg DECIMAL(8,2),
    duration_seconds INTEGER,
    distance_km DECIMAL(8,2)
);

-- Performed training, optionally started from a routine.
CREATE TABLE training_session (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id),
    routine_id BIGINT REFERENCES routine(id),
    -- Values: gym, running, cycling, walking. Sprint 1 uses gym.
    activity_type VARCHAR(30) NOT NULL,
    started_at TIMESTAMP NOT NULL,
    ended_at TIMESTAMP,
    notes TEXT
);

-- Exercises actually recorded in a session, independent of template edits.
CREATE TABLE session_exercise (
    id BIGSERIAL PRIMARY KEY,
    session_id BIGINT NOT NULL REFERENCES training_session(id),
    -- Stable template slot for matching previous results, even after reordering.
    -- Keep historical exercise/results if the template slot is removed.
    routine_exercise_id BIGINT REFERENCES routine_exercise(id) ON DELETE SET NULL,
    exercise_id BIGINT NOT NULL REFERENCES exercise(id),
    exercise_order INTEGER NOT NULL,
    notes TEXT
);

-- Actual set results, separate from saved routine defaults.
-- On routine load, use the owner's latest completed session for this routine.
-- Copy its matching set measurements into NEW session rows; reset completed to FALSE.
-- Use saved routine sets when no matching previous result exists; never reuse history rows.
CREATE TABLE exercise_set (
    id BIGSERIAL PRIMARY KEY,
    session_exercise_id BIGINT NOT NULL REFERENCES session_exercise(id),
    set_number INTEGER NOT NULL,
    reps INTEGER,
    weight_kg DECIMAL(8,2),
    duration_seconds INTEGER,
    distance_km DECIMAL(8,2),
    completed BOOLEAN NOT NULL DEFAULT FALSE
);

-- Personal physical goals; metric/unit decisions remain pending.
CREATE TABLE physical_goal (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id),
    -- Values: build_muscle, lose_fat, gain_weight, maintain_weight.
    -- Target metric/unit and interpretation remain pending DEC-01.
    goal_type VARCHAR(50) NOT NULL,
    target_value DECIMAL(8,2) NOT NULL,
    start_date DATE NOT NULL DEFAULT CURRENT_DATE,
    target_date DATE,
    completed_at TIMESTAMP
);

-- User-owned dated observations for overall evolution and physical-goal progress.
-- Measurements remain available when goals change; units are explicit in column names.
CREATE TABLE body_measurement (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id),
    date DATE NOT NULL DEFAULT CURRENT_DATE,
    weight_kg DECIMAL(5,2),
    body_fat_percentage DECIMAL(5,2),
    muscle_mass_kg DECIMAL(5,2),
    waist_cm DECIMAL(5,2),
    chest_cm DECIMAL(5,2),
    arm_cm DECIMAL(5,2),
    thigh_cm DECIMAL(5,2)
);

-- Imported global catalogue identities; manual and user-owned exercises are independent.
CREATE UNIQUE INDEX ix_exercise_catalogue_source_external_id ON exercise (source, external_id)
WHERE user_id IS NULL AND external_id IS NOT NULL AND source <> 'manual';
