"""Expected friendship failures, independent of HTTP transport."""


class SocialError(Exception):
    """Base class for expected friendship failures."""


class PersonNotFound(SocialError):
    """Missing, inactive or not yet set up account."""


class SelfFriendship(SocialError):
    """An account cannot befriend itself."""


class RequestNotFound(SocialError):
    """No incoming friend request from that account."""
