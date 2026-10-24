"""Routine editing and exercise selection endpoints."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import StringConstraints

from app.core.auth.dependencies import CurrentUser
from app.db.session import DatabaseSession
from app.features.training import service
from app.features.training.schemas import (
    BodyPartList,
    ExercisePage,
    ExerciseResponse,
    MuscleGroupList,
    RoutineCreate,
    RoutinePage,
    RoutinePatch,
    RoutineResponse,
)

router = APIRouter(tags=["training"])
ResourceId = Annotated[int, Path(gt=0, le=2**63 - 1)]
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0, le=2**63 - 1)]
BodyPart = Annotated[str, StringConstraints(max_length=100)]


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
    except service.TrainingNotFound:
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


@router.get("/routines/{routine_id}", responses={404: {"description": "Routine not found"}})
async def get_routine(
    routine_id: ResourceId, user: CurrentUser, session: DatabaseSession
) -> RoutineResponse:
    try:
        return await service.get_routine(session, user.id, routine_id)
    except service.TrainingNotFound:
        raise HTTPException(404, "Routine not found") from None


@router.post("/routines", status_code=201)
async def post_routine(
    data: RoutineCreate, user: CurrentUser, session: DatabaseSession
) -> RoutineResponse:
    try:
        return await service.create_routine(session, user.id, data)
    except service.InvalidSelection:
        raise HTTPException(422, "Exercise selection is unavailable") from None
    except service.TrainingNotFound:
        raise HTTPException(404, "Routine not found") from None


@router.patch("/routines/{routine_id}", responses={404: {"description": "Routine not found"}})
async def patch_routine(
    routine_id: ResourceId, data: RoutinePatch, user: CurrentUser, session: DatabaseSession
) -> RoutineResponse:
    try:
        return await service.update_routine(session, user.id, routine_id, data)
    except service.TrainingNotFound:
        raise HTTPException(404, "Routine not found") from None
    except service.InvalidSelection:
        raise HTTPException(422, "Exercise or routine slot selection is unavailable") from None
