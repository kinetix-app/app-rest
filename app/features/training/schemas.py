"""Public training API contracts, separate from persistence metadata."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.json_schema import SkipJsonSchema

from app.features.training.units import WeightUnit, canonical_weight

EntityId = Annotated[int, Field(strict=True, gt=0, le=2**63 - 1)]


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class WeightInput(InputModel):
    value: Decimal = Field(ge=0, max_digits=16, decimal_places=8, allow_inf_nan=False)
    unit: WeightUnit

    @field_validator("value", mode="before")
    @classmethod
    def decimal_text(cls, value):
        if not isinstance(value, str):
            raise ValueError("Weight value must be decimal text")
        return value

    @model_validator(mode="after")
    def valid_mass(self) -> Self:
        canonical_weight(self.value, self.unit)
        return self


class WeightResponse(BaseModel):
    value: Decimal
    unit: WeightUnit


class PlannedSet(InputModel):
    reps: int = Field(strict=True, ge=1, le=2**31 - 1)
    weight_kg: Decimal | None = Field(
        default=None, ge=0, max_digits=8, decimal_places=2, allow_inf_nan=False
    )
    weight: WeightInput | None = None

    @model_validator(mode="after")
    def one_mass(self) -> Self:
        if (self.weight is None) == (self.weight_kg is None):
            raise ValueError("Supply exactly one of weight or weight_kg")
        if "weight" in self.model_fields_set and "weight_kg" in self.model_fields_set:
            raise ValueError("Supply exactly one of weight or weight_kg")
        return self

    def canonical_kg(self) -> Decimal:
        if self.weight is not None:
            return canonical_weight(self.weight.value, self.weight.unit)
        assert self.weight_kg is not None
        return canonical_weight(self.weight_kg, "kg")


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
    weight: WeightResponse | None = None
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


class CompletedSet(InputModel):
    reps: int = Field(strict=True, ge=1, le=2**31 - 1)
    weight: WeightInput


class CompletedExercise(InputModel):
    exercise_id: EntityId
    routine_exercise_id: SkipJsonSchema[EntityId | None] = Field(default=None, exclude=True)
    sets: list[CompletedSet] = Field(max_length=100)


class SessionCreate(InputModel):
    client_session_id: UUID
    routine_id: EntityId | None = None
    started_at: AwareDatetime
    ended_at: AwareDatetime
    exercises: list[CompletedExercise] = Field(max_length=500)

    @model_validator(mode="after")
    def ordered_events(self) -> Self:
        if self.ended_at < self.started_at:
            raise ValueError("Ended time must not precede start time")
        return self


class SessionExerciseResponse(BaseModel):
    id: int
    exercise_order: int
    exercise: ExerciseResponse
    sets: list[SetResponse]


class SessionResponse(BaseModel):
    id: int
    client_session_id: UUID | None
    routine_id: int | None
    activity_type: str
    state: Literal["completed"] = "completed"
    started_at: datetime
    ended_at: datetime
    exercises: list[SessionExerciseResponse]


class SessionPage(BaseModel):
    items: list[SessionResponse]
    limit: int
    offset: int


class DraftSet(InputModel):
    @model_validator(mode="before")
    @classmethod
    def ignore_invalid_unconfirmed_values(cls, value):
        if isinstance(value, dict) and value.get("completed") is False:
            value = dict(value)
            reps = value.get("reps")
            if type(reps) is not int or not 1 <= reps <= 2**31 - 1:
                value["reps"] = None
            try:
                if value.get("weight") is not None:
                    value["weight"] = WeightInput.model_validate(value["weight"])
            except ValueError:
                value["weight"] = None
        return value

    client_id: UUID
    reps: int | None = Field(default=None, strict=True, ge=1, le=2**31 - 1)
    weight: WeightInput | None = None
    completed: bool = Field(strict=True)

    @model_validator(mode="after")
    def confirmed_values(self) -> Self:
        if self.completed and (self.reps is None or self.weight is None):
            raise ValueError("Confirmed sets require repetitions and weight")
        return self


class DraftExercise(InputModel):
    @model_validator(mode="before")
    @classmethod
    def discard_legacy_slot(cls, value):
        if isinstance(value, dict):
            return {key: item for key, item in value.items() if key != "routine_exercise_id"}
        return value

    client_id: UUID
    exercise_id: EntityId
    sets: list[DraftSet] = Field(max_length=100)

    @model_validator(mode="after")
    def unique_sets(self) -> Self:
        ids = [item.client_id for item in self.sets]
        if len(ids) != len(set(ids)):
            raise ValueError("Set client IDs must be unique")
        return self


class DraftSnapshot(InputModel):
    routine_id: EntityId | None = None
    name: str = Field(min_length=1, max_length=150)
    started_at: AwareDatetime
    exercises: list[DraftExercise] = Field(max_length=500)

    @model_validator(mode="after")
    def valid_exercises(self) -> Self:
        ids = [item.client_id for item in self.exercises]
        if len(ids) != len(set(ids)):
            raise ValueError("Exercise client IDs must be unique")
        return self


class DraftResponse(DraftSnapshot):
    client_session_id: UUID
    state: Literal["draft"] = "draft"


class DraftFinish(InputModel):
    ended_at: AwareDatetime
    update_routine: bool = Field(default=False, strict=True)


class ExerciseConfiguration(BaseModel):
    exercise_id: int
    sets: list[SetResponse]
