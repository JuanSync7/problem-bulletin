"""People (user + agent) unified search schemas — v2.1-WP8.

Returned by ``GET /api/v1/people/search``. The shape is uniform across
kinds (no per-kind specific fields needed), so a plain ``PersonRef``
model is used rather than a discriminated union — discriminator was
considered (per WP7 Lessons) but rejected because there's no
kind-specific payload to carry.

Display-field strategy:
- ``kind=user``  → ``display_name`` from ``users.display_name``;
  ``handle`` from ``users.handle`` (materialised column, v2.2-WP17);
  ``email`` exposed only to authenticated callers.
- ``kind=agent`` → ``display_name`` from ``agent_accounts.name``;
  ``handle`` from ``agent_accounts.handle`` (materialised column, v2.2-WP17);
  ``email`` always ``None`` (agents have no email).

Prior to v2.2-WP17, handles were derived in Python (email local-part /
slugified name). The DB column is now the source of truth and is
backfilled with the same algorithm so existing @mentions resolve.
"""
from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class PersonRef(BaseModel):
    """Uniform user-or-agent reference used by the people-search API."""

    model_config = ConfigDict(from_attributes=True)

    kind: Literal["user", "agent"]
    id: UUID
    display_name: str
    handle: str | None = None
    email: str | None = None
    avatar_url: str | None = None


class PeopleSearchResponse(BaseModel):
    items: list[PersonRef]


# ---------------------------------------------------------------------------
# V2a — @mention autocomplete candidates (project-scoped).
# ---------------------------------------------------------------------------


class MentionCandidate(BaseModel):
    """One row in the @mention autocomplete dropdown.

    Returned by ``GET /api/v1/projects/{id}/mention-candidates``. The
    ``type`` discriminator lets the UI render distinct chips/icons for
    human users vs agent accounts.
    """

    model_config = ConfigDict(from_attributes=True)

    type: Literal["user", "agent"]
    id: UUID
    handle: str
    display_name: str


class MentionCandidatesResponse(BaseModel):
    items: list[MentionCandidate]
