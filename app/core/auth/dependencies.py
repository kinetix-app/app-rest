from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.auth.basic import verify_basic
from app.core.auth.types import AuthenticationUnavailable, InvalidCredentials, VerifiedIdentity
from app.db.session import DatabaseSession
from app.features.accounts.models import User
from app.features.accounts.service import AccountDenied, resolve_user

bearer = HTTPBearer(
    auto_error=False, scheme_name="Authentication", description="Clerk session token"
)


async def get_verified_identity(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> VerifiedIdentity:
    if request.app.state.settings.auth_mode == "basic":
        try:
            return verify_basic(
                request.headers.get("Authorization", ""), request.app.state.settings
            )
        except InvalidCredentials:
            raise HTTPException(
                401, "Invalid development credentials", headers={"WWW-Authenticate": "Basic"}
            ) from None
    if credentials is None:
        raise HTTPException(
            401, "Bearer session token required", headers={"WWW-Authenticate": "Bearer"}
        )
    try:
        return await request.app.state.clerk_verifier.verify(credentials.credentials)
    except InvalidCredentials:
        raise HTTPException(
            401, "Invalid or expired session token", headers={"WWW-Authenticate": "Bearer"}
        ) from None
    except AuthenticationUnavailable:
        raise HTTPException(
            503, "Authentication temporarily unavailable", headers={"Retry-After": "30"}
        ) from None


VerifiedSession = Annotated[VerifiedIdentity, Depends(get_verified_identity)]


async def get_current_user(identity: VerifiedSession, session: DatabaseSession) -> User:
    try:
        return await resolve_user(session, identity)
    except AccountDenied:
        raise HTTPException(403, "Account access denied") from None


CurrentUser = Annotated[User, Depends(get_current_user)]
