-- Product schema draft for DAT01; this file is not an Alembic migration.
-- Account fields originate in revision 20261013_01; this draft unifies local IDs as BIGINT.
-- Runtime accounts still use UUIDs and their existing constraints until a follow-up migration.
-- Apply migrations through `make migrate`, not by loading this draft into the app DB.
-- Sprint 1 assessment and AscendAPI import proposal: docs/data-model-review.md.

-- Local entity IDs use BIGSERIAL primary keys (PostgreSQL BIGINT plus a sequence).
-- References use BIGINT without their own sequence, including profiles.user_id.
-- Profiles reuse the user primary key to keep the one-profile-per-user relationship.
-- Credentials/session validation belong to the configured authentication adapter.
-- updated_at is maintained by SQLAlchemy on updates; there is no database trigger.
CREATE TABLE users (
    id BIGSERIAL PRIMARY KEY,
    status VARCHAR(16) NOT NULL DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE auth_accounts (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    issuer VARCHAR(512) NOT NULL,
    subject VARCHAR(255) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_auth_accounts_user_id_users
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE RESTRICT
);

CREATE INDEX ix_auth_accounts_user_id ON auth_accounts (user_id);

CREATE TABLE profiles (
    user_id BIGINT NOT NULL PRIMARY KEY,
    display_name VARCHAR(100),
    timezone VARCHAR(100),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_profiles_user_id_users
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- Proposed feature tables below have not been migrated.
-- Business rules (bounds, valid states, uniqueness and ownership) belong in services.
-- Primary/foreign keys and required columns describe the structural model.
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
    user_id BIGINT NOT NULL REFERENCES users(id),
    calories DECIMAL(8,2) NOT NULL,
    protein DECIMAL(8,2) NOT NULL,
    carbohydrates DECIMAL(8,2) NOT NULL,
    fats DECIMAL(8,2) NOT NULL
);

-- Available sports and activity types.
CREATE TABLE sport (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    description TEXT
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
    sport_id BIGINT NOT NULL REFERENCES sport(id),
    name TEXT NOT NULL,
    overview TEXT,
    body_parts TEXT[],
    equipments TEXT[],
    exercise_types TEXT[],
    target_muscles TEXT[],
    secondary_muscles TEXT[],
    instructions TEXT[],
    exercise_tips TEXT[],
    variations TEXT[],
    keywords TEXT[],
    difficulty TEXT,
    related_exercise_ids TEXT[],
    video_url TEXT,
    image_url TEXT,

    gif_urls JSONB,
    source TEXT NOT NULL DEFAULT 'manual',
    external_id TEXT,
    imported_at TIMESTAMP WITH TIME ZONE
);

-- Training routines, created by users or generated by AI
CREATE TABLE routine (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(id),
    name VARCHAR(150) NOT NULL,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Exercises included in a routine, with their planned sets, reps and other parameters
CREATE TABLE routine_exercise (
    id BIGSERIAL PRIMARY KEY,
    routine_id BIGINT NOT NULL REFERENCES routine(id),
    exercise_id BIGINT NOT NULL REFERENCES exercise(id),
    exercise_order INTEGER NOT NULL,
    sets INTEGER,
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
    sport_id BIGINT NOT NULL REFERENCES sport(id),
    started_at TIMESTAMP NOT NULL,
    ended_at TIMESTAMP,
    notes TEXT
);

-- Exercises actually recorded in a session, independent of template edits.
CREATE TABLE session_exercise (
    id BIGSERIAL PRIMARY KEY,
    session_id BIGINT NOT NULL REFERENCES training_session(id),
    exercise_id BIGINT NOT NULL REFERENCES exercise(id),
    exercise_order INTEGER NOT NULL,
    notes TEXT
);

-- Actual set results, separate from planned routine values.
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

-- Chosen activity targets and periods; remaining product rules are pending.
CREATE TABLE activity_goal (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id),
    sport_id BIGINT REFERENCES sport(id),
    goal_type VARCHAR(30) NOT NULL,
    target_value DECIMAL(10,2) NOT NULL,
    period VARCHAR(20) NOT NULL,
    start_date DATE NOT NULL DEFAULT CURRENT_DATE,
    end_date DATE
);

-- Personal physical goals; metric/unit decisions remain pending.
CREATE TABLE physical_goal (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id),
    goal_type VARCHAR(50) NOT NULL,
    target_value DECIMAL(8,2) NOT NULL,
    start_date DATE NOT NULL DEFAULT CURRENT_DATE,
    target_date DATE,
    completed_at TIMESTAMP
);

-- Dated observations with explicit units in column names.
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

-- Intermediate targets belonging to a physical goal.
CREATE TABLE goal_milestone (
    id BIGSERIAL PRIMARY KEY,
    physical_goal_id BIGINT NOT NULL REFERENCES physical_goal(id),
    target_value DECIMAL(8,2) NOT NULL,
    target_date DATE,
    completed_at TIMESTAMP
);
