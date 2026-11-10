"""Routine editing and exercise selection endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Path, Query, Request, Response, UploadFile
from pydantic import StringConstraints

from app.core.auth.dependencies import CurrentUser
from app.db.session import DatabaseSession
from app.features.accounts.errors import (
    InvalidPicture,
    PictureMissing,
    PictureStorageUnavailable,
    PictureTooLarge,
    UnsupportedPicture,
)
from app.features.training import creation, deletion, drafts, pictures, service, sessions
from app.features.training.errors import (
    IdempotencyConflict,
    InvalidSelection,
    RoutineInUse,
    TrainingNotFound,
)
from app.features.training.schemas import (
    BodyPartList,
    DraftFinish,
    DraftResponse,
    DraftSnapshot,
    ExerciseConfiguration,
    ExercisePage,
    ExerciseResponse,
    MuscleGroupList,
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
EXERCISE_NOT_FOUND_DETAIL = "Exercise not found"
PICTURE_STORAGE_UNAVAILABLE_DETAIL = "Routine picture storage is unavailable"
PICTURE_TOO_LARGE_DETAIL = "Routine picture exceeds 5 MiB limit"


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


@router.get("/exercises/{exercise_id}", responses={404: {"description": EXERCISE_NOT_FOUND_DETAIL}})
async def get_exercise(
    exercise_id: ResourceId, user: CurrentUser, session: DatabaseSession
) -> ExerciseResponse:
    try:
        return await service.get_exercise(session, user.id, exercise_id)
    except TrainingNotFound:
        raise HTTPException(404, EXERCISE_NOT_FOUND_DETAIL) from None


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
    openapi_extra={"requestBody": creation.request_body_schema()},
    responses={
        404: {"description": ROUTINE_NOT_FOUND_DETAIL},
        413: {"description": "Routine content, image or request exceeds size limit"},
        415: {"description": "Unsupported request or image type"},
        422: {"description": "Invalid routine content, image or exercise selection"},
        503: {"description": PICTURE_STORAGE_UNAVAILABLE_DETAIL},
    },
)
async def post_routine(
    request: Request, user: CurrentUser, session: DatabaseSession, weight_unit: WeightUnit = "kg"
) -> RoutineResponse:
    try:
        data, file = await creation.parse_create(request)
        if file is None:
            return await service.create_routine(session, user.id, data, weight_unit)
        image = await file.read(pictures.MAX_PICTURE_BYTES + 1)
        return await pictures.create_with_picture(
            session,
            user.id,
            data,
            request.app.state.blob_storage,
            image,
            file.content_type,
            weight_unit,
        )
    except InvalidSelection:
        raise HTTPException(422, "Exercise selection is unavailable") from None
    except TrainingNotFound:
        raise HTTPException(404, ROUTINE_NOT_FOUND_DETAIL) from None
    except PictureTooLarge:
        raise HTTPException(413, PICTURE_TOO_LARGE_DETAIL) from None
    except UnsupportedPicture:
        raise HTTPException(415, "Use a JPEG, PNG or WebP image") from None
    except InvalidPicture:
        raise HTTPException(422, "Use a valid image with at most 16 million pixels") from None
    except PictureStorageUnavailable:
        raise HTTPException(503, PICTURE_STORAGE_UNAVAILABLE_DETAIL) from None
    finally:
        await request.close()


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


@router.delete(
    "/routines/{routine_id}",
    status_code=204,
    responses={
        404: {"description": ROUTINE_NOT_FOUND_DETAIL},
        409: {"description": "Finish or discard the workout using this routine before deleting it"},
    },
)
async def delete_routine(
    routine_id: ResourceId, user: CurrentUser, session: DatabaseSession, request: Request
) -> Response:
    try:
        await deletion.delete_routine(session, user.id, routine_id, request.app.state.blob_storage)
        return Response(status_code=204)
    except TrainingNotFound:
        raise HTTPException(404, ROUTINE_NOT_FOUND_DETAIL) from None
    except RoutineInUse:
        raise HTTPException(
            409, "Finish or discard the workout using this routine before deleting it"
        ) from None


@router.post(
    "/routines/{routine_id}/picture",
    responses={
        404: {"description": ROUTINE_NOT_FOUND_DETAIL},
        413: {"description": PICTURE_TOO_LARGE_DETAIL},
        415: {"description": "Unsupported image type"},
        422: {"description": "Invalid routine picture"},
        503: {"description": PICTURE_STORAGE_UNAVAILABLE_DETAIL},
    },
)
async def post_routine_picture(
    routine_id: ResourceId,
    user: CurrentUser,
    session: DatabaseSession,
    request: Request,
    file: UploadFile,
) -> RoutineResponse:
    try:
        data = await file.read(pictures.MAX_PICTURE_BYTES + 1)
        return await pictures.upload_picture(
            session, user.id, routine_id, request.app.state.blob_storage, data, file.content_type
        )
    except TrainingNotFound:
        raise HTTPException(404, ROUTINE_NOT_FOUND_DETAIL) from None
    except PictureTooLarge:
        raise HTTPException(413, PICTURE_TOO_LARGE_DETAIL) from None
    except UnsupportedPicture:
        raise HTTPException(415, "Use a JPEG, PNG or WebP image") from None
    except InvalidPicture:
        raise HTTPException(422, "Use a valid image with at most 16 million pixels") from None
    except PictureStorageUnavailable:
        raise HTTPException(503, PICTURE_STORAGE_UNAVAILABLE_DETAIL) from None
    finally:
        await file.close()


@router.get(
    "/routines/{routine_id}/picture",
    responses={
        404: {"description": "Routine picture not found"},
        503: {"description": PICTURE_STORAGE_UNAVAILABLE_DETAIL},
    },
)
async def get_routine_picture(
    routine_id: ResourceId,
    user: CurrentUser,
    session: DatabaseSession,
    request: Request,
) -> Response:
    try:
        data = await pictures.read_picture(
            session, user.id, routine_id, request.app.state.blob_storage
        )
        return Response(
            data, media_type="image/jpeg", headers={"Cache-Control": "private, no-store"}
        )
    except TrainingNotFound, PictureMissing:
        raise HTTPException(404, "Routine picture not found") from None
    except PictureStorageUnavailable:
        raise HTTPException(503, PICTURE_STORAGE_UNAVAILABLE_DETAIL) from None


@router.delete(
    "/routines/{routine_id}/picture",
    responses={404: {"description": ROUTINE_NOT_FOUND_DETAIL}},
)
async def delete_routine_picture(
    routine_id: ResourceId,
    user: CurrentUser,
    session: DatabaseSession,
    request: Request,
) -> RoutineResponse:
    try:
        return await pictures.remove_picture(
            session, user.id, routine_id, request.app.state.blob_storage
        )
    except TrainingNotFound:
        raise HTTPException(404, ROUTINE_NOT_FOUND_DETAIL) from None


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
    responses={404: {"description": EXERCISE_NOT_FOUND_DETAIL}},
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
        raise HTTPException(404, EXERCISE_NOT_FOUND_DETAIL) from None
