"""Admin router: combines all admin submodules into a single /admin router."""

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, JSONResponse
from starlette.responses import Response

from . import auth, calendar, config, crm, crud_generic, dashboard
from .auth import _admin_enabled
from .config import ApiKeyCreate, ApiKeyCreateResponse, ApiKeyResponse, ApiKeyUpdate
from .crud_generic import _CRUD_MODELS

__all__ = [
    "ApiKeyCreate",
    "ApiKeyCreateResponse",
    "ApiKeyResponse",
    "ApiKeyUpdate",
    "_CRUD_MODELS",
    "router",
]

router = APIRouter(prefix="/admin", tags=["admin"])

# Include all submodule routers
router.include_router(auth.router)
router.include_router(crud_generic.router)
router.include_router(dashboard.router)
router.include_router(crm.router)
router.include_router(calendar.router)
router.include_router(config.router)

_STATIC_DIR = Path(__file__).resolve().parent.parent.parent / "static"


@router.get("", include_in_schema=False, response_model=None)
async def admin_page() -> Response:
    """Sirve el dashboard HTML. Solo en debug."""
    if not _admin_enabled():
        return JSONResponse(status_code=404, content={"detail": "Not found"})

    html_path = _STATIC_DIR / "admin.html"
    if not html_path.exists():
        return JSONResponse(status_code=500, content={"detail": "admin.html missing"})
    return FileResponse(html_path, media_type="text/html")
