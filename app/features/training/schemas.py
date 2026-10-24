"""Public training API contracts, separate from persistence metadata."""

from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

EntityId = Annotated[int, Field(strict=True, gt=0, le=2**63 - 1)]


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class PlannedSet(InputModel):
    reps: int = Field(strict=True, ge=1, le=2**31 - 1)
    weight_kg: Decimal = Field(ge=0, max_digits=8, decimal_places=2, allow_inf_nan=False)


class ExerciseSelection(InputModel):
    exercise_id: EntityId
    sets: list[PlannedSet] | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def validate_sets(self) -> Self:
        if "sets" in self.model_fields_set and self.sets is None:
            raise ValueError("Sets cannot be null; omit to preserve or use [] to clear")
        return self


class ExerciseSelectionPatch(ExerciseSelection):
    id: EntityId | None = None


class RoutineCreate(InputModel):
    name: str = Field(min_length=1, max_length=150)
    exercises: list[ExerciseSelection] = Field(min_length=1, max_length=500)


class RoutinePatch(InputModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    exercises: list[ExerciseSelectionPatch] | None = Field(
        default=None, min_length=1, max_length=500
    )

    @model_validator(mode="after")
    def validate_changes(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("Supply name or exercises")
        if any(getattr(self, key) is None for key in self.model_fields_set):
            raise ValueError("Name and exercises cannot be null")
        if self.exercises is not None:
            ids = [item.id for item in self.exercises if item.id is not None]
            if len(ids) != len(set(ids)):
                raise ValueError("Routine slot IDs must be unique")
        return self


class ExerciseResponse(BaseModel):
    id: int
    activity_type: str
    name: str
    overview: str | None
    body_parts: list[str] | None
    equipments: list[str] | None
    exercise_types: list[str] | None
    target_muscles: list[str] | None
    secondary_muscles: list[str] | None
    instructions: list[str] | None
    exercise_tips: list[str] | None
    variations: list[str] | None
    keywords: list[str] | None
    difficulty: str | None
    image_url: str | None
    image_urls: dict[str, str] | None
    video_url: str | None
    gif_urls: dict[str, str] | None


class SetResponse(BaseModel):
    set_number: int
    reps: int | None
    weight_kg: Decimal | None
    duration_seconds: int | None
    distance_km: Decimal | None


class RoutineExerciseResponse(BaseModel):
    id: int
    exercise_order: int
    exercise: ExerciseResponse
    notes: str | None
    default_sets: list[SetResponse]
    sets: list[SetResponse]
    sets_source: Literal["routine", "latest_session"]


class RoutineSummary(BaseModel):
    id: int
    name: str


class RoutineResponse(RoutineSummary):
    exercises: list[RoutineExerciseResponse]


class RoutinePage(BaseModel):
    items: list[RoutineSummary]
    limit: int
    offset: int


class ExerciseSummary(BaseModel):
    id: int
    name: str
    activity_type: str
    body_parts: list[str] | None
    target_muscles: list[str] | None
    equipments: list[str] | None
    image_url: str | None


class MuscleGroupList(BaseModel):
    items: list[str]


class BodyPartList(BaseModel):
    items: list[str]


class ExercisePage(BaseModel):
    items: list[ExerciseSummary]
    limit: int
    offset: int
