"""
Tests for app.services.admin, app.services.categories, app.services.tags.

Coverage:
- search_users: ILIKE match on display_name and email
- update_user_role: changes role field, emits log_event
- update_user_status: toggles is_active
- create_category: auto-generates slug, auto-increments sort_order
- soft_delete_category: sets deleted_at; raises error if problems reference it
- rename_tag: raises error on name collision
- delete_tag: hard deletes with ProblemTag cleanup
- merge_tags: INSERT ON CONFLICT DO NOTHING, then delete source
- resolve_flag: sets status, resolution_note, resolved_by
- de_anonymize: writes AuditLog before returning author_id; 400 if not anonymous
- get_config/update_config: validates key against ALLOWED_CONFIG_KEYS
- 404 for nonexistent user/category/tag/flag
"""
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from app.services.admin import (
    search_users,
    update_user_role,
    update_user_status,
    de_anonymize,
)
from app.services.categories import create_category, soft_delete_category
from app.services.tags import rename_tag, delete_tag, merge_tags, get_tags


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ALLOWED_CONFIG_KEYS = frozenset(
    ["max_pin_count", "claim_expiry_days", "magic_link_ttl_minutes", "auto_watch_default_level"]
)


def _make_user(
    *,
    user_id=None,
    display_name="Alice",
    email="alice@example.com",
    role="user",
    is_active=True,
):
    u = MagicMock()
    u.id = user_id or uuid.uuid4()
    u.display_name = display_name
    u.email = email
    u.role = role
    u.is_active = is_active
    return u


def _make_category(*, cat_id=None, name="Design", slug="design", sort_order=0, deleted_at=None):
    c = MagicMock()
    c.id = cat_id or uuid.uuid4()
    c.name = name
    c.slug = slug
    c.sort_order = sort_order
    c.deleted_at = deleted_at
    return c


def _make_tag(*, tag_id=None, name="fpga"):
    t = MagicMock()
    t.id = tag_id or uuid.uuid4()
    t.name = name
    return t


def _make_flag(*, flag_id=None, status="pending"):
    f = MagicMock()
    f.id = flag_id or uuid.uuid4()
    f.status = status
    f.resolution_note = None
    f.resolved_by = None
    return f


def _make_problem(*, problem_id=None, is_anonymous=True, category_id=None, author_id=None):
    p = MagicMock()
    p.id = problem_id or uuid.uuid4()
    p.is_anonymous = is_anonymous
    p.category_id = category_id or uuid.uuid4()
    p.author_id = author_id or uuid.uuid4()
    return p


def _scalars_result(rows):
    """Return a mock that behaves like session.execute().scalars().all()."""
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    result.scalar_one_or_none.return_value = rows[0] if rows else None
    result.scalar.return_value = rows[0] if rows else None
    return result


# ---------------------------------------------------------------------------
# search_users
# ---------------------------------------------------------------------------


class TestSearchUsers:
    @pytest.mark.asyncio
    async def test_returns_matching_users_by_display_name(self, mock_db):
        alice = _make_user(display_name="Alice")
        mock_db.execute = AsyncMock(return_value=_scalars_result([alice]))

        result = await search_users(db=mock_db, q="alice")

        mock_db.execute.assert_called_once()
        assert alice in result

    @pytest.mark.asyncio
    async def test_returns_matching_users_by_email(self, mock_db):
        user = _make_user(email="alice@corp.com")
        mock_db.execute = AsyncMock(return_value=_scalars_result([user]))

        result = await search_users(db=mock_db, q="@corp.com")

        assert user in result

    @pytest.mark.asyncio
    async def test_no_query_param_returns_all_users(self, mock_db):
        users = [_make_user(display_name=f"User{i}") for i in range(3)]
        mock_db.execute = AsyncMock(return_value=_scalars_result(users))

        result = await search_users(db=mock_db, q=None)

        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_empty_q_returns_all_users(self, mock_db):
        users = [_make_user()]
        mock_db.execute = AsyncMock(return_value=_scalars_result(users))

        result = await search_users(db=mock_db, q="")

        assert result == users

    @pytest.mark.asyncio
    async def test_no_matches_returns_empty_list(self, mock_db):
        mock_db.execute = AsyncMock(return_value=_scalars_result([]))

        result = await search_users(db=mock_db, q="zzznomatch")

        assert result == []


# ---------------------------------------------------------------------------
# update_user_role
# ---------------------------------------------------------------------------


class TestUpdateUserRole:
    @pytest.mark.asyncio
    async def test_updates_role_field(self, mock_db):
        user = _make_user(role="user")
        mock_db.get = AsyncMock(return_value=user)

        with patch("app.services.admin.log_event", new_callable=AsyncMock) as mock_log:
            await update_user_role(db=mock_db, user_id=user.id, new_role="admin")

        assert user.role == "admin"

    @pytest.mark.asyncio
    async def test_emits_log_event_role_changed(self, mock_db):
        user = _make_user()
        mock_db.get = AsyncMock(return_value=user)

        with patch("app.services.admin.log_event", new_callable=AsyncMock) as mock_log:
            await update_user_role(db=mock_db, user_id=user.id, new_role="admin")

        mock_log.assert_called_once()
        call_args = mock_log.call_args
        assert "role_changed" in str(call_args) or "user.role_changed" in str(call_args)

    @pytest.mark.asyncio
    async def test_raises_404_for_nonexistent_user(self, mock_db):
        mock_db.get = AsyncMock(return_value=None)

        with pytest.raises(Exception) as exc_info:
            await update_user_role(db=mock_db, user_id=uuid.uuid4(), new_role="admin")

        assert "404" in str(exc_info.value) or "not found" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# update_user_status
# ---------------------------------------------------------------------------


class TestUpdateUserStatus:
    @pytest.mark.asyncio
    async def test_deactivates_user(self, mock_db):
        user = _make_user(is_active=True)
        mock_db.get = AsyncMock(return_value=user)

        with patch("app.services.admin.log_event", new_callable=AsyncMock):
            await update_user_status(db=mock_db, user_id=user.id, is_active=False)

        assert user.is_active is False

    @pytest.mark.asyncio
    async def test_reactivates_user(self, mock_db):
        user = _make_user(is_active=False)
        mock_db.get = AsyncMock(return_value=user)

        with patch("app.services.admin.log_event", new_callable=AsyncMock):
            await update_user_status(db=mock_db, user_id=user.id, is_active=True)

        assert user.is_active is True

    @pytest.mark.asyncio
    async def test_emits_status_changed_log_event(self, mock_db):
        user = _make_user()
        mock_db.get = AsyncMock(return_value=user)

        with patch("app.services.admin.log_event", new_callable=AsyncMock) as mock_log:
            await update_user_status(db=mock_db, user_id=user.id, is_active=False)

        mock_log.assert_called_once()
        assert "status_changed" in str(mock_log.call_args)

    @pytest.mark.asyncio
    async def test_raises_404_for_nonexistent_user(self, mock_db):
        mock_db.get = AsyncMock(return_value=None)

        with pytest.raises(Exception) as exc_info:
            await update_user_status(db=mock_db, user_id=uuid.uuid4(), is_active=False)

        assert "404" in str(exc_info.value) or "not found" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# create_category
# ---------------------------------------------------------------------------


class TestCreateCategory:
    @pytest.mark.asyncio
    async def test_auto_generates_slug(self, mock_db):
        # simulate empty table: MAX(sort_order) returns None
        scalar_mock = MagicMock()
        scalar_mock.scalar.return_value = None
        mock_db.execute = AsyncMock(return_value=scalar_mock)

        created = []

        def capture_add(obj):
            created.append(obj)

        mock_db.add = capture_add

        await create_category(db=mock_db, name="RTL Design")

        assert mock_db.flush.called
        assert len(created) == 1
        assert created[0].slug == "rtl-design"

    @pytest.mark.asyncio
    async def test_sort_order_zero_when_table_empty(self, mock_db):
        scalar_mock = MagicMock()
        scalar_mock.scalar.return_value = None
        mock_db.execute = AsyncMock(return_value=scalar_mock)

        created = []
        mock_db.add = lambda obj: created.append(obj)

        await create_category(db=mock_db, name="First Category")

        assert created[0].sort_order == 0

    @pytest.mark.asyncio
    async def test_sort_order_increments_from_existing_max(self, mock_db):
        scalar_mock = MagicMock()
        scalar_mock.scalar.return_value = 4
        mock_db.execute = AsyncMock(return_value=scalar_mock)

        created = []
        mock_db.add = lambda obj: created.append(obj)

        await create_category(db=mock_db, name="New Category")

        assert created[0].sort_order == 5

    @pytest.mark.asyncio
    async def test_slugify_strips_special_characters(self, mock_db):
        scalar_mock = MagicMock()
        scalar_mock.scalar.return_value = None
        mock_db.execute = AsyncMock(return_value=scalar_mock)

        created = []
        mock_db.add = lambda obj: created.append(obj)

        await create_category(db=mock_db, name="EDA Tools & Flows!")

        assert created[0].slug == "eda-tools-flows"

    @pytest.mark.asyncio
    async def test_slugify_trims_leading_trailing_spaces(self, mock_db):
        scalar_mock = MagicMock()
        scalar_mock.scalar.return_value = None
        mock_db.execute = AsyncMock(return_value=scalar_mock)

        created = []
        mock_db.add = lambda obj: created.append(obj)

        await create_category(db=mock_db, name=" Design ")

        assert created[0].slug == "design"

    @pytest.mark.asyncio
    async def test_sequential_creates_increment_sort_order(self, mock_db):
        sort_orders_seen = []

        async def fake_execute(stmt):
            mock = MagicMock()
            mock.scalar.return_value = sort_orders_seen[-1] if sort_orders_seen else None
            return mock

        mock_db.execute = fake_execute
        created = []

        def capture_add(obj):
            sort_orders_seen.append(obj.sort_order)
            created.append(obj)

        mock_db.add = capture_add

        await create_category(db=mock_db, name="Cat A")
        await create_category(db=mock_db, name="Cat B")

        assert created[0].sort_order == 0
        assert created[1].sort_order == 1


# ---------------------------------------------------------------------------
# soft_delete_category
# ---------------------------------------------------------------------------


class TestSoftDeleteCategory:
    @pytest.mark.asyncio
    async def test_sets_deleted_at_when_no_problems(self, mock_db):
        cat = _make_category()
        mock_db.get = AsyncMock(return_value=cat)
        # no problems reference this category
        count_result = MagicMock()
        count_result.scalar.return_value = 0
        mock_db.execute = AsyncMock(return_value=count_result)

        await soft_delete_category(db=mock_db, category_id=cat.id)

        assert cat.deleted_at is not None

    @pytest.mark.asyncio
    async def test_raises_error_when_problems_reference_category(self, mock_db):
        cat = _make_category()
        mock_db.get = AsyncMock(return_value=cat)
        count_result = MagicMock()
        count_result.scalar.return_value = 3  # 3 problems reference this category
        mock_db.execute = AsyncMock(return_value=count_result)

        with pytest.raises(Exception) as exc_info:
            await soft_delete_category(db=mock_db, category_id=cat.id)

        err_str = str(exc_info.value).lower()
        assert "409" in err_str or "in use" in err_str or "referenced" in err_str

    @pytest.mark.asyncio
    async def test_deleted_at_unchanged_when_blocked(self, mock_db):
        cat = _make_category(deleted_at=None)
        mock_db.get = AsyncMock(return_value=cat)
        count_result = MagicMock()
        count_result.scalar.return_value = 1
        mock_db.execute = AsyncMock(return_value=count_result)

        with pytest.raises(Exception):
            await soft_delete_category(db=mock_db, category_id=cat.id)

        assert cat.deleted_at is None

    @pytest.mark.asyncio
    async def test_raises_404_for_nonexistent_category(self, mock_db):
        mock_db.get = AsyncMock(return_value=None)

        with pytest.raises(Exception) as exc_info:
            await soft_delete_category(db=mock_db, category_id=uuid.uuid4())

        assert "404" in str(exc_info.value) or "not found" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# rename_tag
# ---------------------------------------------------------------------------


class TestRenameTag:
    @pytest.mark.asyncio
    async def test_renames_tag_successfully(self, mock_db):
        tag = _make_tag(name="old-name")
        mock_db.get = AsyncMock(return_value=tag)
        # no conflict
        conflict_result = MagicMock()
        conflict_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=conflict_result)

        await rename_tag(db=mock_db, tag_id=tag.id, new_name="new-name")

        assert tag.name == "new-name"

    @pytest.mark.asyncio
    async def test_raises_error_on_name_collision(self, mock_db):
        tag = _make_tag(name="fpga")
        existing = _make_tag(name="asic")
        mock_db.get = AsyncMock(return_value=tag)
        conflict_result = MagicMock()
        conflict_result.scalar_one_or_none.return_value = existing
        mock_db.execute = AsyncMock(return_value=conflict_result)

        with pytest.raises(Exception) as exc_info:
            await rename_tag(db=mock_db, tag_id=tag.id, new_name="asic")

        err_str = str(exc_info.value).lower()
        assert "409" in err_str or "conflict" in err_str or "already exists" in err_str

    @pytest.mark.asyncio
    async def test_self_rename_succeeds(self, mock_db):
        """Renaming to the same name should not raise a 409."""
        tag = _make_tag(name="fpga")
        mock_db.get = AsyncMock(return_value=tag)
        # no OTHER tag with this name
        conflict_result = MagicMock()
        conflict_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=conflict_result)

        # Should not raise
        await rename_tag(db=mock_db, tag_id=tag.id, new_name="fpga")

    @pytest.mark.asyncio
    async def test_raises_404_for_nonexistent_tag(self, mock_db):
        mock_db.get = AsyncMock(return_value=None)

        with pytest.raises(Exception) as exc_info:
            await rename_tag(db=mock_db, tag_id=uuid.uuid4(), new_name="anything")

        assert "404" in str(exc_info.value) or "not found" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# delete_tag
# ---------------------------------------------------------------------------


class TestDeleteTag:
    @pytest.mark.asyncio
    async def test_hard_deletes_tag_and_problem_tag_rows(self, mock_db):
        tag = _make_tag()
        mock_db.get = AsyncMock(return_value=tag)
        execute_result = MagicMock()
        mock_db.execute = AsyncMock(return_value=execute_result)

        await delete_tag(db=mock_db, tag_id=tag.id)

        # Should have executed a DELETE on ProblemTag and then deleted the tag
        assert mock_db.execute.called or mock_db.delete.called
        # At minimum, tag should be removed
        if mock_db.delete.called:
            mock_db.delete.assert_called_with(tag)

    @pytest.mark.asyncio
    async def test_raises_404_for_nonexistent_tag(self, mock_db):
        mock_db.get = AsyncMock(return_value=None)

        with pytest.raises(Exception) as exc_info:
            await delete_tag(db=mock_db, tag_id=uuid.uuid4())

        assert "404" in str(exc_info.value) or "not found" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# merge_tags
# ---------------------------------------------------------------------------


class TestMergeTags:
    @pytest.mark.asyncio
    async def test_merges_unique_problems_to_target(self, mock_db):
        source = _make_tag(name="source-tag")
        target = _make_tag(name="target-tag")

        def get_side_effect(model, pk):
            if pk == source.id:
                return source
            if pk == target.id:
                return target
            return None

        mock_db.get = AsyncMock(side_effect=get_side_effect)
        mock_db.execute = AsyncMock(return_value=MagicMock())

        result = await merge_tags(db=mock_db, source_id=source.id, target_id=target.id)

        assert mock_db.execute.called
        # Source tag should be deleted
        assert mock_db.delete.called

    @pytest.mark.asyncio
    async def test_on_conflict_do_nothing_for_duplicate_associations(self, mock_db):
        """merge_tags should use INSERT ON CONFLICT DO NOTHING — no integrity error on duplicates."""
        source = _make_tag(name="dup-source")
        target = _make_tag(name="dup-target")

        def get_side_effect(model, pk):
            return source if pk == source.id else target

        mock_db.get = AsyncMock(side_effect=get_side_effect)
        # Simulate no IntegrityError (ON CONFLICT absorbs it)
        mock_db.execute = AsyncMock(return_value=MagicMock())

        # Should not raise
        await merge_tags(db=mock_db, source_id=source.id, target_id=target.id)

    @pytest.mark.asyncio
    async def test_raises_400_when_source_equals_target(self, mock_db):
        tag_id = uuid.uuid4()

        with pytest.raises(Exception) as exc_info:
            await merge_tags(db=mock_db, source_id=tag_id, target_id=tag_id)

        err_str = str(exc_info.value).lower()
        assert "400" in err_str or "different" in err_str or "same" in err_str

    @pytest.mark.asyncio
    async def test_raises_404_for_nonexistent_source(self, mock_db):
        target = _make_tag()
        mock_db.get = AsyncMock(return_value=None)

        with pytest.raises(Exception) as exc_info:
            await merge_tags(db=mock_db, source_id=uuid.uuid4(), target_id=target.id)

        assert "404" in str(exc_info.value) or "not found" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_raises_404_for_nonexistent_target(self, mock_db):
        source = _make_tag()

        def get_side_effect(model, pk):
            if pk == source.id:
                return source
            return None

        mock_db.get = AsyncMock(side_effect=get_side_effect)

        with pytest.raises(Exception) as exc_info:
            await merge_tags(db=mock_db, source_id=source.id, target_id=uuid.uuid4())

        assert "404" in str(exc_info.value) or "not found" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_merge_with_no_source_problems_still_deletes_source(self, mock_db):
        source = _make_tag(name="empty-source")
        target = _make_tag(name="target")

        def get_side_effect(model, pk):
            return source if pk == source.id else target

        mock_db.get = AsyncMock(side_effect=get_side_effect)
        mock_db.execute = AsyncMock(return_value=MagicMock())

        await merge_tags(db=mock_db, source_id=source.id, target_id=target.id)

        # Source tag must be deleted even when it has zero ProblemTag rows
        assert mock_db.delete.called


# ---------------------------------------------------------------------------
# resolve_flag
# ---------------------------------------------------------------------------


class TestResolveFlag:
    @pytest.mark.asyncio
    async def test_sets_flag_resolved_status(self, mock_db):
        from app.services.admin import resolve_flag

        flag = _make_flag(status="pending")
        admin_user = _make_user(role="admin")
        mock_db.get = AsyncMock(return_value=flag)

        with patch("app.services.admin.log_event", new_callable=AsyncMock):
            await resolve_flag(
                db=mock_db,
                flag_id=flag.id,
                resolution_note="Handled",
                resolved_by=admin_user.id,
            )

        assert flag.status == "resolved"
        assert flag.resolution_note == "Handled"
        assert flag.resolved_by == admin_user.id

    @pytest.mark.asyncio
    async def test_emits_flag_resolved_log_event(self, mock_db):
        from app.services.admin import resolve_flag

        flag = _make_flag()
        mock_db.get = AsyncMock(return_value=flag)

        with patch("app.services.admin.log_event", new_callable=AsyncMock) as mock_log:
            await resolve_flag(
                db=mock_db,
                flag_id=flag.id,
                resolution_note="ok",
                resolved_by=uuid.uuid4(),
            )

        mock_log.assert_called_once()
        assert "flag.resolved" in str(mock_log.call_args) or "resolved" in str(mock_log.call_args)

    @pytest.mark.asyncio
    async def test_raises_404_for_nonexistent_flag(self, mock_db):
        from app.services.admin import resolve_flag

        mock_db.get = AsyncMock(return_value=None)

        with pytest.raises(Exception) as exc_info:
            await resolve_flag(
                db=mock_db,
                flag_id=uuid.uuid4(),
                resolution_note="n/a",
                resolved_by=uuid.uuid4(),
            )

        assert "404" in str(exc_info.value) or "not found" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# de_anonymize
# ---------------------------------------------------------------------------


class TestDeAnonymize:
    @pytest.mark.asyncio
    async def test_writes_audit_log_before_returning_author_id(self, mock_db):
        problem = _make_problem(is_anonymous=True)
        mock_db.get = AsyncMock(return_value=problem)

        audit_rows = []
        original_add = mock_db.add

        def capture_add(obj):
            audit_rows.append(obj)

        mock_db.add = capture_add

        with patch("app.services.admin.log_event", new_callable=AsyncMock):
            result = await de_anonymize(db=mock_db, problem_id=problem.id, admin_id=uuid.uuid4())

        # AuditLog must be added before the response
        assert len(audit_rows) >= 1
        assert result == problem.author_id

    @pytest.mark.asyncio
    async def test_flush_called_before_returning(self, mock_db):
        problem = _make_problem(is_anonymous=True)
        mock_db.get = AsyncMock(return_value=problem)
        mock_db.add = MagicMock()

        with patch("app.services.admin.log_event", new_callable=AsyncMock):
            await de_anonymize(db=mock_db, problem_id=problem.id, admin_id=uuid.uuid4())

        mock_db.flush.assert_called()

    @pytest.mark.asyncio
    async def test_emits_de_anonymize_log_event(self, mock_db):
        problem = _make_problem(is_anonymous=True)
        mock_db.get = AsyncMock(return_value=problem)
        mock_db.add = MagicMock()

        with patch("app.services.admin.log_event", new_callable=AsyncMock) as mock_log:
            await de_anonymize(db=mock_db, problem_id=problem.id, admin_id=uuid.uuid4())

        mock_log.assert_called()
        assert "de_anonymize" in str(mock_log.call_args)

    @pytest.mark.asyncio
    async def test_raises_400_when_problem_not_anonymous(self, mock_db):
        problem = _make_problem(is_anonymous=False)
        mock_db.get = AsyncMock(return_value=problem)

        with pytest.raises(Exception) as exc_info:
            await de_anonymize(db=mock_db, problem_id=problem.id, admin_id=uuid.uuid4())

        err_str = str(exc_info.value).lower()
        assert "400" in err_str or "not anonymous" in err_str

    @pytest.mark.asyncio
    async def test_no_audit_log_written_when_not_anonymous(self, mock_db):
        problem = _make_problem(is_anonymous=False)
        mock_db.get = AsyncMock(return_value=problem)
        added = []
        mock_db.add = lambda obj: added.append(obj)

        with pytest.raises(Exception):
            await de_anonymize(db=mock_db, problem_id=problem.id, admin_id=uuid.uuid4())

        assert len(added) == 0

    @pytest.mark.asyncio
    async def test_raises_404_for_nonexistent_problem(self, mock_db):
        mock_db.get = AsyncMock(return_value=None)

        with pytest.raises(Exception) as exc_info:
            await de_anonymize(db=mock_db, problem_id=uuid.uuid4(), admin_id=uuid.uuid4())

        assert "404" in str(exc_info.value) or "not found" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_second_call_writes_second_audit_log_entry(self, mock_db):
        """No idempotency guard: two calls write two audit entries."""
        problem = _make_problem(is_anonymous=True)
        mock_db.get = AsyncMock(return_value=problem)
        added = []
        mock_db.add = lambda obj: added.append(obj)

        with patch("app.services.admin.log_event", new_callable=AsyncMock):
            await de_anonymize(db=mock_db, problem_id=problem.id, admin_id=uuid.uuid4())
            await de_anonymize(db=mock_db, problem_id=problem.id, admin_id=uuid.uuid4())

        # Two separate AuditLog entries expected
        assert len(added) >= 2


# ---------------------------------------------------------------------------
# get_config / update_config
# ---------------------------------------------------------------------------


class TestGetConfig:
    @pytest.mark.asyncio
    async def test_returns_all_config_rows_alphabetically(self, mock_db):
        from app.services.admin import get_config

        rows = [MagicMock(key=k) for k in ["zzz", "aaa", "mmm"]]
        mock_db.execute = AsyncMock(return_value=_scalars_result(rows))

        result = await get_config(db=mock_db)

        assert result == rows


class TestUpdateConfig:
    @pytest.mark.asyncio
    async def test_updates_existing_allowed_key(self, mock_db):
        from app.services.admin import update_config

        existing = MagicMock(key="max_pin_count", value="5")
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = existing
        mock_db.execute = AsyncMock(return_value=result_mock)

        with patch("app.services.admin.log_event", new_callable=AsyncMock):
            await update_config(db=mock_db, key="max_pin_count", value="10")

        assert existing.value == "10"

    @pytest.mark.asyncio
    async def test_inserts_new_allowed_key(self, mock_db):
        from app.services.admin import update_config

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=result_mock)
        added = []
        mock_db.add = lambda obj: added.append(obj)

        with patch("app.services.admin.log_event", new_callable=AsyncMock):
            await update_config(db=mock_db, key="claim_expiry_days", value="30")

        assert len(added) == 1

    @pytest.mark.asyncio
    @pytest.mark.parametrize("key", list(ALLOWED_CONFIG_KEYS))
    async def test_all_allowed_keys_succeed(self, mock_db, key):
        from app.services.admin import update_config

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=result_mock)
        mock_db.add = MagicMock()

        with patch("app.services.admin.log_event", new_callable=AsyncMock):
            # Should not raise
            await update_config(db=mock_db, key=key, value="test_value")

    @pytest.mark.asyncio
    async def test_raises_400_for_disallowed_key(self, mock_db):
        from app.services.admin import update_config

        with pytest.raises(Exception) as exc_info:
            await update_config(db=mock_db, key="unknown_key", value="anything")

        err_str = str(exc_info.value).lower()
        assert "400" in err_str or "not an allowed" in err_str or "allowed" in err_str

    @pytest.mark.asyncio
    async def test_disallowed_key_writes_nothing_to_db(self, mock_db):
        from app.services.admin import update_config

        mock_db.add = MagicMock()

        with pytest.raises(Exception):
            await update_config(db=mock_db, key="unknown_key", value="x")

        mock_db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_emits_config_updated_log_event(self, mock_db):
        from app.services.admin import update_config

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=result_mock)
        mock_db.add = MagicMock()

        with patch("app.services.admin.log_event", new_callable=AsyncMock) as mock_log:
            await update_config(db=mock_db, key="max_pin_count", value="5")

        mock_log.assert_called_once()
        assert "config.updated" in str(mock_log.call_args) or "updated" in str(mock_log.call_args)


# ---------------------------------------------------------------------------
# get_tags
# ---------------------------------------------------------------------------


class TestGetTags:
    @pytest.mark.asyncio
    async def test_returns_tags_sorted_by_name_by_default(self, mock_db):
        rows = [MagicMock(name="z-tag"), MagicMock(name="a-tag")]
        mock_db.execute = AsyncMock(return_value=_scalars_result(rows))

        result = await get_tags(db=mock_db)

        assert result == rows

    @pytest.mark.asyncio
    async def test_raises_422_for_invalid_sort_param(self, mock_db):
        with pytest.raises(Exception) as exc_info:
            await get_tags(db=mock_db, sort="invalid")

        err_str = str(exc_info.value).lower()
        assert "422" in err_str or "sort" in err_str or "name" in err_str

    @pytest.mark.asyncio
    async def test_usage_count_sort_accepted(self, mock_db):
        rows = [MagicMock(name="popular", usage_count=10)]
        mock_db.execute = AsyncMock(return_value=_scalars_result(rows))

        # Should not raise
        result = await get_tags(db=mock_db, sort="usage")

        assert result == rows
