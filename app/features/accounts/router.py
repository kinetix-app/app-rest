from fastapi import APIRouter, HTTPException

from app.core.auth.dependencies import CurrentUser
from app.db.session import DatabaseSession
from app.features.accounts.schemas import AccountResponse, ProfilePatch
from app.features.accounts.service import AccountDenied, read_account, update_profile

auth_router = APIRouter(prefix="/auth", tags=["accounts"])

router = APIRouter(prefix="/me", tags=["accounts"])


@auth_router.get("/me", responses={403: {"description": "Account access denied"}})
@router.get("", responses={403: {"description": "Account access denied"}})
async def get_me(user: CurrentUser, session: DatabaseSession) -> AccountResponse:
    try:
        return await read_account(session, user.id)
    except AccountDenied:
        raise HTTPException(403, "Account access denied") from None


@router.patch("/profile", responses={403: {"description": "Account access denied"}})
async def patch_profile(
    changes: ProfilePatch, user: CurrentUser, session: DatabaseSession
) -> AccountResponse:
    try:
        return await update_profile(session, user.id, changes)
    except AccountDenied:
        raise HTTPException(403, "Account access denied") from None
