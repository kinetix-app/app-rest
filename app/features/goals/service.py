from sqlalchemy.ext.asyncio import AsyncSession

from app.features.accounts.models import User
from app.features.accounts.service import AccountDenied, lock_active_user, require_active
from app.features.goals.models import AccountObjective
from app.features.goals.schemas import ObjectivePut, ObjectiveResponse


async def read_objective(session: AsyncSession, user_id: int) -> ObjectiveResponse:
    user = await session.get(User, user_id, populate_existing=True)
    if user is None:
        raise AccountDenied
    require_active(user)
    selected = await session.get(AccountObjective, user_id)
    return ObjectiveResponse(objective=selected.objective if selected else None)


async def set_objective(
    session: AsyncSession, user_id: int, value: ObjectivePut
) -> ObjectiveResponse:
    try:
        await lock_active_user(session, user_id)
        selected = await session.get(AccountObjective, user_id)
        if selected is None:
            session.add(AccountObjective(user_id=user_id, objective=value.objective))
        else:
            selected.objective = value.objective
        await session.commit()
        return ObjectiveResponse(objective=value.objective)
    except Exception:
        await session.rollback()
        raise
