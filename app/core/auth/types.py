from dataclasses import dataclass


@dataclass(frozen=True)
class VerifiedIdentity:
    issuer: str
    subject: str
    session_id: str


class InvalidCredentials(Exception):
    """The supplied credential is not an accepted user session."""


class AuthenticationUnavailable(Exception):
    """Authentication is unconfigured or its trusted key service is unavailable."""
