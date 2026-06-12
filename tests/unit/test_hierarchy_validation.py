"""Unit tests for ticket parent-type matrix (WP3 service layer).

Pure unit tests over the `_PARENT_ALLOWED` table in
``app.services.tickets``. No DB required. Per spec §3.

The matrix:
- workpackage: no parent
- epic:        no parent, or workpackage parent
- story:       no parent, or epic / workpackage parent
- task:        no parent, or story / epic / workpackage parent
- bug:         no parent, or story / epic / workpackage parent (peer of task)
- subtask:     task / story / bug parent REQUIRED (spec restricts to task/bug;
               WP3 permits story for back-compat — see lessons-learned)
"""
from __future__ import annotations

import pytest

from app.enums import TicketType
from app.services.tickets import _PARENT_ALLOWED


@pytest.mark.parametrize(
    "child,parent,expected",
    [
        # workpackage may have no parent.
        (TicketType.workpackage, None, True),
        (TicketType.workpackage, TicketType.epic, False),
        # epic: none or workpackage
        (TicketType.epic, None, True),
        (TicketType.epic, TicketType.workpackage, True),
        (TicketType.epic, TicketType.story, False),
        # story: none, epic, workpackage
        (TicketType.story, None, True),
        (TicketType.story, TicketType.epic, True),
        (TicketType.story, TicketType.workpackage, True),
        (TicketType.story, TicketType.task, False),
        # task: none, story, epic, workpackage
        (TicketType.task, None, True),
        (TicketType.task, TicketType.story, True),
        (TicketType.task, TicketType.epic, True),
        (TicketType.task, TicketType.workpackage, True),
        (TicketType.task, TicketType.subtask, False),
        # bug: same allowed parents as task
        (TicketType.bug, None, True),
        (TicketType.bug, TicketType.story, True),
        (TicketType.bug, TicketType.epic, True),
        (TicketType.bug, TicketType.workpackage, True),
        (TicketType.bug, TicketType.task, False),
        # subtask: parent REQUIRED (None not allowed); task/bug/story allowed
        (TicketType.subtask, None, False),
        (TicketType.subtask, TicketType.task, True),
        (TicketType.subtask, TicketType.bug, True),
        (TicketType.subtask, TicketType.epic, False),
        (TicketType.subtask, TicketType.workpackage, False),
    ],
)
def test_parent_type_matrix(child, parent, expected):
    """Every child-type pair is either in the allowed-set or not."""
    allowed = _PARENT_ALLOWED.get(child, set())
    assert (parent in allowed) is expected


def test_subtask_requires_parent_invariant():
    """``None`` is NEVER in the subtask allow-set — DB has the CHECK too."""
    assert None not in _PARENT_ALLOWED[TicketType.subtask]


def test_workpackage_has_no_parent_only():
    """workpackage is the top of the in-project tree — only None is allowed."""
    assert _PARENT_ALLOWED[TicketType.workpackage] == {None}
