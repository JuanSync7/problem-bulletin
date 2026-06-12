"""v2.11-WP01 — ORM↔DB alignment for ``agent_accounts.created_by``.

v2.10-WP02 tightened the DB column to NOT NULL via migration ``a17`` and
routed test seeding through ``tests.helpers.seed_agent_account`` so every
INSERT carries a real ``created_by``.

What v2.10 did NOT do: tighten the ORM model and the service signature.
Both still allowed ``None``, meaning a forgetful caller would pass the type
checker and only fail at flush time with a hard-to-read ``IntegrityError``.

This WP closes the gap at the type-checker / service boundary. The two
tests below are RED on unchanged main and GREEN after the fix.
"""
from __future__ import annotations

import pytest

from app.exceptions import ValidationError
from app.models.agent_account import AgentAccount
from app.services.agent_accounts import AgentAccountService

# Reuse the live-Postgres ``db`` fixture from the services tree.
from tests.services.conftest import db, pg_engine  # noqa: F401


def test_agent_account_model_created_by_is_not_null():
    """G1 — the SQLAlchemy column metadata must mirror the DB constraint."""
    column = AgentAccount.__table__.columns["created_by"]
    assert column.nullable is False, (
        "AgentAccount.created_by must declare nullable=False to mirror the "
        "NOT NULL constraint applied by migration a17."
    )


@pytest.mark.asyncio
async def test_service_create_account_without_created_by_raises_validation_error(db):
    """G2 — the service must reject a missing/None ``created_by`` cleanly.

    Pre-fix: omitting ``created_by`` would flush a NULL row, the DB would
    raise ``IntegrityError``, and the caller would get a confusing trace.
    Post-fix: the service guards the precondition up front — either via the
    keyword-only signature (``TypeError`` when omitted entirely) or via the
    explicit ``None`` guard inside the body (``ValidationError``).
    """
    svc = AgentAccountService()

    # Omitting the argument entirely is a signature-level error.
    with pytest.raises(TypeError):
        await svc.create_account(db, name="bot-test-missing-created-by")  # type: ignore[call-arg]

    # Passing ``None`` explicitly (e.g. an old caller still threading a
    # nullable variable through) hits the service-layer guard.
    with pytest.raises(ValidationError):
        await svc.create_account(
            db, name="bot-test-none-created-by", created_by=None,  # type: ignore[arg-type]
        )
