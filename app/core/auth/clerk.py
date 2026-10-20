import httpx
import jwt
from clerk_backend_api.security import (
    TokenVerificationError,
    VerifyTokenOptions,
    verify_token_async,
)
from clerk_backend_api.security.machine import get_token_type
from clerk_backend_api.security.types import TokenType, TokenVerificationErrorReason
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.auth.types import AuthenticationUnavailable, InvalidCredentials, VerifiedIdentity
from app.core.config import Settings


class SessionClaims(BaseModel):
    model_config = ConfigDict(strict=True)

    iss: str
    sub: str = Field(min_length=1, max_length=255)
    sid: str = Field(min_length=1, max_length=255)
    exp: int
    nbf: int
    iat: int
    azp: str | None = None
    sts: str | None = None


class ClerkVerifier:
    """Verify Clerk tokens with the SDK, then validate the application's session contract."""

    def __init__(self, settings: Settings):
        self.settings = settings

    async def verify(self, token: str) -> VerifiedIdentity:
        if not self.settings.clerk_issuer or not self.settings.clerk_secret_key:
            raise AuthenticationUnavailable
        # Only session JWTs belong on user routes; never send machine credentials to Clerk.
        if (
            len(token) > 16384
            or token.count(".") != 2
            or get_token_type(token) != TokenType.SESSION_TOKEN
        ):
            raise InvalidCredentials
        try:
            payload = await verify_token_async(
                token,
                VerifyTokenOptions(
                    secret_key=self.settings.clerk_secret_key.get_secret_value(),
                    audience=self.settings.clerk_audience,
                    clock_skew_in_ms=self.settings.clerk_clock_skew_seconds * 1000,
                ),
            )
            # The SDK returns a dict. Its auth objects only map fields, without validation.
            # It checks supplied time claims but does not require them or verify the issuer.
            claims = SessionClaims.model_validate(payload)
        except TokenVerificationError as error:
            if error.reason in (
                TokenVerificationErrorReason.JWK_FAILED_TO_LOAD,
                TokenVerificationErrorReason.JWK_REMOTE_INVALID,
                TokenVerificationErrorReason.JWK_FAILED_TO_RESOLVE,
                TokenVerificationErrorReason.SERVER_ERROR,
            ):
                raise AuthenticationUnavailable from error
            raise InvalidCredentials from error
        except httpx.HTTPError as error:
            raise AuthenticationUnavailable from error
        except (jwt.InvalidTokenError, ValidationError, ValueError, TypeError) as error:
            raise InvalidCredentials from error
        if claims.iss != self.settings.clerk_issuer or claims.sts not in (None, "active"):
            raise InvalidCredentials
        if claims.azp is not None and claims.azp not in self.settings.clerk_authorized_parties:
            raise InvalidCredentials
        if not claims.sub.startswith("user_") or not claims.sid.startswith("sess_"):
            raise InvalidCredentials
        return VerifiedIdentity(claims.iss, claims.sub, claims.sid)
