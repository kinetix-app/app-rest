"""Routine editing and exercise selection endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Path, Query, Response
from pydantic import StringConstraints

from app.core.auth.dependencies import CurrentUser
from app.db.session import DatabaseSession
from app.features.training import drafts, service, sessions
from app.features.training.errors import IdempotencyConflict, InvalidSelection, TrainingNotFound
from app.features.training.schemas import (
    BodyPartList,
    DraftFinish,
    DraftResponse,
    DraftSnapshot,
    ExerciseConfiguration,
    ExercisePage,
    ExerciseResponse,
    MuscleGroupList,
    RoutineCreate,
    RoutinePage,
    RoutinePatch,
    RoutineResponse,
    SessionCreate,
    SessionPage,
    SessionResponse,
)
from app.features.training.units import WeightUnit

router = APIRouter(tags=["training"])
ResourceId = Annotated[int, Path(gt=0, le=2**63 - 1)]
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0, le=2**63 - 1)]
BodyPart = Annotated[str, StringConstraints(max_length=100)]
ROUTINE_NOT_FOUND_DETAIL = "Routine not found"


@router.get("/exercises")
async def get_exercises(
    user: CurrentUser,
    session: DatabaseSession,
    muscle_group: Annotated[str | None, Query(max_length=100)] = None,
    name: Annotated[str | None, Query(max_length=200)] = None,
    body_part: Annotated[list[BodyPart] | None, Query(max_length=30)] = None,
    limit: Limit = 50,
    offset: Offset = 0,
) -> ExercisePage:
    return await service.list_exercises(
        session, user.id, limit, offset, muscle_group, name, body_part
    )


@router.get("/exercises/body-parts")
async def get_body_parts(user: CurrentUser, session: DatabaseSession) -> BodyPartList:
    return await service.list_body_parts(session, user.id)


@router.get("/exercises/muscle-groups")
async def get_muscle_groups(user: CurrentUser, session: DatabaseSession) -> MuscleGroupList:
    return await service.list_muscle_groups(session, user.id)


@router.get("/exercises/{exercise_id}", responses={404: {"description": "Exercise not found"}})
async def get_exercise(
    exercise_id: ResourceId, user: CurrentUser, session: DatabaseSession
) -> ExerciseResponse:
    try:
        return await service.get_exercise(session, user.id, exercise_id)
    except TrainingNotFound:
        raise HTTPException(404, "Exercise not found") from None


@router.get("/routines")
async def get_routines(
    user: CurrentUser,
    session: DatabaseSession,
    limit: Limit = 50,
    offset: Offset = 0,
    name: Annotated[str | None, Query(max_length=150)] = None,
) -> RoutinePage:
    return await service.list_routines(session, user.id, limit, offset, name)


@router.get(
    "/routines/{routine_id}",
    responses={404: {"description": ROUTINE_NOT_FOUND_DETAIL}},
)
async def get_routine(
    routine_id: ResourceId,
    user: CurrentUser,
    session: DatabaseSession,
    weight_unit: WeightUnit = "kg",
) -> RoutineResponse:
    try:
        return await service.get_routine(session, user.id, routine_id, weight_unit)
    except TrainingNotFound:
        raise HTTPException(404, ROUTINE_NOT_FOUND_DETAIL) from None


@router.post(
    "/routines",
    status_code=201,
    responses={
        404: {"description": ROUTINE_NOT_FOUND_DETAIL},
        422: {"description": "Exercise selection is unavailable"},
    },
)
async def post_routine(
    data: RoutineCreate, user: CurrentUser, session: DatabaseSession, weight_unit: WeightUnit = "kg"
) -> RoutineResponse:
    try:
        return await service.create_routine(session, user.id, data, weight_unit)
    except InvalidSelection:
        raise HTTPException(422, "Exercise selection is unavailable") from None
    except TrainingNotFound:
        raise HTTPException(404, ROUTINE_NOT_FOUND_DETAIL) from None


@router.patch(
    "/routines/{routine_id}",
    responses={
        404: {"description": ROUTINE_NOT_FOUND_DETAIL},
        422: {"description": "Exercise or routine slot selection is unavailable"},
    },
)
async def patch_routine(
    routine_id: ResourceId,
    data: RoutinePatch,
    user: CurrentUser,
    session: DatabaseSession,
    weight_unit: WeightUnit = "kg",
) -> RoutineResponse:
    try:
        return await service.update_routine(session, user.id, routine_id, data, weight_unit)
    except TrainingNotFound:
        raise HTTPException(404, ROUTINE_NOT_FOUND_DETAIL) from None
    except InvalidSelection:
        raise HTTPException(422, "Exercise or routine slot selection is unavailable") from None


@router.post(
    "/sessions",
    status_code=201,
    responses={
        409: {"description": "Client session ID already has different workout content"},
        422: {"description": "Exercise or routine source selection is unavailable"},
    },
)
async def post_session(
    data: SessionCreate,
    user: CurrentUser,
    session: DatabaseSession,
    response: Response,
    weight_unit: WeightUnit = "kg",
) -> SessionResponse:
    try:
        result, created = await sessions.create_session(session, user.id, data, weight_unit)
        response.status_code = 201 if created else 200
        return result
    except IdempotencyConflict:
        raise HTTPException(
            409, "Client session ID already has different workout content"
        ) from None
    except InvalidSelection:
        raise HTTPException(422, "Exercise or routine source selection is unavailable") from None


@router.get("/sessions")
async def get_sessions(
    user: CurrentUser,
    session: DatabaseSession,
    limit: Limit = 50,
    offset: Offset = 0,
    weight_unit: WeightUnit = "kg",
) -> SessionPage:
    return await sessions.list_sessions(session, user.id, limit, offset, weight_unit)


@router.get("/sessions/{session_id}", responses={404: {"description": "Session not found"}})
async def get_session(
    session_id: ResourceId,
    user: CurrentUser,
    session: DatabaseSession,
    weight_unit: WeightUnit = "kg",
) -> SessionResponse:
    try:
        return await sessions.get_session(session, user.id, session_id, weight_unit)
    except TrainingNotFound:
        raise HTTPException(404, "Session not found") from None


@router.get("/session-drafts")
async def get_draft(user: CurrentUser, session: DatabaseSession) -> DraftResponse | None:
    return await drafts.latest_draft(session, user.id)


@router.put(
    "/session-drafts/{client_session_id}",
    responses={
        409: {"description": "Draft conflicts with an active or completed workout"},
        422: {"description": "Exercise or routine source selection is unavailable"},
    },
)
async def put_draft(
    client_session_id: UUID, data: DraftSnapshot, user: CurrentUser, session: DatabaseSession
) -> DraftResponse:
    try:
        return await drafts.save_draft(session, user.id, client_session_id, data)
    except IdempotencyConflict:
        raise HTTPException(409, "Draft conflicts with an active or completed workout") from None
    except InvalidSelection:
        raise HTTPException(422, "Exercise or routine source selection is unavailable") from None


@router.delete(
    "/session-drafts/{client_session_id}",
    status_code=204,
    responses={409: {"description": "Completed workouts cannot be discarded"}},
)
async def delete_draft(
    client_session_id: UUID, user: CurrentUser, session: DatabaseSession
) -> Response:
    try:
        await drafts.discard_draft(session, user.id, client_session_id)
        return Response(status_code=204)
    except IdempotencyConflict:
        raise HTTPException(409, "Completed workouts cannot be discarded") from None


@router.post(
    "/session-drafts/{client_session_id}/finish",
    responses={
        404: {"description": "Draft not found"},
        409: {"description": "Workout finished with different time or routine update choices"},
        422: {"description": "Provide a valid finish time and available routine/exercise sources"},
    },
)
async def finish_draft(
    client_session_id: UUID,
    data: DraftFinish,
    user: CurrentUser,
    session: DatabaseSession,
    weight_unit: WeightUnit = "kg",
) -> SessionResponse:
    try:
        return await drafts.finish_draft(session, user.id, client_session_id, data, weight_unit)
    except IdempotencyConflict:
        raise HTTPException(
            409, "Workout already finished with a different time or routine update decision"
        ) from None
    except TrainingNotFound:
        raise HTTPException(404, "Draft not found") from None
    except InvalidSelection:
        raise HTTPException(
            422, "Provide a valid finish time and available routine/exercise sources"
        ) from None


@router.get(
    "/exercises/{exercise_id}/last-configuration",
    responses={404: {"description": "Exercise not found"}},
)
async def get_last_configuration(
    exercise_id: ResourceId,
    user: CurrentUser,
    session: DatabaseSession,
    weight_unit: WeightUnit = "kg",
) -> ExerciseConfiguration:
    try:
        return await service.get_last_configuration(session, user.id, exercise_id, weight_unit)
    except TrainingNotFound:
        raise HTTPException(404, "Exercise not found") from None
