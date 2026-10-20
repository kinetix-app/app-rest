from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.types import VerifiedIdentity
from app.features.accounts.models import AuthAccount, Profile, User
from app.features.accounts.schemas import AccountResponse, ProfilePatch, ProfileResponse


class AccountDenied(Exception):
    """An existing account is blocked or deleted."""


def require_active(user: User) -> None:
    if user.status != "active":
        raise AccountDenied


async def _find_identity(session: AsyncSession, identity: VerifiedIdentity) -> User | None:
    return await session.scalar(
        select(User)
        .join(AuthAccount, AuthAccount.user_id == User.id)
        .where(AuthAccount.issuer == identity.issuer, AuthAccount.subject == identity.subject)
        .with_for_update(of=User)
    )


async def resolve_user(session: AsyncSession, identity: VerifiedIdentity) -> User:
    # PostgreSQL READ COMMITTED: after a uniqueness conflict the next SELECT sees the winner.
    try:
        user = await _find_identity(session, identity)
        if user is None:
            try:
                async with session.begin_nested():
                    user = User(id=uuid4(), status="active")
                    session.add(user)
                    await session.flush()
                    session.add_all(
                        [
                            AuthAccount(
                                user_id=user.id, issuer=identity.issuer, subject=identity.subject
                            ),
                            Profile(user_id=user.id),
                        ]
                    )
                    await session.flush()
            except IntegrityError:
                # SAVEPOINT rolls back the provisional user/profile as well as its mapping.
                user = await _find_identity(session, identity)
                if user is None:
                    raise
        require_active(user)
        await session.commit()
        return user
    except Exception:
        await session.rollback()
        raise


async def read_account(session: AsyncSession, user_id: UUID) -> AccountResponse:
    user = await session.get(User, user_id, populate_existing=True)
    if user is None:
        raise AccountDenied
    require_active(user)
    profile = await session.get(Profile, user_id)
    if profile is None:
        raise RuntimeError("Account profile is missing")
    return AccountResponse(
        id=user.id,
        status=user.status,
        created_at=user.created_at,
        profile=ProfileResponse.model_validate(profile),
    )


async def update_profile(
    session: AsyncSession, user_id: UUID, changes: ProfilePatch
) -> AccountResponse:
    try:
        user = await session.scalar(select(User).where(User.id == user_id).with_for_update())
        if user is None:
            raise AccountDenied
        require_active(user)
        profile = await session.get(Profile, user_id)
        if profile is None:
            raise RuntimeError("Account profile is missing")
        for name, value in changes.model_dump(exclude_unset=True).items():
            setattr(profile, name, value)
        await session.flush()
        await session.refresh(profile)
        response = await read_account(session, user_id)
        await session.commit()
        return response
    except Exception:
        await session.rollback()
        raise
