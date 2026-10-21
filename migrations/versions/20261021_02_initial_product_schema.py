"""Initial nutrition, training and goal tables from db-schema.sql.

Account UUIDs are converted to generated BIGINTs by the preceding revision.
This is a frozen schema snapshot, independent of future draft edits.
"""

from alembic import op

revision = "20261021_02"
down_revision = "20261021_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
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
        )
    """)
    op.execute("""
        CREATE TABLE recipe (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT REFERENCES users(id),
            name VARCHAR(150) NOT NULL,
            description TEXT,
            instructions TEXT,
            servings INTEGER NOT NULL DEFAULT 1
        )
    """)
    op.execute("""
        CREATE TABLE recipe_ingredient (
            id BIGSERIAL PRIMARY KEY,
            recipe_id BIGINT NOT NULL REFERENCES recipe(id),
            food_id BIGINT NOT NULL REFERENCES food(id),
            quantity_grams DECIMAL(8,2) NOT NULL
        )
    """)
    op.execute("""
        CREATE TABLE nutrition_day (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL REFERENCES users(id),
            date DATE NOT NULL
        )
    """)
    op.execute("""
        CREATE TABLE meal (
            id BIGSERIAL PRIMARY KEY,
            nutrition_day_id BIGINT NOT NULL REFERENCES nutrition_day(id),
            -- Proposed values: breakfast, lunch, dinner, snack; final meal categories pending.
            meal_type VARCHAR(30) NOT NULL
        )
    """)
    op.execute(
        "COMMENT ON COLUMN meal.meal_type IS 'Proposed values: breakfast, lunch, dinner, "
        "snack; final meal categories pending.'"
    )
    op.execute("""
        CREATE TABLE meal_item (
            id BIGSERIAL PRIMARY KEY,
            meal_id BIGINT NOT NULL REFERENCES meal(id),
            food_id BIGINT REFERENCES food(id),
            recipe_id BIGINT REFERENCES recipe(id),
            quantity_grams DECIMAL(8,2),
            servings DECIMAL(8,2)
        )
    """)
    op.execute("""
        CREATE TABLE nutrition_goal (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL REFERENCES users(id),
            calories DECIMAL(8,2) NOT NULL,
            protein DECIMAL(8,2) NOT NULL,
            carbohydrates DECIMAL(8,2) NOT NULL,
            fats DECIMAL(8,2) NOT NULL
        )
    """)
    op.execute("""
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
            -- Proposed values: strength, cardio, stretching, mobility;
            -- catalogue vocabulary pending.
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
            imported_at TIMESTAMP WITH TIME ZONE
        )
    """)
    op.execute(
        "COMMENT ON COLUMN exercise.activity_type IS 'Values: gym, running, cycling, "
        "walking. Sprint 1 uses gym.'"
    )
    op.execute(
        "COMMENT ON COLUMN exercise.exercise_types IS 'Provider/manual classification, "
        "distinct from activity_type. Proposed values: strength, cardio, stretching, "
        "mobility; catalogue vocabulary pending.'"
    )
    op.execute(
        "COMMENT ON COLUMN exercise.difficulty IS 'Proposed values: beginner, "
        "intermediate, advanced; catalogue vocabulary pending.'"
    )
    op.execute(
        "COMMENT ON COLUMN exercise.source IS 'Values: manual, ascend_edb_v1, "
        "ascend_edb_v2; extend when another source is added.'"
    )
    op.execute("""
        CREATE TABLE routine (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT REFERENCES users(id),
            name VARCHAR(150) NOT NULL,
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("""
        CREATE TABLE routine_exercise (
            id BIGSERIAL PRIMARY KEY,
            routine_id BIGINT NOT NULL REFERENCES routine(id),
            exercise_id BIGINT NOT NULL REFERENCES exercise(id),
            exercise_order INTEGER NOT NULL,
            notes TEXT
        )
    """)
    op.execute("""
        CREATE TABLE routine_exercise_set (
            id BIGSERIAL PRIMARY KEY,
            routine_exercise_id BIGINT NOT NULL REFERENCES routine_exercise(id),
            set_number INTEGER NOT NULL,
            reps INTEGER,
            weight_kg DECIMAL(8,2),
            duration_seconds INTEGER,
            distance_km DECIMAL(8,2)
        )
    """)
    op.execute("""
        CREATE TABLE training_session (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL REFERENCES users(id),
            routine_id BIGINT REFERENCES routine(id),
            -- Values: gym, running, cycling, walking. Sprint 1 uses gym.
            activity_type VARCHAR(30) NOT NULL,
            started_at TIMESTAMP NOT NULL,
            ended_at TIMESTAMP,
            notes TEXT
        )
    """)
    op.execute(
        "COMMENT ON COLUMN training_session.activity_type IS 'Values: gym, running, "
        "cycling, walking. Sprint 1 uses gym.'"
    )
    op.execute("""
        CREATE TABLE session_exercise (
            id BIGSERIAL PRIMARY KEY,
            session_id BIGINT NOT NULL REFERENCES training_session(id),
            -- Stable template slot for matching previous results, even after reordering.
            -- Keep historical exercise/results if the template slot is removed.
            routine_exercise_id BIGINT REFERENCES routine_exercise(id) ON DELETE SET NULL,
            exercise_id BIGINT NOT NULL REFERENCES exercise(id),
            exercise_order INTEGER NOT NULL,
            notes TEXT
        )
    """)
    op.execute(
        "COMMENT ON COLUMN session_exercise.routine_exercise_id IS 'Stable template slot "
        "for matching previous results, even after reordering. Keep historical "
        "exercise/results if the template slot is removed.'"
    )
    op.execute("""
        CREATE TABLE exercise_set (
            id BIGSERIAL PRIMARY KEY,
            session_exercise_id BIGINT NOT NULL REFERENCES session_exercise(id),
            set_number INTEGER NOT NULL,
            reps INTEGER,
            weight_kg DECIMAL(8,2),
            duration_seconds INTEGER,
            distance_km DECIMAL(8,2),
            completed BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)
    op.execute("""
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
        )
    """)
    op.execute(
        "COMMENT ON COLUMN physical_goal.goal_type IS 'Values: build_muscle, lose_fat, "
        "gain_weight, maintain_weight. Target metric/unit and interpretation remain "
        "pending DEC-01.'"
    )
    op.execute("""
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
        )
    """)


def downgrade() -> None:
    op.drop_table("body_measurement")
    op.drop_table("physical_goal")
    op.drop_table("exercise_set")
    op.drop_table("session_exercise")
    op.drop_table("training_session")
    op.drop_table("routine_exercise_set")
    op.drop_table("routine_exercise")
    op.drop_table("routine")
    op.drop_table("exercise")
    op.drop_table("nutrition_goal")
    op.drop_table("meal_item")
    op.drop_table("meal")
    op.drop_table("nutrition_day")
    op.drop_table("recipe_ingredient")
    op.drop_table("recipe")
    op.drop_table("food")
