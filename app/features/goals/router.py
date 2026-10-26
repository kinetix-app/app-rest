from fastapi import APIRouter, HTTPException

from app.core.auth.dependencies import CurrentUser
from app.db.session import DatabaseSession
from app.features.accounts.service import AccountDenied
from app.features.goals.schemas import ObjectivePut, ObjectiveResponse
from app.features.goals.service import read_objective, set_objective

router = APIRouter(prefix="/me/objective", tags=["goals"])


@router.get("", responses={403: {"description": "Account access denied"}})
async def get_objective(user: CurrentUser, session: DatabaseSession) -> ObjectiveResponse:
    try:
        return await read_objective(session, user.id)
    except AccountDenied:
        raise HTTPException(403, "Account access denied") from None


@router.put("", responses={403: {"description": "Account access denied"}})
async def put_objective(
    value: ObjectivePut, user: CurrentUser, session: DatabaseSession
) -> ObjectiveResponse:
    try:
        return await set_objective(session, user.id, value)
    except AccountDenied:
        raise HTTPException(403, "Account access denied") from None
