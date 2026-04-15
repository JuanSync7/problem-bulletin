from fastapi import APIRouter, Depends

# require_admin is being created by another task — use conditional import
try:
    from app.auth.dependencies import require_admin
except ImportError:
    # Placeholder until auth module is available
    async def require_admin():  # type: ignore[misc]
        pass

admin_router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)

from app.routes.admin import categories, config, moderation, tags, users  # noqa: E402, F401

admin_router.include_router(categories.router)
admin_router.include_router(tags.admin_tag_router)
admin_router.include_router(users.router)
admin_router.include_router(moderation.router)
admin_router.include_router(config.router)
