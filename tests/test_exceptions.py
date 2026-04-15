"""
Tests for app.exceptions — application exception hierarchy.
Derived from: docs/AION_BULLETIN_TEST_DOCS.md — Foundation Layer: app/exceptions.py
"""
import pytest
from starlette.exceptions import HTTPException

from app.exceptions import (
    AppError,
    DuplicateVoteError,
    FileSizeLimitError,
    FileTypeNotAllowedError,
    ForbiddenTransitionError,
    MagicLinkExpiredError,
    PinLimitExceededError,
    TenantMismatchError,
)

# Canonical list of all seven documented subclasses (used for exhaustive checks)
ALL_SUBCLASSES = [
    ForbiddenTransitionError,
    PinLimitExceededError,
    FileSizeLimitError,
    FileTypeNotAllowedError,
    DuplicateVoteError,
    MagicLinkExpiredError,
    TenantMismatchError,
]


# ---------------------------------------------------------------------------
# Base class contract
# ---------------------------------------------------------------------------

class TestAppErrorBase:
    def test_app_error_is_exception(self):
        """REQ: AppError inherits from Exception."""
        assert issubclass(AppError, Exception)

    def test_app_error_is_not_http_exception(self):
        """REQ: AppError is NOT an HTTPException (no HTTP framework leakage)."""
        err = AppError("test message")
        assert not isinstance(err, HTTPException)

    def test_app_error_is_not_subclass_of_http_exception(self):
        """REQ: AppError class is not a subclass of HTTPException."""
        assert not issubclass(AppError, HTTPException)

    def test_app_error_instantiable(self):
        """REQ: AppError can be instantiated directly."""
        err = AppError("something went wrong")
        assert err is not None

    def test_app_error_message_accessible(self):
        """REQ: AppError message is accessible via args."""
        err = AppError("something went wrong")
        assert "something went wrong" in str(err) or err.args[0] == "something went wrong"


# ---------------------------------------------------------------------------
# Subclass hierarchy — all 7 subclasses are instances of AppError
# ---------------------------------------------------------------------------

class TestSubclassHierarchy:
    def test_forbidden_transition_error_is_app_error(self):
        """REQ: ForbiddenTransitionError is an instance of AppError."""
        err = ForbiddenTransitionError("open", "accepted")
        assert isinstance(err, AppError)

    def test_pin_limit_exceeded_error_is_app_error(self):
        """REQ: PinLimitExceededError is an instance of AppError."""
        err = PinLimitExceededError()
        assert isinstance(err, AppError)

    def test_file_size_limit_error_is_app_error(self):
        """REQ: FileSizeLimitError is an instance of AppError."""
        err = FileSizeLimitError(5_000_000, 2_000_000)
        assert isinstance(err, AppError)

    def test_file_type_not_allowed_error_is_app_error(self):
        """REQ: FileTypeNotAllowedError is an instance of AppError."""
        err = FileTypeNotAllowedError("application/exe", "virus.exe")
        assert isinstance(err, AppError)

    def test_duplicate_vote_error_is_app_error(self):
        """REQ: DuplicateVoteError is an instance of AppError."""
        err = DuplicateVoteError()
        assert isinstance(err, AppError)

    def test_magic_link_expired_error_is_app_error(self):
        """REQ: MagicLinkExpiredError is an instance of AppError."""
        err = MagicLinkExpiredError()
        assert isinstance(err, AppError)

    def test_tenant_mismatch_error_is_app_error(self):
        """REQ: TenantMismatchError is an instance of AppError."""
        err = TenantMismatchError()
        assert isinstance(err, AppError)

    @pytest.mark.parametrize("subclass", ALL_SUBCLASSES)
    def test_all_subclasses_are_subclasses_of_app_error(self, subclass):
        """REQ (exhaustive): issubclass check for every documented subclass."""
        assert issubclass(subclass, AppError)

    def test_all_seven_subclasses_exist(self):
        """REQ (boundary): Exactly the seven documented subclasses are importable."""
        # If any import above failed, this test would never reach here.
        assert len(ALL_SUBCLASSES) == 7


# ---------------------------------------------------------------------------
# Structured fields — ForbiddenTransitionError
# ---------------------------------------------------------------------------

class TestForbiddenTransitionError:
    def test_stores_current_and_target(self):
        """REQ: ForbiddenTransitionError stores .current and .target fields."""
        err = ForbiddenTransitionError("open", "accepted")
        assert err.current == "open"
        assert err.target == "accepted"

    def test_current_equals_target_valid_instantiation(self):
        """REQ (boundary): current == target is a valid instantiation; no transition-graph validation."""
        err = ForbiddenTransitionError("open", "open")
        assert err.current == "open"
        assert err.target == "open"

    def test_missing_args_raises_type_error(self):
        """REQ: ForbiddenTransitionError() with no args raises TypeError."""
        with pytest.raises(TypeError):
            ForbiddenTransitionError()

    def test_missing_one_arg_raises_type_error(self):
        """REQ: ForbiddenTransitionError('open') missing target raises TypeError."""
        with pytest.raises(TypeError):
            ForbiddenTransitionError("open")

    def test_caught_by_except_app_error(self):
        """REQ: ForbiddenTransitionError is caught by 'except AppError'."""
        caught = False
        try:
            raise ForbiddenTransitionError("open", "accepted")
        except AppError:
            caught = True
        assert caught

    def test_caught_by_own_type(self):
        """REQ: ForbiddenTransitionError is caught by its own except clause."""
        caught = False
        try:
            raise ForbiddenTransitionError("open", "accepted")
        except ForbiddenTransitionError:
            caught = True
        assert caught


# ---------------------------------------------------------------------------
# Structured fields — FileSizeLimitError
# ---------------------------------------------------------------------------

class TestFileSizeLimitError:
    def test_stores_file_size_and_max_size(self):
        """REQ: FileSizeLimitError stores .file_size and .max_size fields."""
        err = FileSizeLimitError(5_000_000, 2_000_000)
        assert err.file_size == 5_000_000
        assert err.max_size == 2_000_000

    def test_missing_args_raises_type_error(self):
        """REQ: FileSizeLimitError() with no args raises TypeError."""
        with pytest.raises(TypeError):
            FileSizeLimitError()

    def test_caught_by_except_app_error(self):
        """REQ: FileSizeLimitError is caught by 'except AppError'."""
        caught = False
        try:
            raise FileSizeLimitError(5_000_000, 2_000_000)
        except AppError:
            caught = True
        assert caught


# ---------------------------------------------------------------------------
# Structured fields — FileTypeNotAllowedError
# ---------------------------------------------------------------------------

class TestFileTypeNotAllowedError:
    def test_stores_content_type_and_filename(self):
        """REQ: FileTypeNotAllowedError stores .content_type and .filename fields."""
        err = FileTypeNotAllowedError("application/exe", "virus.exe")
        assert err.content_type == "application/exe"
        assert err.filename == "virus.exe"

    def test_missing_args_raises_type_error(self):
        """REQ: FileTypeNotAllowedError() with no args raises TypeError."""
        with pytest.raises(TypeError):
            FileTypeNotAllowedError()

    def test_caught_by_except_app_error(self):
        """REQ: FileTypeNotAllowedError is caught by 'except AppError'."""
        caught = False
        try:
            raise FileTypeNotAllowedError("application/exe", "virus.exe")
        except AppError:
            caught = True
        assert caught


# ---------------------------------------------------------------------------
# No-argument exceptions — pass-body subclasses
# ---------------------------------------------------------------------------

class TestNoArgExceptions:
    @pytest.mark.parametrize("exc_cls", [
        PinLimitExceededError,
        DuplicateVoteError,
        MagicLinkExpiredError,
        TenantMismatchError,
    ])
    def test_instantiable_with_no_arguments(self, exc_cls):
        """REQ: pass-body exceptions instantiate with no arguments."""
        err = exc_cls()
        assert err is not None

    @pytest.mark.parametrize("exc_cls", [
        PinLimitExceededError,
        DuplicateVoteError,
        MagicLinkExpiredError,
        TenantMismatchError,
    ])
    def test_is_instance_of_app_error(self, exc_cls):
        """REQ: pass-body exceptions are instances of AppError."""
        err = exc_cls()
        assert isinstance(err, AppError)


# ---------------------------------------------------------------------------
# Catch-all except AppError
# ---------------------------------------------------------------------------

class TestCatchAll:
    @pytest.mark.parametrize("exc_cls,args", [
        (ForbiddenTransitionError, ("open", "accepted")),
        (PinLimitExceededError, ()),
        (FileSizeLimitError, (5_000_000, 2_000_000)),
        (FileTypeNotAllowedError, ("image/svg+xml", "bad.svg")),
        (DuplicateVoteError, ()),
        (MagicLinkExpiredError, ()),
        (TenantMismatchError, ()),
    ])
    def test_except_app_error_catches_all_subclasses(self, exc_cls, args):
        """REQ: 'except AppError' catches every documented subclass."""
        caught_type = None
        try:
            raise exc_cls(*args)
        except AppError as e:
            caught_type = type(e)
        assert caught_type is exc_cls

    def test_except_duplicate_vote_does_not_catch_pin_limit(self):
        """REQ: Specific handler does not catch unrelated sibling subclasses."""
        with pytest.raises(PinLimitExceededError):
            try:
                raise PinLimitExceededError()
            except DuplicateVoteError:
                pass  # should NOT be caught here

    def test_except_specific_type_catches_own_class(self):
        """REQ: Specific except clause catches its own exception type."""
        caught = False
        try:
            raise DuplicateVoteError()
        except DuplicateVoteError:
            caught = True
        assert caught


# GAP: No test for exception handler HTTP status code mapping (requires app.main integration)
# GAP: No test for middleware AppError fallback catch (owned by app.main)
