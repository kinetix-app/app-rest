from fastapi import APIRouter, HTTPException
from fastapi.openapi.utils import validation_error_definition

from app.core.auth.dependencies import CurrentUser
from app.db.session import DatabaseSession
from app.features.accounts.service import AccountDenied
from app.features.goals.errors import (
    FutureMeasurement,
    MeasurementRequestConflict,
    ObjectiveChanged,
)
from app.features.goals.progress import (
    create_measurement,
    list_measurements,
    put_physical_target,
    read_physical_target,
)
from app.features.goals.progress_schemas import (
    MeasurementCreate,
    MeasurementHistory,
    MeasurementResponse,
    PhysicalTargetPut,
    PhysicalTargetResponse,
)

router = APIRouter(prefix="/me", tags=["progress"])


@router.get("/body-measurements")
async def get_measurements(user: CurrentUser, session: DatabaseSession) -> MeasurementHistory:
    return await list_measurements(session, user.id)


@router.post(
    "/body-measurements",
    status_code=201,
    responses={
        403: {"description": "Account access denied"},
        409: {"description": "Request conflict"},
        422: {
            "description": "Validation error or measurement date in the future",
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "properties": {
                            "detail": {
                                "anyOf": [
                                    {"type": "array", "items": validation_error_definition},
                                    {"type": "string"},
                                ]
                            }
                        },
                    }
                }
            },
        },
    },
)
async def post_measurement(
    value: MeasurementCreate, user: CurrentUser, session: DatabaseSession
) -> MeasurementResponse:
    try:
        return await create_measurement(session, user.id, value)
    except AccountDenied:
        raise HTTPException(403, "Account access denied") from None
    except FutureMeasurement:
        raise HTTPException(422, "Measurement date cannot be in the future") from None
    except MeasurementRequestConflict:
        raise HTTPException(409, "This request ID already belongs to another check-in") from None


@router.get("/physical-target")
async def get_target(user: CurrentUser, session: DatabaseSession) -> PhysicalTargetResponse:
    return await read_physical_target(session, user.id)


@router.put(
    "/physical-target",
    responses={
        403: {"description": "Account access denied"},
        409: {"description": "Objective changed"},
    },
)
async def put_target(
    value: PhysicalTargetPut, user: CurrentUser, session: DatabaseSession
) -> PhysicalTargetResponse:
    try:
        return await put_physical_target(session, user.id, value)
    except AccountDenied:
        raise HTTPException(403, "Account access denied") from None
    except ObjectiveChanged:
        raise HTTPException(409, "The selected objective changed. Reload and try again.") from None
