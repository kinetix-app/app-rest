import json
import time

import httpx
import jwt
import pytest
from asgi_lifespan import LifespanManager
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import SecretStr, ValidationError

from app.core.auth.clerk import ClerkVerifier
from app.core.auth.types import AuthenticationUnavailable, InvalidCredentials
from app.features.accounts.schemas import ProfilePatch
from app.main import create_app


@pytest.fixture
def auth_settings(settings):
    settings.clerk_secret_key = SecretStr("sk_test_backend_only")
    settings.clerk_issuer = "https://kinetix-test.clerk.accounts.dev"
    settings.clerk_authorized_parties = ["https://kinetix.example"]
    return settings


@pytest.mark.anyio
async def test_valid_native_token_and_sdk_key_cache(auth_settings, clerk_jwks, signed_token):
    verifier = ClerkVerifier(auth_settings)
    identity = await verifier.verify(signed_token())
    assert identity.issuer == auth_settings.clerk_issuer
    assert identity.subject == "user_alice"
    assert identity.session_id == "sess_alice"
    await verifier.verify(signed_token(azp="https://kinetix.example"))
    assert len(clerk_jwks.requests) == 1
    request = clerk_jwks.requests[0]
    assert str(request.url) == "https://api.clerk.com/v1/jwks"
    assert request.headers["Authorization"] == "Bearer sk_test_backend_only"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "overrides",
    [
        {"iss": "https://attacker.example"},
        {"exp": 1},
        {"nbf": int(time.time()) + 600},
        {"iat": int(time.time()) + 600},
        {"exp": None},
        {"nbf": None},
        {"iat": None},
        {"sid": None},
        {"sub": None},
        {"azp": "https://attacker.example"},
        {"sts": "pending"},
        {"sub": "machine_alice"},
        {"sid": ""},
        {"exp": "9999999999"},
    ],
)
async def test_invalid_claims_rejected(auth_settings, clerk_jwks, signed_token, overrides):
    verifier = ClerkVerifier(auth_settings)
    token = signed_token(**overrides)
    with pytest.raises(InvalidCredentials):
        await verifier.verify(token)


@pytest.mark.anyio
async def test_wrong_signature_and_algorithm_rejected(
    auth_settings, signing_material, signed_token, clerk_jwks
):
    claims = jwt.decode(signed_token(), options={"verify_signature": False})
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    tokens = [
        jwt.encode(claims, other_key, algorithm="RS256", headers={"kid": "test-key"}),
        jwt.encode(claims, "wrong-secret" * 4, algorithm="HS256", headers={"kid": "test-key"}),
        "not-a-jwt",
        "ak_machine",
        "ak_machine.jwt.token",
        "m2m_machine.jwt.token",
        "mt_machine.jwt.token",
        "oat_machine.jwt.token",
        "x" * 16385,
    ]
    verifier = ClerkVerifier(auth_settings)
    for token in tokens:
        with pytest.raises(InvalidCredentials):
            await verifier.verify(token)


@pytest.mark.anyio
async def test_sdk_refreshes_rotated_key(auth_settings, signed_token, clerk_jwks):
    verifier = ClerkVerifier(auth_settings)
    await verifier.verify(signed_token())
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    key = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    # Rotation can replace the key material even while the key ID is cached.
    key.update(kid="test-key", alg="RS256", use="sig")
    clerk_jwks.response = httpx.Response(200, json={"keys": [key]})
    claims = jwt.decode(signed_token(), options={"verify_signature": False})
    rotated = jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": "test-key"})
    await verifier.verify(rotated)
    assert len(clerk_jwks.requests) == 2


@pytest.mark.anyio
@pytest.mark.parametrize(
    "response",
    [httpx.Response(503), httpx.Response(200, json={}), httpx.Response(200, content="invalid")],
)
async def test_jwks_failure_denies_authentication(
    auth_settings, signed_token, clerk_jwks, response
):
    clerk_jwks.response = response
    token = signed_token()
    verifier = ClerkVerifier(auth_settings)
    with pytest.raises(AuthenticationUnavailable):
        await verifier.verify(token)


@pytest.mark.anyio
async def test_unknown_key_rejected(auth_settings, signed_token, clerk_jwks):
    clerk_jwks.response = httpx.Response(200, json={"keys": []})
    token = signed_token()
    verifier = ClerkVerifier(auth_settings)
    with pytest.raises(InvalidCredentials):
        await verifier.verify(token)


@pytest.mark.anyio
async def test_audience_enforced(auth_settings, signed_token, clerk_jwks):
    auth_settings.clerk_audience = "kinetix-api"
    verifier = ClerkVerifier(auth_settings)
    await verifier.verify(signed_token(aud="kinetix-api"))
    for audience in (None, "other-api"):
        token = signed_token(aud=audience)
        with pytest.raises(InvalidCredentials):
            await verifier.verify(token)


@pytest.mark.anyio
async def test_missing_and_unconfigured_auth_does_not_access_database(settings):
    app = create_app(settings)  # Deliberately unreachable database.
    async with LifespanManager(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            for headers in [{}, {"Authorization": "Basic abc"}, {"Cookie": "__session=abc"}]:
                response = await client.get("/api/v1/me", headers=headers)
                assert response.status_code == 401
                assert response.headers["WWW-Authenticate"] == "Bearer"
            response = await client.get("/api/v1/me", headers={"Authorization": "Bearer abc"})
            assert response.status_code == 503
            assert "abc" not in response.text


@pytest.mark.parametrize(
    "changes",
    [
        {"display_name": " "},
        {"timezone": "Mars/Nowhere"},
        {"timezone": "../etc/passwd"},
        {"user_id": "other"},
    ],
)
def test_profile_validation(changes):
    with pytest.raises(ValidationError):
        ProfilePatch(**changes)


def test_profile_patch_omission_and_null_are_distinct():
    assert ProfilePatch().model_dump(exclude_unset=True) == {}
    assert ProfilePatch(display_name=None).model_dump(exclude_unset=True) == {"display_name": None}


@pytest.mark.anyio
@pytest.mark.parametrize("claim", ["exp", "nbf", "iat"])
async def test_invalid_time_claim_type_rejected(auth_settings, clerk_jwks, signed_token, claim):
    token = signed_token(**{claim: {"invalid": 1}})
    verifier = ClerkVerifier(auth_settings)
    with pytest.raises(InvalidCredentials):
        await verifier.verify(token)


@pytest.mark.anyio
@pytest.mark.parametrize("status", [401, 503])
async def test_authentication_failure_does_not_access_database(
    auth_settings, clerk_jwks, signed_token, status
):
    if status == 503:
        clerk_jwks.response = httpx.Response(503)
    token = signed_token(iss="https://attacker.example")
    app = create_app(auth_settings)  # Deliberately unreachable database.
    async with LifespanManager(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
            assert response.status_code == status
            assert token not in response.text


@pytest.mark.anyio
async def test_missing_secret_key_denies_authentication(auth_settings, signed_token):
    auth_settings.clerk_secret_key = None
    token = signed_token()
    verifier = ClerkVerifier(auth_settings)
    with pytest.raises(AuthenticationUnavailable):
        await verifier.verify(token)


@pytest.mark.anyio
@pytest.mark.parametrize("error", [httpx.ConnectError("unavailable"), httpx.ReadTimeout("timeout")])
async def test_sdk_network_failure_denies_authentication(
    auth_settings, clerk_jwks, signed_token, error
):
    clerk_jwks.error = error
    token = signed_token()
    verifier = ClerkVerifier(auth_settings)
    with pytest.raises(AuthenticationUnavailable):
        await verifier.verify(token)
