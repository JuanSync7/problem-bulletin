"""Live-Postgres tests for the admin / categories / tags services.

Rewritten in v2.10-WP04b.  The legacy v1 file mocked db.execute/get and
called the services with mock objects against signatures the production
code never honoured (e.g. ``search_users(db, q=...)`` vs prod
``(db, query)``; ``resolve_flag(flag_id, resolution_note=, resolved_by=)``
vs prod ``(flag_id, admin_id, note)``).  These tests target the real
service surface with the live ``db`` session fixture.

Service contracts pinned here
-----------------------------
- ``search_users(db, query)``    -> list[User], ILIKE on email + display_name
- ``update_user_role(db, user_id, new_role)`` -> User, 404 on missing
- ``update_user_status(db, user_id, is_active)`` -> User, 404 on missing
- ``create_category(db, name)`` -> Category; sort_order = max+1 starting at 0
- ``soft_delete_category(db, category_id: str)`` -> None, 409 if FKs, 404 missing
- ``rename_tag(db, tag_id, new_name)`` -> Tag, 409 on dup, 404 missing
- ``delete_tag(db, tag_id)`` -> None, 404 missing
- ``merge_tags(db, source_id, target_id)`` -> Tag, 404 missing, error if same
- ``resolve_flag(db, flag_id, admin_id, note)`` -> Flag
- ``de_anonymize(db, problem_id, admin_id)`` -> {"author_id": UUID}
- ``get_config(db)`` -> list[AppConfig]
- ``update_config(db, key, value)`` -> AppConfig (allowlist enforced)
- ``get_tags(db, sort='name', q=None)`` -> list[dict]; unknown sort silently
  falls back to name order (no 422)
"""
from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from app.exceptions import ValidationError as DomainValidationError
from app.models.app_config import AppConfig
from app.services.admin import (
    de_anonymize,
    get_config,
    resolve_flag,
    search_users,
    update_config,
    update_user_role,
    update_user_status,
)
from app.services.categories import (
    CategoryInUseError,
    CategoryNotFoundError,
    create_category,
    soft_delete_category,
)
from app.services.tags import (
    TagMergeError,
    TagNameConflictError,
    TagNotFoundError,
    delete_tag,
    get_tags,
    merge_tags,
    rename_tag,
)
from tests.helpers.seed_agent_account import seed_user
from tests.helpers.seed_problem import seed_problem, seed_tag


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Small test-local helpers
# ---------------------------------------------------------------------------

async def _seed_flag(
    db,
    *,
    reporter_id,
    content_type: str = "problem",
    content_id=None,
    reason: str = "spam",
    status: str = "pending",
) -> uuid.UUID:
    """INSERT a row into ``flags`` and return its id."""
    fid = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO flags "
            "(id, content_type, content_id, reporter_id, reason, status) "
            "VALUES (:id, :ct, :cid, :rid, :rsn, :st)"
        ),
        {
            "id": fid,
            "ct": content_type,
            "cid": content_id or uuid.uuid4(),
            "rid": reporter_id,
            "rsn": reason,
            "st": status,
        },
    )
    return fid


async def _count_audit_for(db, problem_id) -> int:
    res = await db.execute(
        text("SELECT count(*) FROM audit_logs WHERE target_id = :p AND target_type='problem'"),
        {"p": problem_id},
    )
    return int(res.scalar() or 0)


# ===========================================================================
# search_users
# ===========================================================================

class TestSearchUsers:
    async def test_returns_matching_users_by_display_name(self, db):
        token = uuid.uuid4().hex[:8]
        await seed_user(db, display_name=f"Alice-{token}", handle=f"al_{token}")
        await db.flush()
        out = await search_users(db, f"Alice-{token}")
        assert any(u.display_name == f"Alice-{token}" for u in out)

    async def test_returns_matching_users_by_email(self, db):
        token = uuid.uuid4().hex[:8]
        await seed_user(db, email=f"u-{token}@corp.test", handle=f"em_{token}")
        await db.flush()
        out = await search_users(db, f"u-{token}@corp.test")
        assert any(u.email == f"u-{token}@corp.test" for u in out)

    async def test_no_query_param_returns_all_users(self, db):
        u1 = await seed_user(db)
        u2 = await seed_user(db)
        await db.flush()
        out = await search_users(db, None)
        ids = {u.id for u in out}
        assert u1 in ids and u2 in ids

    async def test_empty_q_returns_all_users(self, db):
        """Empty string is falsy in the service; treated like "no filter"."""
        u = await seed_user(db)
        await db.flush()
        out = await search_users(db, "")
        assert u in {x.id for x in out}

    async def test_no_matches_returns_empty_list(self, db):
        out = await search_users(db, f"nope_{uuid.uuid4().hex}")
        assert out == []


# ===========================================================================
# update_user_role
# ===========================================================================

class TestUpdateUserRole:
    async def test_updates_role_field(self, db):
        uid = await seed_user(db, role="user")
        await db.flush()
        user = await update_user_role(db, uid, "admin")
        assert user.role == "admin"

    async def test_emits_log_event_role_changed(self, db, caplog):
        uid = await seed_user(db, role="user")
        await db.flush()
        with caplog.at_level("INFO", logger="aion.events"):
            await update_user_role(db, uid, "admin")
        # log_event emits via the ``aion.events`` logger; at minimum a record
        # exists and references the event_type.
        msg = " ".join(r.message + " " + str(getattr(r, "event_type", "")) for r in caplog.records)
        assert "user.role_changed" in msg or "role_changed" in msg

    async def test_raises_404_for_nonexistent_user(self, db):
        with pytest.raises(HTTPException) as exc:
            await update_user_role(db, uuid.uuid4(), "admin")
        assert exc.value.status_code == 404


# ===========================================================================
# update_user_status
# ===========================================================================

class TestUpdateUserStatus:
    async def test_deactivates_user(self, db):
        uid = await seed_user(db, is_active=True)
        await db.flush()
        user = await update_user_status(db, uid, False)
        assert user.is_active is False

    async def test_reactivates_user(self, db):
        uid = await seed_user(db, is_active=False)
        await db.flush()
        user = await update_user_status(db, uid, True)
        assert user.is_active is True

    async def test_emits_status_changed_log_event(self, db, caplog):
        uid = await seed_user(db)
        await db.flush()
        with caplog.at_level("INFO", logger="aion.events"):
            await update_user_status(db, uid, False)
        msg = " ".join(r.message + " " + str(getattr(r, "event_type", "")) for r in caplog.records)
        assert "status_changed" in msg

    async def test_raises_404_for_nonexistent_user(self, db):
        with pytest.raises(HTTPException) as exc:
            await update_user_status(db, uuid.uuid4(), False)
        assert exc.value.status_code == 404


# ===========================================================================
# create_category
# ===========================================================================

class TestCreateCategory:
    async def test_sort_order_zero_when_table_empty(self, db):
        """First category in a clean DB gets ``sort_order=0``.

        Production uses ``max+1`` with ``coalesce(MAX, -1)``; if there is
        already content in the dev DB we can't claim ``=0``, only that
        sequential creates increment by 1 inside this TX.
        """
        # Snapshot current max so we know the expected next value.
        res = await db.execute(text(
            "SELECT COALESCE(MAX(sort_order), -1) FROM categories WHERE deleted_at IS NULL"
        ))
        max_before = int(res.scalar())
        cat = await create_category(db, f"Cat-{uuid.uuid4().hex[:6]}")
        # The service returns max+1.
        assert cat.sort_order == max_before + 1

    async def test_sequential_creates_increment_sort_order(self, db):
        """Two sequential creates must yield consecutive sort_order values."""
        a = await create_category(db, f"A-{uuid.uuid4().hex[:6]}")
        b = await create_category(db, f"B-{uuid.uuid4().hex[:6]}")
        assert b.sort_order == a.sort_order + 1


# ===========================================================================
# soft_delete_category
# ===========================================================================

class TestSoftDeleteCategory:
    async def test_sets_deleted_at_when_no_problems(self, db):
        cat = await create_category(db, f"Del-{uuid.uuid4().hex[:6]}")
        await db.flush()
        await soft_delete_category(db, str(cat.id))
        # Re-read to check deleted_at.
        res = await db.execute(
            text("SELECT deleted_at FROM categories WHERE id = :id"),
            {"id": cat.id},
        )
        assert res.scalar() is not None

    async def test_raises_error_when_problems_reference_category(self, db):
        cat = await create_category(db, f"Used-{uuid.uuid4().hex[:6]}")
        await seed_problem(db, category_id=cat.id)
        await db.flush()
        with pytest.raises(CategoryInUseError):
            await soft_delete_category(db, str(cat.id))

    async def test_raises_404_for_nonexistent_category(self, db):
        with pytest.raises(CategoryNotFoundError):
            await soft_delete_category(db, str(uuid.uuid4()))


# ===========================================================================
# rename_tag
# ===========================================================================

class TestRenameTag:
    async def test_renames_tag_successfully(self, db):
        tid = await seed_tag(db, name=f"old-{uuid.uuid4().hex[:6]}")
        await db.flush()
        new_name = f"new-{uuid.uuid4().hex[:6]}"
        tag = await rename_tag(db, tid, new_name)
        assert tag.name == new_name

    async def test_self_rename_succeeds(self, db):
        """Renaming to the same name is a no-op (no 409)."""
        name = f"self-{uuid.uuid4().hex[:6]}"
        tid = await seed_tag(db, name=name)
        await db.flush()
        tag = await rename_tag(db, tid, name)
        assert tag.name == name

    async def test_raises_404_for_nonexistent_tag(self, db):
        with pytest.raises(TagNotFoundError):
            await rename_tag(db, uuid.uuid4(), "whatever")


# ===========================================================================
# delete_tag
# ===========================================================================

class TestDeleteTag:
    async def test_raises_404_for_nonexistent_tag(self, db):
        with pytest.raises(TagNotFoundError):
            await delete_tag(db, uuid.uuid4())


# ===========================================================================
# merge_tags
# ===========================================================================

class TestMergeTags:
    async def test_merges_unique_problems_to_target(self, db):
        src = await seed_tag(db, name=f"src-{uuid.uuid4().hex[:6]}")
        tgt = await seed_tag(db, name=f"tgt-{uuid.uuid4().hex[:6]}")
        pid = await seed_problem(db)
        # Attach src to a problem.
        await db.execute(
            text("INSERT INTO problem_tags (problem_id, tag_id) VALUES (:p, :t)"),
            {"p": pid, "t": src},
        )
        await db.flush()

        result = await merge_tags(db, src, tgt)
        assert result.id == tgt

        # Problem is now tagged with target, source is gone.
        res = await db.execute(
            text("SELECT tag_id FROM problem_tags WHERE problem_id = :p"),
            {"p": pid},
        )
        tag_ids = {r[0] for r in res.all()}
        assert tgt in tag_ids
        assert src not in tag_ids

        # Source tag row deleted.
        res = await db.execute(text("SELECT id FROM tags WHERE id = :id"), {"id": src})
        assert res.scalar_one_or_none() is None

    async def test_merge_with_no_source_problems_still_deletes_source(self, db):
        src = await seed_tag(db, name=f"empty-{uuid.uuid4().hex[:6]}")
        tgt = await seed_tag(db, name=f"tgt2-{uuid.uuid4().hex[:6]}")
        await db.flush()
        await merge_tags(db, src, tgt)
        res = await db.execute(text("SELECT id FROM tags WHERE id = :id"), {"id": src})
        assert res.scalar_one_or_none() is None

    async def test_raises_404_for_nonexistent_source(self, db):
        tgt = await seed_tag(db, name=f"only-{uuid.uuid4().hex[:6]}")
        await db.flush()
        with pytest.raises(TagNotFoundError):
            await merge_tags(db, uuid.uuid4(), tgt)

    async def test_raises_404_for_nonexistent_target(self, db):
        src = await seed_tag(db, name=f"lone-{uuid.uuid4().hex[:6]}")
        await db.flush()
        with pytest.raises(TagNotFoundError):
            await merge_tags(db, src, uuid.uuid4())


# ===========================================================================
# resolve_flag
# ===========================================================================

class TestResolveFlag:
    async def test_sets_flag_resolved_status(self, db):
        reporter = await seed_user(db)
        admin = await seed_user(db, role="admin")
        fid = await _seed_flag(db, reporter_id=reporter)
        await db.flush()
        flag = await resolve_flag(db, fid, admin, "handled")
        assert flag.status == "resolved"
        assert flag.resolution_note == "handled"
        assert flag.resolved_by == admin

    async def test_emits_flag_resolved_log_event(self, db, caplog):
        reporter = await seed_user(db)
        admin = await seed_user(db, role="admin")
        fid = await _seed_flag(db, reporter_id=reporter)
        await db.flush()
        with caplog.at_level("INFO", logger="aion.events"):
            await resolve_flag(db, fid, admin, "ok")
        msg = " ".join(r.message + " " + str(getattr(r, "event_type", "")) for r in caplog.records)
        assert "flag.resolved" in msg or "resolved" in msg

    async def test_raises_404_for_nonexistent_flag(self, db):
        with pytest.raises(HTTPException) as exc:
            await resolve_flag(db, uuid.uuid4(), uuid.uuid4(), "n/a")
        assert exc.value.status_code == 404


# ===========================================================================
# de_anonymize
# ===========================================================================

class TestDeAnonymize:
    async def test_writes_audit_log_before_returning_author_id(self, db):
        author = await seed_user(db)
        admin = await seed_user(db, role="admin")
        pid = await seed_problem(db, author_id=author, is_anonymous=True)
        await db.flush()

        before = await _count_audit_for(db, pid)
        result = await de_anonymize(db, pid, admin)
        after = await _count_audit_for(db, pid)

        assert result == {"author_id": author}
        assert after == before + 1

    async def test_flush_called_before_returning(self, db):
        """After the call the audit row is visible within the same TX."""
        author = await seed_user(db)
        admin = await seed_user(db, role="admin")
        pid = await seed_problem(db, author_id=author, is_anonymous=True)
        await db.flush()
        await de_anonymize(db, pid, admin)
        # If flush had not been called the audit insert would still be in
        # the pending unit-of-work and the SELECT here would see 0.
        assert await _count_audit_for(db, pid) >= 1

    async def test_emits_de_anonymize_log_event(self, db, caplog):
        author = await seed_user(db)
        admin = await seed_user(db, role="admin")
        pid = await seed_problem(db, author_id=author, is_anonymous=True)
        await db.flush()
        with caplog.at_level("INFO", logger="aion.events"):
            await de_anonymize(db, pid, admin)
        msg = " ".join(r.message + " " + str(getattr(r, "event_type", "")) for r in caplog.records)
        assert "de_anonymize" in msg or "admin.de_anonymize" in msg

    async def test_raises_400_when_problem_not_anonymous(self, db):
        author = await seed_user(db)
        admin = await seed_user(db, role="admin")
        pid = await seed_problem(db, author_id=author, is_anonymous=False)
        await db.flush()
        with pytest.raises(HTTPException) as exc:
            await de_anonymize(db, pid, admin)
        assert exc.value.status_code == 400

    async def test_raises_404_for_nonexistent_problem(self, db):
        with pytest.raises(HTTPException) as exc:
            await de_anonymize(db, uuid.uuid4(), uuid.uuid4())
        assert exc.value.status_code == 404

    async def test_second_call_writes_second_audit_log_entry(self, db):
        """No idempotency guard — two calls write two audit entries."""
        author = await seed_user(db)
        admin = await seed_user(db, role="admin")
        pid = await seed_problem(db, author_id=author, is_anonymous=True)
        await db.flush()

        before = await _count_audit_for(db, pid)
        await de_anonymize(db, pid, admin)
        await de_anonymize(db, pid, admin)
        after = await _count_audit_for(db, pid)
        assert after == before + 2


# ===========================================================================
# get_tags
# ===========================================================================

class TestGetTags:
    async def test_returns_tags_sorted_by_name_by_default(self, db):
        # Use sortable names that won't collide with pre-existing rows.
        token = uuid.uuid4().hex[:6]
        await seed_tag(db, name=f"zzz-{token}")
        await seed_tag(db, name=f"aaa-{token}")
        await db.flush()

        out = await get_tags(db, sort="name", q=token)
        names = [t["name"] for t in out]
        assert names == sorted(names)
        assert names[0].startswith(f"aaa-")

    async def test_raises_422_for_invalid_sort_param(self, db):
        """Strict service-layer contract (v2.11-WP04 A7).

        WP04b rewrote this test to pin a permissive fallback because
        production silently coerced unknown sorts to ``name``.  v2.11-WP04
        restores the strict contract: the service raises
        :class:`ValidationError` on an unknown sort.  The route already
        returns 422 before reaching the service, so HTTP behaviour is
        unchanged; this guard now also protects direct service callers
        (MCP, scripts, background jobs).
        """
        from app.exceptions import ValidationError as DomainValidationError

        token = uuid.uuid4().hex[:6]
        await seed_tag(db, name=f"bb-{token}")
        await seed_tag(db, name=f"aa-{token}")
        await db.flush()

        with pytest.raises(DomainValidationError):
            await get_tags(db, sort="not-a-real-sort", q=token)

    async def test_usage_count_sort_accepted(self, db):
        """``sort=usage`` runs and yields a ``usage_count`` key on each row."""
        token = uuid.uuid4().hex[:6]
        popular = await seed_tag(db, name=f"pop-{token}")
        unused = await seed_tag(db, name=f"unused-{token}")
        pid = await seed_problem(db)
        await db.execute(
            text("INSERT INTO problem_tags (problem_id, tag_id) VALUES (:p, :t)"),
            {"p": pid, "t": popular},
        )
        await db.flush()

        out = await get_tags(db, sort="usage", q=token)
        # Each result must have usage_count populated.
        for row in out:
            assert "usage_count" in row
        # The popular tag should appear before the unused one in the slice.
        names = [t["name"] for t in out]
        assert names.index(f"pop-{token}") < names.index(f"unused-{token}")


# ===========================================================================
# Previously-passing (non-deferred) tests, ported to live DB so they keep
# exercising the public contract end-to-end.
# ===========================================================================

class TestCreateCategoryExtras:
    async def test_auto_generates_slug(self, db):
        cat = await create_category(db, "RTL Design")
        assert cat.slug == "rtl-design"

    async def test_sort_order_increments_from_existing_max(self, db):
        # Force an existing row with sort_order=4 so MAX is well-known.
        a = await create_category(db, f"X-{uuid.uuid4().hex[:6]}")
        # Bump its sort_order to a known sentinel.
        await db.execute(
            text("UPDATE categories SET sort_order = 4 WHERE id = :id"),
            {"id": a.id},
        )
        await db.flush()
        b = await create_category(db, f"Y-{uuid.uuid4().hex[:6]}")
        assert b.sort_order == 5

    async def test_slugify_strips_special_characters(self, db):
        cat = await create_category(db, f"EDA Tools & Flows-{uuid.uuid4().hex[:4]}!")
        assert "&" not in cat.slug and "!" not in cat.slug
        assert cat.slug.startswith("eda-tools-flows-")

    async def test_slugify_trims_leading_trailing_spaces(self, db):
        cat = await create_category(db, f"  trimme-{uuid.uuid4().hex[:6]}  ")
        assert not cat.slug.startswith("-")
        assert not cat.slug.endswith("-")


class TestSoftDeleteCategoryExtras:
    async def test_deleted_at_unchanged_when_blocked(self, db):
        cat = await create_category(db, f"Block-{uuid.uuid4().hex[:6]}")
        await seed_problem(db, category_id=cat.id)
        await db.flush()
        with pytest.raises(CategoryInUseError):
            await soft_delete_category(db, str(cat.id))
        res = await db.execute(
            text("SELECT deleted_at FROM categories WHERE id = :id"),
            {"id": cat.id},
        )
        assert res.scalar() is None


class TestRenameTagExtras:
    async def test_raises_error_on_name_collision(self, db):
        token = uuid.uuid4().hex[:6]
        a = await seed_tag(db, name=f"taken-{token}")
        b = await seed_tag(db, name=f"other-{token}")
        await db.flush()
        with pytest.raises(TagNameConflictError):
            await rename_tag(db, b, f"taken-{token}")


class TestDeleteTagExtras:
    async def test_hard_deletes_tag_and_problem_tag_rows(self, db):
        tid = await seed_tag(db, name=f"del-{uuid.uuid4().hex[:6]}")
        pid = await seed_problem(db)
        await db.execute(
            text("INSERT INTO problem_tags (problem_id, tag_id) VALUES (:p, :t)"),
            {"p": pid, "t": tid},
        )
        await db.flush()

        await delete_tag(db, tid)
        # Tag row gone.
        res = await db.execute(text("SELECT id FROM tags WHERE id = :id"), {"id": tid})
        assert res.scalar_one_or_none() is None
        # problem_tags row gone.
        res = await db.execute(
            text("SELECT 1 FROM problem_tags WHERE tag_id = :t"), {"t": tid},
        )
        assert res.scalar_one_or_none() is None


class TestMergeTagsExtras:
    async def test_on_conflict_do_nothing_for_duplicate_associations(self, db):
        """If both src and tgt already tag the same problem, the merge is a no-op
        on that pair (ON CONFLICT DO NOTHING) and the source row is removed."""
        src = await seed_tag(db, name=f"dsrc-{uuid.uuid4().hex[:6]}")
        tgt = await seed_tag(db, name=f"dtgt-{uuid.uuid4().hex[:6]}")
        pid = await seed_problem(db)
        await db.execute(
            text("INSERT INTO problem_tags (problem_id, tag_id) VALUES (:p, :s), (:p, :t)"),
            {"p": pid, "s": src, "t": tgt},
        )
        await db.flush()

        # Should NOT raise IntegrityError.
        await merge_tags(db, src, tgt)
        res = await db.execute(text("SELECT id FROM tags WHERE id = :id"), {"id": src})
        assert res.scalar_one_or_none() is None

    async def test_raises_400_when_source_equals_target(self, db):
        same = uuid.uuid4()
        with pytest.raises(TagMergeError):
            await merge_tags(db, same, same)


class TestDeAnonymizeExtras:
    async def test_no_audit_log_written_when_not_anonymous(self, db):
        author = await seed_user(db)
        admin = await seed_user(db, role="admin")
        pid = await seed_problem(db, author_id=author, is_anonymous=False)
        await db.flush()

        before = await _count_audit_for(db, pid)
        with pytest.raises(HTTPException):
            await de_anonymize(db, pid, admin)
        after = await _count_audit_for(db, pid)
        assert after == before


# ---------------------------------------------------------------------------
# Config service
# ---------------------------------------------------------------------------

class TestGetConfig:
    async def test_returns_all_config_rows_alphabetically(self, db):
        # Insert two known keys.
        key_a = "auto_watch_default_level"
        key_b = "max_pin_count"
        await db.execute(
            text(
                "INSERT INTO app_config (key, value) VALUES (:k, :v) "
                "ON CONFLICT (key) DO NOTHING"
            ),
            {"k": key_a, "v": "all_activity"},
        )
        await db.execute(
            text(
                "INSERT INTO app_config (key, value) VALUES (:k, :v) "
                "ON CONFLICT (key) DO NOTHING"
            ),
            {"k": key_b, "v": "5"},
        )
        await db.flush()

        out = await get_config(db)
        keys = [c.key for c in out]
        assert keys == sorted(keys)
        assert key_a in keys and key_b in keys


class TestUpdateConfig:
    async def test_updates_existing_allowed_key(self, db):
        await db.execute(
            text(
                "INSERT INTO app_config (key, value) VALUES ('max_pin_count', '3') "
                "ON CONFLICT (key) DO UPDATE SET value = excluded.value"
            )
        )
        await db.flush()
        cfg = await update_config(db, "max_pin_count", "10")
        assert cfg.value == "10"

    async def test_inserts_new_allowed_key(self, db):
        await db.execute(text("DELETE FROM app_config WHERE key = 'claim_expiry_days'"))
        await db.flush()
        cfg = await update_config(db, "claim_expiry_days", "30")
        assert cfg.value == "30"

    @pytest.mark.parametrize(
        "key",
        ["max_pin_count", "claim_expiry_days", "magic_link_ttl_minutes",
         "auto_watch_default_level"],
    )
    async def test_all_allowed_keys_succeed(self, db, key):
        # Either insert or update — both should succeed without raising.
        cfg = await update_config(db, key, "v")
        assert cfg.key == key

    async def test_raises_400_for_disallowed_key(self, db):
        with pytest.raises(HTTPException) as exc:
            await update_config(db, "unknown_key", "anything")
        assert exc.value.status_code == 400

    async def test_disallowed_key_writes_nothing_to_db(self, db):
        before_res = await db.execute(
            text("SELECT count(*) FROM app_config WHERE key = 'unknown_key'")
        )
        before = int(before_res.scalar() or 0)
        with pytest.raises(HTTPException):
            await update_config(db, "unknown_key", "v")
        after_res = await db.execute(
            text("SELECT count(*) FROM app_config WHERE key = 'unknown_key'")
        )
        assert int(after_res.scalar() or 0) == before

    async def test_emits_config_updated_log_event(self, db, caplog):
        with caplog.at_level("INFO", logger="aion.events"):
            await update_config(db, "max_pin_count", "7")
        msg = " ".join(r.message + " " + str(getattr(r, "event_type", "")) for r in caplog.records)
        assert "config.updated" in msg or "config" in msg


# ===========================================================================
# v2.11-WP03 — service-layer input validation + audit-actor consistency
# ===========================================================================

class TestUpdateUserRoleRoleValidation:
    """v2.11-WP03 G1/G2: service layer validates ``new_role`` against the
    canonical ``UserRole`` enum.  Previously the service wrote whatever
    string the caller passed; only the pydantic route schema defended
    against garbage, leaving background-job / agent callers exposed.
    """

    async def test_rejects_unknown_role_with_validation_error(self, db):
        uid = await seed_user(db, role="user")
        await db.flush()
        with pytest.raises(DomainValidationError) as exc:
            await update_user_role(db, uid, "totally_invalid")
        assert exc.value.fields[0]["name"] == "role"

    async def test_accepts_canonical_admin_role(self, db):
        uid = await seed_user(db, role="user")
        await db.flush()
        user = await update_user_role(db, uid, "admin")
        assert user.role == "admin"

    async def test_accepts_canonical_user_role(self, db):
        uid = await seed_user(db, role="admin")
        await db.flush()
        user = await update_user_role(db, uid, "user")
        assert user.role == "user"


class TestUpdateConfigAuditActor:
    """v2.11-WP03 G3: ``update_config`` must record the *caller's principal
    id* in the audit ``user_id`` slot — not a literal ``"admin"`` and not
    the config key being mutated.
    """

    async def test_log_event_uses_actor_id_not_literal_admin(self, db, caplog):
        admin = await seed_user(db, role="admin")
        await db.flush()
        with caplog.at_level("INFO", logger="aion.events"):
            await update_config(db, "max_pin_count", "9", actor_id=admin)
        # Find the config.updated record and inspect the user_id field
        # threaded through extra_data.
        records = [
            r for r in caplog.records
            if "config.updated" in r.message
            or (getattr(r, "extra_data", None) or {}).get("event_type") == "config.updated"
        ]
        assert records, "expected a config.updated log_event record"
        user_ids = {
            (getattr(r, "extra_data", None) or {}).get("user_id") for r in records
        }
        # The user_id must be the actor's UUID string — NOT the literal
        # "admin" sentinel and NOT the config key.
        assert str(admin) in user_ids
        assert "admin" not in user_ids
        assert "max_pin_count" not in user_ids
