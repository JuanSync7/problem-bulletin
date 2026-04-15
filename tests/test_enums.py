"""
Tests for app.enums — all six domain enumerations.
Derived from: docs/AION_BULLETIN_TEST_DOCS.md — Foundation Layer: app/enums.py
"""
import json

import pytest

from app.enums import (
    NotificationType,
    ParentType,
    ProblemStatus,
    SortMode,
    UserRole,
    WatchLevel,
)


# ---------------------------------------------------------------------------
# ProblemStatus
# ---------------------------------------------------------------------------

class TestProblemStatus:
    EXPECTED_MEMBERS = {"open", "claimed", "solved", "accepted", "duplicate"}

    def test_exact_members(self):
        """REQ-156: ProblemStatus has exactly five members matching the spec."""
        actual = {m.value for m in ProblemStatus}
        assert actual == self.EXPECTED_MEMBERS

    def test_member_count_is_five(self):
        """REQ-156 (boundary): Exactly five — not four, not six."""
        assert len(ProblemStatus) == 5

    def test_str_equality_open(self):
        """REQ: str mixin — ProblemStatus.open == 'open'."""
        assert ProblemStatus.open == "open"

    def test_str_equality_all_members(self):
        """REQ: Each member's str value equals its name."""
        for member in ProblemStatus:
            assert member == member.value
            assert member == member.name

    def test_construction_from_string(self):
        """REQ: ProblemStatus('open') returns ProblemStatus.open."""
        assert ProblemStatus("open") == ProblemStatus.open

    def test_construction_all_values(self):
        """REQ: All member values can reconstruct the member via ProblemStatus(value)."""
        for member in ProblemStatus:
            assert ProblemStatus(member.value) is member

    def test_invalid_member_raises_value_error(self):
        """REQ: ProblemStatus('closed') raises ValueError."""
        with pytest.raises(ValueError):
            ProblemStatus("closed")

    def test_json_serialisation(self):
        """REQ: json.dumps({'status': ProblemStatus.open}) == '{"status": "open"}'."""
        result = json.dumps({"status": ProblemStatus.open})
        assert result == '{"status": "open"}'

    def test_json_round_trip(self):
        """REQ: Members serialise to their string value and can be deserialised back."""
        for member in ProblemStatus:
            serialised = json.dumps({"v": member})
            loaded = json.loads(serialised)["v"]
            assert loaded == member.value
            assert ProblemStatus(loaded) is member

    def test_usable_as_dict_key(self):
        """REQ: str mixin allows use as dict key without special handling."""
        d = {ProblemStatus.open: "value"}
        assert d["open"] == "value"

    def test_values_are_lowercase_with_underscores(self):
        """REQ (boundary): All values are lowercase strings with underscores — no mixed case."""
        for member in ProblemStatus:
            assert member.value == member.value.lower()
            assert "-" not in member.value


# ---------------------------------------------------------------------------
# UserRole
# ---------------------------------------------------------------------------

class TestUserRole:
    EXPECTED_MEMBERS = {"user", "admin"}

    def test_exact_members(self):
        """REQ: UserRole has exactly two members: user and admin."""
        actual = {m.value for m in UserRole}
        assert actual == self.EXPECTED_MEMBERS

    def test_str_equality_admin(self):
        """REQ: str mixin — UserRole.admin == 'admin'."""
        assert UserRole.admin == "admin"

    def test_str_equality_user(self):
        """REQ: str mixin — UserRole.user == 'user'."""
        assert UserRole.user == "user"

    def test_construction_from_string(self):
        """REQ: UserRole('admin') returns UserRole.admin."""
        assert UserRole("admin") == UserRole.admin

    def test_invalid_member_raises_value_error(self):
        """REQ: UserRole('superadmin') raises ValueError."""
        with pytest.raises(ValueError):
            UserRole("superadmin")

    def test_json_serialisation(self):
        """REQ: UserRole members serialise to their string value."""
        result = json.dumps({"role": UserRole.admin})
        assert result == '{"role": "admin"}'


# ---------------------------------------------------------------------------
# WatchLevel
# ---------------------------------------------------------------------------

class TestWatchLevel:
    EXPECTED_MEMBERS = {"all_activity", "solutions_only", "status_only", "none"}

    def test_exact_members(self):
        """REQ: WatchLevel has exactly four members as specified."""
        actual = {m.value for m in WatchLevel}
        assert actual == self.EXPECTED_MEMBERS

    def test_none_member_is_string_not_python_none(self):
        """REQ (boundary): WatchLevel.none is the string 'none', not Python None."""
        assert WatchLevel.none == "none"
        assert WatchLevel.none is not None
        assert isinstance(WatchLevel.none, str)

    def test_construction_of_none_member(self):
        """REQ: WatchLevel('none') returns WatchLevel.none without error."""
        result = WatchLevel("none")
        assert result is WatchLevel.none

    def test_str_equality_none(self):
        """REQ: str mixin — WatchLevel.none == 'none'."""
        assert WatchLevel.none == "none"

    def test_invalid_member_raises_value_error(self):
        """REQ: WatchLevel('everything') raises ValueError."""
        with pytest.raises(ValueError):
            WatchLevel("everything")

    def test_json_round_trip_none_member(self):
        """REQ: WatchLevel.none serialises to 'none' and round-trips correctly."""
        serialised = json.dumps({"watch": WatchLevel.none})
        loaded = json.loads(serialised)["watch"]
        assert loaded == "none"
        assert WatchLevel(loaded) is WatchLevel.none


# ---------------------------------------------------------------------------
# NotificationType
# ---------------------------------------------------------------------------

class TestNotificationType:
    EXPECTED_MEMBERS = {
        "problem_claimed",
        "solution_posted",
        "solution_accepted",
        "comment_posted",
        "status_changed",
        "problem_pinned",
        "upstar_received",
        "mention",
    }

    def test_exact_members(self):
        """REQ-310: NotificationType has exactly the eight specified members."""
        actual = {m.value for m in NotificationType}
        assert actual == self.EXPECTED_MEMBERS

    def test_member_count_is_eight(self):
        """REQ-310 (boundary): Exactly eight members — not seven, not nine."""
        assert len(NotificationType) == 8

    def test_construction_from_string(self):
        """REQ: NotificationType('mention') returns NotificationType.mention."""
        assert NotificationType("mention") == NotificationType.mention

    def test_invalid_member_raises_value_error(self):
        """REQ: Invalid value raises ValueError."""
        with pytest.raises(ValueError):
            NotificationType("unknown_type")

    def test_all_values_lowercase_with_underscores(self):
        """REQ (boundary): All values are lowercase with underscores."""
        for member in NotificationType:
            assert member.value == member.value.lower()
            assert "-" not in member.value

    def test_json_serialisation(self):
        """REQ: Members serialise to their string value."""
        result = json.dumps({"type": NotificationType.mention})
        assert result == '{"type": "mention"}'


# ---------------------------------------------------------------------------
# SortMode
# ---------------------------------------------------------------------------

class TestSortMode:
    EXPECTED_MEMBERS = {"top", "new", "active", "discussed"}

    def test_exact_members(self):
        """REQ: SortMode has exactly four members: top, new, active, discussed."""
        actual = {m.value for m in SortMode}
        assert actual == self.EXPECTED_MEMBERS

    def test_str_equality(self):
        """REQ: str mixin — each SortMode member equals its string name."""
        for member in SortMode:
            assert member == member.value

    def test_construction_from_string(self):
        """REQ: SortMode('top') returns SortMode.top."""
        assert SortMode("top") == SortMode.top

    def test_invalid_member_raises_value_error(self):
        """REQ: Invalid value raises ValueError."""
        with pytest.raises(ValueError):
            SortMode("trending")

    def test_json_serialisation(self):
        """REQ: SortMode members serialise to their string value."""
        result = json.dumps({"sort": SortMode.new})
        assert result == '{"sort": "new"}'


# ---------------------------------------------------------------------------
# ParentType
# ---------------------------------------------------------------------------

class TestParentType:
    EXPECTED_MEMBERS = {"problem", "solution", "comment"}

    def test_exact_members(self):
        """REQ: ParentType has exactly three members: problem, solution, comment."""
        actual = {m.value for m in ParentType}
        assert actual == self.EXPECTED_MEMBERS

    def test_str_equality(self):
        """REQ: str mixin — each ParentType member equals its string name."""
        for member in ParentType:
            assert member == member.value

    def test_construction_from_string(self):
        """REQ: ParentType('comment') returns ParentType.comment."""
        assert ParentType("comment") == ParentType.comment

    def test_invalid_member_raises_value_error(self):
        """REQ: Invalid value raises ValueError."""
        with pytest.raises(ValueError):
            ParentType("attachment")

    def test_json_serialisation(self):
        """REQ: ParentType members serialise to their string value."""
        result = json.dumps({"parent": ParentType.problem})
        assert result == '{"parent": "problem"}'


# ---------------------------------------------------------------------------
# Cross-enum: str mixin contract
# ---------------------------------------------------------------------------

class TestStrMixinContract:
    """Verify the str mixin works uniformly across all six enums."""

    @pytest.mark.parametrize("enum_cls, value", [
        (ProblemStatus, "open"),
        (UserRole, "admin"),
        (WatchLevel, "none"),
        (NotificationType, "mention"),
        (SortMode, "top"),
        (ParentType, "problem"),
    ])
    def test_member_is_instance_of_str(self, enum_cls, value):
        """REQ: All enum members are instances of str due to str mixin."""
        member = enum_cls(value)
        assert isinstance(member, str)

    @pytest.mark.parametrize("enum_cls, value", [
        (ProblemStatus, "open"),
        (UserRole, "admin"),
        (WatchLevel, "none"),
        (NotificationType, "mention"),
        (SortMode, "top"),
        (ParentType, "problem"),
    ])
    def test_member_usable_as_dict_key_with_plain_string(self, enum_cls, value):
        """REQ: str mixin — member usable as dict key interchangeable with plain string."""
        member = enum_cls(value)
        d = {member: "result"}
        assert d[value] == "result"

# GAP: No test for StrEnum vs str,Enum compatibility on Python 3.11+ (rejected design)
# GAP: No test for SQLAlchemy VARCHAR column round-trip (requires database integration)
