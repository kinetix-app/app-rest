"""Expected post use-case failures, independent of HTTP transport."""


class PostError(Exception):
    """Base class for expected post failures."""


class PostNotFound(PostError):
    """Missing post, or a post the account is not allowed to see."""


class CommentNotFound(PostError):
    """Missing comment on a visible post."""


class PostActionForbidden(PostError):
    """The account can see the resource but may not change it."""


class EmptyPost(PostError):
    """A post without a workout, caption or photo."""


class WorkoutUnavailable(PostError):
    """The workout is missing, unfinished or owned by another account."""


class WorkoutAlreadyShared(PostError):
    """The completed workout already has a post."""


class MediaMissing(PostError):
    """The requested post image does not exist."""


class MediaStorageUnavailable(PostError):
    """Post image storage is not configured or failed."""
