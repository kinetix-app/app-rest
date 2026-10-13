import asyncio
from time import monotonic

import httpx
import jwt
from clerk_backend_api.security import TokenVerificationError, VerifyTokenOptions, verify_token
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
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
    """Instance-scoped asynchronous key cache; SDK performs networkless RSA verification."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient):
        self.settings = settings
        self.client = client
        self._keys: dict[str, str] = {}
        self._expires_at = 0.0
        self._last_attempt: float | None = None
        self._lock = asyncio.Lock()

    async def _signing_key(self, kid: str) -> str:
        async with self._lock:
            now = monotonic()
            if now < self._expires_at and kid in self._keys:
                return self._keys[kid]
            if self._last_attempt is not None and now - self._last_attempt < 30:
                if now >= self._expires_at:
                    raise AuthenticationUnavailable
                raise InvalidCredentials
            self._last_attempt = now
            self._keys = await self._fetch_signing_keys()
            self._expires_at = monotonic() + self.settings.clerk_jwks_cache_seconds
            if kid not in self._keys:
                raise InvalidCredentials
            return self._keys[kid]

    async def _fetch_signing_keys(self) -> dict[str, str]:
        # URL comes exclusively from validated server configuration, never JWT claims.
        url = f"{self.settings.clerk_issuer}/.well-known/jwks.json"
        try:
            response = await self.client.get(url)
            response.raise_for_status()
            if len(response.content) > 65536:
                raise ValueError("Oversized JWKS")
            return self._parse_signing_keys(response.json()["keys"])
        except (httpx.HTTPError, jwt.PyJWTError, ValueError, KeyError, TypeError) as error:
            raise AuthenticationUnavailable from error

    @staticmethod
    def _parse_signing_keys(keys: object) -> dict[str, str]:
        if not isinstance(keys, list) or not 1 <= len(keys) <= 100:
            raise ValueError("Invalid JWKS")
        parsed: dict[str, str] = {}
        for item in keys:
            signing_key = ClerkVerifier._parse_signing_key(item)
            if signing_key is None:
                continue
            key_id, pem = signing_key
            if key_id in parsed:
                raise ValueError("Invalid key ID")
            parsed[key_id] = pem
        if not parsed:
            raise ValueError("No usable signing keys")
        return parsed

    @staticmethod
    def _parse_signing_key(item: object) -> tuple[str, str] | None:
        if not isinstance(item, dict):
            raise ValueError("Invalid JWK")
        if item.get("kty") != "RSA" or item.get("use", "sig") != "sig":
            return None
        if item.get("alg", "RS256") != "RS256":
            return None
        key_id = item.get("kid")
        if not isinstance(key_id, str) or not key_id:
            raise ValueError("Invalid key ID")
        public_key = jwt.algorithms.RSAAlgorithm.from_jwk(item)
        if not isinstance(public_key, RSAPublicKey):
            raise ValueError("Invalid RSA key")
        pem = public_key.public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode()
        return key_id, pem

    async def verify(self, token: str) -> VerifiedIdentity:
        if not self.settings.clerk_issuer:
            raise AuthenticationUnavailable
        if len(token) > 16384 or token.count(".") != 2:
            raise InvalidCredentials
        try:
            header = jwt.get_unverified_header(token)
        except jwt.InvalidTokenError as error:
            raise InvalidCredentials from error
        kid = header.get("kid")
        if header.get("alg") != "RS256" or not isinstance(kid, str) or not 1 <= len(kid) <= 255:
            raise InvalidCredentials
        key = await self._signing_key(kid)
        try:
            # SDK disables issuer validation and does not require time claims: enforce below.
            payload = verify_token(
                token,
                VerifyTokenOptions(
                    jwt_key=key,
                    audience=self.settings.clerk_audience,
                    clock_skew_in_ms=self.settings.clerk_clock_skew_seconds * 1000,
                ),
            )
            claims = SessionClaims.model_validate(payload)
        except (TokenVerificationError, jwt.InvalidTokenError, ValidationError) as error:
            raise InvalidCredentials from error
        if claims.iss != self.settings.clerk_issuer or claims.sts not in (None, "active"):
            raise InvalidCredentials
        if claims.azp is not None and claims.azp not in self.settings.clerk_authorized_parties:
            raise InvalidCredentials
        if not claims.sub.startswith("user_") or not claims.sid.startswith("sess_"):
            raise InvalidCredentials
        return VerifiedIdentity(claims.iss, claims.sub, claims.sid)
