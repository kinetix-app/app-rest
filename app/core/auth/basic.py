"""Local development credentials; never enabled in production."""

from base64 import b64decode
from secrets import compare_digest

from app.core.auth.types import InvalidCredentials, VerifiedIdentity
from app.core.config import Settings


def verify_basic(authorization: str, settings: Settings) -> VerifiedIdentity:
    scheme, _, encoded = authorization.partition(" ")
    if settings.auth_mode != "basic" or settings.app_env == "production":
        raise InvalidCredentials
    if scheme.lower() != "basic" or not encoded:
        raise InvalidCredentials
    try:
        username, separator, password = (
            b64decode(encoded, validate=True).decode("utf-8").partition(":")
        )
    except ValueError as error:
        raise InvalidCredentials from error
    configured = settings.basic_auth_users.get(username)
    expected = configured.get_secret_value() if configured is not None else ""
    valid = compare_digest(password.encode("utf-8"), expected.encode("utf-8"))
    if not separator or configured is None or not valid:
        raise InvalidCredentials
    return VerifiedIdentity("urn:kinetix:dev", username, None)
