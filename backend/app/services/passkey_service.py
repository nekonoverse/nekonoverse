import json
import uuid
from datetime import datetime, timezone

import webauthn
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from app.config import settings
from app.models.passkey import PasskeyCredential
from app.valkey_client import valkey

CHALLENGE_TTL = 300  # 5 minutes


# ── Registration flow ──────────────────────────────────────────────────────


async def generate_registration_options(user, session_id: str) -> dict:
    """Generate a registration challenge and store it in Valkey."""
    actor = user.actor

    existing = [
        PublicKeyCredentialDescriptor(id=cred.credential_id)
        for cred in user.passkey_credentials
    ]

    options = webauthn.generate_registration_options(
        rp_id=settings.domain,
        rp_name="Nekonoverse",
        user_id=str(user.id).encode(),
        user_name=actor.username,
        user_display_name=actor.display_name or actor.username,
        exclude_credentials=existing,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
    )

    challenge_b64 = bytes_to_base64url(options.challenge)
    await valkey.set(
        f"webauthn:reg:{session_id}",
        json.dumps({"challenge": challenge_b64, "user_id": str(user.id)}),
        ex=CHALLENGE_TTL,
    )

    raw = webauthn.options_to_json(options)
    return json.loads(raw) if isinstance(raw, str) else raw


async def verify_registration_response(
    db: AsyncSession,
    session_id: str,
    credential_json: dict,
    name: str | None = None,
) -> PasskeyCredential:
    """Verify the registration response and save the credential to the DB."""
    stored = await valkey.get(f"webauthn:reg:{session_id}")
    if not stored:
        raise ValueError("Challenge expired or not found")

    data = json.loads(stored)
    expected_challenge = base64url_to_bytes(data["challenge"])
    user_id = uuid.UUID(data["user_id"])

    await valkey.delete(f"webauthn:reg:{session_id}")

    from webauthn.helpers.structs import RegistrationCredential

    credential = RegistrationCredential.parse_raw(json.dumps(credential_json))

    verification = webauthn.verify_registration_response(
        credential=credential,
        expected_challenge=expected_challenge,
        expected_rp_id=settings.domain,
        expected_origin=settings.frontend_url,
    )

    passkey = PasskeyCredential(
        user_id=user_id,
        credential_id=verification.credential_id,
        public_key=verification.credential_public_key,
        sign_count=verification.sign_count,
        name=name,
        aaguid=str(verification.aaguid) if verification.aaguid else None,
    )
    db.add(passkey)
    await db.commit()
    await db.refresh(passkey)

    return passkey


# ── Authentication flow ────────────────────────────────────────────────────


async def generate_authentication_options(challenge_id: str) -> dict:
    """Generate an authentication challenge and store it in Valkey."""
    options = webauthn.generate_authentication_options(
        rp_id=settings.domain,
        user_verification=UserVerificationRequirement.PREFERRED,
    )

    challenge_b64 = bytes_to_base64url(options.challenge)
    await valkey.set(
        f"webauthn:auth:{challenge_id}",
        challenge_b64,
        ex=CHALLENGE_TTL,
    )

    raw = webauthn.options_to_json(options)
    return json.loads(raw) if isinstance(raw, str) else raw


async def verify_authentication_response(
    db: AsyncSession,
    challenge_id: str,
    credential_json: dict,
):
    """Verify the authentication response and return the authenticated User."""
    stored_challenge = await valkey.get(f"webauthn:auth:{challenge_id}")
    if not stored_challenge:
        raise ValueError("Challenge expired or not found")

    expected_challenge = base64url_to_bytes(stored_challenge)
    await valkey.delete(f"webauthn:auth:{challenge_id}")

    from webauthn.helpers.structs import AuthenticationCredential

    credential = AuthenticationCredential.parse_raw(json.dumps(credential_json))
    credential_id_bytes = base64url_to_bytes(credential.raw_id)

    result = await db.execute(
        select(PasskeyCredential).where(PasskeyCredential.credential_id == credential_id_bytes)
    )
    passkey = result.scalar_one_or_none()
    if not passkey:
        raise ValueError("Credential not found")

    verification = webauthn.verify_authentication_response(
        credential=credential,
        expected_challenge=expected_challenge,
        expected_rp_id=settings.domain,
        expected_origin=settings.frontend_url,
        credential_public_key=passkey.public_key,
        credential_current_sign_count=passkey.sign_count,
    )

    passkey.sign_count = verification.new_sign_count
    passkey.last_used_at = datetime.now(timezone.utc)
    await db.commit()

    from app.services.user_service import get_user_by_id

    user = await get_user_by_id(db, passkey.user_id)
    if not user or not user.is_active:
        raise ValueError("User not found or inactive")

    return user


# ── Credential management ──────────────────────────────────────────────────


async def list_passkeys(db: AsyncSession, user) -> list[PasskeyCredential]:
    result = await db.execute(
        select(PasskeyCredential)
        .where(PasskeyCredential.user_id == user.id)
        .order_by(PasskeyCredential.created_at)
    )
    return list(result.scalars().all())


async def delete_passkey(db: AsyncSession, user, passkey_id: uuid.UUID) -> None:
    result = await db.execute(
        select(PasskeyCredential).where(
            PasskeyCredential.id == passkey_id,
            PasskeyCredential.user_id == user.id,
        )
    )
    passkey = result.scalar_one_or_none()
    if not passkey:
        raise ValueError("Passkey not found")
    await db.delete(passkey)
    await db.commit()
