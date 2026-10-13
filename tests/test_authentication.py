import time

import httpx
import jwt
import pytest
from asgi_lifespan import LifespanManager
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import ValidationError

from app.core.auth.clerk import ClerkVerifier
from app.core.auth.types import AuthenticationUnavailable, InvalidCredentials
from app.features.accounts.schemas import ProfilePatch
from app.main import create_app


@pytest.fixture
def auth_settings(settings):
    settings.clerk_issuer = "https://kinetix-test.clerk.accounts.dev"
    settings.clerk_authorized_parties = ["https://kinetix.example"]
    return settings


@pytest.mark.anyio
async def test_valid_native_token_and_key_cache(auth_settings, signing_material, signed_token):
    requests = []

    def jwks(request):
        requests.append(request)
        return httpx.Response(200, json={"keys": [signing_material[1]]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(jwks)) as client:
        verifier = ClerkVerifier(auth_settings, client)
        identity = await verifier.verify(signed_token())
        assert identity.subject == "user_alice"
        await verifier.verify(signed_token(azp="https://kinetix.example"))
        assert len(requests) == 1
        assert str(requests[0].url) == auth_settings.clerk_issuer + "/.well-known/jwks.json"
        unknown = jwt.encode({}, signing_material[0], algorithm="RS256", headers={"kid": "unknown"})
        for _ in range(3):
            with pytest.raises(InvalidCredentials):
                await verifier.verify(unknown)
        assert len(requests) == 1


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
async def test_invalid_claims_rejected(auth_settings, signing_material, signed_token, overrides):
    transport = httpx.MockTransport(
        lambda _: httpx.Response(200, json={"keys": [signing_material[1]]})
    )
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(InvalidCredentials):
            await ClerkVerifier(auth_settings, client).verify(signed_token(**overrides))


@pytest.mark.anyio
async def test_wrong_signature_and_algorithm_rejected(
    auth_settings, signing_material, signed_token
):
    transport = httpx.MockTransport(
        lambda _: httpx.Response(200, json={"keys": [signing_material[1]]})
    )
    claims = jwt.decode(signed_token(), options={"verify_signature": False})
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    tokens = [
        jwt.encode(claims, other_key, algorithm="RS256", headers={"kid": "test-key"}),
        jwt.encode(claims, "wrong-secret" * 4, algorithm="HS256", headers={"kid": "test-key"}),
        "not-a-jwt",
        "ak_machine",
        "x" * 16385,
    ]
    async with httpx.AsyncClient(transport=transport) as client:
        verifier = ClerkVerifier(auth_settings, client)
        for token in tokens:
            with pytest.raises(InvalidCredentials):
                await verifier.verify(token)


@pytest.mark.anyio
async def test_key_rotation_and_expired_cache_fail_closed(
    auth_settings, signing_material, signed_token
):
    responses = [
        {"keys": [dict(signing_material[1])]},
        {"keys": [dict(signing_material[1], kid="rotated")]},
    ]

    def jwks(_):
        return httpx.Response(200, json=responses.pop(0))

    async with httpx.AsyncClient(transport=httpx.MockTransport(jwks)) as client:
        verifier = ClerkVerifier(auth_settings, client)
        await verifier.verify(signed_token())
        verifier._last_attempt = None
        claims = jwt.decode(signed_token(), options={"verify_signature": False})
        rotated = jwt.encode(
            claims, signing_material[0], algorithm="RS256", headers={"kid": "rotated"}
        )
        await verifier.verify(rotated)
        verifier._expires_at = 0
        with pytest.raises(AuthenticationUnavailable):
            await verifier.verify(rotated)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "response",
    [httpx.Response(503), httpx.Response(200, json={}), httpx.Response(200, json={"keys": []})],
)
async def test_jwks_failure_denies_authentication(auth_settings, signed_token, response):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: response)) as client:
        with pytest.raises(AuthenticationUnavailable):
            await ClerkVerifier(auth_settings, client).verify(signed_token())


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
