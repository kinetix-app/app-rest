"""Feed, workout posts, likes and comments; blob I/O stays outside database transactions."""

import asyncio
from collections.abc import Sequence
from decimal import Decimal
from typing import Literal
from uuid import uuid4

import sqlalchemy as sa
from azure.core.exceptions import ResourceNotFoundError
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.storage.azure import BlobStorage
from app.features.accounts.models import Profile, User
from app.features.posts.errors import (
    CommentNotFound,
    EmptyPost,
    MediaMissing,
    MediaStorageUnavailable,
    PostActionForbidden,
    PostNotFound,
    WorkoutAlreadyShared,
    WorkoutUnavailable,
)
from app.features.posts.media import (
    POSTS_PATH,
    STORAGE_ERRORS,
    blob_prefix,
    cleanup_media,
    normalize_post_image,
)
from app.features.posts.models import (
    FileType,
    PostType,
    PostVisibility,
    file,
    post,
    post_comment,
    post_like,
)
from app.features.posts.schemas import (
    CommentPage,
    CommentResponse,
    LikeResponse,
    PostAuthor,
    PostMedia,
    PostPage,
    PostResponse,
    WorkoutDetail,
    WorkoutExercise,
    WorkoutSet,
    WorkoutSummary,
    WorkoutTemplate,
    WorkoutTemplateExercise,
)
from app.features.social.service import friend_ids_query
from app.features.training.models import (
    exercise,
    exercise_set,
    session_exercise,
    training_session,
)
from app.features.training.schemas import ExerciseResponse
from app.features.training.service import selectable_exercise
from app.features.training.units import display_weight

users = User.__table__
profiles = Profile.__table__
FeedScope = Literal["everyone", "friends"]


def _visible_posts(user_id: int) -> sa.Select:
    """Own posts of any visibility, plus active authors' PUBLIC posts and their FRIENDS
    posts when the caller is an accepted friend."""
    return (
        sa.select(post)
        .select_from(post.join(users, users.c.id == post.c.user_id))
        .where(
            sa.or_(
                post.c.user_id == user_id,
                sa.and_(
                    users.c.status == "active",
                    sa.or_(
                        post.c.visibility == PostVisibility.PUBLIC,
                        sa.and_(
                            post.c.visibility == PostVisibility.FRIENDS,
                            post.c.user_id.in_(friend_ids_query(user_id)),
                        ),
                    ),
                ),
            )
        )
    )


async def _visible_owner(
    session: AsyncSession, user_id: int, post_id: int, *, lock: str | None = None
) -> int:
    """Return the post owner, locking the post row so concurrent deletion serializes."""
    query = _visible_posts(user_id).with_only_columns(post.c.user_id).where(post.c.id == post_id)
    if lock == "share":
        query = query.with_for_update(read=True, of=post)
    elif lock == "update":
        query = query.with_for_update(of=post)
    owner = await session.scalar(query)
    if owner is None:
        raise PostNotFound
    return owner


async def _authors(session: AsyncSession, ids: set[int]) -> dict[int, PostAuthor]:
    rows = {
        row.user_id: row
        for row in (
            await session.execute(
                sa.select(
                    profiles.c.user_id, profiles.c.display_name, profiles.c.picture_blob_name
                ).where(profiles.c.user_id.in_(ids))
            )
        ).all()
    }
    return {
        value: PostAuthor(
            id=value,
            display_name=rows[value].display_name if value in rows else None,
            has_picture=value in rows and rows[value].picture_blob_name is not None,
        )
        for value in ids
    }


async def _workouts(session: AsyncSession, ids: set[int]) -> dict[int, WorkoutSummary]:
    if not ids:
        return {}
    names: dict[int, list[str]] = {}
    for row in (
        await session.execute(
            sa.select(session_exercise.c.session_id, exercise.c.name)
            .join(exercise, exercise.c.id == session_exercise.c.exercise_id)
            .where(session_exercise.c.session_id.in_(ids))
            .order_by(
                session_exercise.c.session_id,
                session_exercise.c.exercise_order,
                session_exercise.c.id,
            )
        )
    ).all():
        names.setdefault(row.session_id, []).append(row.name)
    totals = {
        row.session_id: row
        for row in (
            await session.execute(
                sa.select(
                    session_exercise.c.session_id,
                    sa.func.count(exercise_set.c.id).label("set_count"),
                    sa.func.coalesce(sa.func.sum(exercise_set.c.reps), 0).label("total_reps"),
                    sa.func.coalesce(
                        sa.func.sum(exercise_set.c.reps * exercise_set.c.weight_kg), 0
                    ).label("volume"),
                )
                .join(exercise_set, exercise_set.c.session_exercise_id == session_exercise.c.id)
                .where(session_exercise.c.session_id.in_(ids))
                .group_by(session_exercise.c.session_id)
            )
        ).all()
    }
    result = {}
    for row in (
        await session.execute(
            sa.select(training_session).where(
                training_session.c.id.in_(ids), training_session.c.ended_at.is_not(None)
            )
        )
    ).mappings():
        total = totals.get(row["id"])
        result[row["id"]] = WorkoutSummary(
            session_id=row["id"],
            title=row["title"],
            activity_type=row["activity_type"],
            started_at=row["started_at"],
            ended_at=row["ended_at"],
            duration_seconds=max(0, int((row["ended_at"] - row["started_at"]).total_seconds())),
            exercise_count=len(names.get(row["id"], [])),
            set_count=total.set_count if total else 0,
            total_reps=int(total.total_reps) if total else 0,
            total_volume_kg=display_weight(Decimal(total.volume if total else 0), "kg"),
            exercises=names.get(row["id"], []),
        )
    return result


async def _hydrate(session: AsyncSession, user_id: int, rows: Sequence) -> list[PostResponse]:
    if not rows:
        return []
    post_ids = [row["id"] for row in rows]
    authors = await _authors(session, {row["user_id"] for row in rows})
    workouts = await _workouts(
        session, {row["training_session_id"] for row in rows if row["training_session_id"]}
    )
    media: dict[int, list[PostMedia]] = {}
    for row in (
        await session.execute(
            sa.select(file.c.id, file.c.post_id, file.c.type, file.c.order)
            .where(file.c.post_id.in_(post_ids))
            .order_by(file.c.post_id, file.c.order, file.c.id)
        )
    ).all():
        media.setdefault(row.post_id, []).append(
            PostMedia(
                id=row.id,
                type=row.type,
                order=row.order,
                url=f"{POSTS_PATH}/{row.post_id}/media/{row.id}",
            )
        )
    likes = dict(
        (
            await session.execute(
                sa.select(post_like.c.post_id, sa.func.count())
                .where(post_like.c.post_id.in_(post_ids))
                .group_by(post_like.c.post_id)
            )
        ).all()
    )
    comments = dict(
        (
            await session.execute(
                sa.select(post_comment.c.post_id, sa.func.count())
                .where(post_comment.c.post_id.in_(post_ids))
                .group_by(post_comment.c.post_id)
            )
        ).all()
    )
    liked = set(
        await session.scalars(
            sa.select(post_like.c.post_id).where(
                post_like.c.post_id.in_(post_ids), post_like.c.user_id == user_id
            )
        )
    )
    return [
        PostResponse(
            id=row["id"],
            caption=row["caption"],
            description=row["text"],
            text=row["text"],
            visibility=row["visibility"],
            type=row["type"],
            created_at=row["created_at"],
            author=authors[row["user_id"]],
            workout=workouts.get(row["training_session_id"]),
            media=media.get(row["id"], []),
            like_count=likes.get(row["id"], 0),
            comment_count=comments.get(row["id"], 0),
            liked_by_me=row["id"] in liked,
            is_mine=row["user_id"] == user_id,
        )
        for row in rows
    ]


async def list_feed(
    session: AsyncSession,
    user_id: int,
    limit: int,
    before_id: int | None,
    scope: FeedScope = "everyone",
) -> PostPage:
    query = _visible_posts(user_id).order_by(post.c.id.desc()).limit(limit + 1)
    if scope == "friends":
        # The caller's own posts stay in the friends feed alongside friends' posts.
        query = query.where(
            sa.or_(post.c.user_id == user_id, post.c.user_id.in_(friend_ids_query(user_id)))
        )
    if before_id is not None:
        query = query.where(post.c.id < before_id)
    rows = (await session.execute(query)).mappings().all()
    page = rows[:limit]
    return PostPage(
        items=await _hydrate(session, user_id, page),
        next_before_id=page[-1]["id"] if len(rows) > limit else None,
    )


async def get_post(session: AsyncSession, user_id: int, post_id: int) -> PostResponse:
    row = (
        (await session.execute(_visible_posts(user_id).where(post.c.id == post_id)))
        .mappings()
        .first()
    )
    if row is None:
        raise PostNotFound
    return (await _hydrate(session, user_id, [row]))[0]


async def get_post_workout(session: AsyncSession, user_id: int, post_id: int) -> WorkoutDetail:
    """Exercises and sets of the workout a visible post shares; 404 for free posts."""
    session_id = await session.scalar(
        _visible_posts(user_id)
        .with_only_columns(post.c.training_session_id)
        .where(post.c.id == post_id)
    )
    summary = (await _workouts(session, {session_id})).get(session_id) if session_id else None
    if summary is None:
        raise PostNotFound
    exercises: dict[int, WorkoutExercise] = {}
    rows = await session.execute(
        sa.select(
            session_exercise.c.id,
            exercise.c.id.label("exercise_id"),
            exercise.c.name,
            sa.case((selectable_exercise(user_id), exercise.c.image_url)).label("image_url"),
            exercise_set.c.set_number,
            exercise_set.c.reps,
            exercise_set.c.weight_kg,
            exercise_set.c.duration_seconds,
            exercise_set.c.distance_km,
        )
        .join(exercise, exercise.c.id == session_exercise.c.exercise_id)
        .outerjoin(exercise_set, exercise_set.c.session_exercise_id == session_exercise.c.id)
        .where(session_exercise.c.session_id == session_id)
        .order_by(
            session_exercise.c.exercise_order,
            session_exercise.c.id,
            exercise_set.c.set_number,
            exercise_set.c.id,
        )
    )
    for row in rows:
        item = exercises.setdefault(
            row.id,
            WorkoutExercise(
                exercise_id=row.exercise_id, name=row.name, image_url=row.image_url, sets=[]
            ),
        )
        if row.set_number is not None:
            item.sets.append(
                WorkoutSet(
                    set_number=row.set_number,
                    reps=row.reps,
                    weight_kg=None
                    if row.weight_kg is None
                    else display_weight(row.weight_kg, "kg"),
                    duration_seconds=row.duration_seconds,
                    distance_km=row.distance_km,
                )
            )
    return WorkoutDetail(**summary.model_dump(), detailed_exercises=list(exercises.values()))


async def get_workout_template(
    session: AsyncSession, user_id: int, post_id: int
) -> WorkoutTemplate:
    workout = await get_post_workout(session, user_id, post_id)
    ids = {item.exercise_id for item in workout.detailed_exercises}
    rows = await session.execute(
        sa.select(exercise).where(exercise.c.id.in_(ids), selectable_exercise(user_id))
    )
    selectable = {row["id"]: ExerciseResponse.model_validate(row) for row in rows.mappings()}
    exercises = []
    skipped = []
    for item in workout.detailed_exercises:
        if item.exercise_id in selectable:
            exercises.append(
                WorkoutTemplateExercise(exercise=selectable[item.exercise_id], sets=item.sets)
            )
        else:
            skipped.append(item.name)
    return WorkoutTemplate(title=workout.title, exercises=exercises, skipped_exercises=skipped)


async def _require_shareable(
    session: AsyncSession, user_id: int, training_session_id: int, *, lock: bool
) -> None:
    query = sa.select(training_session.c.id).where(
        training_session.c.id == training_session_id,
        training_session.c.user_id == user_id,
        training_session.c.ended_at.is_not(None),
    )
    if lock:
        # Serializes concurrent shares of the same workout; the UNIQUE column is the backstop.
        query = query.with_for_update()
    if await session.scalar(query) is None:
        raise WorkoutUnavailable
    if await session.scalar(
        sa.select(post.c.id).where(post.c.training_session_id == training_session_id)
    ):
        raise WorkoutAlreadyShared


async def create_post(
    session: AsyncSession,
    user_id: int,
    storage: BlobStorage | None,
    *,
    caption: str,
    description: str,
    training_session_id: int | None,
    visibility: PostVisibility,
    images: Sequence[tuple[bytes, str | None]],
) -> PostResponse:
    if training_session_id is None and not (caption or description or images):
        raise EmptyPost
    normalized = [await asyncio.to_thread(normalize_post_image, *image) for image in images]
    if normalized and storage is None:
        raise MediaStorageUnavailable
    if training_session_id is not None:
        # Fail fast before uploading; the insert transaction re-checks under a row lock.
        try:
            await _require_shareable(session, user_id, training_session_id, lock=False)
            await session.commit()
        except BaseException:
            await session.rollback()
            raise
    names: list[str] = []
    if normalized:
        assert storage is not None
        try:
            for data in normalized:
                names.append(f"{blob_prefix(user_id)}{uuid4().hex}.jpg")
                await storage.upload_post_media(names[-1], data)
        except STORAGE_ERRORS:
            await cleanup_media(storage, names, user_id)
            raise MediaStorageUnavailable from None
    try:
        if training_session_id is not None:
            await _require_shareable(session, user_id, training_session_id, lock=True)
        post_id = await session.scalar(
            post.insert()
            .values(
                caption=caption,
                text=description,
                user_id=user_id,
                visibility=visibility,
                type=PostType.GENERAL if training_session_id is None else PostType.SESSION,
                training_session_id=training_session_id,
            )
            .returning(post.c.id)
        )
        if names:
            assert storage is not None
            await session.execute(
                file.insert(),
                [
                    {
                        "post_id": post_id,
                        "order": position,
                        "type": FileType.IMAGE,
                        "url": storage.post_media_blob_url(name),
                        "file_name": name,
                        "file_size": len(data),
                    }
                    for position, (name, data) in enumerate(zip(names, normalized, strict=True), 1)
                ],
            )
        result = await get_post(session, user_id, post_id)
        await session.commit()
        return result
    except IntegrityError:
        await session.rollback()
        await cleanup_media(storage, names, user_id)
        raise WorkoutAlreadyShared from None
    except BaseException:
        await session.rollback()
        await cleanup_media(storage, names, user_id)
        raise


async def delete_post(
    session: AsyncSession, user_id: int, post_id: int, storage: BlobStorage | None
) -> None:
    try:
        if await _visible_owner(session, user_id, post_id, lock="update") != user_id:
            raise PostActionForbidden
        names = list(
            await session.scalars(
                sa.delete(file).where(file.c.post_id == post_id).returning(file.c.file_name)
            )
        )
        await session.execute(sa.delete(post_like).where(post_like.c.post_id == post_id))
        await session.execute(sa.delete(post_comment).where(post_comment.c.post_id == post_id))
        await session.execute(sa.delete(post).where(post.c.id == post_id))
        await session.commit()
    except BaseException:
        await session.rollback()
        raise
    await cleanup_media(storage, names, user_id)


async def set_like(session: AsyncSession, user_id: int, post_id: int, liked: bool) -> LikeResponse:
    try:
        await _visible_owner(session, user_id, post_id, lock="share")
        if liked:
            await session.execute(
                insert(post_like).values(post_id=post_id, user_id=user_id).on_conflict_do_nothing()
            )
        else:
            await session.execute(
                sa.delete(post_like).where(
                    post_like.c.post_id == post_id, post_like.c.user_id == user_id
                )
            )
        count = await session.scalar(
            sa.select(sa.func.count()).select_from(post_like).where(post_like.c.post_id == post_id)
        )
        await session.commit()
    except BaseException:
        await session.rollback()
        raise
    return LikeResponse(liked=liked, like_count=count or 0)


def _comment_query() -> sa.Select:
    return sa.select(
        post_comment, profiles.c.display_name, profiles.c.picture_blob_name
    ).select_from(post_comment.outerjoin(profiles, profiles.c.user_id == post_comment.c.user_id))


def _comment_response(row, user_id: int) -> CommentResponse:
    return CommentResponse(
        id=row["id"],
        post_id=row["post_id"],
        author=PostAuthor(
            id=row["user_id"],
            display_name=row["display_name"],
            has_picture=row["picture_blob_name"] is not None,
        ),
        comment=row["comment"],
        created_at=row["created_at"],
        is_mine=row["user_id"] == user_id,
    )


async def list_comments(
    session: AsyncSession, user_id: int, post_id: int, limit: int, after_id: int | None
) -> CommentPage:
    await _visible_owner(session, user_id, post_id)
    query = (
        _comment_query()
        .where(post_comment.c.post_id == post_id)
        .order_by(post_comment.c.id)
        .limit(limit + 1)
    )
    if after_id is not None:
        query = query.where(post_comment.c.id > after_id)
    rows = (await session.execute(query)).mappings().all()
    page = rows[:limit]
    return CommentPage(
        items=[_comment_response(row, user_id) for row in page],
        next_after_id=page[-1]["id"] if len(rows) > limit else None,
    )


async def create_comment(
    session: AsyncSession, user_id: int, post_id: int, text: str
) -> CommentResponse:
    try:
        await _visible_owner(session, user_id, post_id, lock="share")
        comment_id = await session.scalar(
            post_comment.insert()
            .values(post_id=post_id, user_id=user_id, comment=text)
            .returning(post_comment.c.id)
        )
        row = (
            (await session.execute(_comment_query().where(post_comment.c.id == comment_id)))
            .mappings()
            .one()
        )
        await session.commit()
    except BaseException:
        await session.rollback()
        raise
    return _comment_response(row, user_id)


async def delete_comment(
    session: AsyncSession, user_id: int, post_id: int, comment_id: int
) -> None:
    try:
        owner = await _visible_owner(session, user_id, post_id, lock="share")
        author = await session.scalar(
            sa.select(post_comment.c.user_id).where(
                post_comment.c.id == comment_id, post_comment.c.post_id == post_id
            )
        )
        if author is None:
            raise CommentNotFound
        # Comment authors and the post owner may remove a comment.
        if user_id not in (author, owner):
            raise PostActionForbidden
        await session.execute(sa.delete(post_comment).where(post_comment.c.id == comment_id))
        await session.commit()
    except BaseException:
        await session.rollback()
        raise


async def read_media(
    session: AsyncSession, user_id: int, post_id: int, file_id: int, storage: BlobStorage | None
) -> bytes:
    try:
        await _visible_owner(session, user_id, post_id)
        name = await session.scalar(
            sa.select(file.c.file_name).where(file.c.id == file_id, file.c.post_id == post_id)
        )
        await session.commit()
    except BaseException:
        await session.rollback()
        raise
    if name is None:
        raise MediaMissing
    if storage is None:
        raise MediaStorageUnavailable
    try:
        return await storage.read_post_media(name)
    except ResourceNotFoundError:
        raise MediaMissing from None
    except STORAGE_ERRORS:
        raise MediaStorageUnavailable from None
