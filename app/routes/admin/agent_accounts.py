"""Admin routes for managing AgentAccount records (Task R3).

Endpoints:
    POST   /api/v1/admin/agent-accounts          create + return plaintext key once
    GET    /api/v1/admin/agent-accounts          list (no plaintext)
    POST   /api/v1/admin/agent-accounts/{id}/revoke

All endpoints require an admin user.
"""
from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.bearer_auth import get_admin_actor
from app.models.agent_account import AgentAccount
from app.services.agent_accounts import AgentAccountService
from app.services.context import Actor

router = APIRouter(prefix="/v1/admin/agent-accounts", tags=["admin", "agent-accounts"])


class CreateAgentAccountBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    scopes: list[str] = Field(default_factory=list)


class AgentAccountRead(BaseModel):
    id: UUID
    name: str
    description: Optional[str] = None
    api_key_prefix: str
    scopes: list[str]
    active: bool


class AgentAccountCreated(AgentAccountRead):
    api_key: str  # plaintext, returned once


@router.post("", status_code=status.HTTP_201_CREATED, response_model=AgentAccountCreated)
async def create_agent_account(
    payload: CreateAgentAccountBody,
    actor: Actor = Depends(get_admin_actor),
    db: AsyncSession = Depends(get_db),
):
    svc = AgentAccountService()
    account, plaintext = await svc.create_account(
        db,
        name=payload.name,
        description=payload.description,
        scopes=payload.scopes,
        created_by=actor.id,
    )
    return AgentAccountCreated(
        id=account.id,
        name=account.name,
        description=account.description,
        api_key_prefix=account.api_key_prefix,
        scopes=list(account.scopes or []),
        active=account.active,
        api_key=plaintext,
    )


@router.get("", response_model=list[AgentAccountRead])
async def list_agent_accounts(
    actor: Actor = Depends(get_admin_actor),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(AgentAccount).order_by(AgentAccount.name.asc())
    )
    accounts = result.scalars().all()
    return [
        AgentAccountRead(
            id=a.id,
            name=a.name,
            description=a.description,
            api_key_prefix=a.api_key_prefix,
            scopes=list(a.scopes or []),
            active=a.active,
        )
        for a in accounts
    ]


@router.post("/{account_id}/revoke", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_agent_account(
    account_id: UUID,
    actor: Actor = Depends(get_admin_actor),
    db: AsyncSession = Depends(get_db),
):
    svc = AgentAccountService()
    await svc.revoke(db, account_id)
    return None
