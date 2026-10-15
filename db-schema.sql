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
    user_id BIGINT,
    name VARCHAR(150) NOT NULL,
    brand VARCHAR(100),
    calories DECIMAL(8,2) NOT NULL,
    protein DECIMAL(8,2) NOT NULL,
    carbohydrates DECIMAL(8,2) NOT NULL,
    fats DECIMAL(8,2) NOT NULL,
    barcode VARCHAR(50),

    CONSTRAINT food_nutrition_nonnegative_check CHECK (
        calories >= 0 AND protein >= 0 AND carbohydrates >= 0 AND fats >= 0
    )
);

-- Recipe table
CREATE TABLE recipe (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT,
    name VARCHAR(150) NOT NULL,
    description TEXT,
    instructions TEXT,
    servings INTEGER NOT NULL DEFAULT 1,

    CONSTRAINT recipe_servings_positive_check CHECK (servings > 0)
);

-- Ingredients of a recipe, relate to recipes and food
CREATE TABLE recipe_ingredient (
    id BIGSERIAL PRIMARY KEY,
    recipe_id BIGINT NOT NULL REFERENCES recipe(id),
    food_id BIGINT NOT NULL REFERENCES food(id),
    quantity_grams DECIMAL(8,2) NOT NULL,

    CONSTRAINT recipe_ingredient_quantity_positive_check CHECK (quantity_grams > 0)
);


-- The total nutrition for a day, relate to a date
CREATE TABLE nutrition_day (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    date DATE NOT NULL,

    CONSTRAINT nutrition_day_user_date_unique UNIQUE (user_id, date)
);


-- Meals for a day, relate to nutrition_day
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
    servings DECIMAL(8,2),

    CONSTRAINT meal_item_source_check CHECK (
        (food_id IS NOT NULL AND recipe_id IS NULL AND quantity_grams > 0 AND servings IS NULL)
        OR
        (recipe_id IS NOT NULL AND food_id IS NULL AND servings > 0 AND quantity_grams IS NULL)
    )
);

-- Daily nutritional goals for each user
CREATE TABLE nutrition_goal (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id),
    calories DECIMAL(8,2) NOT NULL,
    protein DECIMAL(8,2) NOT NULL,
    carbohydrates DECIMAL(8,2) NOT NULL,
    fats DECIMAL(8,2) NOT NULL,

    CONSTRAINT nutrition_goal_values_check CHECK (
        calories > 0 AND protein >= 0 AND carbohydrates >= 0 AND fats >= 0
    )
);
