"""Expected nutrition use-case failures, independent of HTTP transport."""


class NutritionError(Exception):
    """Base class for expected nutrition failures."""


class FoodNotFoundError(NutritionError):
    pass


class RecipeNotFoundError(NutritionError):
    pass


class MealItemNotFoundError(NutritionError):
    pass


class NutritionGoalNotFoundError(NutritionError):
    pass


class FoodInUseError(NutritionError):
    pass


class RecipeInUseError(NutritionError):
    pass
