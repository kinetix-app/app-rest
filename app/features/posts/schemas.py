"""Public posts API contracts, separate from persistence metadata."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.features.posts.models import FileType, PostType, PostVisibility
from app.features.training.schemas import ExerciseResponse

MAX_POST_CAPTION = 160
MAX_POST_DESCRIPTION = 2200
MAX_COMMENT_TEXT = 1000


class PostAuthor(BaseModel):
    id: int
    display_name: str | None
    # Load the photo from GET /api/v1/people/{id}/picture when true.
    has_picture: bool = False


class WorkoutSummary(BaseModel):
    """Deterministic totals of the shared completed workout."""

    session_id: int
    title: str
    activity_type: str
    started_at: datetime
    ended_at: datetime
    duration_seconds: int
    exercise_count: int
    set_count: int
    total_reps: int
    # Sum of reps x weight_kg over recorded sets, rounded half-up to 0.01 kg.
    total_volume_kg: Decimal
    exercises: list[str]


class WorkoutSet(BaseModel):
    set_number: int
    reps: int | None
    weight_kg: Decimal | None
    duration_seconds: int | None
    distance_km: Decimal | None


class WorkoutExercise(BaseModel):
    exercise_id: int
    name: str
    image_url: str | None
    sets: list[WorkoutSet]


class WorkoutDetail(WorkoutSummary):
    """Everything the author recorded in the shared workout, in the order it was done."""

    detailed_exercises: list[WorkoutExercise]


class WorkoutTemplateExercise(BaseModel):
    exercise: ExerciseResponse
    sets: list[WorkoutSet]


class WorkoutTemplate(BaseModel):
    title: str
    exercises: list[WorkoutTemplateExercise]
    skipped_exercises: list[str]


class PostMedia(BaseModel):
    id: int
    type: FileType
    order: int
    # Authenticated API path; the private bucket URL is never exposed.
    url: str


class PostResponse(BaseModel):
    id: int
    caption: str
    description: str
    text: str = Field(deprecated=True, description="Legacy alias of description")
    visibility: PostVisibility
    type: PostType
    created_at: datetime
    author: PostAuthor
    workout: WorkoutSummary | None
    media: list[PostMedia]
    like_count: int
    comment_count: int
    liked_by_me: bool
    is_mine: bool


class PostPage(BaseModel):
    items: list[PostResponse]
    # Pass as before_id to fetch the next (older) page; null when there are no more posts.
    next_before_id: int | None


class LikeResponse(BaseModel):
    liked: bool
    like_count: int


class CommentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    comment: str = Field(min_length=1, max_length=MAX_COMMENT_TEXT)


class CommentResponse(BaseModel):
    id: int
    post_id: int
    author: PostAuthor
    comment: str
    created_at: datetime
    is_mine: bool


class CommentPage(BaseModel):
    items: list[CommentResponse]
    # Pass as after_id to fetch the next (newer) page; null when there are no more comments.
    next_after_id: int | None
