"""AgentAccountService — provisioning + bearer auth (Task S8 / A15).

Keys are 32-byte urlsafe tokens. We store an argon2id hash plus the first 8
characters of the plaintext as a non-secret lookup prefix (so we don't have to
hash every row to authenticate). The prefix is indexed.

Plaintext keys are returned to the caller exactly once, at creation time.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Sequence
from uuid import UUID

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import ActorType
from app.exceptions import AuthError, ScopeDeniedError, ValidationError
from app.models.agent_account import AgentAccount
from app.services.context import Actor

_PREFIX_LEN = 8

# Shared argon2 hasher. Default params (3 iters, 64MiB) are fine for
# per-request bearer auth; we cache (prefix -> account) for ≤5s in the route
# layer so the verify cost amortises.
_HASHER = PasswordHasher()


def _generate_key() -> str:
    """Return a 32-byte urlsafe token (43 chars after b64 strip)."""
    return secrets.token_urlsafe(32)


class AgentAccountService:
    """Manage ``agent_accounts`` rows + bearer-token authentication."""

    async def create_account(
        self,
        session: AsyncSession,
        *,
        name: str,
        scopes: Sequence[str] | None = None,
        description: str | None = None,
        created_by: UUID | None = None,
    ) -> tuple[AgentAccount, str]:
        """Create an agent account and return ``(account, plaintext_key)``.

        The plaintext key is returned ONCE here and is not stored anywhere.
        Re-issue requires creating a new account (or revoking + recreating).
        """
        if not name or not name.strip():
            raise ValidationError([{"name": "name", "reason": "required"}])

        plaintext = _generate_key()
        prefix = plaintext[:_PREFIX_LEN]
        hashed = _HASHER.hash(plaintext)

        account = AgentAccount(
            name=name,
            description=description,
            api_key_hash=hashed,
            api_key_prefix=prefix,
            scopes=list(scopes or []),
            created_by=created_by,
            active=True,
        )
        session.add(account)
        await session.flush([account])
        return account, plaintext

    async def authenticate(
        self,
        session: AsyncSession,
        api_key: str,
    ) -> Actor:
        """Resolve a plaintext API key to an :class:`Actor`.

        Lookup is by prefix (indexed); argon2 verifies the remainder. Updates
        ``last_seen_at`` on success. Raises :class:`AuthError` on any failure
        path (unknown prefix, hash mismatch, revoked, inactive).
        """
        if not api_key or len(api_key) <= _PREFIX_LEN:
            raise AuthError("invalid api key")

        prefix = api_key[:_PREFIX_LEN]
        stmt = select(AgentAccount).where(
            AgentAccount.api_key_prefix == prefix,
            AgentAccount.active.is_(True),
            AgentAccount.revoked_at.is_(None),
        )
        result = await session.execute(stmt)
        candidates = list(result.scalars().all())
        if not candidates:
            raise AuthError("invalid api key")

        matched: AgentAccount | None = None
        for candidate in candidates:
            try:
                _HASHER.verify(candidate.api_key_hash, api_key)
                matched = candidate
                break
            except VerifyMismatchError:
                continue
        if matched is None:
            raise AuthError("invalid api key")

        matched.last_seen_at = datetime.now(timezone.utc)
        await session.flush([matched])

        return Actor(
            id=matched.id,
            type=ActorType.agent,
            label=matched.name,
            scopes=tuple(matched.scopes or ()),
        )

    @staticmethod
    def require_scope(actor: Actor, required: str) -> None:
        """Raise :class:`ScopeDeniedError` if ``actor`` lacks ``required``."""
        if required not in (actor.scopes or ()):
            raise ScopeDeniedError(required)

    async def revoke(
        self,
        session: AsyncSession,
        account_id: UUID,
    ) -> None:
        """Mark an account inactive + revoked. Idempotent."""
        await session.execute(
            update(AgentAccount)
            .where(AgentAccount.id == account_id)
            .values(active=False, revoked_at=datetime.now(timezone.utc))
        )
